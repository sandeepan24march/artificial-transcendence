
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "data" / "briefing.json"

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

CATEGORIES = [
    "Finance & Global Economy",
    "Indian Share Market",
    "Technology & AI",
    "Healthcare",
    "Crypto Watch",
]

WATCHLIST = [
    "TAO", "BTC", "ETH", "SOL", "ADA", "BNB",
    "USDT", "SPX6900", "BRETT", "RENDER", "AKT", "SUI"
]

CRYPTO_TERMS = [
    "bitcoin", "ethereum", "solana", "cardano", "binance",
    "tether", "bittensor", "spx6900", "based brett",
    "render token", "akash network", "sui blockchain",
    "cryptocurrency", "crypto", "stablecoin", "blockchain",
    "defi", "altcoin", "token"
]

INDIA_TERMS = [
    "nifty", "sensex", "nse", "bse", "bank nifty",
    "sebi", "rbi", "indian stocks", "indian market",
    "india shares", "dalal street", "fii", "dii",
    "ipo", "rupee", "mutual fund"
]

TECH_TERMS = [
    "artificial intelligence", " ai ", "machine learning",
    "gpu", "nvidia", "cloud computing", "data center",
    "datacenter", "semiconductor", "robotics", "openai",
    "google", "microsoft", "amazon", "cybersecurity",
    "software", "technology", "chip"
]


def clean_text(value):
    value = re.sub(r"<[^>]*>", " ", value or "")
    return re.sub(r"\s+", " ", unescape(value)).strip()


def parse_date(value):
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def fetch_feed(name, url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 ArtificialTranscendence/1.0"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        root = ET.fromstring(response.read())

    entries = root.findall(".//item")
    atom = "{http://www.w3.org/2005/Atom}"
    if not entries:
        entries = root.findall(f".//{atom}entry")

    def field(entry, *paths):
        for path in paths:
            node = entry.find(path)
            if node is not None and node.text:
                return node.text.strip()
        return ""

    result = []
    for entry in entries[:20]:
        title = clean_text(field(entry, "title", f"{atom}title"))
        link = field(entry, "link")
        if not link:
            node = entry.find(f"{atom}link")
            if node is not None:
                link = node.attrib.get("href", "")

        summary = clean_text(field(
            entry, "description", "summary",
            f"{atom}summary", f"{atom}content"
        ))[:650]

        published = parse_date(field(
            entry, "pubDate", "published", "updated",
            f"{atom}published", f"{atom}updated"
        ))

        if not title or urlparse(link).scheme not in ("http", "https"):
            continue

        result.append({
            "title": title,
            "summary": summary,
            "url": link,
            "published": published,
            "source": name
        })

    return result


def category_for(item):
    source = item["source"]
    text = f" {item['title']} {item['summary']} ".lower()

    if source in ("CoinDesk", "Cointelegraph"):
        return "Crypto Watch"
    if source == "Medical Xpress":
        return "Healthcare"
    if source in ("Economic Times Markets", "Moneycontrol Markets"):
        return "Indian Share Market"

    if any(term in text for term in CRYPTO_TERMS):
        return "Crypto Watch"
    if any(term in text for term in INDIA_TERMS):
        return "Indian Share Market"
    if source in ("TechCrunch", "The Verge"):
        return "Technology & AI"
    if any(term in text for term in TECH_TERMS):
        return "Technology & AI"

    return "Finance & Global Economy"


def make_story(item):
    return {
        "headline": item["title"],
        "what_happened": item["summary"] or "Read the original report for details.",
        "why_it_matters": "See the original source for context.",
        "what_to_watch": "Follow the source for further developments.",
        "source_name": item["source"],
        "source_url": item["url"],
        "source_published_at": item["published"]
    }


def main():
    sections = [
        {"category": category, "stories": []}
        for category in CATEGORIES
    ]
    sections[-1]["watchlist"] = WATCHLIST

    collected = []
    for name, url in FEEDS.items():
        try:
            items = fetch_feed(name, url)
            print(f"{name}: fetched {len(items)} stories")
            collected.extend(items)
        except Exception as exc:
            print(f"WARNING: {name}: {exc}")

    unique = {}
    for item in collected:
        unique.setdefault(item["url"], item)

    if len(unique) < 8:
        raise RuntimeError("Too few RSS items; keeping previous briefing.")

    now = datetime.now(timezone.utc)
    for item in unique.values():
        published = item["published"]
        if published:
            try:
                age_days = (
                    now - datetime.fromisoformat(published)
                ).total_seconds() / 86400
                if age_days > 3 or age_days < -1:
                    continue
            except ValueError:
                continue

        category = category_for(item)
        section = next(
            s for s in sections if s["category"] == category
        )
        section["stories"].append(make_story(item))

    for section in sections:
        section["stories"].sort(
            key=lambda s: s["source_published_at"] or "",
            reverse=True
        )
        section["stories"] = section["stories"][:8]

    total = sum(len(s["stories"]) for s in sections)
    if total < 8:
        raise RuntimeError(
            "Too few recent stories; keeping previous briefing."
        )

    briefing = {
        "title": "Daily Intelligence Briefing",
        "published_at": now.isoformat(),
        "timezone": "Asia/Kolkata",
        "sections": sections,
        "disclaimer": (
            "For information only; not personalised investment "
            "or medical advice. Headlines and summaries originate "
            "from external RSS publishers. Categories are automated."
        )
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(briefing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )
    temporary.replace(OUTPUT)

    for section in sections:
        print(f"{section['category']}: {len(section['stories'])} stories")
    print(f"SUCCESS: Saved {total} stories to {OUTPUT}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
