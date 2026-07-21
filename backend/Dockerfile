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

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
