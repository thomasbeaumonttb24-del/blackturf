"""Défi du mois : paris verrouillés dans la base elle-même

Le code du site refuse déjà tout pari après le départ et n'offre aucun moyen de
modifier ou supprimer un pari. Ces triggers répètent ces règles au niveau de
Postgres, pour qu'aucun bug, script ou accès direct ne puisse les contourner :

  - INSERT : uniquement « en attente », horodaté maintenant, sur une course à
    venir dont le départ prévu est à plus de 2 minutes et sans arrivée connue ;
  - UPDATE : un pari réglé ne bouge plus ; un pari en attente ne peut que passer
    à gagné / perdu / remboursé ; ni cheval, ni mise, ni course, ni joueur, ni
    horodatage ne se modifie ;
  - DELETE : refusé, sauf pendant la suppression d'un compte par un admin
    (variable de transaction blackturf.suppression_compte).

Postgres uniquement (SQLite, utilisé par les tests unitaires, ignore).

Revision ID: 0055
Revises: 0054
"""
from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None

VERROU_MINUTES = 2  # = services.defi.VERROU_AVANT_DEPART


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"""
CREATE OR REPLACE FUNCTION defi_paris_insert_verrou() RETURNS trigger AS $$
DECLARE
    c RECORD;
BEGIN
    IF NEW.statut <> 'en_attente' OR NEW.points_retour IS NOT NULL OR NEW.regle_at IS NOT NULL THEN
        RAISE EXCEPTION 'defi_paris : un pari naît en attente de règlement';
    END IF;
    IF NEW.engage_at < now() - interval '2 minutes' OR NEW.engage_at > now() + interval '2 minutes' THEN
        RAISE EXCEPTION 'defi_paris : horodatage du pari invalide';
    END IF;
    SELECT statut, date_heure INTO c FROM courses WHERE course_id = NEW.course_id;
    IF NOT FOUND OR c.statut <> 'a_venir'
       OR now() >= c.date_heure - interval '{VERROU_MINUTES} minutes' THEN
        RAISE EXCEPTION 'defi_paris : paris fermés pour cette course';
    END IF;
    IF EXISTS (SELECT 1 FROM resultats WHERE course_id = NEW.course_id) THEN
        RAISE EXCEPTION 'defi_paris : arrivée déjà connue';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION defi_paris_update_verrou() RETURNS trigger AS $$
BEGIN
    IF OLD.statut <> 'en_attente' THEN
        RAISE EXCEPTION 'defi_paris : pari déjà réglé, non modifiable';
    END IF;
    IF NEW.pari_id IS DISTINCT FROM OLD.pari_id
       OR NEW.user_id IS DISTINCT FROM OLD.user_id
       OR NEW.mois IS DISTINCT FROM OLD.mois
       OR NEW.course_id IS DISTINCT FROM OLD.course_id
       OR NEW.type_pari IS DISTINCT FROM OLD.type_pari
       OR NEW.chevaux::text IS DISTINCT FROM OLD.chevaux::text
       OR NEW.points IS DISTINCT FROM OLD.points
       OR NEW.origine IS DISTINCT FROM OLD.origine
       OR NEW.engage_at IS DISTINCT FROM OLD.engage_at THEN
        RAISE EXCEPTION 'defi_paris : un pari engagé ne se modifie pas';
    END IF;
    IF NEW.statut NOT IN ('en_attente', 'gagne', 'perd', 'rembourse') THEN
        RAISE EXCEPTION 'defi_paris : statut inconnu';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION defi_paris_delete_verrou() RETURNS trigger AS $$
BEGIN
    IF coalesce(current_setting('blackturf.suppression_compte', true), '') <> 'on' THEN
        RAISE EXCEPTION 'defi_paris : un pari ne se supprime pas';
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS defi_paris_insert_verrou ON defi_paris;
CREATE TRIGGER defi_paris_insert_verrou BEFORE INSERT ON defi_paris
    FOR EACH ROW EXECUTE FUNCTION defi_paris_insert_verrou();
DROP TRIGGER IF EXISTS defi_paris_update_verrou ON defi_paris;
CREATE TRIGGER defi_paris_update_verrou BEFORE UPDATE ON defi_paris
    FOR EACH ROW EXECUTE FUNCTION defi_paris_update_verrou();
DROP TRIGGER IF EXISTS defi_paris_delete_verrou ON defi_paris;
CREATE TRIGGER defi_paris_delete_verrou BEFORE DELETE ON defi_paris
    FOR EACH ROW EXECUTE FUNCTION defi_paris_delete_verrou();
""")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("""
DROP TRIGGER IF EXISTS defi_paris_insert_verrou ON defi_paris;
DROP TRIGGER IF EXISTS defi_paris_update_verrou ON defi_paris;
DROP TRIGGER IF EXISTS defi_paris_delete_verrou ON defi_paris;
DROP FUNCTION IF EXISTS defi_paris_insert_verrou();
DROP FUNCTION IF EXISTS defi_paris_update_verrou();
DROP FUNCTION IF EXISTS defi_paris_delete_verrou();
""")
