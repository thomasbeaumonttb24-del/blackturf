"""Purge les jobs RQ EN ÉCHEC de plus de N jours (défaut 7).

Ne touche à rien d'autre : ni jobs en attente, ni jobs terminés, ni données
métier. Un job raté ne contient que sa trace d'échec — l'apprentissage
post-course qu'il portait est de toute façon perdu depuis des semaines, et une
relance ne produirait aucune ligne rejouable (les features ne sont plus
reconstituables après la course).
"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))   # `python scripts/x.py`

from redis import Redis
from rq.job import Job
from rq.registry import FailedJobRegistry

from api.config import get_settings

JOURS = int(sys.argv[1]) if len(sys.argv) > 1 else 7

conn = Redis.from_url(get_settings().redis_url)
limite = dt.datetime.utcnow() - dt.timedelta(days=JOURS)

for file in ("default", "ml"):
    registre = FailedJobRegistry(file, connection=conn)
    ids = registre.get_job_ids()
    supprimes = gardes = orphelins = 0
    for jid in ids:
        try:
            job = Job.fetch(jid, connection=conn)
        except Exception:
            registre.remove(jid, delete_job=True)   # métadonnées déjà expirées
            orphelins += 1
            continue
        fin = job.ended_at
        if fin is not None and fin.replace(tzinfo=None) > limite:
            gardes += 1
            continue
        registre.remove(jid, delete_job=True)
        supprimes += 1
    print(f"{file}: {len(ids)} en échec -> {supprimes} purgés (> {JOURS} j), "
          f"{orphelins} orphelins, {gardes} conservés")
