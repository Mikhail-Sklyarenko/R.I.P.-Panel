"""Start Studio in the csgobot environment without importing its config in UI."""
from pathlib import Path
import subprocess
import sys

from config.paths import get_app_root


def launch_studio():
    root = Path(get_app_root())
    script = root/'scripts/nav_studio.py'
    if not script.exists():
        raise FileNotFoundError('Установите обновление Navigation Studio в корень проекта')
    candidates = [root/'vendor/csgobot/venv/Scripts/python.exe', root/'.venv/Scripts/python.exe',
                  root/'vendor/csgobot/venv/bin/python', root/'.venv/bin/python']
    python = next((p for p in candidates if p.is_file()), None)
    if python is None and not getattr(sys, 'frozen', False):
        python = Path(sys.executable)
    if python is None:
        raise FileNotFoundError('Не найден Python среды csgobot')
    return subprocess.Popen([str(python), str(script)], cwd=root,
                            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == 'win32' else 0)
