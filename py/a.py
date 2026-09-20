import asyncio
import json
from datetime import datetime
from twscrape import API, gather
from twscrape.logger import set_log_level


async def main():
    api = API()

    query = 'TH18 (base OR layout OR "copy link" OR "base link") lang:en -filter:replies'

    print("Searching for latest TH18 bases on X...")

    tweets = await gather(api.search(query, limit=50))

    bases = []

    for tweet in tweets:
        text = tweet.rawContent.lower()
        url = f"https://x.com/{tweet.user.username}/status/{tweet.id}"

        base_links = []
        if "link.clashofclans.com" in text or "action=OpenLayout" in text:
            parts = tweet.rawContent.split()
            for part in parts:
                if "link.clashofclans.com" in part or "OpenLayout" in part:
                    base_links.append(part.strip())

        if base_links or any(word in text for word in ["th18", "town hall 18", "legend", "war base", "cwl"]):
            bases.append(
                {
                    "date": tweet.date.strftime("%Y-%m-%d %H:%M"),
                    "username": tweet.user.username,
                    "text": tweet.rawContent[:280] + "..." if len(tweet.rawContent) > 280 else tweet.rawContent,
                    "post_url": url,
                    "base_links": base_links,
                    "likes": tweet.likeCount,
                    "views": tweet.viewCount,
                }
            )

    unique_bases = {b["post_url"]: b for b in bases}.values()

    print(f"Found {len(unique_bases)} relevant posts.")

    html_content = generate_html(list(unique_bases))

    filename = f"TH18_Bases_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"✅ Saved to {filename}")


def generate_html(bases):
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Latest Clash of Clans TH18 Bases - {datetime.now().strftime("%Y-%m-%d")}</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; background: #0f0f0f; color: #ddd; }}
            h1 {{ color: #ffcc00; }}
            .base {{ border: 1px solid #333; padding: 15px; margin: 15px 0; border-radius: 8px; background: #1a1a1a; }}
            a {{ color: #00ccff; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
            .links {{ margin-top: 10px; }}
            .meta {{ color: #888; font-size: 0.9em; }}
        </style>
    </head>
    <body>
        <h1>🛡️ Latest TH18 Clash of Clans Bases from X</h1>
        <p>Found {len(bases)} recent posts • Sorted by recency</p>
    """

    for base in sorted(bases, key=lambda x: x["date"], reverse=True):
        html += f"""
        <div class="base">
            <strong>@{base["username"]}</strong> • {base["date"]}
            <p>{base["text"]}</p>
            <div class="meta">
                ❤️ {base["likes"]} • 👁️ {base["views"]}
                <a href="{base["post_url"]}" target="_blank">[View Post on X]</a>
            </div>
        """

        if base["base_links"]:
            html += '<div class="links"><strong>Base Copy Links:</strong><ul>'
            for link in base["base_links"]:
                html += f'<li><a href="{link}" target="_blank">{link}</a></li>'
            html += "</ul></div>"

        html += "</div>"

    html += """
    </body>
    </html>
    """
    return html


if __name__ == "__main__":
    set_log_level("INFO")
    asyncio.run(main())
