#!/bin/bash
# Re-chiffre les sauvegardes restees EN CLAIR (generation anterieure au 27/08/2026).
#
# Prudence deliberee : le clair n est supprime qu APRES verification de la sortie.
# Si quoi que ce soit cloche, on garde le clair et on passe au suivant — perdre
# une sauvegarde vaut bien pire que de la garder trop longtemps en clair.
set -uo pipefail
umask 077
DIR=/opt/blackturf/backups
CERT=/opt/blackturf/.backup-cert.pem
[ -s "$CERT" ] || { echo "certificat absent" >&2; exit 1; }
LIMITE=${1:-99}

n=0
for CLAIR in $(ls -1t "$DIR"/blackturf_*.sql.gz 2>/dev/null); do
  [ "$n" -ge "$LIMITE" ] && break
  case "$CLAIR" in *.enc) continue;; esac
  OUT="${CLAIR}.enc"
  [ -f "$OUT" ] && { echo "  deja fait : $(basename "$OUT")"; continue; }
  echo -n "  $(basename "$CLAIR") … "

  if ! gzip -t "$CLAIR" 2>/dev/null; then echo "SOURCE CORROMPUE, ignoree (clair conserve)"; continue; fi

  DK=$(mktemp); KENC=$(mktemp); TMP="$OUT.partiel"
  openssl rand -out "$DK" 32
  if ! openssl pkeyutl -encrypt -pubin -inkey <(openssl x509 -in "$CERT" -pubkey -noout) \
        -pkeyopt rsa_padding_mode:oaep -pkeyopt rsa_oaep_md:sha256 -in "$DK" -out "$KENC" 2>/dev/null \
     || [ "$(stat -c %s "$KENC")" != "512" ]; then
    echo "SCELLEMENT ECHOUE (clair conserve)"; shred -u "$DK" 2>/dev/null; rm -f "$KENC" "$TMP"; continue
  fi
  cat "$KENC" > "$TMP"
  if ! openssl enc -aes-256-ctr -pbkdf2 -pass "file:$DK" -in "$CLAIR" >> "$TMP" 2>/dev/null; then
    echo "CHIFFREMENT ECHOUE (clair conserve)"; shred -u "$DK" 2>/dev/null; rm -f "$KENC" "$TMP"; continue
  fi
  shred -u "$DK" 2>/dev/null; rm -f "$KENC"

  # Trois controles avant de detruire quoi que ce soit.
  T=$(stat -c %s "$TMP"); S=$(stat -c %s "$CLAIR")
  if [ "$(head -c 2 "$TMP" | xxd -p)" = "1f8b" ] || [ "$T" -lt $((S/2)) ] || [ "$T" -lt 1024 ]; then
    echo "SORTIE SUSPECTE ($T octets pour $S, clair conserve)"; rm -f "$TMP"; continue
  fi
  chmod 600 "$TMP"; mv "$TMP" "$OUT"
  shred -u "$CLAIR" 2>/dev/null || rm -f "$CLAIR"
  echo "OK ($((T/1024/1024)) Mo)"
  n=$((n+1))
done
echo "  --- $n fichier(s) re-chiffre(s) ---"
