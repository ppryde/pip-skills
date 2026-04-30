from django.db import models


class Article(models.Model):
    title = models.CharField(max_length=300)
    slug = models.SlugField(unique=True)
    author_name = models.CharField(max_length=200)
    published_at = models.DateTimeField()
    is_published = models.BooleanField(default=True)
    view_count = models.IntegerField(default=0)
    # Wide columns — rarely read by callers
    body = models.TextField()
    metadata = models.JSONField(default=dict)
    raw_html = models.TextField(blank=True)
    search_vector = models.TextField(blank=True)
    revision_notes = models.TextField(blank=True)
    internal_tags = models.TextField(blank=True)

    class Meta:
        app_label = "fixture04"
