"""
Caller file for fixture 04 — feeds the caller-grep pass.

These are the only places Article objects from list_articles() are consumed.
Only three fields are accessed: title, slug, published_at.
The wide columns (body, metadata, raw_html, search_vector, etc.) are never read.
"""

from .target import get_article_ids, list_articles


def render_article_list():
    articles = list_articles()
    rows = []
    for article in articles:
        rows.append({
            "title": article.title,
            "slug": article.slug,
            "date": article.published_at,
        })
    return rows


def sidebar_article_links():
    articles = list_articles()
    return [(a.title, a.slug) for a in articles]


def article_id_set():
    return set(get_article_ids())
