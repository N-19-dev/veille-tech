import json
import re
import shutil
from pathlib import Path
from datetime import datetime, date, timedelta

EXPORT_DIR = Path("export")
DOCS_DIR = Path("docs")
POSTS_DIR = DOCS_DIR / "posts"
INDEX_MD = DOCS_DIR / "index.md"
ARCHIVES_MD = DOCS_DIR / "archives.md"

# ---------- Helpers dates ----------

def iso_week_to_range(label: str):
    """
    '2025w42' -> (start_date, end_date_exclusive)
    ISO: semaine = lundi→dimanche ; start = lundi 00:00, end = lundi suivant
    """
    m = re.fullmatch(r"(\d{4})w(\d{2})", label)
    if not m:
        raise ValueError(f"Label semaine invalide: {label}")
    year, week = int(m.group(1)), int(m.group(2))
    jan4 = date(year, 1, 4)  # ISO: la semaine 1 contient le 4 janvier
    week1_monday = jan4 - timedelta(days=jan4.isoweekday() - 1)
    start = week1_monday + timedelta(weeks=week - 1)
    end = start + timedelta(days=7)
    return start, end

def human_week_label(label: str) -> str:
    start, end = iso_week_to_range(label)
    end_inclusive = end - timedelta(days=1)
    return f"Semaine {label[-2:]} — {start.strftime('%d %b %Y')} → {end_inclusive.strftime('%d %b %Y')}"

def human_date_yyyymmdd(yyyymmdd: str) -> str:
    return datetime.strptime(yyyymmdd, "%Y%m%d").strftime("%d %B %Y")

def _fmt_date(ts: int) -> str:
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")
    except Exception:
        return ""

# ---------- Découverte des exports ----------

def find_weekly_exports():
    """
    Retourne [(week_label, week_dir, ai_summary_path, ai_selection_json)] triés du plus récent au plus ancien.
    """
    out = []
    if not EXPORT_DIR.exists():
        return out
    for p in sorted(EXPORT_DIR.iterdir()):
        if p.is_symlink():  # ignore export/latest
            continue
        if not p.is_dir():
            continue
        if not re.fullmatch(r"\d{4}w\d{2}", p.name):
            continue
        summary = p / "ai_summary.md"
        selection = p / "ai_selection.json"
        if summary.exists():
            out.append((p.name, p, summary, selection if selection.exists() else None))
    # tri desc (année, semaine)
    out.sort(key=lambda t: (int(t[0][:4]), int(t[0][-2:])), reverse=True)
    return out

def find_legacy_exports():
    """
    Format hérité: ai_summary_YYYYMMDD.md (+ ai_selection_YYYYMMDD.json)
    Retourne [(YYYYMMDD, None, summary_path, selection_json)] triés du plus récent au plus ancien.
    """
    pairs = []
    if not EXPORT_DIR.exists():
        return pairs
    for smd in EXPORT_DIR.glob("ai_summary_*.md"):
        m = re.fullmatch(r"ai_summary_(\d{8})\.md", smd.name)
        if not m:
            continue  # ignore 'ai_summary_2025w41.md' etc.
        date_str = m.group(1)
        sel = EXPORT_DIR / f"ai_selection_{date_str}.json"
        pairs.append((date_str, None, smd, sel if sel.exists() else None))
    pairs.sort(key=lambda t: t[0], reverse=True)
    return pairs

# ---------- Extraction d’un résumé court (accroche carte accueil) ----------

_OVERVIEW_RE = re.compile(r"(?mi)^\s*##\s*.*aperçu\s*général.*semaine.*?$")

def _strip_md(s: str) -> str:
    # retire liens [texte](url), emphases, code inline simple
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"[*_`]+", "", s)
    return s

def _first_sentences(text: str, max_chars: int = 180, max_sentences: int = 2) -> str:
    parts = re.split(r"(?<=[\.\!\?])\s+", text.strip())
    snippet = " ".join(parts[:max_sentences]).strip()
    if len(snippet) > max_chars:
        snippet = snippet[:max_chars].rstrip(" ,;:") + "…"
    return snippet

