"""Generate explicitly fictional previews, without database access or sending mail."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.email_templates import daily, weekly

out = Path(__file__).resolve().parents[2] / "docs" / "email-previews"
out.mkdir(parents=True, exist_ok=True)
items = [
    {"course_id": "demo", "heure": "13:45", "hippodrome": "Vincennes · exemple fictif", "nom_cheval": "Cheval de démonstration", "numero": 8, "niveau": 3, "ev": .142},
    {"course_id": "demo", "heure": "15:10", "hippodrome": "ParisLongchamp · exemple fictif", "nom_cheval": "Un nom particulièrement long pour vérifier le retour à la ligne", "numero": 12, "niveau": 4, "ev": .186},
]
data = {"debut": "14/09/2026 (DÉMONSTRATION)", "fin": "20/09/2026 · chiffres fictifs",
        "top": [{"course_id": "demo", "profil": "Modéré", "date": "16/09 à 15:10", "hippodrome": "Course de démonstration", "code": "R1C4", "mise": 10.0, "retour": 75.40, "net": 65.40},
                {"course_id": "demo", "profil": "Prudent", "date": "18/09 à 14:20", "hippodrome": "Exemple fictif", "code": "R2C3", "mise": 10.0, "retour": 42.20, "net": 32.20},
                {"course_id": "demo", "profil": "Risqué", "date": "20/09 à 16:05", "hippodrome": "Exemple fictif", "code": "R1C5", "mise": 10.0, "retour": 28.50, "net": 18.50}],
        "profils": [{"label": "Prudent", "n": 10, "mise": 100., "retour": 112.20, "net": 12.20},
                    {"label": "Modéré", "n": 10, "mise": 100., "retour": 95.40, "net": -4.60},
                    {"label": "Risqué", "n": 10, "mise": 100., "retour": 58.50, "net": -41.50}]}
unsub = "https://blackturf.fr/newsletter"
for name, rendered in (("quotidien", daily(items, "DÉMONSTRATION — données fictives", unsub)),
                       ("hebdomadaire", weekly(data, unsub, "https://blackturf.fr/newsletter"))):
    html, plain = rendered
    (out / (name + ".html")).write_text(html, encoding="utf-8")
    (out / (name + ".txt")).write_text(plain, encoding="utf-8")
print(out)
