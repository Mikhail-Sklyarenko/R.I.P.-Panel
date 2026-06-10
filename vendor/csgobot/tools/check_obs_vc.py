"""Exit 0 if OBS Virtual Camera is listed in DirectShow devices, else 1."""

from __future__ import annotations

import sys

DEFAULT_DEVICE = "OBS Virtual Camera"


def main() -> int:
    device_name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DEVICE
    try:
        from pygrabber.dshow_graph import FilterGraph

        devices = FilterGraph().get_input_devices()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if device_name in devices:
        print(device_name)
        return 0
    print(
        f'"{device_name}" not found; available: {devices}',
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
