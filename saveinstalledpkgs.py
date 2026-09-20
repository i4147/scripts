import subprocess
import sys
from pathlib import Path
OUTPUT_FILE = Path("installed_packages_deb.txt")
def get_installed_debian_packages():
    try:
        result = subprocess.run(
            ["dpkg-query", "-W", "-f=${binary:Package}\n"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        sys.exit("dpkg-query not found. Are you on a Debian-based system?")
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.stderr.strip())
    return sorted(pkg for pkg in result.stdout.splitlines() if pkg)
def save_packages(packages, path):
    path.write_text("\n".join(packages) + "\n", encoding="utf-8")
def main():
    packages = get_installed_debian_packages()
    save_packages(packages, OUTPUT_FILE)
    print(f"Saved {len(packages)} packages to {OUTPUT_FILE.resolve()}")
if __name__ == "__main__":
    raise SystemExit(main())
