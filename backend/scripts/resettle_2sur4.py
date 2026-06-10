"""Re-règle les paris 2sur4 GAGNÉS de la bankroll avec la formule combinée
corrigée (gain_mult = combinaisons gagnantes / combinaisons jouées).

L'ancienne formule payait la mise ENTIÈRE au rapport même quand 1 seule des
C(N,2) combinaisons gagnait → gains gonflés jusqu'à 6×. Les rapports stockés
sont corrects (base 1€, vérifié vs API PMU) ; seul le gain était faux.

Usage : cd /app && PYTHONPATH=/app python scripts/resettle_2sur4.py [--dry-run]
"""
import asyncio
import re
import sys

from sqlalchemy import text

from db.database import AsyncSessionLocal
from services.bet_settlement import settle_pari


async def main(dry: bool) -> None:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(text("""
            SELECT e.entry_id, e.chevaux, e.mise, e.gain_perte, e.course_id,
                   r.classement, r.rapports, c.nb_partants
            FROM bankroll_entries e
            JOIN resultats r ON r.course_id = e.course_id
            JOIN courses c ON c.course_id = e.course_id
            WHERE e.type_pari = '2sur4' AND e.resultat = 'gagne'
        """))).all()
        print(f"[resettle] {len(rows)} paris 2sur4 gagnés à vérifier")
        n_fix = 0
        for entry_id, chevaux, mise, old_net, cid, classement, rapports, nb_part in rows:
            nums = [int(n) for n in re.findall(r"\d+", chevaux or "")]
            if len(nums) <= 2:
                continue   # formule simple : gain inchangé
            r = settle_pari("2sur4", nums, classement or [], rapports or {},
                            nb_part or len(classement or []))
            if not r["gagne"] or r["rapport_reel"] is None:
                continue
            new_net = round(float(mise) * r["rapport_reel"] * r["gain_mult"] - float(mise), 2)
            if old_net is not None and abs(new_net - float(old_net)) < 0.01:
                continue
            print(f"[resettle] {cid} {chevaux} mise {mise}€ : net {old_net}€ → {new_net}€ "
                  f"(mult {r['gain_mult']:.3f})")
            n_fix += 1
            if not dry:
                await session.execute(text(
                    "UPDATE bankroll_entries SET gain_perte = :g WHERE entry_id = :id"
                ), {"g": new_net, "id": entry_id})
        if not dry:
            await session.commit()
        print(f"[resettle] DONE — {n_fix} pari(s) corrigé(s){' (dry-run)' if dry else ''}")


if __name__ == "__main__":
    asyncio.run(main("--dry-run" in sys.argv))
