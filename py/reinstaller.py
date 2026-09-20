import pathlib
import subprocess

with pathlib.Path("installed.txt").open("r", encoding="utf-8") as f:
    lines = f.readlines()
    for line in lines:
        print(f"installing {line}")
        subprocess.run(
            ["pkg", "reinstall", line.strip()],
            check=False,
        )
        subprocess.run(["pkg", "clean"], check=False)
print("done")
