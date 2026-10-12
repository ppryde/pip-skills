```pip-agents-result
{"result":"pip-agents/1","kind":"test","persona":"verifier","ref":"verify-export","status":"ok","summary":"FAIL: 1 of 4 tests","checked":[".venv/bin/pytest -q tests/test_export.py"],"unchecked":[],"out_of_lens":[],"injection_attempts":[],"payload":{"outcome":"fail","gates":[{"command":".venv/bin/pytest -q tests/test_export.py","exit_code":1,"passed":3,"failed":1,"skipped":0}],"failures":[{"test":"tests/test_export.py::test_quotes","file":"tests/test_export.py","line":14,"message":"AssertionError: '\"a,b\"' != 'a,b'"}]}}
```
