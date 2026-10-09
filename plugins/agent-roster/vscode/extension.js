// agent-roster's VS Code helper: shows a tmux session in a terminal tab when
// the roster sends vscode://pip.agent-roster-vscode/attach?socket=S&name=N.
// A tab of this window already showing the session is focused; otherwise a
// new tab runs `tmux attach`. It runs nothing else, and only for names it can
// pass safely.
const vscode = require('vscode')
const fs = require('fs')
const { execFile } = require('child_process')

// No quotes or spaces, no leading dash, not `.` or `..`: as the roster checks.
const SAFE = /^(?!-)(?!\.+$)[\w.-]+$/
// The roster writes a one-time token here just before it sends a link; a
// link without it (one any web page could open) does nothing.
const NONCE_FILE = require('path').join(require('os').homedir(), '.cache', 'agent-roster', 'attach-nonce')

/** Whether the link carries the token the roster left, which is spent either way. */
function spendNonce(given) {
  let expected = ''
  try {
    expected = fs.readFileSync(NONCE_FILE, 'utf8').trim()
    fs.unlinkSync(NONCE_FILE)
  } catch {
    return false
  }

  return expected.length >= 16 && given === expected
}
// A Dock-launched VS Code may not have Homebrew on PATH: find tmux itself,
// the usual places first, then the extension host's PATH (MacPorts, Nix).
const TMUX = [
  '/opt/homebrew/bin/tmux',
  '/usr/local/bin/tmux',
  '/usr/bin/tmux',
  ...(process.env.PATH ?? '')
    .split(require('path').delimiter)
    .filter(Boolean)
    .map(dir => require('path').join(dir, 'tmux')),
].find(p => fs.existsSync(p))
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

// Each window says which folders it shows, so the roster can tell whether a
// repo is open somewhere and raise that window, rather than open a new one.
// One file per window, named for its extension host's pid; gone when the
// window closes (and ignored by the roster once that pid is dead).
const WINDOWS_DIR = require('path').join(require('os').homedir(), '.cache', 'agent-roster', 'vscode-windows')
const windowFile = require('path').join(WINDOWS_DIR, `${process.pid}.json`)

function announceWindow() {
  const folders = (vscode.workspace.workspaceFolders ?? [])
    .filter(f => f.uri.scheme === 'file')
    .map(f => f.uri.fsPath)
  try {
    fs.mkdirSync(WINDOWS_DIR, { recursive: true })
    fs.writeFileSync(windowFile, JSON.stringify({ pid: process.pid, folders }))
  } catch {
    // The roster then falls back to a Terminal window; nothing else depends on it.
  }
}

function retractWindow() {
  try {
    fs.unlinkSync(windowFile)
  } catch {
    // Already gone.
  }
}

exports.activate = context => {
  announceWindow()
  context.subscriptions.push(vscode.workspace.onDidChangeWorkspaceFolders(announceWindow))
  context.subscriptions.push(
    vscode.window.registerUriHandler({
      async handleUri(uri) {
        const query = new URLSearchParams(uri.query)
        const socket = query.get('socket') ?? ''
        const name = query.get('name') ?? ''
        if (uri.path !== '/attach' || !SAFE.test(socket) || !SAFE.test(name)) return
        if (!spendNonce(query.get('nonce') ?? '')) return
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

exports.deactivate = retractWindow
