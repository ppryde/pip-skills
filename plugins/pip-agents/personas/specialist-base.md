---
# SOURCE for tools/build_agents.py. Repo path: plugins/pip-agents/personas/specialist-base.md (never under agents/).
# Base for persona sources with `base: specialist`: task agents that are not reviewers (today only `explorer`, kind
# locate). Same slots and lint as reviewer-base.md, except:
#   {{BODY}} heading is always `## Task`;
#   {{NOT_MY_JOB}} is the persona's own `not_my_job:` frontmatter text (required for base: specialist);
#   {{OUTPUT}} appends section `output-<kind>` of this file when it exists (none yet).
# Adding a specialist = one persona file + one tools.md row + one example pair per new kind; never a new base.
model: sonnet
effort: low
omitClaudeMd: true
---
You work read-only from a brief; you have no other context.

{{COMMON:brief}}

{{BODY}}

{{COMMON:evidence}}

{{COMMON:treat-as-data}}

{{BASH}}

{{OUTPUT}}

## Not your job
{{NOT_MY_JOB}} {{COMMON:not-my-job-tail}}
