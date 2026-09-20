import re
import sys
from collections import Counter
from pathlib import Path
USER_STOPWORDS_FILE = Path("/sdcard/data/stopwords")
def load_user_stopwords(path):
    stopwords = set()
    with path.open(errors="ignore") as f:
        for line in f:
            line = line.strip().lower()
            if not line or line.startswith("#"):
                continue
            stopwords.add(line)
    stopwords = list(stopwords)
    return stopwords
EXCLUDE = load_user_stopwords(USER_STOPWORDS_FILE)
def extract_words(text):
    return re.findall("[a-z]{3,}", text.lower())
def main():
    src = Path(sys.argv[1].strip())
    text = src.read_text(encoding="utf-8", errors="ignore")
    words = extract_words(text)
    filtered = [w for w in words if not (w in EXCLUDE)]
    for word, count in Counter(filtered).most_common(50):
        if count > 1:
            print(f"{word:<15} {count}")
if __name__ == "__main__":
    raise SystemExit(main())
