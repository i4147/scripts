import argparse
import json
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

FALLBACK_ORDER = ("translate", "deep_translator", "googletrans")


class BackendError(Exception):
    pass


def _make_translate(source, target, script_path):
    try:
        import translate
    except ImportError as e:
        raise BackendError(f"cannot import 'translate': {e}")

    mod_file = os.path.abspath(getattr(translate, "__file__", "") or "")
    if mod_file and mod_file == os.path.abspath(script_path):
        raise BackendError(
            "'translate' resolves to this script itself (rename the script to avoid shadowing the package)"
        )

    cls = getattr(translate, "Translator", None) or getattr(translate, "GoogleTranslator", None)
    if cls is None:
        raise BackendError("'translate' module exposes neither 'Translator' nor 'GoogleTranslator'")

    if cls.__name__ == "Translator":

        def call(text, cls=cls, source=source, target=target):
            result = cls(from_lang=source, to_lang=target).translate(text)
            print(f"{text} -> {result}")
            return result

    else:

        def call(text, cls=cls, source=source, target=target):
            result = cls(source=source, target=target).translate(text)
            print(f"{text} -> {result}")
            return result

    return call


def _make_deep_translator(source, target, _script_path):
    try:
        from deep_translator import GoogleTranslator
    except ImportError as e:
        raise BackendError(f"cannot import 'deep_translator': {e}")

    def call(text, cls=GoogleTranslator, source=source, target=target):

        result = cls(source=source, target=target).translate(text)
        print(f"{text} -> {result}")
        return result

    return call


def _make_googletrans(source, target, _script_path):
    try:
        from googletrans import Translator
    except ImportError as e:
        raise BackendError(f"cannot import 'googletrans': {e}")

    lock = threading.Lock()
    inst = Translator()

    def call(text, inst=inst, lock=lock, source=source, target=target):
        with lock:
            result = inst.translate(text, src=source, dest=target).text
            print(f"{text} -> {result}")
            return result

    return call


_BACKEND_FACTORIES = {
    "translate": _make_translate,
    "deep_translator": _make_deep_translator,
    "googletrans": _make_googletrans,
}


class TranslatorWrapper:
    def __init__(self, preferred, source, target, script_path):
        self.source = source
        self.target = target
        self.backend_name = None
        self._call = None

        candidates = [preferred] + [b for b in FALLBACK_ORDER if b != preferred]

        errors = []
        for name in candidates:
            factory = _BACKEND_FACTORIES.get(name)
            if factory is None:
                errors.append((name, "unknown backend"))
                continue
            try:
                self._call = factory(source, target, script_path)
            except BackendError as e:
                errors.append((name, str(e)))
                continue

            self.backend_name = name
            if name != preferred:
                print(f"⚠️  Backend '{preferred}' unavailable — falling back to '{name}'.")
            return

        print("Error: no usable translation backend found.", file=sys.stderr)
        for name, err in errors:
            print(f"  - {name}: {err}", file=sys.stderr)
        print("\nInstall at least one of:", file=sys.stderr)
        print("  pip install translate", file=sys.stderr)
        print("  pip install deep_translator", file=sys.stderr)
        print("  pip install googletrans==4.0.0rc1", file=sys.stderr)
        sys.exit(1)

    def translate(self, text):
        return self._call(text)


def load_progress(out_path):
    if not os.path.exists(out_path):
        return {}
    try:
        with open(out_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, IOError):
        pass
    return {}


def save_output(out_path, data, lock):
    with lock:
        tmp_path = out_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, out_path)


def parse_args():
    parser = argparse.ArgumentParser(description="Translate a word list file line by line to JSON.")

    parser.add_argument(
        "-i",
        "--input",
        default="words.txt",
        help="Input file with one word per line (default: words.txt)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="words.json",
        help="Output JSON file (default: words.json)",
    )

    parser.add_argument("-s", "--source", default="fr", help="Source language code (default: fr)")
    parser.add_argument("-t", "--target", default="en", help="Target language code (default: en)")

    parser.add_argument(
        "-b",
        "--backend",
        default="translate",
        choices=FALLBACK_ORDER,
        help="Preferred translation backend (default: translate); falls back automatically if unusable",
    )

    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=4,
        help="Number of concurrent worker threads (default: 4)",
    )
    parser.add_argument(
        "-d",
        "--delay",
        type=float,
        default=0.3,
        help="Delay in seconds between requests per worker (default: 0.3)",
    )

    parser.add_argument(
        "--save-every",
        type=int,
        default=100,
        help="Save the output file every N words (default: 100)",
    )
    parser.add_argument(
        "--no-continue",
        action="store_true",
        help="Do not resume from a previous job; start from scratch",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    input_path = args.input
    out_path = args.output

    if not os.path.exists(input_path):
        print(f"Error: Input file '{input_path}' not found.")
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        words = [line.strip() for line in f if line.strip()]

    print(f"Loaded {len(words)} words from {input_path}")
    print(f"Source -> target: {args.source} -> {args.target}")

    results = {} if args.no_continue else load_progress(out_path)
    if results:
        print(f"Resuming: {len(results)} words already translated.")

    pending = [w for w in words if w not in results]

    if not pending:
        print("Nothing to translate. Done.")
        return

    translator = TranslatorWrapper(
        preferred=args.backend,
        source=args.source,
        target=args.target,
        script_path=__file__,
    )
    print(
        f"Backend: {translator.backend_name} | "
        f"Workers: {args.workers} | Delay: {args.delay}s | "
        f"Save every: {args.save_every}"
    )
    print(f"Words to translate: {len(pending)}")

    save_lock = threading.Lock()
    counter_lock = threading.Lock()
    print_lock = threading.Lock()
    completed_count = [0]
    total_pending = len(pending)

    def translate_word(word):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                time.sleep(args.delay)
                result = translator.translate(word)
                print(f"{word} -> {result}")
                return word, ("" if result is None else str(result).strip())
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(args.delay * (attempt + 2))
                else:
                    return word, f"__ERROR__: {e}"

    try:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(translate_word, w): w for w in pending}

            for future in as_completed(futures):
                word, translation = future.result()
                results[word] = translation

                with counter_lock:
                    completed_count[0] += 1
                    count = completed_count[0]

                with print_lock:
                    status = "✗" if translation.startswith("__ERROR__") else "✓"
                    print(f"[{count}/{total_pending}] {status} {word} -> {translation}")

                if count % args.save_every == 0:
                    save_output(out_path, results, save_lock)
                    with print_lock:
                        print(f"  💾 Saved progress ({count}/{total_pending})")

    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user. Saving progress...")
        save_output(out_path, results, save_lock)
        print(f"Progress saved to {out_path}. Run again to resume.")
        sys.exit(0)

    save_output(out_path, results, save_lock)
    print(f"\n✅ Done! Translated {len(results)} words total.")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
