# Worktree/Branch Distinction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Distinguish worktree/branch for cards and live agents on the shared board; scope the Party to the served repo; surface "unbegun" repos (live agents, no board) in the selector with a quest-themed holding page.

**Architecture:** census captures each session's git branch at record time (new `branch` field). Overseer backend surfaces it, scopes `/api/sessions` to the served repo via `derive_repo_root`, and augments `/api/repos` with census-derived unbegun repos. Frontend adds card branch badges, per-agent branch labels, a dim/spotlight branch filter, and the holding page.

**Tech stack:** census (stdlib Python), overseer backend (FastAPI, shells CLIs), frontend (React/Vite/@dnd-kit, committed dist).

## Global Constraints
- census is a SOFT, fail-safe dependency — branch derivation must NEVER raise or slow the status line meaningfully; git failure → no branch.
- Every `branch` value is optional end-to-end (absent → no chip/label/filter entry).
- Security unchanged: client-supplied `root` still validated against the board allowlist before any CLI shelling; **unbegun repo roots are never shelled** (no `/api/board` fetch for them).
- Python 3.9 floor; `from __future__ import annotations`. No new runtime deps.
- Gate: `plugins/overseer/tests/`, `plugins/overseer/dashboard/backend/tests/`, `plugins/census/tests/` (pytest via worktree `.venv`); frontend vitest + `npm run build` (node via nvm `v22.22.1`); committed-dist freshness (`test_dist_freshness.py`). ruff + mypy(scripts) clean.

---

## Task 1: Census captures the git branch
**Files:** Modify `plugins/census/scripts/store.py` (`merge`, ~line 178-190); Test `plugins/census/tests/test_store.py`.
**Interfaces:** entry dict gains optional `"branch": str | None`. Add `def _git_branch(worktree_cwd: str | None) -> str | None` — `git -C <cwd> rev-parse --abbrev-ref HEAD`, stripped; returns None on any failure / empty / "HEAD" (detached). Wrapped so it never raises.
- [ ] Write failing test: a git repo tmp cwd on a known branch → `merge` stores `entry["branch"] == "<branch>"`; a non-git cwd → `branch` is None/absent; monkeypatched git failure → None, no raise.
- [ ] Run → fail.
- [ ] Implement `_git_branch` (subprocess with `capture_output`, `timeout`, `cwd`, catch `OSError`/`SubprocessError`; None on returncode!=0 or blank/"HEAD"). In `merge`, set `entry["branch"] = _git_branch(worktree)`.
- [ ] Run → pass; census suite green.
- [ ] Commit: `feat(census): record each session's git branch (fail-safe)`.

## Task 2: Backend surfaces `branch` on session summaries
**Files:** Modify `plugins/overseer/dashboard/backend/app/main.py` (`_session_summary`, ~145); Test `dashboard/backend/tests/test_sessions*.py` (or where session tests live).
**Interfaces:** `_session_summary` output gains `"branch"` when `entry.get("branch")` present (omit when absent, mirroring the model/pr/session_name pattern).
- [ ] Failing test: a census entry with `branch` → summary carries it; without → key absent.
- [ ] Implement; run → pass.
- [ ] Commit: `feat(overseer-dashboard): surface session branch`.

## Task 3: Scope `/api/sessions` to the served repo (+ ghost-drop)
**Files:** Modify `main.py` (`_sessions_list` ~175, `get_sessions` ~319); Test backend sessions tests.
**Interfaces:** `get_sessions(root: str | None = None)` — resolve via the existing `_resolve_root(_derived_launch_root, root)` (default derived main root; client root still validated). `_sessions_list(repo_root)` keeps only sessions where `derive_repo_root(Path(entry["worktree_cwd"]))` resolves and equals `repo_root`; sessions whose cwd doesn't resolve (removed worktree) are dropped. `derive_repo_root` imported from `scripts.store` (already used elsewhere in main.py).
- [ ] Failing test: three sessions with cwds under repo A, repo B, and a non-existent path → `get_sessions(root=A)` returns only A's; ghost dropped; unknown root → 400 (unchanged).
- [ ] Implement; run → pass. (Note: `derive_repo_root` is a git subprocess per session; N small. Optional: memoize by cwd within the call.)
- [ ] Frontend `useSessions.ts` must pass the active root — see Task 6/8 wiring; backend default keeps it working until then.
- [ ] Commit: `feat(overseer-dashboard): scope Party sessions to the served repo`.

