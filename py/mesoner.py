import os
import sys


if sys.version_info < (3, 11):
    import tomli as tomllib
else:
    import tomllib


def parse_meson_project():
    if not os.path.exists("pyproject.toml"):
        print("Error: No pyproject.toml found in this directory.")
        sys.exit(1)

    with open("pyproject.toml", "rb") as f:
        config = tomllib.load(f)

    backend = config.get("build-system", {}).get("build-backend", "")
    if "mesonpy" not in backend:
        print(f"Warning: This project uses '{backend}', not mesonpy. Proceeding anyway...")

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

    meson_tool_meta = config.get("tool", {}).get("meson-python", {}).get("metadata", {})
    version_provider = (
        meson_tool_meta.get("version", {}).get("provider", "")
        if isinstance(meson_tool_meta.get("version"), dict)
        else ""
    )

    setup_code = rf"""import os
import re
import sys
from setuptools import setup, find_packages

# --- Dynamic Metadata Extraction For Meson Conventions ---
version = {repr(project.get("version", "0.1.0"))}
description = {repr(project.get("description", ""))}

def extract_meson_metadata():
    global version
    if "version" not in {repr(dynamic_fields)}:
        return

    # Check the standard meson.build configuration file for project version
    if os.path.exists("meson.build"):
        try:
            with open("meson.build", "r", encoding="utf-8") as f:
                content = f.read()
            # Match patterns like: project('name', 'cpp', version: '1.2.3')
            match = re.search(r"project\s*\\([^)]*version\s*:\s*['\\\"]([^'\\\"]+)['\\\"])", content, re.IGNORECASE)
            if match:
                version = match.group(2)
                return
        except Exception:
            pass

    # If the project utilizes a third-party plugin helper like DiscoverVersion
    provider = {repr(version_provider)}
    if provider and "DiscoverVersion" in provider:
        try:
            import subprocess
            git_version = subprocess.check_output(["git", "describe", "--tags", "--always"]).decode("utf-8").strip()
            if git_version:
                version = git_version
                return
        except Exception:
            pass

extract_meson_metadata()

# --- Execution Setup ---
# Note: Since this project relies on a Meson binary setup, running setup.py directly 
# will only map out Python components unless specialized extension modules are declared.
setup(
    name={repr(name)},
    version=version,
    author={repr(author_name)},
    author_email={repr(author_email)},
    description=description,
    long_description=open({repr(readme_path)}).read() if {repr(readme_path)} and os.path.exists({repr(readme_path)}) else "",
    long_description_content_type="text/markdown" if str({repr(readme_path)}).endswith(".md") else "text/x-rst",
    license={repr(license_str)},
    python_requires={repr(project.get("requires-python", ""))},
    classifiers={repr(project.get("classifiers", []))},
    install_requires={repr(install_requires)},
    extras_require={repr(extras_require)},
    packages=find_packages(where="src") if os.path.exists("src") else find_packages(),
    package_dir={{"": "src"}} if os.path.exists("src") else {{}},
    zip_safe=False,
)
"""

    with open("setup.py", "w", encoding="utf-8") as out:
        out.write(setup_code)

    print(f"Successfully generated a legacy fallback setup.py for meson-python project: '{name}'")


if __name__ == "__main__":
    parse_meson_project()
