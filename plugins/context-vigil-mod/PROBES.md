# context-vigil-mod probes (spec §9) — 2026-10-04

Run: throwaway `cvm-probe` mod in a tmux-hosted `claude --model haiku --remote-control`,
terminal half driven by a script, phone half by the owner. Phone results marked
**pending** until the owner reports them.

## 1. Notice reaching the phone
Observed: toast → terminal not captured (transient), phone **pending**; ui.log line → terminal yes (`⏺ cvm-probe: 🧪 probe log line …` in the transcript), phone: shows and resolves there — the Mods Field Notes record "ui.ask can be answered on the phone and resolves with the label (verified 2026-10-04)", and an open ask raises Remote Control's "action required" push (this probe's original "phone pending" was an unanswered dialog, not a non-resolving one).
Decision: notify() uses both `ui.toast` and `ui.log` until the phone result narrows it.

Phone result (owner on the Claude Android app, 2026-10-04, CC 2.1.289): **neither reaches the phone** — not from a command handler, not from an idle `$.clock` timer. Also not: `$.session.append` `system` (stored as an `informational` row) or `user` (stored `isMeta`). Reaches the phone: a plugin prompt (`$.prompt.submit`, shown as "The <plugin> plugin sent a message: …", starts a model turn), a slash command's reply `{ text }` (grey `<plugin>: …` line), model output / tools / the model's AskUserQuestion. A `ui.render` observer saw only `terminal` asks — never `mobile`, no `session.attach` — so mod UI (panes, bars) does not draw on the phone today. Live consequence: the RC countdown notice was never seen on the phone (smoke #4, two runs).
Decision (pending owner approval): in phone sessions, also send phone-relevant notices as a plugin prompt; start the countdown after it lands.

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

## 11. Which prompt-cache lifetime is the session on? (added 2026-10-05, owner request)
Researched, not probed live. Sources: https://code.claude.com/docs/en/prompt-caching (Cache lifetime), https://code.claude.com/docs/en/env-vars, https://code.claude.com/docs/en/statusline (prompt cache fields).
- Claude Code decides the TTL per request in two buckets. Main conversation default: 1h on a Claude subscription within plan usage; 5m on usage credits, API key, or a cloud provider. Everything else (subagents, compaction, titles): 5m. Precedence: `FORCE_PROMPT_CACHING_5M` > `CLAUDE_CODE_PROMPT_CACHE_TTL` / `promptCacheTtl` (v2.1.242+) > `ENABLE_PROMPT_CACHING_1H` > default. The 1h TTL is unavailable through the Claude apps gateway; Bedrock varies by model; gateways must forward the `anthropic-beta` header.
- It CAN change mid-session with no model switch: once plan usage runs out and the session draws on usage credits, the main conversation drops to 5m. A model switch gets its own cache, so `cache_ttl` on `classic.PreModelSwitch`/`PostModelSwitch` is the other trigger.
- Definitive per-response signal: the API's `usage.cache_creation` split (`ephemeral_1h_input_tokens` / `ephemeral_5m_input_tokens`), documented as the way to confirm the TTL, present on every assistant row in the transcript. The engine's `turn.complete.usage` carries only the summed `cache_creation_input_tokens` (no split), so it gates the read (0 = pure cache read, nothing learnt) and the transcript tail gives the split. The statusline `prompt_cache.ttl` / `expires_at` is the same truth but is a status-line payload, not an event a mod receives.
- Decision (lazy, owner-approved): last light is scheduled assuming 1h and the TTL is checked once, when the timer fires and `shouldFire` passes, by `sh -c 'tail -c 65536 "$1" | grep -o ...'` (only each row's small `cache_creation` object is emitted, never whole rows). The latest response that wrote decides; pure reads are walked back over. 1h fires; any 5m tokens (mixed counts as 5m: the shortest-lived write goes cold first, and warming a cold cache is the costlier error) or nothing in the tail does not fire and logs `last_light.skip` (`ttl-5m` / `ttl-unknown`). No widening, no retry. Nothing is read per turn and no TTL state is kept, so a mid-session drop to 5m (usage credits, a model switch) is caught at the only moment it matters. A pending last-light handover implies 1h was verified at fire time, so the return hold uses last API time + 1 h.
- Transcript path: from `classic.SessionStart`, else `<config>/projects/<cwd, non-alphanumerics to ->/<id>.jsonl`. Subagent transcripts live in their own files (not verified for every version).
- Information layer (not a gate): `$.state.cacheTtl` is set by one detached tail read on the session's first cache-writing `turn.complete` and by `classic.PostModelSwitch` `cache_ttl`; it drives only the "Last light is off" line and the "back on" notice (`last_light.off` / `last_light.on`). The fire-time check ignores it.
- Not used: `classic.PreModelSwitch` `cache_ttl` (unprobed whether it describes the cache left or entered), and the statusline `prompt_cache.ttl` (not an event a mod receives).
