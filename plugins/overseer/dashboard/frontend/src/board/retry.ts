/**
 * How hard to keep trying, and when to stop.
 *
 * Pure and DOM-free so the policy can be read and tested on its own — the
 * hooks import the schedule, they do not invent one.
 *
 * The behaviour this replaces: the board polled every 5s forever and the
 * banner said "we'll keep sending riders until one makes it through", which
 * was literally true. A stopped backend meant an alarming red strip and an
 * endless stream of doomed requests, and a REFUSED DASHBOARD TOKEN meant the
 * same — even though no number of identical retries can ever be accepted.
 */

/** Automatic retries AFTER the first failure. The first request is not a
 * retry, so the worst case is six requests: one plus these five. */
export const MAX_RETRIES = 5;

/**
 * Seconds to wait before retry `n` (1-based), doubling from 2s and capped
 * at 30: 2, 4, 8, 16, 30 — a minute of trying in total.
 *
 * Capped rather than uncapped-exponential because the thing being waited on
 * is usually a local server being restarted: past half a minute the extra
 * patience buys nothing a person would not rather trigger themselves, and an
 * uncapped schedule quickly reaches delays long enough to look hung.
 */
export function backoffSeconds(retry: number): number {
  return Math.min(30, 2 ** Math.max(1, retry));
}

export type FailureKind =
  /** Worth another rider — the request never landed, or the server is ill. */
  | "retryable"
  /** The gate refused us. An identical retry can only be refused identically. */
  | "auth"
  /** We asked for something the server will never accept (a 4xx that is not
   * an auth failure). Retrying is equally pointless, but the copy differs:
   * this is a bug or a stale client, not a credentials problem. */
  | "rejected"
  /** The person pressed Cancel. Not a failure at all. */
  | "aborted";

/** An `AbortController.abort()` rejection, however the browser spells it. */
function isAbort(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === "AbortError") ||
    (error instanceof Error && error.name === "AbortError")
  );
}

/**
 * Which of the four a rejection is.
 *
 * A rejection with no status never reached the server — offline, server
 * down, DNS — and is the classic retryable case (`TypeError: Failed to
 * fetch`). A 5xx is the server admitting it is having a bad time, which a
 * restart usually cures, so that retries too. 408 and 429 are explicit
 * "come back later" statuses and retry by their own definition.
 *
 * `status` is read structurally rather than via `instanceof ApiError` so
 * this module stays free of the api client (and so a re-thrown or
 * structured-cloned error is still classified correctly).
 */
export function classifyFailure(error: unknown): FailureKind {
  if (isAbort(error)) return "aborted";
  const status = (error as { status?: unknown } | null)?.status;
  if (typeof status !== "number") return "retryable";
  if (status === 401 || status === 403) return "auth";
  if (status === 408 || status === 429 || status >= 500) return "retryable";
  if (status >= 400) return "rejected";
  return "retryable";
}

/** Whether a failure of this kind earns another attempt at all. */
export function isRetryable(kind: FailureKind): boolean {
  return kind === "retryable";
}
