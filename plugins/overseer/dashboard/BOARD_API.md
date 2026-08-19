# overseer board API service

A LAN-only HTTP service that lets an `overseer` CLI running **inside a Docker
dev container** read and write the board (`board.db`) that lives on the
**host**. It is not the dashboard: no `frontend/dist/`, no browser UI, and no
MCP server. It exposes exactly one thing an `overseer --remote` client needs —
a token-gated passthrough that runs the real host CLI and relays its output.

## Run on the host

```bash
/Users/philip.pryde/repos/pip-skills/.venv/bin/python \
  plugins/overseer/dashboard/serve_board_api.py --root /path/to/host/repo
# prints: board API token: <TOKEN>   (auto-generated on the 0.0.0.0 bind)
```

Flags (all optional): `--root PATH` (default `.`) is the repo whose board to
serve; `--host HOST` (default `0.0.0.0`, binds every interface so a container
can reach it) and `--port PORT` (default `8771`). Set `OVERSEER_REMOTE_TOKEN`
in the launcher's environment to pin the token yourself instead of letting it
auto-generate one on a non-loopback bind.

## Point the container at it

Set in the container's environment:

```bash
export OVERSEER_REMOTE=http://host.docker.internal:8771
export OVERSEER_REMOTE_TOKEN=<TOKEN>
```

On Linux, `host.docker.internal` isn't resolvable by default — run the
container with `--add-host=host.docker.internal:host-gateway`.

## Use it

With `OVERSEER_REMOTE`/`OVERSEER_REMOTE_TOKEN` set, every `overseer` verb and
hook invocation in the container transparently forwards to the host board:

```bash
overseer board
overseer set-stage WF-1 done
```

(Interactive verbs, e.g. `clear`, must pass `--yes` — there's no TTY on the
host side of the forward to prompt against.)

## Security

- **LAN-only source guard** — a middleware rejects any caller whose source
  address isn't private/loopback/link-local with `403`, before any auth
  check runs. The service never answers a caller outside the LAN, no matter
  what host/port it's bound to. **There is no override for this guard.**
- **Token auth** — mutating/exec requests require a matching
  `X-Overseer-Token` header (the same token printed at launch, or the one you
  set via `OVERSEER_REMOTE_TOKEN`). A missing/wrong token is rejected with
  `401`.
- Never expose this service beyond your LAN (no port-forwarding it to the
  internet, no reverse proxy without equivalent auth) — the LAN guard is the
  only thing standing between "dev container on my machine" and "anyone who
  can route to this host."

## Dependency note

The container's `overseer` install needs `httpx` — it's only imported on the
`--remote` code path (`plugins/overseer/scripts/remote.py`), so a normal
local (non-remote) install doesn't need it, but a container that will use
`--remote`/`OVERSEER_REMOTE` does.

## Verified

Smoke-tested end to end against a scratch repo (loopback bind, since
loopback passes the LAN guard the same as any other private address):
launched the service, ran `overseer new-card --title "smoke via remote"`
via `OVERSEER_REMOTE`/`OVERSEER_REMOTE_TOKEN` from a separate process, got
`WF-001` back with exit 0, and confirmed the card on the host board via
`overseer --root <scratch> board`. Confirmed `/api/exec` returns `401` for
a missing/wrong `X-Overseer-Token` and `200` with the correct one.
