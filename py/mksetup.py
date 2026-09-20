import shutil
import sys
import tempfile
import zipfile
from email.parser import Parser
from pathlib import Path


EXT_SUFFIXES = (".so", ".pyd", ".dll")


def extract_wheel(whl: Path, dst: Path) -> None:
    with zipfile.ZipFile(whl) as zf:
        zf.extractall(dst)


def find_extensions(root: Path) -> list[str]:
    return [".".join(f.relative_to(root).with_suffix("").parts) for f in root.rglob("*") if f.suffix in EXT_SUFFIXES]


def generate_pyproject_toml() -> str:
    return '[build-system]\nrequires = ["setuptools>=61", "wheel"]\nbuild-backend = "setuptools.build_meta"\n'


def generate_setup_py(meta: dict, extensions: list[str]) -> str:
    ext_block = (
        "from setuptools import Extension\n\next_modules = [\n" + "\n".join((f for m in extensions)) + "\n]\n"
        if extensions
        else "ext_modules = []\n"
    )
    return f


def load_root(input_path: Path) -> Path:
    if input_path.is_dir():
        return input_path.resolve()
    if input_path.suffix == ".whl":
        tmp = Path(tempfile.mkdtemp())
        extract_wheel(input_path, tmp)
        return tmp
    msg = "Input must be a .whl file or an unzipped wheel directory"
    raise SystemExit(msg)


def read_metadata(root: Path) -> dict:
    dist_info = next(root.glob("*.dist-info"), None)
    if not dist_info:
        msg = "No .dist-info directory found"
        raise RuntimeError(msg)
    meta_file = dist_info / "METADATA"
    meta = Parser().parsestr(meta_file.read_text())
    return {
        "name": meta["Name"],
        "version": meta["Version"],
        "summary": meta.get("Summary", ""),
        "install_requires": meta.get_all("Requires-Dist") or [],
    }


def main() -> None:
    if len(sys.argv) != 2:
        msg = "Usage: python mk_setuppy.py <wheel.whl | unzipped-dir>"
        raise SystemExit(msg)
    input_path = Path(sys.argv[1]).resolve()
    root = load_root(input_path)
    meta = read_metadata(root)
    extensions = find_extensions(root)
    out_dir = Path("output") / meta["name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(root, out_dir, dirs_exist_ok=True)
    (out_dir / "setup.py").write_text(generate_setup_py(meta, extensions))
    (out_dir / "pyproject.toml").write_text(generate_pyproject_toml())
    print(f"✔ setup.py generated for {meta['name']}")
    print("✔ binary extensions detected" if extensions else "✔ pure Python package")


if __name__ == "__main__":
    main()
