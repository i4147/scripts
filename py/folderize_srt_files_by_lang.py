from pathlib import Path
from lingua import LanguageDetectorBuilder


detector = LanguageDetectorBuilder.from_all_languages().build()


def get_srt_files(directory: Path) -> list[Path]:
    return list(directory.glob("*.srt"))


def detect_language(file_path: Path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        
        lines = content.split("\n")
        subtitle_text = "\n".join(
            line for i, line in enumerate(lines) if line.strip() and not line.isdigit() and "-->" not in line
        )

        
        if subtitle_text.strip():
            detected = detector.detect_language_of(subtitle_text)
            return detected
    except Exception as e:
        print(f"  ⚠ Error reading {file_path.name}: {e}")

    return None


def organize_subtitles(directory: Path = Path.cwd()) -> None:
    print(f"🔍 Scanning directory: {directory.absolute()}\n")

    srt_files = get_srt_files(directory)

    if not srt_files:
        print("❌ No .srt files found in the directory.")
        return

    print(f"📊 Found {len(srt_files)} SRT file(s)\n")
    print("=" * 70)

    language_folders = {}

    for file_path in srt_files:
        print(f"\n📄 Processing: {file_path.name}")

        detected_lang = detect_language(file_path)

        if detected_lang:
            lang_name = detected_lang.name
            lang_code = detected_lang.iso_code_639_1.name
            print(f"   ✓ Detected language: {lang_name} ({lang_code})")

            
            folder_name = f"{lang_name}_{lang_code}".lower()

            if folder_name not in language_folders:
                language_folders[folder_name] = []

            language_folders[folder_name].append(file_path)
        else:
            print(f"   ⚠ Could not detect language")

    print("\n" + "=" * 70)
    print(f"\n📁 Creating folders and moving files...\n")

    total_moved = 0

    for folder_name, files in sorted(language_folders.items()):
        folder_path = directory / folder_name
        folder_path.mkdir(exist_ok=True)

        print(f"📂 {folder_name.upper()} ({len(files)} file(s))")

        for file_path in files:
            new_path = folder_path / file_path.name
            file_path.rename(new_path)
            print(f"   ➜ {file_path.name}")
            total_moved += 1

    print(f"\n✅ Complete! Moved {total_moved} file(s) into {len(language_folders)} language folder(s).")


if __name__ == "__main__":
    
    organize_subtitles()
