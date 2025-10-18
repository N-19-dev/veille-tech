import json, re
from pathlib import Path
from datetime import datetime

EXPORT_DIR = Path("export")
DOCS_DIR = Path("docs")
POSTS_DIR = DOCS_DIR / "posts"
INDEX_MD = DOCS_DIR / "index.md"

def find_exports():
    sums = sorted(EXPORT_DIR.glob("ai_summary_*.md"))
    sels = {p.stem[-8:]: p for p in sorted(EXPORT_DIR.glob("ai_selection_*.json"))}
    pairs = []
    for smd in sums:
        date = smd.stem[-8:]
        pairs.append((date, smd, sels.get(date)))
    return sorted(pairs, key=lambda t: t[0], reverse=True)

def human_date(yyyymmdd: str) -> str:
    return datetime.strptime(yyyymmdd, "%Y%m%d").strftime("%d %B %Y")

def build_post(date_str: str, summary_md: Path, selection_json: Path):
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    out = POSTS_DIR / f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}.md"

    # Lire le summary IA
    body = summary_md.read_text(encoding="utf-8")
    # Nettoyage léger si besoin (évite les headings trop gros en H1)
    body = re.sub(r"^#\s+", "## ", body.strip(), flags=re.MULTILINE)

    # Lire la sélection (facultatif)
    links_md = ""
    if selection_json and selection_json.exists():
        data = json.loads(selection_json.read_text(encoding="utf-8"))
        # data = { category_key: [ {title, url, source_name, published_ts, llm_score, ...}, ... ] }
        lines = ["\n---\n", "### 🔗 Liens à creuser (sélection IA)"]
        total = 0
        for cat, items in data.items():
            if not items:
                continue
            lines.append(f"\n#### {cat}")
            for it in items[:10]:
                total += 1
                score = it.get("llm_score", "?")
                src = it.get("source_name","")
                title = it.get("title","")
                url = it.get("url","")
                lines.append(f"- [{title}]({url}) — {src} · **{score}/100**")
        if total == 0:
            lines.append("\n_(Aucune entrée au-dessus du seuil cette semaine.)_")
        links_md = "\n".join(lines)

    # Front matter simple (Material utilise le premier H1 comme titre)
    final = []
    final.append(f"# 🧠 Veille — {human_date(date_str)}")
    final.append("")
    final.append(body)
    if links_md:
        final.append(links_md)

    out.write_text("\n".join(final).strip() + "\n", encoding="utf-8")
    return out

def rebuild_index(pairs):
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    cards = []
    cards.append("# Veille Tech — IA Summaries\n")
    cards.append("_Un résumé hebdomadaire synthétisé par l’IA, avec les meilleurs liens à creuser._\n")

    for date, smd, _sel in pairs:
        slug = f"{date[:4]}-{date[4:6]}-{date[6:]}"
        cards.append(f"""
<div class="post-card">
  <div class="post-meta">{human_date(date)}</div>
  <h3><a href="posts/{slug}.md">Semaine du {human_date(date)}</a></h3>
  <p>Résumé IA + sélection de liens utiles.</p>
</div>
""".strip())

    INDEX_MD.write_text("\n\n".join(cards) + "\n", encoding="utf-8")

def main():
    pairs = find_exports()
    if not pairs:
        raise SystemExit("Aucun export trouvé dans export/. Lance d'abord: python main.py")
    for date, smd, sel in pairs:
        build_post(date, smd, sel)
    rebuild_index(pairs)
    print(f"OK: {len(pairs)} posts générés → docs/posts/*.md ; index mis à jour.")

if __name__ == "__main__":
    main()