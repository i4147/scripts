from __future__ import annotations
import argparse
import subprocess
import sys
import tempfile
import zipfile
from configparser import ConfigParser
from pathlib import Path


def termux_prefix_bin() -> Path:
    return Path("/data/data/com.termux/files/usr/bin")


def find_downloaded_artifacts(workdir: Path) -> list[Path]:
    exts = {".whl", ".tar.gz", ".tar.bz2", ".zip", ".tar"}
    artifacts = []
    for p in workdir.rglob("*"):
        if p.is_file() and any(str(p).endswith(ext) for ext in exts):
            artifacts.append(p)
    return artifacts


def parse_console_script_names_from_wheel(wheel_path: Path) -> list[str]:
    names: list[str] = []
    with zipfile.ZipFile(wheel_path, "r") as zf:
        entry_points_paths = [n for n in zf.namelist() if n.endswith(".dist-info/entry_points.txt")]
        if not entry_points_paths:
            return names
        for ep_path in entry_points_paths:
            raw = zf.read(ep_path).decode("utf-8", errors="replace")
            cfg = ConfigParser()
            cfg.read_string(raw)
            if cfg.has_section("console_scripts"):
                for key in cfg["console_scripts"]:
                    names.append(key.strip())
    seen = set()
    out = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def predict_collisions(bin_dir: Path, artifacts: list[Path]) -> list[str]:
    collisions: list[str] = []
    if not bin_dir.exists():
        return collisions
    existing = {p.name for p in bin_dir.iterdir() if p.is_file()}
    for art in artifacts:
        if art.suffix == ".whl":
            console_names = parse_console_script_names_from_wheel(art)
            for script_name in console_names:
                if script_name in existing:
                    collisions.append(str(bin_dir / script_name))
        else:
            pass
    return collisions


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Safe pip wrapper: download artifacts, inspect wheel entry points, abort on collision in protected bin."
    )
    ap.add_argument("package", help="Package specifier, e.g. requests==2.32.3")
    ap.add_argument(
        "--bin-dir", type=Path, default=termux_prefix_bin(), help="Protected bin directory (default: Termux usr/bin)"
    )
    ap.add_argument("--no-install", action="store_true", help="Only download+inspect, do not install.")
    args = ap.parse_args()
    bin_dir: Path = args.bin_dir
    with tempfile.TemporaryDirectory(prefix="pip-safe-") as td:
        workdir = Path(td)
        cmd_download = [sys.executable, "-m", "pip", "download", "--no-deps", "--dest", str(workdir), args.package]
        print("Downloading:", " ".join(cmd_download))
        subprocess.run(cmd_download, check=True)
        artifacts = find_downloaded_artifacts(workdir)
        if not artifacts:
            print("No downloadable artifacts found; aborting.")
            sys.exit(2)
        print("Artifacts found:")
        for a in artifacts:
            print(" -", a.name)
        collisions = predict_collisions(bin_dir, artifacts)
        if collisions:
            print("\nABORT: Predicted collisions with existing files in protected bin dir:")
            for c in collisions:
                print(" -", c)
            sys.exit(1)
        print("\nNo predicted wheel-script collisions found.")
        if args.no_install:
            print("Skipping install due to --no-install.")
            return
        cmd_install = [sys.executable, "-m", "pip", "install", "--no-deps"]
        cmd_install += [str(a) for a in artifacts]
        print("Installing:", " ".join(cmd_install))
        subprocess.run(cmd_install, check=True)
        print("\nDone.")


if __name__ == "__main__":
    main()
