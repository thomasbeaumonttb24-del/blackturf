"""Référence des paris PMU : règle du jeu, conditions d'offre, rendement mesuré.

Le pari mutuel n'est pas un pari à cote fixe. Le PMU met toutes les mises d'un
même type dans un POOL, prélève sa part, et partage le reste entre les gagnants.
Deux conséquences gouvernent tout ce module :

1. **Le prélèvement est le premier adversaire.** Il varie fortement selon le type
   (~15,5 % sur les paris simples, ~23 % sur les couplés, ~25 % sur les trios,
   jusqu'à ~30 % sur le Multi). Un pari à fort prélèvement exige un avantage
   beaucoup plus grand pour seulement rentrer dans ses frais.
2. **Le rapport dépend des autres parieurs**, jamais d'une cote garantie. Trouver
   le gagnant ne suffit pas : il faut le trouver là où la foule ne l'a pas mis.

Les rendements ci-dessous sont MESURÉS sur nos propres conseils réglés
(19 996 paris, 112 472 € engagés, gains winsorisés à 50× la mise pour qu'un coup
isolé ne raconte pas l'histoire à la place des données). Ils ne sont pas des
estimations théoriques.
"""
from __future__ import annotations

from typing import NamedTuple, Optional


class ParisPMU(NamedTuple):
    """Un type de pari : ce qu'il faut trouver, quand il est offert, ce qu'il rend."""
    nom: str
    flag: str                    # drapeau de disponibilité (cf. bet_catalog)
    a_trouver: str               # condition de gain, en clair
    prelevement: float           # part gardée par le PMU (ordre de grandeur)
    mise_base: float             # mise unitaire PMU en euros
    partants_min: int            # champ minimal sous lequel le PMU ne l'offre pas
    frequence_offre: Optional[float]   # part des courses qui le proposent (mesurée)
    taux_reussite: Optional[float]     # nos conseils gagnants / conseils émis
    roi_mesure: Optional[float]        # ROI winsorisé de NOS conseils, en %
    n_mesure: int                      # nombre de conseils réglés derrière le ROI
    quand_le_jouer: str


