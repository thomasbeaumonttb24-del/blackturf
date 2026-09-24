"""Recalcul COMPLET des ELO avec l'algorithme actuel (ml/elo.py) — sûr en production.

    python -m scripts.elo_recalcul            # à blanc : calcule, mesure, n'écrit rien
    python -m scripts.elo_recalcul --appliquer

Pourquoi pas `scripts/elo_rejeu.py` : il remet tout à 1500, vide `elo_historique`
puis rejoue en validant tous les 500 courses. Pendant des heures le site sert des
ELO à moitié recalculés, et une course terminée pendant le rejeu est comptée deux
fois ou pas du tout. Ici :

1. Tout est calculé EN MÉMOIRE, course par course dans l'ordre chronologique, avec
   `resoudre_course` — la fonction même de la mise à jour en direct. Les lignes
   produites (historique, snapshots pré-course, ratings finaux) vont dans des
   tables de travail `elo_recalcul_*`, hors de toute table servie.
2. À blanc, on s'arrête là et on MESURE sur les 180 derniers jours : l'ELO
   pré-course (ancien = snapshots en base, nouveau = recalcul) range-t-il bien les
   chevaux dans l'ordre d'arrivée ? Et que deviennent les chevaux multi-fautifs ?
3. Avec --appliquer, une SEULE transaction verrouille `chevaux` puis
   `elo_historique`, rejoue les courses terminées entre-temps, et remplace
   ratings, historique et snapshots `participations.elo_avant_*`. Tout ou rien.

Après application : `scripts/recompute_features_prerace.py`, puis le retrain de
nuit (gate champion/challenger) — les features stockées portent encore l'ancien ELO.
"""
import argparse
import asyncio
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from db.database import AsyncSessionLocal
from ml.elo import (ELO_INITIAL, champ_elo, classement_elo, get_k_factor,
                    resoudre_course)

CHAMPS = ("elo_score_plat", "elo_score_trot", "elo_score_obstacle")
LOT_COURSES = 2000
LOT_ECRITURE = 20000
FENETRE_MESURE_JOURS = 180


class Etat:
    """Ratings et expérience de chaque cheval, au fil du rejeu."""

    def __init__(self):
        self.notes: dict[str, dict] = {}
        self.nb: dict[str, dict] = {}

    def note(self, cid):
        n = self.notes.get(cid)
        if n is None:
            n = self.notes[cid] = {"elo_score_global": ELO_INITIAL,
                                   **{c: ELO_INITIAL for c in CHAMPS}}
            self.nb[cid] = {"total": 0, **{c: 0 for c in CHAMPS}}
        return n


def classement_course(classement_json, num2ch: dict) -> list[dict]:
    brut = []
    for e in classement_json or []:
        try:
            num = int(e.get("numero"))
        except (TypeError, ValueError, AttributeError):
            continue
        cid = num2ch.get(num)
        if cid is None or (e.get("position") is None and not e.get("incident")):
            continue
        brut.append({"cheval_id": cid, "position": e.get("position"),
                     "incident": e.get("incident"), "disqualifie": e.get("disqualifie")})
    vus, uniques = set(), []
    for r in classement_elo(brut):
        if r["cheval_id"] not in vus:
            vus.add(r["cheval_id"])
            uniques.append(r)
    return uniques


