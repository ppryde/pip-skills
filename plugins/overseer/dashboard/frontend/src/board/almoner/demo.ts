import type { AlmonerDigest } from "../../api/types";
import { SAMPLE_DIGEST } from "./fixture";

/**
 * Which digest `?demo=1` shows.
 *
 * Two files, for two incompatible jobs:
 *
 *  - `fixture.ts` SHIPS. This repo is public, so every name, subject, link and
 *    number in it is invented. It exists so the page can be seen and argued
 *    with before the almoner CLI does.
 *  - `fixture.local.ts` does NOT ship — it is gitignored — and holds a
 *    developer's own gathered inflow. Judging the design needs real content:
 *    the invented fixture cannot tell you whether a rollup's excerpt is
 *    genuinely enough to dismiss on, because its excerpts were written by
 *    someone who already knew the answer.
 *
 * The local file wins when it exists. `import.meta.glob` is what makes that
 * optional — a bare import of a missing module fails the build, while a glob
 * that matches nothing is simply an empty object.
 */
const overrides = import.meta.glob<{
  SAMPLE_DIGEST?: AlmonerDigest;
  LOCAL_MARKER?: string;
}>(
  "./fixture.local.ts",
  { eager: true }
);

/**
 * The shipped fixture is deliberately used under test even when a local
 * override is present.
 *
 * Otherwise the suite asserts against whatever happens to be in one
 * developer's inbox this morning: it would pass on their machine, fail in CI,
 * and fail differently tomorrow. A private file must never be able to decide
 * whether the tests pass.
 */
const underTest = import.meta.env.MODE === "test";

export const DEMO_DIGEST: AlmonerDigest =
  (!underTest && Object.values(overrides)[0]?.SAMPLE_DIGEST) || SAMPLE_DIGEST;

/** True when the page is showing someone's real inflow rather than the
 * invented sample — the banner says which, because a page that cannot tell
 * you whose data you are looking at is the one way this could mislead. */
export const DEMO_IS_LOCAL = DEMO_DIGEST !== SAMPLE_DIGEST;

/**
 * The marker the local override declares, re-exported so that bundling the
 * override necessarily carries this string into `dist/`.
 *
 * That is the whole point of it. `dist/` is COMMITTED, so a build run on a
 * machine that happens to have a local override compiles someone's real inbox
 * into a public repo — which is not hypothetical: it happened, on this branch,
 * and was caught by grepping the built asset rather than by any test.
 * `backend/tests/test_dist_no_local_fixture.py` now greps for this marker, so
 * a dist built with an override cannot be committed with the suite green.
 *
 * `undefined` whenever no override exists, which is every clean checkout.
 */
export const LOCAL_MARKER: string | undefined =
  Object.values(overrides)[0]?.LOCAL_MARKER;
