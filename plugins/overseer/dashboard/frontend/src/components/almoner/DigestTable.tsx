import { useCallback, useState } from "react";
import type { AlmonerItem } from "../../api/types";
import type { DigestDay } from "../../board/almoner/days";
import { clockTime } from "../../board/almoner/days";
import { relativeArrived, rowState } from "../../board/almoner/digest";
import { Chip } from "../../ui";
import SourceIcon from "./SourceIcon";

/**
 * The digest as a day table — ordered by when things arrived, not by what
 * they are.
 *
 * Urgency stops being positional here and becomes signal carried three ways
 * at once: a spine down the row's left edge, a filled state chip, and (for
 * rows that still want you) a faint wash. Three channels because one is never
 * enough — the chip says "needs you" in words, so the colour is
 * reinforcement rather than the only carrier.
 *
 * ONE layout at every width. An earlier pass restacked into cards below the
 * house breakpoint, and the table simply vanishing on a narrow window was
 * more confusing than useful. The narrow case instead tightens the columns
 * (styles.css) so the same three columns fit a phone: the lead column and the
 * actions are fixed and small, and the conversation takes whatever is left.
 */
export interface DigestTableProps {
  days: DigestDay[];
}

/** What to call the app a row links out to. A derived reconcile item is not
 * FROM anywhere — its link points at the issue that provoked it. */
const APP_NAMES: Record<string, string> = {
  slack: "Slack",
  linear: "Linear",
  mail: "mail",
  notion: "Notion",
  almoner: "upstream",
};

function threadOf(item: AlmonerItem) {
  return item.messages ?? [];
}

function Labels({ item }: { item: AlmonerItem }) {
  const state = rowState(item);
  const alsoIn = (item.seen_in ?? []).filter((source) => source !== item.source);
  return (
    <span className="alm-row__labels">
      <Chip className="alm-lab alm-lab--src" data-source={item.source}>{item.source}</Chip>
      <Chip className="alm-lab">{item.context}</Chip>
      {/* The source chip carries the source's own colour (styles.css keys off
          `data-source`), so "where did this come from" is answerable without
          reading. It is a SECOND channel to the spine's, which stays the
          row's state — the two ask different questions and must not share
          an element. */}
      {item.count !== undefined && item.count > 1 && (
        <Chip className="alm-lab alm-lab--count">{item.count} messages</Chip>
      )}
      {item.asks && item.asks !== "reconcile" && <Chip className="alm-lab">{item.asks}</Chip>}
      {alsoIn.length > 0 && (
        <Chip className="alm-lab alm-lab--dupe">also in {alsoIn.join(", ")}</Chip>
      )}
      <Chip className={`alm-lab alm-lab--state alm-lab--${state.key}`}>{state.label}</Chip>
    </span>
  );
}

function Thread({ item }: { item: AlmonerItem }) {
  return (
    <div className="alm-thread">
      {threadOf(item).map((message, index) => (
        <div
          className={`alm-msg${message.who === "You" ? " alm-msg--mine" : ""}`}
          key={message.url ?? `${message.at ?? ""}-${index}`}
        >
          <div className="alm-msg__head">
            {message.who && <span className="alm-msg__who">{message.who}</span>}
            {message.at && <span className="alm-msg__when">{clockTime(message.at)}</span>}
            {/* Per-message permalink: a reply usually needs to start from one
                particular line, not the top of the conversation. */}
            {message.url && (
              <a className="alm-msg__link" href={message.url} target="_blank" rel="noreferrer">
                ↗
              </a>
            )}
          </div>
          <p className="alm-msg__text">{message.text}</p>
        </div>
      ))}
      <p className="alm-thread__foot">
        {/* The last-speaker rule, said out loud — it stops being invisible
            machinery. A rollup has no speaker at all, so it says why it was
            folded instead of claiming a conversation nobody had. */}
        {item.bundled === true
          ? "Folded together because no person wrote these."
          : item.awaiting === true
            ? "Their word was last — that is why this needs you."
            : "You spoke last — settled."}
      </p>
    </div>
  );
}

export default function DigestTable({ days }: DigestTableProps) {
  const [openIds, setOpenIds] = useState<ReadonlySet<string>>(() => new Set());

  const toggle = useCallback((id: string) => {
    setOpenIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  return (
    <div className="alm-tablewrap">
      <table className="alm-table">
        <thead>
          <tr>
            <th scope="col">When</th>
            <th scope="col">Conversation</th>
            <th scope="col">Go</th>
          </tr>
        </thead>
        {days.map((day) => (
          <tbody key={day.key}>
            <tr className="alm-table__dayrow">
              <th scope="colgroup" colSpan={3}>{day.label}</th>
            </tr>
            {day.items.map((item) => {
              const open = openIds.has(item.id);
              const state = rowState(item);
              // Only worth expanding when the row actually collapsed
              // something: a single message is shown in full by the excerpt.
              const expandable = threadOf(item).length > 1;
              return [
                <tr
                  key={item.id}
                  className={`alm-table__item alm-row--${state.key}`}
                  data-source={item.source}
                >
                  <td className="alm-row__lead">
                    <SourceIcon source={item.source} size={18} />
                    <span className="alm-row__time">{clockTime(item.arrived)}</span>
                  </td>
                  <td>
                    <Labels item={item} />
                    <span className="alm-row__title">{item.title}</span>
                    {item.excerpt && <span className="alm-row__ex">{item.excerpt}</span>}
                  </td>
                  <td className="alm-row__go">
                    {expandable && (
                      <button
                        type="button"
                        className="alm-row__chev"
                        aria-expanded={open}
                        aria-controls={`alm-thread-${item.id}`}
                        // The row's title is in the name because several rows
                        // legitimately collapse the same NUMBER of things —
                        // three "Show 3 messages" buttons on one page is
                        // ambiguous to anyone navigating by control name.
                        aria-label={
                          open
                            ? `Hide ${item.title}`
                            : `Show ${threadOf(item).length} messages in ${item.title}`
                        }
                        onClick={() => toggle(item.id)}
                      >
                        {open ? "▴" : "▾"}
                      </button>
                    )}
                    {item.url && (
                      <a
                        className="alm-row__open"
                        href={item.url}
                        target="_blank"
                        rel="noreferrer"
                        aria-label={`Open in ${APP_NAMES[item.source] ?? item.source}`}
                      >
                        ↗
                      </a>
                    )}
                  </td>
                </tr>,
                // The conversation opens INSIDE the table, not in a drawer:
                // the point of the day table is that nothing leaves the day.
                expandable ? (
                  <tr
                    key={`${item.id}-thread`}
                    className="alm-table__thread"
                    id={`alm-thread-${item.id}`}
                    hidden={!open}
                  >
                    <td />
                    <td colSpan={2}>
                      <Thread item={item} />
                    </td>
                  </tr>
                ) : null,
              ];
            })}
          </tbody>
        ))}
      </table>
      {/* The column shows wall-clock time, which is what a day table is for;
          the relative age is given here for a reader who cannot scan it. */}
      <p className="sr-only">
        {days[0]?.items[0] &&
          `Most recent arrival ${relativeArrived(days[0].items[0].arrived)} ago.`}
      </p>
    </div>
  );
}
