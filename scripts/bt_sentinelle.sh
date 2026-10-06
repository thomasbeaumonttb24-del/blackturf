#!/usr/bin/env bash
# Sentinelle de securite BlackTurf — posee le 2026-10-06 (audit securite).
#
# Complement de bt_sante.sh, qui surveille la SANTE et attend volontairement 45 min
# avant d'ecrire. Ici c'est l'inverse : un signe d'intrusion ou d'attaque part
# TOUT DE SUITE (au plus 2 min), une seule fois par heure et par sujet.
#
# Shell pur, hors conteneur : elle doit parler precisement quand l'app se tait.
# Installee dans /usr/local/bin, cron */2. Journal /var/log/bt-sentinelle.log.
# Version de reference : scripts/bt_sentinelle.sh dans le depot.
set -u
set -o pipefail

ENV_FILE=/opt/blackturf/.env
DEPOT=/opt/blackturf
ETAT=/var/lib/bt-sentinelle
LOG=/var/log/bt-sentinelle.log
REPETITION_S=3600
mkdir -p "$ETAT"; chmod 700 "$ETAT"
MAINTENANT=$(date +%s)
ALERTES=()

journal() { echo "$(date -u '+%F %T') $*" >> "$LOG"; }
alerte() { # $1 = cle (anti-repetition), $2 = message
  local f="$ETAT/vu_$(echo "$1" | md5sum | cut -c1-16)" dernier=0
  [ -f "$f" ] && dernier=$(cat "$f" 2>/dev/null || echo 0)
  case "$dernier" in (*[!0-9]*|"") dernier=0 ;; esac
  journal "ALERTE [$1] $2"
  if [ $((MAINTENANT - dernier)) -ge $REPETITION_S ]; then
    ALERTES+=("$2"); echo "$MAINTENANT" > "$f"
  fi
}
# Condition qui doit tenir 2 passages de suite (4 min) avant d'alerter : pour les
# signaux de panne, pas pour les signaux d'intrusion.
deux_fois() { # $1 = cle, $2 = vrai(1)/faux(0) ; retourne 0 si vrai deux fois de suite
  local f="$ETAT/suite_$1"
  if [ "$2" = 1 ]; then
    if [ -f "$f" ]; then return 0; fi
    touch "$f"; return 1
  fi
  rm -f "$f"; return 1
}
db() { docker exec blackturf_db sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -At -c \"$1\"" 2>/dev/null; }

# ── 1. Connexions SSH reussies ───────────────────────────────────────────────
# IP connues : postes de Thomas. Les deploiements GitHub viennent d'IP Azure
# changeantes : une connexion suivie d'un `reset: moving to origin/main` dans les
# 5 min est un deploiement. On juge donc les connexions vieilles de 6 a 30 min.
CONNUES="$ETAT/ip_connues"
[ -f "$CONNUES" ] || printf '37.67.80.149\n81.65.152.46\n90.61.184.236\n127.0.0.1\n' > "$CONNUES"
VUES="$ETAT/ssh_vues"; touch "$VUES"
RESETS=$(cd "$DEPOT" && git reflog --date=unix -50 2>/dev/null | grep "reset: moving to origin" | sed -E 's/.*HEAD@\{([0-9]+)\}.*/\1/')
journalctl -u ssh --since "-30 min" --until "-6 min" -o short-unix --no-pager 2>/dev/null \
  | grep -E "Accepted (publickey|password|keyboard-interactive) for " | while read -r ts reste; do
    ip=$(echo "$reste" | grep -oE "from [0-9a-fA-F:.]+" | cut -d' ' -f2)
    [ -n "$ip" ] || continue
    t=${ts%.*}; cle="$t $ip"
    grep -qxF "$cle" "$VUES" && continue
    echo "$cle" >> "$VUES"
    grep -qxF "$ip" "$CONNUES" && continue
    deploi=0
    for r in $RESETS; do [ "$r" -ge "$t" ] && [ "$r" -le $((t + 300)) ] && deploi=1; done
    [ "$deploi" = 1 ] && continue
    echo "SSH|Connexion SSH root reussie depuis une IP inconnue : <b>$ip</b> a $(date -u -d @"$t" '+%H:%M') UTC, sans deploiement GitHub derriere. Si ce n'est pas toi (nouvelle box, 4G...), c'est une INTRUSION : couper la cle SSH." >> "$ETAT/a_signaler"
  done
tail -n 500 "$VUES" > "$VUES.tmp" && mv "$VUES.tmp" "$VUES"

