import hashlib
import io
import itertools
import operator
import re
import shutil
from base64 import b85encode
from collections.abc import Iterable
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import TextIO
from zipfile import ZipFile, ZipInfo
import requests
from cachecontrol import CacheControl
from cachecontrol.caches.file_cache import FileCache
from packaging.specifiers import SpecifierSet
from packaging.version import Version
from pkg_metadata import bytes_to_json
from rich.console import Console

SCRIPT_CONSTRAINTS = {
    "default": {"pip": "", "setuptools": "", "wheel": ""},
    "2.6": {"pip": "<10", "setuptools": "<37", "wheel": "<0.30"},
    "2.7": {"pip": "<21.0", "setuptools": "<45", "wheel": ""},
    "3.2": {"pip": "<8", "setuptools": "<30", "wheel": "<0.30"},
    "3.3": {"pip": "<18", "setuptools": "", "wheel": "<0.30"},
    "3.4": {"pip": "<19.2", "setuptools": "", "wheel": ""},
    "3.5": {"pip": "<21.0", "setuptools": "", "wheel": ""},
    "3.6": {"pip": "<22.0", "setuptools": "", "wheel": ""},
    "3.7": {"pip": "<24.1", "setuptools": "", "wheel": ""},
    "3.8": {"pip": "<25.1", "setuptools": "", "wheel": ""},
}
OLDEST_ZIPAPP = Version("22.3")
MOVED_SCRIPTS: dict[str, str] = {}


def get_all_pip_versions() -> dict[Version, tuple[str, str]]:
    data = requests.get("https://pypi.python.org/pypi/pip/json").json()
    versions = sorted((Version(s) for s in data["releases"]))
    retval = {}
    for version in versions:
        wheels = [
            (file["url"], file["digests"]["sha256"])
            for file in data["releases"][str(version)]
            if file["url"].endswith(".whl")
        ]
        if not wheels:
            continue
        assert len(wheels) == 1, (version, wheels)
        retval[version] = wheels[0]
    return retval


def determine_latest(versions: Iterable[Version], *, constraint: str) -> Version:
    assert sorted(versions) == list(versions)
    return list(SpecifierSet(constraint).filter(versions))[-1]


@lru_cache
def get_ordered_templates() -> list[tuple[Version, Path]]:
    all_templates = list(Path("./templates").iterdir())
    fallback = None
    ordered_templates = []
    for template in all_templates:
        if template.name in {"moved.py", "zipapp_main.py"}:
            continue
        if template.name == "default.py":
            fallback = template
            continue
        assert template.name.startswith("pre-")
        version_str = template.name[4:-3]
        version = Version(version_str)
        ordered_templates.append((version, template))
    assert fallback is not None
    assert fallback.name == "default.py"
    ordered_templates.append((Version("1!0"), fallback))
    return sorted(ordered_templates, key=operator.itemgetter(0))


def determine_template(version: Version) -> Path:
    ordered_templates = get_ordered_templates()
    for template_version, template in ordered_templates:
        if version < template_version:
            return template
    assert template.name == "default.py"
    return template


def download_wheel(url: str, expected_sha256: str) -> bytes:
    session = requests.session()
    cached_session = CacheControl(session, cache=FileCache(".web_cache"))
    response = cached_session.get(url)
    response_content = response.content
    hashobj = hashlib.sha256()
    hashobj.update(response_content)
    assert hashobj.hexdigest() == expected_sha256
    return response_content


def populated_script_constraints(original_constraints: dict[str, dict[str, str]]):
    sorted_python_versions = sorted(set(original_constraints) - {"default"})
    for variant in itertools.chain(["default"], sorted_python_versions):
        if variant == "default":
            major, minor = map(int, sorted_python_versions[-1].split("."))
            minor += 1
        else:
            major, minor = map(int, variant.split("."))
        mapping = original_constraints[variant].copy()
        mapping["minimum_supported_version"] = f"({major}, {minor})"
        yield (variant, mapping)


def repack_wheel(data: bytes) -> bytes:
    new_data = BytesIO()
    with ZipFile(BytesIO(data)) as existing_zip, ZipFile(new_data, mode="w") as new_zip:
        for zipinfo in existing_zip.infolist():
            if re.search("pip-.+\\.dist-info/", zipinfo.filename):
                continue
            new_zip.writestr(zipinfo, existing_zip.read(zipinfo))
    return new_data.getvalue()


def encode_wheel_contents(data: bytes) -> str:
    zipdata = b85encode(data).decode("utf8")
    chunked = [zipdata[i : i + 79] for i in range(0, len(zipdata), 79)]
    return "\n".join(chunked)


def determine_destination(base: str, variant: str) -> Path:
    public = Path(base)
    if not public.exists():
        public.mkdir()
    if variant == "default":
        return public / "get-pip.py"
    retval = public / variant / "get-pip.py"
    if not retval.parent.exists():
        retval.parent.mkdir()
    return retval


def detect_newline(f: TextIO) -> str:
    newline = f.newlines
    if not newline:
        return "\n"
    if isinstance(newline, str):
        return newline
    return "\n"


