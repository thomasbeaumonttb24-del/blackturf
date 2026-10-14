"""Pourquoi tant de paiements refusés en France ?

Hypothèse de l'exploitant : jusqu'au 2026-10-04 il y avait un essai gratuit de
7 jours. Des personnes rouvraient un compte avec la MÊME carte pour un nouvel
essai ; le webhook le détecte (`cartes_connues`) et coupe l'essai sur-le-champ
(`trial_end="now"`), ce qui facture immédiatement. Si la carte est vide — typique
d'une prépayée rechargée pour l'occasion — ce débit échoue et compte comme refus.

Le script classe chaque débit refusé :
  · essai coupé (carte réutilisée)     — compte journalisé `essai_refuse_carte_reutilisee`,
                                          ou carte vue sur plusieurs clients Stripe ;
  · ancien essai à échéance           — échec au 1er débit après un essai normal ;
  · après la fin des essais (≥ 04/10) — vrai paiement direct refusé ;
  · autre.
et dit pour chaque carte si elle a fini par payer (client récupéré) ou non.

Sortie ANONYMISÉE (elle part dans un journal GitHub) : ni e-mail, ni empreinte,
ni 4 derniers chiffres — des numéros « carte #n ».

Usage (dans le conteneur api, qui a la base, la clé et la bibliothèque Stripe) :

    docker exec -i blackturf_api python - < backend/scripts/analyse_refus_paiement.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

sys.path.insert(0, "/app")

import stripe  # noqa: E402
from sqlalchemy import text  # noqa: E402

FIN_ESSAIS = datetime(2026, 10, 4, tzinfo=timezone.utc)
PAYS = os.environ.get("PAYS", "FR")


def _d(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


async def _lire_base() -> tuple[dict, dict, Counter]:
    """customer Stripe → événements d'abonnement du compte ; stats cartes_connues."""
    from db.database import AsyncSessionLocal

    evts_par_client: dict[str, list[tuple[str, datetime]]] = defaultdict(list)
    cartes: dict[str, int] = {}
    types_mois: Counter = Counter()
    async with AsyncSessionLocal() as db:
        rows = await db.execute(text(
            "SELECT u.stripe_customer_id, e.type, e.created_at "
            "FROM subscription_events e JOIN users u ON u.user_id = e.user_id "
            "WHERE u.stripe_customer_id IS NOT NULL"))
        for cus, typ, quand in rows:
            evts_par_client[cus].append((typ, quand))
        rows = await db.execute(text(
            "SELECT empreinte, COALESCE(tentatives_autres_comptes, 0) FROM cartes_connues"))
        cartes = {emp: n for emp, n in rows}
        rows = await db.execute(text(
            "SELECT to_char(created_at, 'YYYY-MM'), type, count(*) FROM subscription_events "
            "WHERE type IN ('essai_refuse_carte_reutilisee', 'carte_refusee_autre_compte', "
            "'paiement_echoue', 'paiement_recu', 'essai_bientot_fini') GROUP BY 1, 2"))
        for mois, typ, n in rows:
            types_mois[(mois, typ)] += n
    return evts_par_client, cartes, types_mois


def _motif_facture(ch, cache: dict) -> str:
    inv = ch.get("invoice")
    if not inv:
        return "?"
    if isinstance(inv, dict):
        return inv.get("billing_reason") or "?"
    if inv not in cache:
        try:
            cache[inv] = stripe.Invoice.retrieve(inv).get("billing_reason") or "?"
        except Exception:  # noqa: BLE001
            cache[inv] = "?"
    return cache[inv]


