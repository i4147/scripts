import argparse
import contextlib
import shutil
import subprocess
import tarfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE_DIR = Path.home() / "tmp" / "debs"
BASE_DIR.mkdir(parents=True, exist_ok=True)


def run(cmd: str) -> str:
    return subprocess.check_output(cmd, shell=True, text=True)


def get_installed_packages() -> list[str]:
    return run("dpkg-query -W -f='${Package}\n'").split()


def get_package_files(pkg) -> list[str]:
    files = run(f"dpkg -L {pkg}").splitlines()
    return [f for f in files if Path(f).exists()]


def get_package_metadata(pkg) -> dict[str, str]:
    fmt = "${Package}\n${Version}\n${Architecture}\n${Maintainer}\n${Description}\n"
    out = run(f"dpkg-query -W -f='{fmt}' {pkg}").splitlines()
    return {
        "Package": out[0],
        "Version": out[1],
        "Architecture": out[2],
        "Maintainer": out[3],
        "Description": out[4],
    }


def create_control_file(path, meta: dict[str, str]) -> None:
    control_content = (
        f"Package: {meta['Package']}\n"
        f"Version: {meta['Version']}\n"
        f"Architecture: {meta['Architecture']}\n"
        f"Maintainer: {meta['Maintainer']}\n"
        f"Description: {meta['Description']}\n"
    )
    (path / "control").write_text(control_content)


def copy_pkg_files(files: list[str], dest) -> None:
    for f in files:
        target = dest / f.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(Exception):
            shutil.copy2(f, target)


def build_tar_xz(source_dir, output_path) -> None:
    with tarfile.open(output_path, "w:xz") as tar:
        tar.add(source_dir, arcname=".")


def build_deb(pkg_dir, output_deb: Path) -> None:
    debian_binary = pkg_dir / "debian-binary"
    debian_binary.write_text("2.0\n")
    control_tar = pkg_dir / "control.tar.xz"
    data_tar = pkg_dir / "data.tar.xz"
    build_tar_xz(pkg_dir / "DEBIAN", control_tar)
    build_tar_xz(pkg_dir / "files", data_tar)
    subprocess.run(
        f"ar r {output_deb} {debian_binary} {control_tar} {data_tar}",
        shell=True,
        check=True,
    )


def process_package(pkg) -> str | None:
    try:
        pkg_dir = BASE_DIR / pkg
        if pkg_dir.exists():
            shutil.rmtree(pkg_dir)
        pkg_dir.mkdir()
        files_dir = pkg_dir / "files"
        debian_dir = pkg_dir / "DEBIAN"
        files_dir.mkdir()
        debian_dir.mkdir()
        meta = get_package_metadata(pkg)
        files = get_package_files(pkg)
        copy_pkg_files(files, files_dir)
        create_control_file(debian_dir, meta)
        output_deb = BASE_DIR / f"{pkg}.deb"
        build_deb(pkg_dir, output_deb)
        return f"[✔] {pkg} → {output_deb}"
    except Exception as e:
        return f"[✖] {pkg} FAILED: {e}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workers",
        type=int,
        default=multiprocessing.cpu_count(),
        help="Number of parallel workers",
    )
    args = parser.parse_args()
    pkgs = get_installed_packages()
    print(f"[+] Building {len(pkgs)} packages using {args.workers} workers…\n")
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_package, pkg): pkg for pkg in pkgs}
        for future in as_completed(futures):
            print(future.result())


if __name__ == "__main__":
    main()
