import { expect, test } from 'claude-code/testing'
import { HOME_VARS_CHECKED, configRootOf, expandHome, homeOf, isAbsolute, joinPath, pathKey, sepOf, trimSeps } from '../plugin/core/home'

// The same tests run in census-mod, context-vigil-mod and agent-roster, against identical copies of core/home.ts.

test('home is HOME, else USERPROFILE, else HOMEDRIVE+HOMEPATH', async () => {
  expect(homeOf({ HOME: '/home/u', USERPROFILE: 'C:\\Users\\u' })).toBe('/home/u')
  expect(homeOf({ USERPROFILE: 'C:\\Users\\u', HOMEDRIVE: 'D:', HOMEPATH: '\\x' })).toBe('C:\\Users\\u')
  expect(homeOf({ HOMEDRIVE: 'C:', HOMEPATH: '\\Users\\u' })).toBe('C:\\Users\\u')
  expect(homeOf({})).toBeNull()
  expect(homeOf({ HOMEDRIVE: 'C:' })).toBeNull() // half a pair is no home
  expect(homeOf({ HOME: '  ', USERPROFILE: 'C:\\Users\\u' })).toBe('C:\\Users\\u') // blank is unset
})

test('the config dir is CLAUDE_CONFIG_DIR, else <home>/.claude, in the home\'s own separator', async () => {
  expect(configRootOf({ CLAUDE_CONFIG_DIR: '/cfg/', HOME: '/home/u' })).toBe('/cfg')
  expect(configRootOf({ HOME: '/home/u/' })).toBe('/home/u/.claude')
  expect(configRootOf({ USERPROFILE: 'C:\\Users\\x' })).toBe('C:\\Users\\x\\.claude')
  expect(configRootOf({ HOMEDRIVE: 'C:', HOMEPATH: '\\Users\\x\\' })).toBe('C:\\Users\\x\\.claude')
  expect(configRootOf({ CLAUDE_CONFIG_DIR: 'D:\\cfg\\' , USERPROFILE: 'C:\\Users\\x' })).toBe('D:\\cfg')
  expect(configRootOf({})).toBeNull()
  expect(configRootOf({ CLAUDE_CONFIG_DIR: '/' })).toBe('/')
})

test('no mixed separators: a backslash base keeps backslashes, a slash base keeps slashes', async () => {
  expect(joinPath('C:\\Users\\x', '.claude', 'sessions')).toBe('C:\\Users\\x\\.claude\\sessions')
  expect(joinPath('C:\\Users\\x\\', 'a/b')).toBe('C:\\Users\\x\\a\\b')
  expect(joinPath('/home/u', '.claude')).toBe('/home/u/.claude')
  expect(joinPath('/', 'projects')).toBe('/projects')
  expect(joinPath('C:\\', 'x')).toBe('C:\\x')
  expect(joinPath('/home/u/')).toBe('/home/u')
  expect(sepOf('C:\\Users\\x')).toBe('\\')
  expect(sepOf('C:/Users/x')).toBe('/')
  expect(sepOf('mixed\\and/slash')).toBe('/')
})

test('trailing separators of either kind go; the root stays', async () => {
  expect(trimSeps('/a/b//')).toBe('/a/b')
  expect(trimSeps('C:\\Users\\x\\\\')).toBe('C:\\Users\\x')
  expect(trimSeps('C:/Users/x/')).toBe('C:/Users/x')
  expect(trimSeps('/')).toBe('/')
  expect(trimSeps('C:\\')).toBe('C:\\')
  expect(trimSeps('C:')).toBe('C:\\')
  expect(trimSeps('\\\\server\\share\\')).toBe('\\\\server\\share')
})

test('~, ~/x and ~\\x expand with the same home; nothing else does', async () => {
  const win = { USERPROFILE: 'C:\\Users\\x' }
  expect(expandHome('~', win)).toBe('C:\\Users\\x')
  expect(expandHome('~\\shadow', win)).toBe('C:\\Users\\x\\shadow')
  expect(expandHome('~/shadow/a', win)).toBe('C:\\Users\\x\\shadow\\a')
  expect(expandHome('~/shadow', { HOME: '/home/u' })).toBe('/home/u/shadow')
  expect(expandHome('~other/x', win)).toBe('~other/x')
  expect(expandHome('/abs', win)).toBe('/abs')
  expect(expandHome('~/x', {})).toBe('~/x') // no home to expand with
})

test('absolute means / , a drive, or a UNC share', async () => {
  for (const p of ['/x', 'C:\\x', 'c:/x', '\\\\server\\share']) expect(isAbsolute(p)).toBe(true)
  for (const p of ['x', './x', 'C:x', '~/x']) expect(isAbsolute(p)).toBe(false)
})

test('compare on a normalised key: one separator, no trailing one, lower-case for drive and UNC paths only', async () => {
  expect(pathKey('C:\\Users\\X\\.Claude\\')).toBe(pathKey('c:/users/x/.claude'))
  expect(pathKey('\\\\Server\\Share')).toBe('//server/share')
  expect(pathKey('/Home/U/')).toBe('/Home/U') // POSIX is case-sensitive
  expect(pathKey('/')).toBe('/')
})

test('messages name the variables actually checked', async () => {
  expect(HOME_VARS_CHECKED).toBe('CLAUDE_CONFIG_DIR, HOME, USERPROFILE and HOMEDRIVE+HOMEPATH')
})