def main() -> None:
    cle = os.environ.get("STRIPE_SECRET_KEY", "")
    if not cle:
        sys.exit("STRIPE_SECRET_KEY absent — lancer dans le conteneur blackturf_api.")
    stripe.api_key = cle

    evts_par_client, cartes_connues, types_mois = asyncio.run(_lire_base())

    debits = []
    cache_inv: dict = {}
    clients_par_carte: dict[str, set] = defaultdict(set)
    for ch in stripe.Charge.list(limit=100).auto_paging_iter():
        carte = (ch.get("payment_method_details") or {}).get("card") or {}
        emp = carte.get("fingerprint") or f"sans-empreinte-{ch['id']}"
        if ch.get("customer"):
            clients_par_carte[emp].add(ch["customer"])
        if (carte.get("country") or "??") != PAYS:
            continue
        out = ch.get("outcome") or {}
        tds = (carte.get("three_d_secure") or {}).get("result") or "-"
        debits.append({
            "quand": _d(ch["created"]),
            "ok": ch.get("status") == "succeeded" and ch.get("paid"),
            "echec": ch.get("status") == "failed",
            "emp": emp,
            "client": ch.get("customer"),
            "type_carte": carte.get("funding") or "?",
            "marque": carte.get("brand") or "?",
            "issue": out.get("type") or "?",           # issuer_declined / blocked / authorized
            "motif": out.get("reason") or ch.get("failure_code") or "?",
            "risque": out.get("risk_level") or "?",
            "tds": tds,
            "facture": _motif_facture(ch, cache_inv),
            "montant": ch.get("amount", 0) / 100,
        })

    if not debits:
        sys.exit(f"Aucun débit sur carte {PAYS}.")
    debits.sort(key=lambda d: d["quand"])

    # Numérotation anonyme des cartes, dans l'ordre d'apparition.
    num = {}
    for d in debits:
        num.setdefault(d["emp"], len(num) + 1)

    def categorie(d) -> str:
        evts = evts_par_client.get(d["client"] or "", [])
        coupe = any(t == "essai_refuse_carte_reutilisee" for t, _ in evts)
        multi = len(clients_par_carte.get(d["emp"], ())) > 1 or cartes_connues.get(d["emp"], 0) > 0
        if coupe or (multi and d["quand"] < FIN_ESSAIS):
            return "essai coupé (carte réutilisée)"
        if d["quand"] >= FIN_ESSAIS:
            return "après fin des essais (paiement direct)"
        if any(t == "essai_bientot_fini" for t, _ in evts):
            return "1er débit après un essai normal"
        return "autre (avant le 04/10)"

    echecs = [d for d in debits if d["echec"]]
    reussis = [d for d in debits if d["ok"]]
    print(f"\n=== DÉBITS SUR CARTES {PAYS} — {debits[0]['quand']:%d/%m/%Y} → "
          f"{debits[-1]['quand']:%d/%m/%Y} ===")
    print(f"{len(reussis)} réussis, {len(echecs)} refusés, "
          f"{len({d['emp'] for d in echecs})} cartes distinctes refusées, "
          f"{len({d['client'] for d in echecs})} clients Stripe distincts refusés")

    print("\n--- Refus par catégorie ---")
    cat = Counter(categorie(d) for d in echecs)
    cat_cartes = defaultdict(set)
    for d in echecs:
        cat_cartes[categorie(d)].add(d["emp"])
    for c, n in cat.most_common():
        print(f"{c:<42}{n:>4} refus  {len(cat_cartes[c]):>3} cartes")

    print("\n--- Refus : issue × motif bancaire ---")
    for (i, m), n in Counter((d["issue"], d["motif"]) for d in echecs).most_common():
        print(f"{i:<18}{m:<28}{n:>4}")

    print("\n--- Refus par type de carte ---")
    for t, n in Counter(d["type_carte"] for d in echecs).most_common():
        ok = sum(1 for d in reussis if d["type_carte"] == t)
        print(f"{t:<12}{n:>4} refus   {ok:>3} réussis   taux refus {100*n/(n+ok):.0f}%")

    print("\n--- Refus par motif de facture Stripe ---")
    for f, n in Counter(d["facture"] for d in echecs).most_common():
        print(f"{f:<28}{n:>4}")

    print("\n--- Refus par 3D Secure ---")
    for f, n in Counter(d["tds"] for d in echecs).most_common():
        print(f"{f:<28}{n:>4}")

    print("\n--- Refus par semaine ---")
    for s, n in sorted(Counter(d["quand"].strftime("%G-S%V") for d in echecs).items()):
        print(f"{s}  {n:>3}  " + "█" * n)

    print("\n--- Fiche par carte refusée (anonyme) ---")
    print(f"{'Carte':<9}{'Type':<9}{'Comptes':>8}{'Refus':>6}{'Réussis':>8}  "
          f"{'1er refus':<11}{'dernier':<11}{'Récupéré':<9} Motifs")
    par_carte = defaultdict(list)
    for d in debits:
        par_carte[d["emp"]].append(d)
    recup = perdu = 0
    for emp, lst in sorted(par_carte.items(), key=lambda kv: -sum(x["echec"] for x in kv[1])):
        ko = [x for x in lst if x["echec"]]
        if not ko:
            continue
        ok = [x for x in lst if x["ok"]]
        apres = any(x["quand"] > ko[0]["quand"] for x in ok)
        recup += apres
        perdu += not apres
        n_comptes = max(len(clients_par_carte.get(emp, ())), 1)
        motifs = ", ".join(f"{m}×{k}" for m, k in Counter(x["motif"] for x in ko).most_common(3))
        print(f"#{num[emp]:<8}{lst[0]['type_carte']:<9}{n_comptes:>8}{len(ko):>6}{len(ok):>8}  "
              f"{ko[0]['quand']:%d/%m/%y}   {ko[-1]['quand']:%d/%m/%y}   "
              f"{'oui' if apres else 'non':<9} {motifs}  [{categorie(ko[0])}]")
    print(f"\nCartes refusées qui ont fini par payer : {recup} ; jamais payé : {perdu}")

    print("\n--- Base : cartes et journal d'abonnement ---")
    print(f"cartes_connues : {len(cartes_connues)} cartes, "
          f"{sum(1 for n in cartes_connues.values() if n > 0)} présentées par un autre compte "
          f"({sum(cartes_connues.values())} tentatives au total)")
    for (mois, typ), n in sorted(types_mois.items()):
        print(f"{mois}  {typ:<34}{n:>4}")


if __name__ == "__main__":
    main()
