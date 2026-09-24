import sys
import subprocess
from pathlib import Path
import shutil
import tempfile
from importlib.metadata import distributions


pkg_with_script = [
    "google",
    "nudenet",
    "isort",
    "hypothesis",
    "webcolors",
    "coloredlogs",
    "colored",
    "face_recognition_models",
    "py7zr",
    "nbclassic",
    "nltk",
    "notebook",
    "courlan",
    "rapidfuzz",
    "pypdfium2",
    "debugpy",
    "crosshair",
    "crc32c",
    "compreffor",
    "pygments",
    "sumy",
    "markdown_it",
    "docutils",
    "rdflib",
    "tqdm",
    "tifffile",
    "networkx",
    "imageio",
    "gyp",
    "pysrt",
    "xar",
    "libretranslate",
    "runflare",
    "flask",
    "idna",
    "yapf",
    "pycmd",
    "super_image",
    "streamlit",
    "jupyterlab",
    "openai",
    "jupyter_events",
    "jupyter_console",
    "jupyter_core",
    "jupyter_client",
    "jupyter_server",
    "twisted",
    "virtualenv",
    "babel",
    "chardet",
    "huggingface_hub",
    "dulwich",
    "pylint",
    "binaryornot",
    "htmlmin",
    "argon2",
    "markdownify",
    "flake8_colors",
    "filetype",
    "unifont_utils",
    "pybind11",
    "rsa",
    "sympy",
    "mistletoe",
    "httpx",
    "html_to_markdown",
    "google_auth_oauthlib",
    "deep_translator",
    "cython_lint",
    "cairosvg",
    "cachecontrol",
    "gdown",
    "terminaltables",
    "pipdeptree",
    "pip_check",
    "jinja2",
    "waitress",
    "pytest",
    "pyflakes",
    "pydocstyle",
    "dutree",
    "pyupgrade",
    "tld",
    "dateparser",
    "htmldate",
    "trafilatura",
    "git",
    "pre_commit",
    "commitizen",
    "stevedore",
    "pysubs2",
    "pymediainfo",
    "trakit",
    "guessit",
    "dogpile",
    "knowit",
    "subliminal",
    "watchdog",
]


def get_user_site_packages():
    try:
        result = subprocess.run(
            [sys.executable, "-m", "site", "--user-site"], capture_output=True, text=True, check=True
        )
        return Path(result.stdout.strip())
    except subprocess.CalledProcessError:
        for path in sys.path:
            if "site-packages" in path and "user" in path:
                return Path(path)
        print("Could not determine user site-packages directory")
        sys.exit(1)


def get_installed_packages():
    packages = {}

    for dist in distributions():
        pkg_name = dist.metadata.get("Name", "").lower()
        if not pkg_name:
            continue

        try:
            location = dist._path.parent if hasattr(dist, "_path") else None
            if location:
                user_site = get_user_site_packages()
                if user_site not in location.parents and user_site != location:
                    continue
        except:
            pass

        packages[pkg_name] = {
            "name": dist.metadata.get("Name", pkg_name),
            "version": dist.version,
            "location": str(dist._path.parent) if hasattr(dist, "_path") else "unknown",
        }

    return packages


def get_installed_user_packages():
    packages = {}

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--user", "--format=json"], capture_output=True, text=True, check=True
        )

        import json

        data = json.loads(result.stdout)

        for pkg in data:
            packages[pkg["name"].lower()] = {"name": pkg["name"], "version": pkg["version"]}
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(f"Error getting package list via pip: {e}")

        packages = get_installed_packages()

    return packages


def repack_as_wheel(pkg_name, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            print(f"  Downloading {pkg_name}...")
            result = subprocess.run(
                [sys.executable, "-m", "pip", "download", "--no-deps", pkg_name, "--dest", temp_dir],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                print(f"  Error downloading {pkg_name}: {result.stderr}")
                return False

            temp_path = Path(temp_dir)
            downloaded_files = (
                list(temp_path.glob(f"{pkg_name}*.tar.gz"))
                + list(temp_path.glob(f"{pkg_name}*.zip"))
                + list(temp_path.glob(f"{pkg_name}*.whl"))
            )

            if not downloaded_files:
                for file in temp_path.iterdir():
                    if file.name.lower().startswith(pkg_name.lower()):
                        downloaded_files.append(file)

            if not downloaded_files:
                print(f"  No source distribution found for {pkg_name}")
                return False

            source_file = downloaded_files[0]

            if source_file.suffix == ".whl":
                shutil.copy2(source_file, output_dir / source_file.name)
                print(f"  Copied existing wheel: {source_file.name}")
                return True

            print(f"  Building wheel for {pkg_name}...")
            result = subprocess.run(
                [sys.executable, "-m", "pip", "wheel", "--no-deps", str(source_file), "--wheel-dir", str(output_dir)],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                print(f"  Error building wheel: {result.stderr}")
                return False

            print(f"  Successfully built wheel for {pkg_name}")
            return True

        except Exception as e:
            print(f"  Error processing {pkg_name}: {e}")
            return False


def normalize_package_name(name):
    return name.lower().replace("-", "_").replace("_", "-")


def main():

    output_dir = Path.home() / "tmp" / "wheels"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Output directory: {output_dir}")
    print(f"Python version: {sys.version}")
    print(f"Checking user site-packages...")

    installed = get_installed_user_packages()
    print(f"Found {len(installed)} installed packages in user site-packages")

    exclude_set = {normalize_package_name(pkg) for pkg in pkg_with_script}

    to_process = []
    for pkg_name, info in installed.items():
        normalized = normalize_package_name(pkg_name)

        if normalized in exclude_set:
            continue

        is_variant = False
        for listed in exclude_set:
            listed_normalized = normalize_package_name(listed)

            if listed_normalized in normalized or normalized in listed_normalized:
                is_variant = True
                break

        if not is_variant:
            to_process.append(info["name"])

    print(f"\nFound {len(to_process)} packages not in the list to repack:")
    if to_process:
        for pkg in to_process[:10]:
            print(f"  - {pkg}")
        if len(to_process) > 10:
            print(f"  ... and {len(to_process) - 10} more")

    success_count = 0
    failed_packages = []

    for pkg_name in to_process:
        print(f"\nProcessing {pkg_name}...")
        if repack_as_wheel(pkg_name, output_dir):
            success_count += 1
        else:
            failed_packages.append(pkg_name)

    print(f"\n{'=' * 60}")
    print(f"Summary:")
    print(f"  Total packages processed: {len(to_process)}")
    print(f"  Successfully repacked: {success_count}")
    print(f"  Failed: {len(failed_packages)}")

    if failed_packages:
        print(f"\nFailed packages:")
        for pkg in failed_packages:
            print(f"  - {pkg}")

    print(f"\nWheels saved to: {output_dir}")

    wheels = list(output_dir.glob("*.whl"))
    if wheels:
        print(f"\nCreated {len(wheels)} wheel files:")
        for wheel in sorted(wheels):
            size = wheel.stat().st_size / (1024 * 1024)
            print(f"  - {wheel.name} ({size:.2f} MB)")


if __name__ == "__main__":
    main()