## Task 4: `/api/repos` includes unbegun repos
**Files:** Modify `main.py` (the `/api/repos` handler ~280 and `_discover_roots`); Test `dashboard/backend/tests/test_repos.py`.
**Interfaces:** each repo entry gains `has_board: bool` and `live_sessions: int`. Board repos (from `repos --json`): `has_board=true`. Then read live census sessions, `derive_repo_root` each, and for any repo root NOT in the board set add an entry `{label: <basename>, root, has_board:false, current:false, live_sessions:N}`. `live_sessions` on board repos = count of live sessions mapping to them. Do NOT add unbegun roots to the validated board allowlist used by `_resolve_root` (keep that = board roots only).
- [ ] Failing tests: with a board repo + a census session in a different boardless repo → `/api/repos` lists both, the boardless one `has_board:false, live_sessions>=1`; a board repo is never double-listed; **`GET /api/board?root=<unbegun root>` is still rejected 400** (unbegun roots aren't in the board allowlist).
- [ ] Implement; run → pass.
- [ ] Commit: `feat(overseer-dashboard): surface unbegun repos (live agents, no board) in /api/repos`.

## Task 5: Card branch badge (frontend)
**Files:** Modify `frontend/src/components/CardTile.tsx` (+ `EpicCard.tsx` if it renders branch-bearing cards), `styles.css`; Test the component tests.
**Interfaces:** when a card has `branch`, render a small on-theme branch chip (guild/parchment styling, visually distinct from status chips). No chip when absent.
- [ ] Failing test: CardTile with `branch:"feat/x"` renders the branch text; without → no chip.
- [ ] Implement + styles; vitest green; rebuild dist at the end (Task 9 batches the final rebuild — but if this task commits UI it must rebuild dist too, OR defer all dist rebuild to a single UI-final task; SIMPLEST: Tasks 5-8 each rebuild dist, or batch 5-8 then one rebuild. Choose: batch the dist rebuild once at the end of Task 8 and have Tasks 5-7 NOT rebuild — mark them src-only, with Task 8 doing the single rebuild+freshness. Note this explicitly in each commit.)
- [ ] Commit (src only): `feat(overseer-dashboard): card branch badge`.

## Task 6: Party per-agent branch label + pass active root (frontend)
**Files:** `frontend/src/components/PartyAvatar.tsx`/`PartyColumn.tsx`/`PartyOverlay.tsx`, `board/party.ts`, `board/useSessions.ts`, `api/client.ts` (thread root); Test party/session tests.
**Interfaces:** `useSessions` sends the active root (same `activeRoot` choke point as the board). Party avatar shows the agent's `branch` (+ existing worktree). Party is backend-scoped now, so it only lists current-repo agents.
- [ ] Failing test: session with branch → avatar shows it; useSessions requests include the active root.
- [ ] Implement; vitest green.
- [ ] Commit (src only): `feat(overseer-dashboard): show each agent's branch in the Party`.

## Task 7: Branch filter — dim + spotlight (frontend)
**Files:** new `frontend/src/components/BranchFilter.tsx` + `board/branches.ts` (distinct-branch derivation), wire in `App.tsx`/`Board.tsx`, `styles.css`; Tests.
**Interfaces:** `distinctBranches(cards, sessions) -> string[]` (union of `card.branch` and session `branch`, sorted, deduped, drop empty). `BranchFilter` sets `activeBranch: string | null`. Cards with `branch !== activeBranch` get class `is-dimmed`; matching cards + Party agents on `activeBranch` get `is-spotlight`. "All" → null (clears). Session-local state.
- [ ] Failing tests: `distinctBranches` unions/dedupes; selecting a branch marks non-matching cards dimmed and matching cards/party spotlit; "All" clears.
- [ ] Implement + styles; vitest green.
- [ ] Commit (src only): `feat(overseer-dashboard): branch filter (dim non-matching, spotlight matches)`.

## Task 8: Unbegun selector entries + holding page (frontend) + single dist rebuild
**Files:** `frontend/src/components/RepoSelector.tsx`, `board/useRepos.ts` (types gain `has_board`, `live_sessions`), new `components/UnbegunHolding.tsx`, `App.tsx` (render holding page when selected repo `has_board:false` — do NOT call `useBoard`/`/api/board`), `styles.css`; Tests. **Then rebuild `dist` once for Tasks 5-8.**
**Interfaces:** selector renders unbegun repos with distinct (faded/dashed) styling + agent count; selecting one sets a state that makes `App` render `<UnbegunHolding repo live_sessions/>` instead of the board, and suppresses the board fetch. Holding copy (quest voice, pluralise from `live_sessions`):
> 🗺️ **Your quest has not yet begun in _{repo}_.** — {N} adventurer{s} already roam these lands, but no Guild Board has been raised here. Run `overseer init` in `{repo}` to open the board and begin.
- [ ] Failing tests: selector lists an unbegun repo (has_board:false) distinctly; selecting it renders the holding page with correct name + pluralised count and does NOT trigger a board fetch; selecting a normal repo still shows the board.
- [ ] Implement; vitest green.
- [ ] Rebuild dist: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npm install && npm run build`. Commit `dist/` with this task.
- [ ] `.venv/bin/python -m pytest plugins/overseer/dashboard/backend/tests/test_dist_freshness.py` → pass.
- [ ] Commit: `feat(overseer-dashboard): unbegun-repo holding page + rebuild dist`.

## Task 9: Verification + version bump
**Files:** `plugins/overseer/.claude-plugin/plugin.json`, `plugins/census/.claude-plugin/plugin.json` (bump), READMEs (short notes).
- [ ] Full gate: `plugins/overseer/tests/`, `dashboard/backend/tests/`, `plugins/census/tests/` all pass; vitest pass; ruff + mypy(scripts) clean; dist-freshness pass.
- [ ] Manual smoke: with a temp `CLAUDE_CONFIG_DIR` census store containing sessions in two repos (one with a board, one without), confirm `/api/sessions?root=<board repo>` returns only that repo's sessions with branch, and `/api/repos` lists the boardless one as unbegun. Capture output.
- [ ] Bump overseer + census plugin versions; add a README line each (session branch capture; repo-scoped Party + unbegun holding page).
- [ ] Commit: `chore(overseer,census): bump versions; document branch distinction + scoped Party`.

## Self-Review notes
- Spec coverage: branch capture (T1), surface (T2), Party scope + ghost-drop (T3), unbegun repos (T4), card badge (T5), agent labels (T6), dim/spotlight filter (T7), holding page (T8), verify (T9). ✓
- Security: unbegun roots excluded from the shelled allowlist — asserted in T4. ✓
- Dist rebuild batched once in T8 to avoid 4 rebuilds; Tasks 5-7 are src-only (their tests are vitest on src, which don't need dist). The single freshness check runs in T8.
- Cross-plugin: census version bump alongside overseer (T9) since T1 changes census.
