import os
import requests

if __name__ == "__main__":
    os.makedirs("downloads", exist_ok=True)
    with open("urls.txt") as f:
        urls = [l.strip() for l in f if l.strip() and (not l.startswith("#"))]
    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] {url}")
        try:
            r = requests.get(url, timeout=30, stream=True)
            r.raise_for_status()
            filename = url.split("/")[-1] or "index.html"
            with open(os.path.join("downloads", filename), "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            print("✅ Saved.")
        except Exception as e:
            print(f"❌ Error: {e}")
