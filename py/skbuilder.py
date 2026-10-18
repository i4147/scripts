import os
import sys

if sys.version_info < (3, 11):
    import tomli as tomllib
else:
    import tomllib


def parse_skbuild_project():
    if not os.path.exists("pyproject.toml"):
        print("Error: No pyproject.toml found in this directory.")
        sys.exit(1)
    with open("pyproject.toml", "rb") as f:
        config = tomllib.load(f)
    backend = config.get("build-system", {}).get("build-backend", "")
    if "scikit_build_core" not in backend:
        print(f"Warning: This project uses '{backend}', not scikit_build_core. Proceeding anyway...")
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
    version_regex_file = ""
    version_regex_pattern = ""
    version_is_scm = False
    dynamic_meta_array = config.get("tool", {}).get("dynamic-metadata", [])
    if isinstance(dynamic_meta_array, list):
        for table in dynamic_meta_array:
            if table.get("field") == "version":
                provider = table.get("provider", "")
                if "regex" in provider:
                    version_regex_file = table.get("input", "")
                    version_regex_pattern = table.get("regex", "")
                elif "setuptools_scm" in provider:
                    version_is_scm = True
    if not version_regex_file and not version_is_scm:
        legacy_meta = config.get("tool", {}).get("scikit-build", {}).get("metadata", {}).get("version", {})
        provider = legacy_meta.get("provider", "")
        if "regex" in provider:
            version_regex_file = legacy_meta.get("input", "")
            version_regex_pattern = legacy_meta.get("regex", "")
        elif "setuptools_scm" in provider:
            version_is_scm = True
    setup_code = f"""import os
import re
import sys
from setuptools import setup, find_packages
# --- Dynamic Extraction For scikit-build-core / CMake Configurations ---
version = {repr(project.get("version", "0.1.0"))}
description = {repr(project.get("description", ""))}
def extract_skbuild_metadata():
    global version
    if "version" not in {repr(dynamic_fields)}:
        return
    # Case A: setuptools_scm version fallback
    if {version_is_scm}:
        try:
            import subprocess
            git_version = subprocess.check_output(["git", "describe", "--tags", "--always"]).decode("utf-8").strip()
            if git_version:
                version = git_version
                return
        except Exception:
            pass
    # Case B: Regex Plugin fallback
    regex_file = {repr(version_regex_file)}
    regex_pattern = {repr(version_regex_pattern)}
    
    if regex_file and os.path.exists(regex_file):
        pattern_str = regex_pattern if regex_pattern else r'__version__\s*=\s*["\']([^"\']+)["\']'
        try:
            with open(regex_file, "r", encoding="utf-8") as f:
                content = f.read()
                match = re.search(pattern_str, content)
                if match:
                    version = match.group(1)
                    return
        except Exception:
            pass
extract_skbuild_metadata()
# --- Execution Setup ---
# Note: Because this relies on CMake components, compiling via legacy setup.py
# requires making sure your environment has binary toolchains accessible.
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
    packages=find_packages(where="src") if os.path.exists("src") else find_packages(),
    package_dir={{"": "src"}} if os.path.exists("src") else {{}},
    zip_safe=False,
)
"""
    with open("setup.py", "w", encoding="utf-8") as out:
        out.write(setup_code)
    print(f"Successfully generated a fallback setup.py for scikit-build-core project: '{name}'")


if __name__ == "__main__":
    parse_skbuild_project()