def generate_one(variant: str, mapping, *, console, pip_versions) -> None:
    pip_version = determine_latest(pip_versions.keys(), constraint=mapping["pip"])
    wheel_url, wheel_hash = pip_versions[pip_version]
    console.log(f"  Downloading [green]{Path(wheel_url).name}")
    original_wheel = download_wheel(wheel_url, wheel_hash)
    repacked_wheel = repack_wheel(original_wheel)
    encoded_wheel = encode_wheel_contents(repacked_wheel)
    template = determine_template(pip_version)
    console.log(f"  Rendering [yellow]{template}")
    with template.open() as f:
        newline = detect_newline(f)
        rendered_template = f.read().format(
            zipfile=encoded_wheel,
            installed_version=pip_version,
            pip_version=mapping["pip"],
            setuptools_version=mapping["setuptools"],
            wheel_version=mapping["wheel"],
            minimum_supported_version=mapping["minimum_supported_version"],
        )
    destination = determine_destination("public", variant)
    console.log(f"  Writing [blue]{destination}")
    with destination.open("w", newline=newline) as f:
        f.write(rendered_template)


def generate_moved(destination: str, *, location: str, console: Console) -> None:
    template = Path("templates") / "moved.py"
    assert template.exists()
    with template.open() as f:
        newline = detect_newline(f)
        rendered_template = f.read().format(location=location)
    console.log(f"  Writing [blue]{destination}[reset]")
    console.log(f"    Points users to [cyan]{location}[reset]")
    Path(destination).write_text(rendered_template, encoding="utf-8", newline=newline)


def zipapp_location(pip_version: Version) -> Path:
    zipapp_dir = Path("public/zipapp")
    zipapp_dir.mkdir(exist_ok=True)
    return zipapp_dir / f"pip-{pip_version}.pyz"


def generate_zipapp(pip_version: Version, *, console: Console, pip_versions: dict[Version, tuple[str, str]]) -> None:
    wheel_url, wheel_hash = pip_versions[pip_version]
    console.log(f"  Downloading [green]{Path(wheel_url).name}")
    original_wheel = download_wheel(wheel_url, wheel_hash)
    zipapp_name = zipapp_location(pip_version)
    console.log(f"  Creating [green]{zipapp_name}")
    with Path(zipapp_name).open("wb") as f:
        f.write(b"#!/usr/bin/env python\n")
        with ZipFile(f, mode="w") as dest:
            console.log("  Copying pip from original wheel to zipapp")
            major = 0
            minor = 0
            with ZipFile(io.BytesIO(original_wheel)) as src:
                for info in src.infolist():
                    if info.filename.startswith("pip/"):
                        data = src.read(info)
                        dest.writestr(info, data)
                    elif info.filename.endswith(".dist-info/METADATA"):
                        data = bytes_to_json(src.read(info))
                        if "requires_python" in data:
                            py_req = data["requires_python"]
                            py_req = py_req.replace(" ", "")
                            m = re.match("^>=(\\d+)\\.(\\d+)$", py_req)
                            if m:
                                major, minor = map(int, m.groups())
                                console.log(f"  Zipapp requires Python {py_req}")
                            else:
                                console.log(f"  Python requirement {py_req} too complex - check skipped")
            main_info = ZipInfo()
            main_info.filename = "__main__.py"
            main_info.create_system = 0
            template = Path("templates") / "zipapp_main.py"
            zipapp_main = template.read_text(encoding="utf-8").format(major=major, minor=minor)
            dest.writestr(main_info, zipapp_main)


def generate_zipapp_for_current(pip_version: Version) -> None:
    zipapp_name = zipapp_location(pip_version)
    unversioned_name = "public/pip.pyz"
    shutil.copy(zipapp_name, unversioned_name)


def main() -> None:
    console = Console()
    with console.status("Fetching pip versions..."):
        pip_versions = get_all_pip_versions()
        console.log(f"Found {len(pip_versions)} available pip versions.")
        console.log(f"Latest version: {max(pip_versions)}")
    with console.status("Generating scripts...") as status:
        for variant, mapping in populated_script_constraints(SCRIPT_CONSTRAINTS):
            status.update(f"Working on [magenta]{variant}")
            console.log(f"[magenta]{variant}")
            generate_one(variant, mapping, console=console, pip_versions=pip_versions)
    if MOVED_SCRIPTS:
        console.log("[magenta]Generating 'moved' scripts...")
        with console.status("Generating 'moved' scripts...") as status:
            for legacy, current in MOVED_SCRIPTS.items():
                status.update(f"Working on [magenta]{legacy}")
                generate_moved(legacy, console=console, location=current)
    with console.status("Generating zipapps...") as status:
        for version in pip_versions:
            if version < OLDEST_ZIPAPP:
                continue
            generate_zipapp(version, console=console, pip_versions=pip_versions)
        generate_zipapp_for_current(max(pip_versions))


if __name__ == "__main__":
    main()
