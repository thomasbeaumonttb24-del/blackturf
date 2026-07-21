"""
Audit de COUVERTURE du scraping BlackTurf — READ-ONLY (aucune écriture).

Répond à deux questions :
  1. Quelles sources scrapent réellement ? (scrape_log : dernier ok / erreur / cadence)
  2. Chaque donnée scrapée arrive-t-elle bien en base ? (taux de remplissage des
     colonnes qui alimentent les features ML)

Une feature dont la colonne source est vide à ~100 % est une feature MORTE :
le modèle la voit comme une constante (cf. audit 2026-06-17). Ce script mesure
ce taux de vide, source par source, sur une fenêtre récente.

Usage (dans le conteneur api du VPS) :
    cd /app && PYTHONPATH=/app python scripts/scrape_coverage.py [N_JOURS]
    (N_JOURS = fenêtre d'analyse, défaut 7)

Sortie : tableaux lisibles en console. N'écrit RIEN en base.
"""
import asyncio
import sys
from sqlalchemy import text

from db.database import AsyncSessionLocal


def _bar(pct: float, width: int = 20) -> str:
    n = int(round(pct / 100 * width))
    return "█" * n + "·" * (width - n)


def _line(label: str, n_ok: int, n_tot: int) -> str:
    pct = (100.0 * n_ok / n_tot) if n_tot else 0.0
    flag = "  ⚠ VIDE" if pct < 5 else ("  ~ faible" if pct < 40 else "")
    return f"  {label:<34} {pct:5.1f}%  {_bar(pct)}  ({n_ok}/{n_tot}){flag}"


async def section_scrape_log(session, n_jours: int) -> None:
    print("\n" + "=" * 78)
    print(f"1. SCRAPE_LOG — activité par source (dernières {n_jours*24} h)")
    print("=" * 78)
    rows = (await session.execute(text("""
        SELECT source,
               COUNT(*) FILTER (WHERE statut = 'ok')     AS oks,
               COUNT(*) FILTER (WHERE statut = 'erreur') AS errs,
               MAX(created_at) FILTER (WHERE statut = 'ok')     AS last_ok,
               MAX(created_at) FILTER (WHERE statut = 'erreur') AS last_err,
               COALESCE(SUM(nb_courses), 0)  AS courses,
               COALESCE(SUM(nb_partants), 0) AS partants
        FROM scrape_log
        WHERE created_at > now() - (:nj || ' days')::interval
        GROUP BY source
        ORDER BY source
    """), {"nj": str(n_jours)})).fetchall()

    if not rows:
        print("  (aucune ligne scrape_log sur la fenêtre — orchestrateur arrêté ?)")
        return
    print(f"  {'source':<14}{'ok':>5}{'err':>5}  {'dernier_ok':<20}{'courses':>8}{'partants':>9}")
    print("  " + "-" * 74)
    for r in rows:
        src, oks, errs, last_ok, last_err, courses, partants = r
        last_ok_s = last_ok.strftime("%Y-%m-%d %H:%M") if last_ok else "JAMAIS"
        warn = "  ⚠" if (oks == 0 or (errs and errs >= oks)) else ""
        print(f"  {src:<14}{oks:>5}{errs:>5}  {last_ok_s:<20}{courses:>8}{partants:>9}{warn}")


