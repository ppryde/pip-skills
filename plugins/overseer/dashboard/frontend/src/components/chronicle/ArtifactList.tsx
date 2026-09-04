/**
 * Published artifact pages — favicon, title as a link, when, and the
 * session that made it (on the page-level list). Untrusted strings from the
 * transcript render as text nodes only; the href is the parsed
 * `claude.ai/code/artifact/...` url or nothing.
 */
import type { ChronicleArtifact } from "../../api/types";
import { formatWhen } from "../../board/chronicle/format";

export interface ArtifactListProps {
  artifacts: ChronicleArtifact[];
  /** Show the owning session beside each page (page-level list). */
  showSession?: boolean;
  onOpenSession?: (id: string) => void;
}

export default function ArtifactList({ artifacts, showSession = false, onOpenSession }: ArtifactListProps) {
  if (artifacts.length === 0) {
    return <p className="chr-chart__empty">No artifacts published in this window.</p>;
  }
  return (
    <ul className="chr-artifacts" aria-label="Artifacts">
      {artifacts.map((a) => {
        const name = a.title ?? a.url ?? "untitled";
        return (
          <li key={`${a.session_id}:${a.url ?? a.ts}`} className="chr-artifacts__row">
            <span className="chr-artifacts__icon" aria-hidden="true">
              {a.favicon ?? "📄"}
            </span>
            <span className="chr-artifacts__body">
              {a.url ? (
                <a className="chr-artifacts__link" href={a.url} target="_blank" rel="noreferrer">
                  {name}
                </a>
              ) : (
                <span className="chr-artifacts__link chr-artifacts__link--dead" title="The published url never landed in the transcript">
                  {name}
                </span>
              )}
              {a.description && <span className="chr-artifacts__desc">{a.description}</span>}
              <span className="chr-artifacts__meta">
                {formatWhen(a.first_ts ?? a.ts)}
                {a.publishes > 1 && ` · ${a.publishes} publishes`}
                {showSession && (
                  <>
                    {" · "}
                    {onOpenSession ? (
                      <button type="button" className="chr-artifacts__session" onClick={() => onOpenSession(a.session_id)}>
                        {a.session_title ?? a.session_id.slice(0, 8)}
                      </button>
                    ) : (
                      a.session_title ?? a.session_id.slice(0, 8)
                    )}
                  </>
                )}
              </span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}
