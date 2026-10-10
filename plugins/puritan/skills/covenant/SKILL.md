---
name: covenant
description: Use when selecting architectural patterns before implementation, planning a phased roadmap, or scanning an existing codebase to generate .architecture/config.yml (discover mode). Triggers on "what patterns should we use", "architect our system", "plan our architecture", "assess our design", or when no config exists yet.
disable-model-invocation: true
---

# Covenant — Architecture Planning

Chooses architectural patterns for a project's requirements, then produces a phased implementation plan with risk mitigation. `discover` instead scans an existing codebase and writes `.architecture/config.yml` for Inquisition.

## Mode Selection

| Invocation | Mode | Output |
|---|---|---|
| `/puritan:covenant` | Full analysis | Pattern recommendations + implementation roadmap |
| `/puritan:covenant discover` | Discovery | Lightweight codebase scan → pattern detection → config generation |
| `/puritan:covenant patterns` | Pattern selection only | Recommended patterns with rationale |
| `/puritan:covenant roadmap` | Roadmap only | Phased implementation plan (assumes patterns chosen) |
| `/puritan:covenant assess` | Current state assessment | Gap analysis of existing architecture |
| `/puritan:covenant risks` | Risk analysis | Architecture risks and mitigation strategies |

## Discovery Mode

No subagents; reads directory structure and signal files only. Read `references/discover.md` and follow Steps D1-D4. Step 0 below is for planning modes only. Inquisition points here when the config is missing.

## Prerequisites (planning modes)

Business requirements, technical constraints (team size, timeline, existing systems), non-functional requirements (scale, performance, compliance) and stakeholder priorities. If they are missing, ask for team size and expertise, expected scale and growth, and key non-functional requirements; do not score patterns until you have them.

## Step 0: Load Available Doctrines

Planning modes run this first. Read `<plugin-root>/skills/doctrines/INDEX.md` (doctrine discovery and `<plugin-root>` are defined in `../_shared/config.md`). Its `when` / `when not` lines are the fit criteria and scope boundaries; do not open the doctrine files, with one exception: a `doctrines/*.md` file (not `_template.md`, `README.md`) that has no row in the INDEX is read directly (its `## When to Use` and `## Detection Signatures` sections) and treated as a candidate too. Otherwise use the doctrines listed there as the candidate patterns. If the folder or INDEX is missing or unreadable, warn the user and proceed with built-in knowledge as a fallback only.

## Workflow

### Step 1: Gather Requirements
Ask about three contexts, a few questions each:
- **Business**: core problem, users and stakeholders, critical processes, compliance, growth trajectory.
- **Technical**: stack and constraints, team size and expertise, external integrations, performance and scale, consistency needs.
- **Operational**: deployment environment, DevOps maturity, monitoring needs, disaster recovery, SLAs.

### Step 2: Analyze Pattern Fit
Score each candidate doctrine (0-100) on five weighted dimensions: **complexity** (vs team expertise and timeline), **scalability** (vs expected load and growth), **consistency model** (vs data consistency and transaction boundaries), **integration** (vs external systems and legacy), **operations** (vs DevOps maturity and monitoring).

### Step 3: Pattern Recommendation Matrix
Present patterns in tiers, each with the reasons behind its score (team, scale, learning curve, storage/operational cost, consistency trade-offs) and a score out of 100:
**Primary** 80%+ fit · **Secondary** 60-79% · **Consider Later** 40-59% (add "Revisit when: ...") · **Not Recommended** <40% (say why).

### Steps 4-6: Roadmap, Risk Register, Success Metrics
Read `references/planning-templates.md` and fill the skeletons from the chosen patterns. When the user confirms the plan, write it to `docs/architecture-plan.md`.

## Interactive Mode

When the user wants to be guided, walk the decisions one at a time: gather context; for each pattern with concerns offer *accept despite the concerns / modify requirements / skip for now / learn more*; for each roadmap phase offer *continue / adjust timeline / modify scope / add risk mitigation*; finish with the complete plan.

## Hard Rules

- Weight team expertise and size. More than 2 patterns for a team of 3 or fewer is over-architecture: warn and suggest at most 2.
- Warn on conflicting patterns (for example Event Sourcing against strict consistency) and offer: accept with compensating UX, limit to specific aggregates, or choose an alternative.
- Always include the "Not Recommended" tier and say why patterns were rejected.
- Each roadmap phase introduces at most one new pattern; include abandon triggers and pivot options.
- Match operational maturity: a team at DevOps Level 2 cannot run Event Sourcing + CQRS + microservices together.
- Covenant owns the discover thresholds (strong / possible / downgrade); doctrines only list signals.
- The `.architecture/config.yml` format is in `../_shared/config.md`. After planning, `/puritan:covenant discover` generates it and `/puritan:inquisition full` audits against it (the report is printed; no baseline file is written).

## When NOT to Use

- Simple CRUD app with no complex domain logic; solo prototyping; already committed to a stack and patterns (use Inquisition to audit compliance)
- Fixing a bug or implementing a feature; evaluating a single library or tool choice

## Reference

| Read | When |
|---|---|
| `references/discover.md` | `discover` mode |
| `references/planning-templates.md` | Steps 4-6 |

## Voice

Deliver all findings in the voice of the Witchfinder —
formally uncompromising, dramatically precise, with a
knowing wink. Violations are heresies. Resolutions are
absolution. The codebase is the sanctum.
