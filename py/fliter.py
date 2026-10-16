import os
import sys


if sys.version_info < (3, 11):
    import tomli as tomllib
else:
    import tomllib


def parse_flit_project():
    if not os.path.exists("pyproject.toml"):
        print("Error: No pyproject.toml found in this directory.")
        sys.exit(1)

    with open("pyproject.toml", "rb") as f:
        config = tomllib.load(f)

    backend = config.get("build-system", {}).get("build-backend", "")
    if "flit_core" not in backend:
        print(f"Warning: This project uses '{backend}', not flit_core. Proceeding anyway...")

    project = config.get("project", {})
    if not project:
        print("Error: No [project] table found in pyproject.toml.")
        sys.exit(1)

    name = project.get("name")
    if not name:
        print("Error: Project name is missing from pyproject.toml.")
        sys.exit(1)

    import_name = config.get("tool", {}).get("flit", {}).get("module", {}).get("name", name)

    authors_list = project.get("authors", []) or project.get("maintainers", [])
    author_name = ", ".join([a["name"] for a in authors_list if "name" in a])
    author_email = ", ".join([a["email"] for a in authors_list if "email" in a])

    dynamic_fields = project.get("dynamic", [])

    readme = project.get("readme", "")
    if isinstance(readme, dict):
        readme_path = readme.get("file", "")
    else:
        readme_path = readme

    license_val = project.get("license", "")
    license_str = license_val.get("text", "") if isinstance(license_val, dict) else license_val

    install_requires = project.get("dependencies", [])
    extras_require = project.get("optional-dependencies", {})

    setup_code = f"""import os
import sys
from setuptools import setup, find_packages

# --- Dynamic Extraction For Flit Conventions ---
version = "0.1.0"
description = ""

def extract_flit_metadata():
    global version, description
    import ast
    # Flit projects map to either {import_name}.py or {import_name}/__init__.py
    target_file = None
    if os.path.exists("{import_name}.py"):
        target_file = "{import_name}.py"
    elif os.path.exists("{import_name}/__init__.py"):
        target_file = "{import_name}/__init__.py"
        
    if not target_file:
        return

    with open(target_file, "r", encoding="utf-8") as f:
        content = f.read()
        
    # Read the docstring for the short description if requested
    if "description" in {repr(dynamic_fields)}:
        try:
            parsed = ast.parse(content)
            doc = ast.get_docstring(parsed)
            if doc:
                description = doc.split("\\n")[0].strip()
        except Exception:
            pass

    # Read __version__ directly from the source code
    if "version" in {repr(dynamic_fields)}:
        try:
            for line in content.splitlines():
                if line.startswith("__version__"):
                    version = ast.literal_eval(line.split("=")[1].strip())
                    break
        except Exception:
            pass

extract_flit_metadata()

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
    packages=find_packages(),
    py_modules=[{repr(import_name)}],
    zip_safe=False,
)
"""

    with open("setup.py", "w", encoding="utf-8") as out:
        out.write(setup_code)

    print(f"Successfully generated a universal legacy setup.py for project: '{name}'")


if __name__ == "__main__":
    parse_flit_project()
