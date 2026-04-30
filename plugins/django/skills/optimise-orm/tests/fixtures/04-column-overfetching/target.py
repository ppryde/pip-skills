"""
Article listing — column over-fetching patterns.

list_articles: fetches all columns but callers only read title, slug, published_at.
  Triggers FETCH-020 (body/metadata/raw_html unread), FETCH-022 (.only() viable).
get_article_ids: single-field iteration — FETCH-021 opportunity.
"""

from .models import Article


def list_articles():
    """FETCH-020 + FETCH-022: wide model fetched; only 3 fields read by callers."""
    return Article.objects.filter(is_published=True)


def get_article_ids():
    """FETCH-021: single-field iteration — values_list(flat=True) opportunity."""
    return [a.id for a in Article.objects.filter(is_published=True)]
