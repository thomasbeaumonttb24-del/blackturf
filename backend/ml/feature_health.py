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
# Part la plus RÉCENTE de l'échantillon sur laquelle le verdict est rendu (cf.
# `analyser_features`). 25 % de 45 jours ≈ 11 jours : assez pour qu'une feature
# vivante montre sa variance, assez court pour ne pas juger le présent sur le passé.
PART_RECENTE = 0.25
# Plancher de lignes de la tranche récente : sous ce volume, une absence de variance
# ne prouve rien (une feature rare comme `jument_pleine` serait déclarée morte).
MIN_LIGNES_RECENTES = 2000
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
# CORRECTION DU 2026-09-06 — une cause « vérifiée » qui ne l'était qu'à moitié.
# Les quatre features de commentaire portaient « commentaire_course absent de l'API
# PMU ». C'est faux tel quel : le champ est absent de /performances-detaillees, le
# SEUL endpoint qu'on interroge pour l'historique d'un cheval (clés relevées le
# 2026-09-06 : corde, distanceAvecPrecedent, distanceParcourue, itsHim, nomCheval,
# nomJockey, numPmu, oeillere, place, poidsJockey, reductionKilometrique — pas de
# commentaire). Mais /participants, lui, le publie une fois la course courue :
# 79 partants sur 136 le 05/09, 135 sur 163 le 04/09. La donnée existe donc, elle
# n'est simplement pas lue au bon endroit — ce qui n'est pas la même dette, et ce
# que la formulation d'origine faisait passer pour une impasse définitive.
# La règle du registre est « une cause VÉRIFIÉE » : on écrit donc ce qui est vrai.
_COMMENTAIRE = ("commentaire_course jamais écrit : /performances-detaillees ne "
                "publie pas de commentaire ; /participants le publie APRÈS la "
                "course et n'est pas relu pour l'historique (vérifié 2026-09-06)")

SANS_SOURCE: dict[str, str] = {
    "commentaire_signal": _COMMENTAIRE,
    "commentaire_malchance_recente": _COMMENTAIRE,
    "commentaire_gagne_facile": _COMMENTAIRE,
    "nb_commentaires_lus": _COMMENTAIRE,
    # `acceleration_label` se déduit des temps de passage. `temps_passage` n'a ni
    # source ni écrivain dans tout le code (vérifié 2026-08-31) : la colonne est vide
    # depuis l'origine, et les trois taux de dynamique valent donc 0 partout.
    # `dyn_nb_data` et les `dyn_reduction_km_*` survivent, eux, par `reduction_km`.
    "dyn_taux_accelere": "acceleration_label sans source (temps_passage jamais écrit, vérifié 2026-08-31)",
    "dyn_taux_faiblit": "acceleration_label sans source (temps_passage jamais écrit, vérifié 2026-08-31)",
    "dyn_finit_fort": "acceleration_label sans source (temps_passage jamais écrit, vérifié 2026-08-31)",
    # `participations.retard_gains` : 0 valeur non nulle sur toute la base (vérifié
    # 2026-09-06). Le champ n'existe pas dans la réponse /participants du PMU — la
    # liste complète de ses clés a été relevée le même jour — et aucune autre source
    # ne l'écrit : `PartantScrape.retard_gains` reste à None dans tous les parseurs.
    "retard_gains": "aucun champ retard de gains dans l'API PMU (vérifié 2026-09-06)",
}

