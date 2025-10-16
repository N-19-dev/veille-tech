# analyze_llm.py — IA via API OpenAI-compatible (Groq)
# - lit les items récents dans veille.db
# - score chaque item (0..100) + labels + notes
# - met à jour la DB (colonnes llm_*)
# - exporte une sélection filtrée (score >= threshold)
# - retries + logs + option --limit
#
# Dépendances: openai==1.50.2, pyyaml
import re
import asyncio
import functools
import json
import os
import random
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

import yaml
from openai import OpenAI

# ---------- Polyfill: asyncio.to_thread pour Python < 3.9 ----------
async def _to_thread(func, /, *args, **kwargs):
    loop = asyncio.get_running_loop()
    pfunc = functools.partial(func, *args, **kwargs)
    return await loop.run_in_executor(None, pfunc)

# ---------- DB helpers ----------
DB_ALTER = [
    "ALTER TABLE items ADD COLUMN llm_score INTEGER",
    "ALTER TABLE items ADD COLUMN llm_labels TEXT",
    "ALTER TABLE items ADD COLUMN llm_notes TEXT",
]

@contextmanager
def db_conn(path: str):
    conn = sqlite3.connect(path)
    try:
        yield conn
    finally:
        conn.commit()
        conn.close()

def ensure_llm_columns(db_path: str):
    with db_conn(db_path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(items)").fetchall()}
        for stmt in DB_ALTER:
            col = stmt.split(" ADD COLUMN ")[1].split()[0]
            if col not in cols:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError:
                    pass

def fetch_items_to_score(db_path: str, window_start_ts: int, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    with db_conn(db_path) as conn:
        sql = """
            SELECT id, url, title, summary, content, source_name, category_key, published_ts, llm_score
            FROM items
            WHERE published_ts >= ?
            ORDER BY published_ts DESC
        """
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = conn.execute(sql, (window_start_ts,)).fetchall()
        items = []
        for r in rows:
            items.append(dict(
                id=r[0], url=r[1], title=r[2], summary=r[3] or "",
                content=r[4] or "", source_name=r[5], category_key=r[6],
                published_ts=r[7], llm_score=r[8]
            ))
        return items

def update_item_score(db_path: str, item_id: str, score: Optional[int], labels: List[str], notes: str):
    with db_conn(db_path) as conn:
        conn.execute("""
            UPDATE items
            SET llm_score = ?, llm_labels = ?, llm_notes = ?
            WHERE id = ?
        """, (score, json.dumps(labels, ensure_ascii=False), notes, item_id))

def to_markdown(groups: Dict[str, List[Dict[str, Any]]]) -> str:
    lines = [f"# Veille Tech — Sélection IA du {datetime.now().strftime('%Y-%m-%d')}\n"]
    for cat, items in groups.items():
        if not items:
            continue
        lines.append(f"## {cat}\n")
        for it in items:
            dt = datetime.fromtimestamp(it['published_ts'], tz=timezone.utc).strftime("%Y-%m-%d")
            score = it.get("llm_score", "?")
            try:
                labels_list = json.loads(it.get("llm_labels") or "[]")
            except Exception:
                labels_list = []
            labels = ", ".join(labels_list)
            lines.append(f"- [{it['title']}]({it['url']}) — {it['source_name']} · {dt} · **{score}/100**")
            if labels:
                lines.append(f"  - _Labels_: {labels}")
            if it.get("llm_notes"):
                lines.append(f"  - {it['llm_notes'][:280]}{'…' if len(it['llm_notes'])>280 else ''}")
        lines.append("")
    return "\n".join(lines)

def group_filtered(db_path: str, min_ts: int, threshold: int) -> Dict[str, List[Dict[str, Any]]]:
    with db_conn(db_path) as conn:
        rows = conn.execute("""
            SELECT url, title, summary, published_ts, source_name, category_key, llm_score, llm_labels, llm_notes
            FROM items
            WHERE published_ts >= ? AND llm_score >= ?
            ORDER BY published_ts DESC
        """, (min_ts, threshold)).fetchall()
        out: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            item = dict(
                url=r[0], title=r[1], summary=r[2], published_ts=r[3],
                source_name=r[4], category_key=r[5], llm_score=r[6],
                llm_labels=r[7], llm_notes=r[8],
            )
            out.setdefault(item["category_key"], []).append(item)
        return out
    

def _strip_weird_chars(md: str) -> str:
    # enlève le caractère ¶ et normalise les espaces
    md = md.replace("¶", "")
    # uniformise "A creuser" / "À creuser"
    md = re.sub(r"(?i)à\s*creuser\s*:?$", "**À creuser :**", md, flags=re.MULTILINE)
    md = re.sub(r"(?i)à\s*creuser\s*:\s*", "**À creuser :**\n", md)
    return md.strip()

def _normalize_creuser_lists(block: str) -> str:
    """
    Transforme 'À creuser : * url * url' en:
    **À creuser :**
    - url
    - url
    """
    lines = []
    for raw in block.splitlines():
      if "**À creuser :**" in raw:
          # récupère tout ce qui suit sur la même ligne (liens séparés par * ou •)
          after = raw.split("**À creuser :**", 1)[1].strip()
          links = re.split(r"\s*[\*\u2022]\s*", after) if after else []
          lines.append("**À creuser :**")
          for lk in links:
              lk = lk.strip(" -•*")
              if not lk:
                  continue
              # si c'est un URL brut, préfixe en puce
              if re.match(r"^https?://", lk):
                  lines.append(f"- {lk}")
              else:
                  # déjà en Markdown ? garde en puce
                  lines.append(f"- {lk}")
      else:
          lines.append(raw)
    return "\n".join(lines)

def ensure_all_sections_ordered(md: str, expected_titles: list[str], placeholder: str) -> str:
    """
    - Garde '## 🟦 Aperçu général de la semaine' en tête (si présent, sinon on ne force pas).
    - Réordonne / renomme les sections H2 selon expected_titles
      (si une section manque, on ajoute 'Rien d’important cette semaine.').
    - Nettoie les 'À creuser' mal formatés.
    """
    md = _strip_weird_chars(md)

    # Sépare par sections H2
    sections = re.split(r"(?m)^\s*##\s+", md)
    heads = re.findall(r"(?m)^\s*##\s+(.+)$", md)

    # Reconstruit un dict {title: content}
    content_by_title = {}
    if sections:
        # si le doc commence par un contenu avant la 1re H2, on le garde comme 'prelude'
        prelude = sections[0].strip()
        for h, body in zip(heads, sections[1:]):
            # nettoie le corps + normalise les listes "À creuser"
            body = _normalize_creuser_lists(body.strip())
            # supprime un éventuel titre redondant en 1ère ligne
            body = re.sub(r"(?m)^\s*#{1,6}\s+.*$", "", body, count=1).strip()
            content_by_title[h.strip()] = body

    # Récupère et fixe l'overview
    overview_key = "🟦 Aperçu général de la semaine"
    overview_md = content_by_title.get(overview_key, "")
    # fallback: si l'IA a écrit "Aperçu général..." sans emoji, essaye de le retrouver
    if not overview_md:
        for k in list(content_by_title.keys()):
            if "aperçu" in k.lower() and "semaine" in k.lower():
                overview_md = content_by_title.pop(k, "")
                break

    # Construit le document final
    final = []
    if overview_md:
        final.append(f"## {overview_key}\n\n{overview_md}")
    else:
        # si tu veux forcer un bloc overview vide :
        final.append(f"## {overview_key}\n\n_Résumé indisponible cette semaine._")

    # Ajoute les sections dans l'ordre exact des titres attendus
    for title in expected_titles:
        body = None
        # essaie match exact
        if title in content_by_title:
            body = content_by_title[title]
        else:
            # essaie match approx: retire emojis/accents pour comparer
            def simpl(s): return re.sub(r"[\W_]+", " ", s, flags=re.UNICODE).lower().strip()
            stitle = simpl(title)
            for k, v in list(content_by_title.items()):
                if simpl(k) == stitle or stitle in simpl(k):
                    body = v
                    break

        if body and body.strip():
            final.append(f"## {title}\n\n{body.strip()}")
        else:
            final.append(f"## {title}\n\n_{placeholder}_")

    return "\n\n".join(final).strip() + "\n"

# ---------- Prompting ----------
ANALYSIS_SYSTEM_PROMPT = """Tu es un assistant de veille techno pour data/analytics/BI/ML en français.
Objectif: marquer les articles vraiment utiles pour un·e data engineer/analyst/architect.

Définition de "utile":
- Annonce officielle importante (GA/Preview, breaking changes, deprecations)
- Release notes substantielles (performance/changements majeurs)
- Benchmarks ou études avec chiffres actionnables
- Guides/tutoriels étape-par-étape de bonne qualité
- Sécurité: CVE, patchs critiques
- Outils cloud/DB/ETL/Orchestration/BI listés dans notre périmètre
- Évite: marketing fluff, récaps trop génériques, contenu très redondant
- Garde toutes les sections thématiques listées dans le contexte; si une section n’a rien de notable, écris une ligne “Rien d’important cette semaine.”
- Utilise exactement ces titres de sections (H2) dans cet ordre. Si une section n’a rien de notable, écris “Rien d’important cette semaine.” :

Réponds au format JSON strict:
{
  "score": int entre 0 et 100,
  "labels": [2 à 5 mots-clés max],
  "notes": "2 phrases max. Pourquoi c'est (in)utile et pour qui?"
}
Ne commente rien d'autre.
"""

def build_user_prompt(item: Dict[str, Any]) -> str:
    content = item["content"] or item["summary"] or ""
    content = content[:3000]  # limite le contexte
    return f"""Titre: {item['title']}
Source: {item['source_name']}
Catégorie: {item['category_key']}
URL: {item['url']}
Publié UTC: {datetime.fromtimestamp(item['published_ts'], tz=timezone.utc).isoformat()}

Résumé+extrait:
{content}
"""

def safe_parse_json(reply: str) -> Dict[str, Any]:
    txt = reply.strip()
    if txt.startswith("```"):
        txt = txt.strip("` \n")
        if txt.lower().startswith("json"):
            txt = txt.split("\n", 1)[-1]
    start = txt.find("{")
    end = txt.rfind("}")
    if start != -1 and end != -1 and end > start:
        txt = txt[start:end+1]
    try:
        data = json.loads(txt)
        out = {
            "score": int(data.get("score", 50)),
            "labels": data.get("labels") or [],
            "notes": data.get("notes") or ""
        }
        return out
    except Exception:
        return {"score": 50, "labels": [], "notes": reply[:240]}

# ---------- Scoring via OpenAI-compatible API (Groq) ----------
async def score_items_openai(items: List[Dict[str, Any]], base_url: str, api_key_env: str,
                             model: str, temperature: float, max_tokens: int, concurrent: int, db_path: str):
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise RuntimeError(f"Variable d'environnement {api_key_env} manquante. Fais: export {api_key_env}='sk_groq_...'")

    client = OpenAI(base_url=base_url, api_key=api_key)
    sem = asyncio.Semaphore(max(1, int(concurrent) or 1))

    async def score_one(idx: int, it: Dict[str, Any]):
        system = ANALYSIS_SYSTEM_PROMPT
        user = build_user_prompt(it)
        delay = 1.5
        last_err = None
        async with sem:
            for attempt in range(4):  # 1 essai + 3 retries
                try:
                    # Appel sync dans un thread (compat Py3.8)
                    resp = await _to_thread(
                        client.chat.completions.create,
                        model=model,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user}
                        ],
                        temperature=float(temperature),
                        max_tokens=int(max_tokens),
                    )
                    reply = resp.choices[0].message.content or ""
                    data = safe_parse_json(reply)
                    score = int(data.get("score", 50))
                    labels = data.get("labels") or []
                    notes = data.get("notes") or ""
                    update_item_score(db_path, it["id"], score, labels, notes)
                    if (idx + 1) % 5 == 0 or attempt > 0:
                        print(f"[ok] {idx+1}/{len(items)} — score={score} — {it['title'][:80]}")
                    return
                except Exception as e:
                    last_err = e
                    print(f"[retry] {idx+1}/{len(items)} — tentative {attempt+1} — err: {e}")
                    await asyncio.sleep(delay)
                    delay *= 2
            update_item_score(db_path, it["id"], None, [], f"LLM error: {last_err}")
            print(f"[err] {idx+1}/{len(items)} — {it['title'][:80]} — {last_err}")

    await asyncio.gather(*[score_one(i, it) for i, it in enumerate(items)])