async def section_participation_fill(session, n_jours: int) -> None:
    print("\n" + "=" * 78)
    print(f"2. PARTICIPATIONS — taux de remplissage des cotes/signaux (≤ {n_jours} j)")
    print("=" * 78)
    r = (await session.execute(text("""
        SELECT
          COUNT(*) AS tot,
          COUNT(cote_pmu)             AS pmu,
          COUNT(cote_geny)            AS geny,
          COUNT(cote_bzh)             AS bzh,
          COUNT(cote_winamax)         AS winamax,
          COUNT(cote_betclic)         AS betclic,
          COUNT(cote_unibet)          AS unibet,
          COUNT(cote_betfair_exchange) AS betfair,
          COUNT(rang_pronostic_geny)  AS rang_geny,
          COUNT(jours_depuis_derniere) AS repos,
          COUNT(avis_entraineur)      AS avis,
          COUNT(tendance_force)       AS tendance,
          COUNT(changement_jockey) FILTER (WHERE changement_jockey) AS chg_jockey
        FROM participations p
        JOIN courses c ON c.course_id = p.course_id
        WHERE c.date_heure::date > current_date - (:nj || ' days')::interval
          AND p.non_partant = false
    """), {"nj": str(n_jours)})).one()
    tot = r[0]
    if not tot:
        print("  (aucun partant sur la fenêtre)")
        return
    print(_line("cote_pmu        (PMU)",        r[1],  tot))
    print(_line("cote_geny       (Geny)",       r[2],  tot))
    print(_line("cote_bzh        (Zeturf)",     r[3],  tot))
    print(_line("cote_winamax    (Winamax)",    r[4],  tot))
    print(_line("cote_betclic    (Betclic)",    r[5],  tot))
    print(_line("cote_unibet     (Unibet)",     r[6],  tot))
    print(_line("cote_betfair    (Betfair)",    r[7],  tot))
    print(_line("rang_pronostic_geny",          r[8],  tot))
    print(_line("jours_depuis_derniere",        r[9],  tot))
    print(_line("avis_entraineur (PMU)",        r[10], tot))
    print(_line("tendance_force  (PMU)",        r[11], tot))
    print(_line("changement_jockey=true",       r[12], tot))


async def section_course_fill(session, n_jours: int) -> None:
    print("\n" + "=" * 78)
    print(f"3. COURSES — pénétromètre / pools / météo (≤ {n_jours} j)")
    print("=" * 78)
    r = (await session.execute(text("""
        SELECT
          COUNT(*) AS tot,
          COUNT(penetrometre_coef)     AS penetro,
          COUNT(pool_total_centimes)   AS pool_tot,
          COUNT(pool_gagnant_centimes) AS pool_gag,
          COUNT(pool_gagnant_evolution) AS pool_evo
        FROM courses
        WHERE date_heure::date > current_date - (:nj || ' days')::interval
    """), {"nj": str(n_jours)})).one()
    tot = r[0]
    if not tot:
        print("  (aucune course sur la fenêtre)")
        return
    print(_line("penetrometre_coef (FranceGalop/PMU)", r[1], tot))
    print(_line("pool_total       (PMU smart money)",  r[2], tot))
    print(_line("pool_gagnant     (PMU)",              r[3], tot))
    print(_line("pool_evolution   (PMU)",              r[4], tot))

    meteo = (await session.execute(text("""
        SELECT COUNT(DISTINCT mc.course_id)
        FROM meteo_courses mc
        JOIN courses c ON c.course_id = mc.course_id
        WHERE c.date_heure::date > current_date - (:nj || ' days')::interval
    """), {"nj": str(n_jours)})).scalar()
    print(_line("météo (lignes meteo_courses)", int(meteo or 0), tot))

    presse = (await session.execute(text("""
        SELECT COUNT(DISTINCT pp.course_id)
        FROM pronostics_presse pp
        JOIN courses c ON c.course_id = pp.course_id
        WHERE c.date_heure::date > current_date - (:nj || ' days')::interval
    """), {"nj": str(n_jours)})).scalar()
    print(_line("pronostics_presse (Paris-Turf/CanalTurf)", int(presse or 0), tot))


