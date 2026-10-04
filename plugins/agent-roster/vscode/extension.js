// agent-roster's VS Code helper: shows a tmux session in a terminal tab when
// the roster sends vscode://pip.agent-roster-vscode/attach?socket=S&name=N.
// A tab of this window already showing the session is focused; otherwise a
// new tab runs `tmux attach`. It runs nothing else, and only for names it can
// pass safely.
const vscode = require('vscode')
const fs = require('fs')
const { execFile } = require('child_process')

const SAFE = /^[\w.-]+$/
// A Dock-launched VS Code may not have Homebrew on PATH: find tmux itself.
const TMUX = ['/opt/homebrew/bin/tmux', '/usr/local/bin/tmux', '/usr/bin/tmux'].find(p => fs.existsSync(p))
// A client started from a tab's shell sits a level or two below it (zsh, a
// wrapper function's subshell); further up is VS Code itself.
const ANCESTOR_DEPTH = 4

const run = (file, args) =>
  new Promise(resolve => execFile(file, args, (err, stdout) => resolve(err ? '' : String(stdout))))

async function parentOf(pid) {
  return Number((await run('/bin/ps', ['-o', 'ppid=', '-p', String(pid)])).trim()) || 0
}

/** Every pid a few levels up from each of the session's attached tmux clients. */
async function clientLineage(socket, name) {
  const out = await run(TMUX, ['-L', socket, 'list-clients', '-t', `=${name}`, '-F', '#{client_pid}'])
  const lineage = new Set()
  for (const line of out.split('\n')) {
    let pid = Number(line.trim())
    for (let depth = 0; pid > 1 && depth <= ANCESTOR_DEPTH; depth++) {
      lineage.add(pid)
      pid = await parentOf(pid)
    }
  }

  return lineage
}

/** This window's terminal tab already showing the session, if any. */
async function tabShowing(socket, name) {
  const lineage = await clientLineage(socket, name)
  if (lineage.size === 0) return undefined
  for (const terminal of vscode.window.terminals) {
    const pid = await terminal.processId
    if (pid && lineage.has(pid)) return terminal
  }

  return undefined
}

exports.activate = context => {
  context.subscriptions.push(
    vscode.window.registerUriHandler({
      async handleUri(uri) {
        const query = new URLSearchParams(uri.query)
        const socket = query.get('socket') ?? ''
        const name = query.get('name') ?? ''
        if (uri.path !== '/attach' || !SAFE.test(socket) || !SAFE.test(name)) return
        if (!TMUX) {
          void vscode.window.showErrorMessage('agent-roster: tmux not found')
          return
        }
        const open = await tabShowing(socket, name)
        if (open) {
          open.show()
          return
        }
        const terminal = vscode.window.createTerminal({
          name: `tmux ${name}`,
          shellPath: TMUX,
          shellArgs: ['-L', socket, 'attach', '-t', `=${name}`],
          // Opened from inside tmux, an attach would refuse to nest.
          env: { TMUX: null },
        })
        terminal.show()
      },
    }),
  )
}

exports.deactivate = () => {}
