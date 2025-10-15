# tests/conftest.py
# - Met le dossier racine dans sys.path pour importer veille_tech.py
# - Fournit quelques fixtures utiles (catégories, config filtre)

import os
import sys
import pytest
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

@pytest.fixture
def sample_categories():
    from veille_tech import Category
    return [
      Category(key="db_sql_olap", title="🔢 Bases de données & OLAP",
               keywords=["postgres", "mysql", "bigquery", "snowflake", "databricks", "trino", "duckdb", "olap"]),
      Category(key="dataprep_orchestration_etl", title="👨‍🔧 Data Prep & Orchestration (ELT/ETL)",
               keywords=["airflow", "dagster", "prefect", "dbt", "dataform", "sqlmesh", "ingestion", "transformation"]),
      Category(key="python_polars_duckdb", title="🐍 Python, Polars, DuckDB",
               keywords=["python", "polars", "duckdb"]),
    ]

@pytest.fixture
def editorial_cfg():
    # Mimique la structure cfg.dict() utilisée par is_editorial_article
    return {
        "crawl": {
            "min_text_length": 100,
            "whitelist_domains": ["example.com", "blog.example.org", "airflow.apache.org"],
            "blacklist_domains": ["reddit.com", "twitter.com", "x.com", "github.com", "community.", "careers."],
            "path_allow_regex": r"(^|/)(blog|posts|articles|news)(/|$)",
            "path_deny_regex":  r"(^|/)(forum|community|jobs|careers|events|release-notes|whats-new)(/|$)",
        }
    }

@pytest.fixture
def now_ts():
    return int(datetime.now(tz=timezone.utc).timestamp())

@pytest.fixture
def last_week_ts():
    return int((datetime.now(tz=timezone.utc) - timedelta(days=7)).timestamp())