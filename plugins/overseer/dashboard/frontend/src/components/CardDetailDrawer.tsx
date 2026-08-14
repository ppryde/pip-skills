import { useCallback, useEffect, useRef, useState } from "react";
import { editCard, getCard, pullChildren, setLabels } from "../api/client";
import type { CardDetail } from "../api/types";
import type { UseBoardResult } from "../board/useBoard";
import type { PartyMember } from "../board/party";
import { accentKeyForCard, bannerLabelForCard } from "../board/cardAccent";
import { rarityStars } from "../board/rarityStars";
import { parseProgressLog } from "../board/progressLog";
import { ACCENT_GROUPS } from "../board/avatarAccent";
import { HTTP_URL_RE } from "../board/httpUrl";
import { cardIconKey, laneIcon } from "../board/laneIcons";
import BudgetMeter from "./BudgetMeter";
import DependencyBadge from "./DependencyBadge";
import ClaimControl from "./ClaimControl";
import PrioritySelect from "./PrioritySelect";
import LinkEditor from "./LinkEditor";
import StatusMenu from "./StatusMenu";
import MarkdownView from "./MarkdownView";
import ChecklistRows from "./ChecklistRows";
import PartyAvatar from "./PartyAvatar";
import LabelEditor from "./LabelEditor";
import { StarIcon } from "./icons";
// WF-097 follow-up: the edit-mode title field and body field now route
// through the design-library `<Input>`/`<Textarea>` primitives (`src/ui/`) —
// `.card-drawer__title-input`/`.card-drawer__body-textarea` in styles.css are
// slimmed to the genuine overrides they layer on the shared `.qb-input` base
// (display font / monospace prose / dashed border / resize), which is exactly
// the split `.qb-input`'s own doc comment anticipates. The `.card-drawer__close`
// "×" stays the icon-only affordance, and the Quest|Scroll viewtoggle stays on
// its bespoke segmented `.qb-btn` pair (aria-pressed mechanics unchanged).
//
// Label standardisation follow-up: every small caption/eyebrow in the drawer
// now routes through the SAME `<Label>` the topbar's REPO/BRANCH/SCRY/
// Provisions eyebrows use, so they read as one look app-wide —
// `.card-drawer__section-heading` (via `<Label as="h3">`, keeping real
// heading semantics — see Label's own doc comment), `.card-drawer__journey-
// label`, and `.card-drawer__checklist-count`; each class below is slimmed
// to its genuine layout delta now that `.qb-label` supplies the caption
// look. Deliberately EXCLUDED: `.card-drawer__id` (the card's own id VALUE,
// not a field caption), `.card-drawer__hero-class`/`.card-drawer__pr-chip`
// (badge/chip VALUES — a session's model name or a PR ref, not label text),
// and the status-fact pill (a filled/tinted chip, a different design
// language from the muted eyebrow) — none of these describe another
// element, they ARE the content, so `.qb-label`'s uppercase-eyebrow
// treatment doesn't apply.
import { Button, Input, Label, Textarea } from "../ui";

export interface CardDetailDrawerProps {
  /** Card id to show, or null when the drawer is closed. */
  cardId: string | null;
  onClose: () => void;
  mutate: UseBoardResult["mutate"];
  inFlight: boolean;
  /** All card ids on the board — threaded down to LinkEditor for its
   * parent/dependency option lists (see wf005-c6-brief.md). */
  allCardIds: string[];
  /** id -> title lookup (WF-081) for the same board `allCardIds` draws
   * from — threaded straight through to LinkEditor so its depends-on
   * picker can show each candidate's title alongside its id. Optional:
   * omitting it just falls back to id-only display, same as before. */
  cardTitles?: Record<string, string>;
  /** The shared session<->card join (App.tsx) — the drawer is a fourth
   * CONSUMER of this one array, never its own poll (WF-030 Decisions).
   * Resolved against `detail.claimed_by` to render the hero chip's
   * PartyAvatar + class; ClaimControl's independent poll is unrelated. */
  party: PartyMember[];
  /** F10 editable colour registry (WF-067) — board payload's `label_colors`,
   * passed straight through to `LabelEditor`. */
  colorRegistry?: Record<string, string>;
}

