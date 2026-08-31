#!/bin/bash
set -euo pipefail

# Un dump contient les adresses e-mail, les mots de passe haches et les
# identifiants clients Stripe de tous les abonnes. Il naissait en 644 : lisible
# par n'importe quel compte de la machine. `umask 077` verrouille les fichiers
# crees ici ; le `chmod` explicite plus bas rattrape ceux d'avant.
umask 077

DIR=/opt/blackturf/backups
CERT=/opt/blackturf/.backup-cert.pem
mkdir -p "$DIR"
chmod 700 "$DIR"

# ── Chiffrement ───────────────────────────────────────────────────────────────
# Chiffrement A CLE PUBLIQUE : cette machine chiffre, elle ne peut PAS dechiffrer.
# Voler le VPS ne donne donc rien de lisible, et la copie deportee peut voyager
# sans exposer les donnees des abonnes.
#
# La cle PRIVEE n'est pas ici et ne doit jamais y arriver : elle vit sur le poste
# de l'exploitant (CLE_SAUVEGARDES_blackturf.key). Sans elle, AUCUNE sauvegarde
# n'est restaurable — c'est le prix du chiffrement. Elle doit donc etre copiee
# ailleurs qu'a un seul endroit.
#
# Schema hybride explicite plutot que `openssl cms` : en sortie DER, CMS
# bufferise l'integralite du message en memoire. Sur un dump de ~1 Go, sur une
# machine qui a deja connu un OOM, c'est inacceptable. Ici tout est en FLUX, a
# memoire constante :
#   [512 octets : cle AES scellee RSA-4096 OAEP][chiffre AES-256-CTR]
# La taille fixe du prefixe rend le dechiffrement trivial et deterministe.
[ -s "$CERT" ] || {
  # ECHEC FERME, jamais de repli en clair. Une sauvegarde non chiffree produite
  # en silence parce qu'un fichier manque est exactement le mode de panne qu'on
  # cherche a supprimer (cf. le repli `${REDIS_PASSWORD:-redis_secret}`).
  echo "SAUVEGARDE ECHOUEE : $CERT absent (certificat de chiffrement)" >&2; exit 1; }

TS=$(date +%Y%m%d_%H%M%S)
FILE="$DIR/blackturf_$TS.sql.gz.enc"
TMP="$FILE.partiel"
CLAIR="$TMP.clair"
DK=$(mktemp); KENC=$(mktemp)
trap 'rm -f "$TMP" "$CLAIR" "$KENC"; shred -u "$DK" 2>/dev/null || rm -f "$DK"' EXIT

# Le dump est d'abord ecrit en clair pour verifier son integrite AVANT
# chiffrement : `gzip -t` sur un flux deja chiffre ne prouverait rien, et un
# dump corrompu chiffre reste un dump corrompu.
docker exec blackturf_db pg_dump -U blackturf -d blackturf --no-owner | gzip > "$CLAIR"
[ -s "$CLAIR" ] || { echo "SAUVEGARDE ECHOUEE : dump vide" >&2; exit 1; }
gzip -t "$CLAIR" || { echo "SAUVEGARDE ECHOUEE : archive corrompue" >&2; exit 1; }

