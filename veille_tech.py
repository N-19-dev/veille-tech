# veille_tech.py
# Mini-framework de veille techno avec filtrage temporel (lookback_days)
# - Récupération RSS/Atom + autodécouverte
# - Extraction contenu (readability)
# - Classification par mots-clés
# - Dédup / stockage SQLite
# - Export JSON/Markdown
# - Filtre strict: ne garde que les items publiés dans la fenêtre lookback_days

import asyncio
import re
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

import yaml
import aiohttp
from aiolimiter import AsyncLimiter
import feedparser
from bs4 import BeautifulSoup
from slugify import slugify
from pydantic import BaseModel
from readability import Document
from urllib.parse import urlparse, urljoin
import urllib.robotparser as robotparser
from tqdm.asyncio import tqdm
import re
from urllib.parse import urlparse

# -----------------------
# Models & Config
# -----------------------

class Category(BaseModel):
    key: str
    title: str
    keywords: List[str]

class Source(BaseModel):
    name: str
    url: str

class StorageCfg(BaseModel):
    sqlite_path: str

class CrawlCfg(BaseModel):
    concurrency: int = 8
    per_host_rps: float = 1.0
    timeout_sec: int = 20
    user_agent: str = "VeilleTechBot/1.0 (+https://example.local/veille)"
    lookback_days: int = 7  # ✅ fenêtre de temps par défaut

class ExportCfg(BaseModel):
    out_dir: str = "export"
    make_markdown_digest: bool = True
    max_items_per_cat: int = 50

class NotifyCfg(BaseModel):
    slack_webhook_env: Optional[str] = None

class AppConfig(BaseModel):
    storage: StorageCfg
    crawl: CrawlCfg
    export: ExportCfg
    notify: NotifyCfg
    categories: List[Category]
    sources: List[Source]

# -----------------------
# Storage
# -----------------------

SQL_SCHEMA = """
CREATE TABLE IF NOT EXISTS items(
  id TEXT PRIMARY KEY,
  url TEXT,
  title TEXT,
  summary TEXT,
  content TEXT,
  published_ts INTEGER,
  source_name TEXT,
  category_key TEXT,
  created_ts INTEGER
);
CREATE INDEX IF NOT EXISTS idx_items_cat_pub ON items(category_key, published_ts DESC);
"""

@contextmanager
def db_conn(path: str):
    conn = sqlite3.connect(path)
    try:
        yield conn
    finally:
        conn.commit()
        conn.close()

def ensure_db(path: str):
    with db_conn(path) as conn:
        conn.executescript(SQL_SCHEMA)

def upsert_item(path: str, item: Dict[str, Any]):
    with db_conn(path) as conn:
        conn.execute("""
            INSERT OR IGNORE INTO items(id, url, title, summary, content, published_ts, source_name, category_key, created_ts)
            VALUES (:id, :url, :title, :summary, :content, :published_ts, :source_name, :category_key, :created_ts)
        """, item)

