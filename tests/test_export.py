# tests/test_export.py
from datetime import datetime, timezone
from veille_tech import to_markdown, Category

def test_to_markdown_formatting():
    categories_by_key = {
        "db_sql_olap": Category(key="db_sql_olap", title="🔢 Bases de données & OLAP",
                                keywords=["postgres", "mysql"])
    }
    groups = {
        "db_sql_olap": [
            {
                "url": "https://example.com/blog/duckdb-1-0",
                "title": "DuckDB 1.0",
                "summary": "Big release",
                "published_ts": int(datetime(2025, 10, 14, 9, 0, tzinfo=timezone.utc).timestamp()),
                "source_name": "DuckDB Blog",
            }
        ]
    }
    md = to_markdown(groups, categories_by_key)
    assert "# Veille Tech — Digest" in md
    assert "## 🔢 Bases de données & OLAP" in md
    assert "- [DuckDB 1.0](https://example.com/blog/duckdb-1-0)" in md