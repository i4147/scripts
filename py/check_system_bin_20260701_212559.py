import hashlib
from pathlib import Path


def calculate_hash(filepath, chunk_size=8192):
    sha256 = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    except (IOError, OSError):
        return None


def get_system_bin_hashes():
    system_bin = Path("/system/bin")
    if not system_bin.exists():
        print("⚠️  /system/bin directory not found!")
        return {}

    hashes = {}
    print("📂 Scanning /system/bin files...")

    for filepath in system_bin.iterdir():
        if filepath.is_file():
            try:
                if filepath.name == "uncrypt":
                    continue
                hash_value = calculate_hash(filepath)
                if hash_value:
                    hashes[hash_value] = filepath.name
                    print(f"  ✓ {filepath.name}")
            except:
                pass

    print(f"✅ Scanned {len(hashes)} files in /system/bin\n")
    return hashes


def check_current_directory(system_hashes):
    current_dir = Path(".")
    matches = []

    print("🔍 Scanning current directory...")

    for filepath in current_dir.iterdir():
        if filepath.is_file() and not filepath.name.startswith("."):
            hash_value = calculate_hash(filepath)
            if hash_value and hash_value in system_hashes:
                matches.append((filepath.name, system_hashes[hash_value]))
                print(f"  ⚠️  {filepath.name} -> matches /system/bin/{system_hashes[hash_value]}")

    return matches


def main():
    print("=" * 60)
    print("🔐 File Hash Comparison Tool")
    print("=" * 60)

    
    system_hashes = get_system_bin_hashes()

    if not system_hashes:
        print("❌ No files found in /system/bin or directory inaccessible")
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