/**
 * Sensible display order for well-known sections — anything else present in
 * `sections` is rendered too, just appended after these (see wf005-c5-brief.md:
 * "render whatever sections exist — do not hardcode a fixed set that hides
 * unknown headings").
 */
const PREFERRED_SECTION_ORDER = [
  "## Goal",
  "## Plan",
  "## Decisions",
  "## Progress log",
  "## Review log",
  "## Verification",
];

function orderedSectionEntries(
  sections: Record<string, string>
): [string, string][] {
  const keys = Object.keys(sections);
  const preferred = PREFERRED_SECTION_ORDER.filter((k) => keys.includes(k));
  const rest = keys.filter((k) => !PREFERRED_SECTION_ORDER.includes(k));
  return [...preferred, ...rest].map((k) => [k, sections[k]]);
}

function sectionLabel(heading: string): string {
  return heading.replace(/^#+\s*/, "");
}

/**
 * Read-only expand-to-view drawer (Chunk 5). Fetches `getCard(id)` lazily
 * into its OWN state — the board is never touched by opening/closing this.
 *
 * Carries the SAME monotonic-counter discipline as `useBoard.mutate` (see
 * wf005-context.md "Single mutation entrypoint" + the C5 brief's "counter-
 * guarded refetch" amendment): a stale/out-of-order `getCard` response (the
 * user reopens a different card before the first resolves, or a later
 * refetch — added in C6 — resolves first) is dropped; only the latest
 * issued request's result is ever applied.
 *
 * C6 adds the mutation controls (PrioritySelect/LinkEditor/StatusMenu). Each
 * routes its own call through `useBoard().mutate` (passed down from `App`)
 * — this component never calls the api client + setState for a mutation
 * itself. After any of those mutations settles, the control invokes
 * `onMutated` (wired to `refetchDetail` below) so the drawer's OWN view
 * re-fetches too, through the same counter guard — the board refresh from
 * `mutate` and this card-detail refetch are separate concerns.
 */
function CardDetailDrawer({
  cardId,
  onClose,
  mutate,
  inFlight,
  allCardIds,
  cardTitles,
  party,
  colorRegistry,
}: CardDetailDrawerProps) {
  const [detail, setDetail] = useState<CardDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Rendered vs. verbatim-source view of the card body — local to the
  // drawer, reset (below) whenever a card is opened, so switching cards
  // never carries the previous card's "source" toggle forward.
  const [view, setView] = useState<"rendered" | "source">("rendered");

  // Title/body edit mode (Task 8) — local drafts, seeded from `detail` and
  // reset (below) whenever the shown card changes, so switching cards never
  // leaks a draft from the previous card into the new one.
  const [editing, setEditing] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [bodyDraft, setBodyDraft] = useState("");
  // Fix-up (dual review, PR3): `busy` + `editError` mirror NewCardDialog's
  // own local state — `mutate`'s default swallow-and-refresh behavior would
  // otherwise exit edit mode and drop the draft on a FAILED save (see
  // `saveEdit` below). `busy` is a synchronous in-flight guard distinct from
  // the `inFlight` prop (which only updates once `mutate` has set React
  // state), so a rapid double-click of Save can't fire two overlapping
  // `editCard` calls.
  const [busy, setBusy] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  // Monotonic counter, same pattern as useBoard's requestIdRef: a response is
  // only applied if its id is still the latest issued when it resolves.
  const requestIdRef = useRef(0);

  // Tracks the ACTUAL currently-open card id, independent of any particular
  // `refetchDetail` closure below. A mutation control (PrioritySelect/
  // StatusMenu/LinkEditor) captures `onMutated` at click time and invokes it
  // once its own async `mutate()` settles — if the drawer has since closed
  // or switched to a different card, that captured closure is stale and
  // must no-op rather than firing an unneeded `getCard` for a card that's
  // no longer open (see wf005 review: "guard stale onMutated closure").
  const activeCardIdRef = useRef<string | null>(cardId);
  useEffect(() => {
    activeCardIdRef.current = cardId;
  }, [cardId]);

  const fetchDetail = useCallback((id: string) => {
    const reqId = ++requestIdRef.current;
    setLoading(true);
    setError(null);

    getCard(id)
      .then((res) => {
        if (reqId !== requestIdRef.current) return; // stale — a newer open/refetch won
        setDetail(res);
      })
      .catch((e) => {
        if (reqId !== requestIdRef.current) return;
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (reqId === requestIdRef.current) setLoading(false);
      });
  }, []);

  useEffect(() => {
    if (cardId === null) return;
    setView("rendered");
    fetchDetail(cardId);
  }, [cardId, fetchDetail]);

  // Re-fetch the currently-open card, through the same counter guard —
  // passed to the mutation controls as `onMutated`. Guarded against a stale
  // closure: only refetches if `cardId` (captured when this instance of the
  // callback was created) still matches the drawer's actual open card at
  // invocation time — a no-op once the drawer has closed or switched cards.
  const refetchDetail = useCallback(() => {
    if (cardId !== null && activeCardIdRef.current === cardId) {
      fetchDetail(cardId);
    }
  }, [cardId, fetchDetail]);

  // Reset the title/body edit drafts (and exit edit mode) whenever the
  // shown card changes — a switch to a different card, or a refetch that
  // brings back updated content after a save, both land here so a draft
  // never leaks across cards and a completed save falls back to the read
  // view once the refreshed detail arrives.
  useEffect(() => {
    if (!detail) return;
    setTitleDraft(detail.title);
    setBodyDraft(detail.body);
    setEditing(false);
    setEditError(null);
  }, [detail?.id, detail?.title, detail?.body]);

  const cancelEdit = () => {
    if (detail) {
      setTitleDraft(detail.title);
      setBodyDraft(detail.body);
    }
    setEditing(false);
    setEditError(null);
  };

  // Same routing as every other drawer control (PrioritySelect/LinkEditor/
  // ClaimControl/LabelEditor's onSave above): the save goes THROUGH
  // `useBoard().mutate` — never a direct `editCard` call — so the shared
  // board state (and thus TileShell's tiles) updates immediately, then
  // `refetchDetail` (the SAME counter-guarded closure those siblings pass
  // as `onMutated`) refreshes the drawer's own detail.
  //
  // Fix-up (dual review, PR3): `{ rethrow: true }`, same as NewCardDialog's
  // `submit()` — DEFAULT `mutate` swallows a rejection into the global error
  // banner and still resolves, which used to mean a FAILED save fell through
  // to `setEditing(false)` + `refetchDetail()` unconditionally: edit mode
  // silently closed and the user's unsaved draft was discarded. Now a
  // rejection is caught here, edit mode stays open, both drafts are left
  // exactly as the user typed them, and an inline error renders below the
  // textarea — success is the only path that closes edit mode.
  const saveEdit = async () => {
    if (!detail || !titleDraft.trim() || busy) return;
    setBusy(true);
    setEditError(null);
    try {
      await mutate(
        () => editCard(detail.id, { title: titleDraft.trim(), body: bodyDraft }),
        { rethrow: true }
      );
      setEditing(false);
      refetchDetail();
    } catch (e) {
      setEditError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  // Pull children (F9, WF-066) — confirm-gated, epics only (rendered below).
  // Routes through the SAME `mutate` prop as every sibling control
  // (StatusMenu/LinkEditor/ClaimControl/LabelEditor's onSave/saveEdit above)
  // so the board's own state updates immediately, then `refetchDetail` — the
  // same counter-guarded closure those siblings pass as `onMutated` —
  // refreshes the drawer's own detail view.
  const handlePullChildren = async () => {
    if (!detail) return;
    if (!window.confirm("Pull all live children into this epic's column?")) {
      return;
    }
    await mutate(() => pullChildren(detail.id));
    refetchDetail();
  };

  useEffect(() => {
    if (cardId === null) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [cardId, onClose]);

  if (cardId === null) return null;

  const sectionEntries = detail ? orderedSectionEntries(detail.sections) : [];
  const accentKey = detail ? accentKeyForCard(detail) : "";
  const bannerLabel = detail ? bannerLabelForCard(detail) : "";
  const stars = detail ? rarityStars(detail.complexity) : 0;
  const heroSession = detail?.claimed_by
    ? party.find((p) => p.session.id === detail.claimed_by)?.session
    : undefined;
  // Journey progress (HANDOFF): % over the FULL checklist, same derivation
  // as WF-028's board-tile progress bar — the drawer never windows its
  // checklist to begin with, so there's no wrong-source slice to guard
  // against here, just the same done/total math.
  const checklistTotal = detail?.checklist.length ?? 0;
  const checklistDone =
    detail?.checklist.filter((e) => e.status === "completed").length ?? 0;
  const journeyPct =
    checklistTotal > 0 ? Math.round((checklistDone / checklistTotal) * 100) : 0;

  return (
    <div className="drawer-overlay" data-testid="drawer-overlay" onClick={onClose}>
      <aside
        className="card-drawer"
        role="dialog"
        aria-label={detail ? `${detail.id} details` : `${cardId} details`}
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          className="card-drawer__close"
          onClick={onClose}
          aria-label="Close"
        >
          ×
        </button>

        {loading && <p className="card-drawer__status">Loading…</p>}
        {error && (
          <p className="card-drawer__status card-drawer__status--error">
            {error}
          </p>
        )}

        {!loading && !error && detail && (
          <>
            <header className="card-drawer__header">
              <div className="card-drawer__banner-row">
                <span
                  className={`card-drawer__banner card-drawer__banner--${accentKey}`}
                >
                  {bannerLabel}
                </span>
                <span className="card-drawer__id">{detail.id}</span>
                {stars > 0 && (
                  <span className="card-drawer__stars" aria-hidden="true">
                    {[0, 1, 2, 3].map((i) => (
                      <StarIcon
                        key={i}
                        filled={i < stars}
                        className={
                          "card-drawer__star " +
                          (i < stars
                            ? "card-drawer__star--filled"
                            : "card-drawer__star--empty")
                        }
                      />
                    ))}
                  </span>
                )}
                {!editing && (
                  <Button
                    className="card-drawer__edit-btn"
                    variant="neutral"
                    onClick={() => setEditing(true)}
                    disabled={inFlight}
                  >
                    Edit
                  </Button>
                )}
              </div>
              {editing ? (
                <Input
                  aria-label="title"
                  className="card-drawer__title-input"
                  value={titleDraft}
                  onChange={(e) => setTitleDraft(e.target.value)}
                />
              ) : (
                <div className="card-drawer__title-row">
                  <img
                    className="card-drawer__lifecycle-icon"
                    src={laneIcon(cardIconKey(detail))}
                    alt=""
                    aria-hidden="true"
                  />
                  <h2 className="card-drawer__title">{detail.title}</h2>
                </div>
              )}
              <div className="card-drawer__facts">
                <span
                  className={`card-drawer__status-fact card-drawer__status-fact--${accentKey}`}
                >
                  {detail.status}
                </span>
                {detail.repo && <span className="repo-chip">{detail.repo}</span>}
                {/* Card's stored PR ref/URL (WF-073) — Card.pr, a plain
                    string set via `overseer set-field --pr`. NOT the same
                    thing as the hero chip's live census PrWindow data below
                    (that's the CLAIMING SESSION's currently-open PR, not
                    this card's). Same http(s)->anchor / bare-text render
                    rule as the Links section further down. */}
                {detail.pr &&
                  (HTTP_URL_RE.test(detail.pr) ? (
                    <a
                      href={detail.pr}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="card-drawer__pr-chip"
                    >
                      PR
                    </a>
                  ) : (
                    <span className="card-drawer__pr-chip">{detail.pr}</span>
                  ))}
                <PrioritySelect
                  cardId={detail.id}
                  value={detail.priority}
                  mutate={mutate}
                  inFlight={inFlight}
                  onMutated={refetchDetail}
                />
                <BudgetMeter budget={detail.budget} />
                {detail.claimed_by && (
                  <span
                    className="card-drawer__hero-chip"
                    title={detail.claimed_by}
                  >
                    {/* Stale-evicted edge (Decisions): claimed_by can outlive
                        the session's presence in the shared party poll — the
                        chip still renders, just without an avatar/class. */}
                    {heroSession && (
                      <PartyAvatar session={heroSession} size={20} />
                    )}
                    <span className="card-drawer__hero-name">
                      {heroSession?.session_name || detail.claimed_by}
                    </span>
                    {heroSession?.model && (
                      <span className="card-drawer__hero-class">
                        {heroSession.model}
                      </span>
                    )}
                  </span>
                )}
              </div>
              {/* Editable labels (F1, WF-058) — its own row below the facts
                  line so it never crowds the priority/budget/hero chips
                  there. Routes through `useBoard().mutate` (the SAME
                  single-mutation-entrypoint `mutate` prop PrioritySelect/
                  LinkEditor/ClaimControl use — see wf005-context.md) so the
                  shared board state updates instantly, same as every other
                  drawer control, then calls `refetchDetail` — the SAME
                  counter-guarded closure those siblings pass as their own
                  `onMutated` — so the drawer's own detail view refreshes
                  too. */}
              <LabelEditor
                labels={detail.labels ?? []}
                onSave={async (labels) => {
                  await mutate(() => setLabels(detail.id, labels));
                  refetchDetail();
                }}
                colorRegistry={colorRegistry}
              />
            </header>

            <div className="card-drawer__controls">
              <StatusMenu
                cardId={detail.id}
                status={detail.status}
                mutate={mutate}
                inFlight={inFlight}
                onMutated={refetchDetail}
              />
              <LinkEditor
                cardId={detail.id}
                parent={detail.parent}
                dependsOn={detail.depends_on}
                allCardIds={allCardIds}
                cardTitles={cardTitles}
                mutate={mutate}
                inFlight={inFlight}
                onMutated={refetchDetail}
              />
              <ClaimControl
                cardId={detail.id}
                claimedBy={detail.claimed_by}
                mutate={mutate}
                inFlight={inFlight}
                onMutated={refetchDetail}
              />
              {/* Pull children (F9, WF-066) — epics only; confirm-gated
                  because it mutates every live child's stage/status at
                  once. */}
              {detail.is_epic && (
                <Button
                  variant="neutral"
                  onClick={() => void handlePullChildren()}
                  disabled={inFlight}
                >
                  Pull children
                </Button>
              )}
            </div>

            {/* Journey progress + Sub-quests panel + Locked-behind pill:
                Quest view ONLY (HANDOFF's two-mutually-exclusive-panels
                model — Scroll shows the markdown card alone; the checklist
                is display-only, so there's no interactivity reason to keep
                it mounted under Scroll). The tab bar itself stays outside
                this swap, below. */}
            {view === "rendered" && (
              <>
                {detail.checklist.length > 0 && (
                  <>
                    {/* Journey progress (HANDOFF: Quest tab, above the
                        sub-quests panel; hidden with the whole block when
                        there's no checklist). */}
                    <div className="card-drawer__journey">
                      <Label className="card-drawer__journey-label">
                        Journey progress
                      </Label>
                      <div
                        className="card-drawer__journey-track"
                        data-progress-pct={journeyPct}
                      >
                        <div
                          className={`card-drawer__journey-fill card-drawer__journey-fill--${accentKey}`}
                          style={{ width: `${journeyPct}%` }}
                        />
                      </div>
                    </div>
                    <section className="card-drawer__checklist">
                      <div className="card-drawer__checklist-header">
                        <Label as="h3" className="card-drawer__section-heading">
                          Sub-quests
                        </Label>
                        <Label className="card-drawer__checklist-count">
                          {checklistDone} / {checklistTotal}
                        </Label>
                      </div>
                      <ChecklistRows entries={detail.checklist} />
                    </section>
                  </>
                )}

                {/* Locked-behind pill (HANDOFF: Quest tab, after the
                    sub-quests panel — NOT the header meta row, see chunk
                    2's Decisions). Independent of the checklist's own
                    presence: a card can be blocked on a dependency with
                    zero sub-quests. DependencyBadge self-gates (renders
                    nothing when ready or dep-less), same unconditional-
                    render usage as TileShell's board-tile footer. */}
                <div className="card-drawer__locked">
                  <DependencyBadge card={detail} />
                </div>

                {/* Read-only Links section (F8, WF-065) — plain reference
                    links (label/path), NOT the LinkEditor above (that
                    manages parent/depends_on card relationships). Renders
                    nothing when the card has none. */}
                {detail.links && detail.links.length > 0 && (
                  <section className="card-drawer__links">
                    <Label as="h3" className="card-drawer__section-heading">
                      Links
                    </Label>
                    <ul className="card-drawer__links-list">
                      {detail.links.map((l, i) => (
                        <li key={i}>
                          {HTTP_URL_RE.test(l.path) ? (
                            <a
                              href={l.path}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              {l.label}
                            </a>
                          ) : (
                            <span>{l.label}</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
              </>
            )}

            {/* Title/body edit mode (Task 8) — replaces the Quest|Scroll tab
                bar + body panel with a raw-markdown textarea + Save/Cancel
                while editing; the read views below render unchanged
                otherwise. Save routes through `mutate` (see `saveEdit`
                above), exactly like every other drawer control. */}
            {editing ? (
              <div className="card-drawer__edit-body">
                <Textarea
                  aria-label="body"
                  className="card-drawer__body-textarea"
                  value={bodyDraft}
                  onChange={(e) => setBodyDraft(e.target.value)}
                  rows={14}
                />
                {editError && (
                  <p className="card-drawer__edit-error" role="alert">
                    {editError}
                  </p>
                )}
                <div className="card-drawer__edit-actions">
                  <Button
                    variant="primary"
                    onClick={() => void saveEdit()}
                    disabled={busy || inFlight || !titleDraft.trim()}
                  >
                    Save
                  </Button>
                  <Button
                    variant="neutral"
                    onClick={cancelEdit}
                    disabled={busy || inFlight}
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            ) : (
              <>
                {/* Segmented Quest | Scroll (MD) toggle (HANDOFF labels;
                    WF-096 restyled it onto the shared `.qb-btn` Role-A
                    recipe, matching the topbar/atlas segmented controls) —
                    internal view state stays "rendered"/"source" and the
                    aria-pressed/state mechanics are unchanged either way,
                    only the paint/labels moved. */}
                <div
                  className="card-drawer__viewtoggle"
                  role="group"
                  aria-label="Body view"
                >
                  <button
                    type="button"
                    className="qb-btn card-drawer__viewtoggle-btn"
                    aria-pressed={view === "rendered"}
                    onClick={() => setView("rendered")}
                  >
                    Quest
                  </button>
                  <button
                    type="button"
                    className="qb-btn card-drawer__viewtoggle-btn"
                    aria-pressed={view === "source"}
                    onClick={() => setView("source")}
                  >
                    Scroll <span className="card-drawer__md-badge">MD</span>
                  </button>
                </div>
                <div className="card-drawer__body">
              {view === "source" ? (
                <pre className="card-drawer__source" data-testid="card-source">{detail.body}</pre>
              ) : sectionEntries.length > 0 ? (
                sectionEntries.map(([heading, text]) => {
                  // Quest-log timeline (WF-030 chunk 9, stretch) — "##
                  // Progress log" only, and only when it parses cleanly
                  // (parseProgressLog returns null rather than a partial
                  // list on any malformed line — see its doc comment).
                  // Every other section, and a Progress log that doesn't
                  // parse, renders through the existing MarkdownView path
                  // unchanged.
                  const progressEntries =
                    heading === "## Progress log"
                      ? parseProgressLog(text)
                      : null;
                  return (
                    <section key={heading} className="card-drawer__section">
                      <Label as="h3" className="card-drawer__section-heading">
                        {sectionLabel(heading)}
                      </Label>
                      {progressEntries ? (
                        <ol className="card-drawer__quest-log">
                          {progressEntries.map((entry, i) => (
                            <li
                              key={i}
                              className={
                                "card-drawer__quest-log-entry card-drawer__quest-log-entry--" +
                                ACCENT_GROUPS[i % ACCENT_GROUPS.length]
                              }
                            >
                              <span
                                className="card-drawer__quest-log-dot"
                                aria-hidden="true"
                              />
                              <span className="card-drawer__quest-log-text">
                                {entry.note}
                              </span>
                              <span className="card-drawer__quest-log-stamp">
                                {entry.timestamp}
                              </span>
                            </li>
                          ))}
                        </ol>
                      ) : (
                        <MarkdownView text={text} />
                      )}
                    </section>
                  );
                })
              ) : (
                <MarkdownView text={detail.body} />
              )}
                </div>
              </>
            )}
          </>
        )}
      </aside>
    </div>
  );
}

export default CardDetailDrawer;
