import { Component } from "react";
import type { ReactNode } from "react";
import { Button } from "../ui";

interface ChunkLoadBoundaryProps {
  children: ReactNode;
}

interface ChunkLoadBoundaryState {
  failed: boolean;
}

/**
 * Catches a rejected `React.lazy` import — a 404 on the page's own chunk —
 * so it fails CONTAINED rather than taking the whole app down.
 *
 * `ChroniclePage` is code-split (App.tsx). Its chunk is fetched by hashed
 * filename the first time that tab is opened after mount; a tab left open
 * across a `dist/` rebuild (new hashes, old chunk file gone) throws on that
 * fetch, and a React error boundary is the only mechanism that can catch a
 * throw during render — an ordinary try/catch around JSX cannot, and
 * `<Suspense>` alone only covers the PENDING state, not a REJECTED one.
 * Without this, the reject unwinds past `<Suspense>` and unmounts
 * everything `<App/>` rendered — board and all — for a failure that only
 * concerns the one lazy page.
 *
 * A class component because `getDerivedStateFromError` has no hook
 * equivalent — there is no React error-boundary hook.
 */
export default class ChunkLoadBoundary extends Component<
  ChunkLoadBoundaryProps,
  ChunkLoadBoundaryState
> {
  state: ChunkLoadBoundaryState = { failed: false };

  static getDerivedStateFromError(): ChunkLoadBoundaryState {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return (
        <div className="chunk-load-error" role="alert">
          <p className="chunk-load-error__title">This page couldn't load.</p>
          <p className="chunk-load-error__body">
            The dashboard was updated since this tab was opened. Reloading
            fetches the current version.
          </p>
          <Button onClick={() => window.location.reload()}>Reload</Button>
        </div>
      );
    }
    return this.props.children;
  }
}
