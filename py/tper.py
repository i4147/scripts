from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

from deep_translator import GoogleTranslator
from tqdm import tqdm

INPUT_FILE = "words.txt"
OUTPUT_FILE = "dic.json"
MAX_WORKERS = 12
SAVE_EVERY = 1000
lock = Lock()


def translate_word(word) -> str | None:
    for attempt in range(3):
        try:
            return GoogleTranslator(source="auto", target="en").translate(word)
        except Exception as e:
            print(f"[WARN] Failed '{word}' (attempt {attempt + 1}): {e}")
            time.sleep(0.5)
    return None


def load_words(input_file: str) -> list[str]:
    with Path(input_file).open(encoding="utf-8") as f:
        return [w.strip() for w in f if w.strip()]


def load_existing_results(output_file: str):
    if Path(output_file).exists():
        try:
            with Path(output_file).open(encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            print(f"[WARN] Could not load existing {output_file}: {e}")
    return {}


def save_results_atomic(results, output_file: str) -> None:
    tmp = output_file + ".tmp"
    with Path(tmp).open("w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    Path(tmp).replace(output_file)


def main() -> None:
    words = load_words(INPUT_FILE)
    print(f"[INFO] Loaded {len(words)} Persian words")
    results = load_existing_results(OUTPUT_FILE)
    print(f"[INFO] Loaded {len(results)} existing translations from {OUTPUT_FILE}")
    to_translate = [w for w in words if w not in results]
    total_remaining = len(to_translate)
    print(f"[INFO] {total_remaining} words to translate (will skip already translated)")
    if total_remaining == 0:
        print("[INFO] Nothing to do. Exiting.")
        return
    new_count = 0
    pbar = tqdm(total=total_remaining, desc="Translating", unit="word")
    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_map = {executor.submit(translate_word, w): w for w in to_translate}
            for future in as_completed(future_map):
                persian_word = future_map[future]
                try:
                    english = future.result()
                    with lock:
                        if english:
                            results[persian_word] = english
                            new_count += 1
                            print(f"{persian_word} → {english}")
                        else:
                            print(f"[FAIL] Could not translate: {persian_word}")
                        pbar.update(1)
                        if new_count % SAVE_EVERY == 0:
                            print(f"[INFO] Saving progress after {new_count} new translations...")
                            save_results_atomic(results, OUTPUT_FILE)
                except Exception as e:
                    print(f"[ERROR] Unexpected error for '{persian_word}': {e}")
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user. Saving progress...")
    finally:
        with lock:
            save_results_atomic(results, OUTPUT_FILE)
        pbar.close()
        print(f"\n[SAVED] Translation dictionary saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    raise SystemExit(main())