# ---------- Weekly summary helper (Groq / OpenAI-compatible) ----------
def fetch_items_for_summary(db_path: str, min_ts: int, min_score: int) -> List[Dict[str, Any]]:
    with db_conn(db_path) as conn:
        rows = conn.execute("""
            SELECT title, url, source_name, category_key, summary, content, published_ts, llm_score
            FROM items
            WHERE published_ts >= ? AND COALESCE(llm_score,0) >= ?
            ORDER BY llm_score DESC, published_ts DESC
        """, (min_ts, min_score)).fetchall()
        out = []
        for r in rows:
            out.append(dict(
                title=r[0], url=r[1], source=r[2], category=r[3],
                summary=r[4] or "", content=r[5] or "",
                published_ts=r[6], llm_score=r[7]
            ))
        return out

def build_highlights(items: List[Dict[str, Any]], max_items: int = 12) -> str:
    """
    Sélectionne les items les plus forts toutes catégories confondues
    (tri score DESC puis date DESC) pour aider l'IA à rédiger l'aperçu général.
    """
    top = sorted(
        items,
        key=lambda x: (int(x.get("llm_score") or 0), int(x["published_ts"])),
        reverse=True
    )[:max_items]
    lines = ["# Highlights (toutes catégories)"]
    for it in top:
        dt = datetime.fromtimestamp(it["published_ts"], tz=timezone.utc).strftime("%Y-%m-%d")
        lines.append(f"- [{it['title']}]({it['url']}) — {it['source']} · {dt} · score {it.get('llm_score','?')}")
    return "\n".join(lines)

