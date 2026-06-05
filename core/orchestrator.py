"""Очередь аккаунтов, одна активная сессия, worker thread → JSONL + UI."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable

from dataclasses import dataclass

from config.loader import load_config
from core.session_fsm import run_session
from core.session_mode import SessionMode
from core.session_state import SessionState


@dataclass(frozen=True)
class _QueueItem:
    login: str
    mode: SessionMode = SessionMode.FULL
    force_farm: bool = False


class Orchestrator:
    def __init__(
        self,
        *,
        test_mode: bool = True,
        ui_callback: Callable[[str], None] | None = None,
        drop_callback: Callable[[str], None] | None = None,
        on_session_complete: Callable[
            [str, SessionState, SessionMode], None
        ] | None = None,
    ) -> None:
        self.test_mode = test_mode
        self._ui_callback = ui_callback or (lambda _msg: None)
        self._drop_callback = drop_callback or (lambda _msg: None)
        self._on_session_complete = on_session_complete
        self._queue: queue.Queue[_QueueItem | None] = queue.Queue()
        self.launched_count: int = 0
        self._stop_requested = threading.Event()
        self._worker: threading.Thread | None = None
        self._active_login: str | None = None
        self._lock = threading.Lock()

    @property
    def active_login(self) -> str | None:
        return self._active_login

    def enqueue(
        self,
        logins: list[str],
        *,
        mode: SessionMode = SessionMode.FULL,
        force_farm: bool = False,
    ) -> None:
        if not logins:
            self._ui_callback("orchestrator: no accounts to enqueue")
            return
        for login in logins:
            self._queue.put(
                _QueueItem(login.strip(), mode=mode, force_farm=force_farm)
            )
        self._ui_callback(
            f"orchestrator: queued {len(logins)} — {', '.join(logins)}"
        )
        self._ensure_worker()

    def stop(self) -> None:
        self._stop_requested.set()
        self._queue.put(None)
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=5.0)
        self._worker = None
        self._stop_requested.clear()
        self._ui_callback("orchestrator: stop requested")

    def wait_until_idle(self, timeout: float = 60.0) -> bool:
        """Дождаться опустошения очереди (worker остаётся жив для следующих enqueue)."""
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
        return True

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker and self._worker.is_alive():
                return
            self._stop_requested.clear()
            self._worker = threading.Thread(
                target=self._worker_loop,
                name="farm-orchestrator",
                daemon=True,
            )
            self._worker.start()

    def _worker_loop(self) -> None:
        while not self._stop_requested.is_set():
            try:
                item = self._queue.get(timeout=0.3)
            except queue.Empty:
                continue
            if item is None:
                self._queue.task_done()
                break
            login = item.login
            self._active_login = login
            self.launched_count += 1
            try:
                self._ui_callback(f"orchestrator: session start {login}")
                final = run_session(
                    login,
                    test_mode=self.test_mode,
                    session_mode=item.mode,
                    force_farm=item.force_farm,
                    on_main=self._ui_callback,
                    on_drop=self._drop_callback,
                )
                if final != SessionState.DONE:
                    self._ui_callback(f"[{login}] ended ({final.value})")
                if self._on_session_complete:
                    self._on_session_complete(login, final, item.mode)
            except Exception as exc:
                self._ui_callback(f"[{login}] error: {exc}")
                if self._on_session_complete:
                    self._on_session_complete(
                        login, SessionState.FAILED, item.mode
                    )
            finally:
                self._active_login = None
                self._queue.task_done()
                if not self._stop_requested.is_set():
                    self._cooldown_between_accounts()

        with self._lock:
            self._worker = None

    def _cooldown_between_accounts(self) -> None:
        """FSM ACCOUNTS_LAUNCH_DELAY → cooldown_between_accounts_sec."""
        delay = int(load_config().cooldown_between_accounts_sec)
        if delay <= 0:
            return
        if self._queue.empty():
            return
        self._ui_callback(
            f"orchestrator: cooldown {delay}s before next account"
        )
        deadline = time.monotonic() + delay
        while time.monotonic() < deadline:
            if self._stop_requested.is_set():
                return
            time.sleep(0.2)
