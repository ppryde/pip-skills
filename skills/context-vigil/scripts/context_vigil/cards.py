"""Install questions in AskUserQuestion's exact input shape (spec §3b, §4).

The agent passes these to its AskUserQuestion tool as printed, so the strings live
here and nowhere else. Limits: ≤ 4 questions per card, header ≤ 12 chars, 2–4
options, the default first and marked "(Recommended)"."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from context_vigil import launcher

Option = Tuple[str, str, str]   # label, description, install flag


def _question(header: str, question: str, options: List[Option]) -> Dict[str, Any]:
    return {"header": header, "question": question, "multiSelect": False,
            "options": [{"label": label, "description": desc} for label, desc, _ in options]}


THRESHOLD: List[Option] = [
    ("35% (Recommended)", "A balance of lean context and fewer handovers.", "--threshold 35"),
    ("25%", "Hand over sooner, with a leaner context.", "--threshold 25"),
    ("50%", "Fewer handovers, more degradation before each.", "--threshold 50"),
]
LAUNCH: List[Option] = [
    ("🚀 On demand (Recommended)", "Adds a `claude-tmux` command; `claude` is unchanged.",
     "--launcher on-demand"),
    ("♾️ Always", "`claude` always starts inside tmux (asks to confirm).",
     "--launcher always --confirm-always"),
    ("⏸ Not now", "No launcher; you type /clear after a handover.", "--launcher not-now"),
]
LAST_LIGHT: List[Option] = [
    ("Off (Recommended)", "Nothing happens while you are away.", "--last-light off"),
    ("On", "When you've stepped away with context ≥ 25% and the cache is 5 minutes from "
           "going cold, the agent prepares a handover. Nothing is cleared: come back, carry "
           "on, or /clear to resume ✨ Needs tmux.", "--last-light on"),
]
LAST_LIGHT_THRESHOLD: List[Option] = [
    ("25% (Recommended)", "Step in once a cold cache would cost a quarter of the window.",
     "--last-light on --last-light-threshold 25"),
    ("35%", "Only for larger contexts.", "--last-light on --last-light-threshold 35"),
    ("50%", "Only for very large contexts.", "--last-light on --last-light-threshold 50"),
]
BAR: List[Option] = [
    ("No (Recommended)", "The end-of-turn notice is enough.", "--bar off"),
    ("Yes", "[1] hand over · [2] remind me later · [0] dismiss. Terminal and desktop; "
            "needs a Claude Code build with mods.", "--bar on"),
]
ALWAYS_CONFIRM: List[Option] = [
    ("Yes, always (Recommended)", launcher.ALWAYS_CONFIRM, "--launcher always --confirm-always"),
    ("No, on demand", "Use `claude-tmux` instead.", "--launcher on-demand"),
]


def _flags(card: Dict[str, Any], options: List[List[Option]]) -> Dict[str, Dict[str, str]]:
    """header -> label -> install flag, so equal labels in different questions never collide."""
    return {q["header"]: {label: flag for label, _, flag in opts}
            for q, opts in zip(card["questions"], options)}


def install_cards(mods: bool) -> Dict[str, Any]:
    questions = [
        (_question("🎚️ Nudge at", "At what context % should I tap you on the shoulder?",
                   THRESHOLD), THRESHOLD),
        (_question("🖥️ Launcher", "How should Claude start for hands-free handovers?", LAUNCH),
         LAUNCH),
        (_question("🌅Last light",
                   "Prepare a handover before an idle 1-hour cache goes cold 🧊?", LAST_LIGHT),
         LAST_LIGHT),
    ]
    if mods:
        questions.append((_question("🎛️Vigil bar", "Add a pop-up bar above the prompt when "
                                                   "context crosses the threshold?", BAR), BAR))
    card1 = {"questions": [q for q, _ in questions]}
    threshold_card = last_light_card()
    confirm_card = {"questions": [_question(
        "♾️ Always", "Make `claude` always start inside tmux?", ALWAYS_CONFIRM)]}
    flags = _flags(card1, [opts for _, opts in questions])
    flags.update(_flags(threshold_card, [LAST_LIGHT_THRESHOLD]))
    flags.update(_flags(confirm_card, [ALWAYS_CONFIRM]))
    return {
        "card1": card1,
        "followups": {"last_light_threshold": threshold_card, "always_confirm": confirm_card},
        "flags": flags,
    }


def last_light_card() -> Dict[str, Any]:
    return {"questions": [_question("🌅 Threshold", "At what context % should last light "
                                                    "step in?", LAST_LIGHT_THRESHOLD)]}
