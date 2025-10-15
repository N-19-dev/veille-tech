# tests/test_filters.py
from veille_tech import is_editorial_article

def test_filter_allows_blog_path(editorial_cfg):
    url = "https://example.com/blog/data-engineering/etl-best-practices"
    assert is_editorial_article(url, editorial_cfg, text="x" * 200)

def test_filter_denies_release_notes(editorial_cfg):
    url = "https://example.com/release-notes/v1-2-3"
    assert not is_editorial_article(url, editorial_cfg, text="x" * 500)

def test_filter_denies_blacklisted_domain(editorial_cfg):
    url = "https://twitter.com/some-thread"
    assert not is_editorial_article(url, editorial_cfg, text="x" * 500)

def test_filter_respects_min_length(editorial_cfg):
    url = "https://blog.example.org/posts/short"
    assert not is_editorial_article(url, editorial_cfg, text="too short")