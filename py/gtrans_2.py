
import sys
import json
import time
from googletrans import Translator


def translate_words(input_file, output_file):
    
    with open(input_file, "r", encoding="utf-8") as f:
        words = [line.strip() for line in f if line.strip()]

    total = len(words)
    print(f"Loaded {total} words from {input_file}\n")

    translator = Translator()
    translations = {}

    for i, word in enumerate(words, 1):
        try:
            result = translator.translate(word, src="en", dest="fa")
            translated = result.text
            translations[word] = translated
            
            print(f"[{i}/{total}] {word}  →  {translated}")
        except Exception as e:
            translations[word] = None
            print(f"[{i}/{total}] {word}  →  ERROR: {e}")
            time.sleep(1)  

        
        time.sleep(0.3)

        
        if i % 50 == 0:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(translations, f, ensure_ascii=False, indent=2)

    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(translations, f, ensure_ascii=False, indent=2)

    print(f"\nDone. Saved {len(translations)} translations to {output_file}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python translate_dict.py <input_file> [output_file]")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "dictionary_fa.json"

    translate_words(input_file, output_file)


if __name__ == "__main__":
    main()
