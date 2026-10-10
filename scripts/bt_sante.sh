#!/usr/bin/env bash
# Sonde de sante BlackTurf — posee le 2026-09-08.
#
# Pourquoi en shell pur et pas dans l'app : une sonde qui depend du conteneur
# api se tait precisement quand il faut qu'elle parle. Elle n'a besoin que de
# docker et de bt_mail_admin.py (Resend puis relais SMTP, cles lues dans le .env).
#
# Installee dans /usr/local/bin, cron */15. Version de reference : ce fichier
# (scripts/bt_sante.sh) ; elle n'etait que sur le serveur jusqu'au 10/10/2026.
#
# Elle ne CORRIGE qu'une seule chose, la seule qui soit sans risque : au-dela de
# 85 % de disque elle declenche la purge du cache de build (script dedie, verrou
# flock, ne touche ni image en service ni volume). Tout le reste, elle le
# signale sans agir.
set -u
set -o pipefail

# Surchargeables pour l essai a blanc (journal et etat jetables).
LOG=${BT_SANTE_LOG:-/var/log/bt-sante.log}
MAILER=${BT_MAIL_ADMIN:-/usr/local/bin/bt_mail_admin.py}
ETAT=${BT_SANTE_ETAT:-/var/lib/bt-sante.etat}
PRUNE=/opt/blackturf/scripts/docker_cache_prune.sh
SEUIL_DISQUE_WARN=80
SEUIL_DISQUE_PURGE=85
SEUIL_DISQUE_CRIT=90
RAM_MIN_MO=400
# Une cote vieille de plus de 12 h n'est anormale QUE le jour : il n'y a aucune
# course entre 23 h et 06 h UTC, et la premiere cote PMU tombe au plus tot 3,65 h
# avant le depart (mediane 12,6 h). Sonder la nuit ne produirait que du bruit.
STALE_H=12
HEURE=$(date -u +%-H)
JOUR_DE_COURSE=0
[ "$HEURE" -ge 8 ] && [ "$HEURE" -le 22 ] && JOUR_DE_COURSE=1

PROBLEMES=""
ajoute() { PROBLEMES="${PROBLEMES}$1"$'\n'; }
journal() { echo "$(date -Is) $1" >> "$LOG"; }

# ── 1. Disque ────────────────────────────────────────────────────────────────
USAGE=$(df --output=pcent / | tail -1 | tr -dc '0-9')
LIBRE=$(df -h --output=avail / | tail -1 | tr -d ' ')
if [ "${USAGE:-0}" -ge "$SEUIL_DISQUE_PURGE" ] && [ -x "$PRUNE" ]; then
  journal "disque ${USAGE}% >= ${SEUIL_DISQUE_PURGE}% : purge automatique du cache de build"
  "$PRUNE" >> "$LOG" 2>&1
  USAGE=$(df --output=pcent / | tail -1 | tr -dc '0-9')
  LIBRE=$(df -h --output=avail / | tail -1 | tr -d ' ')
  journal "disque apres purge : ${USAGE}% (${LIBRE} libres)"
fi
if [ "${USAGE:-0}" -ge "$SEUIL_DISQUE_CRIT" ]; then
  ajoute "CRITIQUE disque : ${USAGE}% utilise, ${LIBRE} libres (purge deja tentee)"
elif [ "${USAGE:-0}" -ge "$SEUIL_DISQUE_WARN" ]; then
  ajoute "ALERTE disque : ${USAGE}% utilise, ${LIBRE} libres"
fi

# ── 2. Memoire ───────────────────────────────────────────────────────────────
DISPO=$(free -m | awk '/^Mem:/ {print $7}')
[ "${DISPO:-9999}" -lt "$RAM_MIN_MO" ] && ajoute "ALERTE memoire : ${DISPO} Mo disponibles (seuil ${RAM_MIN_MO})"

# ── 3. Conteneurs ────────────────────────────────────────────────────────────
for c in blackturf_api blackturf_frontend blackturf_db blackturf_redis blackturf_nginx blackturf_worker blackturf_scheduler blackturf_scraper; do
  etat=$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || echo absent)
  [ "$etat" != "running" ] && ajoute "CRITIQUE conteneur $c : etat=$etat"
