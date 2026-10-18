#!/data/data/com.termux/files/usr/bin/python
from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from dh import walker

GREEN = "\033[32m"
DIM = "\033[2m"
RESET = "\033[0m"

ALL_EXTS = [".jpg", ".jpeg", ".png", ".svg"]
KIND_BY_EXT: dict[str, str] = {
    ".jpg": "jpg",
    ".jpeg": "jpg",
    ".png": "png",
    ".svg": "svg",
}
TOOL_BY_KIND: dict[str, str] = {
    "jpg": "jpegoptim",
    "png": "pngquant",
    "svg": "svgo",
}


@dataclass
class Result:
    path: Path
    before: int
    after: int
    status: str
    kind: str
    detail: str = ""

    @property
    def saved(self) -> int:
        return max(self.before - self.after, 0)


def kind_of(p: Path) -> str:
    return KIND_BY_EXT.get(p.suffix.lower(), "")


def optimize_jpg(path: Path, before: int, opts: dict, dry_run: bool) -> Result:
    q = opts["jpg_quality"]
    if dry_run:
        tmpdir = tempfile.mkdtemp()
        try:
            cmd = ["jpegoptim", f"-m{q}", "--strip-all", "-q", "-d", tmpdir, str(path)]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            except FileNotFoundError:
                return Result(path, before, before, "error", "jpg", "jpegoptim not found")
            if proc.returncode != 0:
                return Result(path, before, before, "error", "jpg", (proc.stderr or proc.stdout).strip()[:200])
            out = Path(tmpdir) / path.name
            if not out.exists():
                return Result(path, before, before, "unchanged", "jpg")
            after = out.stat().st_size
            if after >= before:
                return Result(path, before, after, "unchanged", "jpg")
            return Result(path, before, after, "optimized", "jpg")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    cmd = ["jpegoptim", f"-m{q}", "--strip-all", "-q", "-o", str(path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return Result(path, before, before, "error", "jpg", "jpegoptim not found")
    if proc.returncode != 0:
        return Result(path, before, before, "error", "jpg", (proc.stderr or proc.stdout).strip()[:200])
    after = path.stat().st_size
    if after >= before:
        return Result(path, before, after, "unchanged", "jpg")
    return Result(path, before, after, "optimized", "jpg")


def optimize_png(path: Path, before: int, opts: dict, dry_run: bool) -> Result:
    tmp_out: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=path.suffix, dir=path.parent, delete=False) as tmp:
            tmp_out = Path(tmp.name)
        cmd = [
            "pngquant",
            "--force",
            "--strip",
            f"--quality={opts['png_quality']}",
            "--output",
            str(tmp_out),
            "--",
            str(path),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            return Result(path, before, before, "error", "png", "pngquant not found")
        if proc.returncode in (98, 99):
            return Result(path, before, before, "unchanged", "png")
        if proc.returncode != 0:
            return Result(path, before, before, "error", "png", f"exit {proc.returncode}")
        after = tmp_out.stat().st_size
        if after >= before:
            return Result(path, before, after, "unchanged", "png")
        if not dry_run:
            shutil.copymode(path, tmp_out)
            os.replace(tmp_out, path)
            tmp_out = None
        return Result(path, before, after, "optimized", "png")
    finally:
        if tmp_out is not None:
            try:
                tmp_out.unlink(missing_ok=True)
            except OSError:
                pass


def optimize_svg(path: Path, before: int, opts: dict, dry_run: bool) -> Result:
    tmp_out: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=path.suffix, dir=path.parent, delete=False) as tmp:
            tmp_out = Path(tmp.name)
        cmd = ["svgo", "-q", "-i", str(path), "-o", str(tmp_out)]
        if opts["svg_multipass"]:
            cmd.append("--multipass")
        if opts["svg_precision"] is not None:
            cmd.extend(["--precision", str(opts["svg_precision"])])
        if opts["svg_config"]:
            cmd.extend(["--config", opts["svg_config"]])
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            return Result(path, before, before, "error", "svg", "svgo not found")
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout).strip()[:200]
            return Result(path, before, before, "error", "svg", err or f"exit {proc.returncode}")
        after = tmp_out.stat().st_size
        if after >= before:
            return Result(path, before, after, "unchanged", "svg")
        if not dry_run:
            shutil.copymode(path, tmp_out)
            os.replace(tmp_out, path)
            tmp_out = None
        return Result(path, before, after, "optimized", "svg")
    finally:
        if tmp_out is not None:
            try:
                tmp_out.unlink(missing_ok=True)
            except OSError:
                pass


