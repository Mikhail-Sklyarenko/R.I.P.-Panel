"""Read-only HUD monitor inside the existing panel; never focuses CS2."""
import time
import customtkinter as ctk
from modules.wingman.visual import HudReader

_LABELS = {"unknown": "Нет подтверждённого состояния — управление не разрешено",
           "finished": "Итог матча", "halftime": "Смена сторон",
           "round_over": "Раунд завершён", "buy_menu": "Окно закупки",
           "defusing": "Обезвреживание выполняется"}


class WingmanMonitor:
    def __init__(self, root):
        self.window = ctk.CTkToplevel(root)
        self.window.title("Напарники — проверка распознавания")
        self.window.geometry("560x180")
        self.label = ctk.CTkLabel(self.window, text="Переключитесь в открытое окно CS2", wraplength=520)
        self.label.pack(padx=16, pady=20)
        ctk.CTkLabel(self.window, text="Только наблюдение · русский HUD · 1280×720").pack()
        self.closed = False
        self.reader = None
        self.handle = None
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.job = self.window.after(500, self.poll)

    def close(self):
        self.closed = True
        if self.job is not None:
            self.window.after_cancel(self.job)
            self.job = None
        self.window.destroy()

    def poll(self):
        self.job = None
        if self.closed:
            return
        try:
            import win32gui
            from modules.ui_nav.window import find_cs2_hwnd
            from modules.ui_nav.capture import capture_client
            if self.reader is None:
                self.reader = HudReader()
            hwnd = find_cs2_hwnd()
            if win32gui.GetForegroundWindow() != hwnd or win32gui.IsIconic(hwnd):
                self.label.configure(text="Переключитесь в CS2: перекрытое окно не анализируется")
            else:
                image = capture_client(hwnd, skip_focus=True)
                evidence = self.reader.read(image, now=time.monotonic())
                text = ("Требуется клиентская область 1280×720" if evidence.reason == "uncalibrated_resolution"
                        else _LABELS[evidence.state])
                self.label.configure(text=text)
        except Exception as exc:
            self.label.configure(text=f"Наблюдение недоступно: {exc}")
        if not self.closed:
            self.job = self.window.after(500, self.poll)
