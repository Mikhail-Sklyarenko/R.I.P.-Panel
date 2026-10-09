"""One current-account test session, owned and stopped by the existing panel."""
import threading
import time
import uuid
from .setup import prepare


class TestSession:
    __test__ = False
    def __init__(self, config, log):
        self.config, self.log = config, log
        self.thread = None
        self.context = None

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self):
        if self.running:return False
        from modules.combat import csgobot_ai
        if csgobot_ai._PROCESS is not None and csgobot_ai._PROCESS.poll() is None:
            raise RuntimeError("Сначала остановите текущий бот")
        path, changed = prepare(self.config)
        if changed:
            self.log("Напарники: установлен канал состояния. Перезапустите CS2 один раз, откройте тестовый Inferno / Напарники и повторите запуск.")
            return False
        self.context = {"config":self.config,"session_id":"wingman-"+uuid.uuid4().hex[:10],
                        "login":"current-game-account","wingman_gsi_path":str(path),
                        "stop_requested":False,"emit":lambda event,detail="",**_:self.log(detail)}
        def run():
            try:
                ok = csgobot_ai.start_ai(self.context)
                self.log("Напарники: остановлено" if self.context["stop_requested"] else
                         "Напарники: тест завершён" if ok else "Напарники: тест прерван — проверьте журнал")
            except Exception as exc:
                self.log(f"Напарники: ошибка запуска — {exc}")
            finally:
                csgobot_ai.stop_ai()
        self.thread = threading.Thread(target=run,name="wingman-test",daemon=True)
        self.thread.start()
        self.log("Напарники: тест текущего аккаунта. Ожидаются данные Inferno / Напарники; автоматический поиск не выполняется.")
        return True

    def stop(self):
        if self.context is not None:self.context["stop_requested"] = True
        if self.thread is not None:
            self.thread.join(timeout=2)
        if self.running:
            from modules.combat import csgobot_ai
            csgobot_ai.stop_ai()
