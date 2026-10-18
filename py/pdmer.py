import os
import sys

if sys.version_info < (3, 11):
    import tomli as tomllib
else:
    import tomllib


def parse_pdm_project():
    if not os.path.exists("pyproject.toml"):
        print("Error: No pyproject.toml found in this directory.")
        sys.exit(1)
    with open("pyproject.toml", "rb") as f:
        config = tomllib.load(f)
    backend = config.get("build-system", {}).get("build-backend", "")
    if "pdm.backend" not in backend:
        print(f"Warning: This project uses '{backend}', not pdm.backend. Proceeding anyway...")
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
    pdm_build = config.get("tool", {}).get("pdm", {}).get("build", {})
    package_dir_src = pdm_build.get("package-dir", "")
    custom_includes = pdm_build.get("includes", [])
    py_modules = [m.replace(".py", "") for m in custom_includes if m.endswith(".py")]
    pdm_version_cfg = config.get("tool", {}).get("pdm", {}).get("version", {})
    version_source = pdm_version_cfg.get("source", "file" if "version" in dynamic_fields else "static")
    version_path = pdm_version_cfg.get("path", "")
    setup_code = f"""import os
import sys
from setuptools import setup, find_packages
# --- Dynamic Metadata Extraction For PDM Conventions ---
version = {repr(project.get("version", "0.1.0"))}
description = {repr(project.get("description", ""))}
def extract_pdm_metadata():
    global version
    if "version" not in {repr(dynamic_fields)}:
        return
    # Case A: PDM version sourced from SCM / Git Tag
    if {repr(version_source)} == "scm":
        try:
            import subprocess
            git_version = subprocess.check_output(["git", "describe", "--tags", "--always"]).decode("utf-8").strip()
            if git_version:
                version = git_version
                return
        except Exception:
            pass
    # Case B: PDM version sourced from a designated file attribute
    explicit_path = {repr(version_path)}
    search_paths = [explicit_path] if explicit_path else [
        "{name.replace("-", "_")}/__init__.py",
        "src/{name.replace("-", "_")}/__init__.py",
    ]
    import ast
    for path in search_paths:
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("__version__") or line.strip().startswith("VERSION"):
                        try:
                            # Isolate the value side of the assignment safely
                            version = ast.literal_eval(line.split("=")[1].strip())
                            return
                        except Exception:
                            pass
extract_pdm_metadata()
# --- Structural Directory Evaluation ---
# If a package-dir was specified, target it. Fall back to standard routes otherwise.
pdm_pkg_dir = {repr(package_dir_src)}
if pdm_pkg_dir:
    packages = find_packages(where=pdm_pkg_dir)
    package_dir = {{"": pdm_pkg_dir}}
elif os.path.exists("src"):
    packages = find_packages(where="src")
    package_dir = {{"": "src"}}
else:
    packages = find_packages()
    package_dir = {{}}
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
    packages=packages,
    package_dir=package_dir,
    py_modules={repr(py_modules)},
    zip_safe=False,
)
"""
    with open("setup.py", "w", encoding="utf-8") as out:
        out.write(setup_code)
    print(f"Successfully generated a universal fallback setup.py for PDM-based project: '{name}'")


if __name__ == "__main__":
    parse_pdm_project()
