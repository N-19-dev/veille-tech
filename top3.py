# top3.py
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
import yaml

def main(config_path="config.yaml"):
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    db_path = cfg["storage"]["sqlite_path"]
    lookback_days = int(cfg.get("summary", {}).get("lookback_days", cfg.get("crawl", {}).get("lookback_days", 7)))

    min_ts = int((datetime.now(tz=timezone.utc) - timedelta(days=lookback_days)).timestamp())

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    rows = cur.execute("""
        SELECT title, url, source_name, category_key, llm_score, published_ts
        FROM items
        WHERE published_ts >= ? AND llm_score IS NOT NULL
        ORDER BY llm_score DESC, published_ts DESC
        LIMIT 3
    """, (min_ts,)).fetchall()
    con.close()

    out_dir = Path(cfg.get("export", {}).get("out_dir", "export"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_md = out_dir / f"top3_{datetime.now().strftime('%Y%m%d')}.md"

    lines = [f"# 🏆 Top 3 — Semaine du {datetime.now().strftime('%Y-%m-%d')}\n"]
    if not rows:
        lines.append("_Aucun article scoré cette semaine._\n")
    else:
        for (title, url, source, cat, score, ts) in rows:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            lines.append(f"- [{title}]({url}) — {source} · {dt} · **{score}/100**  ")
            lines.append(f"  _Catégorie_: `{cat}`\n")

    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"[done] Export Top 3: {out_md}")

if __name__ == "__main__":
    main()