"""
feature_health.py — Détection des features MORTES / CONSTANTES (scraper cassé).

Le détecteur de drift (drift_detector.py) surveille la PERFORMANCE (Brier/ADWIN)
mais PAS la distribution des features. Une feature qui devient constante ou nulle
(source de scrape morte → valeur par défaut figée, ex. Turfoo 403 → taux=0.12 pour
tous) n'est jamais alertée : variance nulle ⇒ les arbres ne splittent jamais dessus
(impact 0) MAIS le DÉFAUT trompeur (même valeur partout) se présente comme un faux
signal uniforme.

Ce module échantillonne les features_ml pré-départ récentes et calcule, par feature
numérique : taux de NULL/absent, variance, nb de valeurs distinctes. Il FLAGGE les
features « mortes » (null_rate élevé OU variance ~0 OU ≤1 valeur distincte), journalise
et persiste un snapshot (table feature_health). `get_dead_features()` expose la liste
pour exclusion OPTIONNELLE au retrain (par défaut on LOGGE seulement, on n'exclut pas
automatiquement → pas de surprise silencieuse sur le modèle ; règle no-fake-data).

CE MODULE MESURE, IL NE PROTÈGE PAS. C'est une mesure d'observabilité, calculée sur un
échantillon de 45 jours : elle sert à ALERTER. La protection du modèle, elle, est faite
à l'entraînement (`ml.models.BlackTurfEnsemble.train`), qui écarte les colonnes
constantes sur SA propre part d'apprentissage — la seule mesure qui décrit vraiment ce
que le modèle a sous les yeux. Les deux ne peuvent donc pas diverger dangereusement :
si l'une manque une feature morte, l'autre la voit.
"""
from __future__ import annotations

import json
import math
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

# Seuils de déclaration « feature morte ». Conservateurs : on ne flagge que le franchement
# dégénéré (sinon faux positifs sur des features légitimement rares comme jument_pleine).
NULL_RATE_DEAD = 0.95      # ≥95% de valeurs manquantes/NULL → morte
DISTINCT_DEAD = 1          # ≤1 valeur distincte (présente) → constante
VAR_EPS = 1e-9            # variance sous ce seuil = constante numérique
SAMPLE_LIMIT = 40000      # plafond de lignes échantillonnées (mémoire bornée)
# Clés non-features (méta) à ignorer dans le scan.
_META_KEYS = {
    "participation_id", "course_id", "numero", "cheval_id", "position",
    "y_top3", "y_win", "date_heure",
}

# ── Features mortes DONT LA CAUSE EST ÉTABLIE ────────────────────────────────
# Une feature constante n'est pas forcément une panne : elle peut dépendre d'une
# donnée qui n'existe pas à la source. La différence compte, et elle ne se voit pas
# dans un compte global. Sans ce registre, l'alerte répétait chaque heure les mêmes
# 20 noms — dont la moitié était documentée depuis l'audit du 2026-08-31 — et noyait
# précisément celles que personne n'a encore expliquées.
#
# RÈGLE : on n'inscrit ici qu'une cause VÉRIFIÉE, avec sa date de vérification. Une
# hypothèse n'y a pas sa place ; elle doit rester dans le lot « inexpliqué », qui est
# ce que l'alerte montre. Le registre est audité en retour : `sante_features` signale
# toute entrée dont la feature a retrouvé de la variance (source revenue, ou cause
# mal établie) — un registre qui pourrit se voit.
SANS_SOURCE: dict[str, str] = {
    # Le PMU ne publie AUCUN commentaire de course : ni au niveau course, ni au
    # niveau participant de /performances-detaillees (clés relevées le 2026-08-31,
    # 0 occurrence). Les quatre features de déroulé lisent donc une colonne vide.
    "commentaire_signal": "commentaire_course absent de l'API PMU (vérifié 2026-08-31)",
    "commentaire_malchance_recente": "commentaire_course absent de l'API PMU (vérifié 2026-08-31)",
    "commentaire_gagne_facile": "commentaire_course absent de l'API PMU (vérifié 2026-08-31)",
    "nb_commentaires_lus": "commentaire_course absent de l'API PMU (vérifié 2026-08-31)",
    # `acceleration_label` se déduit des temps de passage. `temps_passage` n'a ni
    # source ni écrivain dans tout le code (vérifié 2026-08-31) : la colonne est vide
    # depuis l'origine, et les trois taux de dynamique valent donc 0 partout.
    # `dyn_nb_data` et les `dyn_reduction_km_*` survivent, eux, par `reduction_km`.
    "dyn_taux_accelere": "acceleration_label sans source (temps_passage jamais écrit, vérifié 2026-08-31)",
    "dyn_taux_faiblit": "acceleration_label sans source (temps_passage jamais écrit, vérifié 2026-08-31)",
    "dyn_finit_fort": "acceleration_label sans source (temps_passage jamais écrit, vérifié 2026-08-31)",
}