def jouer_course(etat: Etat, course: dict, parts: list, hist: list, snaps: list):
    """Snapshots pré-course de TOUS les partants, puis mise à jour ELO.
    Retourne (classement, ratings de discipline pré-course) pour la mesure."""
    for pid, _num, cid, *_ in parts:
        n = etat.note(cid)
        snaps.append((pid, n["elo_score_global"], n["elo_score_plat"],
                      n["elo_score_trot"], n["elo_score_obstacle"]))
    num2ch = {int(p[1]): p[2] for p in parts if p[1] is not None}
    valides = classement_course(course["classement"], num2ch)
    champ = champ_elo(course["discipline"] or "plat")
    avant = {r["cheval_id"]: etat.note(r["cheval_id"])[champ] for r in valides}
    if len(valides) < 2:
        return valides, avant
    disc = {cid: etat.notes[cid][champ] for cid in avant}
    glob = {cid: etat.notes[cid]["elo_score_global"] for cid in avant}
    nb_disc = {cid: etat.nb[cid][champ] for cid in avant}
    nb_tot = {cid: etat.nb[cid]["total"] for cid in avant}
    k = get_k_factor(course["niveau_course"], course["allocation"])
    res = resoudre_course(valides, disc, glob, nb_disc, nb_tot, k)
    jour = course["date_heure"].date()
    for cid, r in res.items():
        etat.notes[cid][champ] = r["disc_apres"]
        etat.notes[cid]["elo_score_global"] = r["glob_apres"]
        etat.nb[cid][champ] += 1
        etat.nb[cid]["total"] += 1
        hist.append((cid, course["course_id"], jour, (course["discipline"] or "plat")[:20],
                     r["disc_avant"], r["disc_apres"], r["delta_disc"]))
    return valides, avant


class Mesure:
    """Concordance des paires : part des paires de partants que l'ELO pré-course
    range dans l'ordre d'arrivée (égalité de rating = ½). Plus haut = meilleur."""

    def __init__(self):
        self.ok = {"ancien": 0.0, "nouveau": 0.0}
        self.n = {"ancien": 0, "nouveau": 0}
        self.gagnant = {"ancien": [0, 0], "nouveau": [0, 0]}
        # Log-vraisemblance moyenne du vainqueur sous P(i gagne) ∝ 10^(r_i/400) :
        # la probabilité que l'ELO lui-même donne à chaque partant. Plus haut = mieux.
        self.ll = {"ancien": [0.0, 0], "nouveau": [0.0, 0]}
        self.top3 = {"ancien": [0, 0], "nouveau": [0, 0]}
        # Taux « meilleur ELO gagnant » PAR MOIS : un avantage concentré sur une
        # période (ex. snapshots rétro-remplis) trahit un artefact, pas un signal.
        self.par_mois: dict = {}
        self.mois_courant = None
        # Écart-type des notes DANS chaque course : c'est l'échelle que lit le
        # modèle (elo_vs_moyenne, elo_vs_max). Un changement d'échelle entre
        # l'ancien et le nouvel ELO = écart train/serve jusqu'au retrain.
        self.dispersion = {"ancien": [], "nouveau": []}

    def ajouter(self, cle, valides, rating):
        rangs = [(r["position"], rating[r["cheval_id"]]) for r in valides
                 if rating.get(r["cheval_id"]) is not None]
        if len(rangs) < 2:
            return
        for i in range(len(rangs)):
            for j in range(i + 1, len(rangs)):
                (pi, ri), (pj, rj) = rangs[i], rangs[j]
                if pi == pj:
                    continue
                devant, derriere = (ri, rj) if pi < pj else (rj, ri)
                self.ok[cle] += 1.0 if devant > derriere else (0.5 if devant == derriere else 0.0)
                self.n[cle] += 1
        meilleur = max(rangs, key=lambda x: x[1])
        _moy = sum(r for _, r in rangs) / len(rangs)
        self.dispersion[cle].append((sum((r - _moy) ** 2 for _, r in rangs) / len(rangs)) ** 0.5)
        if self.mois_courant:
            m = self.par_mois.setdefault(self.mois_courant, {"ancien": [0, 0], "nouveau": [0, 0]})
            m[cle][0] += 1 if meilleur[0] == 1 else 0
            m[cle][1] += 1
        self.gagnant[cle][0] += 1 if meilleur[0] == 1 else 0
        self.gagnant[cle][1] += 1
        self.top3[cle][0] += 1 if meilleur[0] <= 3 else 0
        self.top3[cle][1] += 1
        import math
        vainqueurs = [r for p, r in rangs if p == 1]
        if len(vainqueurs) == 1:
            mx = max(r for _, r in rangs)
            z = sum(10 ** ((r - mx) / 400.0) for _, r in rangs)
            self.ll[cle][0] += (vainqueurs[0] - mx) / 400.0 * math.log(10) - math.log(z)
            self.ll[cle][1] += 1

    def rapport_dispersion(self):
        import statistics
        d = {k: statistics.median(v) for k, v in self.dispersion.items() if v}
        if len(d) == 2:
            print(f"[echelle] écart-type des notes dans une course (médiane) : ancien "
                  f"{d['ancien']:.1f} · nouveau {d['nouveau']:.1f} · rapport "
                  f"{d['nouveau'] / max(d['ancien'], 1e-9):.2f}", flush=True)

    def rapport_mensuel(self):
        for mois in sorted(self.par_mois):
            m = self.par_mois[mois]
            a, n = m["ancien"], m["nouveau"]
            print(f"[mois] {mois} : meilleur ELO gagnant ancien {a[0] / max(a[1], 1):.3f}"
                  f" · nouveau {n[0] / max(n[1], 1):.3f} ({n[1]} courses)", flush=True)

    def rapport(self):
        for cle in ("ancien", "nouveau"):
            if self.n[cle]:
                g, t = self.gagnant[cle]
                t3, n3 = self.top3[cle]
                ll, nll = self.ll[cle]
                print(f"[mesure] ELO {cle:7s}: concordance des paires {self.ok[cle] / self.n[cle]:.4f}"
                      f" sur {self.n[cle]} paires · meilleur ELO gagnant {g / max(t, 1):.3f}"
                      f" ({g}/{t} courses) · meilleur ELO dans les 3 {t3 / max(n3, 1):.3f}"
                      f" · log-vrais. gagnant {ll / max(nll, 1):.4f}", flush=True)


