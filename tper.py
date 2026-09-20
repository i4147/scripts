import json
import multiprocessing
import time
from pathlib import Path
from typing import Any
from deep_translator import GoogleTranslator
from loguru import logger
from tqdm import tqdm
INPUT_FILE = "words.txt"
OUTPUT_FILE = "dic.json"
MAX_WORKERS = 8
SAVE_EVERY = 1000
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 0.5
def translate_word(word):
    for attempt in range(MAX_RETRIES):
        try:
            return GoogleTranslator(source="auto", target="en").translate(word)
        except Exception as exc:  
            logger.warning(
                "Failed '{}' (attempt {}/{}): {}",
                word,
                attempt + 1,
                MAX_RETRIES,
                exc,
            )
            time.sleep(RETRY_DELAY_SECONDS)
    return None
def load_words(input_file):
    seen = set()
    words = []
    with Path(input_file).open(encoding="utf-8") as fh:
        for raw in fh:
            word = raw.strip()
            if word and word not in seen:
                seen.add(word)
                words.append(word)
    return words
def load_existing_results(output_file):
    path = Path(output_file)
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
        logger.warning("Existing {} is not a JSON object; ignoring.", output_file)
    except Exception as exc:  
        logger.warning("Could not load existing {}: {}", output_file, exc)
    return {}
def save_results_atomic(results, output_file):
    target = Path(output_file)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)
    tmp.replace(target)
def main():
    words = load_words(INPUT_FILE)
    print("Loaded {} Persian words", len(words))
    results = load_existing_results(OUTPUT_FILE)
    print("Loaded {} existing translations from {}", len(results), OUTPUT_FILE)
    to_translate = [w for w in words if w not in results]
    total_remaining = len(to_translate)
    print("{} words to translate (skipping already translated)", total_remaining)
    if total_remaining == 0:
        print("Nothing to do. Exiting.")
        return 0
    new_count = 0
    pbar = tqdm(total=total_remaining, desc="Translating", unit="word")
    counter = multiprocessing.Value("i", 0)
    def on_success(word, translation):
        nonlocal new_count
        if translation:
            results[word] = translation
            new_count += 1
            print("{} → {}", word, translation)
        else:
            logger.error("Could not translate: {}", word)
        pbar.update(1)
        with counter.get_lock():
            counter.value += 1
            current = counter.value
        if current % SAVE_EVERY == 0:
            print("Saving progress after {} new translations...", new_count)
            save_results_atomic(results, OUTPUT_FILE)
    def on_error(exc):
        logger.error("Unexpected worker error: {}", exc)
        pbar.update(1)
    try:
        with multiprocessing.Pool(processes=MAX_WORKERS) as pool:
            for word in to_translate:
                pool.apply_async(
                    translate_word,
                    args=(word,),
                    callback=lambda translation, w=word: on_success(w, translation),
                    error_callback=on_error,
                )
            pool.close()
            pool.join()
    except KeyboardInterrupt:
        print("Interrupted by user. Saving progress...")
    finally:
        save_results_atomic(results, OUTPUT_FILE)
        pbar.close()
        print("Translation dictionary saved to {}", OUTPUT_FILE)
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
