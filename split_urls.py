import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse
EXTENSIONS = [
    "htm",
    "html",
    "js",
    "css",
    "pdf",
    "asp",
    "aspx",
    "php",
    "jsp",
    "jpg",
    "jpeg",
    "png",
    "gif",
    "svg",
    "webp",
    "zip",
    "rar",
    "7z",
    "tar",
    "gz",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "ppt",
    "pptx",
    "txt",
    "csv",
    "xml",
    "json",
    "mp3",
    "mp4",
    "avi",
    "mov",
    "wav",
    "exe",
    "dmg",
    "apk",
]
def get_extension(url):
    url = url.strip().strip('"').strip("'")
    if not url:
        return None
    parsed = urlparse(url)
    path = parsed.path or url  
    last_segment = path.rstrip("/").split("/")[-1]
    if "." not in last_segment:
        return None
    ext = last_segment.rsplit(".", 1)[-1].lower()
    return ext if ext in EXTENSIONS else None
def main():
    input_file = Path(sys.argv[1].strip())  
    if not input_file.exists():
        print(f"Input file not found: {input_file}")
        return
    buckets = defaultdict(list)
    with input_file.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            url = line.strip()
            if not url:
                continue
            ext = get_extension(url)
            if ext:
                buckets[ext].append(url)
    cwd = Path.cwd()
    if not buckets:
        print("No URLs with recognized extensions found.")
        return
    for ext, urls in sorted(buckets.items()):
        out_path = cwd / f"{ext}_urls.txt"
        out_path.write_text("\n".join(urls) + "\n", encoding="utf-8")
        print(f"{out_path.name}: {len(urls)} URLs")
if __name__ == "__main__":
    main()
