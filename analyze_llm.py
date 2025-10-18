# analyze_llm.py
# Scoring LLM (Groq OpenAI-compat) + sélection + résumé hebdo avec sections fixes
# Exporte dans export/<YYYYwWW>/ :
#  - ai_selection.json / ai_selection.md
#  - ai_summary.md (avec Top 3 en tête)
#  - top3.md
# (et crée/actualise export/latest → export/<YYYYwWW>)

import os
import re
import json
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

import yaml
from openai import OpenAI

from veille_tech import db_conn, week_bounds  # même fenêtre semaine

# -----------------------
# DB helpers
# -----------------------

def ensure_llm_columns(db_path: str):
    with db_conn(db_path) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(items)").fetchall()]
        if "llm_score" not in cols:
            conn.execute("ALTER TABLE items ADD COLUMN llm_score INTEGER")
        if "llm_notes" not in cols:
            conn.execute("ALTER TABLE items ADD COLUMN llm_notes TEXT")

def fetch_items_to_score(db_path: str, min_ts: int, max_ts: int, limit: Optional[int] = None):
    with db_conn(db_path) as conn:
        q = """
        SELECT id, url, title, summary, content, published_ts, source_name, category_key, llm_score
        FROM items
        WHERE published_ts >= ? AND published_ts < ?
        ORDER BY published_ts DESC
        """
        params = [min_ts, max_ts]
        if limit:
            q += " LIMIT ?"
            params.append(limit)
        rows = conn.execute(q, params).fetchall()
    keys = ["id","url","title","summary","content","published_ts","source_name","category_key","llm_score"]
    return [dict(zip(keys, r)) for r in rows]

def group_filtered(db_path: str, min_ts: int, max_ts: int, min_score: int):
    with db_conn(db_path) as conn:
        cats = [r[0] for r in conn.execute("SELECT DISTINCT category_key FROM items")]
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for c in cats:
            rows = conn.execute("""
                SELECT url, title, summary, published_ts, source_name, llm_score
                FROM items
                WHERE category_key=? AND published_ts>=? AND published_ts<? AND COALESCE(llm_score,0) >= ?
                ORDER BY llm_score DESC, published_ts DESC
            """, (c, min_ts, max_ts, min_score)).fetchall()
            groups[c] = [dict(url=r[0], title=r[1], summary=r[2], published_ts=r[3], source_name=r[4], llm_score=r[5]) for r in rows]
        return groups

def fetch_items_for_summary(db_path: str, min_ts: int, max_ts: int, min_score: int):
    with db_conn(db_path) as conn:
        rows = conn.execute("""
            SELECT title, url, source_name, category_key, llm_score, published_ts
            FROM items
            WHERE published_ts >= ? AND published_ts < ? AND COALESCE(llm_score,0) >= ?
            ORDER BY llm_score DESC, published_ts DESC
        """, (min_ts, max_ts, min_score)).fetchall()
    keys = ["title","url","source","category","llm_score","published_ts"]
    return [dict(zip(keys, r)) for r in rows]

def to_markdown(groups: Dict[str, List[Dict[str, Any]]]) -> str:
    lines = ["# Sélection IA — Semaine\n"]
    for key, items in groups.items():
        if not items: continue
        lines.append(f"## {key}\n")
        for it in items:
            dt = datetime.fromtimestamp(it["published_ts"], tz=timezone.utc).strftime("%Y-%m-%d")
            score = it.get("llm_score", "?")
            lines.append(f"- [{it['title']}]({it['url']}) — {it['source_name']} · {dt} · **{score}/100**")
        lines.append("")
    return "\n".join(lines)

# -----------------------
# Scoring (Groq OpenAI-compat)
# -----------------------

try:
    _to_thread = asyncio.to_thread  # py3.9+
except AttributeError:
    async def _to_thread(fn, *a, **k):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: fn(*a, **k))

SCORE_SYSTEM_PROMPT = (
    "Tu es un assistant de veille. Donne un score d'utilité (0-100) pour un public data/analytics/BI/ML. "
    "Réponds UNIQUEMENT par un entier, sans texte."
)

def build_scoring_prompt(it: Dict[str, Any]) -> str:
    base = f"""Titre: {it['title']}
Source: {it['source_name']}
Catégorie: {it['category_key']}
Résumé: {it.get('summary','')[:500]}
Contenu: { (it.get('content') or '')[:1200] }
"""
    return base + "\nScore entre 0 et 100 ? Réponds par un entier."