# ── Features dont la donnée vient d'une source de scraping DÉSACTIVÉE ────────
# Ce n'est pas une panne, c'est une décision : `SCRAPER_DISABLED_SOURCES` liste les
# sources qu'on a explicitement mises en sommeil (racing_post, turfoo, france_galop,
# zeturf, geny, betclic, winamax, unibet en production le 2026-09-06). Huit features
# en dépendaient et remontaient chaque heure comme « mortes sans cause établie ».
#
# `services.data_quality.couverture_sources` traitait déjà ce cas pour les COTES
# (statut `silent_disabled`) : une source coupée exprès n'est pas une alerte. La
# santé des features ignorait la même information et criait sur la même décision.
#
# Cette table n'est pas un second registre d'exceptions : elle NOMME LA SOURCE, et
# le classement se refait à chaque lecture. Rallumer `france_galop` remet aussitôt
# ses six features dans le lot inexpliqué si elles restent constantes — ce qu'une
# liste figée de noms ne saurait pas faire.
SOURCE_PAR_FEATURE: dict[str, str] = {
    # `chevaux.running_style` / `taux_en_tete` : 0 valeur sur 56 149 chevaux.
    # Écrites par `sources/france_galop.py` (galop) uniquement.
    "running_style_code": "france_galop",
    "taux_en_tete": "france_galop",
    "nb_meneurs_course": "france_galop",
    "pace_conflict_score": "france_galop",
    "running_style_terrain_fit": "france_galop",
    # `chevaux.prix_vente_yearling` : 0 valeur. France Galop ET Racing Post l'écrivent ;
    # on nomme celle qui couvre le plus, les deux étant en sommeil.
    "prix_vente_log": "racing_post",
    # `participations.rang_pronostic_geny` : 0 valeur. Écrit par le seul cycle geny,
    # et la source est en sommeil depuis que ses cotes se sont révélées fausses
    # (plafond à 9,9, décalage d'un cheval — audit du 2026-08-27).
    "rang_pronostic_geny": "geny",
    # `participations.cote_betclic` : 0 valeur.
    "steam_move_betclic": "betclic",
}


def _cause_source_eteinte(feature: str, sources_desactivees) -> str | None:
    """Cause « la source est coupée exprès », ou None si elle tourne (ou inconnue)."""
    src = SOURCE_PAR_FEATURE.get(feature)
    if src and src in (sources_desactivees or ()):
        return f"source '{src}' désactivée (SCRAPER_DISABLED_SOURCES)"
    return None


def classer_mortes(mortes, sources_desactivees=None) -> dict:
    """Range une liste de features mortes en « cause établie » / « inexpliquée ».

    Fonction PURE (pas de base, et pas d'environnement non plus : la liste des
    sources en sommeil est PASSÉE par l'appelant, qui la lit déjà pour la couverture
    des cotes). `services.data_quality` l'applique aux instantanés DÉJÀ persistés,
    donc le classement vaut immédiatement, sans attendre un nouveau calcul nocturne.

    Deux causes établies, et elles ne se valent pas :
      - `SANS_SOURCE` : la donnée n'existe pas, personne ne peut la produire ;
      - source en sommeil : la donnée existe, on a choisi de ne pas la collecter.
    La seconde se dément toute seule le jour où la source est rallumée.
    """
    mortes = sorted(set(mortes or []))
    raisons: dict[str, str] = {}
    for f in mortes:
        cause = SANS_SOURCE.get(f) or _cause_source_eteinte(f, sources_desactivees)
        if cause:
            raisons[f] = cause
    documentees = [f for f in mortes if f in raisons]
    return {
        "documentees": documentees,
        "inexpliquees": [f for f in mortes if f not in raisons],
        "raisons": raisons,
    }


def registre_perime(mortes) -> list[str]:
    """Entrées du registre dont la feature n'est PLUS morte — donc à retirer.

    Le registre affirme « cette donnée n'existe pas à la source ». Le jour où la
    source revient, l'affirmation devient fausse et personne ne le remarquerait :
    c'est cette vérification-là qui manque à la plupart des listes d'exceptions.
    """
    return sorted(set(SANS_SOURCE) - set(mortes or []))


def _mesurer(data, keys) -> dict:
    """Par feature : taux d'absence, nb de valeurs distinctes, variance. Fonction PURE."""
    n = len(data)
    out: dict[str, dict] = {}
    for k in keys:
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
        var = None
        if numeric and present > 1:
            mean = s / present
            var = max(0.0, s2 / present - mean * mean)
        out[k] = {
            "null_rate": round(1.0 - present / n, 4) if n else 1.0,
            "distinct": len(seen),
            "var": var,
        }
    return out