# ── CLE AES EN HEXADECIMAL, ET SURTOUT PAS EN OCTETS BRUTS ───────────────────
# `openssl enc -pass file:` ne lit QUE LA PREMIERE LIGNE du fichier de cle. Avec
# 32 octets aleatoires bruts, si le premier octet vaut 0x0a (saut de ligne), la
# passphrase effective est VIDE — et le sel PBKDF2 est ecrit en clair dans le
# fichier. N'importe qui tenant le .enc le dechiffre alors sans aucune cle :
#
#   $ printf '\x0a\xde\xad...' > kbad.bin          # 32 octets, le 1er vaut 0x0a
#   $ echo "DONNEES SENSIBLES" | openssl enc -aes-256-ctr -pbkdf2 \
#         -pass file:kbad.bin -out bad.enc
#   $ openssl enc -d -aes-256-ctr -pbkdf2 -pass "pass:" -in bad.enc
#   DONNEES SENSIBLES                               <- dechiffre, passphrase vide
#
# Probabilite 1/256 = 0,39 % par sauvegarde, soit 5,3 % qu'au moins une des 14
# conservees soit dans ce cas. Et plus generalement, un 0x0a n'importe ou dans les
# 32 octets (11,8 % des tirages) tronque la cle a cet endroit. Un dump contient les
# adresses e-mail, les mots de passe haches et les identifiants Stripe de tous les
# abonnes : ce n'est pas un risque theorique.
#
# `-hex` produit 64 caracteres de l'alphabet [0-9a-f] : aucun saut de ligne n'y est
# possible, la premiere ligne EST la cle entiere, et l'entropie reste de 256 bits.
#
# COMPATIBILITE : la restauration ne change pas d'un iota. `restore_backup.sh`
# ecrit ce que `pkeyutl -decrypt` lui rend et le passe a `-pass file:` — que ce
# soient 32 octets bruts (ancien format) ou 64 caracteres hex (nouveau). Les
# sauvegardes deja produites restent donc restaurables telles quelles.
openssl rand -hex 32 > "$DK"
# Fail-closed : si un jour `-hex` disparaissait ou changeait de forme, on ne veut
# pas decouvrir a la restauration qu'on a re-fabrique une cle tronquable.
[ "$(head -n 1 "$DK" | tr -d '\n' | wc -c)" = "64" ] || {
  echo "SAUVEGARDE ECHOUEE : cle AES mal formee (64 caracteres hex attendus)" >&2; exit 1; }
case "$(head -n 1 "$DK")" in
  *[!0-9a-f]*) echo "SAUVEGARDE ECHOUEE : cle AES hors alphabet hexadecimal" >&2; exit 1;;
esac

openssl pkeyutl -encrypt -pubin \
  -inkey <(openssl x509 -in "$CERT" -pubkey -noout) \
  -pkeyopt rsa_padding_mode:oaep -pkeyopt rsa_oaep_md:sha256 \
  -in "$DK" -out "$KENC"
# RSA-4096 OAEP produit TOUJOURS 512 octets. On le verifie : si la taille change
# un jour (autre taille de cle), le dechiffrement lirait un mauvais prefixe et
# echouerait silencieusement au pire moment — celui de la restauration.
[ "$(stat -c %s "$KENC")" = "512" ] || {
  echo "SAUVEGARDE ECHOUEE : cle scellee de $(stat -c %s "$KENC") octets, 512 attendus" >&2; exit 1; }

cat "$KENC" > "$TMP"
openssl enc -aes-256-ctr -pbkdf2 -pass "file:$DK" -in "$CLAIR" >> "$TMP"

# Preuve que la sortie n'est pas le clair recopie : un .gz commence par 1f 8b.
[ "$(head -c 2 "$TMP" | xxd -p)" != "1f8b" ] || {
  echo "SAUVEGARDE ECHOUEE : sortie non chiffree" >&2; exit 1; }
[ "$(stat -c %s "$TMP")" -gt 1024 ] || { echo "SAUVEGARDE ECHOUEE : sortie trop petite" >&2; exit 1; }

shred -u "$CLAIR" 2>/dev/null || rm -f "$CLAIR"
mv "$TMP" "$FILE"
chmod 600 "$FILE"

# Retention : les 14 plus recentes, chiffrees ET anciennes en clair confondues,
# pour que les deux generations de noms soient purgees par la meme regle.
#
# `|| true` INDISPENSABLE, et son absence a fait tomber le script chaque nuit
# depuis le 2026-08-27. Le second motif (`blackturf_*.sql.gz` sans `.enc`) ne
# correspond plus a rien depuis que toutes les sauvegardes sont chiffrees : `ls`
# sort alors en 2, `set -o pipefail` propage, `set -e` tue le script. La purge,
# elle, avait bien eu lieu — c'est tout ce qui SUIT qui ne s'executait plus : le
# `chmod`, le message « OK », et le bloc de copie deportee ci-dessous.
#
# Le symptome etait invisible : les sauvegardes etaient bien produites et bien
# chiffrees (restauration verifiee de bout en bout le 2026-08-31), seul le code de
# retour etait faux. Trace dans backups/backup.log : la derniere ligne « OK » date
# du 27/08 et porte un nom SANS `.enc`. Personne ne lit un journal qui n'affiche
# que des avertissements de pg_dump.
ls -1t "$DIR"/blackturf_*.sql.gz.enc "$DIR"/blackturf_*.sql.gz 2>/dev/null \
  | tail -n +15 | xargs -r rm -f || true
