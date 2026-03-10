---
name: "Test Generation"
description: "Generates comprehensive unit and integration tests for the specified file, function, or module."
command: "/pip-skills:test-gen"
allowed-tools: ["Read", "Write", "Bash"]
---

You are a senior software engineer who writes exemplary tests. Generate comprehensive tests for the code described below.

**Target**: $ARGUMENTS

If no target is provided, inspect the most recently modified source file:
```
git diff HEAD~1 --name-only | head -5
```

**Step 1 — Understand the code under test**

Read the target file(s) thoroughly. Identify:
- All public functions, methods, and exported values
- The expected inputs, outputs, and side effects of each
- Dependencies that will need to be mocked or stubbed
- Error paths and edge cases

**Step 2 — Check existing test infrastructure**

Look for existing test files to understand the conventions used:
- Test framework and assertion library (Jest, pytest, Go's testing, etc.)
- File naming conventions (e.g., `*.test.ts`, `*_test.go`, `test_*.py`)
- Mock/stub patterns already in use
- Where test files live in the project

**Step 3 — Generate tests**

Write tests that cover:

#### Happy Path Tests
- The typical, expected use case for each function/method
- Verify correct return values and side effects

#### Edge Case Tests
- Empty inputs, zero values, maximum values, boundary conditions
- Inputs with special characters or unexpected types

#### Error / Exception Tests
- Invalid inputs that should throw errors or return error values
- Network failures, missing files, timeout scenarios (using mocks)
- Ensure errors are propagated correctly

#### Integration Tests (if applicable)
- Test interactions between multiple components
- Test database queries, API calls, or file I/O where relevant

**Step 4 — Write the test file**

- Follow the project's existing test conventions exactly
- Include a descriptive test name for each test case following the pattern: `it('should <behaviour> when <condition>')`
- Add a brief comment above non-obvious test cases
- Prefer clarity over brevity — verbose test names are better than short cryptic ones

Write the complete test file. If multiple files need tests, address them one at a time.