# ── 2. Fichiers sensibles modifies ──────────────────────────────────────────
EMPREINTES="$ETAT/empreintes"
calc_empreintes() {
  {
    sha256sum /root/.ssh/authorized_keys /etc/passwd /etc/shadow /etc/group /etc/sudoers \
      /etc/ssh/sshd_config /etc/crontab "$ENV_FILE" 2>/dev/null
    sha256sum /etc/sudoers.d/* /etc/ssh/sshd_config.d/* /etc/cron.d/* /home/*/.ssh/authorized_keys 2>/dev/null
    crontab -l 2>/dev/null | sha256sum | sed 's#-$#crontab-root#'
    ls /etc/systemd/system/*.service /etc/systemd/system/*.timer 2>/dev/null | sha256sum | sed 's#-$#unites-systemd#'
    ls /usr/local/bin /usr/local/sbin 2>/dev/null | sha256sum | sed 's#-$#binaires-locaux#'
  } | sort -k2
}
calc_empreintes > "$EMPREINTES.new"
if [ -f "$EMPREINTES" ]; then
  diff <(cat "$EMPREINTES") "$EMPREINTES.new" | grep '^>' | awk '{print $3}' | while read -r f; do
    echo "FICHIER_$f|Fichier systeme sensible MODIFIE : <b>$f</b>. Normal seulement si toi ou Claude venez d'intervenir sur le serveur." >> "$ETAT/a_signaler"
  done
fi
mv "$EMPREINTES.new" "$EMPREINTES"

# Code en production modifie hors deploiement (le deploiement fait reset --hard).
modifs=$(cd "$DEPOT" && git status --porcelain --untracked-files=no 2>/dev/null | head -5 | tr '\n' ' ')
[ -n "$modifs" ] && alerte "code_modifie" "Code de production modifie sur le serveur hors deploiement : <b>$modifs</b>"

# ── 3. Ports en ecoute et conteneurs inattendus ─────────────────────────────
PORTS=$(ss -tlnH 2>/dev/null | awk '{print $4}' | sort -u)
if [ -f "$ETAT/ports" ]; then
  nouveaux=$(comm -13 "$ETAT/ports" <(echo "$PORTS") | tr '\n' ' ')
  [ -n "${nouveaux// /}" ] && alerte "ports_$nouveaux" "Nouveau port en ecoute sur le serveur : <b>$nouveaux</b>"
fi
echo "$PORTS" > "$ETAT/ports"
CONTENEURS=$(docker ps --format '{{.Names}}' | sort)
inconnus=$(echo "$CONTENEURS" | grep -vE '^blackturf_(api|frontend|worker|scheduler|scraper|db|redis|nginx)$' | grep -v '^$' | grep -vE '^(gate|test|verif|tmp)' | tr '\n' ' ')
[ -n "${inconnus// /}" ] && alerte "conteneur_$inconnus" "Conteneur inconnu en marche : <b>$inconnus</b>"
for c in api frontend worker scheduler scraper db redis nginx; do
  etat=$(docker inspect -f '{{.State.Status}}' "blackturf_$c" 2>/dev/null || echo absent)
  if deux_fois "conteneur_$c" "$([ "$etat" != running ] && echo 1 || echo 0)"; then
    alerte "arret_$c" "Service <b>$c</b> hors service (etat : $etat) depuis plus de 2 min."
  fi
done

# ── 4. Comptes : admin et inscriptions ──────────────────────────────────────
admins=$(db "select count(*) from users where is_admin")
case "$admins" in
  1|"") ;;  # vide = base injoignable, traite par bt_sante
  *) alerte "admins_$admins" "Nombre de comptes ADMIN anormal : <b>$admins</b> (attendu : 1, admin@blackturf.fr). Un compte a pu etre promu." ;;
esac
admins_noms=$(db "select string_agg(email, ',') from users where is_admin")
[ -n "$admins_noms" ] && [ "$admins_noms" != "admin@blackturf.fr" ] && \
  alerte "admin_noms_$admins_noms" "Compte admin inattendu : <b>$admins_noms</b>"
inscrits=$(db "select count(*) from users where created_at > now() - interval '10 minutes'")
[ "${inscrits:-0}" -gt 25 ] 2>/dev/null && alerte "inscriptions" "Vague d'inscriptions : <b>$inscrits</b> comptes en 10 min (robots ?)."

# ── 5. Trafic : inondation, force brute, erreurs ────────────────────────────
TRAFIC=$(docker logs --since 5m blackturf_nginx 2>/dev/null)
total=$(echo "$TRAFIC" | grep -c '"' || true)
e5xx=$(echo "$TRAFIC" | awk '$8 ~ /^5[0-9][0-9]$/' | wc -l)
login_ko=$(echo "$TRAFIC" | grep 'POST /api/v1/auth/login' | awk '$8 == 401 || $8 == 400' | wc -l)
top=$(echo "$TRAFIC" | awk '$1 != "172.18.0.1" && $1 != "127.0.0.1" {print $1}' | sort | uniq -c | sort -rn | head -1)
top_n=$(echo "$top" | awk '{print $1+0}'); top_ip=$(echo "$top" | awk '{print $2}')
[ "$total" -gt 4000 ] && alerte "inondation" "Trafic anormal : <b>$total requetes en 5 min</b> (normal : ~250). Attaque par saturation possible."
[ "${top_n:-0}" -gt 800 ] && alerte "ip_$top_ip" "Une seule IP martele le site : <b>$top_ip</b>, $top_n requetes en 5 min."
[ "$login_ko" -gt 40 ] && alerte "force_brute" "Force brute sur la connexion : <b>$login_ko echecs</b> en 5 min."
if deux_fois "5xx" "$([ "$e5xx" -gt 25 ] && echo 1 || echo 0)"; then
  alerte "5xx" "Le site renvoie des erreurs serveur : <b>$e5xx erreurs 5xx</b> en 5 min, deux passages de suite."
fi

# ── 6. fail2ban : campagne de scan ──────────────────────────────────────────
bans=0
for j in blackturf-scanners sshd; do
  n=$(fail2ban-client status "$j" 2>/dev/null | awk -F: '/Total banned/ {gsub(/ /,"",$2); print $2}')
  bans=$((bans + ${n:-0}))
done
if [ -f "$ETAT/bans" ]; then
  delta=$((bans - $(cat "$ETAT/bans")))
  [ "$delta" -gt 15 ] && alerte "campagne_scan" "Campagne de scan en cours : <b>$delta IP bannies</b> en 2 min par fail2ban (elles sont bloquees, rien a faire sauf si ca dure)."
fi
echo "$bans" > "$ETAT/bans"

# ── 7. Disponibilite vue du serveur ─────────────────────────────────────────
code_site=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 --resolve blackturf.fr:443:127.0.0.1 https://blackturf.fr/)
code_api=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 --resolve api.blackturf.fr:443:127.0.0.1 https://api.blackturf.fr/api/v1/health)
if deux_fois "dispo" "$([ "$code_site" != 200 ] || [ "$code_api" != 200 ] && echo 1 || echo 0)"; then
  alerte "dispo" "Site indisponible depuis plus de 2 min : accueil HTTP $code_site, API HTTP $code_api."
fi

# ── 8. Charge machine (minage, saturation) ──────────────────────────────────
charge=$(awk '{print int($1)}' /proc/loadavg); coeurs=$(nproc)
if deux_fois "charge" "$([ "$charge" -gt $((coeurs * 3)) ] && echo 1 || echo 0)"; then
  proc=$(ps -eo pcpu,comm --sort=-pcpu | sed -n 2,4p | tr -s ' ' | tr '\n' ';')
  alerte "charge" "Serveur sature : charge <b>$charge</b> pour $coeurs coeurs. Processus en tete : $proc"
fi

# ── Envoi ───────────────────────────────────────────────────────────────────
if [ -f "$ETAT/a_signaler" ]; then
  while IFS='|' read -r cle msg; do alerte "$cle" "$msg"; done < "$ETAT/a_signaler"
  rm -f "$ETAT/a_signaler"
fi
[ ${#ALERTES[@]} -eq 0 ] && exit 0

cle=$(grep -m1 '^RESEND_API_KEY=' "$ENV_FILE" | cut -d= -f2- | tr -d "\"'\r")
dest=$(grep -m1 '^ADMIN_EMAIL=' "$ENV_FILE" | cut -d= -f2- | tr -d "\"'\r")
exped=$(grep -m1 '^EMAIL_FROM=' "$ENV_FILE" | cut -d= -f2- | tr -d "\"'\r")
corps=""; for a in "${ALERTES[@]}"; do corps="$corps<li>$a</li>"; done
charge_json=$(EXPED="$exped" DEST="$dest" CORPS="$corps" N="${#ALERTES[@]}" python3 -c '
import json, os
print(json.dumps({
  "from": os.environ["EXPED"] or "alerte@blackturf.fr",
  "to": [os.environ["DEST"]],
  "subject": "[BlackTurf] ALERTE SECURITE (" + os.environ["N"] + ")",
  "html": "<h3>Sentinelle de securite BlackTurf</h3><ul>" + os.environ["CORPS"] + "</ul>"
          "<p style=\"color:#666\">Verifiee toutes les 2 min, chaque sujet au plus une fois par heure. "
          "Journal : /var/log/bt-sentinelle.log sur le serveur.</p>",
}))')
code=$(curl -s -o /tmp/bt_sentinelle_resend.out -w '%{http_code}' -X POST https://api.resend.com/emails \
  -H "Authorization: Bearer ${cle}" -H "Content-Type: application/json" -d "$charge_json")
journal "e-mail -> $dest : HTTP $code (${#ALERTES[@]} alerte(s))"
