import json
import os
import tomllib
from pathlib import Path


def detect_binaries(crate_dir: Path):
    cargo_toml = crate_dir / "Cargo.toml"
    src_main = crate_dir / "src" / "main.rs"
    binaries = []
    if src_main.exists():
        binaries.append(crate_dir.name)
    if cargo_toml.exists():
        with cargo_toml.open("rb") as f:
            data = tomllib.load(f)
        binaries.extend(bin_def["name"] for bin_def in data.get("bin", []) if "name" in bin_def)
    return list(set(binaries))


def scan(root):
    results = {}
    for entry in os.scandir(root):
        if entry.is_dir():
            bins = detect_binaries(Path(entry.path))
            if bins:
                results[entry.name] = bins
    return results


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "path",
        help="Directory containing Rust crates",
    )
    ap.add_argument(
        "-o",
        "--out",
        default="binary_crates.json",
    )
    args = ap.parse_args()
    data = scan(args.path)
    with Path(args.out).open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"Found {len(data)} binary crates → {args.out}")
