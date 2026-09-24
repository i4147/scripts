import argparse
from pathlib import Path


def load_user_info() -> dict[str, str]:
    info_path = Path.home() / ".myinfo"
    info = {}

    if not info_path.exists():
        return info

    for line in info_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, val = line.split("=", 1)
        info[key.strip()] = val.strip()

    return info


def write_file_if_missing(path: Path, content: str = "") -> None:
    if not path.exists():
        path.write_text(content)


def create_project_structure(pkg: str, author: str, email: str, url: str) -> None:
    cwd = Path.cwd()

    version = "1.4.7"

    readme_path = cwd / "README.md"
    write_file_if_missing(readme_path, f"# {pkg}\n")

    src_pkg = cwd / "src" / pkg
    src_pkg.mkdir(parents=True, exist_ok=True)
    write_file_if_missing(src_pkg / "__init__.py")

    tests_path = cwd / "tests"
    tests_path.mkdir(exist_ok=True)
    write_file_if_missing(tests_path / "__init__.py")

    setup_py = cwd / "setup.py"
    setup_py.write_text('__import__("setuptools").setup()\n')

    setup_cfg = cwd / "setup.cfg"
    cfg_content = [
        "[metadata]",
        f"name = {pkg}",
        f"version = {version}",
    ]

    if author:
        cfg_content.append(f"author = {author}")
    if email:
        cfg_content.append(f"author_email = {email}")
    if url:
        cfg_content.append(f"url = {url}")

    cfg_content.extend(
        [
            "",
            "[options]",
            "package_dir =",
            "    = src",
            "packages = find:",
            "python_requires = >=3.13",
            "",
            "[options.packages.find]",
            "where = src",
        ]
    )

    setup_cfg.write_text("\n".join(cfg_content))

    pyproject_path = cwd / "pyproject.toml"
    pyproject_path.write_text(
        '[build-system]\nrequires = ["setuptools>=69.0", "wheel"]\nbuild-backend = "setuptools.build_meta"\n'
    )

    print(f"Project '{pkg}' initialized in {cwd}")


def main() -> None:
    user_info = load_user_info()

    parser = argparse.ArgumentParser(description="Initialize a Python project structure")
    parser.add_argument("name", help="Package name")
    parser.add_argument("--version", default="1.4.7", help="Initial version (default: 1.4.7)")
    args = parser.parse_args()

    author = user_info.get("name", "")
    email = user_info.get("email", "")
    github_user = user_info.get("github_username", "")

    url = f"https://github.com/{github_user}/{args.name}" if github_user else ""

    create_project_structure(args.name, author, email, url)


if __name__ == "__main__":
    main()
