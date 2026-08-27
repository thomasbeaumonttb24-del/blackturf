"""
Zone de marché d'un hippodrome — BlackTurf.

Le rapport parimutuel ne se forme pas de la même façon selon le pays de la
réunion, et l'écart est MESURÉ sur nos propres pronostics figés puis réglés
(60 jours, `profil_run_log`) :

    Simple Gagnant   France 0,939   étranger 0,807   (rapport réel / estimé)
    Simple Placé     France 0,977   étranger 0,883

La cause est mécanique : sur une réunion étrangère (tote américain surtout)
l'argent continue d'entrer dans le pool APRÈS le figeage du pronostic. Cas
mesuré le 2026-08-27 à Saratoga : le N°1 de la R6C4 valait 15,0 au moment du
plan (figé 24 min avant le départ) et a payé 3,3 — `mouvement_cote_pct` −80,6 %.
Conséquence produit : sur l'étranger, 52 % des paris prudents gagnants payaient
sous la tranche ×1,8 du profil, contre 22 % en France.

Ce module ne répond qu'à UNE question : cette course se court-elle en France ou
à l'étranger. `hippodromes.pays` est renseigné par le scraper depuis le
programme PMU (ISO3 ; aucun 'UNK' sur les 4 916 courses des 90 derniers jours).

Un hippodrome ABSENT de la table renvoie None, et l'appelant retombe alors sur
le facteur global tous-pays — jamais sur une zone devinée. C'est le même
principe de cold-start que le reste du calibrage : pas de donnée, pas de
correction.

On ne descend PAS au pays : à ce grain les échantillons tombent sous le seuil de
gagnants nécessaire (RC_MIN_WINS) et le facteur retomberait à 1.0 partout. La
zone à deux valeurs est le grain le plus fin qui reste mesurable.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ZONE_FRANCE = "FRA"
ZONE_ETRANGER = "ETR"

# Codes considérés comme « France » (le scraper écrit l'ISO3 ; 'FR' est toléré
# pour les lignes anciennes issues du défaut du modèle `Reunion.pays`).
_CODES_FRANCE = {"FRA", "FR"}
_CODES_INCONNUS = {"", "UNK", "UNKNOWN", "NONE", "NULL"}


def zone_depuis_pays(pays: str | None) -> str | None:
    """Zone de marché depuis un code pays ISO3. None = pays inconnu → pas de zone.

    Renvoyer None plutôt que ZONE_ETRANGER par défaut est délibéré : un pays
    manquant ne prouve pas qu'on est à l'étranger, et un mauvais classement
    appliquerait le facteur étranger (0,81) à des courses françaises.
    """
    if not pays:
        return None
    p = str(pays).strip().upper()
    if p in _CODES_INCONNUS:
        return None
    return ZONE_FRANCE if p in _CODES_FRANCE else ZONE_ETRANGER


async def zone_hippodrome(session: AsyncSession, hippodrome_nom: str | None) -> str | None:
    """Zone de marché d'un hippodrome, par son nom (clé UNIQUE `ix_hippodromes_nom`).

    Lecture seule, jamais bloquante : toute erreur SQL renvoie None (pas de zone
    → facteur global), car une correction de rapport ne vaut pas de faire échouer
    la génération d'un plan.
    """
    if not hippodrome_nom:
        return None
    try:
        row = (await session.execute(
            text("SELECT pays FROM hippodromes WHERE nom = :nom"),
            {"nom": hippodrome_nom},
        )).first()
    except Exception:
        return None
    return zone_depuis_pays(row[0]) if row else None
