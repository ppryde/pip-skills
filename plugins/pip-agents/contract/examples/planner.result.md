```pip-agents-result
{"result":"pip-agents/1","kind":"plan","persona":"planner","ref":"plan-export","status":"ok","summary":"2 steps, tests first","checked":["/tmp/pip-agents/p1/task.md","app/export.py:1-80"],"unchecked":[],"out_of_lens":[],"injection_attempts":[],"payload":{"outcome":"done","chunks":2,"steps":[{"title":"Failing test for CSV quoting","files":["tests/test_export.py"],"check":"pytest tests/test_export.py fails on quoting"},{"title":"Quote fields in write_row","files":["app/export.py"],"check":"pytest tests/test_export.py passes"}]}}
```