# Ordonné du plus rentable au moins rentable, sur NOS données.
CATALOGUE: tuple[ParisPMU, ...] = (
    ParisPMU(
        nom="Simple Gagnant", flag="est_simple_gagnant",
        a_trouver="le cheval arrive 1er",
        prelevement=0.155, mise_base=1.0, partants_min=3,
        frequence_offre=0.954, taux_reussite=0.089, roi_mesure=-9.0, n_mesure=6297,
        quand_le_jouer=(
            "Le pari de référence : prélèvement le plus faible du PMU. Notre seule "
            "tranche jamais rentable s'y trouve (rapport ×4-8, +0,6 % sur 1 367 "
            "conseils). Au-delà de ×30 il s'effondre (-32,7 %) : la foule sur-mise "
            "les outsiders, pas nous."),
    ),
    ParisPMU(
        nom="Simple Placé", flag="est_simple_place",
        a_trouver="le cheval finit dans les 3 premiers (les 2 premiers si moins de 8 partants)",
        prelevement=0.155, mise_base=1.0, partants_min=4,
        frequence_offre=0.955, taux_reussite=0.369, roi_mesure=-9.6, n_mesure=3279,
        quand_le_jouer=(
            "Le plus régulier : il tombe une fois sur trois, donc son rendement se "
            "mesure vite et se prête à un capital modeste. Sous ×4 il tient (-6,5 %) ; "
            "au-delà, il chute à -24,6 % — un placé qui paie gros est un placé "
            "improbable."),
    ),
    ParisPMU(
        nom="Couplé Gagnant", flag="est_couple_gagnant",
        a_trouver="les 2 chevaux désignés terminent 1er et 2e, dans n'importe quel ordre",
        prelevement=0.23, mise_base=1.0, partants_min=8,
        frequence_offre=0.855, taux_reussite=0.037, roi_mesure=-9.7, n_mesure=5430,
        quand_le_jouer=(
            "Prélèvement bien plus lourd que le simple, à réserver aux courses où "
            "deux chevaux dominent nettement. Nos tranches ×15-60 affichent un ROI "
            "positif mais sur trop peu de gagnants (~33) pour être crédible ; "
            "au-delà de ×60 c'est -66,2 % sans ambiguïté."),
    ),
    ParisPMU(
        nom="Couplé Placé", flag="est_couple_place",
        a_trouver="les 2 chevaux désignés finissent tous deux dans les 3 premiers",
        prelevement=0.23, mise_base=1.0, partants_min=8,
        frequence_offre=0.855, taux_reussite=0.184, roi_mesure=-18.1, n_mesure=2212,
        quand_le_jouer=(
            "Souvent perçu comme prudent parce qu'il tombe une fois sur cinq — mais "
            "son rapport ne compense jamais le prélèvement : -18,1 % chez nous, et "
            "-46,6 % dès que le rapport visé dépasse ×8."),
    ),
    ParisPMU(
        nom="Couplé Ordre", flag="est_couple_ordre",
        a_trouver="les 2 chevaux terminent 1er et 2e, dans l'ordre exact",
        prelevement=0.23, mise_base=1.0, partants_min=4,
        frequence_offre=0.139, taux_reussite=0.074, roi_mesure=-24.0, n_mesure=417,
        quand_le_jouer=(
            "Remplace le Couplé Gagnant sur les champs réduits, où il est parfois le "
            "SEUL couplé offert. Exiger l'ordre double la difficulté sans doubler le "
            "rapport."),
    ),
    ParisPMU(
        nom="Trio", flag="est_trio",
        a_trouver="les 3 chevaux désignés font le podium, dans n'importe quel ordre",
        prelevement=0.25, mise_base=1.0, partants_min=8,
        frequence_offre=0.837, taux_reussite=0.024, roi_mesure=-21.6, n_mesure=1658,
        quand_le_jouer=(
            "Rapport spectaculaire, réussite à 2,4 %. Son ROI brut de +102 % tenait "
            "à UN rapport à 4 526 € : sans lui, -21,6 %. À ne juger qu'en gains "
            "plafonnés, et à ne pas confondre avec un signal."),
    ),
    ParisPMU(
        nom="2sur4", flag="est_2sur4",
        a_trouver="2 des 4 chevaux désignés terminent dans les 4 premiers",
        prelevement=0.25, mise_base=3.0, partants_min=14,
        frequence_offre=0.464, taux_reussite=0.565, roi_mesure=-27.2, n_mesure=124,
        quand_le_jouer=(
            "Le taux de réussite le plus élevé du catalogue (56 %) et pourtant "
            "-27,2 % : le rapport est structurellement trop faible pour la mise de "
            "base de 3 €. Gagner souvent n'est pas gagner de l'argent."),
    ),
    ParisPMU(
        nom="Super 4", flag="est_super4",
        a_trouver="les 4 premiers dans l'ordre exact",
        prelevement=0.25, mise_base=1.0, partants_min=14,
        frequence_offre=0.235, taux_reussite=0.014, roi_mesure=-77.7, n_mesure=72,
        quand_le_jouer="Ordre exact sur 4 chevaux : réservé au jeu de loterie, jamais au rendement.",
    ),
    ParisPMU(
        nom="Trio Ordre", flag="est_trio_ordre",
        a_trouver="les 3 premiers dans l'ordre exact",
        prelevement=0.25, mise_base=1.0, partants_min=4,
        frequence_offre=0.144, taux_reussite=0.021, roi_mesure=-66.0, n_mesure=94,
        quand_le_jouer="Offert surtout sur les champs réduits. Rendement mesuré très négatif.",
    ),
    ParisPMU(
        nom="Multi", flag="est_multi",
        a_trouver="les 4 premiers dans le désordre, parmi 4 à 7 chevaux au choix",
        prelevement=0.30, mise_base=3.0, partants_min=14,
        frequence_offre=0.159, taux_reussite=0.113, roi_mesure=-19.0, n_mesure=145,
        quand_le_jouer=(
            "Le prélèvement le plus lourd du PMU, et la mise grimpe vite avec le "
            "nombre de chevaux (en 4 : 3 € ; en 7 : 105 €). Nos Multi en 4 et 5 "
            "mesurent -95 % et -99 %."),
    ),
    ParisPMU(
        nom="Quinté+", flag="est_quinte",
        a_trouver="les 5 premiers, l'ordre exact payant le rapport plein",
        prelevement=0.26, mise_base=2.0, partants_min=14,
        frequence_offre=0.019, taux_reussite=None, roi_mesure=None, n_mesure=0,
        quand_le_jouer=(
            "Une course par jour. Pool massif donc rapports élevés, mais échantillon "
            "trop mince chez nous pour en dire quoi que ce soit d'honnête."),
    ),
    ParisPMU(
        nom="Pick5", flag="est_pick5",
        a_trouver="les 5 premiers d'une course désignée, dans le désordre",
        prelevement=0.26, mise_base=1.0, partants_min=14,
        frequence_offre=0.038, taux_reussite=None, roi_mesure=None, n_mesure=23,
        quand_le_jouer="Échantillon insuffisant : aucune conclusion à en tirer pour l'instant.",
    ),
)

PAR_NOM: dict[str, ParisPMU] = {p.nom: p for p in CATALOGUE}
PAR_FLAG: dict[str, ParisPMU] = {p.flag: p for p in CATALOGUE}


def prelevement(nom_pari: str | None) -> float:
    """Part gardée par le PMU sur ce type. 0.25 par défaut (hypothèse prudente :
    on ne sous-estime jamais l'adversaire principal)."""
    p = PAR_NOM.get(_famille(nom_pari))
    return p.prelevement if p else 0.25


def mise_base(nom_pari: str | None) -> float:
    """Mise unitaire PMU : proposer moins n'est pas jouable au guichet."""
    p = PAR_NOM.get(_famille(nom_pari))
    return p.mise_base if p else 1.0


def partants_min(nom_pari: str | None) -> int:
    """Champ minimal sous lequel le PMU n'ouvre pas ce pari."""
    p = PAR_NOM.get(_famille(nom_pari))
    return p.partants_min if p else 0


def _famille(nom_pari: str | None) -> str:
    """« Multi en 5 », « Mini Multi en 6 » → « Multi ». Les variantes ne diffèrent
    que par le nombre de chevaux couverts, pas par la règle ni le prélèvement."""
    if not nom_pari:
        return ""
    n = str(nom_pari)
    if "Multi" in n:
        return "Multi"
    if n.startswith("Quinté"):
        return "Quinté+"
    if n.startswith("Tiercé"):
        return "Trio"          # même famille de podium, prélèvement voisin
    return n
