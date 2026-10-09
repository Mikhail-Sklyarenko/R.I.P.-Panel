"""Route readiness must not require recognition of unrelated Dust2 areas."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def check_scope(csgobot_module_path):
    path = Path(__file__).resolve().parents[1] / "scripts/nav_acceptance.py"
    spec = importlib.util.spec_from_file_location("nav_acceptance_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.readiness


def evaluate(check_scope, rows, connected=True):
    ground = SimpleNamespace(contains=lambda p: .43 < p[0] < .50 and .40 < p[1] < .63)
    goals = [SimpleNamespace(id="mid", x=.458, y=.432),
             SimpleNamespace(id="mid_upper", x=.461, y=.606)]
    return check_scope(rows, connected, ground, goals)


def observations():
    return [dict(frame="mid_frame.jpg", accepted=True, x=.458, y=.432),
            dict(frame="mid_upper_frame.jpg", accepted=True, x=.461, y=.606),
            dict(frame="bombsite_a_frame.jpg", accepted=False, reason="low_registration_confidence")]


def test_unrelated_rejection_warns_without_blocking_mid(check_scope):
    result = evaluate(check_scope, observations())
    assert result["offline_ready"] and result["warnings"]
    assert not result["corpus_all_accepted"]


@pytest.mark.parametrize("fault", ["missing", "rejected", "wrong_position", "disconnected"])
def test_route_failures_still_block_drive(check_scope, fault):
    rows = observations()
    if fault == "missing":
        rows.pop(0)
    elif fault == "rejected":
        rows[0]["accepted"] = False
    elif fault == "wrong_position":
        rows[0]["x"] = .8
    result = evaluate(check_scope, rows, connected=fault != "disconnected")
    assert not result["offline_ready"] and result["errors"]
