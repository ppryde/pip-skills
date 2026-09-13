/**
 * The Almoner — one triaged view of everything asking for your attention.
 *
 * An almoner received incoming petitions, judged which were genuine and
 * pressing, and distributed relief accordingly. This page does that for the
 * working day: several systems gathered, the noise discarded, what remains
 * laid out as the day actually happened.
 *
 * Read-only against every system it touches. Nothing is sent, replied to,
 * marked read, archived, assigned or resolved.
 *
 * Reading order is deliberate — summary before detail:
 *   1. the day band     "where did the time go"
 *   2. waiting on you   "who am I holding up"
 *   3. the day table    "what exactly"
 * The first two are answers; the table is the working surface.
 *
 * Unlike the Chronicle, this page owns its own fetch, and there is no poll: a
 * digest is several remote round trips, with a headless agent behind each
 * connector-backed source. "No schedule — refresh is manual" is a stated
 * non-goal of the plugin, not an omission.
 *
 * `groupDigest` (grouping by urgency rather than by time) is still exported
 * and tested but no longer rendered here — the table replaced it as the
 * primary view. It is one component away from returning as a toggle.
 */
import { useMemo } from "react";
import type { AlmonerStatus } from "../../api/types";
import { dayBand } from "../../board/almoner/band";
import { groupByDay } from "../../board/almoner/days";
import { failedSources, relativeArrived } from "../../board/almoner/digest";
import { SAMPLE_DIGEST } from "../../board/almoner/fixture";
import { whosWaiting } from "../../board/almoner/people";
import { useAlmonerDigest } from "../../board/almoner/useAlmoner";
import { Button } from "../../ui";
import Waylaid from "../Waylaid";
import DayBand from "./DayBand";
import DigestTable from "./DigestTable";
import WaitingStrip from "./WaitingStrip";

export interface AlmonerPageProps {
  status: AlmonerStatus | null;
  /** Render the sample digest instead of fetching (`#almoner?demo=1`). The
   * page says so in a banner — see `fixture.ts` on why it is labelled. */
  demo?: boolean;
}

export default function AlmonerPage({ status, demo = false }: AlmonerPageProps) {
  const live = useAlmonerDigest();

  const digest = demo ? SAMPLE_DIGEST : live.digest;
  const items = useMemo(() => digest?.items ?? [], [digest]);
  const days = useMemo(() => groupByDay(items), [items]);
  const people = useMemo(() => whosWaiting(items), [items]);
  // The band covers ONE day — a scatter across a fortnight is a different
  // chart, and this one answers "what shape did that day have".
  //
  // The newest day that actually has arrivals, though, not simply `days[0]`.
  // A day can exist with nothing to plot: `groupByDay` parks undated reconcile
  // items on today, so at 00:12 the newest day is a synthetic one holding a
  // single derived row and no arrival times at all. Reading `days[0]` there
  // gave `null` and the band silently vanished — the page looked broken for
  // the first hours of every day. The same guard covers a real day of nothing
  // but machine-mail rollups, which `dayBand` excludes by design.
  const band = useMemo(() => {
    for (const day of days) {
      const drawn = dayBand(day.items);
      if (drawn) return drawn;
    }
    return null;
  }, [days]);
  const failed = failedSources(digest?.sources);

  // "Installed but no sources" is a normal published state — the plugin ships
  // an empty source list — and must not read as "nothing needs you".
  const unconfigured = !demo && status?.installed === true && status?.configured === false;

  return (
    <div className={`almoner${live.loading ? " almoner--refreshing" : ""}`}>
      <div className="almoner__bar">
        {/* No heading here: the guild bar above names the page (TopBar's
            per-view title). The page name twice, one under the other, is a
            layout that has lost track of who owns it. */}
        <Button
          variant="primary"
          onClick={live.refresh}
          disabled={live.loading || demo}
          title="Gather from every configured source. Read-only — nothing is sent, replied to or marked read."
        >
          {live.loading ? "Gathering…" : "Gather"}
        </Button>
        {live.refreshedAt !== null && !demo && (
          <span className="almoner__stamp">
            gathered {relativeArrived(new Date(live.refreshedAt).toISOString())} ago
            {digest?.sources ? ` · ${digest.sources.length} sources` : ""}
          </span>
        )}
      </div>

      {demo && (
        <div className="almoner__notice almoner__notice--demo">
          <strong>Sample data.</strong> This is a fixture, not your inflow — the almoner
          CLI does not exist yet. Drop the <code>?demo=1</code> to see the real thing.
        </div>
      )}

      {live.error && <Waylaid error={live.error} onRetry={live.refresh} />}

      {/* A silently short digest is worse than a visible error: an empty list
          reads as "nothing needs you" whether or not a source fell over. */}
      {failed.length > 0 && (
        <div className="almoner__notice almoner__notice--failed">
          Could not reach <strong>{failed.join(", ")}</strong> — this digest is incomplete.
        </div>
      )}

      {unconfigured && (
        <div className="almoner__empty">
          <p className="almoner__empty-title">No sources configured.</p>
          <p>
            Add an <code>almoner.sources</code> list to your overseer{" "}
            <code>config.local.json</code> to tell the almoner where to gather from.
          </p>
        </div>
      )}

      {!unconfigured && digest === null && !live.loading && !live.error && (
        <div className="almoner__empty">
          <p className="almoner__empty-title">Nothing gathered yet.</p>
          <p>
            Press <strong>Gather</strong> to read every configured source. There is no
            timer and no background poll — the almoner looks only when asked.
          </p>
        </div>
      )}

      {digest !== null && days.length === 0 && !live.loading && (
        <div className="almoner__empty">
          <p className="almoner__empty-title">Nothing needs you.</p>
          <p>Every source answered and none of it was asking anything.</p>
        </div>
      )}

      {days.length > 0 && (
        <>
          <DayBand band={band} label={days[0].label} />
          <WaitingStrip people={people} />
          <DigestTable days={days} />
        </>
      )}

      {/* Said out loud, because an unexplained short list is indistinguishable
          from a quiet day — and on real mail the discarded pile is the
          overwhelming majority of what arrived. */}
      {digest?.suppressed !== undefined && digest.suppressed > 0 && (
        <p className="almoner__suppressed">
          <strong>{digest.suppressed}</strong> filtered out before ranking — newsletters,
          receipts, alerts and other mail no person wrote.
        </p>
      )}

      {digest?.ranked === false && days.length > 0 && (
        <p className="almoner__unranked">
          Unranked — the judging pass did not run, so rows sit in the order they arrived
          rather than by need.
        </p>
      )}
    </div>
  );
}
