"""Rejeu ELO chronologique anti-fuite : reset + replay toutes les courses du plus
ancien au plus recent, snapshot elo_avant_* par participation AVANT chaque course."""
import asyncio
from sqlalchemy import text
from db.database import AsyncSessionLocal
from ml.elo import update_elo_after_race, ELO_INITIAL

async def main():
    async with AsyncSessionLocal() as s:
        print("[elo] reset ELO + clear historique", flush=True)
        await s.execute(text("UPDATE chevaux SET elo_score_global=:e, elo_score_plat=:e, elo_score_trot=:e, elo_score_obstacle=:e"), {"e": ELO_INITIAL})
        await s.execute(text("DELETE FROM elo_historique"))
        await s.commit()
        courses = (await s.execute(text("SELECT course_id, discipline, niveau_course, allocation FROM courses WHERE statut='termine' ORDER BY date_heure"))).all()
        print(f"[elo] {len(courses)} courses a rejouer", flush=True)
        n = 0
        for cid, disc, niv, dot in courses:
            await s.execute(text("UPDATE participations p SET elo_avant_global=ch.elo_score_global, elo_avant_plat=ch.elo_score_plat, elo_avant_trot=ch.elo_score_trot, elo_avant_obstacle=ch.elo_score_obstacle FROM chevaux ch WHERE ch.cheval_id=p.cheval_id AND p.course_id=:cid"), {"cid": cid})
            res = (await s.execute(text("SELECT classement FROM resultats WHERE course_id=:cid"), {"cid": cid})).scalar()
            if not res:
                continue
            num2ch = {int(r[0]): r[1] for r in (await s.execute(text("SELECT numero, cheval_id FROM participations WHERE course_id=:cid"), {"cid": cid})).all()}
            classement = []
            for e in res:
                try:
                    num = int(e.get("numero")); pos = e.get("position")
                except Exception:
                    continue
                ch = num2ch.get(num)
                if ch and pos is not None:
                    classement.append({"cheval_id": ch, "position": int(pos), "incident": e.get("incident")})
            if classement:
                try:
                    await update_elo_after_race(s, cid, disc or "plat", niv, dot, classement)
                except Exception as ex:
                    print("[elo] skip", cid, str(ex)[:80], flush=True)
            n += 1
            if n % 500 == 0:
                await s.commit()
                print(f"[elo] {n}/{len(courses)}", flush=True)
        await s.commit()
        print(f"[elo] ELO_REJEU_DONE {n} courses", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
