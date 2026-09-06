import type { Insight } from "../../board/chronicle/insights";

/** Counsel from the elders: the window's token-efficiency insights.
 *
 * Closed, a row is a figure, its verdict in a word, a title and one line of
 * counsel — enough to know whether to care. Open, it adds the supporting
 * figures, any breakdown, and the levers worth knowing about. Detail hides
 * behind simplicity: the resolutions are options, never a to-do list, and
 * nothing is shown unasked. Native `<details>` so the toggle is a real
 * button to the keyboard and assistive tech without any wiring. */
export default function CounselPanel({ insights }: { insights: Insight[] }) {
  return (
    <section className="chr-panel chr-panel--wide chr-counsel" style={{ ["--chr-hue" as string]: "var(--chr-turns)" }}>
      <h3 className="chr-panel__title">Counsel from the elders</h3>
      <p className="chr-panel__sub">What these numbers say about token efficiency. Open a row for the levers.</p>
      <ul className="chr-counsel__list">
        {insights.map((i) => {
          const hasMore = Boolean(i.detail || (i.rows && i.rows.length > 0) || (i.resolutions && i.resolutions.length > 0));
          const head = (
            <>
              <span className="chr-counsel__figure">
                <span className="chr-counsel__value">{i.value}</span>
                <span className="chr-counsel__verdict">{i.verdictWord}</span>
              </span>
              <span className="chr-counsel__head">
                <span className="chr-counsel__title">{i.title}</span>
                <span className="chr-counsel__counsel">{i.counsel}</span>
              </span>
            </>
          );
          return (
            <li key={i.id} className="chr-counsel__item" data-verdict={i.verdict}>
              {hasMore ? (
                <details className="chr-counsel__disclosure">
                  <summary className="chr-counsel__summary" aria-label={`${i.title}: ${i.value}, ${i.verdictWord}`}>
                    {head}
                    <span className="chr-counsel__chevron" aria-hidden="true" />
                  </summary>
                  <div className="chr-counsel__more">
                    {i.detail && <p className="chr-counsel__detail">{i.detail}</p>}
                    {i.rows && i.rows.length > 0 && (
                      <table className="chr-counsel__rows">
                        {i.rowHeadings && (
                          <thead>
                            <tr>
                              <th scope="col" className="sr-only">Model</th>
                              <th scope="col" className="chr-num">{i.rowHeadings.value}</th>
                              {i.rowHeadings.share && (
                                <th scope="col" className="chr-num">{i.rowHeadings.share}</th>
                              )}
                            </tr>
                          </thead>
                        )}
                        <tbody>
                          {i.rows.map((r) => (
                            <tr key={r.label} className="chr-counsel__row" title={r.detail}>
                              <th scope="row">{r.label}</th>
                              <td className="chr-num">{r.value}</td>
                              {i.rowHeadings?.share && <td className="chr-num chr-counsel__share">{r.share ?? "—"}</td>}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                    {i.facts && i.facts.length > 0 && (
                      <div className="chr-counsel__facts">
                        <p className="chr-counsel__levers-title">In this window</p>
                        <ul className="chr-counsel__fact-list">
                          {i.facts.map((f) => (
                            <li key={f} className="chr-counsel__fact">
                              {f}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {i.resolutions && i.resolutions.length > 0 && (
                      <div className="chr-counsel__levers">
                        <p className="chr-counsel__levers-title">What you could do</p>
                        <ul className="chr-counsel__lever-list">
                          {i.resolutions.map((r) => (
                            <li key={r.title} className="chr-counsel__lever">
                              <span className="chr-counsel__lever-title">{r.title}</span>
                              <span className="chr-counsel__lever-body">{r.body}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                </details>
              ) : (
                <div className="chr-counsel__summary chr-counsel__summary--static">{head}</div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