async def lire_courses(session, deja: set | None = None) -> list[dict]:
    rows = (await session.execute(text("""
        SELECT c.course_id, c.date_heure, c.discipline, c.niveau_course, c.allocation
        FROM courses c JOIN resultats r USING (course_id)
        WHERE c.statut = 'termine' AND c.date_heure IS NOT NULL
        ORDER BY c.date_heure, c.course_id
    """))).all()
    return [dict(r._mapping) for r in rows if not deja or r[0] not in deja]


async def lire_lot(session, ids: list[str]):
    cls = dict((await session.execute(text(
        "SELECT course_id, classement FROM resultats WHERE course_id = ANY(:ids)"),
        {"ids": ids})).all())
    parts: dict[str, list] = {}
    for r in (await session.execute(text("""
        SELECT participation_id, numero, cheval_id, course_id,
               elo_avant_plat, elo_avant_trot, elo_avant_obstacle
        FROM participations WHERE course_id = ANY(:ids) AND cheval_id IS NOT NULL
    """), {"ids": ids})).all():
        parts.setdefault(r[3], []).append(r)
    return cls, parts


async def ecrire_travail(session, hist: list, snaps: list):
    if hist:
        await session.execute(text("""
            INSERT INTO elo_recalcul_hist VALUES
            (:c, :co, :d, :di, :a, :p, :de)"""),
            [{"c": h[0], "co": h[1], "d": h[2], "di": h[3], "a": h[4], "p": h[5], "de": h[6]}
             for h in hist])
    if snaps:
        await session.execute(text("""
            INSERT INTO elo_recalcul_snap VALUES (:id, :g, :p, :t, :o)
            ON CONFLICT (participation_id) DO NOTHING"""),
            [{"id": s[0], "g": s[1], "p": s[2], "t": s[3], "o": s[4]} for s in snaps])
    hist.clear()
    snaps.clear()


