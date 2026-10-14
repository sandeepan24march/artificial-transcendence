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

# RSS sources are attempted independently. Some publishers may block RSS or
# change endpoints; one failed feed will not stop the remaining sources.
FEEDS = {
    # AI, invention and deep technology
    "MIT Technology Review": "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
    "VentureBeat AI": "https://venturebeat.com/category/ai/feed/",
    "The Decoder": "https://the-decoder.com/feed/",
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "Wired AI": "https://www.wired.com/feed/tag/ai/latest/rss",
    "The Verge AI": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    # Indian markets
    "Economic Times Markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "Moneycontrol Markets": "https://www.moneycontrol.com/rss/marketreports.xml",
    "Livemint Markets": "https://www.livemint.com/rss/marketsRSS",
    # Global markets and economy
    "BBC Business": "https://feeds.bbci.co.uk/news/business/rss.xml",
    "Bloomberg Markets": "https://www.bloomberg.com/feeds/markets/news.rss",
    "Reuters Business (Google News RSS)": "https://news.google.com/rss/search?q=site%3Areuters.com%2Fbusiness%2F+business+markets&hl=en-US&gl=US&ceid=US%3Aen",
    "WSJ Markets": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    # HealthTech and medical innovation
    "MedCity News": "https://medcitynews.com/feed/",
    "MobiHealthNews": "https://www.mobihealthnews.com/feed",
    "STAT News": "https://www.statnews.com/feed/",
    "Medical News Today": "https://www.medicalnewstoday.com/rss",
    "MedTech Dive": "https://www.medtechdive.com/feeds/news/",
    "Medical Xpress": "https://medicalxpress.com/rss-feed/",
    # Crypto news/research
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss",
    "Decrypt": "https://decrypt.co/feed",
    "The Block": "https://www.theblock.co/rss.xml",
    "DeFiLlama Research": "https://defillama.com/research/feed.xml",
    # General fallback feeds
    "TechCrunch": "https://techcrunch.com/feed/",
    "The Verge": "https://www.theverge.com/rss/index.xml",
}

CATEGORIES = ["Finance & Global Economy", "Indian Share Market", "Technology & AI", "Healthcare", "Crypto Watch"]
WATCHLIST = ["TAO", "BTC", "ETH", "SOL", "ADA", "BNB", "USDT", "SPX6900", "BRETT", "RENDER", "AKT", "SUI"]

CRYPTO_TERMS = ["bitcoin", "ethereum", "solana", "cardano", "binance", "tether", "bittensor", "spx6900", "based brett", "brett", "render token", "akash network", "sui blockchain", "cryptocurrency", "crypto", "stablecoin", "blockchain", "defi", "altcoin", "token", "on-chain", "onchain", "web3", "digital asset"]
INDIA_TERMS = ["nifty", "sensex", "nse", "bse", "bank nifty", "sebi", "rbi", "indian stocks", "indian market", "india shares", "dalal street", "fii", "dii", "ipo", "rupee", "mutual fund", "indian equity"]
TECH_TERMS = ["artificial intelligence", " ai ", "machine learning", "deep learning", "large language model", "llm", "gpu", "nvidia", "cloud computing", "data center", "datacenter", "semiconductor", "robotics", "openai", "google", "microsoft", "amazon", "cybersecurity", "software", "technology", "chip", "neural network", "autonomous agent", "quantum computing", "deep tech", "invention", "research paper", "generative ai"]
HEALTH_TERMS = ["health", "healthcare", "medical", "medicine", "clinical trial", "biotech", "biopharma", "drug discovery", "genomics", "hospital", "medical device", "medtech", "digital health", "telemedicine", "patient", "diagnostic", "surgery", "therapeutic"]

INDIA_SOURCES = {"Economic Times Markets", "Moneycontrol Markets", "Livemint Markets"}
TECH_SOURCES = {"MIT Technology Review", "VentureBeat AI", "The Decoder", "TechCrunch AI", "Wired AI", "The Verge AI", "TechCrunch", "The Verge"}
HEALTH_SOURCES = {"MedCity News", "MobiHealthNews", "STAT News", "Medical News Today", "MedTech Dive", "Medical Xpress"}
CRYPTO_SOURCES = {"CoinDesk", "Cointelegraph", "Decrypt", "The Block", "DeFiLlama Research"}
GLOBAL_SOURCES = {"BBC Business", "Bloomberg Markets", "Reuters Business (Google News RSS)", "WSJ Markets"}


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
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ArtificialTranscendence/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        root = ET.fromstring(response.read())
    atom = "{http://www.w3.org/2005/Atom}"
    entries = root.findall(".//item") or root.findall(f".//{atom}entry")

    def field(entry, *paths):
        for path in paths:
            node = entry.find(path)
            if node is not None and node.text:
                return node.text.strip()
        return ""

    result = []
    for entry in entries[:30]:
        title = clean_text(field(entry, "title", f"{atom}title"))
        link = field(entry, "link")
        if not link:
            node = entry.find(f"{atom}link")
            if node is not None:
                link = node.attrib.get("href", "")
        summary = clean_text(field(entry, "description", "summary", f"{atom}summary", f"{atom}content"))[:650]
        published = parse_date(field(entry, "pubDate", "published", "updated", f"{atom}published", f"{atom}updated"))
        if title and urlparse(link).scheme in ("http", "https"):
            result.append({"title": title, "summary": summary, "url": link, "published": published, "source": name})
    return result


def category_for(item):
    source = item["source"]
    text = f" {item['title']} {item['summary']} ".lower()
    if source in CRYPTO_SOURCES:
        return "Crypto Watch"
    if source in HEALTH_SOURCES:
        return "Healthcare"
    if source in INDIA_SOURCES:
        return "Indian Share Market"
    if source in TECH_SOURCES:
        return "Technology & AI"
    if source in GLOBAL_SOURCES:
        return "Finance & Global Economy"
    if any(term in text for term in CRYPTO_TERMS):
        return "Crypto Watch"
    if any(term in text for term in INDIA_TERMS):
        return "Indian Share Market"
    if any(term in text for term in HEALTH_TERMS):
        return "Healthcare"
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
        "source_published_at": item["published"],
    }


def main():
    sections = [{"category": category, "stories": []} for category in CATEGORIES]
    sections[-1]["watchlist"] = WATCHLIST
    collected = []
    successful_feeds = 0
    for name, url in FEEDS.items():
        try:
            items = fetch_feed(name, url)
            successful_feeds += 1
            print(f"{name}: fetched {len(items)} stories")
            collected.extend(items)
        except Exception as exc:
            print(f"WARNING: {name}: {exc}")
    if successful_feeds == 0:
        raise RuntimeError("All RSS feeds failed; keeping previous briefing.")
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
                age_days = (now - datetime.fromisoformat(published)).total_seconds() / 86400
                if age_days > 3 or age_days < -1:
                    continue
            except ValueError:
                continue
        section = next(s for s in sections if s["category"] == category_for(item))
        section["stories"].append(make_story(item))
    for section in sections:
        section["stories"].sort(key=lambda s: s["source_published_at"] or "", reverse=True)
        section["stories"] = section["stories"][:8]
    total = sum(len(s["stories"]) for s in sections)
    if total < 8:
        raise RuntimeError("Too few recent stories; keeping previous briefing.")
    briefing = {
        "title": "Daily Intelligence Briefing",
        "published_at": now.isoformat(),
        "timezone": "Asia/Kolkata",
        "sections": sections,
        "disclaimer": "For information only; not personalised investment or medical advice. Headlines and summaries originate from external RSS publishers. Categories are automated.",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(briefing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
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
