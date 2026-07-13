import type { Budget } from "../api/types";
import { formatTokens } from "../board/formatTokens";

export interface BudgetMeterProps {
  budget: Budget;
}

/**
 * 2x tripwire fires only when estimate is a positive number and actual >= 2x
 * it — that comparison is on the raw numbers. Displayed values are formatted
 * (see formatTokens.ts); the raw numbers are still available via `title` on
 * hover.
 */
function BudgetMeter({ budget }: BudgetMeterProps) {
  const { estimate, actual } = budget;
  const tripwire = estimate !== null && estimate > 0 && actual >= 2 * estimate;

  return (
    <span
      className={`budget-meter${tripwire ? " budget-meter--tripwire" : ""}`}
      data-tripwire={tripwire || undefined}
    >
      <span
        className="budget-meter__value"
        title={estimate !== null ? `${actual} / ${estimate}` : `${actual}`}
      >
        {estimate !== null
          ? `${formatTokens(actual)} / ${formatTokens(estimate)}`
          : formatTokens(actual)}
      </span>
      {tripwire && (
        <span
          className="budget-meter__flag"
          title="Actual is at least 2x the estimate"
        >
          2x
        </span>
      )}
    </span>
  );
}

export default BudgetMeter;
