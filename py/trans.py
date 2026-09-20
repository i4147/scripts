
import sys
import json
import time
from deep_translator import GoogleTranslator
from tqdm import tqdm


def translate_words(input_file, output_file):
    
    with open(input_file, "r", encoding="utf-8") as f:
        words = [line.strip() for line in f if line.strip()]

    print(f"Loaded {len(words)} words from {input_file}")

    translator = GoogleTranslator(source="en", target="fa")
    translations = {}

    
    for word in tqdm(words, desc="Translating"):
        try:
            translated = translator.translate(word)
            translations[word] = translated
        except Exception as e:
            print(f"\nError translating '{word}': {e}")
            translations[word] = None
            time.sleep(1)  

        
        time.sleep(0.05)

    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(translations, f, ensure_ascii=False, indent=2)

    print(f"\nSaved {len(translations)} translations to {output_file}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python translate_dict.py <input_file> [output_file]")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "dictionary_fa.json"

    translate_words(input_file, output_file)


if __name__ == "__main__":
    main()
