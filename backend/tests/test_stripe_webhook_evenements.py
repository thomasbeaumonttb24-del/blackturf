"""Le déploiement abonne seul le webhook Stripe aux événements du parrainage."""
from scripts import stripe_webhook_evenements as S


class _Liste(list):
    def auto_paging_iter(self):
        return iter(self)


def _stripe(monkeypatch, points):
    modifs = []
    monkeypatch.setattr(S.stripe.WebhookEndpoint, "list", lambda **kw: _Liste(points))
    monkeypatch.setattr(S.stripe.WebhookEndpoint, "modify",
                        lambda pid, **kw: modifs.append((pid, kw["enabled_events"])))
    return modifs


def test_ajoute_seulement_les_manquants_sans_rien_retirer(monkeypatch):
    anciens = ["customer.subscription.created", "invoice.payment_succeeded", "autre.evenement"]
    modifs = _stripe(monkeypatch, [
        {"id": "we_1", "url": "https://api.blackturf.fr/api/v1/stripe/webhook", "enabled_events": anciens},
        {"id": "we_2", "url": "https://autre-service.fr/hook", "enabled_events": ["x"]},
    ])
    bilan = S.synchroniser()
    assert [m[0] for m in modifs] == ["we_1"]  # l'autre webhook n'est pas touché
    evenements = modifs[0][1]
    assert evenements[:3] == anciens  # rien de retiré
    assert "charge.refunded" in evenements and "charge.dispute.created" in evenements
    assert len(evenements) == len(set(evenements))
    assert bilan[0]["action"] == "ajoutés"


def test_idempotent(monkeypatch):
    modifs = _stripe(monkeypatch, [{"id": "we_1", "url": "https://x/api/v1/stripe/webhook",
                                     "enabled_events": list(S.EVENEMENTS)}])
    assert S.synchroniser()[0]["action"] == "rien à faire" and modifs == []


def test_joker_respecte(monkeypatch):
    modifs = _stripe(monkeypatch, [{"id": "we_1", "url": "https://x/api/v1/stripe/webhook", "enabled_events": ["*"]}])
    S.synchroniser()
    assert modifs == []


def test_mode_verifier_necrit_rien(monkeypatch):
    modifs = _stripe(monkeypatch, [{"id": "we_1", "url": "https://x/api/v1/stripe/webhook", "enabled_events": []}])
    assert S.synchroniser(verifier=True)[0]["action"] == "à ajouter" and modifs == []


def test_le_webhook_traite_bien_chaque_evenement_abonne():
    """Garde-fou : ne jamais abonner Stripe à un événement que la route ignore."""
    from pathlib import Path
    route = (Path(S.__file__).parent.parent / "api/routes/stripe_routes.py").read_text()
    for e in S.EVENEMENTS:
        assert f'"{e}"' in route, e


def test_stripe_injoignable_ne_casse_pas_le_deploiement(monkeypatch):
    monkeypatch.setattr(S, "get_settings", lambda: type("C", (), {"stripe_secret_key": "sk"})())
    def _panne(**kw):
        raise RuntimeError("réseau")
    monkeypatch.setattr(S.stripe.WebhookEndpoint, "list", _panne)
    assert S.main() == 0
