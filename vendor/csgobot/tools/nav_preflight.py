"""CLI: minimap nav asset preflight (JSON stdout)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nav.preflight import run_nav_preflight  # noqa: E402


def main() -> int:
    pack_id = os.environ.get("CSGOBOT_NAV_PACK", "auto").strip() or "auto"
    cal_path = os.environ.get("CSGOBOT_NAV_CALIBRATION", "").strip()
    result = run_nav_preflight(pack_id=pack_id, calibration_path=cal_path)
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