async def rejouer(session, etat, courses, hist, snaps, mesure=None, depuis=None,
                  vider=None, jeter=False):
    t0 = time.time()
    for i in range(0, len(courses), LOT_COURSES):
        lot = courses[i:i + LOT_COURSES]
        cls, parts = await lire_lot(session, [c["course_id"] for c in lot])
        for c in lot:
            c["classement"] = cls.get(c["course_id"])
            p = parts.get(c["course_id"], [])
            valides, avant = jouer_course(etat, c, p, hist, snaps)
            c.pop("classement", None)
            if mesure is not None and depuis and c["date_heure"] >= depuis and len(valides) >= 2:
                mesure.mois_courant = c["date_heure"].strftime("%Y-%m")
                idx = {"elo_score_plat": 4, "elo_score_trot": 5, "elo_score_obstacle": 6}[
                    champ_elo(c["discipline"] or "plat")]
                ancien = {r[2]: r[idx] for r in p}
                mesure.ajouter("ancien", valides, ancien)
                mesure.ajouter("nouveau", valides, avant)
        if vider and len(hist) + len(snaps) >= LOT_ECRITURE:
            await vider()
        elif jeter:          # à blanc : rien ne sera écrit, inutile de tout garder
            hist.clear()
            snaps.clear()
        print(f"[elo] {min(i + LOT_COURSES, len(courses))}/{len(courses)} courses"
              f" ({time.time() - t0:.0f}s)", flush=True)


async def fautifs(session, etat: Etat):
    """Chevaux fautifs sur au moins la moitié de 5+ sorties récentes (musique) :
    rang percentile de leur ELO trot, ancien (base) vs recalculé."""
    rows = (await session.execute(text("""
        SELECT DISTINCT ON (p.cheval_id) p.cheval_id, ch.nom, p.musique, ch.elo_score_trot
        FROM participations p JOIN chevaux ch USING (cheval_id)
        JOIN courses c USING (course_id)
        WHERE c.date_heure > NOW() - INTERVAL '60 days' AND p.musique IS NOT NULL
          AND c.discipline IN ('Attelé', 'Monté')
        ORDER BY p.cheval_id, c.date_heure DESC
    """))).all()
    from ml.features import compute_allure_regularite
    anciens = sorted(float(r[3] or ELO_INITIAL) for r in rows)
    nouveaux = sorted(etat.notes.get(r[0], {}).get("elo_score_trot", ELO_INITIAL) for r in rows)

    def pct(val, trie):
        import bisect
        return bisect.bisect_left(trie, val) / max(len(trie), 1)

    cibles = []
    for cid, nom, musique, ancien in rows:
        taux, _, n = compute_allure_regularite(musique)
        if n >= 5 and taux >= 0.5:
            nouveau = etat.notes.get(cid, {}).get("elo_score_trot", ELO_INITIAL)
            cibles.append((nom, musique, pct(float(ancien or ELO_INITIAL), anciens),
                           pct(nouveau, nouveaux)))
    if cibles:
        moy_a = sum(c[2] for c in cibles) / len(cibles)
        moy_n = sum(c[3] for c in cibles) / len(cibles)
        print(f"[fautifs] {len(cibles)} trotteurs fautifs ≥50 % : percentile ELO moyen "
              f"ancien {moy_a:.2f} → nouveau {moy_n:.2f}", flush=True)
        for nom, mus, a, n in sorted(cibles, key=lambda c: -c[2])[:10]:
            print(f"[fautifs]   {nom:25s} {mus[:14]:14s} percentile {a:.2f} → {n:.2f}", flush=True)


