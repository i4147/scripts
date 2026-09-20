import re
from pathlib import Path

from fastwalk import walk_files


def extract_requirements(metadata_path: Path) -> None:
    with Path(metadata_path).open(encoding="utf-8") as f:
        lines = f.readlines()
    requirements = []
    for line in lines:
        if line.startswith("Requires-Dist:"):
            match = re.match(
                r"Requires-Dist:\s*([^\s;]+)",
                line,
            )
            if match:
                requirements.append(match.group(1))
    if not requirements:
        print("No dependencies found in METADATA.")
        return
    with Path("/sdcard/requirements.txt").open("a", encoding="utf-8") as f:
        f.write("\n".join(requirements))


if __name__ == "__main__":
    dir = Path().cwd()
    for pth in walk_files(dir):
        path = Path(pth)
        if path.is_file() and path.name == "METADATA":
            extract_requirements(path)
