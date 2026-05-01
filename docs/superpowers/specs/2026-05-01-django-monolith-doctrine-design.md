# Django Monolith Doctrine — Design Spec

**Date:** 2026-05-01
**Branch:** `puritan-django-monolith`
**Skill targeted:** `puritan` (doctrine + supporting Inquisition / Covenant flows)
**Authoring skill referenced:** `puritan:scriptorium`

## Summary

Adds `django-monolith.md` to puritan's doctrine catalogue as the Django specialisation of `modular-monolith.md` (and the Django-idiomatic bleeds of `repository.md`). Encodes 48 rules across 8 categories covering the boundary heresies that Django's idioms — `'app.Model'` FK strings, signal coupling, migration deps, admin registration, Repository pattern bypass — let through, and which the language-agnostic doctrines miss.

The doctrine ships alongside three supporting changes that make it usable in practice:
1. Schema evolution of `.architecture/config.yml` to support per-target metadata (specifically `uses_repository:`).
2. Schema evolution of `.architecture/decisions.yml` to support model-level exceptions via `exempt_targets:`.
3. Two interactive prompt flows added to `/puritan:inquisition` — strictness selection at first run, and shared-kernel-exception triage after the audit pass.

## Goal

A Django modular monolith running `/puritan:inquisition django-monolith` should:
- Catch idiomatic Django boundary heresies invisible to generic `modular-monolith` rules
- Stay noise-honest by default — known shared kernels (`accounts.User`, `core/` mixins) handled via interactive exemption rather than hardcoded carve-outs
- Pair coherently with `modular-monolith` and `repository` doctrines via cross-references that an Inquisition run can group rather than duplicate
- Surface boundary heresies *before* an app extraction is attempted, where they cost most

## Non-Goals

- Generic Python or modular system rules — those belong in `modular-monolith.md` or new pattern doctrines
- Project-specific naming/folder conventions — those belong in `CLAUDE.md` or project READMEs (per Scriptorium guidance)
- Auto-fixing violations — Inquisition reports; remediation is the user's choice
- Replacing `modular-monolith.md` or `repository.md` — DJM is a specialisation, run alongside

---

## Catalogue scope & structure

