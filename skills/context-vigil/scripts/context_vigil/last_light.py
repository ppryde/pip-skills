"""Last light: before an idle session's 1-hour prompt cache goes cold, ask the agent
to *prepare* a handover. Nothing is cleared. Spec §1."""
from __future__ import annotations

MARKER = "[context-vigil:last-light]"
