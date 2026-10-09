"""Install a dedicated GSI config without changing the user's game settings."""
import json
import secrets
from pathlib import Path


def prepare(config):
    from config.paths import get_data_dir
    from modules.launcher.cs2 import find_csgo_cfg_dir, resolve_cs2_exe
    exe = resolve_cs2_exe(config)
    folder = find_csgo_cfg_dir(exe)
    state_path = get_data_dir() / "wingman_receiver.json"
    if state_path.is_file():
        settings = json.loads(state_path.read_text(encoding="utf-8"))
        token = settings.get("token", "")
        if not isinstance(token,str) or len(token) != 48 or any(c not in "0123456789abcdef" for c in token):
            raise ValueError("Invalid local Wingman receiver configuration")
    else:
        settings = {"token":secrets.token_hex(24), "port":4019}
        state_path.parent.mkdir(parents=True,exist_ok=True)
        state_path.write_text(json.dumps(settings),encoding="utf-8")
        state_path.chmod(0o600)
    text = ('"FarmPanel Wingman"\n{\n'
            ' "uri" "http://127.0.0.1:4019/wingman"\n'
            ' "timeout" "1.0"\n "buffer" "0.05"\n "throttle" "0.1"\n "heartbeat" "0.25"\n'
            ' "auth" { "token" "'+settings["token"]+'" }\n'
            ' "data" { "provider" "1" "map" "1" "round" "1" "player_id" "1" "player_state" "1" "player_weapons" "1" }\n}\n')
    path = folder / "gamestate_integration_farm_panel_wingman.cfg"
    changed = not path.is_file() or path.read_text(encoding="utf-8") != text
    if changed:path.write_text(text,encoding="utf-8")
    return state_path, changed
