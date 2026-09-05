import { useEffect, useState } from "react";
import { Button } from "../ui";
import backpackIcon from "../assets/ui-icons/backpack.png";

/**
 * The "Failed to fetch" state, in the guild's voice: the messenger to the
 * server has been waylaid and riders keep going out until one gets through.
 * Shared by the board and the Chronicle page in place of a bare red line.
 *
 * A slim red-tinted torn-note strip with a compass whose NEEDLE turns — drawn
 * as SVG in the top bar's icon style so the needle is its own part (the
 * compass PNG is one flat image). The raw error and the retry countdown stay
 * as a quiet detail line, so the whimsy never hides the fact. The "Send a
 * rider" button carries the pack's backpack — the rider's kit; the pack has
 * no horse, and a drawn one read as nothing at 16px. Motion pauses under
 * prefers-reduced-motion (styles.css).
 */
export interface WaylaidProps {
  /** The raw failure, verbatim ("Failed to fetch") — kept visible. */
  error: string;
  /** How often the owning hook retries by itself; drives the countdown. */
  retryEverySeconds: number;
  /** "Send a rider": retry now. */
  onRetry: () => void;
}

/** Cream disc, four pips, olive needle — the icon pack's compass, redrawn so
 * the needle group can spin. */
function CompassSeeking() {
  return (
    <svg className="waylaid__compass" viewBox="0 0 64 64" width="36" height="36" aria-hidden="true">
      <circle cx="32" cy="32" r="29" className="waylaid__compass-face" />
      <circle cx="32" cy="32" r="24" className="waylaid__compass-ring" />
      <circle cx="32" cy="9.5" r="1.8" className="waylaid__compass-pip" />
      <circle cx="32" cy="54.5" r="1.8" className="waylaid__compass-pip" />
      <circle cx="9.5" cy="32" r="1.8" className="waylaid__compass-pip" />
      <circle cx="54.5" cy="32" r="1.8" className="waylaid__compass-pip" />
      <g className="waylaid__needle" data-testid="waylaid-needle">
        <polygon points="32,12 37.5,32 26.5,32" className="waylaid__needle-north" />
        <polygon points="32,52 37.5,32 26.5,32" className="waylaid__needle-south" />
        <circle cx="32" cy="32" r="2.6" className="waylaid__compass-pip" />
      </g>
    </svg>
  );
}

export default function Waylaid({ error, retryEverySeconds, onRetry }: WaylaidProps) {
  // Counts down to the owning hook's next automatic retry and wraps round,
  // reset whenever the error text changes (a fresh failure = a fresh rider).
  const [left, setLeft] = useState(retryEverySeconds);
  useEffect(() => {
    setLeft(retryEverySeconds);
    const id = setInterval(() => {
      setLeft((n) => (n <= 1 ? retryEverySeconds : n - 1));
    }, 1000);
    return () => clearInterval(id);
  }, [error, retryEverySeconds]);

  return (
    <div className="waylaid" role="alert">
      <CompassSeeking />
      <div className="waylaid__text">
        <p className="waylaid__title">The messenger has been waylaid.</p>
        <p className="waylaid__body">
          Our courier to the server hasn't come back. We'll keep sending riders until one makes it through.
        </p>
        <p className="waylaid__detail">
          {error} · another rider leaves in {left}s
        </p>
      </div>
      <Button className="waylaid__btn" onClick={onRetry}>
        {/* rpg-icons pack "backpack" — decorative (`alt=""`), the accessible
            name stays "Send a rider". */}
        <img src={backpackIcon} alt="" className="waylaid__pack" />
        Send a rider
      </Button>
    </div>
  );
}
