import type { Budget } from "../api/types";

export interface BudgetMeterProps {
  budget: Budget;
}

/** 2x tripwire fires only when estimate is a positive number and actual >= 2x it. */
function BudgetMeter({ budget }: BudgetMeterProps) {
  const { estimate, actual } = budget;
  const tripwire = estimate !== null && estimate > 0 && actual >= 2 * estimate;

  return (
    <span
      className={`budget-meter${tripwire ? " budget-meter--tripwire" : ""}`}
      data-tripwire={tripwire || undefined}
    >
      <span className="budget-meter__value">
        {estimate !== null ? `${actual} / ${estimate}` : `${actual}`}
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