def query_latest_by_cat(path: str, limit_per_cat: int, min_ts: Optional[int] = None) -> Dict[str, List[Dict[str, Any]]]:
    with db_conn(path) as conn:
        cats = [r[0] for r in conn.execute("SELECT DISTINCT category_key FROM items")]
        result = {}
        for c in cats:
            if min_ts is not None:
                rows = conn.execute("""
                    SELECT url, title, summary, published_ts, source_name
                    FROM items
                    WHERE category_key=? AND published_ts>=?
                    ORDER BY published_ts DESC
                    LIMIT ?
                """, (c, min_ts, limit_per_cat)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT url, title, summary, published_ts, source_name
                    FROM items
                    WHERE category_key=?
                    ORDER BY published_ts DESC
                    LIMIT ?
                """, (c, limit_per_cat)).fetchall()
            result[c] = [
                dict(
                    url=row[0], title=row[1], summary=row[2],
                    published_ts=row[3], source_name=row[4]
                )
                for row in rows
            ]
        return result

# -----------------------
# Robots.txt helper
# -----------------------

class RobotsCache:
    def __init__(self, user_agent: str):
        self.cache: Dict[str, robotparser.RobotFileParser] = {}
        self.ua = user_agent

    async def allowed(self, session: aiohttp.ClientSession, url: str) -> bool:
        host = urlparse(url).netloc
        if host not in self.cache:
            rp = robotparser.RobotFileParser()
            robots_url = f"{urlparse(url).scheme}://{host}/robots.txt"
            try:
                async with session.get(robots_url, timeout=10) as r:
                    if r.status == 200:
                        rp.parse((await r.text()).splitlines())
                    else:
                        rp.default_allow = True
            except Exception:
                rp.default_allow = True
            self.cache[host] = rp
        return self.cache[host].can_fetch(self.ua, url)

# -----------------------
# Fetching & Parsing
# -----------------------

class Fetcher:
    def __init__(self, cfg: CrawlCfg):
        self.cfg = cfg
        self.limiters: Dict[str, AsyncLimiter] = {}

    def limiter_for(self, url: str) -> AsyncLimiter:
        host = urlparse(url).netloc
        if host not in self.limiters:
            rps = max(self.cfg.per_host_rps, 0.1)
            self.limiters[host] = AsyncLimiter(max_rate=rps, time_period=1)
        return self.limiters[host]

    async def get(self, session: aiohttp.ClientSession, url: str) -> Optional[bytes]:
        limiter = self.limiter_for(url)
        async with limiter:
            try:
                async with session.get(url, timeout=self.cfg.timeout_sec, headers={"User-Agent": self.cfg.user_agent}) as resp:
                    if resp.status == 200:
                        return await resp.read()
            except Exception:
                return None
        return None

def hash_id(url: str, title: str) -> str:
    h = hashlib.sha256()
    h.update(url.encode("utf-8"))
    h.update(b"||")
    h.update(title.encode("utf-8"))
    return h.hexdigest()

def extract_main_content(html: str, base_url: str) -> str:
    try:
        doc = Document(html)
        content_html = doc.summary()
        soup = BeautifulSoup(content_html, "lxml")
        # absolutize links/images
        for tag in soup.find_all(["a", "img"]):
            attr = "href" if tag.name == "a" else "src"
            if tag.has_attr(attr):
                tag[attr] = urljoin(base_url, tag[attr])
        # strip scripts/styles
        for t in soup(["script", "style"]):
            t.decompose()
        return soup.get_text("\n", strip=True)
    except Exception:
        # fallback: plain text
        soup = BeautifulSoup(html, "lxml")
        return soup.get_text("\n", strip=True)

def normalize_ts(entry: Dict[str, Any]) -> Optional[int]:
    """
    Tente d'extraire une date depuis un item de feedparser.
    NE FAIT PAS de fallback à 'now' : retourne None si indéterminable.
    """
    # champs structurés
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        if key in entry and entry[key]:
            try:
                dt = datetime(*entry[key][:6], tzinfo=timezone.utc)
                return int(dt.timestamp())
            except Exception:
                pass

    # champs texte libres
    for key in ("published", "updated", "created", "date"):
        val = entry.get(key)
        if val:
            try:
                dt = parsedate_to_datetime(val)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)
                return int(dt.timestamp())
            except Exception:
                pass

    # parfois encodé dans les tags
    for tag in entry.get("tags", []) or []:
        for k in ("term", "label"):
            val = tag.get(k)
            if val:
                try:
                    dt = parsedate_to_datetime(val)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    else:
                        dt = dt.astimezone(timezone.utc)
                    return int(dt.timestamp())
                except Exception:
                    continue

    return None  # ⬅️ clé : on ne sait pas → on ignore l'item

def discover_feed_links(html: str, base_url: str) -> List[str]:
    soup = BeautifulSoup(html, "html5lib")
    urls = []
    for link in soup.find_all("link", attrs={"rel": ["alternate", "ALTERNATE"]}):
        t = link.get("type", "")
        if "rss" in t.lower() or "atom" in t.lower():
            href = link.get("href")
            if href:
                urls.append(urljoin(base_url, href))
    # liens RSS potentiels
    for a in soup.find_all("a", href=True):
        if any(k in a["href"].lower() for k in ("rss", "atom", "feed")):
            urls.append(urljoin(base_url, a["href"]))
    # de-dup
    return list(dict.fromkeys(urls))

# -----------------------
# Classification
# -----------------------

def classify(title: str, summary: str, categories: List[Category]) -> Optional[str]:
    blob = f"{title} {summary}".lower()
    best_key = None
    best_hits = 0
    for c in categories:
        hits = sum(1 for kw in c.keywords if kw.lower() in blob)
        if hits > best_hits:
            best_hits = hits
            best_key = c.key
    return best_key if best_hits > 0 else None

# -----------------------
# Export
# -----------------------

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def to_markdown(groups: Dict[str, List[Dict[str, Any]]], categories: Dict[str, Category]) -> str:
    lines = [f"# Veille Tech — Digest du {datetime.now().strftime('%Y-%m-%d')}\n"]
    for key, items in groups.items():
        if not items:
            continue
        title = categories.get(key).title if key in categories else key
        lines.append(f"## {title}\n")
        for it in items:
            dt = datetime.fromtimestamp(it["published_ts"], tz=timezone.utc).strftime("%Y-%m-%d")
            lines.append(f"- [{it['title']}]({it['url']}) — {it['source_name']} · {dt}")
            if it.get("summary"):
                lines.append(f"  - {it['summary'][:240]}{'…' if len(it['summary'])>240 else ''}")
        lines.append("")  # blank
    return "\n".join(lines)

async def notify_slack(webhook: str, text: str, session: aiohttp.ClientSession):
    payload = {"text": text}
    await session.post(webhook, json=payload)

def is_editorial_article(url: str, cfg: dict, text: str = "") -> bool:
    c = cfg.get("crawl", {})
    domain = urlparse(url).netloc.lower()

    # domain filters
    for bad in c.get("blacklist_domains", []):
        if bad.replace("*","") in domain:
            return False
    wl = c.get("whitelist_domains", [])
    if wl and not any(good in domain for good in wl):
        return False

    # path regex
    path = urlparse(url).path.lower()
    allow_re = c.get("path_allow_regex")
    deny_re  = c.get("path_deny_regex")
    if deny_re and re.search(deny_re, path):
        return False
    if allow_re and not re.search(allow_re, path):
        return False

    # min content length
    min_len = int(c.get("min_text_length", 0))
    if min_len and len(text or "") < min_len:
        return False

    return True

# -----------------------
# Pipeline
# -----------------------

async def run(config_path: str = "config.yaml"):
    cfg = AppConfig(**yaml.safe_load(Path(config_path).read_text(encoding="utf-8")))
    ensure_db(cfg.storage.sqlite_path)

    fetcher = Fetcher(cfg.crawl)
    robots = RobotsCache(cfg.crawl.user_agent)

    out_dir = Path(cfg.export.out_dir)
    ensure_dir(out_dir)

    categories_by_key = {c.key: c for c in cfg.categories}

    now_ts = int(datetime.now(tz=timezone.utc).timestamp())
    lookback_days = getattr(cfg.crawl, "lookback_days", 7)
    window_start_ts = int((datetime.now(tz=timezone.utc) - timedelta(days=lookback_days)).timestamp())

    async with aiohttp.ClientSession(headers={"User-Agent": cfg.crawl.user_agent}) as session:
        # 1) Prépare la liste de flux : direct RSS si possible, sinon autodiscovery
        feed_urls: List[Dict[str, str]] = []

        async def prepare_source(src: Source):
            allowed = await robots.allowed(session, src.url)
            if not allowed:
                return
            raw = await fetcher.get(session, src.url)
            if not raw:
                return
            try:
                text = raw.decode("utf-8", errors="ignore")
            except Exception:
                text = raw.decode("latin-1", errors="ignore")

            # Détection flux direct
            lower = text.lower()
            if "<rss" in lower or "<feed" in lower:
                feed_urls.append({"name": src.name, "feed": src.url})
                return

            # Autodécouverte
            discovered = discover_feed_links(text, src.url)
            if discovered:
                for f in discovered:
                    # petit filtre de chemin côté feed (évite release-notes / whats-new / forum)
                    p = urlparse(f).path.lower()
                    deny_re = cfg.crawl.__dict__.get("path_deny_regex")
                    allow_re = cfg.crawl.__dict__.get("path_allow_regex")
                    if deny_re and re.search(deny_re, p):
                        continue
                    if allow_re and not re.search(allow_re, p):
                        continue
                    feed_urls.append({"name": src.name, "feed": f})
            else:
                # Fallback: on utilisera la page comme "flux" minimal
                feed_urls.append({"name": src.name, "feed": src.url})

        await asyncio.gather(*[prepare_source(s) for s in cfg.sources])

        # Dé-dup des feeds par URL
        seen = set()
        final_feeds = []
        for f in feed_urls:
            if f["feed"] not in seen:
                seen.add(f["feed"])
                final_feeds.append(f)

        # 2) Fetch & parse des flux
        sem = asyncio.Semaphore(cfg.crawl.concurrency)

        async def process_feed(entry: Dict[str, str]) -> int:
            url = entry["feed"]
            name = entry["name"]
            inserts = 0
            async with sem:
                if not await robots.allowed(session, url):
                    return 0
                raw = await fetcher.get(session, url)
                if not raw:
                    return 0
                text = raw.decode("utf-8", errors="ignore")
                parsed = feedparser.parse(text)

                if parsed.entries:
                    # Branche RSS/Atom
                    for e in parsed.entries[:40]:
                        published_ts = normalize_ts(e)
                        # ⛔ skip si pas de date ou trop ancien
                        if not published_ts or published_ts < window_start_ts:
                            continue

                        link = e.get("link") or e.get("id") or url
                        title = (e.get("title") or "").strip() or link
                        summary = BeautifulSoup((e.get("summary") or ""), "lxml").get_text(" ", strip=True)

                        # Récupère le contenu de l’article
                        content_text = ""
                        if link and await robots.allowed(session, link):
                            art_raw = await fetcher.get(session, link)
                            if art_raw:
                                art_txt = art_raw.decode("utf-8", errors="ignore")
                                content_text = extract_main_content(art_txt, link)

                        text_for_filter = (content_text or summary or "")
                        if not is_editorial_article(link, cfg.dict(), text=text_for_filter):
                            continue

                        cat_key = classify(title, (summary or content_text[:300]), cfg.categories)
                        if not cat_key:
                            continue

                        item = {
                            "id": hash_id(link, title),
                            "url": link,
                            "title": title,
                            "summary": summary or content_text[:300],
                            "content": content_text[:10000],
                            "published_ts": published_ts,
                            "source_name": name,
                            "category_key": cat_key,
                            "created_ts": now_ts
                        }
                        upsert_item(cfg.storage.sqlite_path, item)
                        inserts += 1
                else:
                    # Fallback: page HTML -> scrapper des <a> récents et dater via meta
                    soup = BeautifulSoup(text, "lxml")
                    links = []
                    for a in soup.select("a[href]"):
                        href = urljoin(url, a["href"])
                        t = (a.get_text() or "").strip()
                        if len(t) > 6 and href.startswith("http"):
                            links.append((href, t))
                    links = links[:20]

                    def guess_published_ts(html_txt: str) -> Optional[int]:
                        s = BeautifulSoup(html_txt, "lxml")
                        # Meta og/article/temps
                        candidates = [
                            ('meta[property="article:published_time"]', "content"),
                            ('meta[name="article:published_time"]', "content"),
                            ('meta[name="publish-date"]', "content"),
                            ('meta[name="pubdate"]', "content"),
                            ('meta[name="date"]', "content"),
                            ('time[datetime]', "datetime"),
                        ]
                        for sel, attr in candidates:
                            el = s.select_one(sel)
                            if el and el.has_attr(attr):
                                try:
                                    dt = datetime.fromisoformat(el[attr].replace("Z", "+00:00"))
                                    return int(dt.astimezone(timezone.utc).timestamp())
                                except Exception:
                                    pass
                        # balise <time> simple
                        time_el = s.find("time")
                        if time_el and time_el.get("datetime"):
                            try:
                                dt = datetime.fromisoformat(time_el["datetime"].replace("Z", "+00:00"))
                                return int(dt.astimezone(timezone.utc).timestamp())
                            except Exception:
                                pass
                        return None

                    for href, t in links:
                        if not await robots.allowed(session, href):
                            continue
                        art_raw = await fetcher.get(session, href)
                        if not art_raw:
                            continue
                        art_txt = art_raw.decode("utf-8", errors="ignore")
                        published_ts = guess_published_ts(art_txt)
                        # ⛔ skip si pas de date fiable ou trop ancien
                        if not published_ts or published_ts < window_start_ts:
                            continue
                        text_content = extract_main_content(art_txt, href)
                        if not is_editorial_article(href, cfg.dict(), text=text_content):
                            continue
                        cat_key = classify(t, text_content[:300], cfg.categories)
                        if not cat_key:
                            continue
                        item = {
                            "id": hash_id(href, t),
                            "url": href,
                            "title": t,
                            "summary": text_content[:300],
                            "content": text_content[:10000],
                            "published_ts": published_ts,
                            "source_name": name,
                            "category_key": cat_key,
                            "created_ts": now_ts
                        }
                        upsert_item(cfg.storage.sqlite_path, item)
                        inserts += 1
            return inserts

        total_new = 0
        for added in await tqdm.gather(*[process_feed(f) for f in final_feeds]):
            total_new += (added or 0)

        # 3) Export (re-filtre par sécurité)
        groups = query_latest_by_cat(
            cfg.storage.sqlite_path,
            cfg.export.max_items_per_cat,
            min_ts=window_start_ts
        )

        ensure_dir(out_dir)
        # JSON
        json_path = out_dir / f"digest_{datetime.now().strftime('%Y%m%d')}.json"
        json_path.write_text(json.dumps(groups, indent=2, ensure_ascii=False), encoding="utf-8")
        # Markdown
        if cfg.export.make_markdown_digest:
            md = to_markdown(groups, categories_by_key)
            md_path = out_dir / f"digest_{datetime.now().strftime('%Y%m%d')}.md"
            md_path.write_text(md, encoding="utf-8")

        # 4) Notification Slack (optionnelle)
        webhook_env = cfg.notify.slack_webhook_env
        if webhook_env:
            wh = os.environ.get(webhook_env)
            if wh:
                lines = [f"*Veille Tech* — derniers ajouts (<={lookback_days}j):"]
                for k, items in groups.items():
                    if items:
                        title = categories_by_key.get(k).title if k in categories_by_key else k
                        lines.append(f"• {title}: {len(items)} items")
                await notify_slack(wh, "\n".join(lines), session)

        # 5) Purge DB (facultatif) — décommente pour ne garder que la fenêtre glissante
        # with db_conn(cfg.storage.sqlite_path) as conn:
        #     conn.execute("DELETE FROM items WHERE published_ts < ?", (window_start_ts,))

        print(f"Done. New/kept items this run (inserted): {total_new}")
        print(f"Exported: {json_path}")
        if cfg.export.make_markdown_digest:
            print(f"Exported: {md_path}")

# -----------------------
# CLI
# -----------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Veille techno crawler (fenêtre temporelle)")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    asyncio.run(run(args.config))