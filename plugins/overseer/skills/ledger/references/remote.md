# Remote use from a dev container (`--remote`)

Port 8771 and `OVERSEER_DASHBOARD_TOKEN` are retired (BREAKING, overseer 0.30.0).
There is one server, the dashboard, on port 8770.

- **Server (host):** `dashboard/serve.py --host 0.0.0.0`. The exec token is
  `OVERSEER_REMOTE_TOKEN` in the server's environment (16+ characters) or, when
  unset, a minted token persisted at `<root>/.overseer/remote-token` (`0600`).
  It is never printed. The dashboard's own gate has a separate token
  (`OVERSEER_DASHBOARD_TOKEN`, else `.overseer/dashboard-token` on a non-loopback
  bind); it does not open exec.
- **Client (container):** `OVERSEER_REMOTE=http://host.docker.internal:8770`.
  `OVERSEER_REMOTE_TOKEN` must hold the same token, unless the container
  mounts the repo, where the CLI reads `.overseer/remote-token` itself.
- **Refused over `--remote`:** `init`, `backup`, `restore`, `clear`,
  `claude-dirs`, `merge-boards` and the `*-hook` verbs except `pretool-hook`.
  Run those on the host. Archived boards are never targets. A value starting
  `--file` is refused.
- **`bootstrap` and `dispatch-prep` run their git in the container** (WF-300):
  the client creates the worktree, takes the review diff and writes the bundles
  itself, and only the git-free board verbs (`bootstrap-begin`, `bootstrap-finish`,
  `dispatch-record`) reach the host. Run them from a checkout of the repo in the
  container, and keep every round of a card in the one container that
  bootstrapped it: set `worktree_dir` in `.overseer/config.json` to a path inside
  the mounted repo, or the worktree is lost with a short-lived container. If
  `bootstrap` stops after creating the worktree ("card ... is at bootstrap on the
  host"), rerun `bootstrap --card <id>`; the existing worktree is adopted. The
  host and the container must both run overseer 0.31.0 or later.
- `resume`, `handoff` and `handover` cannot see the container's git: they print
  `not checked, remote` for a worktree and say nothing about a branch.
- `--file` and `--text-file` work: the client reads the file and sends it as
  `--text -`.

Threat table and migration: `dashboard/README.md`.
