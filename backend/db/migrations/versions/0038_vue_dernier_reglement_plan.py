"""Un plan a plusieurs règlements : toute mesure doit prendre le DERNIER.

Contexte (2026-08-23). `bet_plan_settlements` est append-only par construction :
un rapport PMU publié en retard produit une NOUVELLE ligne de règlement, et le
dernier `settled_at` fait foi. C'est le bon choix — on ne réécrit jamais un
règlement — mais il pose un piège que la mesure a payé cher.

État réel au moment de cette migration : 35 184 lignes de règlement pour 20 338
plans. 3 954 plans en ont entre 2 et 11 (un règlement « partial » à chaque
tentative, puis le règlement définitif). Une agrégation qui somme la table entière
compte donc la MÊME mise plusieurs fois, et surtout compte les tentatives
intermédiaires — celles où le rapport n'était pas encore publié, donc où le gain
vaut 0 par honnêteté. Résultat mesuré : le ROI du profil conservateur ressort à
−65 % en sommant tout, contre −19,7 % en ne gardant que le dernier règlement.
Un écart de 45 points, dans le sens le plus trompeur qui soit.

`ml/bet_plan_performance.py` déduplique déjà correctement (ROW_NUMBER). Cette vue
existe pour que ce ne soit plus une précaution à se rappeler : toute requête
d'exploitation, d'administration ou d'analyse ponctuelle doit partir d'ici.

Revision ID: 0038
Revises: 0037
Create Date: 2026-08-23
"""
from alembic import op


revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE VIEW bet_plan_settlement_actuel AS
        SELECT DISTINCT ON (plan_snapshot_id) *
        FROM bet_plan_settlements
        ORDER BY plan_snapshot_id, settled_at DESC, settlement_id DESC
    """)
    op.execute("""
        COMMENT ON VIEW bet_plan_settlement_actuel IS
        'Dernier reglement connu de chaque plan. Toute mesure de ROI part d''ici : '
        'sommer bet_plan_settlements compte plusieurs fois la meme mise et inclut '
        'les tentatives ou le rapport PMU n''etait pas encore publie.'
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS bet_plan_settlement_actuel")
