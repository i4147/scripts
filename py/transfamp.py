from __future__ import annotations

import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from deep_translator import GoogleTranslator


def translate_file(path: Path) -> tuple[Path, dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            print(f"⚠️  Empty file: {path.name}")
            return path, {}
        translator = GoogleTranslator(source="fa", target="en")
        translated_text = translator.translate(content)
        original_lines = [line.strip() for line in content.split("\n") if line.strip()]
        translated_lines = [line.strip() for line in translated_text.split("\n") if line.strip()]
        if len(original_lines) != len(translated_lines):
            translations = {}
            for i, line in enumerate(original_lines):
                if line:
                    try:
                        translated = GoogleTranslator(source="fa", target="en").translate(line)
                        translations[line] = translated
                    except Exception as e:
                        translations[line] = f"TRANSLATION_ERROR: {e!s}"
                        print(f"  ⚠️  Error translating line {i + 1} in {path.name}: {e}")
        else:
            translations = dict(zip(original_lines, translated_lines, strict=False))
        print(f"✅ Translated: {path.name} ({len(translations)} words)")
        return path, translations
    except Exception as e:
        print(f"❌ Error processing {path.name}: {e}")
        return path, {}


def save_translation(input_path: Path, translations: dict, output_dir: Path | None = None):
    if output_dir is None:
        output_dir = input_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    output_filename = input_path.stem + "_translations.json"
    output_path = output_dir / output_filename
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(translations, f, ensure_ascii=False, indent=2)
    print(f"💾 Saved: {output_path.name}")
    return output_path


def main():
    current_dir = Path(".")
    max_workers = 4
    output_dir = Path("./translations")
    text_files = list(current_dir.glob("*.txt"))
    if not text_files:
        print("❌ No .txt files found in the current directory")
        print("   If your files have a different extension, modify the glob pattern")
        return
    print(f"📚 Found {len(text_files)} file(s) to translate")
    print(f"🚀 Starting translation with {max_workers} parallel workers")
    print("-" * 40)
    start_time = time.time()
    successful = 0
    failed = 0
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {executor.submit(translate_file, path): path for path in text_files}
        for future in as_completed(future_to_file):
            path = future_to_file[future]
            try:
                input_path, translations = future.result()
                if translations:
                    save_translation(input_path, translations, output_dir)
                    successful += 1
                else:
                    failed += 1
            except Exception as e:
                print(f"❌ Failed to process {path.name}: {e}")
                failed += 1
    elapsed_time = time.time() - start_time
    print("\n" + "=" * 40)
    print("✨ Translation complete!")
    print(f"   ✅ Successful: {successful} files")
    if failed > 0:
        print(f"   ❌ Failed: {failed} files")
    print(f"   ⏱️  Time elapsed: {elapsed_time:.2f} seconds")
    print(f"   📁 Output directory: {output_dir.absolute()}")


if __name__ == "__main__":
    raise SystemExit(main())
