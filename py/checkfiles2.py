import shutil
import subprocess
from pathlib import Path

if not Path("error").exists():
    Path("error").mkdir()


def check_file(file: Path) -> dict[str, Path | int | str] | None:
    result = subprocess.run(
        ["prettier", "--check", str(file)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return {
            "file": file,
            "code": result.returncode,
            "stderr": result.stderr.strip(),
        }
    return None


if __name__ == "__main__":
    file_with_error = []
    for p in Path().rglob("*"):
        path = Path(p)
        if path.is_file() and (path.suffix in {".js", ".css"}):
            print(f"[ ] {path}")
            err = check_file(path)
            if err:
                print(path)
                file_with_error.append(path)
    for e in file_with_error:
        if Path(e).is_file():
            dst = f"error/{e}"
            shutil.move(e, dst)
