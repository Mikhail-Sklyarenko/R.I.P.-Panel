"""Exit 0 if PyTorch CUDA is available in csgobot venv. Prints JSON to stdout."""

from __future__ import annotations

import json
import sys


def run_check() -> dict[str, object]:
    try:
        import torch
    except Exception as exc:
        return {
            "cuda": False,
            "device": "",
            "torch_version": "",
            "error": f"torch import failed: {exc}",
            "install_hint": (
                "pip install torch torchvision --index-url "
                "https://download.pytorch.org/whl/cu121"
            ),
        }

    cuda = bool(torch.cuda.is_available())
    device = ""
    if cuda:
        try:
            device = str(torch.cuda.get_device_name(0))
        except Exception:
            device = "cuda:0"

    result: dict[str, object] = {
        "cuda": cuda,
        "device": device,
        "torch_version": str(getattr(torch, "__version__", "")),
    }
    if not cuda:
        result["install_hint"] = (
            "pip install torch torchvision --index-url "
            "https://download.pytorch.org/whl/cu121"
        )
    return result


def main() -> int:
    result = run_check()
    print(json.dumps(result))
    if not result.get("cuda"):
        hint = result.get("install_hint", "install CUDA-enabled PyTorch")
        print(str(hint), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
