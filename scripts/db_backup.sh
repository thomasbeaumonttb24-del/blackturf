#!/bin/bash
set -euo pipefail

# Un dump contient les adresses e-mail, les mots de passe haches et les
# identifiants clients Stripe de tous les abonnes. Il naissait en 644 : lisible
# par n'importe quel compte de la machine, alors que le compte `blackturf`
# existe et a un shell. `umask 077` verrouille les fichiers CREES ICI ; le
# `chmod` explicite plus bas rattrape ceux qui existaient deja.
umask 077

DIR=/opt/blackturf/backups
mkdir -p "$DIR"
chmod 700 "$DIR"

TS=$(date +%Y%m%d_%H%M%S)
FILE="$DIR/blackturf_$TS.sql.gz"
# On ecrit sous un nom temporaire, jamais directement sous le nom final : avec
# `set -e` + `pipefail`, un pg_dump qui meurt en cours de route laissait un
# fichier TRONQUE mais non vide sous le nom definitif. Il passait le test
# `-s` du jour suivant et occupait un des 14 emplacements de retention : une
# sauvegarde inutilisable qui se faisait passer pour valide.
TMP="$FILE.partiel"
trap 'rm -f "$TMP"' EXIT

docker exec blackturf_db pg_dump -U blackturf -d blackturf --no-owner | gzip > "$TMP"

if [ ! -s "$TMP" ]; then echo "SAUVEGARDE ECHOUEE : fichier vide"; exit 1; fi
# `gzip -t` relit l'archive entiere : c'est ce qui distingue « le fichier fait
# la bonne taille » de « le fichier est reellement restaurable ».
if ! gzip -t "$TMP"; then echo "SAUVEGARDE ECHOUEE : archive corrompue"; exit 1; fi

mv "$TMP" "$FILE"
trap - EXIT
chmod 600 "$FILE"

# Retention : les 14 plus recentes.
ls -1t "$DIR"/blackturf_*.sql.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
# Rattrape les droits des sauvegardes anterieures a ce durcissement.
chmod 600 "$DIR"/blackturf_*.sql.gz 2>/dev/null || true

echo "OK $FILE ($(du -h "$FILE" | cut -f1))"
