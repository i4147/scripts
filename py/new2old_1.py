import os
import sys

if sys.version_info < (3, 11):
    import tomli as tomllib
else:
    import tomllib


def parse_setuptools_project():
    if not os.path.exists("pyproject.toml"):
        print("Error: No pyproject.toml found in this directory.")
        sys.exit(1)
    with open("pyproject.toml", "rb") as f:
        config = tomllib.load(f)
    backend = config.get("build-system", {}).get("build-backend", "")
    if "setuptools" not in backend:
        print(f"Warning: This project uses '{backend}', not setuptools. Proceeding anyway...")
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
    setuptools_tool = config.get("tool", {}).get("setuptools", {})
    setuptools_dynamic = setuptools_tool.get("dynamic", {})
    version_attr = ""
    if "version" in dynamic_fields and isinstance(setuptools_dynamic.get("version"), dict):
        version_attr = setuptools_dynamic["version"].get("attr", "")
    packages_find_cfg = setuptools_tool.get("packages", {}).get("find", {})
    find_where = packages_find_cfg.get("where", ["." if not os.path.exists("src") else "src"])[0]
    find_include = packages_find_cfg.get("include", ["*"])
    find_exclude = packages_find_cfg.get("exclude", [])
    setup_code = f"""import os
import sys
from setuptools import setup, find_packages
# --- Dynamic Metadata Extraction For Setuptools/PEP621 Conventions ---
version = {repr(project.get("version", "0.1.0"))}
description = {repr(project.get("description", ""))}
def extract_setuptools_metadata():
    global version
    if "version" not in {repr(dynamic_fields)}:
        return
    # Handle Setuptools module attribute directives (e.g., mymodule.__version__)
    attr_path = {repr(version_attr)}
    if attr_path:
        try:
            # Add current directory to path to safely parse local modules
            sys.path.insert(0, os.getcwd())
            module_name, obj_name = attr_path.rsplit(".", 1)
            
            # If the source root is inside src/, make sure it can be discovered
            if os.path.exists("src"):
                sys.path.insert(0, os.path.join(os.getcwd(), "src"))
            import importlib
            mod = importlib.import_module(module_name)
            version = getattr(mod, obj_name)
            return
        except Exception:
            pass
    # Fallback to standard version scanning if imports fail
    search_paths = [
        "{name.replace("-", "_")}/__init__.py",
        "src/{name.replace("-", "_")}/__init__.py",
    ]
    import ast
    for path in search_paths:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("__version__"):
                        try:
                            version = ast.literal_eval(line.split("=").strip())
                            return
                        except Exception:
                            pass
extract_setuptools_metadata()
# --- Execution Setup ---
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
    packages=find_packages(where={repr(find_where)}, include={repr(find_include)}, exclude={repr(find_exclude)}),
    package_dir={{"": {repr(find_where)}}} if {repr(find_where)} != "." else {{}},
    zip_safe=False,
)
"""
    with open("setup.py", "w", encoding="utf-8") as out:
        out.write(setup_code)
    print(f"Successfully generated a legacy fallback setup.py for Setuptools project: '{name}'")


if __name__ == "__main__":
    parse_setuptools_project()
