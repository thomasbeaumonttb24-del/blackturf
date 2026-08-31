"""La colonne « MVT » de la comparaison des cotes doit afficher quelque chose.

Constaté le 2026-08-19 sur la course 19082026R1C8 : la colonne était vide pour
les 15 partants, alors que `participations.mouvement_cote_pct` contenait une
valeur pour chacun d'eux. L'API ne lisait pas cette colonne : elle recalculait le
mouvement à partir de Betclic (`cote_betclic_ouverture` → `cote_betclic`), or
Betclic n'est pas scrapé (aucune source gratuite). La branche ne s'activait donc
JAMAIS, et une donnée déjà collectée était jetée pour 100 % des partants.
"""
import inspect

import pytest

from api.routes import courses as courses_mod


def _source_du_calcul() -> str:
    """Le calcul vit dans la construction de la réponse de la page course."""
    return inspect.getsource(courses_mod)


def test_le_mouvement_pmu_sert_de_repli():
    source = _source_du_calcul()
    assert "elif p.mouvement_cote_pct is not None:" in source, (
        "sans repli, la colonne MVT reste vide tant que Betclic n'est pas scrapé")


def test_la_conversion_de_fraction_en_pourcentage_est_faite():
    """En base la valeur est une fraction ((direct − référence) / référence) : la
    servir telle quelle afficherait « 0,2 % » là où le mouvement vaut 23 %."""
    source = _source_du_calcul()
    assert "float(p.mouvement_cote_pct) * 100" in source


def test_le_signe_est_inverse():
    """Conventions opposées : en base, positif = la cote MONTE (cheval délaissé) ;
    à l'affichage, positif = la cote BAISSE (l'argent arrive dessus). Sans
    inversion, le front afficherait une flèche à l'envers sur chaque partant."""
    source = _source_du_calcul()
    assert "round(-float(p.mouvement_cote_pct) * 100, 1)" in source


def test_betclic_reste_prioritaire():
    """Quand Betclic est disponible, il reste la meilleure mesure : il compare
    deux cotes du MÊME opérateur à deux instants, sans mélange de sources."""
    source = _source_du_calcul()
    i_betclic = source.index("if p.cote_betclic_ouverture and p.cote_betclic")
    i_repli = source.index("elif p.mouvement_cote_pct is not None:")
    assert i_betclic < i_repli
