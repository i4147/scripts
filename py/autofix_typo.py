
import re
import sys
import shutil
from pathlib import Path
from typing import Set, Tuple
import argparse
from difflib import get_close_matches


try:
    from nltk.corpus import words as nltk_words

    NLTK_AVAILABLE = True
except ImportError:
    NLTK_AVAILABLE = False
    print("Warning: NLTK not installed. Install with: pip install nltk", file=sys.stderr)


try:
    from Levenshtein import distance as levenshtein_distance

    USE_LEVENSHTEIN = True
except ImportError:
    USE_LEVENSHTEIN = False
    print("Warning: python-Levenshtein not installed. Using difflib (slower).", file=sys.stderr)

    def levenshtein_distance(s1, s2):
        if len(s1) < len(s2):
            return levenshtein_distance(s2, s1)
        if len(s2) == 0:
            return len(s1)
        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        return previous_row[-1]



SKIP_PATTERNS = [
    r"^https?://",
    r"^ftp://",
    r"^file://",  
    r"^[a-f0-9]{32,}$",  
    r"^[A-Z_]+$",  
    r"^[a-z][a-z0-9_]*$",  
    r"^[a-z][A-Za-z0-9]*$",  
]


EXTENSIONS = {".md", ".py", ".toml", ".json", ".html", ".css", ".js"}


class TypoFixer:
    def __init__(self, oxford_dict_path: str = None, preview: bool = True) -> None:
        self.valid_words: Set[str] = set()
        self.preview = preview
        self.changes_made = 0
        self.files_processed = 0

        
        self._load_nltk_words()
        if oxford_dict_path and Path(oxford_dict_path).exists():
            self._load_oxford_dict(oxford_dict_path)

        
        self._add_code_keywords()

        
        self.skip_regex = re.compile("|".join(SKIP_PATTERNS), re.IGNORECASE)

    def _load_nltk_words(self) -> None:
        if NLTK_AVAILABLE:
            try:
                
                import nltk

                try:
                    nltk.data.find("corpora/words.zip")
                except LookupError:
                    print("Downloading NLTK words corpus...", file=sys.stderr)
                    nltk.download("words", quiet=True)

                self.valid_words.update(w.lower() for w in nltk_words.words())
                print(f"Loaded {len(nltk_words.words())} words from NLTK", file=sys.stderr)
            except Exception as e:
                print(f"Error loading NLTK words: {e}", file=sys.stderr)

    def _load_oxford_dict(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if "\t" in line:
                        word = line.split("\t")[0].strip().lower()
                        if word:
                            self.valid_words.add(word)
            print(f"Loaded additional words from Oxford dict", file=sys.stderr)
        except Exception as e:
            print(f"Error loading Oxford dictionary: {e}", file=sys.stderr)

    def _add_code_keywords(self) -> None:
        code_keywords = {
            
            "def",
            "class",
            "import",
            "from",
            "return",
            "yield",
            "if",
            "else",
            "elif",
            "for",
            "while",
            "break",
            "continue",
            "try",
            "except",
            "finally",
            "raise",
            "with",
            "as",
            "lambda",
            "True",
            "False",
            "None",
            "and",
            "or",
            "not",
            "is",
            "in",
            
            "function",
            "var",
            "let",
            "const",
            "typeof",
            "instanceof",
            "new",
            "this",
            "delete",
            "void",
            "typeof",
            "null",
            "undefined",
            "div",
            "span",
            "class",
            "id",
            "style",
            "font",
            "color",
            
            "true",
            "false",
            "null",
            "undefined",
            "NaN",
        }
        self.valid_words.update(code_keywords)

    def is_valid_word(self, word: str) -> bool:
        if not word or len(word) < 2:
            return True

        
        if self.skip_regex.match(word):
            return True

        
        if word.isupper() and len(word) <= 5:
            return True

        
        return word.lower() in self.valid_words

    def suggest_correction(self, word: str) -> str:
        if self.is_valid_word(word):
            return word

        
        original_word = word
        word_lower = word.lower()

        
        candidates = get_close_matches(word_lower, self.valid_words, n=1, cutoff=0.8)

        if candidates:
            correction = candidates[0]

            
            if original_word.isupper():
                return correction.upper()
            elif original_word[0].isupper() and original_word[1:].islower():
                return correction.capitalize()
            else:
                return correction

        return original_word  

    def fix_text(self, text: str) -> Tuple[str, int]:
        
        
        word_pattern = re.compile(r"\b([a-zA-Z]+(?:[-\'][a-zA-Z]+)*)\b")

        changes = 0

        def replace_word(match):
            nonlocal changes
            word = match.group(1)

            
            if len(word) <= 2:
                return match.group(0)

            corrected = self.suggest_correction(word)
            if corrected != word:
                changes += 1
                if self.preview:
                    print(f"  Would change: '{word}' -> '{corrected}'", file=sys.stderr)
            return corrected

        fixed = word_pattern.sub(replace_word, text)
        return fixed, changes

    def fix_file(self, filepath: Path) -> bool:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                original = f.read()
        except (UnicodeDecodeError, IOError) as e:
            print(f"  Skipping {filepath}: {e}", file=sys.stderr)
            return False

        
        if "\0" in original:
            return False

        fixed, changes = self.fix_text(original)

        if changes > 0 and not self.preview:
            
            backup = filepath.with_suffix(filepath.suffix + ".bak")
            shutil.copy2(filepath, backup)

            
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(fixed)
            print(f"  Fixed {changes} typo(s) in {filepath}", file=sys.stderr)
        elif changes > 0 and self.preview:
            print(f"  Would fix {changes} typo(s) in {filepath}", file=sys.stderr)

        self.changes_made += changes
        return changes > 0

    def process_directory(self, root_dir: str) -> None:
        root_path = Path(root_dir)

        for ext in EXTENSIONS:
            for filepath in root_path.rglob(f"*{ext}"):
                if filepath.is_file():
                    self.files_processed += 1
                    print(f"Processing: {filepath}", file=sys.stderr)
                    self.fix_file(filepath)

        print(f"\nSummary: Processed {self.files_processed} files", file=sys.stderr)
        if self.preview:
            print(f"Preview mode: Would fix {self.changes_made} typos total", file=sys.stderr)
            print("Run with --apply to make changes", file=sys.stderr)
        else:
            print(f"Fixed {self.changes_made} typos total", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-fix typos in text/code files")
    parser.add_argument("--oxford-dict", type=str, help="Path to Oxford dictionary file (word\\tdefinition)")
    parser.add_argument("--apply", action="store_true", help="Actually apply fixes (default: preview only)")
    parser.add_argument("--dir", type=str, default=".", help="Directory to process (default: current)")

    args = parser.parse_args()

    if not NLTK_AVAILABLE and not args.oxford_dict:
        print("Error: Need either NLTK or Oxford dictionary", file=sys.stderr)
        print("Install NLTK: pip install nltk", file=sys.stderr)
        print("Or provide --oxford-dict path", file=sys.stderr)
        sys.exit(1)

    fixer = TypoFixer(oxford_dict_path=args.oxford_dict, preview=not args.apply)
    fixer.process_directory(args.dir)

    if args.apply and fixer.changes_made == 0:
        print("No typos found to fix!", file=sys.stderr)


if __name__ == "__main__":
    main()
