import json
import time
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final
from deep_translator import GoogleTranslator
from loguru import logger

MAX_WORKERS = 8
OUTPUT_DIR = Path("./translations")
TranslateResult = tuple[Path, dict[str, str]]


def translate_file(file_path):
    try:
        content = file_path.read_text(encoding="utf-8").strip()
        if not content:
            logger.warning(f"⚠️  Empty file: {file_path.name}")
            return file_path, {}
        translator = GoogleTranslator(source="fa", target="en")
        translated_text = translator.translate(content)
        if translated_text is None:
            translated_text = ""
        original_lines = [line.strip() for line in content.split("\n") if line.strip()]
        translated_lines = [line.strip() for line in translated_text.split("\n") if line.strip()]
        translations = {}
        if len(original_lines) != len(translated_lines):
            for i, line in enumerate(original_lines):
                if line:
                    try:
                        translated_line = GoogleTranslator(source="fa", target="en").translate(line)
                        translations[line] = translated_line or ""
                    except Exception as exc:
                        translations[line] = f"TRANSLATION_ERROR: {exc!s}"
                        logger.warning(f"  ⚠️  Error translating line {i + 1} in {file_path.name}: {exc}")
        else:
            translations = dict(zip(original_lines, translated_lines, strict=False))
        print(f"✅ Translated: {file_path.name} ({len(translations)} words)")
        return file_path, translations
    except Exception as exc:
        logger.error(f"❌ Error processing {file_path.name}: {exc}")
        return file_path, {}


def save_translation(
    input_path,
    translations,
    output_dir=None,
):
    resolved_dir = output_dir if output_dir is not None else input_path.parent
    resolved_dir.mkdir(parents=True, exist_ok=True)
    output_filename = input_path.stem + "_translations.json"
    output_path = resolved_dir / output_filename
    output_path.write_text(json.dumps(translations, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"💾 Saved: {output_path.name}")
    return output_path


def main():
    current_dir = Path(".")
    text_files = list(current_dir.glob("*.txt"))
    if not text_files:
        logger.error("❌ No .txt files found in the current directory")
        print("   If your files have a different extension, modify the glob pattern")
        return
    print(f"📚 Found {len(text_files)} file(s) to translate")
    print(f"🚀 Starting translation with {MAX_WORKERS} parallel workers")
    print("-" * 40)
    start_time = time.time()
    successful = 0
    failed = 0
    with Pool(processes=MAX_WORKERS) as pool:
        async_results = [pool.apply_async(translate_file, (file_path,)) for file_path in text_files]
        for file_path, async_res in zip(text_files, async_results):
            try:
                input_path, translations = async_res.get()
                if translations:
                    save_translation(input_path, translations, OUTPUT_DIR)
                    successful += 1
                else:
                    failed += 1
            except Exception as exc:
                logger.error(f"❌ Failed to process {file_path.name}: {exc}")
                failed += 1
    elapsed_time = time.time() - start_time
    print("=" * 40)
    print("✨ Translation complete!")
    print(f"   ✅ Successful: {successful} files")
    if failed > 0:
        logger.warning(f"   ❌ Failed: {failed} files")
    print(f"   ⏱️  Time elapsed: {elapsed_time:.2f} seconds")
    print(f"   📁 Output directory: {OUTPUT_DIR.absolute()}")


if __name__ == "__main__":
    raise SystemExit(main())
