"""Panel/CLI lifecycle for the coordinator and the local agent."""
from __future__ import annotations

import socket
import threading
from pathlib import Path
from typing import Any, Callable

from config.loader import load_config
from config.paths import (
    get_agent_token_path, get_wingman_agent_journal_path, get_wingman_fleet_db_path,
    get_wingman_fleet_roster_path,
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


def lan_configuration_ready(*, mode: str, tls: bool, cert_exists: bool, ca_exists: bool,
                            registrations: dict[str, str]) -> bool:
    """Configuration readiness only. This is not a four-PC proof."""
    if mode != "secure_lan" or not tls or not cert_exists or not ca_exists:
        return False
    if len(registrations) < 4:
        return False
    return all(state == "registered" for state in registrations.values())


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
            scheme = "https" if self.server.tls else "http"
            return {"running": True, "url": f"{scheme}://{local_ip()}:{self.server.port}"}
        cfg = load_config()
        mode = getattr(cfg.wingman_fleet_transport, "value", str(cfg.wingman_fleet_transport))
        if mode == "simulation":
            raise RuntimeError("simulation mode does not open a network listener")
        roster = self.roster()
        token = (cfg.wingman_fleet_token or roster.token).strip()
        if len(token) < 24:
            raise RuntimeError("fleet token must contain at least 24 characters")
        roster.token, roster.port = token, int(cfg.wingman_fleet_port)
        self.save_roster(roster)
        self.store = FleetStore(get_wingman_fleet_db_path())
        from config.paths import get_operator_token_path
        operator_token = ""
        operator_path = get_operator_token_path()
        if operator_path.is_file():
            try:
                from modules.fleet_agent.credentials import load_agent_token
                operator_token = load_agent_token(operator_path)
            except Exception:
                self.log("fleet: operator credentials could not be read")
                operator_token = ""
        self.coordinator = Coordinator(self.store, token=token, operator_token=operator_token, log=self.log)
        if not operator_token:
            try:
                from modules.fleet_agent.credentials import store_agent_token
                store_agent_token(operator_path, self.coordinator.operator_token)
            except Exception:
                self.log("fleet: operator credentials were not stored")
        from core.wingman_fleet.assignments import AssignmentBook
        self.assignments = AssignmentBook(self.store)
        self.coordinator.assignments = self.assignments
        if mode == "secure_lan":
            cert, key = cfg.wingman_fleet_tls_cert.strip(), cfg.wingman_fleet_tls_key.strip()
            if not cert or not key or not cfg.wingman_fleet_tls_ca.strip():
                raise RuntimeError("SECURE_LAN requires a certificate, a key, and a CA file")
            self.server = FleetServer(self.coordinator, host="0.0.0.0", port=roster.port).start(
                certfile=cert, keyfile=key,
            )
            url = f"https://{local_ip()}:{self.server.port}"
        else:
            self.log("fleet: localhost HTTP is a development transport, not a LAN deployment")
            self.server = FleetServer(self.coordinator, host="127.0.0.1", port=roster.port).start()
            url = f"http://127.0.0.1:{self.server.port}"
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
        from core.wingman_fleet.accounts import CatalogError
        from modules.fleet_accounts.catalog import AccountCatalog
        from modules.fleet_agent.credentials import CredentialError, load_agent_token
        from modules.vault.store import vault_login_names
        from config.paths import get_accounts_index_path, get_data_dir
        catalog = AccountCatalog(get_data_dir() / "fleet_catalog.db", agent_id=agent_id)
        index_path = get_accounts_index_path()
        names, vault_code = vault_login_names()
        if index_path.is_file():
            try:
                catalog.sync_index_payload(
                    index_path.read_text(encoding="utf-8"),
                    names if vault_code == "ok" else None,
                )
            except CatalogError as exc:
                self.log(f"fleet catalog: {exc}")
        if vault_code != "ok":
            catalog.note_vault_status(vault_code)
            self.log(f"fleet catalog: vault {vault_code}")
        url = (cfg.wingman_fleet_url or f"http://127.0.0.1:{roster.port}").rstrip("/")
        mode = getattr(cfg.wingman_fleet_transport, "value", str(cfg.wingman_fleet_transport))
        if mode == "simulation":
            raise RuntimeError("simulation mode does not open a network agent")
        if mode == "secure_lan" and not url.startswith("https://"):
            raise RuntimeError("SECURE_LAN agent requires an https coordinator URL")
        ca_file = cfg.wingman_fleet_tls_ca.strip() if url.startswith("https://") else ""
        agent_token = ""
        token_path = get_agent_token_path(agent_id)
        if token_path.is_file():
            try:
                agent_token = load_agent_token(token_path)
            except CredentialError as exc:
                self.log(f"fleet agent credentials: {exc}")
        self.agent = AgentService(
            agent_id, self.backend, HttpTransport(url, ca_file=ca_file), journal, token=token,
            build_version=APP_VERSION, resource_manifest=default_manifest(), computer=_machine(),
            log=self.log, catalog=catalog, agent_token=agent_token,
        )
        self._thread = threading.Thread(target=self.agent.run_forever, daemon=True, name="fleet-agent")
        self._thread.start()
        self.log(f"fleet agent {agent_id} → {url}")
        return {"running": True, "agent_id": agent_id, "url": url}

    def start_run(self) -> str:
        if self.coordinator is None:
            self.start_coordinator()
        book = getattr(self, "assignments", None)
        if book is None:
            raise RuntimeError("fleet assignments are not available")
        roster = self.roster()
        links = {agent_id: link.value for agent_id, link in self.coordinator.links().items()}
        plan = book.build_run_plan(
            roster, build_version=APP_VERSION, resource_manifest=default_manifest(), links=links,
        )
        self.save_roster(roster)
        if self.backend is not None and self.agent is not None:
            account = plan.account_for_agent(self.agent.agent_id)
            if account is not None:
                self.backend.apply_identity_assignment(account.steam_id64)
        self.coordinator.start_run(plan)
        self.log(f"fleet run {plan.run_id}")
        return plan.run_id

    def claim_agent(self, code: str) -> str:
        """Claim a one-time enrollment code and store the agent token with DPAPI."""
        from modules.fleet_agent.credentials import claim_enrollment, store_agent_token
        cfg = load_config()
        agent_id = (cfg.wingman_fleet_agent_id or "").strip()
        if not agent_id:
            raise RuntimeError("задайте wingman_fleet_agent_id")
        roster = self.roster()
        url = (cfg.wingman_fleet_url or f"http://127.0.0.1:{roster.port}").rstrip("/")
        ca_file = cfg.wingman_fleet_tls_ca.strip() if url.startswith("https://") else ""
        token, generation = claim_enrollment(url, agent_id, code.strip(), ca_file=ca_file)
        store_agent_token(get_agent_token_path(agent_id), token)
        journal = CommandJournal(get_wingman_agent_journal_path(agent_id))
        try:
            journal.bind_registration(generation)
        finally:
            journal.close()
        if self.agent is not None and self.agent.agent_id == agent_id:
            self._restart_local_agent()
            self.log(f"fleet agent {agent_id} enrolled and restarted")
        else:
            self.log(f"fleet agent {agent_id} enrolled")
        return agent_id

    def _restart_local_agent(self) -> dict[str, Any]:
        """Stop the running agent and start a new process generation with the new token."""
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
            try:
                self.backend.close()
            except Exception:
                pass
            self.backend = None
        return self.start_agent()

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
        cfg = load_config()
        mode = getattr(cfg.wingman_fleet_transport, "value", str(cfg.wingman_fleet_transport))
        tls = bool(self.server is not None and self.server.tls)
        registrations: dict[str, str] = {}
        book = getattr(self, "assignments", None)
        if book is not None:
            for entry in self.roster().slots.values():
                agent_id = str(entry.get("agent_id") or "")
                if agent_id:
                    registrations[agent_id] = book.registration_state(agent_id)
        if self.server is not None:
            scheme = "https" if tls else "http"
            url = f"{scheme}://{local_ip()}:{self.server.port}"
        else:
            url = cfg.wingman_fleet_url
        transport = "secure-lan" if mode == "secure_lan" and tls else (
            "simulation" if mode == "simulation" else "localhost-http"
        )
        st: dict[str, Any] = {
            "coordinator": bool(self.server),
            "agent": self.agent.snapshot() if self.agent else None,
            "url": url,
            "transport": transport,
            "lan_ready": lan_configuration_ready(
                mode=mode, tls=tls,
                cert_exists=bool(cfg.wingman_fleet_tls_cert) and Path(cfg.wingman_fleet_tls_cert).is_file(),
                ca_exists=bool(cfg.wingman_fleet_tls_ca) and Path(cfg.wingman_fleet_tls_ca).is_file(),
                registrations=registrations,
            ),
            "four_pc_proven": False,
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