async def score_items_openai(items: List[Dict[str, Any]], base_url: str, api_key_env: str,
                             model: str, temperature: float, max_tokens: int,
                             concurrent: int, db_path: str):
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise RuntimeError(f"Variable d'environnement {api_key_env} manquante.")
    client = OpenAI(base_url=base_url, api_key=api_key)

    sem = asyncio.Semaphore(concurrent)

    async def one(it: Dict[str, Any]):
        async with sem:
            prompt = build_scoring_prompt(it)
            try:
                resp = await _to_thread(
                    client.chat.completions.create,
                    model=model,
                    messages=[
                        {"role": "system", "content": SCORE_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                text = (resp.choices[0].message.content or "").strip()
                m = re.search(r"(\d{1,3})", text)
                score = max(0, min(100, int(m.group(1)))) if m else None
                note = None
            except Exception as e:
                score = None
                note = f"LLM error: {e}"

            with db_conn(db_path) as conn:
                conn.execute(
                    "UPDATE items SET llm_score=?, llm_notes=? WHERE id=?",
                    (score, note, it["id"])
                )

    await asyncio.gather(*[one(it) for it in items])

# -----------------------
# Summary helpers
# -----------------------

def build_summary_context(items: List[Dict[str, Any]], links_per_section: int) -> str:
    by_cat: Dict[str, List[Dict[str, Any]]] = {}
    for it in items:
        by_cat.setdefault(it["category"], []).append(it)
    lines = []
    for cat, arr in by_cat.items():
        lines.append(f"## {cat}")
        for it in sorted(arr, key=lambda x: (x.get("llm_score", 0), x["published_ts"]), reverse=True)[:links_per_section]:
            dt = datetime.fromtimestamp(it["published_ts"], tz=timezone.utc).strftime("%Y-%m-%d")
            sc = it.get("llm_score","?")
            lines.append(f"- [{it['title']}]({it['url']}) — {it['source']} · {dt} · **{sc}/100**")
        lines.append("")
    return "\n".join(lines).strip()

def build_highlights(items: List[Dict[str, Any]], max_items: int = 12) -> str:
    top = sorted(items, key=lambda x: (int(x.get("llm_score") or 0), int(x["published_ts"])), reverse=True)[:max_items]
    lines = ["# Highlights (toutes catégories)"]
    for it in top:
        dt = datetime.fromtimestamp(it["published_ts"], tz=timezone.utc).strftime("%Y-%m-%d")
        lines.append(f"- [{it['title']}]({it['url']}) — {it['source']} · {dt} · score {it.get('llm_score','?')}")
    return "\n".join(lines)

SUMMARY_SYSTEM_PROMPT = """Tu es un assistant de veille techno (data/analytics/BI/ML) en français.
Objectif: produire un résumé hebdomadaire clair, actionnable, concis.

Structure (Markdown):
1) "## 🟦 Aperçu général de la semaine"
   - 1–2 paragraphes ou 5–8 puces max (tendances transversales)
2) Sections par thèmes (mêmes titres que fournis), 3–6 puces max
   - Termine CHAQUE section par "**À creuser :**" avec quelques liens si disponibles

Règles:
- Français pro, concis. Pas d'invention: s'appuyer sur le contexte donné.
- Ne pas mettre la réponse dans un bloc de code.
"""

def _strip_weird_chars(md: str) -> str:
    md = md.replace("¶", "")
    md = re.sub(r"(?i)à\s*creuser\s*:?$", "**À creuser :**", md, flags=re.MULTILINE)
    md = re.sub(r"(?i)à\s*creuser\s*:\s*", "**À creuser :**\n", md)
    return md.strip()

def _normalize_creuser_lists(block: str) -> str:
    lines = []
    for raw in block.splitlines():
        if "**À creuser :**" in raw:
            after = raw.split("**À creuser :**", 1)[1].strip()
            links = re.split(r"\s*[\*\u2022]\s*", after) if after else []
            lines.append("**À creuser :**")
            for lk in links:
                lk = lk.strip(" -•*")
                if not lk: continue
                lines.append(f"- {lk}")
        else:
            lines.append(raw)
    return "\n".join(lines)

def ensure_all_sections_ordered(md: str, expected_titles: List[str], placeholder: str) -> str:
    md = _strip_weird_chars(md)
    sections = re.split(r"(?m)^\s*##\s+", md)
    heads = re.findall(r"(?m)^\s*##\s+(.+)$", md)
    content_by_title: Dict[str, str] = {}
    if sections:
        for h, body in zip(heads, sections[1:]):
            body = _normalize_creuser_lists(body.strip())
            body = re.sub(r"(?m)^\s*#{1,6}\s+.*$", "", body, count=1).strip()
            content_by_title[h.strip()] = body

    overview_key = "🟦 Aperçu général de la semaine"
    overview_md = content_by_title.get(overview_key, "")
    if not overview_md:
        for k in list(content_by_title.keys()):
            if "aperçu" in k.lower() and "semaine" in k.lower():
                overview_md = content_by_title.pop(k, ""); break

    final = []
    if overview_md:
        final.append(f"## {overview_key}\n\n{overview_md}")
    else:
        final.append(f"## {overview_key}\n\n_Résumé indisponible cette semaine._")

    def simpl(s: str) -> str:
        return re.sub(r"[\W_]+", " ", s, flags=re.UNICODE).lower().strip()

    for title in expected_titles:
        body = None
        if title in content_by_title:
            body = content_by_title[title]
        else:
            stitle = simpl(title)
            for k,v in list(content_by_title.items()):
                if simpl(k) == stitle or stitle in simpl(k):
                    body = v; break
        if body and body.strip():
            final.append(f"## {title}\n\n{body.strip()}")
        else:
            final.append(f"## {title}\n\n_{placeholder}_")

    return "\n\n".join(final).strip() + "\n"

# -----------------------
# Top K
# -----------------------

def build_top_k_md(items: List[Dict[str, Any]], k: int = 3) -> str:
    """
    Construit une section Markdown 'Top k' à partir d'une liste d'items scorés.
    Tri: score desc puis date desc.
    """
    if not items:
        return "## 🏆 Top 3 de la semaine\n\n_Aucun article cette semaine._\n"

    top = sorted(
        items,
        key=lambda x: (int(x.get("llm_score") or 0), int(x["published_ts"])),
        reverse=True
    )[:k]

    lines = ["## 🏆 Top 3 de la semaine", ""]
    for i, it in enumerate(top, start=1):
        dt = datetime.fromtimestamp(it["published_ts"], tz=timezone.utc).strftime("%Y-%m-%d")
        title = it["title"]
        url = it["url"]
        src = it["source"]
        score = it.get("llm_score", "?")
        lines.append(f"- **{i}.** [{title}]({url}) — {src} · {dt} · **{score}/100**")
    lines.append("")
    return "\n".join(lines)

# -----------------------
# LLM summary (Groq)
# -----------------------

async def generate_weekly_summary_openai(
    base_url: str,
    api_key_env: str,
    model: str,
    context_md: str,
    max_sections: int,
    expected_titles: List[str],
    highlights_md: Optional[str] = None,
) -> str:
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise RuntimeError(f"Variable d'environnement {api_key_env} manquante.")
    client = OpenAI(base_url=base_url, api_key=api_key)

    high_block = f"[HIGHLIGHTS]\n{highlights_md}\n\n" if highlights_md else ""
    section_list = "\n".join(f"- {t}" for t in expected_titles)

    user_prompt = f"""Voici une sélection d'articles de la semaine (déjà filtrés et scorés).
Commence par un **Aperçu général de la semaine** à partir des *Highlights*, puis détaille par thèmes.
Ne crée pas plus de {max_sections} sections thématiques.

Tu DOIS utiliser exactement ces titres H2, dans cet ordre, et les conserver même s'il n'y a rien à dire :
{section_list}

{high_block}[CONTEXTE PAR THÈMES]
{context_md}
"""

    resp = await _to_thread(
        client.chat.completions.create,
        model=model,
        messages=[
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=1200,
    )
    return resp.choices[0].message.content or ""

# -----------------------
# MAIN
# -----------------------

async def main(config_path: str = "config.yaml", limit: Optional[int] = None):
    # --- charge config & prépare ---
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    expected_titles = [c.get("title", c.get("key")) for c in cfg.get("categories", [])]

    db_path = cfg["storage"]["sqlite_path"]

    llm_cfg = cfg.get("llm", {})
    provider = llm_cfg.get("provider")
    temperature = float(llm_cfg.get("temperature", 0.2))
    max_tokens = int(llm_cfg.get("max_tokens", 400))
    concurrent = int(llm_cfg.get("concurrent", 1))
    threshold = int(llm_cfg.get("score_threshold", 60))

    ensure_llm_columns(db_path)

    # Fenêtre semaine (Europe/Paris)
    week_offset = int(os.getenv("WEEK_OFFSET", "0"))
    week_start_ts, week_end_ts, week_label, _, _ = week_bounds("Europe/Paris", week_offset=week_offset)

    # Items à scorer
    items = fetch_items_to_score(db_path, week_start_ts, week_end_ts, limit=limit)
    print(f"[diag] items dans la semaine: {len(items)}")
    items_to_score = [it for it in items if it["llm_score"] is None]
    print(f"[diag] à scorer (llm_score IS NULL): {len(items_to_score)}")
    print(f"[diag] provider: {provider}")

    # --- scoring via LLM ---
    if items_to_score:
        if provider == "openai_compat":
            base_url = llm_cfg.get("base_url", "https://api.groq.com/openai/v1")
            api_key_env = llm_cfg.get("api_key_env", "GROQ_API_KEY")
            model = llm_cfg.get("model", "llama-3.1-8b-instant")
            await score_items_openai(items_to_score, base_url, api_key_env, model, temperature, max_tokens, concurrent, db_path)
        else:
            raise RuntimeError(f"Provider LLM inconnu: {provider} (attendu: 'openai_compat')")

    # Stats
    with db_conn(db_path) as conn:
        recent_scored = conn.execute(
            "SELECT COUNT(*) FROM items WHERE published_ts >= ? AND published_ts < ? AND llm_score IS NOT NULL",
            (week_start_ts, week_end_ts)
        ).fetchone()[0]
        errors = conn.execute("SELECT COUNT(*) FROM items WHERE llm_notes LIKE 'LLM error:%'").fetchone()[0]
    print(f"[diag] items scorés (semaine): {recent_scored}, erreurs cumulées: {errors}")

    # --- Dossier hebdo ---
    out_root = Path(cfg.get("export", {}).get("out_dir", "export"))
    week_dir = out_root / week_label
    week_dir.mkdir(parents=True, exist_ok=True)

    # Export sélection IA
    groups = group_filtered(db_path, week_start_ts, week_end_ts, threshold)
    json_path = week_dir / "ai_selection.json"
    md_path = week_dir / "ai_selection.md"
    json_path.write_text(json.dumps(groups, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(to_markdown(groups), encoding="utf-8")
    kept = sum(len(v) for v in groups.values())
    print(f"[done] Export IA (semaine {week_label}): {kept} items ≥ {threshold}")
    print(f" - {json_path}\n - {md_path}")

    # Résumé hebdo IA
    sum_cfg = cfg.get("summary", {})
    if sum_cfg.get("enabled", True) and kept > 0:
        sum_min_score = int(sum_cfg.get("min_score", threshold))
        max_sections = int(sum_cfg.get("max_sections", 8))
        links_per = int(sum_cfg.get("links_per_section", 5))

        sum_items = fetch_items_for_summary(db_path, week_start_ts, week_end_ts, sum_min_score)
        if sum_items:
            # Contexte par thèmes + highlights cross-thèmes
            context_md = build_summary_context(sum_items, links_per)
            highlights_md = build_highlights(sum_items, max_items=12)

            if provider == "openai_compat":
                base_url = llm_cfg.get("base_url", "https://api.groq.com/openai/v1")
                api_key_env = llm_cfg.get("api_key_env", "GROQ_API_KEY")
                model = llm_cfg.get("model", "llama-3.1-8b-instant")

                # Génération du résumé IA avec sections attendues
                weekly_md = await generate_weekly_summary_openai(
                    base_url=base_url,
                    api_key_env=api_key_env,
                    model=model,
                    context_md=context_md,
                    max_sections=max_sections,
                    expected_titles=expected_titles,
                    highlights_md=highlights_md,
                )
                weekly_md = ensure_all_sections_ordered(
                    weekly_md,
                    expected_titles=expected_titles,
                    placeholder="Rien d’important cette semaine."
                )

                # --- Top 3 : fichier dédié + injection dans le rapport final
                top_md = build_top_k_md(sum_items, k=3)
                top3_path = week_dir / "top3.md"
                top3_path.write_text(top_md, encoding="utf-8")
                print(f"[done] Top 3: {top3_path}")

                weekly_md = top_md + "\n" + weekly_md

                summary_path = week_dir / "ai_summary.md"
                summary_path.write_text(weekly_md, encoding="utf-8")
                print(f"[done] Résumé hebdo IA: {summary_path}")
        else:
            print("[info] Aucun item éligible pour le résumé hebdo (fenêtre/score).")

    # lien symbolique "latest" → cette semaine (best effort)
    latest = out_root / "latest"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(week_dir, target_is_directory=True)
    except Exception:
        pass

# -----------------------
# CLI
# -----------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Analyse LLM (hebdomadaire)")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--week-offset", type=int, default=None)
    args = parser.parse_args()
    if args.week_offset is not None:
        os.environ["WEEK_OFFSET"] = str(args.week_offset)
    asyncio.run(main(args.config, limit=args.limit))