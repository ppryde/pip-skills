# Covenant planning templates (Steps 4-6 and scenarios)

Generic skeletons. Fill them from the patterns the user actually chose (Step 3), never from a fixed set: phases, deliverables, risks and metrics must name those patterns, the user's domain and the user's numbers.

## Step 4: Implementation Roadmap

```markdown
# Implementation Roadmap

## Phase 0: Foundation (Weeks 1-2)
### Goals
- Development environment, coding standards, project structure
### Deliverables
- [ ] Repository with CI/CD pipeline
- [ ] Architecture decision records (ADRs)
### Patterns Applied
- Basic scaffolding only
### Risk Mitigation
- Low-risk phase; validate CI/CD early

## Phase N: <one new pattern> (Weeks a-b)
### Goals
- <what this phase makes true>
### Deliverables
- [ ] <checkable artefact>
### Patterns Applied
- **<Pattern>**: <which parts>
### Risk Mitigation
- <start small, parallel run, abandon trigger>
```

One new pattern per phase. Order by dependency (foundations first). Give each phase an abandon trigger.

## Step 5: Risk Register

```markdown
# Architecture Risk Register

## High Risk Items
### Risk: <pattern-specific failure or team gap>
**Probability**: Low | Medium | High
**Impact**: Low | Medium | High | Critical
**Mitigation Strategies**:
1. <concrete action>

## Medium Risk Items
(same shape)

## Risk Decision Matrix
| Pattern | Abandon Triggers | Pivot Options |
|---|---|---|
| <pattern> | <measurable threshold> | <simpler fallback> |
```

Typical risks to consider: single point of failure in new infrastructure, missing team experience, eventual-consistency surprises, lag or schema evolution in read models and events, operational maturity below what the patterns need.

## Step 6: Success Metrics

```markdown
# Success Metrics
## Technical: replay/recovery time, latency percentiles, test coverage, deploy frequency, MTTR
## Business: delivery velocity, production incidents, time to market, availability
## Team: decision confidence, review turnaround, onboarding time, technical-debt ratio
```
Set each number from the user's stated requirements; do not invent targets.

## Scenarios (calibration for pattern weighting)

- Greenfield, small team, long timeline: start with the core domain pattern, delay the costly add-ons until the foundation is proven.
- Legacy modernisation, large team, uptime critical: strangle gradually; apply new patterns to new features first.
- Rapid growth, tiny team: start simple, adopt the pattern that unlocks scaling first, prepare (do not build) the next one.
