"""Hard-negative promote helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_DATASETS = (
    Path(__file__).resolve().parents[1]
    / "vendor"
    / "csgobot"
    / "yolov8"
    / "datasets"
)
if str(_DATASETS) not in sys.path:
    sys.path.append( str(_DATASETS))

from promote_hard_negatives import is_hard_neg  # noqa: E402


def test_is_hard_neg_by_trigger() -> None:
    assert is_hard_neg({"trigger": "empty_scene"}, Path("x"), all_empty=False)
    assert is_hard_neg({"trigger": "texture_fp"}, Path("x"), all_empty=False)
    assert is_hard_neg({"force_empty": True}, Path("x"), all_empty=False)
    assert not is_hard_neg({"trigger": "timer"}, Path("x"), all_empty=False)


def test_promote_hard_negatives_writes_empty(tmp_path) -> None:
    from promote_hard_negatives import main

    raw = tmp_path / "captures" / "pc" / "sess"
    (raw / "images").mkdir(parents=True)
    (raw / "meta").mkdir()
    (raw / "labels_soft").mkdir()
    img = raw / "images" / "frame1__t__texture_fp.jpg"
    img.write_bytes(
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
    )
    (raw / "labels_soft" / "frame1__t__texture_fp.txt").write_text(
        "0 0.5 0.5 0.1 0.2\n", encoding="utf-8"
    )
    (raw / "meta" / "frame1__t__texture_fp.json").write_text(
        json.dumps(
            {
                "trigger": "texture_fp",
                "force_empty": True,
                "pc_id": "pc",
                "team": "t",
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "hard_negatives"
    rc = main(
        [
            "--raw-root",
            str(tmp_path / "captures"),
            "--out-root",
            str(out),
            "--train-pct",
            "100",
            "--val-pct",
            "0",
        ]
    )
    assert rc == 0
    labels = list((out / "train" / "labels").glob("*.txt"))
    assert len(labels) == 1
    assert labels[0].read_text(encoding="utf-8") == ""


def test_import_empty_yolo_splits_preserves_split(tmp_path) -> None:
    from import_empty_yolo_splits import main

    root = tmp_path / "bootstrap"
    for split, stem, empty in (
        ("train", "map_a", True),
        ("train", "map_b", False),
        ("val", "map_c", True),
    ):
        img_dir = root / split / "images"
        lbl_dir = root / split / "labels"
        img_dir.mkdir(parents=True, exist_ok=True)
        lbl_dir.mkdir(parents=True, exist_ok=True)
        (img_dir / f"{stem}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + stem.encode())
        (lbl_dir / f"{stem}.txt").write_text(
            "" if empty else "0 0.5 0.5 0.1 0.2\n", encoding="utf-8"
        )

    out = tmp_path / "hard_negatives"
    rc = main(
        [
            "--dataset-root",
            str(root),
            "--out-root",
            str(out),
            "--prefix",
            "hn_bs_",
            "--summary",
            str(tmp_path / "summary.json"),
        ]
    )
    assert rc == 0
    assert (out / "train" / "images" / "hn_bs_map_a.png").is_file()
    assert (out / "train" / "labels" / "hn_bs_map_a.txt").read_text(encoding="utf-8") == ""
    assert not (out / "train" / "images" / "hn_bs_map_b.png").exists()
    assert (out / "val" / "images" / "hn_bs_map_c.png").is_file()
    assert (tmp_path / "summary.json").is_file()
