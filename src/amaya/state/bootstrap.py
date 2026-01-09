from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SEEDS = ROOT / "seeds"
DATA = ROOT / "data"


def _read_meta_version(path: Path) -> int | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    version = payload.get("version")
    if not isinstance(version, int):
        raise RuntimeError(f"Invalid meta.json version in {path}")
    return version


def _copy_seed_tree() -> None:
    for src in SEEDS.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(SEEDS)
        dst = DATA / rel
        if dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def ensure_runtime_data() -> None:
    if not SEEDS.exists():
        raise RuntimeError("Missing seeds/ directory")

    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "kb" / "projects").mkdir(parents=True, exist_ok=True)

    seed_version = _read_meta_version(SEEDS / "meta.json")
    if seed_version is None:
        raise RuntimeError("Missing seeds/meta.json")
    data_version = _read_meta_version(DATA / "meta.json")
    if data_version is not None and data_version != seed_version:
        raise RuntimeError(
            "Data version mismatch. Migration is required before startup."
        )

    _copy_seed_tree()
