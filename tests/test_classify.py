# tests/test_classify.py
from veille_tech import classify

def test_classify_hits_dbt(sample_categories):
    title = "Introducing dbt mesh for large teams"
    summary = "dbt now supports cross-project dependencies"
    assert classify(title, summary, sample_categories) == "dataprep_orchestration_etl"

def test_classify_hits_duckdb(sample_categories):
    title = "DuckDB 1.0 release brings performance boosts"
    summary = "columnar storage and OLAP improvements"
    assert classify(title, summary, sample_categories) == "db_sql_olap"

def test_classify_no_match(sample_categories):
    title = "Kubernetes tips for cluster autoscaling"
    summary = "some infra notes"
    assert classify(title, summary, sample_categories) is None