def extract_overview_excerpt(summary_path: Path, max_chars: int = 180) -> str:
    """
    Va chercher la section '## Aperçu général de la semaine' dans ai_summary.md.
    Renvoie 1–2 phrases courtes.
    """
    try:
        md = summary_path.read_text(encoding="utf-8")
    except Exception:
        return ""
    # trouver le header "Aperçu général de la semaine"
    m = _OVERVIEW_RE.search(md)
    if not m:
        # fallback : prendre le tout début du fichier (hors H1 si présent)
        body = re.sub(r"(?m)^\s*#\s+.*$", "", md, count=1).strip()
        body = _strip_md(body)
        return _first_sentences(body, max_chars=max_chars)

    start = m.end()
    rest = md[start:]
    # arrêter au prochain H2
    nxt = re.search(r"(?m)^\s*##\s+", rest)
    block = rest[:nxt.start()] if nxt else rest
    # si la section contient des puces, on prend la première ligne utile
    lines = [l.strip(" -•\t") for l in block.strip().splitlines() if l.strip()]
    if not lines:
        return ""
    para = " ".join(lines[:3])  # compacte 2–3 lignes si puces
    para = _strip_md(para)
    return _first_sentences(para, max_chars=max_chars)

# ---------- Rendu HTML propre des "Liens à creuser" ----------

def render_links_sections_html(data: dict, per_cat_limit: int = 10) -> str:
    """
    data = { cat_key: [ {title,url,source_name,published_ts,llm_score}, ... ] }
    Renvoie un bloc HTML propre avec <details> par catégorie et badges de score.
    """
    if not data:
        return "<p><em>Aucune entrée au-dessus du seuil cette semaine.</em></p>"

    parts = ['<hr />', '<h3>🔗 Liens à creuser (sélection IA)</h3>']

    # ordre: garder l'ordre d'insertion du JSON
    for cat, items in data.items():
        safe_cat = cat.replace("_", " ").strip()
        parts.append('<details class="links-cat" open>')
        parts.append(f'  <summary><strong>{safe_cat}</strong> <span class="count">({len(items)})</span></summary>')
        parts.append('  <ul class="link-list">')

        for it in items[:per_cat_limit]:
            title = it.get("title") or it.get("url") or "Sans titre"
            url = it.get("url", "#")
            src = it.get("source_name", "").strip()
            score = it.get("llm_score", None)
            dt = _fmt_date(it.get("published_ts"))

            score_html = f'<span class="score-badge">{int(score)}</span>' if isinstance(score, (int, float)) else ""
            meta = " · ".join(x for x in [src, dt] if x)

            parts.append('    <li class="link-item">')
            parts.append(f'      <a href="{url}" target="_blank" rel="noopener">{title}</a>')
            if meta or score_html:
                parts.append('      <div class="meta">')
                if meta:
                    parts.append(f'        <span class="src">{meta}</span>')
                if score_html:
                    parts.append(f'        {score_html}')
                parts.append('      </div>')
            parts.append('    </li>')

        parts.append('  </ul>')
        parts.append('</details>')

    return "\n".join(parts)

# ---------- Génération des posts ----------

