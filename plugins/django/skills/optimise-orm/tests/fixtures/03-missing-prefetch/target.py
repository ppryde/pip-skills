"""
Author/book listing — missing prefetch_related patterns.

list_authors_with_books: accesses book_set in loop without prefetch (FETCH-010).
list_books_with_tags: accesses M2M tags in loop without prefetch (FETCH-010).
filter_books_per_author: uses string prefetch but then filters per-row (FETCH-011).
nested_prefetch_reeval: Prefetch without to_attr causes silent re-fetch (FETCH-012).
"""

from django.db.models import Prefetch

from .models import Author, Book


def list_authors_with_books():
    """FETCH-010: reverse FK access in loop without prefetch."""
    authors = Author.objects.all()
    result = []
    for author in authors:
        books = list(author.books.all())  # N extra queries
        result.append({"author": author.name, "books": [b.title for b in books]})
    return result


def list_books_with_tags():
    """FETCH-010: M2M access in loop without prefetch."""
    books = Book.objects.filter(is_published=True)
    result = []
    for book in books:
        tags = list(book.tags.all())  # N extra queries
        result.append({"title": book.title, "tags": [t.name for t in tags]})
    return result


def filter_books_per_author():
    """FETCH-011: string prefetch then per-row Python filter — Prefetch(queryset=) needed."""
    authors = Author.objects.prefetch_related("books")
    for author in authors:
        recent = author.books.filter(published_year__gte=2020)  # re-queries DB
        yield author.name, list(recent)


def nested_prefetch_reeval():
    """FETCH-012: Prefetch without to_attr — silent re-fetch risk."""
    authors = Author.objects.prefetch_related(
        Prefetch("books", queryset=Book.objects.filter(is_published=True))
    )
    for author in authors:
        books = author.books.all()  # may re-query — no to_attr set
        yield author.name, [b.title for b in books]
