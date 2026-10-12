"""Seeded fuzzing: nothing hostile stays allowed, and whatever is allowed matches the real shells."""
from __future__ import annotations

import random

from tribunal_helpers import ALLOW_CORPUS, allow_gh, allowed, assert_oracle_agrees

SEED = 20261010
CASES = 5000

META = list(";&|<>(){}$`\\#~*?[]!\"'\n\r\x00^ \t=")
# Alphabet for single-character mutation: printable ASCII, whitespace, control, non-ASCII.
MUTATE = [chr(c) for c in range(32, 127)] + ["\n", "\t", "\r", "\x00", "\x7f", "é", "ｇ", "​"]


def test_appended_metachars_never_survive(tmp_path) -> None:  # noqa: ANN001
    rng = random.Random(SEED)
    survivors: set[str] = set()
    for _ in range(CASES):
        base = rng.choice(ALLOW_CORPUS)
        extra = "".join(rng.choice(META) for _ in range(rng.randint(1, 4)))
        cmd = base + extra
        if not allowed(cmd):
            continue
        survivors.add(cmd)
        # No quote characters: the extra text stays bare, so only blanks and `=` may survive.
        if "'" not in extra and '"' not in extra:
            assert not extra.strip(" \t="), repr(cmd)
    # Whatever did survive must be understood identically by the real shells.
    assert survivors, "fuzz produced no survivors; the property is vacuous"
    for cmd in sorted(survivors):
        assert_oracle_agrees(cmd, tmp_path)


def test_single_character_mutations_are_denied_or_shell_equivalent(tmp_path) -> None:  # noqa: ANN001
    rng = random.Random(SEED + 1)
    survivors: set[str] = set()
    tokenizable: set[str] = set()
    for _ in range(CASES):
        base = rng.choice(ALLOW_CORPUS)
        pos = rng.randrange(len(base))
        mode = rng.random()
        ch = rng.choice(MUTATE)
        if mode < 0.7:
            cmd = base[:pos] + ch + base[pos + 1 :]  # replace
        elif mode < 0.9:
            cmd = base[:pos] + ch + base[pos:]  # insert
        else:
            cmd = base[:pos] + base[pos + 1 :]  # delete
        if allowed(cmd):
            survivors.add(cmd)
        elif allow_gh.tokenize(cmd) is not None:
            tokenizable.add(cmd)
    assert survivors and tokenizable, "mutation fuzz is vacuous"
    # Every allowed mutant: argv must equal what bash and zsh produce.
    for cmd in sorted(survivors):
        assert_oracle_agrees(cmd, tmp_path)
    # A sample of tokenizer-accepted-but-declined mutants too (the tokenizer is the trust boundary).
    sample = sorted(tokenizable)
    rng.shuffle(sample)
    for cmd in sample[:300]:
        assert_oracle_agrees(cmd, tmp_path)


def test_random_strings_never_crash_the_hook_logic() -> None:
    rng = random.Random(SEED + 2)
    alphabet = list("ghpr viewapi-_=/.:'\"$;\n") + ["gh ", "pr ", "api ", "graphql ", "--json ", "-f "]
    for _ in range(CASES):
        cmd = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 24)))
        argv = allow_gh.tokenize(cmd)
        if argv is not None:
            allow_gh.decide(argv)  # must not raise
