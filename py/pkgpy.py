import pathlib
import subprocess

result = subprocess.run(
    ["apt", "search", "python"],
    capture_output=True,
    text=True,
)
lines = result.stdout.splitlines()
python_packages = [line.split("/")[0] for line in lines if line.startswith("python-")]
with pathlib.Path("py.txt").open("w", encoding="utf-8") as f:
    f.writelines(pkg + "\n" for pkg in python_packages)
print(f"Saved {len(python_packages)} python- packages to py.txt")
