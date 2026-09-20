import json
import time
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final, TypedDict
from deep_translator import GoogleTranslator  
from loguru import logger
CHUNK_SIZE = 4500
MAX_WORKERS = 8
INPUT_FILE = Path("words.txt")
OUTPUT_FILE = Path("fa_en.json")
class TranslationResult(TypedDict):
    pass
Chunk = tuple[int, int, str]
def chunk_file(file_path, chunk_size=CHUNK_SIZE):
    chunks = []
    current_chunk = []
    current_size = 0
    start_line = 0
    line_num = 0
    try:
        with file_path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f):
                if current_size + len(line) > chunk_size and current_chunk:
                    chunks.append((start_line, line_num - 1, "".join(current_chunk)))
                    current_chunk = [line]
                    current_size = len(line)
                    start_line = line_num
                else:
                    current_chunk.append(line)
                    current_size += len(line)
            if current_chunk:
                chunks.append((start_line, line_num, "".join(current_chunk)))
    except Exception as exc:
        logger.error(f"Error reading file {file_path}: {exc}")
    return chunks
def translate_chunk(chunk_data, chunk_index, total_chunks):
    start_line, end_line, text = chunk_data
    if chunk_index > 0:
        time.sleep(2)
    try:
        translator = GoogleTranslator(source="fa", target="en")
        translated = translator.translate(text)
        if not translated:
            return None
        return {
            "chunk_id": f"{start_line}_{end_line}",
            "start_line": start_line,
            "end_line": end_line,
            "original": text,
            "translated": translated,
        }
    except Exception as exc:
        logger.error(f"Error translating chunk {start_line}_{end_line}: {exc}")
        return None
def main():
    if not INPUT_FILE.exists():
        logger.error(f"Input file {INPUT_FILE} not found.")
        return
    print("Extracting chunks...")
    chunks = chunk_file(INPUT_FILE)
    print(f"Total chunks: {len(chunks)}")
    if not chunks:
        logger.warning("No text found to translate.")
        return
    print("Translating chunks...")
    translations = []
    total_chunks = len(chunks)
    with Pool(processes=MAX_WORKERS) as pool:
        async_results = [
            pool.apply_async(translate_chunk, (chunk, idx, total_chunks))
            for idx, chunk in enumerate(chunks)
        ]
        for i, async_res in enumerate(async_results, 1):
            result = async_res.get()
            if result is not None:
                translations.append(result)
            print(f"Progress: {i}/{total_chunks}")
    if not translations:
        logger.warning("No translations were successful.")
        return
    print(f"Writing results to {OUTPUT_FILE}...")
    try:
        final_data = {
            "translations": sorted(translations, key=lambda item: item["start_line"])
        }
        OUTPUT_FILE.write_text(
            json.dumps(final_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("Done!")
    except Exception as exc:
        logger.error(f"Error writing output file: {exc}")
if __name__ == "__main__":
    raise SystemExit(main())
