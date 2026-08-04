"""Run end-to-end product dataset pipeline.

Stages:
1) (optional) download HF dataset via huggingface-cli
2) convert HF imagefolder -> YOLO
3) merge sources into product dataset
4) audit dataset
5) generate immutable manifest
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run product dataset pipeline")
    parser.add_argument("--workdir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--hf-repo", type=str, default="")
    parser.add_argument("--hf-local-dir", type=Path, default=Path("hf_raw/fvossel_cs2"))
    parser.add_argument("--hf-data-subdir", type=str, default="data")
    parser.add_argument("--convert-splits", type=str, default="train,validation")
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="source in form name=path_to_yolo_root",
    )
    parser.add_argument("--out-root", type=Path, default=Path("product_v1"))
    parser.add_argument("--classes", type=str, default="c,ch,t,th")
    parser.add_argument("--train-pct", type=int, default=80)
    parser.add_argument("--val-pct", type=int, default=10)
    parser.add_argument("--dedup-stem", action="store_true")
    parser.add_argument(
        "--copy-images",
        action="store_true",
        help="Copy images instead of symlinking (uses more disk)",
    )
    parser.add_argument("--manifest-out", type=Path, default=Path("manifests/product_v1_manifest.json"))
    args = parser.parse_args()

    workdir = args.workdir.resolve()
    py = sys.executable

    # Optional HF download
    if args.hf_repo:
        hf_cli = shutil.which("huggingface-cli")
        if hf_cli is None:
            raise RuntimeError(
                "huggingface-cli not found. Install: pip install 'huggingface_hub[cli]'"
            )
        run(
            [
                hf_cli,
                "download",
                args.hf_repo,
                "--repo-type",
                "dataset",
                "--local-dir",
                str((workdir / args.hf_local_dir).resolve()),
            ]
        )

    dynamic_sources = list(args.source)

    # Optional conversion if HF root exists
    hf_data_root = (workdir / args.hf_local_dir / args.hf_data_subdir).resolve()
    converted_root = (workdir / "sources" / "hf_converted").resolve()
    if hf_data_root.exists():
        convert_cmd = [
            py,
            str((workdir / "hf_to_yolo.py").resolve()),
            "--hf-root",
            str(hf_data_root),
            "--out-root",
            str(converted_root),
            "--splits",
            args.convert_splits,
        ]
        if args.copy_images:
            convert_cmd.append("--copy-images")
        run(convert_cmd)
        dynamic_sources.append(f"hf={converted_root}")

    if not dynamic_sources:
        raise RuntimeError("no sources provided; pass --source or --hf-repo with convertible data")

    # Build
    build_cmd = [
        py,
        str((workdir / "build_product_dataset.py").resolve()),
        "--out-root",
        str((workdir / args.out_root).resolve()),
        "--classes",
        args.classes,
        "--train-pct",
        str(args.train_pct),
        "--val-pct",
        str(args.val_pct),
    ]
    if args.dedup_stem:
        build_cmd.append("--dedup-stem")
    if args.copy_images:
        build_cmd.append("--copy-images")
    for src in dynamic_sources:
        build_cmd.extend(["--source", src])
    run(build_cmd)

    # Audit
    run(
        [
            py,
            str((workdir / "audit_dataset.py").resolve()),
            "--root",
            str((workdir / args.out_root).resolve()),
            "--names",
            args.classes,
        ]
    )

    # Manifest
    manifest_cmd = [
        py,
        str((workdir / "make_manifest.py").resolve()),
        "--root",
        str((workdir / args.out_root).resolve()),
        "--classes",
        args.classes,
        "--out",
        str((workdir / args.manifest_out).resolve()),
    ]
    for src in dynamic_sources:
        manifest_cmd.extend(["--source", src])
    run(manifest_cmd)

    print("pipeline complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
