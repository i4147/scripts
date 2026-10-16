import os
import pathlib

import regex

url_pattern = regex.compile(r'https?://[^\s"\']+')
urls = set()
for root, dirs, files in os.walk("."):
    dirs[:] = [d for d in dirs if not d.startswith(".")]
    for file in files:
        filepath = os.path.join(root, file)
        try:
            with pathlib.Path(filepath).open(encoding="utf-8", errors="ignore") as f:
                content = f.read()
                found = url_pattern.findall(content)
                urls.update(found)
        except Exception as e:
            print(f"Failed to read {filepath}: {e}")
with pathlib.Path("urls.txt").open("w", encoding="utf-8") as f:
    f.writelines(url + "\n" for url in sorted(urls))
print(f"Extracted {len(urls)} unique URLs to urls.txt")
