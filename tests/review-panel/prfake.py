"""A scripted stand-in for `gh` and `git` so prreview tests never reach GitHub."""
from __future__ import annotations

import json


class FakeGh:
    def __init__(self):
        self.calls: list[list[str]] = []
        self.rules: list[tuple[str, object]] = []
        self.on("gh --version", (0, "gh version 2.96.0 (2026-01-01)\n", ""))

    def on(self, needle: str, response, times: int | None = None):
        """Prepend a rule: a call whose joined argv contains `needle` gets `response`
        ((rc, out, err), a list of them used in order, or a callable(argv))."""
        self.rules.insert(0, (needle, response))
        return self

    def __call__(self, argv, timeout=60):
        assert isinstance(argv, list) and all(isinstance(a, str) for a in argv)
        self.calls.append(list(argv))
        line = " ".join(argv)
        for needle, resp in self.rules:
            if needle in line:
                if callable(resp):
                    return resp(argv)
                if isinstance(resp, list):
                    return resp.pop(0) if len(resp) > 1 else resp[0]
                return resp
        return 1, "", f"unscripted: {line}"

    def lines(self):
        return [" ".join(c) for c in self.calls]

    def writes(self):
        return [c for c in self.lines() if "-X POST" in c or "-X PUT" in c or "-X PATCH" in c]


HEAD = "a" * 40

DIFF = """diff --git a/src/a.py b/src/a.py
index 111..222 100644
--- a/src/a.py
+++ b/src/a.py
@@ -1,3 +1,4 @@
 one
+two
 three
 four
@@ -10,2 +11,2 @@
 ten
-eleven
+eleven!
"""


def pr_view(head=HEAD, n=7):
    return 0, json.dumps({"number": n, "url": f"https://github.com/own/rep/pull/{n}",
                          "headRefOid": head}), ""


def pages(*items):
    return 0, json.dumps([list(items)]), ""


def standard(diff=DIFF, head=HEAD, local=HEAD, comments=(), reviews=()):
    g = FakeGh()
    g.on("gh pr view", pr_view(head))
    g.on("git rev-parse HEAD", (0, local + "\n", ""))
    g.on("git status", (0, "", ""))
    g.on("git rev-list", (0, "0\t0\n", ""))
    g.on("Accept: application/vnd.github.v3.diff", (0, diff, ""))
    g.on("/pulls/7/comments", pages(*comments))
    g.on("/pulls/7/reviews?", pages(*reviews))
    g.on("-X POST", (0, json.dumps({"html_url": "https://github.com/own/rep/pull/7#r1"}), ""))
    return g