VARIANTES = {
    # nom : réglages de ml.elo (le reste reste à sa valeur par défaut)
    "nouveau": {},
    "k_x2": {"K_MULTIPLICATEUR": 2.0},
    "k_x4": {"K_MULTIPLICATEUR": 4.0},
    "k_x8": {"K_MULTIPLICATEUR": 8.0},
    "k_x4_sans_provisoire": {"K_MULTIPLICATEUR": 4.0, "PROVISOIRE_K_MAX": 1.0},
    "sans_amorce": {"AMORCE_MIN_NOTES": 10 ** 9},
    "sans_k_provisoire": {"PROVISOIRE_K_MAX": 1.0},
    "ponderation_ecart": {"PONDERATION_ECART": True},
    "incident_demi": {"POIDS_DUEL_INCIDENT": 0.5},
    "incident_ignore": {"POIDS_DUEL_INCIDENT": 0.0},
    "type_ancien": {"AMORCE_MIN_NOTES": 10 ** 9, "PROVISOIRE_K_MAX": 1.0,
                    "PONDERATION_ECART": True, "POIDS_DUEL_INCIDENT": 0.0},
}


async def grille():
    """Rejoue l'historique RÉEL une fois par variante, à blanc, et compare les
    mesures. Ne crée ni n'écrit aucune table."""
    import ml.elo as E
    defauts = {k: getattr(E, k) for v in VARIANTES.values() for k in v}
    async with AsyncSessionLocal() as s:
        await s.execute(text("SET statement_timeout = 0"))
        depuis = datetime.now(timezone.utc) - timedelta(days=FENETRE_MESURE_JOURS)
        base = await lire_courses(s)
        print(f"[grille] {len(base)} courses, {len(VARIANTES)} variantes", flush=True)
        for nom, reglages in VARIANTES.items():
            for k, v in defauts.items():
                setattr(E, k, v)
            for k, v in reglages.items():
                setattr(E, k, v)
            mesure = Mesure()
            await rejouer(s, Etat(), [dict(c) for c in base], [], [], mesure, depuis,
                          jeter=True)
            print(f"[grille] ── {nom} {reglages}", flush=True)
            mesure.rapport()
        for k, v in defauts.items():
            setattr(E, k, v)