def build_post_week(week_label: str, summary_md: Path, selection_json: Path | None) -> Path:
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    out = POSTS_DIR / f"{week_label}.md"

    body = summary_md.read_text(encoding="utf-8").strip()
    # évite un H1 parasite : on mettra notre propre H1
    body = re.sub(r"(?m)^\s*#\s+", "## ", body)

    links_block = ""
    if selection_json and selection_json.exists():
        try:
            data = json.loads(selection_json.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        # 🔥 Rendu HTML propre
        links_block = render_links_sections_html(data, per_cat_limit=10)

    h1 = f"# 🧠 Veille — {human_week_label(week_label)}"
    final = [h1, "", body]
    if links_block:
        final.append(links_block)

    out.write_text("\n".join(final).strip() + "\n", encoding="utf-8")
    return out

def build_post_legacy(date_str: str, summary_md: Path, selection_json: Path | None) -> Path:
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    out = POSTS_DIR / f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}.md"

    body = summary_md.read_text(encoding="utf-8").strip()
    body = re.sub(r"(?m)^\s*#\s+", "## ", body)

    links_block = ""
    if selection_json and selection_json.exists():
        try:
            data = json.loads(selection_json.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        links_block = render_links_sections_html(data, per_cat_limit=10)

    try:
        h1 = f"# 🧠 Veille — {human_date_yyyymmdd(date_str)}"
    except Exception:
        h1 = f"# 🧠 Veille — {date_str}"

    final = [h1, "", body]
    if links_block:
        final.append(links_block)

    out.write_text("\n".join(final).strip() + "\n", encoding="utf-8")
    return out

# ---------- Pages : Accueil & Archives ----------

def render_card(title_html: str, subtitle_html: str, href: str, description: str) -> str:
    return f"""
<div class="post-card">
  <div class="post-meta">{subtitle_html}</div>
  <h3><a href="{href}">{title_html}</a></h3>
  <p>{description}</p>
</div>
""".strip()

def write_index(weekly_pairs, legacy_pairs, max_cards: int = 12):
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    cards = []
    cards.append("# 🏠 Accueil\n")
    cards.append("_Dernières semaines — triées du plus récent au plus ancien._\n")

    # Construire le flux (clé, href, sous-titre, extrait)
    feed = []
    for wlabel, wdir, smd, _sel in weekly_pairs:
        href = f"posts/{wlabel}/"  # sans .md (MkDocs router)
        subtitle = human_week_label(wlabel)
        excerpt = extract_overview_excerpt(smd, max_chars=180)
        title = f"Semaine {wlabel[-2:]}"
        feed.append((("week", int(wlabel[:4]), int(wlabel[-2:])), title, subtitle, href, excerpt))

    for dstr, _dir, smd, _sel in legacy_pairs:
        href = f"posts/{dstr[:4]}-{dstr[4:6]}-{dstr[6:]}/"
        subtitle = human_date_yyyymmdd(dstr)
        excerpt = extract_overview_excerpt(smd, max_chars=180)
        title = subtitle
        feed.append((("date", int(dstr[:4]), int(dstr[4:6]) * 100 + int(dstr[6:])), title, subtitle, href, excerpt))

    # Tri desc
    feed.sort(key=lambda x: x[0], reverse=True)

    for _key, title, subtitle, href, excerpt in feed[:max_cards]:
        desc = excerpt or "Résumé IA, Top 3 et liens à creuser."
        cards.append(render_card(title_html=title, subtitle_html=subtitle, href=href, description=desc))

    INDEX_MD.write_text("\n\n".join(cards) + "\n", encoding="utf-8")

def write_archives(weekly_pairs, legacy_pairs):
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    lines = []
    lines.append("# 📚 Archives\n")
    lines.append("_Tous les posts, du plus récent au plus ancien._\n")

    entries = []
    for w in weekly_pairs:
        label = w[0]
        year, week = int(label[:4]), int(label[-2:])
        entries.append((human_week_label(label), f"posts/{label}/", year, week))
    for d in legacy_pairs:
        ds = d[0]
        year = int(ds[:4])
        day_key = int(ds[4:])
        entries.append((human_date_yyyymmdd(ds), f"posts/{ds[:4]}-{ds[4:6]}-{ds[6:]}/", year, day_key))

    entries.sort(key=lambda x: (x[2], x[3]), reverse=True)

    current_year = None
    for label, href, year, _order in entries:
        if current_year != year:
            if current_year is not None:
                lines.append("")
            current_year = year
            lines.append(f"## {year}")
        lines.append(f"- [{label}]({href})")

    ARCHIVES_MD.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")

# ---------- Main ----------

def main():
    # Nettoyage des anciens posts pour éviter les résidus
    if POSTS_DIR.exists():
        shutil.rmtree(POSTS_DIR)

    weekly = find_weekly_exports()
    legacy = find_legacy_exports()

    if not weekly and not legacy:
        raise SystemExit("Aucun export trouvé. Lance d'abord: python main.py")

    # Génère les posts
    for week_label, _dir, smd, sel in weekly:
        build_post_week(week_label, smd, sel)
    for date_str, _dir, smd, sel in legacy:
        build_post_legacy(date_str, smd, sel)

    # Pages globales
    write_index(weekly, legacy, max_cards=12)
    write_archives(weekly, legacy)

    print("OK: site reconstruit → docs/index.md, docs/archives.md, docs/posts/*.md")

if __name__ == "__main__":
    main()