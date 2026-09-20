import shutil
import tarfile
from pathlib import Path
import apt
import apt_pkg
import os

BASE_DIR = Path.home() / "debs"
BASE_DIR.mkdir(parents=True, exist_ok=True)


apt_pkg.init_system()


def get_installed_packages() -> list[str]:
    cache = apt.Cache()
    return [pkg.name for pkg in cache if pkg.is_installed]


def get_package_files(pkg_name: str) -> list[str]:
    try:
        
        dpkg_info_dir = Path("/data/data/com.termux/files/usr/var/lib/dpkg/info")
        list_file = dpkg_info_dir / f"{pkg_name}.list"

        if not list_file.exists():
            return []

        files = list_file.read_text().splitlines()
        
        return [f for f in files if Path(f).exists()]
    except Exception:
        return []


def get_package_metadata(pkg_name: str) -> dict[str, str]:
    cache = apt.Cache()

    if pkg_name not in cache:
        raise ValueError(f"Package {pkg_name} not found")

    pkg = cache[pkg_name]

    
    if pkg.is_installed:
        version = pkg.installed.version
    else:
        version = pkg.candidate.version

    
    description = pkg.description or "No description available"
    
    maintainer = pkg.record.get("Maintainer", "Unknown Maintainer") if hasattr(pkg, "record") else "Unknown Maintainer"

    return {
        "Package": pkg_name,
        "Version": version,
        "Architecture": pkg.architecture or "all",
        "Maintainer": maintainer,
        "Description": description.replace("\n", " ").strip(),
    }


def create_control_file(path: Path, meta: dict[str, str]) -> None:
    control_content = (
        f"Package: {meta['Package']}\n"
        f"Version: {meta['Version']}\n"
        f"Architecture: {meta['Architecture']}\n"
        f"Maintainer: {meta['Maintainer']}\n"
        f"Description: {meta['Description']}\n"
    )
    (path / "control").write_text(control_content)


def copy_pkg_files(files: list[str], dest: Path) -> None:
    for f in files:
        
        path = Path(f)
        if not path.is_file():
            continue

        target = dest / f.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)

        try:
            
            shutil.copy2(f, target)
            
            stat_info = os.stat(f)
            os.chmod(target, stat_info.st_mode)
        except (PermissionError, OSError, shutil.Error):
            
            try:
                content = path.read_bytes()
                target.write_bytes(content)
                
                try:
                    os.chmod(target, path.stat().st_mode)
                except:
                    pass
            except:
                pass


def build_tar_xz(source_dir: Path, output_path: Path) -> None:
    with tarfile.open(output_path, "w:xz") as tar:
        tar.add(source_dir, arcname=".")


def build_deb(pkg_dir: Path, output_deb: Path) -> None:
    debian_binary_content = b"2.0\n"
    control_tar_path = pkg_dir / "control.tar.xz"
    data_tar_path = pkg_dir / "data.tar.xz"

    
    build_tar_xz(pkg_dir / "DEBIAN", control_tar_path)

    
    build_tar_xz(pkg_dir / "files", data_tar_path)

    
    control_data = control_tar_path.read_bytes()
    data_data = data_tar_path.read_bytes()

    
    
    create_ar_archive(
        output_deb,
        [("debian-binary", debian_binary_content), ("control.tar.xz", control_data), ("data.tar.xz", data_data)],
    )


def create_ar_archive(output_path: Path, files: list[tuple[str, bytes]]) -> None:
    with open(output_path, "wb") as f:
        
        f.write(b"!<arch>\n")

        for name, content in files:
            
            name_bytes = name.encode("ascii")
            if len(name_bytes) > 16:
                name_bytes = name_bytes[:16]
            name_padded = name_bytes.ljust(16, b" ")

            
            size = len(content)
            size_str = str(size).encode("ascii")
            size_padded = size_str.rjust(10, b" ")

            
            header = (
                name_padded  
                + b"1234567890"  
                + b"123456"  
                + b"123456"  
                + b"100644 "  
                + size_padded  
                + b"\x60\x0a"  
            )
            f.write(header)

            
            f.write(content)

            
            if size % 2 == 1:
                f.write(b"\n")


def process_pkg(pkg_name: str) -> str | None:
    try:
        pkg_dir = BASE_DIR / pkg_name
        if pkg_dir.exists():
            shutil.rmtree(pkg_dir)
        pkg_dir.mkdir()

        files_dir = pkg_dir / "files"
        debian_dir = pkg_dir / "DEBIAN"
        files_dir.mkdir()
        debian_dir.mkdir()

        
        meta = get_package_metadata(pkg_name)
        files = get_package_files(pkg_name)

        if not files:
            print(f"[!] No files found for {pkg_name}")
            return

        
        copy_pkg_files(files, files_dir)
        create_control_file(debian_dir, meta)

        
        output_deb = BASE_DIR / f"{pkg_name}.deb"
        build_deb(pkg_dir, output_deb)

        print(f"[✔] {pkg_name} → {output_deb}")

        
        shutil.rmtree(pkg_dir)
        return str(output_deb)

    except Exception as e:
        print(f"[✖] {pkg_name} FAILED: {e}")
        return


def main() -> None:
    import sys

    args = sys.argv[1:]
    pkgs = [p.strip() for p in args] if args else ["python", "mc", "python2"]

    print(f"[+] Building {len(pkgs)} packages\n")

    for pkg in pkgs:
        process_pkg(pkg)


if __name__ == "__main__":
    main()
