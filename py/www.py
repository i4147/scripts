from pathlib import Path

if __name__ == "__main__":
    cwd = Path.cwd()
    for path in rglob("*.whl"):
        fname = path.name
        target_dir = Path("/sdcard/whl")
        target_path = target_dir / fname
        if target_path.exists():
            target_path.unlink()
        data = path.read_bytes()
        target_path.write_bytes(data)
        path.unlink()
        print(f"{ppath.name} -> {target_path.name}")
    print("done")
