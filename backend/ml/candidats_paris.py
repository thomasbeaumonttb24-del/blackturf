"""
Tous les paris CANDIDATS d'une course, retenus ou non, figés avant le départ puis
réglés en observation.

Pourquoi (audit du 23/09/2026, P1 « l'apprentissage des types ne suffit pas à
choisir le meilleur pari de la course ») : on ne règle aujourd'hui que les tickets
RETENUS par les plans. On ne peut donc pas savoir si le Couplé Placé écarté aurait
mieux payé que le Simple Gagnant joué sur la même course, au même horaire. Ce
journal garde chaque candidat de `combo_bets.enumerate_bet_candidates` — la liste
même que voit le générateur de plans — avec sa probabilité, son rapport estimé, son
EV et les profils qui l'ont retenu, puis le règle aux vrais rapports PMU.

Observation seulement : rien ici n'entre dans une décision.
"""
from __future__ import annotations

import json
from typing import Optional

import structlog
from sqlalchemy import text

log = structlog.get_logger(module="candidats_paris")


def cle_pari(type_pari: str, numeros) -> str:
    """Identité d'un pari : type + chevaux triés (l'ordre joué ne distingue pas
    deux candidats de la même formule)."""
    return f"{type_pari}|{'-'.join(str(int(n)) for n in sorted(numeros))}"


def cles_retenues(plans: dict[str, dict]) -> dict[str, list[str]]:
    """{cle_pari: [profils]} des tickets effectivement émis dans les plans."""
    out: dict[str, list[str]] = {}
    for profil, plan in (plans or {}).items():
        for niveau in (plan or {}).get("niveaux") or []:
            for pari in niveau.get("paris") or []:
                nums = [c.get("numero") for c in pari.get("chevaux") or []
                        if c.get("numero") is not None]
                if not nums or not pari.get("type"):
                    continue
                profils = out.setdefault(cle_pari(pari["type"], nums), [])
                if profil not in profils:
                    profils.append(profil)
    return out


def preds_candidats(preds: list[dict]) -> list[dict]:
    """Même entrée que `mise_calculator.generer_plan` donne à l'énumération."""
    return [{"numero": p["numero"],
             "nom": p.get("nom_cheval") or p.get("nom") or f"N°{p['numero']}",
             "proba_top1": p.get("proba_top1"), "proba_top3": p.get("proba_top3"),
             "cote_pmu": p.get("cote_pmu")}
            for p in preds if not p.get("non_partant") and p.get("numero") is not None]


def lignes_candidats(cands: list[dict], retenus: dict[str, list[str]]) -> list[dict]:
    """Une ligne par candidat distinct (le premier rencontré fait foi)."""
    lignes: dict[str, dict] = {}
    for c in cands or []:
        nums = [int(h["numero"]) for h in c.get("chevaux") or [] if h.get("numero") is not None]
        if not nums or not c.get("type_pari"):
            continue
        cle = cle_pari(c["type_pari"], nums)
        if cle in lignes:
            continue
        lignes[cle] = {
            "cle": cle, "type_pari": c["type_pari"], "numeros": nums,
            "niveau": c.get("niveau"),
            "proba_gain": c.get("proba_gain"), "rapport_estime": c.get("rapport_estime"),
            "ev": c.get("ev"), "edge": c.get("edge"),
            "cotes": {str(int(h["numero"])): h.get("cote") for h in c.get("chevaux") or []
                      if h.get("numero") is not None},
            "retenu_par": retenus.get(cle, []),
        }
    return list(lignes.values())


