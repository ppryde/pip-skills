# context-vigil-mod probes (spec §9) — 2026-10-04

Run: throwaway `cvm-probe` mod in a tmux-hosted `claude --model haiku --remote-control`,
terminal half driven by a script, phone half by the owner. Phone results marked
**pending** until the owner reports them.

## 1. Notice reaching the phone
Observed: toast → terminal not captured (transient), phone **pending**; ui.log line → terminal yes (`⏺ cvm-probe: 🧪 probe log line …` in the transcript), phone **pending**.
Decision: notify() uses both `ui.toast` and `ui.log` until the phone result narrows it.

## 2. Registered tool offered next turn
Observed: probe_echo called yes — registered by a command, then called by the model on the very next (plugin-submitted) prompt; result shape accepted: `{ result: string }` yes (`echo: pelican` rendered).
Decision: vigil_handover served by a `tool.call` hook on TOOL_FULL returning `{ result: string }`. The hook's `e` carries the tool's input fields flat beside `tool` and `tool_use_id` (`{ word, tool, tool_use_id }`).

## 3. AskUserQuestion answers visible to a tool.call hook
Observed: answers found at `r.result.answers` only (the input carries no answers); keyed by question text (`{ "Pick one?": "A" }`); multi-select join not probed. Options with `description: ""` are accepted.
Decision: `extractAnswers` (Task 9) reads input first, then result — keep (the result path is the live one; the input path is harmless).

## 4. classic.SessionStart source 'clear' after a MOD-RUN /clear
Observed: source `clear` (new session id); injected context reached the model (HERON) yes; `command.run` resolved `{ text: "" }`.

## 5. tool.call result `context` reaches the model
Observed: OSPREY yes.
Decision: setup follow-up cards ride `context` on the AskUserQuestion result (Task 15) — keep.

## 6. $.ui.ask
Observed: terminal → resolved to `Resume from handover` (dialog headed "Plugin", our options plus "Type something." / "Chat about this"); phone **pending**. The live `$.ui.ask` did NOT pass through the mod's own `tool.call` hook (no `AskUserQuestion` event logged for it).
Decision: last-light return question (Task 13) keeps `$.ui.ask` and awaits its label. The test world may still answer `$.ui.ask` through its AskUserQuestion stub; the shell must not depend on seeing its own `$.ui.ask` in `tool.call`.

## 7. Plugin prompt origin and { drop }
Observed: human prompts reach hooks with origin `{ kind: 'composer' }`; `{ drop }` held the prompt yes; re-submit arrived yes (`held prompt re-sent "hello there"`, and the model answered it). The mod's own `$.prompt.submit` prompts (the probe_echo ask, the AskUserQuestion ask, the held re-send) never reached the mod's own `prompt.submit` hook — every logged origin is `composer`; the transcript shows them as "Prompt from the cvm-probe plugin".
Decision: a mod never sees its own submitted prompts in `prompt.submit`, so nothing may rely on that (e.g. a countdown cancel keyed on our own plugin origin needs no guard — our resume prompt cannot cancel it). Other plugins' prompts were not probed; treat `kind: 'plugin'` from another plugin as agent activity as planned.

## 8. Naming the session after a clear (owner request, added 2026-10-04)
Observed: `sessionTitle` returned from `classic.SessionStart` (source `clear`) did NOT name the session (no `custom-title` in the new transcript). A mod-run `$.command.run({ command: 'rename', args })` right after the mod-run clear did: "Session renamed to: …", a `custom-title` + `agent-name` entry in the new transcript, the name in the prompt border; it resolves with `context` = a system-reminder "The user named this session …".
Decision: rename via a mod-run `/rename` from a timer in the clear branch of `classic.SessionStart` (Task 11a/12).
Follow-up (owner: keep an existing name): a plain `/clear` on a session named "cvm probe — renamed by mod" wrote the same `custom-title` + `agent-name` into the NEW transcript — `/clear` carries the name by itself. A session launched as `--remote-control cvm-probe` had no `custom-title` (only Claude Code's own `ai-title`). Decision: rename only when the pre-clear transcript holds no `"type":"custom-title"` line (Task 12a).

## 9. Does `$.state` survive a `/clear`? (added 2026-10-04, from review questions)
Observed: a `$.state` marker set at version 4 read back `{ version: 0 }` (unset) inside the NEW session's `classic.SessionStart` (source `clear`) — twice. Module variables survive (same process; the mod logged no reload), `$.store` is per account.
Decision: `$.state` is per session and is wiped by every clear BEFORE our SessionStart hook runs. Anything that must cross a clear (the pending handover, the limit latch, early-stop marks) is read from module variables or `$.store`, never `$.state` (Task 14a).