done

# ── 4. Unites systemd en echec ───────────────────────────────────────────────
# cloud-init-hotplugd echoue en permanence sur cet hebergeur, sans consequence :
# l'inclure noierait toute vraie panne dans une alerte quotidienne ignoree.
ECHECS=$(systemctl --failed --no-legend --plain 2>/dev/null | awk '{print $1}' | grep -v '^cloud-init-hotplugd' | tr '\n' ' ')
[ -n "${ECHECS// /}" ] && ajoute "ALERTE services en echec : $ECHECS"

# ── 5. Sterilite ET effondrement des daemons de cotes ────────────────────────
# Un daemon de cotes peut tourner, repondre au heartbeat et n'ecrire AUCUNE
# ligne pendant des jours (constate : zeturf 5 jours, oddschecker 22 h).
#
# DEUX controles, parce que la fraicheur seule ne suffit pas : le 08/09 zeturf
# n'ecrivait plus que 10 lignes/jour au lieu de 73 000, tout en restant
# "recent" — une sonde de fraicheur seule l'aurait declare sain pendant des
# jours. On surveille donc aussi le VOLUME face a la mediane des 7 jours.
#
# La source lue est `cotes_bookmakers.scraped_at`, horodatage propre a
# l'ecriture d'une cote, et surtout PAS `participations.updated_at` : cette
# colonne-la bouge des qu'on touche la ligne pour une autre raison et donne de
# fausses fraicheurs (elle a fait dater a tort une panne le 08/09).
#
# On ne sonde que les daemons ACTIFS : un daemon volontairement arrete ne doit
# pas alerter.
if [ "$JOUR_DE_COURSE" = "1" ]; then
  verifie_source() { # $1=unite systemd  $2=valeur de la colonne source  $3=libelle
    systemctl is-active --quiet "$1" || return 0
    local sql lu age jour med
    sql="SELECT COALESCE(ROUND(EXTRACT(EPOCH FROM (now() - max(scraped_at)))/3600), 999),
                -- Fenetre GLISSANTE de 24 h, surtout pas le jour calendaire en
                -- cours : compare a une mediane de journees COMPLETES, un
                -- compteur qui repart de zero a minuit ferait hurler la sonde
                -- tous les matins et on apprendrait a l'ignorer.
                COALESCE((SELECT count(*) FROM cotes_bookmakers
                          WHERE source = '$2' AND scraped_at > now() - interval '24 hours'), 0),
                COALESCE((SELECT ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY n))
                          FROM (SELECT count(*) AS n FROM cotes_bookmakers
                                WHERE source = '$2'
                                  AND scraped_at::date BETWEEN current_date - 7 AND current_date - 1
                                GROUP BY scraped_at::date) q), 0)
         FROM cotes_bookmakers WHERE source = '$2';"
    lu=$(docker exec blackturf_db psql -U blackturf -d blackturf -tAF'|' -c "$sql" 2>/dev/null | tr -d ' ')
    if [ -z "$lu" ]; then
      ajoute "ALERTE $3 : fraicheur illisible (base injoignable ?)"
      return 0
    fi
    age=$(echo "$lu" | cut -d'|' -f1)
    jour=$(echo "$lu" | cut -d'|' -f2)
    med=$(echo "$lu" | cut -d'|' -f3)
    if [ "${age:-999}" -gt "$STALE_H" ]; then
      ajoute "ALERTE $3 sterile : le daemon $1 tourne mais aucune cote ecrite depuis ${age} h"
    elif [ "${med:-0}" -ge 500 ] && [ "$(( ${jour:-0} * 5 ))" -lt "${med:-0}" ]; then
      # Effondrement : moins de 20 % du volume median des 7 jours precedents.
      # Plancher a 500 pour ne pas alerter sur une source deja marginale.
      ajoute "ALERTE $3 effondree : ${jour} cotes sur 24 h contre ${med} en mediane sur 7 jours (daemon $1)"
    fi
    return 0
  }
  verifie_source zeturf-odds      unibet  "cotes ZEturf"
  verifie_source genybet-odds     geny    "cotes GenyBet"
  verifie_source oddschecker-odds bet365  "cotes Oddschecker"
