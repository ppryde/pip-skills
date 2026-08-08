import type { RepoEntry } from "../api/types";

export interface UnbegunHoldingProps {
  /** The selected repo entry (WF-032) — supplies the display label AND the
   * filesystem root the `overseer init` command below names verbatim. */
  repo: RepoEntry;
  /** Live census session count for this root (mirrors `repo.live_sessions`;
   * threaded as its own prop, matching how `party`/other derived counts are
   * handed down explicitly elsewhere in App.tsx, rather than reaching back
   * into `repo` inside this component). */
  liveSessions: number;
}

function pluralizeAdventurers(n: number): string {
  return n === 1 ? "adventurer" : "adventurers";
}

/**
 * Quest-themed empty state for an "unbegun" repo (WF-032): `/api/repos`
 * discovered this root because census sees live agent sessions in it, but
 * `overseer init` has never been run there, so no board.db exists yet.
 *
 * Rendered by App.tsx INSTEAD OF `<Board/>` whenever the selected repo has
 * `has_board: false` — never alongside it, and never behind a `useBoard`
 * fetch: that call is hard-gated off for exactly this case (see
 * `useBoard`'s `enabled` param), since the backend 400s `/api/board` for an
 * unbegun root.
 */
function UnbegunHolding({ repo, liveSessions }: UnbegunHoldingProps) {
  const adventurerWord = pluralizeAdventurers(liveSessions);

  return (
    <div className="unbegun-holding">
      <div className="unbegun-holding__panel">
        <p className="unbegun-holding__glyph" aria-hidden="true">
          🗺️
        </p>
        <h2 className="unbegun-holding__title">
          Your quest has not yet begun in <em>{repo.label}</em>.
        </h2>
        <p className="unbegun-holding__body">
          {liveSessions} {adventurerWord} already roam these lands, but no
          Guild Board has been raised here.
        </p>
        <p className="unbegun-holding__body">
          To open the board and begin chronicling quests, run{" "}
          <code className="unbegun-holding__command">overseer init</code> in{" "}
          <code className="unbegun-holding__command">{repo.root}</code> (or
          invoke the overseer skill there).
        </p>
      </div>
    </div>
  );
}

export default UnbegunHolding;
