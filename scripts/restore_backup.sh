#!/bin/bash
# Dechiffre une sauvegarde BlackTurf et, en option, la restaure.
#
#   ./restore_backup.sh <fichier.sql.gz.enc> <cle_privee.key> [--restaurer]
#
# A LANCER SUR UNE MACHINE QUI DETIENT LA CLE PRIVEE — jamais sur le VPS : le
# serveur chiffre, il ne doit pas pouvoir dechiffrer. C'est tout l'interet du
# chiffrement a cle publique, et y deposer la cle privee annulerait la mesure.
#
# Format produit par db_backup.sh :
#   [512 octets : cle AES-256 scellee RSA-4096 OAEP-SHA256][chiffre AES-256-CTR]
set -euo pipefail

FICHIER=${1:?usage: restore_backup.sh <fichier.enc> <cle_privee.key> [--restaurer]}
CLE=${2:?chemin de la cle privee manquant}
[ -s "$FICHIER" ] || { echo "fichier introuvable ou vide : $FICHIER" >&2; exit 1; }
[ -s "$CLE" ]     || { echo "cle privee introuvable : $CLE" >&2; exit 1; }

TRAVAIL=$(mktemp -d); trap 'rm -rf "$TRAVAIL"' EXIT

# Le prefixe fait TOUJOURS 512 octets (taille d'un chiffre RSA-4096). Le script
# de sauvegarde le verifie a l'ecriture ; on ne redecouvre donc pas la taille ici.
head -c 512 "$FICHIER"  > "$TRAVAIL/cle.enc"
tail -c +513 "$FICHIER" > "$TRAVAIL/donnees.enc"

openssl pkeyutl -decrypt -inkey "$CLE" \
  -pkeyopt rsa_padding_mode:oaep -pkeyopt rsa_oaep_md:sha256 \
  -in "$TRAVAIL/cle.enc" -out "$TRAVAIL/cle.bin" \
  || { echo "ECHEC : cette cle privee ne correspond pas a ce fichier" >&2; exit 1; }

SORTIE="${FICHIER%.enc}"
openssl enc -d -aes-256-ctr -pbkdf2 -pass "file:$TRAVAIL/cle.bin" \
  -in "$TRAVAIL/donnees.enc" -out "$SORTIE"

# On ne se contente pas d'un dechiffrement « sans erreur » : AES-CTR ne detecte
# pas une alteration, il produirait joyeusement du bruit. `gzip -t` relit
# l'archive entiere et c'est LA preuve que la sauvegarde est exploitable.
gzip -t "$SORTIE" || { echo "ECHEC : archive dechiffree mais corrompue" >&2; exit 1; }
echo "OK dechiffre et verifie : $SORTIE ($(du -h "$SORTIE" | cut -f1))"

if [ "${3:-}" = "--restaurer" ]; then
  echo
  echo "ATTENTION : la restauration ECRASE la base cible. Ctrl-C dans 10 s pour annuler."
  sleep 10
  gunzip -c "$SORTIE" | docker exec -i blackturf_db psql -U blackturf -d blackturf
  echo "restauration terminee"
else
  echo "Pour restaurer :  gunzip -c \"$SORTIE\" | docker exec -i blackturf_db psql -U blackturf -d blackturf"
fi