fi

# ── 5b. Oddschecker refuse par l'anti-bot, vu dans le journal du daemon ──────
# Le controle de volume ci-dessus compte sur 24 h glissantes : le 28/09 le
# daemon a ete bloque par Cloudflare de ~08:00 a 17:30, mais quelques cycles
# passaient encore le matin, et l'alerte n'est partie qu'a 17:00 — neuf heures
# de cotes bet365/betfair/ladbrokes perdues. Le journal du daemon, lui, dit
# tout de suite si un cycle a produit : zero cycle utile en 60 min alors que
# les refus s'accumulent = blocage, quel que soit le volume de la veille.
# Les cycles de veille (aucune course dans la fenetre) ne comptent ni pour ni
# contre. Le journal est tourne vers 01:00 : entre 08 et 22 h il ne contient
# que la journee en cours, la comparaison d'heures en texte suffit.
if [ "$JOUR_DE_COURSE" = "1" ] && systemctl is-active --quiet oddschecker-odds \
   && [ -f /var/log/oddschecker-odds.log ]; then
  oc_depuis="[$(date -d '-60 min' +%H:%M:%S)]"
  oc_lu=$(awk -v d="$oc_depuis" '$1 >= d' /var/log/oddschecker-odds.log | awk '
    / cycle courses=/ && !/veille=True/ && !/ lues=0 / { utiles++ }
    /index\.bloque|race\.bloquee/                      { refus++ }
    END { print utiles+0, refus+0 }')
  oc_utiles=${oc_lu% *}
  oc_refus=${oc_lu#* }
  if [ "${oc_utiles:-0}" -eq 0 ] && [ "${oc_refus:-0}" -ge 6 ]; then
    ajoute "ALERTE Oddschecker bloque par l'anti-bot : 0 cycle productif en 60 min, ${oc_refus} refus Cloudflare (journal /var/log/oddschecker-odds.log)"
  fi
fi

# ── 6. Instantane ELO d'avant course ─────────────────────────────────────────
# features.py lit COALESCE(p.elo_avant_global, ch.elo_score_global). Si personne
# n'ecrit l'instantane, le repli prend l'ELO COURANT : sans consequence en direct,
# mais tout recalcul ulterieur des features injecte alors un ELO du futur dans
# l'entrainement. L'ecriture s'est arretee en juillet 2026 et PERSONNE ne l'a vu
# pendant trois mois (couverture 100 % jusqu'en mai, 0 % de juillet a septembre).
# On surveille donc la couverture sur les courses PARTIES dans les 24 dernieres
# heures : seule mesure qui prouve que bt_elo_snapshot.sh a bien tourne A TEMPS.
#
# La borne basse est la DATE D'INSTALLATION du job d'instantane, pas simplement
# « il y a 24 h » : les courses anterieures n'ont legitimement aucun instantane
# et alerter dessus ferait sonner la sonde pendant une journee entiere sur une
# situation attendue — le meilleur moyen d'apprendre a ignorer ses alertes.
if [ "$JOUR_DE_COURSE" = "1" ] && [ -f /usr/local/bin/bt_elo_snapshot.sh ]; then
  pose=$(stat -c %Y /usr/local/bin/bt_elo_snapshot.sh 2>/dev/null || echo 0)
  elo_lu=$(docker exec blackturf_db psql -U blackturf -d blackturf -tAF'|' -c \
    "SELECT count(*), count(p.elo_avant_global)
     FROM participations p JOIN courses c ON c.course_id = p.course_id
     WHERE p.non_partant = false
       AND c.date_heure BETWEEN GREATEST(now() - interval '24 hours', to_timestamp($pose)) AND now();" 2>/dev/null | tr -d ' ')
  if [ -n "$elo_lu" ]; then
    elo_total=$(echo "$elo_lu" | cut -d'|' -f1)
    elo_ok=$(echo "$elo_lu" | cut -d'|' -f2)
    # Plancher a 100 partants pour ne pas alerter sur une journee creuse.
    if [ "${elo_total:-0}" -ge 100 ] && [ "$(( ${elo_ok:-0} * 100 / elo_total ))" -lt 90 ]; then
      ajoute "ALERTE instantane ELO : ${elo_ok}/${elo_total} partants des dernieres 24 h ont elo_avant_global (bt_elo_snapshot.sh ne tourne plus ?)"
    fi
  fi
fi

# ── 7. Sauvegarde de la veille ───────────────────────────────────────────────
DERNIERE=$(find /opt/blackturf/backups -name 'blackturf_*.sql.gz.enc' -mmin -1800 2>/dev/null | head -1)
[ -z "$DERNIERE" ] && ajoute "CRITIQUE sauvegarde : aucun dump chiffre de moins de 30 h"

# Copie hors serveur = le PC de l exploitant (sauvegarde_rapatrier.sh, tache
# planifiee de 12 h, rattrapee au reveil du PC). Il pose ce temoin apres chaque
# copie verifiee. 72 h de tolerance : un PC eteint un week-end n est pas un
# incident, trois jours sans aucune copie hors serveur en est un.
TEMOIN=/opt/blackturf/backups/.rapatrie_ok
if [ ! -f "$TEMOIN" ] || [ -z "$(find "$TEMOIN" -mmin -4320 2>/dev/null)" ]; then
  ajoute "ALERTE copie hors serveur : aucune sauvegarde rapatriee sur le PC depuis plus de 72 h (lancer rapatrier_sauvegarde.cmd)"
fi

# ── Notification ─────────────────────────────────────────────────────────────
# Etat persistant, une seule ligne : empreinte|compte|premier_vu|dernier_mail
#
# CONFIRMATION AVANT E-MAIL. Un passage isole ne prouve rien : la base peut
# etre occupee une seconde, un daemon peut etre en train de redemarrer, un
# compteur de volume sur 24 h repart forcement bas juste apres la pose d'un
# job. Le 08/09 sept e-mails sont partis en une heure pour des situations qui
# s'etaient reglees seules avant meme qu'on les lise — c'est le meilleur moyen
# d'apprendre a ignorer sa propre sonde. On ne notifie donc que si le MEME
# diagnostic tient plusieurs passages d'affilee. Ce qui disparait avant est
# journalise et jamais envoye.
#
# L'empreinte ignore les CHIFFRES. « 8 cotes », « 10 cotes », « 30 cotes » sont
# le meme probleme ; les garder rendait chaque passage unique et
# court-circuitait a la fois la confirmation et l'anti-repetition de 6 h.
#
# Le « dernier mail » est un CHAMP, pas le mtime du fichier d'etat : on reecrit
# cet etat a chaque passage pour incrementer le compteur, un anti-repetition
# base sur le mtime serait remis a zero toutes les 15 min et ne servirait plus
# a rien.
CONFIRM_ALERTE=3    # 3 x 15 min = 45 min avant notification
CONFIRM_CRITIQUE=2  # 2 x 15 min = 30 min (conteneur a terre, sauvegarde absente)
RAPPEL_S=21600      # 6 h entre deux rappels d'un probleme qui dure

MAINTENANT=$(date +%s)

lit_etat() {
  local ligne
  ligne=$(head -1 "$ETAT" 2>/dev/null || echo "")
  ANC_EMPREINTE=$(echo "$ligne" | cut -d'|' -f1)
  ANC_COMPTE=$(echo "$ligne" | cut -d'|' -f2)
  ANC_PREMIER=$(echo "$ligne" | cut -d'|' -f3)
  ANC_MAIL=$(echo "$ligne" | cut -d'|' -f4)
  case "$ANC_COMPTE"  in (*[!0-9]*|"") ANC_COMPTE=0 ;;  esac
  case "$ANC_PREMIER" in (*[!0-9]*|"") ANC_PREMIER=0 ;; esac
  case "$ANC_MAIL"    in (*[!0-9]*|"") ANC_MAIL=0 ;;    esac
}

envoie() { # $1 = fragment de sujet, $2 = corps HTML. Retourne non-zero si non envoye.
  # Resend, puis les relais SMTP gratuits (Brevo, Mailjet) : avec Resend seul, un
  # quota sature (07/10/2026) rendait la sonde muette sans que rien ne le dise.
  local html res
  html="<h3>Sonde de sante BlackTurf</h3><p>$2</p>"
  html="$html<p style=\"color:#666\">Sonde /usr/local/bin/bt_sante.sh, toutes les 15 min. "
  html="${html}Un probleme n est notifie qu apres plusieurs passages consecutifs : "
  html="${html}ce qui se regle tout seul ne declenche aucun e-mail. Journal : /var/log/bt-sante.log</p>"
  if res=$(printf '%s' "$html" | "$MAILER" "[BlackTurf] $1" 2>&1); then
    journal "e-mail -> admin : $res"
    return 0
  fi
  journal "e-mail NON parti (nouvel essai au passage suivant) : $res"
  return 1
}

# ── Tout va bien ─────────────────────────────────────────────────────────────
if [ -z "${PROBLEMES// /}" ]; then
  lit_etat
  if [ -n "$ANC_EMPREINTE" ] && [ "$ANC_EMPREINTE" != "ok" ]; then
    DUREE=$(( (MAINTENANT - ANC_PREMIER) / 60 ))
    if [ "$ANC_MAIL" -gt 0 ]; then
      # Un avis de cloture n'arrive que si une alerte a REELLEMENT ete envoyee :
      # au pire un message par incident, jamais du bruit.
      journal "retabli apres ${DUREE} min — envoi de l'avis de retour a la normale"
      envoie "retour a la normale" "Tous les controles repassent au vert.<br>Le probleme signale precedemment aura dure ${DUREE} min." || true
    else
      journal "retabli avant confirmation (${ANC_COMPTE} passage(s), ${DUREE} min) — aucun e-mail n'avait ete envoye"
    fi
  fi
  echo "ok|0|0|0" > "$ETAT"
  journal "ok — disque ${USAGE}%, ${DISPO} Mo RAM dispo"
  exit 0
fi

# ── Un probleme est present ──────────────────────────────────────────────────
journal "PROBLEMES:"$'\n'"$PROBLEMES"
logger -p daemon.err -t bt-sante "$(echo "$PROBLEMES" | tr '\n' ' ')"

EMPREINTE=$(echo "$PROBLEMES" | tr -d '0-9' | md5sum | cut -c1-32)
lit_etat
if [ "$EMPREINTE" = "$ANC_EMPREINTE" ]; then
  COMPTE=$((ANC_COMPTE + 1))
  PREMIER=$ANC_PREMIER
  DERNIER_MAIL=$ANC_MAIL
else
  COMPTE=1
  PREMIER=$MAINTENANT
  DERNIER_MAIL=0
fi
[ "$PREMIER" -eq 0 ] && PREMIER=$MAINTENANT

REQUIS=$CONFIRM_ALERTE
echo "$PROBLEMES" | grep -q CRITIQUE && REQUIS=$CONFIRM_CRITIQUE

ecris_etat() { echo "$EMPREINTE|$COMPTE|$PREMIER|$DERNIER_MAIL" > "$ETAT"; }

if [ "$COMPTE" -lt "$REQUIS" ]; then
  journal "e-mail differe : ${COMPTE}/${REQUIS} passages confirmes (notification dans ~$(( (REQUIS - COMPTE) * 15 )) min si ca persiste)"
  ecris_etat
  exit 0
fi

if [ "$DERNIER_MAIL" -gt 0 ] && [ $((MAINTENANT - DERNIER_MAIL)) -lt "$RAPPEL_S" ]; then
  journal "e-mail supprime (deja notifie, rappel dans $(( (RAPPEL_S - MAINTENANT + DERNIER_MAIL) / 60 )) min)"
  ecris_etat
  exit 0
fi

DUREE=$(( (MAINTENANT - PREMIER) / 60 ))
CORPS=$(printf '%s' "$PROBLEMES" | sed 's/&/\&amp;/g; s/</\&lt;/g' | sed 's/$/<br>/')
CORPS="${CORPS}<br>Confirme sur ${COMPTE} passages consecutifs, present depuis ${DUREE} min."
if envoie "alerte serveur" "$CORPS"; then
  DERNIER_MAIL=$MAINTENANT
fi
ecris_etat
