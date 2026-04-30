"""
Pure Python utility module — no Django imports, no ORM usage.

The skill should detect zero candidate ORM sites and exit cleanly:
  "No Django ORM usage detected. Nothing to analyse."

No findings should be emitted.
"""

import hashlib
import json


def hash_payload(data: dict) -> str:
    serialised = json.dumps(data, sort_keys=True)
    return hashlib.sha256(serialised.encode()).hexdigest()


def chunk_list(lst: list, size: int) -> list:
    return [lst[i:i + size] for i in range(0, len(lst), size)]


def flatten(nested: list) -> list:
    result = []
    for item in nested:
        if isinstance(item, list):
            result.extend(flatten(item))
        else:
            result.append(item)
    return result
