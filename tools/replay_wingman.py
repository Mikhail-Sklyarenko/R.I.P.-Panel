"""Replay normalized observations without starting CS2 or sending input."""
from pathlib import Path
from dataclasses import asdict
import argparse
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.wingman.engine import Observation, Phase, RoundEngine


def replay(path):
    engine = RoundEngine()
    decisions = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            now = data.pop("received_at")
            for key in ("own_player", "alive", "buy_allowed", "connected"):
                if key in data and type(data[key]) is not bool:
                    raise ValueError(f"{key} must be boolean")
            for key in ("sequence", "round_number"):
                if type(data[key]) is not int:
                    raise ValueError(f"{key} must be integer")
            data["phase"] = Phase(data["phase"])
            decisions.append(asdict(engine.update(Observation(**data), now=now)))
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError(f"Line {number}: {exc}") from exc
    return decisions


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    try:
        for decision in replay(args.input):
            print(json.dumps(decision, ensure_ascii=False))
    except (ValueError, OSError) as exc:
        parser.exit(2, str(exc) + "\n")
