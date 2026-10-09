"""Identity binding, blocking preflight, input ownership and worker admission/stop."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from core.wingman_fleet.models import Identity
from modules.fleet_agent.gsi import FleetGsi, config_text, install
from modules.fleet_agent.identity import IdentityProbe, account_id_to_steam64, parse_vdf, steam64_to_friend_code
from modules.fleet_agent.input_supervisor import InputBusy, InputOwner, InputSupervisor
from modules.fleet_agent.preflight import Preflight

ROOT = Path(__file__).resolve().parents[1]

LOGINUSERS = '''"users"
{
	"76561198000000010"
	{
		"AccountName"		"farm_one"
		"PersonaName"		"Alpha \\"A\\""
		"RememberPassword"		"1"
		"MostRecent"		"1"
	}
	"76561198000000011"
	{
		"AccountName"		"farm_two"
		"PersonaName"		"Bravo"
		"RememberPassword"		"0"
	}
}
'''


def _steam(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "loginusers.vdf").write_text(LOGINUSERS, encoding="utf-8")
    return tmp_path


def test_steam64_conversions():
    assert account_id_to_steam64(39734282) == "76561198000000010"
    assert steam64_to_friend_code("76561198000000010") == "39734282"
    assert account_id_to_steam64(0) == ""


def test_vdf_parser_handles_escapes():
    users = parse_vdf(LOGINUSERS)["users"]
    assert users["76561198000000010"]["PersonaName"] == 'Alpha "A"'


def test_identity_from_registry_and_gsi(tmp_path):
    root = _steam(tmp_path)
    probe = IdentityProbe(registry=lambda: (39734282, str(root)))
    local = probe.probe()
    assert local.identity is Identity.STEAM_LOCAL and local.steam_id64 == "76561198000000010"
    assert local.persona == 'Alpha "A"' and local.friend_code == "39734282"
    gsi = probe.probe(gsi_steam_id64="76561198000000010", gsi_fresh=True)
    assert gsi.identity is Identity.GSI
    split = probe.probe(gsi_steam_id64="76561198000000011", gsi_fresh=True)
    assert split.identity is Identity.MISMATCH
    wrong = probe.probe(expected_steam_id64="76561198000000011")
    assert wrong.identity is Identity.MISMATCH
    assert IdentityProbe(registry=lambda: (0, "")).probe().identity is Identity.UNCONFIRMED
    remembered = {a.steam_id64: a.detail for a in probe.remembered_accounts()}
    assert remembered == {"76561198000000010": "remembered", "76561198000000011": "no remember-me"}


def test_preflight_blocks_and_caches():
    calls = {"slow": 0}

    def slow():
        calls["slow"] += 1
        return True, ""

    clock = [0.0]
    pf = Preflight([("slow", slow, 30.0), ("size", lambda: (False, "1920x1080"), 0),
                    ("boom", lambda: 1 / 0, 0)], clock=lambda: clock[0])
    ok, failures = Preflight.summary(pf.run())
    assert not ok and failures[0] == "size: 1920x1080" and failures[1].startswith("boom")
    pf.run()
    assert calls["slow"] == 1
    clock[0] = 31.0
    pf.run()
    assert calls["slow"] == 2
    assert [r.code for r in pf.cached()] == ["slow", "size", "boom"]


def test_input_supervisor_is_exclusive_and_releases():
    released = []
    sup = InputSupervisor(release=lambda: released.append(1))
    assert sup.grant_gameplay("w1") and sup.owner is InputOwner.GAMEPLAY
    with pytest.raises(InputBusy):
        with sup.ui("invite"):
            pass
    sup.revoke_gameplay()
    assert sup.owner is InputOwner.NONE and released == [1]
    with sup.ui("invite"):
        assert not sup.grant_gameplay("w2")
    assert released == [1, 1]
    with pytest.raises(RuntimeError):
        with sup.ui("x"):
            raise RuntimeError("click failed")
    assert sup.owner is InputOwner.NONE and len(released) == 3


def test_fleet_gsi_receiver(tmp_path):
    clock = [100.0]
    gsi = FleetGsi("k" * 48, port=0, clock=lambda: clock[0])
    assert gsi.view().age_sec == float("inf")
    assert gsi.accept({"provider": {"appid": 730, "steamid": "76561198000000010", "ip": "162.1.2.3:27015"},
                       "map": {"mode": "scrimcomp2v2", "name": "de_inferno", "phase": "live", "round": 3},
                       "player": {"steamid": "76561198000000010", "name": "Alpha", "activity": "playing",
                                  "team": "CT", "state": {"health": 100}},
                       "allplayers": {
                           "1": {"name": "Alpha"}, "2": {"name": "Bravo"},
                           "3": {"name": "Charlie"}, "4": {"name": "Delta"},
                       }})
    clock[0] = 100.5
    v = gsi.view()
    assert v.fresh and v.map_id == "de_inferno" and v.mode == "scrimcomp2v2" and v.alive and v.team == "CT"
    assert set(gsi.roster_names()) == {"Alpha", "Bravo", "Charlie", "Delta"}
    assert gsi.server_token() == "162.1.2.3:27015"
    assert not gsi.accept({"provider": {"appid": 570, "steamid": "76561198000000010"}})
    path, changed = install(tmp_path, "k" * 48)
    assert changed and "4020/fleet" in path.read_text() and not install(tmp_path, "k" * 48)[1]
    assert '"heartbeat" "1.0"' in config_text("k" * 48)


def _load_gate():
    spec = importlib.util.spec_from_file_location("fleet_gate", ROOT / "vendor" / "csgobot" / "fleet_gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_worker_gate_requires_fresh_matching_lease(tmp_path, monkeypatch):
    mod = _load_gate()
    monkeypatch.delenv("CSGOBOT_ADMISSION_FILE", raising=False)
    assert mod.FleetGate().admitted()  # DM / standalone: no gate
    lease, stop = tmp_path / "lease.json", tmp_path / "stop"
    monkeypatch.setenv("CSGOBOT_ATTEMPT_ID", "run/w1")
    g = mod.FleetGate(str(lease), str(stop))
    g.CACHE_SEC = 0
    assert not g.admitted()
    lease.write_text(json.dumps({"attempt_id": "run/w1", "expires_at": time.time() + 2}))
    assert g.admitted()
    lease.write_text(json.dumps({"attempt_id": "run/w0", "expires_at": time.time() + 2}))
    assert not g.admitted()
    lease.write_text(json.dumps({"attempt_id": "run/w1", "expires_at": time.time() - 1}))
    assert not g.admitted()
    assert not g.stop_requested()
    stop.write_text("stop")
    assert g.stop_requested()


def test_worker_main_is_gated_by_fleet_lease():
    src = (ROOT / "vendor" / "csgobot" / "main.py").read_text(encoding="utf-8")
    assert src.count("fleet_gate().admitted()") == 2
    assert "fleet_gate().stop_requested()" in src


def test_child_env_carries_admission_and_stop(tmp_path):
    from modules.combat import csgobot_ai
    env = {"CSGOBOT_ADMISSION_FILE": "stale"}
    csgobot_ai._apply_child_env_from_ctx({}, env)
    assert "CSGOBOT_ADMISSION_FILE" not in env
    ctx = {"wingman_gsi_path": "x.json", "fleet_admission_file": str(tmp_path / "a.json"),
           "fleet_stop_file": str(tmp_path / "stop"), "fleet_attempt_id": "run/w3"}
    csgobot_ai._apply_child_env_from_ctx(ctx, env)
    assert env["CSGOBOT_ADMISSION_FILE"].endswith("a.json") and env["CSGOBOT_ATTEMPT_ID"] == "run/w3"
    assert env["CSGOBOT_GAME_MODE"] == "wingman"


class _FakeProc:
    def __init__(self, stop_file: Path, cooperative: bool):
        self.stop_file, self.cooperative = stop_file, cooperative
        self.terminated = False
        self.code = None

    def poll(self):
        if self.code is None and self.cooperative and self.stop_file.exists():
            self.code = 0
        return self.code

    def wait(self, timeout=None):
        if self.poll() is None:
            raise subprocess.TimeoutExpired("csgobot", timeout)
        return self.code

    def terminate(self):
        self.terminated, self.code = True, 1

    def kill(self):
        self.code = -9


@pytest.mark.parametrize("cooperative", [True, False])
def test_stop_ai_is_cooperative_then_forceful(tmp_path, monkeypatch, cooperative):
    from modules.combat import csgobot_ai
    from modules.ui_nav import actions
    released = []
    monkeypatch.setattr(actions, "release_all_inputs", lambda: released.append("all"))
    monkeypatch.setattr(actions, "release_combat_inputs", lambda: released.append("combat"))
    monkeypatch.setattr(csgobot_ai, "COOPERATIVE_STOP_SEC", 0.01)
    stop = tmp_path / "stop"
    proc = _FakeProc(stop, cooperative)
    monkeypatch.setattr(csgobot_ai, "_PROCESS", proc)
    monkeypatch.setattr(csgobot_ai, "_PROCESS_STOP_FILE", stop)
    csgobot_ai.stop_ai()
    assert stop.exists()
    assert proc.terminated is (not cooperative)
    assert released == ["all"]
    assert csgobot_ai._PROCESS is None


def test_release_all_inputs_ignores_focus(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from modules.ui_nav import actions
    api = SimpleNamespace(keybd_event=Mock(), MapVirtualKey=lambda vk, mode: vk, mouse_event=Mock())
    monkeypatch.setitem(sys.modules, "win32api", api)
    monkeypatch.setitem(sys.modules, "win32con", SimpleNamespace(
        KEYEVENTF_KEYUP=2, MOUSEEVENTF_LEFTUP=4, MOUSEEVENTF_RIGHTUP=16, MOUSEEVENTF_MIDDLEUP=64))
    monkeypatch.setattr(sys, "platform", "win32")
    actions.release_all_inputs()
    assert api.keybd_event.call_count == len(actions._RELEASE_VKS)
    assert all(c.args[2] == 2 for c in api.keybd_event.call_args_list)
    assert api.mouse_event.call_count == 3
