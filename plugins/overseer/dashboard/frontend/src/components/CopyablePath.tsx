import { useEffect, useState } from "react";

export interface CopyablePathProps {
  path: string;
  /** Accessible name for the copy button; defaults to "Copy path". */
  copyLabel?: string;
}

const COPIED_MS = 1500;

/**
 * WF-071: a filesystem path that stays on one line however long it is. The
 * TAIL is what identifies a path (`…/overseer/ledger-poc-3f2a/board.db`), so
 * it is left-truncated — a leading ellipsis via `direction: rtl` +
 * `text-overflow: ellipsis` in styles.css — with the full path in the title
 * and a copy-to-clipboard button beside it. Copying is the dependable
 * action: a browser will not open a `file://` folder from an http(s) page,
 * so there is deliberately no "open" link here.
 */
function CopyablePath({ path, copyLabel = "Copy path" }: CopyablePathProps) {
  const [copied, setCopied] = useState(false);
  // "copied" shows for a moment, then reverts; React's own cleanup covers
  // an unmount mid-countdown.
  useEffect(() => {
    if (!copied) return;
    const t = window.setTimeout(() => setCopied(false), COPIED_MS);
    return () => window.clearTimeout(t);
  }, [copied]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(path);
      setCopied(true);
    } catch {
      // No clipboard (insecure context, permission denied): the path is
      // still selectable text, so there is nothing more to do here.
    }
  }

  return (
    <span className="copyable-path">
      {/* `&lrm;` pins the bidi direction of the text itself so the rtl
          truncation trick never reorders punctuation at the visible end. */}
      <code className="copyable-path__text" title={path} dir="rtl">
        &lrm;{path}&lrm;
      </code>
      <button type="button" className="copyable-path__copy" onClick={copy} aria-label={copyLabel}>
        {copied ? "copied" : "copy"}
      </button>
    </span>
  );
}

export default CopyablePath;
