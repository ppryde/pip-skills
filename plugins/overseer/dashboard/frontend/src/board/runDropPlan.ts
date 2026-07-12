/**
 * Issues a `DropPlan`'s calls through the ONE mutation entrypoint,
 * `useBoard().mutate`. This is the only place a drag's resulting api calls
 * are made — Board.tsx never calls `setOrder`/`move` + setState itself.
 *
 * A plan with 1+ calls is dispatched as a SINGLE `mutate()` invocation (so
 * the in-flight lock/request-counter covers the whole sequence, not each
 * call individually); the calls run sequentially and the LAST call's
 * response is what `mutate` ends up applying — matching the stage-move case
 * (`move({stage})` then `setOrder`, re-rendered from the final response).
 *
 * Returns that same final response (or `undefined` for a no-op plan, or if
 * the mutation errored — `mutate` swallows the throw and surfaces it via its
 * own `error` state instead of rejecting) so `Board.tsx` can do read-only
 * post-hoc reconciliation (comparing the dragged card's resulting lane
 * against the drop target). This does NOT bypass the single-mutation-entry
 * rule: the response is only ever applied to board state by `mutate` itself;
 * the caller just gets to read the value `fn` already computed.
 */
import { move, setOrder } from "../api/client";
import type { BoardResponse } from "../api/types";
import type { DropPlan } from "./dragPlan";

export async function runDropPlan(
  plan: DropPlan,
  mutate: (fn: () => Promise<BoardResponse>) => Promise<void>
): Promise<BoardResponse | undefined> {
  if (plan.calls.length === 0) return undefined;

  let response: BoardResponse | undefined;
  await mutate(async () => {
    for (const call of plan.calls) {
      response =
        call.kind === "setOrder"
          ? await setOrder(call.id, call.order)
          : await move(call.id, call.body);
    }
    // Non-null: plan.calls.length > 0 is guaranteed by the guard above, so
    // the loop runs at least once and `response` is always assigned.
    return response as BoardResponse;
  });
  return response;
}
