"""Panel/CLI lifecycle for the coordinator and the local agent."""
from __future__ import annotations

import socket
import threading
from typing import Any, Callable

from config.loader import load_config
from config.paths import (
    get_wingman_agent_journal_path, get_wingman_fleet_db_path, get_wingman_fleet_roster_path,
)
from core.startup_checks import APP_VERSION
from core.wingman_fleet.coordinator import Coordinator
from core.wingman_fleet.models import CommandType
from core.wingman_fleet.roster import FleetRoster
from core.wingman_fleet.server import FleetServer, local_ip
from core.wingman_fleet.store import FleetStore
from modules.fleet_agent.journal import CommandJournal
from modules.fleet_agent.live import WindowsBackend, default_manifest
from modules.fleet_agent.service import AgentService
from modules.fleet_agent.transport import HttpTransport


def _machine() -> str:
    return socket.gethostname()


class FleetHost:
    def __init__(self, log: Callable[[str], None] | None = None):
        self.log = log or (lambda _m: None)
        self.store: FleetStore | None = None
        self.coordinator: Coordinator | None = None
        self.server: FleetServer | None = None
        self.agent: AgentService | None = None
        self.backend: WindowsBackend | None = None
        self._thread: threading.Thread | None = None

    def roster(self) -> FleetRoster:
        return FleetRoster.load(get_wingman_fleet_roster_path())

    def save_roster(self, roster: FleetRoster) -> None:
        roster.save(get_wingman_fleet_roster_path())

    def start_coordinator(self) -> dict[str, Any]:
        if self.server is not None:
            return {"running": True, "url": f"http://{local_ip()}:{self.server.port}"}
        cfg = load_config()
        roster = self.roster()
        token = (cfg.wingman_fleet_token or roster.token).strip()
        if len(token) < 24:
            raise RuntimeError("fleet token must contain at least 24 characters")
        roster.token, roster.port = token, int(cfg.wingman_fleet_port)
        self.save_roster(roster)
        self.store = FleetStore(get_wingman_fleet_db_path())
        self.coordinator = Coordinator(self.store, token=token, log=self.log)
        self.server = FleetServer(self.coordinator, host="0.0.0.0", port=roster.port).start()
        url = f"http://{local_ip()}:{self.server.port}"
        self.log(f"fleet coordinator: {url}")
        return {"running": True, "url": url, "token": token}

    def start_agent(self) -> dict[str, Any]:
        if self.agent is not None:
            return {"running": True, "agent_id": self.agent.agent_id}
        cfg = load_config()
        roster = self.roster()
        token = (cfg.wingman_fleet_token or roster.token).strip()
        agent_id = (cfg.wingman_fleet_agent_id or "").strip()
        if not agent_id:
            raise RuntimeError("задайте wingman_fleet_agent_id (слот этого ПК)")
        expected = cfg.wingman_fleet_expected_steamid64.strip()
        if not expected:
            for entry in roster.slots.values():
                if entry.get("agent_id") == agent_id:
                    expected = str(entry.get("steam_id64", ""))
        self.backend = WindowsBackend(agent_id=agent_id, expected_steam_id64=expected,
                                       computer=_machine(), log=self.log)
        journal = CommandJournal(get_wingman_agent_journal_path(agent_id))
        url = (cfg.wingman_fleet_url or f"http://127.0.0.1:{roster.port}").rstrip("/")
        self.agent = AgentService(
            agent_id, self.backend, HttpTransport(url), journal, token=token,
            build_version=APP_VERSION, resource_manifest=default_manifest(), computer=_machine(),
            log=self.log,
        )
        self._thread = threading.Thread(target=self.agent.run_forever, daemon=True, name="fleet-agent")
        self._thread.start()
        self.log(f"fleet agent {agent_id} → {url}")
        return {"running": True, "agent_id": agent_id, "url": url}

    def start_run(self) -> str:
        if self.coordinator is None:
            self.start_coordinator()
        roster = self.roster()
        plan = roster.build_plan(build_version=APP_VERSION, resource_manifest=default_manifest())
        self.coordinator.start_run(plan)
        self.log(f"fleet run {plan.run_id}")
        return plan.run_id

    def stop_run(self) -> None:
        if self.coordinator is not None:
            self.coordinator.stop_run()

    def pair_action(self, pair_id: str, action: str) -> None:
        if self.coordinator is None:
            raise RuntimeError("coordinator is not running")
        self.coordinator.pair_action(pair_id, action)

    def agent_command(self, agent_id: str, command: str) -> None:
        if self.coordinator is None:
            raise RuntimeError("coordinator is not running")
        self.coordinator.agent_command(agent_id, CommandType(command))

    def status(self) -> dict[str, Any]:
        st: dict[str, Any] = {
            "coordinator": bool(self.server),
            "agent": self.agent.snapshot() if self.agent else None,
            "url": f"http://{local_ip()}:{self.server.port}" if self.server else load_config().wingman_fleet_url,
        }
        if self.coordinator is not None:
            st.update(self.coordinator.status())
        return st

    def stop(self) -> None:
        agent = self.agent
        thread = self._thread
        if agent is not None:
            agent.stop()
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)
        if agent is not None:
            agent.shutdown()
            self.agent = None
        self._thread = None
        if self.backend is not None:
            self.backend.close()
            self.backend = None
        if self.server is not None:
            self.server.stop()
            self.server = None
        if self.store is not None:
            self.store.close()
            self.store = None
        self.coordinator = None
        self.log("fleet host stopped")
