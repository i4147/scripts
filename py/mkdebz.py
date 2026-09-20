import argparse
import subprocess
import tempfile
from pathlib import Path


def run_cmd(cmd: list[str]) -> None:
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())


def extract_deb(src: Path, dest: Path) -> None:
    run_cmd(["dpkg-deb", "-R", str(src), str(dest)])


def rebuild_deb(src_dir: Path, out_file: Path) -> None:
    run_cmd(["dpkg-deb", "-b", str(src_dir), str(out_file)])


def read_pkg_list(path: Path) -> list[Path]:
    if not path.exists():
        msg = f"List file not found: {path}"
        raise FileNotFoundError(msg)
    lines = path.read_text(encoding="utf-8").splitlines()
    return [Path(line.strip()) for line in lines if line.strip()]


def repack_package(pkg_path: Path, output_dir: Path) -> Path:
    if not pkg_path.exists():
        msg = f"Package not found: {pkg_path}"
        raise FileNotFoundError(msg)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file = output_dir / pkg_path.name
    with tempfile.TemporaryDirectory() as tempdir:
        tempdir = Path(tempdir)
        extract_dir = tempdir / "extracted"
        extract_dir.mkdir()
        extract_deb(pkg_path, extract_dir)
        rebuild_deb(extract_dir, out_file)
    return out_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Repack Debian packages.")
    parser.add_argument("-p", "--package", help="Single .deb package path")
    parser.add_argument("-f", "--file", help="File containing list of packages")
    parser.add_argument("-o", "--output", default="repacked", help="Output directory")
    args = parser.parse_args()
    output_dir = Path(args.output)
    pkgs: list[Path] = []
    if args.package:
        pkgs.append(Path(args.package))
    if args.file:
        pkgs.extend(read_pkg_list(Path(args.file)))
    if not pkgs:
        msg = "Error: must provide --package or --file"
        raise SystemExit(msg)
    successes = []
    failures = []
    for pkg in pkgs:
        try:
            result = repack_package(pkg, output_dir)
            successes.append(result)
        except Exception as exc:
            failures.append((pkg, str(exc)))
    for _s in successes:
        pass
    for pkg, _err in failures:
        pass


if __name__ == "__main__":
    main()
