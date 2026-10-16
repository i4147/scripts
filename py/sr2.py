from __future__ import annotations

import argparse
import base64
import hashlib
import os
import sys
import zipfile
from email.parser import Parser
from pathlib import Path


def prefix_path() -> Path:
    p = os.environ.get("PREFIX")
    if p:
        return Path(p)
    return Path(sys.base_prefix)


def site_packages_paths(prefix: Path):
    pyver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    return [prefix / "lib" / pyver / "site-packages"]


def find_distributions(site_dirs):
    dists = {}
    for sd in site_dirs:
        if not sd.exists():
            continue
        for p in sd.iterdir():
            if p.is_dir() and (p.name.endswith(".dist-info") or p.name.endswith(".egg-info")):
                key = p.name.rsplit(".", 1)[0].lower()
                dists[key] = p
    return dists


def parse_metadata(distinfo_dir):
    md = {}
    for candidate in ("METADATA", "PKG-INFO"):
        p = distinfo_dir / candidate
        if p.exists():
            txt = p.read_text(encoding="utf-8", errors="ignore")
            parsed = Parser().parsestr(txt)
            md["Name"] = parsed.get("Name")
            md["Version"] = parsed.get("Version")
            md["Summary"] = parsed.get("Summary")
            break
    return md


def read_record(distinfo_dir):
    rec = distinfo_dir / "RECORD"
    if rec.exists():
        return [line.split(",", 1)[0] for line in rec.read_text(encoding="utf-8").splitlines() if line.strip()]
    return []


def compute_hash_and_size(path: Path) -> tuple[str, str]:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    digest = base64.urlsafe_b64encode(h.digest()).rstrip(b"=").decode("ascii")
    return "sha256=" + digest, str(path.stat().st_size)


def _has_native_extensions(files) -> bool:
    native_exts = {
        ".so",
        ".pyd",
        ".dll",
        ".dylib",
        ".sl",
    }
    return any(f.suffix.lower() in native_exts for f in files)


def detect_wheel_tags() -> tuple[str, str, LiteralString]:
    impl = sys.implementation.name
    mj, mn = (
        sys.version_info.major,
        sys.version_info.minor,
    )
    if impl == "cpython":
        py_tag = f"cp{mj}{mn}"
        abi_tag = f"cp{mj}{mn}"
    else:
        py_tag = f"py{mj}"
        abi_tag = "none"
    plat_tag = sys.platform.replace("-", "_").replace(".", "_")
    return py_tag, abi_tag, plat_tag


def build_pure_wheel(distinfo_path, wheel_out_path: Path) -> None:
    base = distinfo_path.parent
    rec_list = read_record(distinfo_path)
    if not rec_list:
        return
    files = [base / f for f in rec_list if (base / f).exists()]
    if _has_native_extensions(files):
        return
    parse_metadata(distinfo_path).get("Name") or distinfo_path.stem
    parse_metadata(distinfo_path).get("Version") or "0"
    distinfo_dir = next(
        (f for f in files if f.name.endswith(".dist-info")),
        None,
    )
    if not distinfo_dir:
        distinfo_dir = distinfo_path
    _py_tag, _abi_tag, _plat_tag = detect_wheel_tags()
    wheel_tag = "py3-none-any"
    with zipfile.ZipFile(
        wheel_out_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as zf:
        for f in files:
            if f.is_file():
                zf.write(
                    f,
                    arcname=f.relative_to(base).as_posix(),
                )
        wheel_file_content = f"""Wheel-Version: 1.0
Generator: repack_pure/1.0
Root-Is-Purelib: true
Tag: {wheel_tag}
"""
        zf.writestr(
            f"{distinfo_dir.name}/WHEEL",
            wheel_file_content,
        )
        record_lines = []
        for f in files:
            if f.is_file():
                h, size = compute_hash_and_size(f)
                record_lines.append(f"{f.relative_to(base).as_posix()},{h},{size}")
        record_lines.append(f"{distinfo_dir.name}/RECORD,,")
        zf.writestr(
            f"{distinfo_dir.name}/RECORD",
            "\n".join(record_lines),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Repack only pure Python packages as wheels")
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Repack all installed packages",
    )
    parser.add_argument(
        "packages",
        nargs="*",
        help="Package names to repack",
    )
    args = parser.parse_args()
    prefix = prefix_path()
    site_dirs = site_packages_paths(prefix)
    dists = find_distributions(site_dirs)
    to_do = []
    if args.all or not args.packages:
        to_do = list(dists.values())
    else:
        for name in args.packages:
            key = name.lower()
            found = next(
                (p for k, p in dists.items() if k.startswith(key)),
                None,
            )
            if found:
                to_do.append(found)
    wheel_dir = Path.home() / "wheels"
    wheel_dir.mkdir(parents=True, exist_ok=True)
    for dist in to_do:
        try:
            dist_name = parse_metadata(dist).get("Name") or dist.stem
            version = parse_metadata(dist).get("Version") or "0"
            wheel_out = wheel_dir / f"{dist_name.replace('-', '_')} -{version} -py3-none-any.whl"
            build_pure_wheel(dist, wheel_out)
        except Exception:
            pass


if __name__ == "__main__":
    main()
