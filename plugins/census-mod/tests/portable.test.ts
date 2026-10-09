import { expect, test } from 'claude-code/testing'
import { PYTHON_CANDIDATES, cacheLinesFromText, copyModeArgv, moveArgv, onWindows, pickPython, removeArgv, tailBytes, titleLinesFromText } from '../plugin/core/portable'
import { ingestArgv } from '../plugin/core/census'

test('python launchers are tried python3, python, py -3, and the first that runs --version wins', async () => {
  expect(PYTHON_CANDIDATES).toEqual([['python3'], ['python'], ['py', '-3']])
  const seen: string[][] = []
  const pick = (ok: string) => pickPython(async argv => (seen.push(argv), argv.join(' ') === ok))
  expect(await pick('python3 --version')).toEqual(['python3'])
  seen.length = 0
  expect(await pick('python --version')).toEqual(['python'])
  expect(seen).toEqual([['python3', '--version'], ['python', '--version']])
  seen.length = 0
  expect(await pick('py -3 --version')).toEqual(['py', '-3'])
  expect(seen.length).toBe(3)
})

test('none found is null; a probe that throws counts as not found', async () => {
  expect(await pickPython(async () => false)).toBeNull()
  expect(await pickPython(async () => { throw new Error('ENOENT') })).toBeNull()
})

test('ingest runs through the chosen launcher', async () => {
  expect(ingestArgv('/p/cli.py')).toEqual(['python3', '/p/cli.py', 'ingest'])
  expect(ingestArgv('C:\\p\\cli.py', ['py', '-3'])).toEqual(['py', '-3', 'C:\\p\\cli.py', 'ingest'])
})

test('move, remove and copy pick the platform from the path', async () => {
  expect(onWindows('C:\\Users\\x\\settings.json')).toBe(true)
  expect(onWindows('\\\\srv\\share\\s.json')).toBe(true)
  expect(onWindows('/home/u/settings.json')).toBe(false)
  expect(moveArgv('/a.tmp', '/a')).toEqual(['mv', '-f', '/a.tmp', '/a'])
  expect(moveArgv('C:\\a.tmp', 'C:\\a')).toBeNull() // never `cmd /c`: it would parse the path
  expect(removeArgv('/a')).toEqual(['rm', '-f', '/a'])
  expect(removeArgv('C:\\a')).toBeNull()
  expect(copyModeArgv('/a', '/b')).toEqual(['cp', '-p', '/a', '/b'])
  expect(copyModeArgv('C:\\a', 'C:\\b')).toBeNull()
})

test('the no-shell readers give what tail|grep gives', async () => {
  const text = 'x\n{"cache_creation":{"ephemeral_1h_input_tokens":5}} y {"cache_creation":{"a":1}}\n'
  expect(cacheLinesFromText(text)).toBe('"cache_creation":{"ephemeral_1h_input_tokens":5}\n"cache_creation":{"a":1}')
  expect(cacheLinesFromText('a'.repeat(100) + '"cache_creation":{"a":1}', 10)).toBe('')
  const t = '{"type":"user"}\n{"type":"custom-title","customTitle":"a"}\n{"type":"custom-title","customTitle":"b"}\n'
  expect(titleLinesFromText(t)).toBe('{"type":"custom-title","customTitle":"a"}\n{"type":"custom-title","customTitle":"b"}')
  expect(titleLinesFromText(t, 20)).toBe('')
})

import { censusDir, bundledCli, shadowDir, shadowStore } from '../plugin/core/census'
import { configRoot, transcriptPathFor } from '../plugin/core/name'
import { worktreeOf, watchPaths } from '../plugin/core/git'

test('a Windows home gives backslash paths all the way down', async () => {
  const win = { USERPROFILE: 'C:\\Users\\x' }
  expect(configRoot(win)).toBe('C:\\Users\\x\\.claude')
  expect(configRoot({ CLAUDE_CONFIG_DIR: 'D:\\cfg\\' })).toBe('D:\\cfg')
  expect(censusDir(win)).toBe('C:\\Users\\x\\.claude\\census')
  expect(censusDir({ ...win, CENSUS_STORE: '~\\store\\' })).toBe('C:\\Users\\x\\store')
  expect(censusDir({ ...win, CENSUS_STORE: 'D:\\store\\census.json' })).toBe('D:\\store')
  expect(shadowStore({ ...win, CENSUS_MOD_STORE: '~/shadow' })).toBe('C:\\Users\\x\\shadow')
  expect(shadowDir({ ...win, CENSUS_MOD_STORE: '~\\shadow\\s.json' })).toBe('C:\\Users\\x\\shadow')
  expect(transcriptPathFor('C:\\Users\\x\\.claude', 'C:\\repo', 's1')).toBe('C:\\Users\\x\\.claude\\projects\\C--repo\\s1.jsonl')
  expect(bundledCli('C:\\p\\census-mod\\')).toBe('C:\\p\\census-mod\\scripts\\cli.py')
  expect(bundledCli('/p/census-mod/')).toBe('/p/census-mod/scripts/cli.py')
})

test('POSIX paths are unchanged', async () => {
  expect(configRoot({ HOME: '/home/u/' })).toBe('/home/u/.claude')
  expect(censusDir({ HOME: '/home/u' })).toBe('/home/u/.claude/census')
  expect(transcriptPathFor('/', '/a/b', 's')).toBe('/projects/-a-b/s.jsonl')
})

test('git paths on Windows: forward-slash drive paths are absolute, and a linked worktree is found', async () => {
  expect(watchPaths({ exitCode: 0, stdout: 'C:/repo/.git\nC:/repo\n' })).toEqual(['C:/repo/.git/HEAD', 'C:/repo/.git/index'])
  expect(worktreeOf({ exitCode: 0, stdout: 'C:/repo/.git/worktrees/w\nC:/wt\n' })).toBe('C:/wt')
})

test('tail by bytes, not UTF-16 units', async () => {
  expect(tailBytes('abcdef', 3)).toBe('def')
  expect(tailBytes('abc', 10)).toBe('abc')
  expect(tailBytes('aé€😀', 4)).toBe('😀')        // 1+2+3+4 bytes: only the emoji fits
  expect(tailBytes('aé€😀', 7)).toBe('€😀')
  expect(tailBytes('aé€😀', 6)).toBe('😀')        // a cut mid-character drops that character
  expect(tailBytes('😀'.repeat(3), 8)).toBe('😀😀')
  // a write sitting before 64 KiB of multi-byte text is out of the window, as `tail -c` has it
  const old = '"cache_creation":{"ephemeral_1h_input_tokens":9}'
  expect(cacheLinesFromText(old + '€'.repeat(30000))).toBe('') // 90000 bytes after it
  expect(cacheLinesFromText(old + '€'.repeat(100))).toBe(old)
})
