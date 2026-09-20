import hashlib
from pathlib import Path


def calculate_hash(filepath, chunk_size=8192):
    sha256 = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    except (IOError, OSError, PermissionError):
        return None


def get_system_bin_hashes():
    system_bin = Path("/system/bin")
    if not system_bin.exists():
        print("⚠️  /system/bin directory not found!")
        return {}

    hashes = {}
    total = 0
    skipped = 0

    print("📂 Scanning /system/bin files...")

    for filepath in system_bin.iterdir():
        if filepath.is_file() or filepath.is_symlink():
            total += 1
            hash_value = calculate_hash(filepath)
            if hash_value:
                hashes[hash_value] = filepath.name
                print(f"  ✓ {filepath.name}")
            else:
                skipped += 1
                print(f"  ⚠️  Skipped {filepath.name} (permission denied or unreadable)")

    print(f"\n✅ Scanned {len(hashes)} files in /system/bin")
    if skipped:
        print(f"⚠️  Skipped {skipped} files (no read permission)")
    print()
    return hashes


def check_current_directory(system_hashes):
    current_dir = Path(".")
    matches = []
    skipped = 0

    print("🔍 Scanning current directory...")

    for filepath in current_dir.iterdir():
        if filepath.is_file():
            hash_value = calculate_hash(filepath)
            if hash_value:
                if hash_value in system_hashes:
                    matches.append((filepath.name, system_hashes[hash_value]))
                    print(f"  ⚠️  {filepath.name} -> matches /system/bin/{system_hashes[hash_value]}")
            else:
                skipped += 1
                print(f"  ⚠️  Skipped {filepath.name} (unreadable)")

    if skipped:
        print(f"\n⚠️  Skipped {skipped} files in current directory")
    return matches


def main():
    print("=" * 60)
    print("🔐 File Hash Comparison Tool")
    print("=" * 60)

    
    system_hashes = get_system_bin_hashes()

    if not system_hashes:
        print("❌ No readable files found in /system/bin")
        print("💡 Try running with root if needed: sudo python3 script.py")
        return

    
    matches = check_current_directory(system_hashes)

    
    print("\n" + "=" * 60)
    print("📊 SUMMARY")
    print("=" * 60)

    if matches:
        print(f"⚠️  Found {len(matches)} matching files:")
        for local_file, system_file in matches:
            print(f"  • {local_file} matches /system/bin/{system_file}")
    else:
        print("✅ No matching files found. All files are unique.")

    print("=" * 60)


if __name__ == "__main__":
    main()