**File path:** `plugins/puritan/skills/doctrines/django-monolith.md`
**ID prefix:** `DJM` (claim block 001-099 in Scriptorium's Violation ID Convention table)
**Language Scope:** `Language-specific: Python` — detection patterns use Django/Python idioms (`@receiver`, `from <app>.models`, `apps.get_model()`, `ForeignKey('app.Model')`)
**Target rule count:** 48 rules across 8 categories (6 rules per category)
**Severity mix:** 24 `error` / 24 `warning` (50/50 — substantially more permissive than MOM's ~80/20, reflecting Django's higher false-positive risk; the strictness/exemption flow recovers rigour where teams want it)
**Default strictness recommendation:** `pragmatic` (selected by user prompt at first run, persisted to `decisions.yml`)

### Required sections (per `_template.md` and Scriptorium Step 9 checklist)

1. Header + 1-2 sentence summary + `Language Scope` declaration
2. **When to Use** (must include "Do NOT use it" calibration)
3. **Why Use It** (4-6 value bullets)
4. **Pros and Cons** (≥5 rows; honest trade-offs)
5. **Applicable Directories**
6. **Violation Catalog** (8 categories, 6 rules each, 48 total)
7. **Allowed Exceptions** (static carve-outs in the doctrine)
8. **Cross-Reference** (bold-with-`.md`-suffix; covers MOM, REP, DDD, HEX, MSG)
9. **Sources and Authority** (≥1 primary, ≥2 practitioners, ≥1 anti-pattern study)
10. **Detection Signatures** (Directory / File / Anti-signal subsections)

### Voice

The doctrine prose adopts the Witchfinder tone established in the repo's CLAUDE.md and Scriptorium SKILL.md — formally precise, dramatically serious, with a knowing wink. Violations are heresies; resolutions are absolution. Persona is flavour, not a barrier to clarity. Detection patterns and the violation tables remain technically unambiguous regardless of voice.

---

## The eight categories

ID ranges leave gaps within each category (e.g. DJM-001 to DJM-006 with DJM-007 to DJM-009 free) so future rules can slot in without renumbering.

### Category 1 — Cross-app references (DJM-001 to DJM-006)

*Direct couplings between Django apps that bypass service-layer boundaries.*

| ID | Category slug | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| DJM-001 | cross-app-fk-string | `ForeignKey('other_app.Model', ...)` cross-app string ref | error | regex `ForeignKey\(['"][\w_]+\.[\w_]+['"]` where prefix differs from current `app_label` |
| DJM-002 | cross-app-direct-import | `from other_app.models import X` cross-app direct import | error | AST: import-from `<other_app>.models` in app's non-migration files |
| DJM-003 | cross-app-reverse-traversal | Reverse-accessor chains crossing 2+ app boundaries (`order.user.payments_set.all()`) | warning | AST: attribute chains on FK/reverse relations spanning multiple `app_label`s |
| DJM-004 | get-model-bypass | `apps.get_model('other', 'Model')` outside migrations and admin | warning | regex `apps\.get_model\(` outside `*/migrations/` and `admin.py` |
| DJM-005 | cross-app-onetoone | `OneToOneField('other_app.Model')` — usually indicates bad decomposition | warning | regex `OneToOneField\(['"][\w_]+\.` with cross-app prefix |
| DJM-006 | cross-app-m2m-through | `ManyToManyField` with `through=` referencing another app's model | warning | regex `ManyToManyField.*through=['"][\w_]+\.` cross-app |

**Cross-refs:** DJM-001/005/006 ↔ MOM-008 (foreign-key-leak); DJM-002 ↔ MOM-001/002 (internal-leak / api-bypass); DJM-003 ↔ MOM-008.

### Category 2 — Signals (DJM-010 to DJM-015)

*Cross-app coupling through Django's signal framework, the silent boundary-erosion path.*

| ID | Category slug | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| DJM-010 | cross-app-receiver | `@receiver(signal, sender=OtherApp.Model)` — silent cross-app coupling | error | AST: `@receiver` decorator with `sender=` resolving to another app's model |
| DJM-011 | ready-cross-app-touch | `AppConfig.ready()` signal handler accessing another app's models | error | AST: model imports/accesses inside `apps.py` `ready()` resolving to other apps |
| DJM-012 | signal-cascade-write | Signal handler triggering writes in another app | warning | AST: receiver function body containing `OtherModel.objects.create/update/delete` |
| DJM-013 | save-override-side-effects | Custom `Model.save()` override producing cross-app side effects | warning | AST: `save()` body invoking other-app services or signals |
| DJM-014 | private-receiver-import | Signal receiver importing from another app's `_internal` / private modules | error | regex `from \w+\._internal` or `from \w+\.services\._private` in receiver files |
| DJM-015 | weak-signal-decoupling | Cross-app signal coupling where a direct service call would be clearer | warning | heuristic: `pre_save`/`post_save` receivers touching <3 lines of state — likely should be a service call |

**Cross-refs:** DJM-010 ↔ MOM-011/012 (excessive-sync-calls / missing-event-contract); DJM-011 ↔ MOM-014 (synchronous-coupling); DJM-012 ↔ MOM-013 (event-loop).

### Category 3 — Migrations (DJM-020 to DJM-025)

*Migration coupling — the most subtle form because it works locally and fails on deploy.*

| ID | Category slug | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| DJM-020 | cross-app-runpython | `RunPython` operation in app A using `apps.get_model('B', ...)` | error | AST: RunPython callbacks accessing models from a different `app_label` than the migration's |
| DJM-021 | unnecessary-cross-app-dep | Cross-app `dependencies = [('other', '0001')]` not strictly required by ops | warning | AST: dependency on another app where no operation references that app's models |
| DJM-022 | bulk-update-foreign | Data migration bulk-updating tables owned by another app | error | AST: `OtherModel.objects.bulk_update/filter().update()` inside RunPython callbacks across apps |
| DJM-023 | cross-app-rawsql | `RunSQL` referencing tables owned by another app | error | regex: SQL string operations on `<other_app>_<table>` patterns inside another app's migrations |
| DJM-024 | model-relocation-leak | Model relocated between apps without updating FK string refs in other apps | warning | cross-file: model exists in app B's models but FK strings still say `'A.Model'` |
| DJM-025 | undeclared-cross-app-data | Migration touching multiple apps' data without explicit `dependencies` declaration | warning | AST: RunPython accessing multiple `app_label`s without all listed in `dependencies` |

**Cross-refs:** DJM-020 ↔ MOM-006 (cross-module-join); DJM-022 ↔ MOM-007 (shared-table); DJM-024 ↔ MOM-024 (circular-init).

### Category 4 — Settings & wiring (DJM-030 to DJM-035)

*Configuration shape and `INSTALLED_APPS` coupling.*

| ID | Category slug | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| DJM-030 | unprefixed-app-config | App-specific config keys in top-level settings without `<APP_LABEL>_` namespacing | warning | regex: settings keys not matching `<APP_LABEL>_*` referencing app-specific concerns |
| DJM-031 | hidden-installed-apps-order | Hidden `INSTALLED_APPS` ordering dependency | error | static check: `AppConfig.ready()` referencing models/registries from apps later in `INSTALLED_APPS` |
| DJM-032 | hardcoded-user-import | Hardcoded `from accounts.models import User` instead of `get_user_model()` / `settings.AUTH_USER_MODEL` | error | regex `from \w+\.models import User` outside the `AUTH_USER_MODEL`-owning app |
| DJM-033 | settings-cross-app-leak | App code reading `django.conf.settings` for values belonging to another app | warning | grep: `settings.<OTHER_APP_PREFIX>_*` accessed from a different app |
| DJM-034 | cross-app-ready-mutation | One app's `AppConfig.ready()` mutating another app's registries / hooks / signals | error | AST: `ready()` body modifying `apps.get_app_config('other')` state |
| DJM-035 | middleware-app-internals | Middleware importing from an app's `_internal` modules | error | regex `from \w+\._internal` / `from \w+\.services\._` inside `*/middleware.py` |

**Cross-refs:** DJM-030 ↔ MOM-043 (global-config-clash); DJM-031 ↔ MOM-024 (circular-init).

### Category 5 — HTTP surface (DJM-040 to DJM-045)

*URL routing, views, middleware, and template-tag boundaries.*

| ID | Category slug | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| DJM-040 | missing-app-namespace | `urls.py` without `app_name = '...'` causing `reverse()` namespace collisions | warning | AST: `urls.py` files lacking `app_name` module-level assignment |
| DJM-041 | unnamespaced-cross-app-reverse | `reverse('view_name')` resolving another app's view without namespace prefix | error | regex `reverse\(['"][^:'"]+['"]\)` matching view names defined in other apps |
| DJM-042 | template-tag-cross-app | Template tag library in app A importing from app B's models/services | warning | AST: imports inside `templatetags/*.py` files crossing app boundaries |
| DJM-043 | middleware-cross-app | Middleware importing app-specific helpers across app boundaries | error | regex: imports in `middleware.py` files crossing app boundaries |
| DJM-044 | view-direct-foreign-models | View in app A importing app B's models directly (vs via a service interface) | error | AST: `view*.py` files containing `from <other_app>.models import` |
| DJM-045 | drf-cross-app-meta | DRF `Serializer.Meta.model` pointing at another app's model | warning | AST: `class Meta` blocks in serializers with `model = <other_app>.<Model>` |

**Cross-refs:** DJM-041 ↔ MOM-002 (api-bypass); DJM-043/044 ↔ MOM-001 (internal-leak); DJM-045 ↔ MOM-001.

### Category 6 — Admin (DJM-050 to DJM-055)

*Django admin is a high-traffic site for accidental cross-app coupling.*

| ID | Category slug | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| DJM-050 | foreign-admin-register | One app's `admin.py` registering a model defined in another app | error | AST: `admin.site.register(OtherModel, ...)` where `OtherModel` is from a different app |
| DJM-051 | admin-traverse-internal | `ModelAdmin` traversing FKs into another app's internals via `list_display` / `list_filter` | warning | AST: list_display callables accessing `obj.fk_to_other.internal_field` |
| DJM-052 | admin-cross-app-action | Admin actions performing cross-app side effects | warning | AST: `@admin.action` body invoking other-app services or models |
| DJM-053 | admin-missing-permissions | Admin registration without app-aware permission scoping | warning | AST: `register` calls without `has_change_permission`/`has_delete_permission` overrides where cross-app FKs exist |
| DJM-054 | cross-app-inline | `TabularInline` / `StackedInline` pointing at another app's model | error | AST: `inlines = [...]` referencing `OtherApp.Inline` |
| DJM-055 | admin-fieldset-leak | Admin fieldsets exposing fields from another app via FK traversal | warning | AST: `fieldsets`/`fields` lists containing `__` traversal across app boundaries |

**Cross-refs:** DJM-050/054 ↔ MOM-001 (internal-leak); DJM-051/055 ↔ MOM-008 (foreign-key-leak).

### Category 7 — Tests (DJM-060 to DJM-065)

*Tests are the silent enforcer — if they cross app boundaries, the boundary doesn't really exist.*

| ID | Category slug | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| DJM-060 | test-imports-foreign-models | Tests in app A importing `from other_app.models import X` directly | error | AST: `from <other>.models import` in `<app>/tests/**` |
| DJM-061 | cross-app-fixture | Test fixtures in app A creating models from app B | warning | AST: `pytest.fixture` / `setUp` bodies instantiating other-app models |
| DJM-062 | test-cross-app-orm | Tests in app A using `OtherApp.objects.X` instead of going via app A's service interface | warning | grep: `OtherModel.objects.` calls in test files |
| DJM-063 | test-cross-app-signal | Tests asserting on signals fired in another app | warning | AST: `mock.patch` / `assertReceivedSignal` targets resolving to other apps |
| DJM-064 | test-shared-state-mutation | Tests mutating shared DB state without per-app teardown | error | AST: tests creating User/shared-kernel records without `tearDown` cleanup or transactional fixtures |
| DJM-065 | test-foreign-scaffolding | Tests for app A reference test scaffolding (fixtures, helpers, factories) defined outside app A's `tests/` AND outside the project-level shared `conftest.py` | error | AST: imports from `<other_app>.tests.*` OR `pytest.fixture`/`@pytest.fixture` references resolving to fixtures defined in another app's tests directory |

**Cross-refs:** DJM-060/062 ↔ MOM-034 (module-test-leak); DJM-064 ↔ MOM-038 (integration-flakiness); DJM-065 ↔ MOM-035 (missing-module-isolation).

### Category 8 — Data access discipline (DJM-070 to DJM-075) — *fires only when target's `uses_repository: true`*

*Django-idiomatic Repository-pattern bleeds. Fires per-app based on the per-target `uses_repository` flag set in `.architecture/config.yml`.*

| ID | Category slug | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| DJM-070 | objects-call-in-view | `Model.objects.X` calls in `views.py` when `uses_repository=true` | error | regex `\w+\.objects\.` in `views.py` for repository-using apps |
| DJM-071 | queryset-leak-from-repo | Repository method returning `QuerySet` rather than list / iterator / domain object | error | AST: methods in `repositories/*.py` with return-type annotation `QuerySet[...]` or returning a `.filter()`/`.all()` chain unwrapped |
| DJM-072 | manager-business-logic | Custom `Manager` / `QuerySet` method carrying business logic (vs query construction only) | error | AST: methods on `Manager` subclasses with >3 conditional branches unrelated to query building (matches REP-020's threshold) |
| DJM-073 | save-bypass-repo | `.save()` / `.delete()` / `.update()` calls in views or serializers for repository-using apps | error | regex `\.save\(\)\|\.delete\(\)` in `views.py` / `serializers.py` for those apps |
| DJM-074 | signal-handler-data-access | Signal handlers performing additional cross-aggregate data access | warning | AST: receiver bodies invoking >1 distinct repository / model class |
| DJM-075 | serializer-objects-call | DRF serializers using `Model.objects` directly when a repository exists for that app | warning | regex `\w+\.objects\.` in `serializers.py` for repository-using apps |

**Cross-refs:** DJM-070/073/075 ↔ REP-013 (controllers-instantiate-repos — Django idiomatic tell); DJM-071 ↔ REP-003 (orm-types-in-interface — Django tell); DJM-072 ↔ REP-020 (responsibility — Django tell).

---

## Severity, strictness, and supporting infrastructure

### Severity defaults

48 rules: 24 `error` / 24 `warning` (50/50). Substantially lower error ratio than MOM's ~80/20 because Django's permissive nature — its idioms (FK strings, signals, `apps.get_model`) cross boundaries by design — means more rules need a softer default. The strictness/exemption flow recovers rigour where the team wants it.

**Severity assignment principle:**
- `error` — heresy is unambiguous and almost always wrong (`@receiver(sender=OtherApp)`, `RunPython` reaching across apps, hardcoded User import, Repository pattern bypass when adopted)
- `warning` — heresy is conditionally bad (`OneToOneField` cross-app, M2M `through=` cross-app, reverse-accessor chains) — fix when boundaries are tightened, accept while migrating

### Strictness model

Standard puritan strictness applies as elsewhere:

| Mode | Behaviour |
|---|---|
| `strict` | All severities at original level. Exemptions only via `decisions.yml`. |
| `pragmatic` | Findings matched by `exempt_targets` demoted to `warning`. Other findings unchanged. |
| `aspirational` | All findings demoted to `warning` regardless of severity. CI doesn't block. |

Default selection happens at first run via interactive prompt (see "Interactive flow extension 1" below). Recommended: `pragmatic`.

### Schema extension 1 — `.architecture/config.yml` rich targets

Currently puritan's `targets:` field accepts bare path strings. DJM needs per-target metadata (specifically `uses_repository`). Schema evolves to support either form (backward-compatible — bare strings continue to work for all other doctrines):

```yaml
doctrines:
  - name: django-monolith
    enabled: true
    targets:
      - path: accounts/
        uses_repository: true
      - path: orders/
        uses_repository: true
      - path: blog/
        # uses_repository unset → defaults to false
      - core/    # bare string still supported, treated as { path: core/, uses_repository: false }
```

Per-target metadata fields supported initially:
- `path:` (required) — directory to scan
- `uses_repository:` (optional, default `false`) — gates Category 8 rules

Future-friendly: schema leaves room for `app_label:`, `domain:`, etc. without further breaking changes.

`/puritan:covenant discover` populates `uses_repository` automatically by scanning each app for Repository indicators:
- File named `repositories.py` or `repositories/` directory
- Class names ending in `Repository` (e.g. `OrderRepository`)
- Imports of the form `from .repositories import` or `from <app>.repositories import`
- Abstract base repository classes (e.g. `class BaseRepository(ABC)`)

User can override the auto-detected value in config.

### Schema extension 2 — `.architecture/decisions.yml` model-level exemptions

Existing `decisions.yml` overrides take rule IDs only. DJM extends with `exempt_targets:` for fine-grained model-level exceptions:

```yaml
strictness:
  django-monolith: pragmatic

overrides:
  DJM-001:
    severity: warning
    reason: "AUTH_USER_MODEL is shared kernel; cross-app FKs to accounts.User accepted."
    exempt_targets:
      - "accounts.User"

  DJM-002:
    severity: warning
    reason: "Common app contains shared abstract base classes only."
    exempt_targets:
      - "common.*"
```

`exempt_targets:` accepts:
- Exact `app_label.ModelName` (e.g. `accounts.User`) — match a single model
- Glob `app_label.*` (e.g. `common.*`) — match all models in an app
- Glob `*.MixinName` (rare; for shared-mixin patterns) — match any app's model with that name. Note: this matches multiple models if multiple apps define classes with the same name; that's intentional but worth flagging during the interactive prompt.

Match logic: a finding is "exempt" if its referenced model matches any pattern in `exempt_targets`. Strictness mode then decides whether the exempt finding is demoted, suppressed, or kept.

### Interactive flow extension 1 — strictness mode prompt at first run

When `django-monolith` is enabled in `.architecture/config.yml` AND there is no `strictness.django-monolith` entry in `decisions.yml`, Inquisition (or Covenant, whichever runs first) prompts:

> **`django-monolith` strictness mode** — pick one:
>
> - **strict** — all rules at full severity. For teams already running a clean modular monolith with hard app boundaries.
> - **pragmatic** — exempt-targeted findings demoted to `warning` (recommended). For teams progressively tightening boundaries.
> - **aspirational** — all findings demoted to `warning`. For teams getting started — Inquisition reports, CI doesn't block.
>
> Recommended: **pragmatic**
> **(s)trict / (p)ragmatic / (a)spirational** [p]

The user's choice persists to `decisions.yml`. This prompt fires **once, up front** (before the audit pass) so the audit knows what severity to apply.

### Interactive flow extension 2 — shared-kernel exemption triage after audit pass

After the audit, before presenting the verdict:

1. Group cross-app findings by referenced model
2. For each model with ≥1 finding and no existing `exempt_targets` entry, prompt:
   > **DJM-001** fired on `ForeignKey('accounts.User')` in 14 places across 7 apps.
   > Treat `accounts.User` as a shared-kernel exception (warning, not error)?
   > **(y)es / (n)o / (s)kip — defer**
3. On `y`: append to `decisions.yml` under the appropriate rule. Re-evaluate findings for that rule with the exemption applied. Demote per strictness mode.
4. On `n`: keep findings as errors, present in the verdict.
5. On `s`: leave undecided, present as errors but flag for next-run review.

Sequential, not interleaved — strictness prompt fires before the audit, exemption prompts fire after. Keeps the UX coherent.

---

## Cross-references and detection signatures

### Cross-reference convention

DJM is a **Django specialisation** of MOM and REP. Cross-refs stored two ways in the doctrine file:

**1. Inline per-rule note** — appended to the violation table row or kept as a trailing note column:

```
| DJM-001 | cross-app-fk-string | ... | error | regex ... | ↔ MOM-008 |
```

Makes it obvious to readers running both doctrines that DJM-001 is the Django-idiomatic tell of MOM-008's structural rule. Future Inquisition dedup work can use this to condense findings (out of scope for v1 — just record the link).

**2. Aggregate Cross-Reference section** — standard puritan format at doctrine bottom:

> **modular-monolith.md** — DJM is the Django specialisation. Run both lenses; MOM catches structural violations, DJM catches Django-idiomatic ones.
>
> **repository.md** — REP defines the abstract Repository pattern discipline. DJM Category 8 (DJM-070+) catches Django-specific bleeds when Repository is the chosen architecture.
>
> **ddd.md** — DDD's bounded contexts often map 1:1 to Django apps in well-organised codebases.
>
> **hexagonal.md** — HEX's port-and-adapter discipline pairs with DJM's data access category for teams using Repository + Hexagonal together.
>
> **messaging.md** — DJM Category 2 governs Django's signal framework specifically. MSG covers async messaging in general; signals are the in-process variant.

### Cross-reference policy

- **Direction:** DJM → MOM/REP only. DJM is the specialisation.
- **Cardinality:** N:M. One DJM rule may cite multiple MOM/REP rules; one MOM rule may be the parent of multiple DJM rules.
- **Honesty:** Some DJM rules have no clean MOM/REP equivalent (Django-specific concerns: `INSTALLED_APPS` ordering, admin coupling, signal framework specifically). Those rules carry no cross-ref. Don't force contrived links.

### Detection Signatures

For Covenant discover mode to fingerprint **a Django modular monolith specifically** — not just "any Django project."

**Directory signals** (any 2+ suggest pattern in use):
- `apps/` subfolder containing multiple Django app directories *each with their own `apps.py` containing an `AppConfig` subclass* (qualified to disambiguate from non-Django `apps/` usage)
- Multiple sibling app directories at project root (`accounts/`, `orders/`, `blog/`) each with their own `apps.py`, `models.py`, `migrations/`
- Per-app `repositories.py` / `services.py` / `selectors.py` (HackSoft / Cosmic Python style — strong signal)
- Per-app `tests/` directories with their own `conftest.py`
- Per-app `templates/<app_name>/` and per-app `static/<app_name>/`

**File signals** (any 1 is significant):
- `manage.py` at project root + 5+ sibling `apps.py` files
- `INSTALLED_APPS` in settings containing 5+ local app entries (excluding `django.contrib.*` and obvious third-party like `rest_framework`)
- Project-level `urls.py` `include()`-ing 5+ app urlconfs
- Custom `AUTH_USER_MODEL = '<app>.User'` set in settings
- `default_app_config` or `AppConfig` with non-trivial `ready()` hooks per app

**Anti-signals** (suggest pattern is NOT in use, leans toward simpler Django):
- Single `models.py` / `views.py` at project root with no per-app folders (Django startproject default)
- `INSTALLED_APPS` with ≤ 2 local entries
- No `apps.py` files (legacy pre-1.9 Django, or single-app project)
- All views in one `urls.py` with no `include()` calls into other apps
- No `manage.py` (not a Django project — quick disqualifier)

**Crossover awareness** — `apps/` is Scriptorium-listed as ambiguous because non-Django repos use `apps/` for unrelated reasons. The qualification "containing `apps.py` files with `AppConfig` subclasses" is the disambiguator.

---

## Calibration prose

### When to Use

Any Django codebase with 3+ business apps where boundary discipline matters — small SaaS backends with `accounts/`, `orders/`, `billing/`; mid-size internal tools; any Django project headed for app extraction or microservice carve-out. Especially valuable when teams are growing and code review can't catch every cross-app coupling by eye.

**Do NOT use it** for single-app Django projects (`startproject` defaults), prototype throwaways, or thin REST API wrappers around a single domain. The strictness model can soften DJM for in-progress codebases, but the doctrine isn't useful where there's no boundary to enforce.

### Why Use It

- Catches Django-idiomatic boundary erosion that generic `modular-monolith` rules miss — FK strings, signal coupling, migration deps, admin registration leaks
- Pairs symmetrically with `repository` for teams adopting Repository pattern in Django (Category 8)
- Surfaces `accounts.User`-style shared-kernel decisions explicitly via the interactive exemption flow rather than letting them stay implicit
- Detects boundary heresies *before* you try to extract an app — most Django app extractions fail because boundaries weren't real, just notional
- Shipped with strictness levels and per-target `uses_repository` so teams at different maturity stages get useful audits without noise

### Pros and Cons (≥5 rows)

| Pros | Cons |
|---|---|
| Catches Django-specific bleeds invisible to generic doctrines | Higher false-positive rate than `modular-monolith` without strictness flow tuned in |
| Strictness + `exempt_targets` keeps the catalogue noise-honest by default | Schema extensions to `config.yml` and `decisions.yml` are non-trivial — affects existing puritan users |
| Per-app `uses_repository` gate prevents Category 8 from creating noise in non-Repository apps | Auto-detecting `uses_repository` requires Covenant to scan each app — extra discover step |
| Pairs cleanly with MOM and REP — cross-references make multi-doctrine runs coherent | 6 categories require Django expertise to populate authoritatively; weak rules in one category dilute confidence in the rest |
| Detects boundary heresies before app extraction, where they cost most | Doctrine assumes Django ≥ 3.x conventions (`AppConfig`, `apps.py`, `default_auto_field`); older projects need rule subset |

### Applicable Directories

Primary targets (mapped via `.architecture/config.yml`):

- `<app_name>/` — top-level Django app (most common layout: `accounts/`, `orders/`, `blog/`)
- `apps/<app_name>/` — Pinterest/Instagram-style nested layout (`apps/accounts/`, `apps/orders/`)
- `<project_name>/<app_name>/` — Django startproject default with apps inside the project package
- `<app_name>/apps.py` — `AppConfig` definitions and `ready()` hooks
- `<app_name>/migrations/` — schema and data migrations (Category 3 scan target)
- `<app_name>/admin.py` — admin registrations (Category 6 scan target)
- `<app_name>/tests/` — per-app test suites (Category 7 scan target)
- `<app_name>/repositories.py` / `<app_name>/repositories/` — Repository implementations when `uses_repository=true` (Category 8)

The doctrine assumes one of these layouts; mixed layouts are detected during Covenant discover.

### Allowed Exceptions (static carve-outs in the doctrine itself)

These differ from runtime `exempt_targets` (user-configurable). These are **doctrine-level acknowledgements** that some patterns are legitimate, baked in regardless of strictness:

- **`settings.AUTH_USER_MODEL` indirection is the canonical form.** DJM-001's detection explicitly excludes `ForeignKey(settings.AUTH_USER_MODEL)` (and `get_user_model()` from DJM-032) — these are the correct forms and don't constitute hardcoded cross-app coupling. String-literal forms (`ForeignKey('accounts.User')`) and direct `from accounts.models import User` imports DO fire their respective rules; teams that want to permit them site-wide add `accounts.User` to `exempt_targets:` via the interactive prompt at first run rather than the doctrine carving an exception.
- **Strangler Fig migrations.** During a phased boundary tightening, cross-app references marked with `# noqa: DJM-XXX strangler` are downgraded to warnings. Standard puritan suppression marker convention.
- **Generic foreign keys (`ContentType`).** `GenericForeignKey` by definition crosses model boundaries and isn't a violation of DJM-001/005/006. Detection patterns explicitly exclude `ContentType`/`GenericForeignKey` references.
- **Project-root test scaffolding.** Shared `tests/base.py`, `tests/factories.py`, or top-level `conftest.py` at project root used by multiple apps' test suites is exempt from DJM-060/065 — it's the correct shape for shared test scaffolding.
- **Project-level abstraction-only apps.** An app whose `models.py` (or all files under `models/`) contains only abstract bases (`class Meta: abstract = True`), mixins, value objects, exceptions, and protocol classes — i.e. no concrete models that produce database tables — is structurally not a boundary target. Cross-app imports of these abstractions don't fire DJM-002. Detection: every concrete `class X(models.Model)` declaration in the app sets `Meta.abstract = True`. Naming conventions like `core/` or `common/` are not required for the exemption to apply — the structural check is what matters.
- **Migration `dependencies` graphs.** DJM-021 only flags dependencies where Django's auto-detection wouldn't have added them — explicit dependencies needed for atomic deployment ordering are not heresy.

---

## Sources and Authority

Per `_template.md` requirements (≥1 primary, ≥2 practitioners, ≥1 anti-pattern study).

**Foundational works:**
- *Two Scoops of Django* (Greenfeld & Roy Greenfeld, latest ed.) — https://www.feldroy.com/books/two-scoops-of-django — canonical app-design and project-layout guidance
- Django docs — Reusable Apps: https://docs.djangoproject.com/en/stable/intro/reusable-apps/ and Applications: https://docs.djangoproject.com/en/stable/ref/applications/ — official boundary primitives
- *Cosmic Python* (Percival & Gregory, 2020) — https://www.cosmicpython.com/ — Repository pattern in Django context, service layer, dependency direction

**Practitioner guidance:**
- HackSoft Django Styleguide — https://github.com/HackSoftware/Django-Styleguide — services/selectors split, fat models avoidance, queryset hygiene
- Pinterest Engineering — Building a faster Django (case study with `apps/` subfolder layout) — https://medium.com/pinterest-engineering
- Instagram Engineering — Django at scale — https://instagram-engineering.com/

**Anti-pattern / failure case studies:**
- Big Ball of Mud (Foote & Yoder) — http://www.laputan.org/mud/ — generic anti-pattern; applies directly to Django apps grown organically
- The Distributed Monolith — https://microservices.io/antipatterns/distributed-monolith.html — what happens when Django apps decompose into microservices without first establishing clean boundaries

---

## Deliverables

The branch ships:

### 1. The doctrine file
`plugins/puritan/skills/doctrines/django-monolith.md` — 48 rules across 8 categories, format mirrors `modular-monolith.md`. Includes all sections per `_template.md` and Scriptorium Step 9 checklist. Witchfinder voice in prose; technical precision throughout the violation tables.

### 2. Scriptorium Violation ID Convention table update
`plugins/puritan/skills/scriptorium/SKILL.md` — add `| Django Monolith | DJM | 001-099 |` row. Opportunistically add the missing `| Modular Monolith | MOM | 001-050 |` row in the same edit (modular-monolith.md exists at MOM-001 to MOM-050 but isn't in the convention table).

### 3. Cross-reference updates to existing doctrines
Per Scriptorium Step 3 ("After writing a new doctrine, check existing doctrines for stale or missing cross-references back to yours and update them"):
- `modular-monolith.md` Cross-Reference section — add `**django-monolith.md**` as Django specialisation
- `repository.md` Cross-Reference section — add `**django-monolith.md**` for Django-idiomatic Repository bleeds

### 4. Config schema extension
`.architecture/config.yml` parser — `targets:` field accepts both bare path strings (existing) and rich objects with `path:` + `uses_repository:` (new). Backward-compatible.

### 5. Covenant `uses_repository` auto-detection
`/puritan:covenant discover` scans each Django app for Repository indicators (`repositories.py`, `*Repository` class names, `from .repositories import` patterns, abstract `BaseRepository` ancestors) and populates `uses_repository: true/false` per target.

### 6. Decisions schema extension
`.architecture/decisions.yml` overrides gain optional `exempt_targets:` field. Match patterns: exact `app.Model`, glob `app.*`, glob `*.MixinName`.

### 7. Inquisition interactive flows
`/puritan:inquisition` learns two new flows when `django-monolith` is enabled:
- **Strictness mode prompt** at first run (s/p/a, default p), persists to `decisions.yml`
- **Shared-kernel exemption prompt** after audit pass, per cross-app model with findings, appends to `decisions.yml` on user approval

### 8. Plugin version bump
`plugins/puritan/.claude-plugin/plugin.json` — bump from `1.1.1` to `1.2.0` (minor: doctrine added + schema extensions).

### 9. Puritan README updates
`plugins/puritan/README.md`:
- Add `Django Monolith` row to the Doctrines table with prefix `DJM`
- Document the rich-target `config.yml` form
- Document the `exempt_targets:` field in `decisions.yml`
- Mention the strictness and shared-kernel interactive flows in the Inquisition section

### 10. Smoke test
After all changes land, run `/puritan:inquisition django-monolith` against a known Django project to verify the doctrine fires sensibly and the interactive flows work end-to-end.

---

## Implementation order

Suggested sequence for the writing-plans phase. Each can be its own commit, ordered for reviewability:

1. **Doctrine file** (`django-monolith.md`) — pure content; ships standalone and is the primary deliverable
2. **Cross-reference updates** in `modular-monolith.md` and `repository.md` — small markdown edits, can land alongside (1)
3. **Scriptorium ID table update** — single-row addition (DJM, opportunistic MOM); trivial edit alongside (1)
4. **Config schema extension** — backward-compatible parser change; needed before Covenant can populate per-target metadata
5. **Covenant `uses_repository` auto-detection** — depends on (4)
6. **Decisions schema extension** (`exempt_targets:`) — needed before Inquisition can apply exemptions
7. **Inquisition strictness prompt + shared-kernel prompt** — depends on (1) and (6)
8. **Plugin version bump + README updates** — last; documents the user-visible changes shipped
9. **Smoke test** — validates the integration end-to-end

---

## Open questions / deferred decisions

None blocking. All design decisions made during brainstorming have been captured above. Items that may surface during implementation:

- **Threshold tuning for DJM-072** ("Manager method with >3 conditional branches"). Inherited from REP-020's threshold; may need calibration against real codebases during smoke test.
- **DJM-015 "weak-signal-decoupling"** is the most heuristic rule (`<3 lines of state`); may convert to a `warning` with a note that team review is required, or drop entirely if it produces too many false positives.
- **Migration scanning in Category 3** requires reading both `<app>/migrations/*.py` AND tracking `app_label` ownership; may need additional Inquisition tooling beyond simple grep/AST.
- **Covenant auto-detection of `uses_repository`** — initial heuristic set may miss Repository implementations that don't follow the canonical naming. Document the auto-detection rules so users can override in config.

---

## Acceptance

The doctrine is considered shippable when:
- File `plugins/puritan/skills/doctrines/django-monolith.md` exists and passes Scriptorium's Step 9 completeness checklist
- `/puritan:inquisition django-monolith` runs against a Django project, prompts for strictness mode, completes the audit, prompts for shared-kernel exemptions, and produces a verdict in the standard format
- Cross-references in `modular-monolith.md` and `repository.md` link back to `django-monolith.md`
- Scriptorium's Violation ID Convention table contains DJM (and MOM)
- Plugin version bumped, README updated, branch ready for PR