def ensure_all_sections(md: str, categories: "list[dict]", placeholder: str = "Rien d’important cette semaine.") -> str:
    """
    Vérifie que chaque catégorie du config a une section H2.
    Si absente, on ajoute la section avec un message par défaut.
    """
    out = md.rstrip() + "\n"
    for cat in categories:
        title = cat.get("title") or cat.get("key")
        # On cherche une ligne '## <Titre>'
        pattern = rf"(?mi)^\s*##\s+{re.escape(title)}\s*$"
        if not re.search(pattern, out):
            out += f"\n\n## {title}\n\n_{placeholder}_\n"
    return out

def build_summary_context(items: List[Dict[str, Any]], links_per_section: int) -> str:
    """
    Construit un contexte compact: pour chaque catégorie, garde les meilleurs items (score/date).
    """
    from collections import defaultdict
    buckets = defaultdict(list)
    for it in items:
        buckets[it["category"]].append(it)
    # top-N par catégorie
    lines = []
    for cat, lst in buckets.items():
        lst = sorted(lst, key=lambda x: (x["llm_score"], x["published_ts"]), reverse=True)[:links_per_section]
        lines.append(f"## {cat}")
        for it in lst:
            lines.append(f"- [{it['title']}]({it['url']}) · {it['source']} · score {it['llm_score']}")
            if it["summary"]:
                lines.append(f"  - {it['summary'][:200]}{'…' if len(it['summary'])>200 else ''}")
    return "\n".join(lines)

