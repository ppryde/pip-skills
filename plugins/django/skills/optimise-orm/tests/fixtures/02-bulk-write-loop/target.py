"""
Product import — bulk write anti-patterns.

import_products loops over incoming data and calls .save() per row (WRITE-001).
restock_products loops over existing products and calls .save() per row (WRITE-002).
No audit framework; no signal listeners on Product.
"""

from .models import Product


def import_products(data):
    """WRITE-001: loop of .save() on new objects — should use bulk_create."""
    for row in data:
        Product(
            name=row["name"],
            sku=row["sku"],
            price=row["price"],
            stock=row.get("stock", 0),
        ).save()


def restock_products(restock_map):
    """
    WRITE-002: loop over existing objects, mutate field, call .save().
    restock_map: {product_id: new_stock_value}
    """
    products = Product.objects.filter(pk__in=restock_map.keys())
    for product in products:
        product.stock = restock_map[product.pk]
        product.save()
