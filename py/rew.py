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
    candidates = []
    candidates.append(prefix / "lib" / pyver / "site-packages")
    for p in sys.path:
        try:
            pth = Path(p)
        except Exception:
            continue
        if (prefix in pth.parents or pth == prefix) and pth.exists():
            candidates.append(pth)
    seen = []
    out = []
    for c in candidates:
        if c not in seen and c.exists():
            seen.append(c)
            out.append(c)
    return out


def find_distributions(site_dirs: list[Path]):
    dists = {}
    for sd in site_dirs:
        for p in sd.iterdir():
            if p.is_dir() and (p.name.endswith(".dist-info") or p.name.endswith(".egg-info")):
                key = p.name.rsplit(".")[0]
                dists[key.lower()] = p
    return dists


def parse_metadata_from_distinfo(distinfo_dir):
    md = {}
    for candidate in ["METADATA", "PKG-INFO"]:
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
        if config.has_section("console_scripts") or config.has_option("console_scripts", ""):
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
    for p in [distinfo_dir / "installed-files.txt", distinfo_dir / "installed_files.txt"]:
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


def safe_move(src, dest) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(src, dest)


def compute_hash_and_size(path) -> tuple[str, str]:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    digest = base64.urlsafe_b64encode(h.digest()).rstrip(b"=").decode("ascii")
    size = path.stat().st_size
    return ("sha256=" + digest, str(size))


def collect_files_for_dist(distinfo_path, site_dirs: list[Path], prefix: Path):
    site_dirs[0] if site_dirs else Path()
    collected = []
    base = distinfo_path.parent
    rec_list = read_record_list(distinfo_path)
    if rec_list:
        if all(("/" not in p and "\\" not in p for p in rec_list)):
            for name in rec_list:
                candidates = []
                candidates.extend((base / name, base / (name + ".py")))
                if "-" in name:
                    candidates.extend((base / name.replace("-", "_"), base / (name.replace("-", "_") + ".py")))
                for c in candidates:
                    if c.exists():
                        if c.is_dir():
                            for root, _dirs, files in os.walk(c):
                                for fn in files:
                                    s = Path(root) / fn
                                    rel = s.relative_to(base)
                                    collected.append((s, Path(rel)))
                        else:
                            collected.append((c, Path(c.relative_to(base))))
        else:
            for rel in rec_list:
                if not rel or rel.startswith(("..", "/")):
                    continue
                src = base / rel
                if src.exists():
                    if src.is_dir():
                        for root, _dirs, files in os.walk(src):
                            for fn in files:
                                s = Path(root) / fn
                                relp = s.relative_to(base)
                                collected.append((s, Path(relp)))
                    else:
                        collected.append((src, Path(rel)))
                else:
                    alt = prefix / rel
                    if alt.exists():
                        if alt.is_dir():
                            for root, _dirs, files in os.walk(alt):
                                for fn in files:
                                    s = Path(root) / fn
                                    relp = s.relative_to(prefix)
                                    collected.append((s, relp))
                        else:
                            collected.append((alt, Path(rel)))
    else:
        tl = distinfo_path / "top_level.txt"
        added = set()
        if tl.exists():
            tops = [l.strip() for l in tl.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
            for name in tops:
                for cand in (base / name, base / (name + ".py")):
                    if cand.exists():
                        if cand.is_dir():
                            for root, _dirs, files in os.walk(cand):
                                for fn in files:
                                    s = Path(root) / fn
                                    rel = s.relative_to(base)
                                    if rel not in added:
                                        collected.append((s, rel))
                                        added.add(rel)
                        else:
                            rel = cand.relative_to(base)
                            if rel not in added:
                                collected.append((cand, rel))
                                added.add(rel)
    for item in distinfo_path.iterdir():
        if item.is_file():
            rel = item.relative_to(base)
            collected.append((item, rel))
    md = parse_metadata_from_distinfo(distinfo_path)
    if "console_scripts" in md:
        scripts = md["console_scripts"]
        script_paths = find_script_paths(prefix, scripts)
        for sp in script_paths:
            rel = sp.relative_to(prefix)
            collected.append((sp, rel))
    seen = set()
    final = []
    for src, rel in collected:
        key = str(rel)
        if key in seen:
            continue
        seen.add(key)
        final.append((src, rel))
    return (final, md)


def build_wheel_from_tree(tree_items, dist_name, version, workdir, wheel_out_path: Path):
    for src, rel in tree_items:
        dest = workdir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_file():
            shutil.move(src, dest)
        elif src.is_dir():
            continue
    distinfo_dirs = list(workdir.glob("*.dist-info"))
    if not distinfo_dirs:
        dinfo_name = f"{dist_name}-{version}.dist-info"
        distinfo_dir = workdir / dinfo_name
        distinfo_dir.mkdir(parents=True, exist_ok=True)
    else:
        distinfo_dir = distinfo_dirs[0]
    wheel_file = distinfo_dir / "WHEEL"
    if not wheel_file.exists():
        content = [
            "Wheel-Version: 1.0",
            "Generator: repack_wheels/1.0",
            "Root-Is-Purelib: true",
            "Tag: py3-none-any",
            "",
        ]
        wheel_file.write_text("\n".join(content), encoding="utf-8")
    record_lines = []
    all_files = []
    for root, _dirs, files in os.walk(workdir):
        for fn in files:
            full = Path(root) / fn
            rel = full.relative_to(workdir).as_posix()
            all_files.append((full, rel))
    for full, rel in sorted(all_files, key=operator.itemgetter(1)):
        if rel.endswith(("/RECORD", "RECORD")):
            continue
        h, size = compute_hash_and_size(full)
        record_lines.append(f"{rel},{h},{size}")
    record_lines.append(f"{distinfo_dir.name + '/RECORD'},,")
    recpath = distinfo_dir / "RECORD"
    recpath.write_text("\n".join(record_lines) + "\n", encoding="utf-8")
    wheel_out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(wheel_out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(workdir):
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
    if not site_dirs:
        print("Error: no site-packages directory found under prefix", prefix, file=sys.stderr)
        sys.exit(2)
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
                print(f"Warning: package {name} not found in site-packages, skipping", file=sys.stderr)
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
            print(f"Repacking {dist_name} {version} ...")
            items, md = collect_files_for_dist(distinfo, site_dirs, prefix)
            if not items:
                print(f"  no files found for {dist_name}, skipping", file=sys.stderr)
                continue
            repack_root / f"{dist_name}-{version}"
            if workdir.exists():
                shutil.rmtree(workdir)
            workdir.mkdir(parents=True, exist_ok=True)
            wheel_name = f"{dist_name.replace('-', '_')} -{version} -py3-none-any.whl"
            wheel_out = wheel_dir / wheel_name
            built = build_wheel_from_tree(items, dist_name, version, workdir, wheel_out)
            print(f"  wrote wheel: {built}")
        except Exception as e:
            print(f"Error repacking {distinfo}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
