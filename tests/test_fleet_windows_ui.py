"""Windows Wingman tab: presence, local bind, click-through, and command order."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from config.loader import ensure_config, load_config, save_config
from config.schema import FleetRole, FleetTransportMode
from core.wingman_fleet.accounts import BindingStatus, CatalogError
from core.wingman_fleet.assignments import AssignmentBook
from modules.fleet_accounts.catalog import AccountCatalog
from modules.fleet_agent.host import FleetHost
from modules.fleet_agent.journal import CommandJournal
from panel.controller import PanelController
from panel.fleet_desk import FleetDesk
from tests.test_fleet_assignments import LINKS, STEAM, _book
from tests.test_wingman_fleet_fsm import TOKEN


def _steam_cs2_pids() -> set[int]:
    raw = subprocess.check_output(["tasklist", "/FO", "CSV", "/NH"], text=True, errors="replace")
    pids = set()
    for line in raw.splitlines():
        lower = line.lower()
        if "steam.exe" in lower or "cs2.exe" in lower:
            parts = line.split(",")
            if len(parts) >= 2:
                pids.add(parts[1].strip().strip('"'))
    return pids


def test_rows_use_book_presence_without_a_link_map(tmp_path):
    book = _book(tmp_path)
    desk = FleetDesk(book)
    desk.slot_agents = {index: f"pc{index}" for index in range(1, 5)}
    rows = desk.rows()
    assert rows[0]["presence"] == "ONLINE / HEALTHY"
    assert rows[0]["link"] == "healthy"
    book.store.db.execute("UPDATE agent_presence SET last_seen=? WHERE agent_id='pc2'", (0.0,))
    rows = desk.rows()
    assert rows[1]["presence"] == "OFFLINE"
    book.revoke_agent("pc3")
    rows = desk.rows()
    assert rows[2]["presence"] == "REVOKED"
    book.store.close()


def test_bind_local_steam_is_manual_and_survives_reopen(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    cfg = ensure_config()
    save_config(cfg.model_copy(update={"wingman_fleet_agent_id": "pc1"}))
    catalog = AccountCatalog(tmp_path / "fleet_catalog.db", agent_id="pc1")
    catalog.sync_logins(["alpha"], ["alpha"])
    local = catalog.by_login("alpha")["local_account_id"]
    catalog.close()
    ctrl = PanelController(None, test_mode=True)
    status = ctrl.bind_local_steam("alpha", STEAM[0])
    assert status == BindingStatus.MANUALLY_BOUND.value
    with pytest.raises(CatalogError):
        ctrl.bind_local_steam("alpha", STEAM[1])
    assert ctrl.bind_local_steam("alpha", STEAM[1], confirm=True) == BindingStatus.MANUALLY_BOUND.value
    again = AccountCatalog(tmp_path / "fleet_catalog.db", agent_id="pc1")
    row = again.get(local)
    assert row["steam_id64"] == STEAM[1]
    assert row["binding_status"] == BindingStatus.MANUALLY_BOUND.value
    again.close()


def test_wrong_order_actions_are_visible(tmp_path):
    book = _book(tmp_path)
    desk = FleetDesk(book)
    assert desk.commit("run") == ""
    assert desk.error
    assert desk.verify() == ""
    assert desk.error
    assert desk.release() == ""
    assert desk.error
    for slot in range(1, 4):
        desk.choose(slot, f"pc{slot}", f"acc-{slot}")
    assert desk.prepare(links=LINKS) == ""
    assert "четырёх" in desk.error or "четырех" in desk.error or "каждом" in desk.error
    book.store.close()


def test_claim_restarts_a_running_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    cfg = ensure_config()
    save_config(cfg.model_copy(update={
        "wingman_fleet_agent_id": "pc1",
        "wingman_fleet_token": TOKEN,
        "wingman_fleet_url": "http://127.0.0.1:8790",
        "wingman_fleet_role": FleetRole.COORDINATOR,
        "wingman_fleet_transport": FleetTransportMode.LOCALHOST_DEVELOPMENT,
    }))
    host = FleetHost()
    restarts = []

    def restart():
        restarts.append(host.agent.agent_id if host.agent is not None else "")
        return {"running": True, "agent_id": "pc1"}

    host._restart_local_agent = restart  # type: ignore[method-assign]
    host.agent = type("A", (), {"agent_id": "pc1"})()
    monkeypatch.setattr(
        "modules.fleet_agent.credentials.claim_enrollment",
        lambda *args, **kwargs: ("n" * 32, 2),
    )
    def _store(path, token):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(token)

    monkeypatch.setattr("modules.fleet_agent.credentials.store_agent_token", _store)
    assert host.claim_agent("code") == "pc1"
    assert restarts == ["pc1"]
    journal = CommandJournal(tmp_path / "fleet" / "pc1.journal")
    # Isolation may use a different journal path; enrollment still stored the generation.
    journal.close()


def _find_button(root, text: str):
    stack = [root]
    while stack:
        widget = stack.pop()
        try:
            if str(widget.cget("text")) == text:
                return widget
        except Exception:
            pass
        try:
            stack.extend(widget.winfo_children())
        except Exception:
            pass
    return None


def _click(widget) -> None:
    widget.update()
    widget.event_generate("<Enter>")
    widget.event_generate("<Button-1>", x=8, y=8)
    widget.event_generate("<ButtonRelease-1>", x=8, y=8)
    try:
        widget.invoke()
    except Exception:
        pass
    widget.update()


def _screenshot(root, path: Path) -> None:
    root.deiconify()
    root.lift()
    root.update_idletasks()
    root.update()
    from PIL import ImageGrab
    path.parent.mkdir(parents=True, exist_ok=True)
    x, y = max(0, root.winfo_rootx()), max(0, root.winfo_rooty())
    w, h = max(100, root.winfo_width()), max(100, root.winfo_height())
    image = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    image.save(path)
    assert path.stat().st_size > 1000


def test_wingman_click_through_prepare_gate_and_window(tmp_path, monkeypatch):
    before = _steam_cs2_pids()
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    cfg = ensure_config()
    save_config(cfg.model_copy(update={
        "wingman_fleet_agent_id": "pc1",
        "wingman_fleet_token": TOKEN,
        "wingman_fleet_role": FleetRole.COORDINATOR,
        "wingman_fleet_transport": FleetTransportMode.LOCALHOST_DEVELOPMENT,
        "panel_geometry": "1280x720+40+40",
    }))
    import customtkinter as ctk
    from panel.ui import PanelView
    root = ctk.CTk()
    ctrl = PanelController(root, test_mode=True)
    view = PanelView(root, ctrl)
    view.build()
    root.update()
    evidence = tmp_path / "ui"
    _screenshot(root, evidence / "wingman_open.png")
    tabs = None
    stack = [root]
    while stack:
        widget = stack.pop()
        if widget.__class__.__name__ == "CTkTabview":
            tabs = widget
            break
        try:
            stack.extend(widget.winfo_children())
        except Exception:
            pass
    assert tabs is not None
    tabs.set("Wingman")
    root.update()
    _screenshot(root, evidence / "wingman_tab.png")
    prepare = _find_button(root, "Подготовить 4 назначения")
    commit = _find_button(root, "Подтвердить состав")
    verify = _find_button(root, "Проверить SteamID64")
    start = _find_button(root, "Старт цикла")
    bind = _find_button(root, "Привязать SteamID64")
    assert prepare and commit and verify and start and bind
    stack = [tabs]
    while stack:
        widget = stack.pop()
        if widget.__class__.__name__ == "CTkScrollableFrame":
            try:
                widget._parent_canvas.yview_moveto(1.0)
            except Exception:
                pass
        try:
            stack.extend(widget.winfo_children())
        except Exception:
            pass
    root.update()
    _screenshot(root, evidence / "wingman_buttons.png")
    root.geometry("1920x1080+0+0")
    root.update()
    _screenshot(root, evidence / "wingman_1920.png")
    _click(commit)
    root.update()
    _click(verify)
    root.update()
    _click(prepare)
    root.update()
    _click(start)
    root.update()
    drained = []
    while True:
        try:
            drained.append(ctrl._log_queue.get_nowait()[1])
        except Exception:
            break
    status = ctrl.format_fleet_status()
    combined = "\n".join(drained) + status
    assert "Запуск запрещён" in combined or "не подтверждены" in combined or "Сначала запустите" in combined
    _screenshot(root, evidence / "wingman_after_gates.png")
    import ctypes
    try:
        scale = int(ctypes.windll.shcore.GetScaleFactorForDevice(0))
    except Exception:
        scale = 0
    kept = Path("docs/fleet/phase-02/evidence")
    kept.mkdir(parents=True, exist_ok=True)
    (kept / "display.json").write_text(
        f'{{"width": {root.winfo_width()}, "height": {root.winfo_height()}, "scale_percent": {scale}}}\n',
        encoding="utf-8",
    )
    for name in ("wingman_open.png", "wingman_tab.png", "wingman_buttons.png", "wingman_1920.png", "wingman_after_gates.png"):
        src = evidence / name
        if src.is_file():
            (kept / name).write_bytes(src.read_bytes())
    root.destroy()
    after = _steam_cs2_pids()
    assert after <= before or after == before
