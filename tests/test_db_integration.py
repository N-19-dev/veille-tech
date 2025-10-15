# tests/test_db_integration.py
# Mini test d'intégration pure DB (pas de réseau, pas d'IA) :
# - crée une DB temporaire
# - ensure_db()
# - upsert_item()
# - query_latest_by_cat() avec fenêtre temporelle

import os
import tempfile
from datetime import datetime, timezone, timedelta

from veille_tech import ensure_db, upsert_item, query_latest_by_cat

def test_db_insert_and_query():
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ensure_db(tmp)
        now_ts = int(datetime.now(tz=timezone.utc).timestamp())
        published_ts_recent = int((datetime.now(tz=timezone.utc) - timedelta(days=1)).timestamp())
        published_ts_old = int((datetime.now(tz=timezone.utc) - timedelta(days=30)).timestamp())

        # item récent
        upsert_item(tmp, {
            "id": "id-recent",
            "url": "https://example.com/blog/recent",
            "title": "Recent post",
            "summary": "useful summary",
            "content": "longer content",
            "published_ts": published_ts_recent,
            "source_name": "Example Blog",
            "category_key": "db_sql_olap",
            "created_ts": now_ts
        })
        # item ancien
        upsert_item(tmp, {
            "id": "id-old",
            "url": "https://example.com/blog/old",
            "title": "Old post",
            "summary": "old summary",
            "content": "old content",
            "published_ts": published_ts_old,
            "source_name": "Example Blog",
            "category_key": "db_sql_olap",
            "created_ts": now_ts
        })

        window_start_ts = int((datetime.now(tz=timezone.utc) - timedelta(days=7)).timestamp())
        groups = query_latest_by_cat(tmp, limit_per_cat=10, min_ts=window_start_ts)

        # On doit retrouver seulement l'item récent dans la catégorie
        assert "db_sql_olap" in groups
        items = groups["db_sql_olap"]
        assert len(items) == 1
        assert items[0]["title"] == "Recent post"
    finally:
        try:
            os.remove(tmp)
        except FileNotFoundError:
            pass