async def section_cheval_fill(session, n_jours: int) -> None:
    print("\n" + "=" * 78)
    print(f"4. CHEVAUX du jour — pedigree / running style / prix vente (≤ {n_jours} j)")
    print("=" * 78)
    r = (await session.execute(text("""
        WITH chx AS (
          SELECT DISTINCT ch.cheval_id, ch.pere, ch.mere, ch.running_style,
                 ch.taux_en_tete, ch.prix_vente_yearling
          FROM chevaux ch
          JOIN participations p ON p.cheval_id = ch.cheval_id
          JOIN courses c ON c.course_id = p.course_id
          WHERE c.date_heure::date > current_date - (:nj || ' days')::interval
        )
        SELECT COUNT(*) AS tot,
               COUNT(pere)               AS pere,
               COUNT(mere)               AS mere,
               COUNT(running_style)      AS rs,
               COUNT(NULLIF(taux_en_tete, 0)) AS tet,
               COUNT(NULLIF(prix_vente_yearling, 0)) AS prix
        FROM chx
    """), {"nj": str(n_jours)})).one()
    tot = r[0]
    if not tot:
        print("  (aucun cheval sur la fenêtre)")
        return
    print(_line("pere   (généalogie — utilisé)",   r[1], tot))
    print(_line("mere   (scrapé mais NON utilisé)", r[2], tot))
    print(_line("running_style (France Galop)",     r[3], tot))
    print(_line("taux_en_tete  (>0)",                r[4], tot))
    print(_line("prix_vente_yearling (>0)",          r[5], tot))


async def section_dormant_hist(session, n_jours: int) -> None:
    print("\n" + "=" * 78)
    print("5. HISTORIQUE_COURSES — colonnes dormantes (features dynamics/draw)")
    print("=" * 78)
    r = (await session.execute(text("""
        SELECT COUNT(*) AS tot,
               COUNT(corde)              AS corde,
               COUNT(terrain)            AS terrain,
               COUNT(indice_vitesse)     AS vitesse,
               COUNT(reduction_km)       AS reduction,
               COUNT(acceleration_label) AS accel
        FROM historique_courses
        WHERE date_course > current_date - (:nj || ' days')::interval * 30
    """), {"nj": str(n_jours)})).one()
    tot = r[0]
    if not tot:
        print("  (aucune ligne historique sur la fenêtre)")
        return
    print(f"  (sur {tot} lignes d'historique récentes)")
    print(_line("corde         (→ draw_bias_score)",   r[1], tot))
    print(_line("terrain       (→ pref_terrain/sire)", r[2], tot))
    print(_line("indice_vitesse(→ vitesse_relative)",  r[3], tot))
    print(_line("reduction_km  (→ dyn_reduction)",     r[4], tot))
    print(_line("acceleration  (→ dyn_accelere)",      r[5], tot))


async def section_stats_tables(session) -> None:
    print("\n" + "=" * 78)
    print("6. TABLES STATS / SUSPENSIONS — présence de données")
    print("=" * 78)
    for tbl, label in [
        ("stats_jockeys", "stats_jockeys (Turfoo)"),
        ("stats_entraineurs", "stats_entraineurs (Turfoo)"),
        ("associations_jockey_entraineur", "associations J×E (calcul interne)"),
        ("suspensions_professionnels", "suspensions (NON utilisé par le modèle)"),
        ("temps_passage", "temps_passage (France Galop)"),
    ]:
        try:
            n = (await session.execute(text(f"SELECT COUNT(*) FROM {tbl}"))).scalar()
            warn = "  ⚠ VIDE" if not n else ""
            print(f"  {label:<44} {int(n or 0):>8} lignes{warn}")
        except Exception as e:
            print(f"  {label:<44} erreur: {str(e)[:40]}")


async def main(n_jours: int = 7) -> None:
    print("\n" + "#" * 78)
    print(f"#  BLACKTURF — AUDIT COUVERTURE SCRAPING  (fenêtre {n_jours} j)  [READ-ONLY]")
    print("#" * 78)
    async with AsyncSessionLocal() as session:
        await section_scrape_log(session, n_jours)
        await section_participation_fill(session, n_jours)
        await section_course_fill(session, n_jours)
        await section_cheval_fill(session, n_jours)
        await section_dormant_hist(session, n_jours)
        await section_stats_tables(session)
    print("\nLecture : ⚠ VIDE (<5%) = source cassée OU feature morte (constante pour")
    print("le modèle). ~ faible (<40%) = couverture partielle. Cf. audit 2026-06-17.\n")


if __name__ == "__main__":
    nj = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    asyncio.run(main(nj))