async def main(appliquer: bool):
    async with AsyncSessionLocal() as s:
        await s.execute(text("SET statement_timeout = 0"))
        for sql in () if not appliquer else ("DROP TABLE IF EXISTS elo_recalcul_hist",
                    "DROP TABLE IF EXISTS elo_recalcul_snap",
                    "DROP TABLE IF EXISTS elo_recalcul_notes",
                    """CREATE UNLOGGED TABLE elo_recalcul_hist (
                         cheval_id text, course_id text, date_course date,
                         discipline varchar(20), elo_avant float, elo_apres float,
                         delta_elo float)""",
                    """CREATE UNLOGGED TABLE elo_recalcul_snap (
                         participation_id text PRIMARY KEY, g float, p float,
                         t float, o float)"""):
            await s.execute(text(sql))
        await s.commit()

        etat, hist, snaps, mesure = Etat(), [], [], Mesure()
        depuis = datetime.now(timezone.utc) - timedelta(days=FENETRE_MESURE_JOURS)

        async def vider():
            await ecrire_travail(s, hist, snaps)
            await s.commit()

        courses = await lire_courses(s)
        print(f"[elo] {len(courses)} courses terminées à rejouer", flush=True)
        await rejouer(s, etat, courses, hist, snaps, mesure, depuis,
                      vider if appliquer else None, jeter=not appliquer)
        mesure.rapport()
        mesure.rapport_mensuel()
        mesure.rapport_dispersion()
        await fautifs(s, etat)

        if not appliquer:
            print("[elo] À BLANC : rien n'a été écrit. Relancer avec --appliquer.", flush=True)
            return
        await vider()

        # ── Sauvegarde de l'existant (réversibilité), hors transaction de bascule ─
        suffixe = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
        for sql in (
            f"CREATE TABLE elo_sauvegarde_chevaux_{suffixe} AS SELECT cheval_id, "
            "elo_score_global, elo_score_plat, elo_score_trot, elo_score_obstacle FROM chevaux",
            f"CREATE TABLE elo_sauvegarde_participations_{suffixe} AS SELECT participation_id, "
            "elo_avant_global, elo_avant_plat, elo_avant_trot, elo_avant_obstacle "
            "FROM participations WHERE elo_avant_global IS NOT NULL",
            f"CREATE TABLE elo_sauvegarde_historique_{suffixe} AS SELECT * FROM elo_historique",
        ):
            await s.execute(text(sql))
        await s.commit()
        print(f"[elo] sauvegarde de l'existant : tables elo_sauvegarde_*_{suffixe}", flush=True)

        # ── Bascule : une transaction, tout ou rien ──────────────────────────
        await s.execute(text("SET LOCAL lock_timeout = '120s'"))
        await s.execute(text("LOCK TABLE chevaux IN SHARE ROW EXCLUSIVE MODE"))
        await s.execute(text("LOCK TABLE elo_historique IN SHARE ROW EXCLUSIVE MODE"))
        deja = {c["course_id"] for c in courses}
        nouvelles = await lire_courses(s, deja)
        if nouvelles:
            print(f"[elo] {len(nouvelles)} course(s) terminée(s) pendant le calcul : rejouées",
                  flush=True)
            await rejouer(s, etat, nouvelles, hist, snaps)
        await ecrire_travail(s, hist, snaps)
        await s.execute(text("""CREATE TEMP TABLE elo_recalcul_notes (
            cheval_id text PRIMARY KEY, g float, p float, t float, o float)
            ON COMMIT DROP"""))
        items = list(etat.notes.items())
        for i in range(0, len(items), LOT_ECRITURE):
            await s.execute(text("INSERT INTO elo_recalcul_notes VALUES (:c, :g, :p, :t, :o)"),
                            [{"c": cid, "g": n["elo_score_global"], "p": n["elo_score_plat"],
                              "t": n["elo_score_trot"], "o": n["elo_score_obstacle"]}
                             for cid, n in items[i:i + LOT_ECRITURE]])
        await s.execute(text("""UPDATE chevaux SET elo_score_global = :e, elo_score_plat = :e,
            elo_score_trot = :e, elo_score_obstacle = :e"""), {"e": ELO_INITIAL})
        await s.execute(text("""UPDATE chevaux ch SET elo_score_global = n.g,
            elo_score_plat = n.p, elo_score_trot = n.t, elo_score_obstacle = n.o
            FROM elo_recalcul_notes n WHERE ch.cheval_id = n.cheval_id"""))
        await s.execute(text("DELETE FROM elo_historique"))
        await s.execute(text("""INSERT INTO elo_historique (elo_id, cheval_id, course_id,
            date_course, discipline, elo_avant, elo_apres, delta_elo)
            SELECT gen_random_uuid()::text, h.* FROM elo_recalcul_hist h"""))
        await s.execute(text("""UPDATE participations p SET elo_avant_global = s.g,
            elo_avant_plat = s.p, elo_avant_trot = s.t, elo_avant_obstacle = s.o
            FROM elo_recalcul_snap s WHERE p.participation_id = s.participation_id"""))
        n_hist = (await s.execute(text("SELECT COUNT(*) FROM elo_historique"))).scalar()
        await s.commit()
        for sql in ("DROP TABLE IF EXISTS elo_recalcul_hist",
                    "DROP TABLE IF EXISTS elo_recalcul_snap"):
            await s.execute(text(sql))
        await s.commit()
        print(f"[elo] APPLIQUÉ : {len(items)} chevaux notés, {n_hist} lignes d'historique."
              " Étape suivante : scripts/recompute_features_prerace.py", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--appliquer", action="store_true")
    ap.add_argument("--grille", action="store_true",
                    help="compare les variantes de l'algorithme, à blanc")
    args = ap.parse_args()
    asyncio.run(grille() if args.grille else main(args.appliquer))
