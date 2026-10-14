
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "data" / "briefing.json"
API_KEY = os.environ.get("OPENAI_API_KEY")
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")

FEEDS = {
    "BBC Business": "https://feeds.bbci.co.uk/news/business/rss.xml",
    "Economic Times Markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "Moneycontrol Markets": "https://www.moneycontrol.com/rss/marketreports.xml",
    "TechCrunch": "https://techcrunch.com/feed/",
    "The Verge": "https://www.theverge.com/rss/index.xml",
    "Medical Xpress": "https://medicalxpress.com/rss-feed/",
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss",
}

WATCHLIST = [
    "TAO", "BTC", "ETH", "SOL", "ADA", "BNB",
    "USDT", "SPX6900", "BRETT", "RENDER", "AKT", "SUI"
]

CATEGORIES = [
    "Finance & Global Economy",
    "Indian Share Market",
    "Technology & AI",
    "Healthcare",
    "Crypto Watch",
]


def clean_text(value):
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", unescape(value)).strip()


def fetch_feed(name, url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ArtificialTranscendenceBriefing/1.0"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read()

    root = ET.fromstring(raw)
    entries = root.findall(".//item")

    # Also support Atom feeds.
    if not entries:
        entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")

    stories = []
    for entry in entries[:15]:
        def get_text(*paths):
            for path in paths:
                node = entry.find(path)
                if node is not None and node.text:
                    return node.text.strip()
            return ""

        title = get_text("title", "{http://www.w3.org/2005/Atom}title")
        link = get_text("link")
        if not link:
            link_node = entry.find("{http://www.w3.org/2005/Atom}link")
            if link_node is not None:
                link = link_node.attrib.get("href", "")

        summary = get_text(
            "description", "summary",
            "{http://www.w3.org/2005/Atom}summary",
            "{http://www.w3.org/2005/Atom}content"
        )
        published = get_text(
            "pubDate", "published", "updated",
            "{http://www.w3.org/2005/Atom}published",
            "{http://www.w3.org/2005/Atom}updated"
        )

        if not title or not link:
            continue

        stories.append({
            "title": clean_text(title),
            "summary": clean_text(summary)[:1200],
            "url": link,
            "published": published,
            "source": name,
        })
    return stories


def collect_news():
    all_stories = []
    for name, url in FEEDS.items():
        try:
            items = fetch_feed(name, url)
            print(f"{name}: fetched {len(items)} stories")
            all_stories.extend(items)
        except Exception as exc:
            print(f"WARNING: Could not fetch {name}: {exc}")

    # Deduplicate by URL.
    unique = {}
    for story in all_stories:
        unique[story["url"]] = story

    stories = list(unique.values())
    if len(stories) < 8:
        raise RuntimeError(
            f"Only {len(stories)} news items were fetched. "
            "Refusing to publish an inadequately sourced briefing."
        )
    return stories


def call_openai(source_stories):
    if not API_KEY:
        raise RuntimeError("OPENAI_API_KEY environment variable is missing.")

    prompt = f"""
Create a factual Daily Intelligence Briefing using ONLY the supplied news items.
Do not invent events, quotes, statistics, prices, forecasts, or source URLs.
A supplied headline alone is not proof of details absent from its summary.
If a category has insufficient relevant evidence, return fewer stories or an
empty list rather than inventing content. Aim for 5-8 stories per category
when the supplied evidence supports them.

Return JSON only, with this exact top-level structure:
{{
  "title": "Daily Intelligence Briefing",
  "published_at": "ISO-8601 UTC timestamp",
  "timezone": "Asia/Kolkata",
  "sections": [
    {{
      "category": "Finance & Global Economy",
      "stories": [
        {{
          "headline": "Short factual headline",
          "what_happened": "Evidence-based summary",
          "why_it_matters": "Practical context",
          "what_to_watch": "A reasonable next development to monitor",
          "source_name": "Publisher from the supplied item",
          "source_url": "Exact URL from the supplied item",
          "source_published_at": "Publication date if available, otherwise null"
        }}
      ]
    }},
    {{
      "category": "Indian Share Market",
      "stories": []
    }},
    {{
      "category": "Technology & AI",
      "stories": []
    }},
    {{
      "category": "Healthcare",
      "stories": []
    }},
    {{
      "category": "Crypto Watch",
      "watchlist": {json.dumps(WATCHLIST)},
      "stories": []
    }}
  ],
  "disclaimer": "For information only; not personalised investment or medical advice."
}}

Keep stories relevant to their category. The Indian Share Market section should
prioritize NSE, BSE, Nifty 50, Sensex, Bank Nifty, RBI, SEBI, earnings, IPOs,
FII/DII activity, and Indian sectors when supported by the sources.
Crypto Watch should cover relevant developments involving the requested assets
when supported by the sources. The watchlist is not a claim about current prices.
Never present old stories as breaking news. Use only exact URLs from the input.
Use concise, useful language and preserve source publication dates where given.

News items:
{json.dumps(source_stories, ensure_ascii=False)}
"""

    payload = json.dumps({
        "model": MODEL,
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": "You are a careful news editor. Output valid JSON only."
            },
            {"role": "user", "content": prompt}
        ],
        "response_format": {"type": "json_object"}
    }).encode("utf-8")

    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"OpenAI API returned HTTP {exc.code}: {details[:1500]}"
        ) from exc

    content = result["choices"][0]["message"]["content"]
    return json.loads(content)


def validate_briefing(data, allowed_urls):
    if data.get("title") != "Daily Intelligence Briefing":
        raise ValueError("Unexpected briefing title.")

    if data.get("timezone") != "Asia/Kolkata":
        raise ValueError("Briefing timezone is incorrect.")

    sections = data.get("sections")
    if not isinstance(sections, list):
        raise ValueError("sections must be a list.")

    categories = [s.get("category") for s in sections]
    if categories != CATEGORIES:
        raise ValueError(f"Unexpected section categories: {categories}")

    for section in sections:
        stories = section.get("stories")
        if not isinstance(stories, list):
            raise ValueError(f"Stories must be a list: {section['category']}")

        for story in stories:
            for field in (
                "headline", "what_happened", "why_it_matters",
                "what_to_watch", "source_name", "source_url"
            ):
                if not isinstance(story.get(field), str) or not story[field].strip():
                    raise ValueError(
                        f"Missing or invalid '{field}' in {section['category']}."
                    )

            if story["source_url"] not in allowed_urls:
                raise ValueError(
                    f"Generated story uses an unverified source URL: "
                    f"{story['source_url']}"
                )

    crypto = sections[-1]
    if crypto.get("watchlist") != WATCHLIST:
        raise ValueError("Crypto watchlist does not match the required list.")

    if not data.get("published_at"):
        raise ValueError("Missing published_at timestamp.")

    data["disclaimer"] = (
        "For information only; not personalised investment or medical advice."
    )


def main():
    print("Collecting RSS news...")
    news = collect_news()

    print(f"Sending {len(news)} sourced items to OpenAI ({MODEL})...")
    briefing = call_openai(news)

    allowed_urls = {item["url"] for item in news}
    validate_briefing(briefing, allowed_urls)

    # Write only after collection, generation, and validation all succeed.
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp_file = OUTPUT.with_suffix(".json.tmp")
    temp_file.write_text(
        json.dumps(briefing, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )
    temp_file.replace(OUTPUT)

    total = sum(len(section["stories"]) for section in briefing["sections"])
    print(f"SUCCESS: Published {total} sourced stories to {OUTPUT}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: Briefing was not updated: {exc}", file=sys.stderr)
        sys.exit(1)