async def enregistrer_candidats(session, course_id: str, preds: list[dict],
                                course_info: dict, plans: dict[str, dict],
                                model_version_id: Optional[str] = None) -> int:
    """Remplace les candidats NON réglés de la course par ceux de cette émission.

    Appelé à chaque re-prédiction avant le départ (cf. `record_profil_runs`) : le
    dernier état avant départ fait foi, comme pour les plans figés.
    """
    from ml.combo_bets import enumerate_bet_candidates

    lignes = lignes_candidats(enumerate_bet_candidates(preds_candidats(preds), course_info),
                              cles_retenues(plans))
    if not lignes:
        return 0
    await session.execute(text(
        "DELETE FROM candidats_paris WHERE course_id = :cid AND statut = 'pending'"),
        {"cid": course_id})
    for l in lignes:
        await session.execute(text("""
            INSERT INTO candidats_paris
                (course_id, cle, type_pari, numeros, niveau, proba_gain, rapport_estime,
                 ev, edge, cotes, retenu_par, model_version_id, statut)
            VALUES (:cid, :cle, :type, CAST(:nums AS jsonb), :niv, :p, :rap, :ev, :edge,
                    CAST(:cotes AS jsonb), CAST(:ret AS jsonb), :mv, 'pending')
            ON CONFLICT (course_id, cle) DO NOTHING
        """), {"cid": course_id, "cle": l["cle"], "type": l["type_pari"],
               "nums": json.dumps(l["numeros"]), "niv": l["niveau"], "p": l["proba_gain"],
               "rap": l["rapport_estime"], "ev": l["ev"], "edge": l["edge"],
               "cotes": json.dumps(l["cotes"]), "ret": json.dumps(l["retenu_par"]),
               "mv": model_version_id})
    return len(lignes)


async def regler_candidats(session, course_id: str) -> dict:
    """Règle les candidats pending/partial de la course aux rapports PMU réels.

    `gain_1eur` = retour d'un euro misé (0 si perdu) ; None tant qu'un gagnant n'a
    pas son rapport publié (statut 'partial', retenté au rattrapage). Un pari
    touché par un non-partant est remboursé : statut 'rembourse', exclu des ROI.
    """
    from services.bet_settlement import settle_pari

    res = (await session.execute(text("""
        SELECT r.classement, r.rapports, c.nb_partants, r.rapports_detail
        FROM resultats r JOIN courses c ON c.course_id = r.course_id
        WHERE r.course_id = :cid
    """), {"cid": course_id})).first()
    if not res or not res[0]:
        return {"regles": 0}
    classement = res[0] if isinstance(res[0], list) else []
    non_partants = {int(r[0]) for r in (await session.execute(text(
        "SELECT numero FROM participations WHERE course_id = :cid AND non_partant = true"),
        {"cid": course_id})).all() if r[0] is not None}
    rows = (await session.execute(text("""
        SELECT cle, type_pari, numeros FROM candidats_paris
        WHERE course_id = :cid AND statut IN ('pending', 'partial')
    """), {"cid": course_id})).all()
    n = 0
    for cle, type_pari, numeros in rows:
        nums = numeros if isinstance(numeros, list) else json.loads(numeros)
        r = settle_pari(type_pari, nums, classement, res[1] or {}, res[2] or len(classement),
                        res[3] or None, non_partants)
        if r.get("rembourse"):
            statut, gain = "rembourse", None
        elif r.get("gagne") and r.get("rapport_reel") is None:
            statut, gain = "partial", None
        else:
            statut = "settled"
            gain = float(r["rapport_reel"]) if r.get("gagne") else 0.0
        await session.execute(text("""
            UPDATE candidats_paris SET statut = :st, gagne = :g, gain_1eur = :gain,
                   note_reglement = :note, settled_at = now()
            WHERE course_id = :cid AND cle = :cle
        """), {"st": statut, "g": bool(r.get("gagne")), "gain": gain,
               "note": (r.get("note") or None), "cid": course_id, "cle": cle})
        n += 1
    return {"regles": n}


async def regler_candidats_en_retard(session, jours: int = 7) -> dict:
    """Rattrapage : courses terminées de la fenêtre avec des candidats non réglés."""
    cids = [r[0] for r in (await session.execute(text("""
        SELECT DISTINCT cp.course_id FROM candidats_paris cp
        JOIN resultats r ON r.course_id = cp.course_id
        WHERE cp.statut IN ('pending', 'partial')
          AND cp.created_at > now() - make_interval(days => :j)
    """), {"j": jours})).all()]
    total = 0
    for cid in cids:
        total += (await regler_candidats(session, cid))["regles"]
        await session.commit()
    return {"courses": len(cids), "regles": total}
