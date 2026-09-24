import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime


class COCBaseExtractor:
    def __init__(self):
        self.bases = []
        self.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    def extract_from_clashofstats(self):
        try:
            url = "https://www.clashofstats.com/bases/town-hall-18"
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, "html.parser")

            base_links = soup.find_all("a", class_="base-link")

            for link in base_links:
                href = link.get("href")
                name = link.get_text(strip=True)
                if href:
                    full_url = urljoin(url, href)
                    self.bases.append({"name": name, "url": full_url, "source": "Clash of Stats"})

            print(f"✓ Extracted {len(self.bases)} bases from Clash of Stats")
        except Exception as e:
            print(f"✗ Error extracting from Clash of Stats: {e}")

    def extract_from_cocbases(self):
        try:
            url = "https://www.cocbases.com/"
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, "html.parser")

            base_links = soup.find_all("a", href=True)
            th18_links = [link for link in base_links if "th18" in link.get("href", "").lower()]

            for link in th18_links[:20]:
                href = link.get("href")
                name = link.get_text(strip=True)
                full_url = urljoin(url, href)
                self.bases.append({"name": name or "TH18 Base", "url": full_url, "source": "COC Bases"})

            print(f"✓ Extracted bases from COC Bases")
        except Exception as e:
            print(f"✗ Error extracting from COC Bases: {e}")

    def extract_from_clash_ninja(self):
        try:
            url = "https://www.clash.ninja/bases/"
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, "html.parser")

            base_links = soup.find_all("a", href=True)
            th18_bases = []

            for link in base_links:
                href = link.get("href")
                if href and ("th18" in href.lower() or "town-hall-18" in href.lower()):
                    name = link.get_text(strip=True)
                    full_url = urljoin(url, href)
                    th18_bases.append({"name": name or "TH18 Base", "url": full_url, "source": "Clash Ninja"})

            self.bases.extend(th18_bases)
            print(f"✓ Extracted {len(th18_bases)} bases from Clash Ninja")
        except Exception as e:
            print(f"✗ Error extracting from Clash Ninja: {e}")

    def remove_duplicates(self):
        seen_urls = set()
        unique_bases = []

        for base in self.bases:
            if base["url"] not in seen_urls:
                seen_urls.add(base["url"])
                unique_bases.append(base)

        self.bases = unique_bases
        print(f"✓ Removed duplicates. Total unique bases: {len(self.bases)}")

    def save_as_html(self, filename="th18_bases.html"):
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TH18 Clash of Clans Bases</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        
        .container {{
            max-width: 1000px;
            margin: 0 auto;
        }}
        
        .header {{
            text-align: center;
            color: white;
            margin-bottom: 40px;
        }}
        
        .header h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }}
        
        .header p {{
            font-size: 1.1em;
            opacity: 0.9;
        }}
        
        .stats {{
            display: flex;
            justify-content: space-around;
            margin-bottom: 30px;
            flex-wrap: wrap;
        }}
        
        .stat-box {{
            background: white;
            padding: 20px 30px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            text-align: center;
            min-width: 150px;
            margin: 10px;
        }}
        
        .stat-box h3 {{
            color: #667eea;
            font-size: 2em;
        }}
        
        .stat-box p {{
            color: #666;
            margin-top: 5px;
        }}
        
        .filter-section {{
            margin-bottom: 30px;
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            justify-content: center;
        }}
        
        .filter-btn {{
            padding: 10px 20px;
            border: none;
            border-radius: 25px;
            cursor: pointer;
            font-size: 0.95em;
            transition: all 0.3s ease;
            background: white;
            color: #667eea;
            font-weight: 600;
        }}
        
        .filter-btn:hover,
        .filter-btn.active {{
            background: #667eea;
            color: white;
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.2);
        }}
        
        .bases-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }}
        
        .base-card {{
            background: white;
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            transition: all 0.3s ease;
            cursor: pointer;
        }}
        
        .base-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 8px 15px rgba(0,0,0,0.2);
        }}
        
        .card-header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px;
        }}
        
        .card-header h3 {{
            margin-bottom: 5px;
            word-break: break-word;
        }}
        
        .card-source {{
            font-size: 0.85em;
            opacity: 0.8;
            background: rgba(255,255,255,0.2);
            padding: 3px 8px;
            border-radius: 3px;
            display: inline-block;
        }}
        
        .card-body {{
            padding: 15px;
        }}
        
        .base-link {{
            display: inline-block;
            width: 100%;
            padding: 12px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            text-decoration: none;
            border-radius: 5px;
            text-align: center;
            font-weight: 600;
            transition: all 0.3s ease;
            margin-top: 10px;
            border: none;
            cursor: pointer;
            font-size: 1em;
        }}
        
        .base-link:hover {{
            opacity: 0.9;
            transform: scale(1.02);
        }}
        
        .base-link:active {{
            transform: scale(0.98);
        }}
        
        .footer {{
            text-align: center;
            color: white;
            padding: 20px;
            opacity: 0.8;
            font-size: 0.9em;
        }}
        
        .no-results {{
            text-align: center;
            color: white;
            padding: 40px;
            font-size: 1.2em;
        }}
        
        @media (max-width: 768px) {{
            .header h1 {{
                font-size: 1.8em;
            }}
            
            .bases-grid {{
                grid-template-columns: 1fr;
            }}
            
            .stats {{
                flex-direction: column;
                align-items: center;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚔️ TH18 Clash of Clans Bases</h1>
            <p>Discover the best Town Hall 18 attack and defense strategies</p>
        </div>
        
        <div class="stats">
            <div class="stat-box">
                <h3>{len(self.bases)}</h3>
                <p>Total Bases</p>
            </div>
            <div class="stat-box">
                <h3>{len(set(b["source"] for b in self.bases))}</h3>
                <p>Sources</p>
            </div>
            <div class="stat-box">
                <h3>{datetime.now().strftime("%B %d, %Y")}</h3>
                <p>Updated</p>
            </div>
        </div>
        
        <div class="filter-section">
            <button class="filter-btn active" onclick="filterBases('all')">All Sources</button>
            {self._generate_filter_buttons()}
        </div>
        
        <div class="bases-grid" id="basesGrid">
            {self._generate_base_cards()}
        </div>
        
        <div class="footer">
            <p>Generated on {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
            <p>Click on any base to view and copy the base layout</p>
        </div>
    </div>
    
    <script>
        function filterBases(source) {{
            const cards = document.querySelectorAll('.base-card');
            const buttons = document.querySelectorAll('.filter-btn');
            
            buttons.forEach(btn => btn.classList.remove('active'));
            event.target.classList.add('active');
            
            cards.forEach(card => {{
                if (source === 'all' || card.getAttribute('data-source') === source) {{
                    card.style.display = 'block';
                }} else {{
                    card.style.display = 'none';
                }}
            }});
        }}
        
        function copyBaseLink(url) {{
            navigator.clipboard.writeText(url).then(() => {{
                alert('Base link copied to clipboard!');
            }});
        }}
    </script>
</body>
</html>
"""

        with open(filename, "w", encoding="utf-8") as f:
            f.write(html_content)

        print(f"✓ HTML file saved as '{filename}'")

    def _generate_filter_buttons(self):
        sources = set(base["source"] for base in self.bases)
        buttons = []

        for source in sorted(sources):
            count = len([b for b in self.bases if b["source"] == source])
            buttons.append(
                f'<button class="filter-btn" onclick="filterBases(\'{source}\')">{source} ({count})</button>'
            )

        return "\n            ".join(buttons)

    def _generate_base_cards(self):
        cards = []

        for i, base in enumerate(self.bases):
            card = f"""<div class="base-card" data-source="{base["source"]}">
                <div class="card-header">
                    <h3>{base["name"]}</h3>
                    <span class="card-source">{base["source"]}</span>
                </div>
                <div class="card-body">
                    <a href="{base["url"]}" target="_blank" class="base-link">View Base</a>
                    <button onclick='copyBaseLink("{base["url"]}"); return false;' class="base-link" style="background: #f39c12; margin-top: 5px;">Copy Link</button>
                </div>
            </div>"""
            cards.append(card)

        return "\n            ".join(cards)

    def run(self):
        print("🚀 Starting TH18 COC Base Extraction...\n")

        self.extract_from_clashofstats()
        self.extract_from_cocbases()
        self.extract_from_clash_ninja()

        print(f"\n📊 Total bases extracted: {len(self.bases)}")

        self.remove_duplicates()

        if self.bases:
            self.save_as_html()
            print("\n✅ Extraction complete! Open 'th18_bases.html' in your browser.")
        else:
            print("\n⚠️ No bases found. The website structure may have changed.")


if __name__ == "__main__":
    extractor = COCBaseExtractor()
    extractor.run()
