import sys
import tomllib
from pathlib import Path
from typing import Optional


def load_toml(path: Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def safe_read_file(path: Path) -> Optional[str]:
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return None


def extract_metadata(toml_data: dict) -> dict:
    project = toml_data.get("project", {})
    build_system = toml_data.get("build-system", {})
    metadata = {
        "name": project.get("name", ""),
        "version": project.get("version", "0.0.0"),
        "description": project.get("description", ""),
        "readme": project.get("readme", {}),
        "requires_python": project.get("requires-python", ""),
        "license": project.get("license", {}),
        "authors": project.get("authors", []),
        "maintainers": project.get("maintainers", []),
        "keywords": project.get("keywords", []),
        "classifiers": project.get("classifiers", []),
        "urls": project.get("urls", {}),
        "scripts": project.get("scripts", {}),
        "entry_points": project.get("entry-points", {}),
        "dependencies": project.get("dependencies", []),
        "optional_dependencies": project.get("optional-dependencies", {}),
        "include_package_data": project.get("include-package-data", False),
    }
    if isinstance(metadata["license"], dict):
        metadata["license"] = metadata["license"].get("text", "")
    return metadata


def generate_setup_py(metadata: dict, existing_setup_cfg: Optional[str], existing_manifest: Optional[str]) -> str:
    requires = metadata["dependencies"] or []
    optional_deps = metadata["optional_dependencies"] or {}
    install_requires_str = ",\n        ".join((f'"{dep}"' for dep in requires)) if requires else ""
    if install_requires_str:
        install_requires_str = f"[\n        {install_requires_str}\n    ]"
    else:
        install_requires_str = "[]"
    extras_require_parts = []
    for extra, deps in optional_deps.items():
        deps_str = ", ".join((f'"{d}"' for d in deps))
        extras_require_parts.append(f'    "{extra}": [{deps_str}],')
    extras_require_str = ",\n".join(extras_require_parts)
    entry_points_parts = []
    for group, points in (metadata["entry_points"] or {}).items():
        points_str = "\n".join((f'    "{k} = {v}"' for k, v in points.items()))
        entry_points_parts.append(f'    "{group}": [\n{points_str}\n    ],')
    entry_points_str = "\n".join(entry_points_parts)
    package_data_section = ""
    data_files_section = ""
    if existing_setup_cfg:
        import configparser

        cp = configparser.ConfigParser()
        try:
            cp.read_string(existing_setup_cfg)
            if "options.package_data" in cp:
                pkg_data = []
                for k, v in cp.items("options.package_data"):
                    pkg_data.append(f'''    "{k}": {v.split(", ")}''')
                package_data_section = "    package_data={\n" + ",\n".join(pkg_data) + "\n    },\n"
            if "options.data_files" in cp:
                data_files = []
                for k, v in cp.items("options.data_files"):
                    files = [f.strip() for f in v.split(",")]
                    data_files.append(f'        ("{k}", {files})')
                data_files_section = "    data_files=[\n" + ",\n".join(data_files) + "\n    ],\n"
        except Exception:
            pass
    authors_str = ""
    if metadata["authors"]:
        author_list = []
        for author in metadata["authors"]:
            name = author.get("name", "")
            email = author.get("email", "")
            if email:
                author_list.append(f"'{name} <{email}>'")
            else:
                author_list.append(f"'{name}'")
        authors_str = ", ".join(author_list)
    maintainers_str = ""
    if metadata["maintainers"]:
        maintainer_list = []
        for maintainer in metadata["maintainers"]:
            name = maintainer.get("name", "")
            email = maintainer.get("email", "")
            if email:
                maintainer_list.append(f"'{name} <{email}>'")
            else:
                maintainer_list.append(f"'{name}'")
        maintainers_str = ", ".join(maintainer_list)
    readme = metadata["readme"]
    long_description = ""
    long_description_content_type = ""
    if isinstance(readme, dict):
        long_description = safe_read_file(Path(readme.get("file", "")))
        long_description_content_type = readme.get("content-type", "text/markdown")
    elif isinstance(readme, str):
        long_description = safe_read_file(Path(readme))
        if readme.endswith(".md"):
            long_description_content_type = "text/markdown"
        elif readme.endswith(".rst"):
            long_description_content_type = "text/x-rst"
        else:
            long_description_content_type = "text/plain"
    classifiers_str = ",\n        ".join((f'"{c}"' for c in metadata["classifiers"])) if metadata["classifiers"] else ""
    if classifiers_str:
        classifiers_str = f"[\n        {classifiers_str}\n    ]"
    else:
        _str = "[]"
    keywords_str = ", ".join((f'"{k}"' for k in metadata["keywords"])) if metadata["keywords"] else "[]"
    url_items = []
    for k, v in (metadata["urls"] or {}).items():
        url_items.append(f'    "{k}": "{v}"')
    urls_str = "{\n" + ",\n".join(url_items) + "\n    }" if url_items else "{}"
    scripts_list = []
    for k, v in (metadata["scripts"] or {}).items():
        scripts_list.append(f'    "{k} = {v}"')
    scripts_str = "[\n" + ",\n".join(scripts_list) + "\n    ]" if scripts_list else "[]"
    entry_points_dict = "{}"
    if entry_points_str:
        entry_points_dict = "{\n" + entry_points_str + "\n    }"
    setup_py = '#!/usr/bin/env python3\nimport os\nfrom setuptools import setup, find_packages\nlong_description = """{long_description}"""\nlong_description_content_type = "{long_description_content_type}"\nif os.path.exists("MANIFEST.in"):\n    with open("MANIFEST.in", "r") as f:\n        manifest_content = f.read()\nelse:\n    manifest_content = ""\nsetup(\n    name="{name}",\n    version="{version}",\n    description="{description}",\n    long_description=long_description,\n    long_description_content_type=long_description_content_type,\n    author="{authors}",\n    author_email="{author_email}",\n    maintainer="{maintainers}",\n    maintainer_email="{maintainer_email}",\n    license="{license}",\n    url="{url}",\n    keywords={keywords},\n    packages=find_packages(),\n    include_package_data={include_package_data},\n    python_requires="{requires_python}",\n    install_requires={install_requires},\n    extras_require={{{extras_require}}},\n    entry_points={entry_points},\n    scripts={scripts},\n    classifiers={classifiers},\n    {package_data_section}{data_files_section}\n)\n'.format(
        name=metadata["name"],
        version=metadata["version"],
        description=metadata["description"],
        long_description=long_description.replace("\n", "\n    ") if long_description else "",
        long_description_content_type=long_description_content_type,
        authors=authors_str or "",
        author_email="",
        maintainers=maintainers_str or "",
        maintainer_email="",
        license=metadata["license"] or "",
        url=list((metadata["urls"] or {}).values())[0] if metadata["urls"] else "",
        keywords=keywords_str,
        include_package_data=str(metadata["include_package_data"]).lower(),
        requires_python=metadata["requires_python"] or "",
        install_requires=install_requires_str,
        extras_require="{" + extras_require_str + "}" if extras_require_str else "{}",
        entry_points=entry_points_dict,
        scripts=scripts_str,
        classifiers=classifiers_str,
        package_data_section=package_data_section,
        data_files_section=data_files_section,
    )
    return setup_py


def main() -> None:
    if len(sys.argv) > 1:
        toml_path = Path(sys.argv[1]).resolve()
    else:
        toml_path = Path("pyproject.toml").resolve()
    if not toml_path.exists():
        print(f"Error: {toml_path} not found.")
        sys.exit(1)
    print(f"Loading {toml_path}...")
    toml_data = load_toml(toml_path)
    metadata = extract_metadata(toml_data)
    setup_cfg_path = Path("setup.cfg")
    manifest_path = Path("MANIFEST.in")
    existing_setup_cfg = safe_read_file(setup_cfg_path)
    existing_manifest = safe_read_file(manifest_path)
    setup_py_content = generate_setup_py(metadata, existing_setup_cfg, existing_manifest)
    setup_py_path = Path("setup.py")
    with open(setup_py_path, "w", encoding="utf-8") as f:
        f.write(setup_py_content)
    print(f"Generated {setup_py_path}")
    print("\n--- Conversion Summary ---")
    print(f"Project name: {metadata['name']}")
    print(f"Version: {metadata['version']}")
    print(f"Dependencies: {len(metadata['dependencies'])}")
    print(f"Optional dependencies: {len(metadata['optional_dependencies'])}")
    if existing_setup_cfg:
        print("Preserved: setup.cfg")
    if existing_manifest:
        print("Preserved: MANIFEST.in")
    print(f"Output: {setup_py_path}")


if __name__ == "__main__":
    main()
