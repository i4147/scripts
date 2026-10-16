import os
import sys


if sys.version_info < (3, 11):
    import tomli as tomllib
else:
    import tomllib


def parse_maturin_project():
    if not os.path.exists("pyproject.toml"):
        print("Error: No pyproject.toml found in this directory.")
        sys.exit(1)

    with open("pyproject.toml", "rb") as f:
        config = tomllib.load(f)

    backend = config.get("build-system", {}).get("build-backend", "")
    if "maturin" not in backend:
        print(f"Warning: This project uses '{backend}', not maturin. Proceeding anyway...")

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

    maturin_tool = config.get("tool", {}).get("maturin", {})
    python_source = maturin_tool.get("python-source", "")

    setup_code = f"""import os
import sys
from setuptools import setup, find_packages

# --- Dynamic Metadata Extraction For Maturin / Cargo Conventions ---
version = {repr(project.get("version", "0.1.0"))}
description = {repr(project.get("description", ""))}

def extract_maturin_metadata():
    global version
    if "version" not in {repr(dynamic_fields)}:
        return

    # Maturin falls back onto Cargo.toml to resolve dynamic python versioning strings
    if os.path.exists("Cargo.toml"):
        try:
            if sys.version_info < (3, 11):
                import tomli as tl
            else:
                import tomllib as tl
                
            with open("Cargo.toml", "rb") as f:
                cargo = tl.load(f)
            cargo_version = cargo.get("package", {{}}).get("version", "")
            if cargo_version:
                version = cargo_version
                return
        except Exception:
            pass

extract_maturin_metadata()

# --- Structural Package Exploration ---
python_root = {repr(python_source)}
if python_root:
    packages = find_packages(where=python_root)
    package_dir = {{"": python_root}}
elif os.path.exists("src"):
    packages = find_packages(where="src")
    package_dir = {{"": "src"}}
else:
    packages = find_packages()
    package_dir = {{}}

# --- Execution Setup ---
# Note: Since this package relies on Rust compilation steps, running setup.py directly 
# will only install the pure Python layers. For actual native compilation, users should 
# install the 'setuptools-rust' extension module.
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
    packages=packages,
    package_dir=package_dir,
    zip_safe=False,
)
"""

    with open("setup.py", "w", encoding="utf-8") as out:
        out.write(setup_code)

    print(f"Successfully generated a legacy fallback setup.py for maturin project: '{name}'")


if __name__ == "__main__":
    parse_maturin_project()
