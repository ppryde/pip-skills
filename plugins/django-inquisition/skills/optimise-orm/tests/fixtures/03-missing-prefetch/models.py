from django.db import models


class Author(models.Model):
    name = models.CharField(max_length=200)
    bio = models.TextField()

    class Meta:
        app_label = "fixture03"


class Book(models.Model):
    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="books")
    title = models.CharField(max_length=300)
    published_year = models.IntegerField()
    is_published = models.BooleanField(default=True)

    class Meta:
        app_label = "fixture03"


class Tag(models.Model):
    books = models.ManyToManyField(Book, related_name="tags")
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "fixture03"
