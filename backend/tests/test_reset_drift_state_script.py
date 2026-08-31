"""Garde-fous de la commande opérateur de reset du drift."""

from argparse import Namespace

import pytest

from scripts.reset_drift_state import CONFIRMATION, validate_apply_request


def _args(**overrides):
    values = {
        "apply": True,
        "confirm": CONFIRMATION,
        "services_stopped": True,
        "reason": "correction du contrat post-course",
        "force": False,
    }
    values.update(overrides)
    return Namespace(**values)


def test_dry_run_requires_no_confirmation():
    validate_apply_request(
        _args(apply=False, confirm="", services_stopped=False),
        [],
    )


@pytest.mark.parametrize(
    ("args", "reasons"),
    [
        (_args(confirm="wrong"), ["known"]),
        (_args(services_stopped=False), ["known"]),
        (_args(reason="court"), ["known"]),
        (_args(), []),
    ],
)
def test_apply_refuses_missing_safety_condition(args, reasons):
    with pytest.raises(ValueError):
        validate_apply_request(args, reasons)


def test_apply_accepts_known_corruption():
    validate_apply_request(_args(), ["confidence_outside_0_1"])


def test_force_is_required_for_unrecognized_state():
    validate_apply_request(_args(force=True), [])
