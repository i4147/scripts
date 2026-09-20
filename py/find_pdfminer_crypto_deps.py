from pathlib import Path
import site

pkg_path = Path(site.getsitepackages()[0]) / "pdfminer"
for py_file in pkg_path.rglob("*.py"):
    content = py_file.read_text()
    if "cryptography" in content:
        print(f"Found: {py_file}")
