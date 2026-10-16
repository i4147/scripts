import os
import sys


if sys.version_info < (3, 11):
    import tomli as tomllib
else:
    import tomllib


def parse_hatch_project():
    if not os.path.exists("pyproject.toml"):
        print("Error: No pyproject.toml found in this directory.")
        sys.exit(1)

    with open("pyproject.toml", "rb") as f:
        config = tomllib.load(f)

    backend = config.get("build-system", {}).get("build-backend", "")
    if "hatchling" not in backend:
        print(f"Warning: This project uses '{backend}', not hatchling. Proceeding anyway...")

    project = config.get("project", {})
    if not project:
        print("Error: No [project] table found in pyproject.toml.")
        sys.exit(1)

    name = project.get("name")
    if not name:
        print("Error: Project name is missing from pyproject.toml.")
        sys.exit(1)

    authors_list = project.get("authors", []) or project.get("maintainers", [])
    author_name = ", ".join([a["name"] for a in authors_list if "name" in a])
    author_email = ", ".join([a["email"] for a in authors_list if "email" in a])

    dynamic_fields = project.get("dynamic", [])

    readme = project.get("readme", "")
    readme_path = readme.get("file", "") if isinstance(readme, dict) else readme

    license_val = project.get("license", "")
    license_str = license_val.get("text", "") if isinstance(license_val, dict) else license_val

    install_requires = project.get("dependencies", [])
    extras_require = project.get("optional-dependencies", {})

    wheel_config = config.get("tool", {}).get("hatch", {}).get("build", {}).get("targets", {}).get("wheel", {})
    custom_packages = wheel_config.get("packages", [])

    if not custom_packages:
        custom_includes = config.get("tool", {}).get("hatch", {}).get("build", {}).get("include", [])
        py_modules = [pkg.replace(".py", "") for pkg in custom_includes if pkg.endswith(".py")]
    else:
        py_modules = []

    hatch_version_path = config.get("tool", {}).get("hatch", {}).get("version", {}).get("path", "")

    uses_vcs = any("hatch-vcs" in req for req in config.get("build-system", {}).get("requires", []))

    setup_code = f"""import os
import sys
from setuptools import setup, find_packages

# --- Dynamic Metadata Extraction For Hatch Conventions ---
version = "0.1.0"
description = {repr(project.get("description", ""))}

def extract_hatch_metadata():
    global version
    if "version" not in {repr(dynamic_fields)}:
        return

    # Check for hatch-vcs (Git tagging fallback)
    if {uses_vcs}:
        try:
            import subprocess
            git_version = subprocess.check_output(["git", "describe", "--tags", "--always"]).decode("utf-8").strip()
            if git_version:
                version = git_version
                return
        except Exception:
            pass

    # Target static path defined in tool.hatch.version.path
    explicit_path = {repr(hatch_version_path)}
    search_paths = [explicit_path] if explicit_path else [
        "{name.replace("-", "_")}/__about__.py",
        "{name.replace("-", "_")}/__init__.py",
        "src/{name.replace("-", "_")}/__about__.py",
        "src/{name.replace("-", "_")}/__init__.py",
    ]

    import ast
    for path in search_paths:
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("__version__"):
                        try:
                            version = ast.literal_eval(line.split("=")[1].strip())
                            return
                        except Exception:
                            pass

extract_hatch_metadata()

# --- Execution Setup ---
setup(
    name={repr(name)},
    version=version,
    author={repr(author_name)},
    author_email={repr(author_email)},
    description=description,
    long_description=open({repr(readme_path)}).read() if {repr(readme_path)} and os.path.exists({repr(readme_path)}) else "",
    long_description_content_type="text/markdown" if {repr(readme_path)}.endswith(".md") else "text/x-rst",
    license={repr(license_str)},
    python_requires={repr(project.get("requires-python", ""))},
    classifiers={repr(project.get("classifiers", []))},
    install_requires={repr(install_requires)},
    extras_require={repr(extras_require)},
    packages={repr(custom_packages)} if {bool(custom_packages)} else find_packages(where="src") if os.path.exists("src") else find_packages(),
    package_dir={{"": "src"}} if os.path.exists("src") and not {bool(custom_packages)} else {{}},
    py_modules={repr(py_modules)},
    zip_safe=False,
)
"""

    with open("setup.py", "w", encoding="utf-8") as out:
        out.write(setup_code)

    print(f"Successfully generated a fallback setup.py for Hatch-based project: '{name}'")


if __name__ == "__main__":
    parse_hatch_project()
