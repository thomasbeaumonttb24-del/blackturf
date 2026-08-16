"""Vérification du chemin head-to-head sur les VRAIES données de prod.

Ne déploie rien, n'entraîne rien, n'écrit rien : charge le champion actif et le
fait prédire sur les courses postérieures à son entraînement (donc strictement
hors-échantillon pour lui), puis affiche son AUC.

But : valider avant déploiement que (1) le .pkl du champion se charge, (2) ses
features sont compatibles avec le schéma courant, (3) l'échantillon OOS est assez
gros pour arbitrer. C'est exactement le chemin que `_head_to_head_auc` empruntera
la nuit suivante — sauf qu'ici il n'y a pas de challenger à comparer.

Usage :  python -m scripts.check_h2h_champion
"""
import asyncio
import json

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sqlalchemy import select, text

from db.database import AsyncSessionLocal
from db.models import ModelVersion
from ml.models import BlackTurfEnsemble
from ml.pipeline import H2H_MIN_ROWS


async def main() -> None:
    async with AsyncSessionLocal() as session:
        mv = (await session.execute(
            select(ModelVersion).where(ModelVersion.est_actif == True)
            .order_by(ModelVersion.version_num.desc())
        )).scalars().first()
        if mv is None:
            print("AUCUN modèle actif en base")
            return
        print(f"champion       : v{mv.version_num} ({mv.nom_fichier})")
        print(f"entraîné le    : {mv.created_at}")
        print(f"wf_auc stocké  : {mv.walk_forward_auc}  (mesuré sur SON dataset)")
        print(f"auc_roc stocké : {mv.auc_roc}")
        print(f"lignes train   : {mv.nb_courses_train}")

        # Mêmes garde-fous anti-fuite que le dataset d'entraînement : features
        # figées AVANT le départ uniquement.
        rows = (await session.execute(text("""
            SELECT fm.features,
                   pa.course_id,
                   CASE WHEN (r.classement->0->>'numero')::int = pa.numero THEN 1 ELSE 0 END AS win
            FROM features_ml fm
            JOIN participations pa ON pa.participation_id = fm.participation_id
            JOIN courses c ON c.course_id = pa.course_id AND c.statut = 'termine'
            JOIN resultats r ON r.course_id = pa.course_id
            WHERE c.date_heure > :cutoff
              AND c.date_heure IS NOT NULL AND fm.computed_at < c.date_heure
              AND jsonb_typeof(r.classement) = 'array'
            ORDER BY c.date_heure
        """), {"cutoff": mv.created_at})).fetchall()

        print(f"\nlignes OOS (postérieures au champion) : {len(rows)}")
        if len(rows) < H2H_MIN_ROWS:
            print(f"INSUFFISANT (< {H2H_MIN_ROWS}) -> le h2h renverra None, "
                  f"repli walk-forward")
            return

        feats = [f if isinstance(f, dict) else json.loads(f) for f, _, _ in rows]
        X = pd.DataFrame(feats)
        X["course_id"] = [c for _, c, _ in rows]
        # Label top-3 impossible à reconstituer ici sans le classement complet :
        # on valide le chemin technique sur le label VICTOIRE, suffisant pour
        # prouver que le modèle charge, prédit et discrimine.
        y = pd.Series([w for _, _, w in rows])
        print(f"courses OOS                          : {X['course_id'].nunique()}")
        print(f"taux de gagnants                     : {y.mean():.4f}")

        champion = BlackTurfEnsemble.load_current()
        if champion is None:
            print("current_model.pkl INTROUVABLE")
            return
        print(f"features attendues par le champion   : {len(champion.feature_names)}")
        manquantes = [f for f in champion.feature_names if f not in X.columns]
        print(f"features manquantes dans le dataset  : {len(manquantes)}"
              + (f" -> {manquantes[:8]}" if manquantes else ""))

        p = champion.predict_proba(X)
        auc = roc_auc_score(y, p)
        print(f"\nAUC du champion sur l'OOS récent     : {auc:.4f}")
        print(f"proba min/moy/max                    : "
              f"{np.min(p):.4f} / {np.mean(p):.4f} / {np.max(p):.4f}")
        print("\n(un challenger sera comparé À CE CHIFFRE, sur ces mêmes lignes)")


if __name__ == "__main__":
    asyncio.run(main())
