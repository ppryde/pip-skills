# Remote use from a dev container (`--remote`)

Port 8771 and `OVERSEER_DASHBOARD_TOKEN` are retired (BREAKING, overseer 0.30.0).
There is one server, the dashboard, on port 8770.

- **Server (host):** `dashboard/serve.py --host 0.0.0.0`. The exec token is
  `OVERSEER_REMOTE_TOKEN` in the server's environment (16+ characters) or, when
  unset, a minted token persisted at `<root>/.overseer/remote-token` (`0600`).
  It is never printed. `OVERSEER_DASHBOARD_TOKEN` is the dashboard's own gate
  and does not open exec.
- **Client (container):** `OVERSEER_REMOTE=http://host.docker.internal:8770`.
  `OVERSEER_REMOTE_TOKEN` must hold the same token, unless the container
  mounts the repo, where the CLI reads `.overseer/remote-token` itself.
- **Refused over `--remote`:** `bootstrap` and `dispatch-prep` (they run git;
  WF-300), `init`, `backup`, `restore`, `clear`, `claude-dirs`, `merge-boards`
  and the `*-hook` verbs except `pretool-hook`. Run those on the host. Archived
  boards are never targets. A value starting `--file` is refused.
- `--file` and `--text-file` work: the client reads the file and sends it as
  `--text -`.

Threat table and migration: `dashboard/README.md`.
