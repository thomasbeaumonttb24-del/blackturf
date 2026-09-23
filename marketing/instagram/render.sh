#!/usr/bin/env bash
# Rend les visuels Instagram (post 4:5 et story 9:16) à partir des HTML.
# Usage : marketing/instagram/render.sh pub-site   → pub-site/post.png + story.png
# Dépend d'un Chromium headless (chemin via $CHROME, sinon détection).
set -euo pipefail
cd "$(dirname "$0")"
dir="${1:-pub-site}"
CHROME="${CHROME:-$(command -v chromium || command -v chromium-browser || command -v google-chrome || echo /opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell)}"
shot() { # fichier largeur hauteur sortie
  "$CHROME" --headless=new --no-sandbox --disable-gpu --hide-scrollbars \
    --window-size="$2,$3" --virtual-time-budget=4000 --screenshot="$4" "file://$PWD/$dir/$1" 2>/dev/null
  echo "→ $4"
}
shot post.html  1080 1350 "$dir/post.png"
shot story.html 1080 1920 "$dir/story.png"
