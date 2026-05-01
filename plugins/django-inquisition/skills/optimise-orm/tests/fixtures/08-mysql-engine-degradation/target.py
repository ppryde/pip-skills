"""
MySQL engine — IDX-040 GIN demotion fixture.

IDX-040 normally fires as high severity for JSONField filtered with __has_key
on Postgres (recommends GinIndex). On MySQL, GIN indexes do not exist;
the finding must be demoted to an info-level banner:
  "GIN indexes are Postgres-specific. Review JSON filtering performance for MySQL."

The skill should NOT emit IDX-040 as a critical/medium/low finding.
It should surface the engine-mismatch as a header note or banner only.
"""

from .models import Product


def get_products_with_colour():
    """IDX-040 candidate — but engine is MySQL, so demoted to info banner."""
    return Product.objects.filter(attributes__has_key="colour")