chmod 600 "$DIR"/blackturf_*.sql.gz* 2>/dev/null || true

echo "OK $FILE ($(du -h "$FILE" | cut -f1), chiffre)"

# ── Copie deportee ────────────────────────────────────────────────────────────
# Une sauvegarde qui vit sur le disque qu'elle protege ne protege ni d'un
# rancongiciel ni de la perte du serveur. Le fichier etant deja chiffre, il peut
# partir chez n'importe quel hebergeur sans exposer les donnees des abonnes.
#
# LE SILENCE ETAIT LE DEFAUT. Ce bloc etait garde par `command -v rclone` : rclone
# n'ayant jamais ete installe sur le VPS, la branche ne s'est jamais executee et
# personne n'en a rien su. Constat du 2026-08-31 : douze sauvegardes, 12 Go, zero
# copie hors site — et la conviction, cote exploitant, qu'il y en avait une. Une
# protection qui s'auto-desactive sans le dire est pire que pas de protection :
# elle produit une fausse assurance.
#
# Desormais l'absence de copie deportee est un ECHEC VISIBLE, pas un no-op. La
# sauvegarde locale reste produite (on ne perd jamais une sauvegarde parce que le
# distant est indisponible), mais le script sort en erreur : le cron enverra le
# message, et `check_retrain_cron.sh` / le journal le montreront.
#
# Pour desactiver sciemment (poste isole, phase de mise au point) :
#   BLACKTURF_BACKUP_SANS_DEPORT=1  dans l'environnement du cron.
if [ "${BLACKTURF_BACKUP_SANS_DEPORT:-0}" = "1" ]; then
  echo "copie deportee DESACTIVEE explicitement (BLACKTURF_BACKUP_SANS_DEPORT=1)"
elif ! command -v rclone >/dev/null; then
  echo "ATTENTION : rclone absent — AUCUNE copie hors site. La sauvegarde locale" >&2
  echo "  $FILE est intacte mais elle ne survivrait pas a la perte du serveur." >&2
  echo "  Installer rclone puis configurer un distant (rclone config)." >&2
  exit 3
elif ! rclone listremotes 2>/dev/null | grep -q .; then
  echo "ATTENTION : rclone installe mais AUCUN distant configure — pas de copie" >&2
  echo "  hors site. Lancer 'rclone config' pour en declarer un." >&2
  exit 3
else
  DEST=$(rclone listremotes | head -1)
  if rclone copy "$FILE" "${DEST}blackturf-backups/" 2>&1 | tail -2; then
    # `rclone copy` peut sortir 0 sans avoir rien transfere : on VERIFIE que le
    # fichier existe bien a destination, avec la bonne taille. Une copie hors site
    # non verifiee ne vaut pas mieux qu'une copie absente.
    TAILLE_LOCALE=$(stat -c %s "$FILE")
    TAILLE_DISTANTE=$(rclone size --json "${DEST}blackturf-backups/$(basename "$FILE")" 2>/dev/null \
                      | grep -o '"bytes":[0-9]*' | cut -d: -f2)
    if [ "${TAILLE_DISTANTE:-0}" = "$TAILLE_LOCALE" ]; then
      echo "copie hors site verifiee : ${DEST}blackturf-backups/ ($TAILLE_LOCALE octets)"
    else
      echo "ATTENTION : copie deportee INCOMPLETE (${TAILLE_DISTANTE:-0} octets a" >&2
      echo "  destination pour $TAILLE_LOCALE en local). Sauvegarde locale intacte." >&2
      exit 3
    fi
  else
    echo "ATTENTION : copie deportee ECHOUEE (sauvegarde locale intacte)" >&2
    exit 3
  fi
fi
