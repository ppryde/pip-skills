// agent-roster's VS Code helper: opens a terminal tab attached to a tmux
// session when the roster sends vscode://pip.agent-roster-vscode/attach?socket=S&name=N.
// It runs nothing but `tmux attach`, and only for names it can pass safely.
const vscode = require('vscode')
const fs = require('fs')

const SAFE = /^[\w.-]+$/
// A Dock-launched VS Code may not have Homebrew on PATH: find tmux itself.
const TMUX = ['/opt/homebrew/bin/tmux', '/usr/local/bin/tmux', '/usr/bin/tmux'].find(p => fs.existsSync(p))

exports.activate = context => {
  context.subscriptions.push(
    vscode.window.registerUriHandler({
      handleUri(uri) {
        const query = new URLSearchParams(uri.query)
        const socket = query.get('socket') ?? ''
        const name = query.get('name') ?? ''
        if (uri.path !== '/attach' || !SAFE.test(socket) || !SAFE.test(name)) return
        if (!TMUX) {
          void vscode.window.showErrorMessage('agent-roster: tmux not found')
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
