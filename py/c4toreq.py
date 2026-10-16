import re
from pathlib import Path

from packaging.version import Version


def extract_upgradable_packages(results_file_path: str) -> list[tuple[str, str]]:
    upgradable_packages = []
    package_pattern = re.compile(
        "^(?P<package_name>[a-zA-Z0-9\\-_.]+)\\s*:\\s*(?P<installed_version>[^|]+?)\\s*\\|\\s*(?P<latest_version>\\S+)$"
    )
    updatable_pattern_with_arrow = re.compile(
        "^(?P<package_name>[a-zA-Z0-9\\-_.]+)\\s*:\\s*(?P<installed_version>\\S+)\\s*->\\s*(?P<latest_version>\\S+)\\s*\\(Updatable!\\)$"
    )
    try:
        with Path(results_file_path).open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                match = updatable_pattern_with_arrow.match(line)
                if match:
                    package_name = match.group("package_name")
                    latest_version = match.group("latest_version")
                    upgradable_packages.append((package_name, latest_version))
                    continue
                match = package_pattern.match(line)
                if match:
                    package_name = match.group("package_name")
                    installed_version_str = match.group("installed_version")
                    latest_version_str = match.group("latest_version")
                    try:
                        installed_ver = Version(installed_version_str)
                        latest_ver = Version(latest_version_str)
                        if installed_ver < latest_ver:
                            upgradable_packages.append((package_name, latest_version_str))
                    except Exception as e:
                        print(
                            f"Warning: Could not parse versions for {package_name} (installed: '{installed_version_str}', latest: '{latest_version_str}'). Error: {e}"
                        )
                else:
                    print(f"Warning: Line format not recognized: {line}")
    except FileNotFoundError:
        print(f"Error: Results file '{results_file_path}' not found.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    return upgradable_packages


def save_to_requirements_file(packages: list[tuple[str, str]], output_file_path: str) -> None:
    try:
        with Path(output_file_path).open("w", encoding="utf-8") as f:
            for pkg_name, latest_version in packages:
                f.write(f"{pkg_name}=={latest_version}\n")
        print(f"\nSuccessfully saved upgradable packages to '{output_file_path}'.")
        print("You can upgrade these packages using:")
        print(f"pip install -r {output_file_path}")
    except Exception as e:
        print(f"Error saving to requirements file: {e}")


if __name__ == "__main__":
    results_file = "/sdcard/cfor.txt"
    output_requirements_file = "requ.txt"
    print(f"Reading results from '{results_file}'...")
    upgradable_pkgs = extract_upgradable_packages(results_file)
    if upgradable_pkgs:
        print("\n--- Upgradable Packages Found ---")
        for pkg_name, latest_version in upgradable_pkgs:
            print(f"{pkg_name} (latest: {latest_version})")
        save_to_requirements_file(upgradable_pkgs, output_requirements_file)
    else:
        print("\nNo upgradable packages found or issues reading the results file.")
