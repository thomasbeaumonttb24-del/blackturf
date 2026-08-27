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

openssl rand -out "$DK" 32
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
ls -1t "$DIR"/blackturf_*.sql.gz.enc "$DIR"/blackturf_*.sql.gz 2>/dev/null \
  | tail -n +15 | xargs -r rm -f
chmod 600 "$DIR"/blackturf_*.sql.gz* 2>/dev/null || true

echo "OK $FILE ($(du -h "$FILE" | cut -f1), chiffre)"

# ── Copie deportee (s'active des qu'un distant rclone existe) ─────────────────
# Une sauvegarde qui vit sur le disque qu'elle protege ne protege ni d'un
# rancongiciel ni de la perte du serveur. Le fichier etant deja chiffre, il peut
# partir chez n'importe quel hebergeur sans exposer les donnees des abonnes.
if command -v rclone >/dev/null && rclone listremotes 2>/dev/null | grep -q .; then
  DEST=$(rclone listremotes | head -1)
  rclone copy "$FILE" "${DEST}blackturf-backups/" 2>&1 | tail -2 \
    || echo "ATTENTION : copie deportee ECHOUEE (sauvegarde locale intacte)"
fi
