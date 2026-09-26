"""Mails de compte et de confirmation (services/email_compte.py) : lien
présent en bouton ET en clair, version texte, mentions obligatoires, échappement."""
from services import email_compte as ec


def _commun(html, texte, lien):
    assert html.count(lien) >= 2                     # bouton + lien en clair
    assert lien in texte
    assert "09 74 75 13 13" in html                  # jeu responsable
    assert "logo-nuit.png" in html and "viewport" in html


def test_confirmation_newsletter():
    lien = "https://blackturf.fr/api/v1/newsletter/confirmation?jeton=abc"
    html, texte = ec.confirmation_newsletter(lien)
    _commun(html, texte, lien)
    assert "instagram.com/blackturf.fr" in html and "aucune lettre" in texte


def test_verification_echappe_le_prenom():
    lien = "https://blackturf.fr/verifier-email?token=abc"
    html, texte = ec.verification_adresse("<script>", lien)
    _commun(html, texte, lien)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "24 heures" in html


def test_reinitialisation():
    lien = "https://blackturf.fr/reinitialiser-mot-de-passe?token=abc"
    html, texte = ec.reinitialisation_mot_de_passe(None, lien)
    _commun(html, texte, lien)
    assert "Bonjour parieur" in html and "1 heure" in html


def test_resiliation_selon_stripe():
    html, texte = ec.resiliation(True)
    assert "échéance de la période en cours" in html and "09 74 75 13 13" in html
    html, texte = ec.resiliation(False)
    assert "72 h" in html and "contact@blackturf.fr" in texte