SUMMARY_SYSTEM_PROMPT = """Tu es un assistant de veille techno (data/analytics/BI/ML) en français.
Objectif: produire un résumé hebdomadaire clair, actionnable, et concis pour un public data engineer/analyst/architect.

Structure impérative de la réponse (Markdown):
1) "## 🟦 Aperçu général de la semaine"
   - 1 à 2 paragraphes courts OU 5–8 puces max
   - Synthétise les tendances transversales (GA/Preview, breaking changes, perfs, sécurité, guides marquants)
2) Sections par thèmes (ex: Bases de données, Orchestration, Transformation SQL, Data Viz, Cloud, IA/ML…)
   - 3–6 puces max par thème, phrases courtes, impacts concrets
   - Termine CHAQUE section par une ligne "**À creuser :**" listant jusqu'à N liens fournis (liste Markdown)
Règles:
- Français clair et professionnel, sans fluff ni redondance.
- Ne pas inventer de faits ni de liens: s'appuyer uniquement sur le contexte fourni.
- Ne pas encapsuler la réponse dans des blocs de code.
"""

async def generate_weekly_summary_openai(
    base_url: str,
    api_key_env: str,
    model: str,
    context_md: str,
    max_sections: int,
    expected_titles: List[str],
    highlights_md: Optional[str] = None,
) -> str:
    """
    Utilise l'API OpenAI-compatible (Groq) pour produire un résumé Markdown
    avec un bloc 'Aperçu général' puis les sections thématiques EXACTEMENT
    dans l'ordre 'expected_titles'. Les sections vides seront gérées ensuite
    par le post-traitement ensure_all_sections_ordered(...).
    """
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise RuntimeError(f"Variable d'environnement {api_key_env} manquante.")
    client = OpenAI(base_url=base_url, api_key=api_key)

    high_block = f"[HIGHLIGHTS]\n{highlights_md}\n\n" if highlights_md else ""
    section_list = "\n".join(f"- {t}" for t in expected_titles)

    user_prompt = f"""Voici une sélection d'articles de la semaine passée (déjà filtrés et scorés).
Commence par un **Aperçu général de la semaine** à partir des *Highlights*, puis détaille par thèmes.
Ne crée pas plus de {max_sections} sections thématiques.

Tu DOIS utiliser exactement les titres H2 suivants, dans cet ordre, et les conserver même s'il n'y a rien à dire :
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

# ---------- Main ----------
async def main(config_path: str = "config.yaml", limit: Optional[int] = None):
    # --- charge config & prépare ---
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    expected_titles = [c.get("title", c.get("key")) for c in cfg.get("categories", [])]

    db_path = cfg["storage"]["sqlite_path"]
    lookback_days = cfg.get("crawl", {}).get("lookback_days", 7)

    llm_cfg = cfg.get("llm", {})
    provider = llm_cfg.get("provider")
    temperature = float(llm_cfg.get("temperature", 0.2))
    max_tokens = int(llm_cfg.get("max_tokens", 400))
    concurrent = int(llm_cfg.get("concurrent", 1))
    threshold = int(llm_cfg.get("score_threshold", 60))

    ensure_llm_columns(db_path)

    # --- fenêtre temporelle ---
    window_start_ts = int((datetime.now(tz=timezone.utc) - timedelta(days=lookback_days)).timestamp())

    # --- items à scorer ---
    items = fetch_items_to_score(db_path, window_start_ts, limit=limit)
    print(f"[diag] items récents: {len(items)}")
    items_to_score = [it for it in items if it["llm_score"] is None]
    print(f"[diag] à scorer (llm_score IS NULL): {len(items_to_score)}")
    print(f"[diag] provider: {provider}")

    # --- scoring via LLM ---
    if items_to_score:
        if provider == "openai_compat":
            base_url = llm_cfg.get("base_url", "https://api.groq.com/openai/v1")
            api_key_env = llm_cfg.get("api_key_env", "GROQ_API_KEY")
            # Mixtral est décommissionné chez Groq -> par défaut on prend Llama 3.1 8B instant
            model = llm_cfg.get("model", "llama-3.1-8b-instant")
            await score_items_openai(
                items_to_score, base_url, api_key_env, model,
                temperature, max_tokens, concurrent, db_path
            )
        else:
            raise RuntimeError(f"Provider LLM inconnu: {provider} (attendu: 'openai_compat')")

    # --- stats post-scoring ---
    with db_conn(db_path) as conn:
        total_scored = conn.execute("SELECT COUNT(*) FROM items WHERE llm_score IS NOT NULL").fetchone()[0]
        recent_scored = conn.execute(
            "SELECT COUNT(*) FROM items WHERE published_ts >= ? AND llm_score IS NOT NULL",
            (window_start_ts,)
        ).fetchone()[0]
        errors = conn.execute("SELECT COUNT(*) FROM items WHERE llm_notes LIKE 'LLM error:%'").fetchone()[0]
    print(f"[diag] items scorés (total): {total_scored}, scorés (fenêtre): {recent_scored}, erreurs: {errors}")

    # --- export sélection IA ---
    groups = group_filtered(db_path, window_start_ts, threshold)
    out_dir = Path(cfg.get("export", {}).get("out_dir", "export"))
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"ai_selection_{datetime.now().strftime('%Y%m%d')}.json"
    md_path = out_dir / f"ai_selection_{datetime.now().strftime('%Y%m%d')}.md"
    json_path.write_text(json.dumps(groups, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(to_markdown(groups), encoding="utf-8")
    kept = sum(len(v) for v in groups.values())
    print(f"[done] Export IA: {kept} items retenus ≥ {threshold}")
    print(f" - {json_path}\n - {md_path}")

    # --- résumé hebdomadaire IA (optionnel) ---
    sum_cfg = cfg.get("summary", {})
    if sum_cfg.get("enabled", True) and kept > 0:
        sum_lookback_days = int(sum_cfg.get("lookback_days", lookback_days))
        sum_min_score = int(sum_cfg.get("min_score", threshold))
        max_sections = int(sum_cfg.get("max_sections", 8))
        links_per = int(sum_cfg.get("links_per_section", 5))

        sum_window_start_ts = int((datetime.now(tz=timezone.utc) - timedelta(days=sum_lookback_days)).timestamp())
        sum_items = fetch_items_for_summary(db_path, sum_window_start_ts, sum_min_score)

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

                # Post-traitement : titres fixes, ordre imposé, sections vides
                placeholder = "Rien d’important cette semaine."
                weekly_md = ensure_all_sections_ordered(
                    weekly_md,
                    expected_titles=expected_titles,
                    placeholder=placeholder
                )

                summary_path = out_dir / f"ai_summary_{datetime.now().strftime('%Y%m%d')}.md"
                summary_path.write_text(weekly_md, encoding="utf-8")
                print(f"[done] Résumé hebdo IA: {summary_path}")
        else:
            print("[info] Aucun item éligible pour le résumé hebdo (fenêtre/score).")


if __name__ == "__main__":
    import argparse, asyncio
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--limit", type=int, default=None, help="Nombre max d'items à scorer (debug)")
    args = p.parse_args()

    asyncio.run(main(args.config, limit=args.limit))