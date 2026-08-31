FROM python:3.12-slim

WORKDIR /app

# build-essential nécessaire pour compiler certaines deps, PUIS purgé du filesystem
# final (réduit la surface : pas de compilateur dans le conteneur de prod).
# libgomp1 = runtime OpenMP requis par lightgbm/xgboost/sklearn — installé
# EXPLICITEMENT (donc marqué manuel) pour SURVIVRE au purge auto de build-essential.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgomp1 \
    build-essential \
    && pip install --no-cache-dir --upgrade pip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/*

# Utilisateur non privilégié : une RCE dans le code Python ne donne PAS root.
RUN useradd --system --uid 1001 --create-home appuser

COPY . .

# /app/models et /app/data sont des points de montage de volumes : on les crée et on
# donne la propriété à appuser (le contenu des volumes doit aussi être chown 1001 côté
# hôte — fait au déploiement).
RUN mkdir -p /app/models /app/data && chown -R 1001:1001 /app

USER 1001

# --proxy-headers : l'app est TOUJOURS derrière nginx, qui envoie X-Forwarded-Proto.
# Sans ce flag uvicorn croit parler en http et construit ses redirections en http —
# un 307 (ex. /api/v1/notifications → /notifications/) renvoyait le navigateur vers
# http:// depuis une page https, qui refuse de suivre (contenu mixte) : requête morte
# et écran vide, sans la moindre erreur visible. --forwarded-allow-ips=* est sûr ici :
# nginx est le SEUL ingress. `--forwarded-allow-ips=*` n'est sûr QU'À CETTE
# CONDITION : le port 8000 est publié sur la loopback uniquement (cf. le mapping
# `127.0.0.1:8000:8000` dans docker-compose.yml). Republier ce port sur 0.0.0.0
# rendrait l'usurpation de X-Forwarded-For possible depuis Internet.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
