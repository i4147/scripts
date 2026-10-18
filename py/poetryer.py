import os
import sys

if sys.version_info < (3, 11):
    import tomli as tomllib
else:
    import tomllib


def clean_poetry_deps(deps_dict):
    reqs = []
    if not deps_dict:
        return reqs
    for pkg, constraint in deps_dict.items():
        if pkg.lower() == "python":
            continue
        if isinstance(constraint, dict):
            version_str = constraint.get("version", "")
            if constraint.get("optional", False):
                continue
        else:
            version_str = constraint
        if version_str.startswith("^"):
            ver = version_str[1:]
            parts = ver.split(".")
            if parts[0] == "0":
                next_minor = int(parts[1]) + 1 if len(parts) > 1 else 1
                version_str = f">={ver}, <0.{next_minor}.0"
            else:
                next_major = int(parts[0]) + 1
                version_str = f">={ver}, <{next_major}.0.0"
        elif version_str.startswith("~"):
            ver = version_str[1:]
            parts = ver.split(".")
            next_minor = int(parts[1]) + 1 if len(parts) > 1 else 1
            version_str = f">={ver}, <{parts[0]}.{next_minor}.0"
        reqs.append(f"{pkg} {version_str}".strip())
    return reqs


def parse_poetry_project():
    if not os.path.exists("pyproject.toml"):
        print("Error: No pyproject.toml found in this directory.")
        sys.exit(1)
    with open("pyproject.toml", "rb") as f:
        config = tomllib.load(f)
    backend = config.get("build-system", {}).get("build-backend", "")
    if "poetry.core" not in backend:
        print(f"Warning: This project uses '{backend}', not poetry-core. Proceeding anyway...")
    tool_poetry = config.get("tool", {}).get("poetry", {})
    project = config.get("project", {})
    name = project.get("name") or tool_poetry.get("name")
    if not name:
        print("Error: Project name missing from pyproject.toml.")
        sys.exit(1)
    version_static = project.get("version") or tool_poetry.get("version", "0.1.0")
    dynamic_fields = project.get("dynamic", [])
    description = project.get("description") or tool_poetry.get("description", "")
    authors_list = project.get("authors", []) or tool_poetry.get("authors", [])
    author_names, author_emails = [], []
    for author in authors_list:
        if isinstance(author, dict):
            if "name" in author:
                author_names.append(author["name"])
            if "email" in author:
                author_emails.append(author["email"])
        elif isinstance(author, str):
            if "<" in author and ">" in author:
                n, e = author.split("<")
                author_names.append(n.strip())
                author_emails.append(e.replace(">", "").strip())
            else:
                author_names.append(author.strip())
    readme = project.get("readme") or tool_poetry.get("readme", "")
    readme_path = readme.get("file", "") if isinstance(readme, dict) else readme
    license_val = project.get("license", "")
    license_str = license_val.get("text", "") if isinstance(license_val, dict) else license_val
    if not license_str and "license" in tool_poetry:
        license_str = tool_poetry["license"]
    python_requires = project.get("requires-python", "")
    install_requires = []
    extras_require = {}
    if project:
        install_requires = project.get("dependencies", [])
        extras_require = project.get("optional-dependencies", {})
        python_requires = project.get("requires-python", "")
    if not install_requires and "dependencies" in tool_poetry:
        poetry_deps = tool_poetry.get("dependencies", {})
        if "python" in poetry_deps:
            python_requires = poetry_deps["python"]
        install_requires = clean_poetry_deps(poetry_deps)
    if "extras" in tool_poetry and not extras_require:
        for group, items in tool_poetry["extras"].items():
            extras_require[group] = [f"{i}" for i in items]
    uses_dynamic = "tool" in config and "poetry-dynamic-versioning" in config["tool"]
    setup_code = f"""import os
import sys
from setuptools import setup, find_packages
# --- Dynamic Metadata Extraction For Poetry Conventions ---
version = {repr(version_static)}
description = {repr(description)}
def extract_poetry_metadata():
    global version
    # Check for git tags via poetry-dynamic-versioning hooks if labeled dynamic
    if {uses_dynamic} or "version" in {repr(dynamic_fields)}:
        try:
            import subprocess
            git_version = subprocess.check_output(["git", "describe", "--tags", "--always"]).decode("utf-8").strip()
            if git_version:
                version = git_version
                return
        except Exception:
            pass
extract_poetry_metadata()
# --- Execution Setup ---
setup(
    name={repr(name)},
    version=version,
    author={repr(", ".join(author_names))},
    author_email={repr(", ".join(author_emails))},
    description=description,
    long_description=open({repr(readme_path)}).read() if {repr(readme_path)} and os.path.exists({repr(readme_path)}) else "",
    long_description_content_type="text/markdown" if str({repr(readme_path)}).endswith(".md") else "text/x-rst",
    license={repr(license_str)},
    python_requires={repr(python_requires)},
    classifiers={repr(project.get("classifiers", []) or tool_poetry.get("classifiers", []))},
    install_requires={repr(install_requires)},
    extras_require={repr(extras_require)},
    packages=find_packages(where="src") if os.path.exists("src") else find_packages(),
    package_dir={{"": "src"}} if os.path.exists("src") else {{}},
    zip_safe=False,
)
"""
    with open("setup.py", "w", encoding="utf-8") as out:
        out.write(setup_code)
    print(f"Successfully generated a legacy fallback setup.py for Poetry project: '{name}'")


if __name__ == "__main__":
    parse_poetry_project()
