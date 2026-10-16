from __future__ import annotations
import argparse
import base64
import hashlib
import operator
import os
import shutil
import sys
import sysconfig
import zipfile
from configparser import ConfigParser
from email.parser import Parser
from pathlib import Path


def prefix_path() -> Path:
    p = os.environ.get("PREFIX")
    if p:
        return Path(p)
    Path(sysconfig.get_paths()["purelib"])
    return Path(os.environ.get("PREFIX", sys.base_prefix))


def site_packages_paths(prefix):
    pyver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    candidates = [prefix / "lib" / pyver / "site-packages"]
    for p in sys.path:
        try:
            ppath = Path(p)
        except Exception:
            continue
        if (prefix in ppath.parents or ppath == prefix) and ppath.exists():
            candidates.append(ppath)
    seen = set()
    out = []
    for c in candidates:
        if c.exists() and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def find_distributions(site_dirs: list[Path]):
    dists = {}
    for sd in site_dirs:
        for p in sd.iterdir():
            if p.is_dir() and (p.name.endswith(".dist-info") or p.name.endswith(".egg-info")):
                key = p.name.rsplit(".", 1)[0].lower()
                dists[key] = p
    return dists


def parse_metadata_from_distinfo(distinfo_dir):
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
    ep = distinfo_dir / "entry_points.txt"
    if ep.exists():
        config = ConfigParser()
        try:
            config.read_string("[DEFAULT]\n" + ep.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            config.read(ep)
        lines = ep.read_text(encoding="utf-8", errors="ignore").splitlines()
        section = None
        console = []
        for ln in lines:
            ln = ln.strip()
            if ln.startswith("[") and ln.endswith("]"):
                section = ln[1:-1].strip()
                continue
            if section == "console_scripts" and ln and (not ln.startswith("#")):
                left = ln.split("=", 1)[0].strip()
                console.append(left)
        md["console_scripts"] = console
    return md


def read_record_list(distinfo_dir):
    rec = distinfo_dir / "RECORD"
    if rec.exists():
        return [
            l.strip().split(",", 1)[0]
            for l in rec.read_text(encoding="utf-8", errors="ignore").splitlines()
            if l.strip()
        ]
    for p in (distinfo_dir / "installed-files.txt", distinfo_dir / "installed_files.txt"):
        if p.exists():
            return [l.strip() for l in p.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
    tt = distinfo_dir / "top_level.txt"
    if tt.exists():
        return [l.strip() for l in tt.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
    return None


def find_script_paths(prefix, script_names):
    bin_dir = prefix / "bin"
    out = []
    if not bin_dir.exists():
        return out
    for s in script_names:
        sp = bin_dir / s
        if sp.exists():
            out.append(sp)
        else:
            for alt in (s, s + ".py", s + "-script.py", s + ".sh"):
                ap = bin_dir / alt
                if ap.exists():
                    out.append(ap)
                    break
    return out


def safe_copy(src, dest) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def compute_hash_and_size(path) -> tuple[str, str]:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    digest = base64.urlsafe_b64encode(h.digest()).rstrip(b"=").decode("ascii")
    return ("sha256=" + digest, str(path.stat().st_size))


def detect_wheel_tags():
    impl = sys.implementation.name
    mj = sys.version_info.major
    mn = sys.version_info.minor
    if impl == "cpython":
        py_tag = f"cp{mj}{mn}"
        abi_tag = f"cp{mj}{mn}"
    else:
        cache = getattr(sys.implementation, "cache_tag", None)
        if cache and "-" in cache:
            py_tag, abi_tag = cache.split("-", 1)
        else:
            py_tag = f"py{mj}"
            abi_tag = "none"
    plat = sysconfig.get_platform().replace("-", "_").replace(".", "_")
    return (py_tag, abi_tag, plat)


def collect_files_for_dist(distinfo_path, site_dirs: list[Path], prefix: Path):
    site_dirs[0] if site_dirs else Path()
    collected = []
    base = distinfo_path.parent
    rec_list = read_record_list(distinfo_path)
    if rec_list:
        if all(("/" not in p and "\\" not in p for p in rec_list)):
            for name in rec_list:
                candidates = [base / name, base / (name + ".py")]
                if "-" in name:
                    candidates += [base / name.replace("-", "_"), base / (name.replace("-", "_") + ".py")]
                for c in candidates:
                    if c.exists():
                        if c.is_dir():
                            for root, _, files in os.walk(c):
                                for fn in files:
                                    s = Path(root) / fn
                                    rel = s.relative_to(base)
                                    collected.append((s, rel))
                        else:
                            collected.append((c, c.relative_to(base)))
        else:
            for rel in rec_list:
                if not rel or rel.startswith(("..", "/")):
                    continue
                src = base / rel
                if src.exists():
                    if src.is_dir():
                        for root, _, files in os.walk(src):
                            for fn in files:
                                s = Path(root) / fn
                                relp = s.relative_to(base)
                                collected.append((s, relp))
                    else:
                        collected.append((src, Path(rel)))
                else:
                    alt = prefix / rel
                    if alt.exists():
                        if alt.is_dir():
                            for root, _, files in os.walk(alt):
                                for fn in files:
                                    s = Path(root) / fn
                                    relp = s.relative_to(prefix)
                                    collected.append((s, relp))
                        else:
                            collected.append((alt, Path(rel)))
    md = parse_metadata_from_distinfo(distinfo_path)
    for item in distinfo_path.iterdir():
        if item.is_file():
            rel = item.relative_to(base)
            collected.append((item, rel))
    if "console_scripts" in md:
        for sp in find_script_paths(prefix, md["console_scripts"]):
            rel = sp.relative_to(prefix)
            collected.append((sp, rel))
    seen = set()
    final = []
    for src, rel in collected:
        k = str(rel)
        if k not in seen:
            seen.add(k)
            final.append((src, rel))
    return (final, md)


def _has_native_extensions(tree_items) -> bool:
    native_exts = {".so", ".pyd", ".dll", ".dylib", ".sl"}
    return any((src.suffix.lower() in native_exts for src, _ in tree_items))


def build_wheel_from_tree(tree_items, dist_name, version, workdir: Path, wheel_out_path: Path):
    for src, rel in tree_items:
        dest = workdir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_file():
            shutil.copy2(src, dest)
    distinfo_dirs = list(workdir.glob("*.dist-info"))
    if not distinfo_dirs:
        dinfo = f"{dist_name}-{version}.dist-info"
        distinfo_dir = workdir / dinfo
        distinfo_dir.mkdir(parents=True, exist_ok=True)
    else:
        distinfo_dir = distinfo_dirs[0]
    py_tag, abi_tag, plat_tag = detect_wheel_tags()
    is_platform_specific = _has_native_extensions(tree_items)
    if is_platform_specific:
        wheel_tag = f"{py_tag}-{abi_tag}-{plat_tag}"
        root_is_purelib = "false"
    else:
        wheel_tag = "py3-none-any"
        root_is_purelib = "true"
    wheel_file = distinfo_dir / "WHEEL"
    if not wheel_file.exists():
        content = [
            "Wheel-Version: 1.0",
            "Generator: repack_wheels/1.0",
            f"Root-Is-Purelib: {root_is_purelib}",
            f"Tag: {wheel_tag}",
            "",
        ]
        wheel_file.write_text("\n".join(content), encoding="utf-8")
    record_lines = []
    all_files = []
    for root, _, files in os.walk(workdir):
        for fn in files:
            full = Path(root) / fn
            rel = full.relative_to(workdir).as_posix()
            all_files.append((full, rel))
    for full, rel in sorted(all_files, key=operator.itemgetter(1)):
        if rel.endswith("/RECORD") or rel == "RECORD":
            continue
        h, size = compute_hash_and_size(full)
        record_lines.append(f"{rel},{h},{size}")
    record_lines.append(f"{distinfo_dir.name + '/RECORD'},,")
    rec = distinfo_dir / "RECORD"
    rec.write_text("\n".join(record_lines) + "\n", encoding="utf-8")
    wheel_out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(wheel_out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(workdir):
            for fn in files:
                full = Path(root) / fn
                rel = full.relative_to(workdir).as_posix()
                zf.write(full, arcname=rel)
    return wheel_out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Repack installed packages into .whl files (Termux-aware).")
    parser.add_argument("packages", nargs="*", help="Package names (distribution names). If none given, repack all.")
    parser.add_argument("-a", "--all", action="store_true", help="Repack all installed packages")
    args = parser.parse_args()
    if not args.packages and (not args.all):
        args.all = True
    prefix = prefix_path()
    site_dirs = [Path(Path.cwd())]
    dists = find_distributions(site_dirs)
    if args.all:
        to_do = list(dists.values())
    else:
        to_do = []
        for name in args.packages:
            key = name.lower()
            found = None
            for k, p in dists.items():
                if k == key or k.startswith(key + "-") or k.split("-")[0] == key:
                    found = p
                    break
            if not found:
                pass
            else:
                to_do.append(found)
    repack_root = Path.home() / "tmp" / "repack"
    wheel_dir = Path.home() / "tmp" / "wheels"
    repack_root.mkdir(parents=True, exist_ok=True)
    wheel_dir.mkdir(parents=True, exist_ok=True)
    for distinfo in to_do:
        try:
            base_name = distinfo.name
            if base_name.endswith(".dist-info"):
                base = base_name[:-10]
            elif base_name.endswith(".egg-info"):
                base = base_name[:-9]
            else:
                base = base_name
            md = parse_metadata_from_distinfo(distinfo)
            dist_name = md.get("Name") or base.split("-", 1)[0]
            version = md.get("Version") or (base.split("-", 1)[1] if "-" in base else "0")
            items, md = collect_files_for_dist(distinfo, site_dirs, prefix)
            if not items:
                continue
            workdir = repack_root / f"{dist_name}-{version}"
            if workdir.exists():
                shutil.rmtree(workdir)
            workdir.mkdir(parents=True, exist_ok=True)
            py_tag, abi_tag, plat_tag = detect_wheel_tags()
            is_platform_specific = _has_native_extensions(items)
            if is_platform_specific:
                wheel_name = f"{dist_name.replace('-', '_')}-{version}-{py_tag}-{abi_tag}-{plat_tag}.whl"
            else:
                wheel_name = f"{dist_name.replace('-', '_')} -{version} -py3-none-any.whl"
            wheel_out = wheel_dir / wheel_name
            build_wheel_from_tree(items, dist_name, version, workdir, wheel_out)
        except Exception:
            pass


if __name__ == "__main__":
    main()