def optimize_one(args: tuple[Path, dict, bool]) -> Result:
    path, opts, dry_run = args
    kind = kind_of(path)
    try:
        before = path.stat().st_size
    except OSError as e:
        return Result(path, 0, 0, "error", kind, str(e))
    try:
        if kind == "jpg":
            return optimize_jpg(path, before, opts, dry_run)
        if kind == "png":
            return optimize_png(path, before, opts, dry_run)
        if kind == "svg":
            return optimize_svg(path, before, opts, dry_run)
        return Result(path, before, before, "unchanged", kind, "unknown extension")
    except Exception as e:
        return Result(path, 0, 0, "error", kind, f"{type(e).__name__}: {e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 4)
    ap.add_argument("-n", "--dry-run", action="store_true")
    ap.add_argument("--root", default=".")
    ap.add_argument("--no-recursive", action="store_true")
    ap.add_argument("--only", nargs="+", choices=["jpg", "png", "svg"], default=None)
    ap.add_argument("--jpg-quality", type=int, default=70)
    ap.add_argument("--png-quality", default="65-80")
    ap.add_argument("--svg-precision", type=int, default=None)
    ap.add_argument("--svg-config", default=None)
    ap.add_argument("--no-svg-multipass", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    files = list(walker(root, recursive=not args.no_recursive, exts=ALL_EXTS))

    if args.only:
        only_set = set(args.only)
        files = [p for p in files if kind_of(p) in only_set]

    if not files:
        print(f"No matching files found under {root}")
        return 0

    kinds_present = {kind_of(p) for p in files}
    missing_tools: set[str] = set()
    for k in kinds_present:
        tool = TOOL_BY_KIND[k]
        if shutil.which(tool) is None:
            missing_tools.add(tool)
            print(f"Warning: {tool} not found — skipping all {k} files", file=sys.stderr)
    files = [p for p in files if TOOL_BY_KIND.get(kind_of(p)) not in missing_tools]

    if not files:
        print("No processable files (all required tools missing).")
        return 1

    print(f"Root: {root}")
    print(f"Files: {len(files)} | jobs: {args.jobs} | dry-run: {args.dry_run}")
    print(
        f"jpg-quality: {args.jpg_quality} | png-quality: {args.png_quality} | "
        f"svg-multipass: {not args.no_svg_multipass}"
    )
    print("-" * 60)

    opts = {
        "jpg_quality": args.jpg_quality,
        "png_quality": args.png_quality,
        "svg_precision": args.svg_precision,
        "svg_config": args.svg_config,
        "svg_multipass": not args.no_svg_multipass,
    }
    tasks = [(p, opts, args.dry_run) for p in files]

    total_saved = 0
    counts = {"optimized": 0, "unchanged": 0, "error": 0}
    by_kind: dict[str, int] = {}

    with mp.Pool(processes=args.jobs) as pool:
        for r in pool.imap_unordered(optimize_one, tasks):
            counts[r.status] = counts.get(r.status, 0) + 1
            if r.status == "optimized":
                total_saved += r.saved
                by_kind[r.kind] = by_kind.get(r.kind, 0) + r.saved
                print(f"{r.path.name} {GREEN}{r.saved}{RESET}")
            elif r.status == "unchanged":
                print(f"{r.path.name} {DIM}unchanged{RESET}")
            else:
                print(f"{r.path.name} {DIM}error: {r.detail}{RESET}", file=sys.stderr)

    print("-" * 60)
    label = "Would free" if args.dry_run else "Space freed"
    print(f"Optimized: {counts['optimized']} | Unchanged: {counts['unchanged']} | Errors: {counts['error']}")
    print(f"{label}: {GREEN}{total_saved:,} bytes{RESET} ({total_saved / 1024 / 1024:.2f} MiB)")
    for k in ("jpg", "png", "svg"):
        if k in by_kind:
            print(f"  {k}: {GREEN}{by_kind[k]:,} bytes{RESET}")
    if args.dry_run:
        print("(dry run — no files were modified)")
    return 0 if counts["error"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
