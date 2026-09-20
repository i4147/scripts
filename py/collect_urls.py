import xml.etree.ElementTree as ET


def get_sitemap_urls(sitemap_url, seen=None):
    if seen is None:
        seen = set()
    if sitemap_url in seen:
        return []
    seen.add(sitemap_url)

    r = session.get(sitemap_url, timeout=20)
    r.raise_for_status()

    root = ET.fromstring(r.content)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    urls = []
    for loc in root.findall(".//sm:loc", ns):
        u = loc.text.strip()
        if u.endswith(".xml") or "sitemap" in u.lower():
            urls.extend(get_sitemap_urls(u, seen))
        else:
            urls.append(u)
    return urls


all_urls = []
for sm in ["https://subdl.com/sitemap.xml", "https://subdl.com/sitemap_index.xml"]:
    try:
        all_urls.extend(get_sitemap_urls(sm))
    except Exception as e:
        print("Sitemap error:", sm, e)

shameless_urls = [u for u in all_urls if "shameless" in u.lower()]
print(len(shameless_urls))