def classer_mortes(mortes) -> dict:
    """Range une liste de features mortes en « cause établie » / « inexpliquée ».

    Fonction PURE (pas de base) : `services.data_quality` l'applique aux instantanés
    DÉJÀ persistés, donc le classement vaut immédiatement, sans attendre un nouveau
    calcul nocturne.
    """
    mortes = sorted(set(mortes or []))
    documentees = [f for f in mortes if f in SANS_SOURCE]
    return {
        "documentees": documentees,
        "inexpliquees": [f for f in mortes if f not in SANS_SOURCE],
        "raisons": {f: SANS_SOURCE[f] for f in documentees},
    }


def registre_perime(mortes) -> list[str]:
    """Entrées du registre dont la feature n'est PLUS morte — donc à retirer.

    Le registre affirme « cette donnée n'existe pas à la source ». Le jour où la
    source revient, l'affirmation devient fausse et personne ne le remarquerait :
    c'est cette vérification-là qui manque à la plupart des listes d'exceptions.
    """
    return sorted(set(SANS_SOURCE) - set(mortes or []))


async def compute_feature_health(session: AsyncSession, jours: int = 45) -> dict:
    """Scanne les features_ml pré-départ des `jours` derniers jours. Retourne un dict
    {n_rows, n_features, dead: [...], stats: {feat: {null_rate, distinct, var}}}."""
    rows = (await session.execute(text("""
        SELECT fm.features
        FROM features_ml fm
        JOIN participations pa ON pa.participation_id = fm.participation_id
        JOIN courses c ON c.course_id = pa.course_id
        WHERE c.date_heure IS NOT NULL
          AND fm.computed_at < c.date_heure
          AND c.date_heure >= now() - make_interval(days => :j)
        ORDER BY c.date_heure DESC
        LIMIT :lim
    """), {"j": int(jours), "lim": SAMPLE_LIMIT})).fetchall()

    data = [(f if isinstance(f, dict) else json.loads(f)) for (f,) in rows]
    n = len(data)
    if n < 200:
        return {"n_rows": n, "insufficient": True}

    # Inventaire des clés numériques.
    keys: set[str] = set()
    for d in data:
        keys.update(d.keys())
    keys -= _META_KEYS

    stats: dict[str, dict] = {}
    dead: list[str] = []
    for k in sorted(keys):
        present = 0
        seen: set = set()
        s = s2 = 0.0
        numeric = True
        for d in data:
            v = d.get(k, None)
            if v is None:
                continue
            present += 1
            if len(seen) <= 12:
                seen.add(v)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                numeric = False
            else:
                s += v
                s2 += v * v
        null_rate = round(1.0 - present / n, 4)
        distinct = len(seen)
        var = None
        if numeric and present > 1:
            mean = s / present
            var = max(0.0, s2 / present - mean * mean)
        is_dead = (
            null_rate >= NULL_RATE_DEAD
            or distinct <= DISTINCT_DEAD
            or (var is not None and var < VAR_EPS)
        )
        stats[k] = {
            "null_rate": null_rate,
            "distinct": distinct,
            "var": (round(var, 9) if var is not None else None),
            "dead": is_dead,
        }
        if is_dead:
            dead.append(k)

    snap = {"n_rows": n, "n_features": len(keys), "n_dead": len(dead),
            "dead": dead, "stats": stats, "jours": jours}
    return snap


async def persist_feature_health(session: AsyncSession, snap: dict) -> None:
    if snap.get("insufficient"):
        return
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS feature_health (
            id BIGSERIAL PRIMARY KEY,
            data JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    await session.execute(text("INSERT INTO feature_health (data) VALUES (:d)"),
                          {"d": json.dumps(snap)})
    await session.commit()


async def get_dead_features(session: AsyncSession) -> list[str]:
    """Liste des features mortes du dernier snapshot (pour exclusion optionnelle au
    retrain). Vide si aucun snapshot. Lecture seule, jamais bloquante."""
    try:
        r = (await session.execute(text(
            "SELECT data FROM feature_health ORDER BY created_at DESC LIMIT 1"))).first()
        if not r:
            return []
        return list((r[0] or {}).get("dead", []))
    except Exception:
        return []
