"""Windowed source launcher. Keep startup failures visible without a console."""
from pathlib import Path
import os
import sys
import traceback


def launch():
    root = Path(__file__).resolve().parent
    os.chdir(root)
    log_path = Path(os.environ.get("FARM_PANEL_DATA_DIR") or root / "data") / "logs" / "panel-startup.log"
    stream = None
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stream = log_path.open("a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = stream
        from main import main
        return main()
    except Exception:
        detail = traceback.format_exc()
        if stream is not None:
            stream.write(detail)
            stream.flush()
        if sys.platform == "win32":
            import ctypes
            message = ("Не удалось запустить Farm Panel.\n\nПодробности: " + str(log_path)
                       if stream is not None else "Не удалось создать журнал Farm Panel.\n\n" + detail)
            ctypes.windll.user32.MessageBoxW(None, message, "Farm Panel", 0x10)
        return 1


if __name__ == "__main__":
    raise SystemExit(launch())
