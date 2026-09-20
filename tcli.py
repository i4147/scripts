import json
import multiprocessing as mp
import sys
from pathlib import Path
from translate import Translator
N_WORKERS = 8
SOURCE_LANG = "en"
TARGET_LANG = "fa"
def translate_word(word):
    word = word.strip()
    if not word:
        return {"source": word, "translation": None, "error": "empty"}
    try:
        translator = Translator(from_lang=SOURCE_LANG, to_lang=TARGET_LANG)
        translation = translator.translate(word)
        print(f"{word} -> {translation}")
        return {"source": word, "translation": translation, "error": None}
    except Exception as exc:  
        return {"source": word, "translation": None, "error": str(exc)}
def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <input_file> [output_file]", file=sys.stderr)
        return 1
    input_path = Path(sys.argv[1])
    if not input_path.is_file():
        print(f"Error: input file '{input_path}' not found.", file=sys.stderr)
        return 1
    if len(sys.argv) >= 3:
        output_path = Path(sys.argv[2])
    else:
        output_path = input_path.with_suffix(".fa.json")
    words = [
        line.strip()
        for line in input_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    print(f"Loaded {len(words)} words from {input_path}", file=sys.stderr)
    with mp.Pool(processes=N_WORKERS) as pool:
        results = pool.map(translate_word, words)
    output_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {len(results)} entries to {output_path}", file=sys.stderr)
    failures = sum(1 for r in results if r["error"])
    if failures:
        print(f"Warning: {failures} entries failed.", file=sys.stderr)
    return 0
if __name__ == "__main__":
    sys.exit(main())
