from pathlib import Path
from lingua import LanguageDetectorBuilder
from collections import Counter


detector = LanguageDetectorBuilder.from_all_languages().build()


def get_srt_files(directory: Path) -> list[Path]:
    return list(directory.glob("*.srt"))


def detect_language_majority_vote(file_path: Path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        detected_languages = []
        line_count = 0
        skipped_count = 0

        for line in lines:
            line = line.strip()

            
            if not line or "-->" in line or line.isdigit():
                skipped_count += 1
                continue

            line_count += 1

            try:
                detected = detector.detect_language_of(line)
                if detected:
                    detected_languages.append(detected)
                    print(f'      Line {line_count}: {detected.name} - "{line[:50]}{"..." if len(line) > 50 else ""}"')
            except Exception as e:
                pass

        if detected_languages:
            
            lang_counter = Counter(detected_languages)
            most_common_lang = lang_counter.most_common(1)[0][0]

            print(f"\n   📊 Statistics:")
            print(f"      Total lines processed: {line_count}")
            print(f"      Lines skipped: {skipped_count}")
            print(f"      Language votes:")
            for lang, count in lang_counter.most_common():
                percentage = (count / line_count) * 100
                print(f"         {lang.name}: {count} votes ({percentage:.1f}%)")

            return most_common_lang

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
    print("=" * 80)

    language_folders = {}

    for file_path in srt_files:
        print(f"\n📄 Processing: {file_path.name}")
        print("─" * 80)

        detected_lang = detect_language_majority_vote(file_path)

        if detected_lang:
            lang_name = detected_lang.name
            lang_code = detected_lang.iso_code_639_1.name
            print(f"\n   ✅ FINAL RESULT: {lang_name} ({lang_code})")

            
            folder_name = f"{lang_name}_{lang_code}".lower()

            if folder_name not in language_folders:
                language_folders[folder_name] = []

            language_folders[folder_name].append(file_path)
        else:
            print(f"\n   ⚠ Could not detect language")

        print("=" * 80)

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