def analyser_features(data: list[dict], jours: int | None = None) -> dict:
    """Verdict de santé sur un échantillon de vecteurs de features, du PLUS RÉCENT
    au plus ancien. Fonction PURE — c'est elle que les tests exercent.

    LE VERDICT PORTE SUR LA TRANCHE RÉCENTE, ET C'EST TOUT L'ENJEU. Mesurer le taux
    d'absence sur 45 jours confond deux situations opposées :

        une feature MORTE      absente/constante partout, y compris hier ;
        une feature NEUVE      absente du passé pour la seule raison qu'elle
                               n'existait pas encore.

    Les deux donnent null_rate ≈ 1. `presse_rang_moyen`, `presse_score_borda` et
    `presse_nb_sources` ont été ajoutées le 2026-09-01 — trois jours avant l'alerte,
    et le compte de features est passé de 208 à 211 dans le même temps. Sur une
    fenêtre de 45 jours elles étaient absentes de 95 % des lignes : comptées mortes
    le jour même de leur naissance, et pire, comptées comme des features qui
    VIENNENT DE MOURIR — ce qui déclenche l'anomalie `critical` réservée à la chute
    d'une source. Une supervision qui accuse un correctif d'être une panne n'est pas
    une supervision.

    On juge donc sur ce qui est servi AUJOURD'HUI, et on nomme à part ce qui vient
    d'apparaître (présent récemment, absent avant). Les statistiques de la fenêtre
    entière restent publiées : elles servent la comparaison, pas le verdict.
    """
    n = len(data)
    keys: set[str] = set()
    for d in data:
        keys.update(d.keys())
    keys -= _META_KEYS
    keys_triees = sorted(keys)

    # Tranche récente : assez large pour que l'absence de variance signifie quelque
    # chose, assez courte pour ne pas traîner le passé. `data` est trié du plus
    # récent au plus ancien (ORDER BY date_heure DESC).
    n_recent = min(n, max(MIN_LIGNES_RECENTES, int(n * PART_RECENTE)))
    recentes, anciennes = data[:n_recent], data[n_recent:]

    stats_fenetre = _mesurer(data, keys_triees)
    stats_recent = _mesurer(recentes, keys_triees)
    stats_ancien = _mesurer(anciennes, keys_triees) if anciennes else {}

    stats: dict[str, dict] = {}
    dead: list[str] = []
    nouvelles: list[str] = []
    for k in keys_triees:
        rec, fen = stats_recent[k], stats_fenetre[k]
        anc = stats_ancien.get(k)
        # NEUVE : servie maintenant, inconnue avant. Ce n'est pas une panne, c'est
        # une naissance — et il ne reste rien à en dire tant que le passé n'a pas
        # rattrapé son retard.
        est_nouvelle = bool(
            anc is not None
            and rec["null_rate"] < 0.5
            and anc["null_rate"] >= NULL_RATE_DEAD
        )
        est_morte = (not est_nouvelle) and (
            rec["null_rate"] >= NULL_RATE_DEAD
            or rec["distinct"] <= DISTINCT_DEAD
            or (rec["var"] is not None and rec["var"] < VAR_EPS)
        )
        stats[k] = {
            # `null_rate` / `var` restent ceux de la FENÊTRE (compatibilité des
            # instantanés déjà en base et des lectures existantes).
            "null_rate": fen["null_rate"],
            "distinct": fen["distinct"],
            "var": (round(fen["var"], 9) if fen["var"] is not None else None),
            "null_rate_recent": rec["null_rate"],
            "distinct_recent": rec["distinct"],
            "var_recent": (round(rec["var"], 9) if rec["var"] is not None else None),
            "nouvelle": est_nouvelle,
            "dead": est_morte,
        }
        if est_morte:
            dead.append(k)
        elif est_nouvelle:
            nouvelles.append(k)

    return {"n_rows": n, "n_rows_recent": n_recent, "n_features": len(keys),
            "n_dead": len(dead), "dead": dead,
            "nouvelles": nouvelles, "n_nouvelles": len(nouvelles),
            "stats": stats, "jours": jours}


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
    if len(data) < 200:
        return {"n_rows": len(data), "insufficient": True}
    return analyser_features(data, jours=jours)


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
