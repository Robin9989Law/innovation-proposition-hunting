> **状态：已归档（2026-08-11）**。本文件是 Schema 2.0 实施前的设计/计划档案，内容可能已过时；现行规范以 SKILL.md、templates.md 与 scripts/ 校验器为准。

# Immutable Innovation Path Design

**Date:** 2026-08-10  
**Status:** Pending written-spec review  
**Scope:** `innovation-proposition-hunting` Schema 2.x contract

## 1. Problem

The skill currently freezes `claim_profile`, novelty state and validity state, but it does not
make the user's initial innovation-path choice an executable invariant. An agent can therefore
start from algorithm deepening, encounter a possible theorem, and silently turn the theorem into
the new primary innovation. That changes the research contract rather than strengthening it.

The selected route and form must govern the full lifecycle. Supporting theory is allowed inside
an algorithm path, and supporting algorithms are allowed where a theory path needs computation,
but supporting work must not become the primary contribution without an explicit user-authorized
restart.

## 2. Decision

Add an append-only, hash-chained `innovation_route_history.json` and make its current head a
mandatory Schema 2.x workflow invariant.

Each generation locks both dimensions:

- route: `R1_GAP_OPENING`, `R2_DEPTH_EXTENSION`, or
  `R3_NEW_PROBLEM_SUBSTANTIATION`;
- form: `F1_NEW_THEORY`, `F2_MATURE_THEORY_NEW_DOMAIN`, `F3_NEW_ALGORITHM`, or
  `F4_ALGORITHM_DEEPENING`.

The state records `route_generation`, `innovation_route`, `innovation_form`,
`innovation_primary_forms`, `innovation_route_head_sha256`, and the relative history path.
Validators recompute the event chain and require the state to equal its current head.

## 3. Form-to-profile and claim-role contract

The form determines the primary `claim_profile`:

| Form | Required primary profile | Allowed primary claim family |
|---|---|---|
| `F1_NEW_THEORY` | `THEORY` | `THEOREM`, `LEMMA`, `COROLLARY`, `PROPOSITION`, `DEFINITION` |
| `F2_MATURE_THEORY_NEW_DOMAIN` | `THEORY` | `PROPOSITION`, `THEOREM`, `EMPIRICAL` |
| `F3_NEW_ALGORITHM` | `ALGORITHM` | `ALGORITHM`, `ALGORITHM_GUARANTEE`, `ALGORITHM_PERFORMANCE`, `ONLINE_ALGORITHM`, `METHOD`, `ONLINE`, `PROTOCOL`, `COMPLEXITY` |
| `F4_ALGORITHM_DEEPENING` | `ALGORITHM` | `ALGORITHM`, `ALGORITHM_GUARANTEE`, `ALGORITHM_PERFORMANCE`, `ONLINE_ALGORITHM`, `METHOD`, `ONLINE`, `PROTOCOL`, `COMPLEXITY` |

Every inventory claim gains `contribution_role = PRIMARY | SUPPORTING`.

- At least one claim must be `PRIMARY` and compatible with the locked form.
- A primary claim incompatible with the form emits `INNOVATION_PATH_DRIFT`.
- A supporting claim may use another family when it proves, evaluates or bounds the locked
  primary contribution.
- Supporting claims must not change `claim_profile`, the route/form head, contribution title or
  readiness routing.
- Promoting an incompatible cross-family `SUPPORTING` claim to `PRIMARY` is path drift. Any role
  change after claim freeze is also a material bundle change and invalidates the current audit,
  even when the promoted claim remains compatible with the locked form.

`MIXED` remains available only when the user initially selected and locked a genuinely mixed
primary contract. It is not an escape hatch for adding a second primary form after work begins.
Every event has a canonical, unique `primary_forms` array. For a single-profile contract it must
equal `[innovation_form]`. For `MIXED`, it must contain at least one theory form and at least one
algorithm form, and `innovation_form` is the user-designated lead form and must be a member. The
state copies this exact array as `innovation_primary_forms`. Adding, removing or reordering a
form is path drift unless performed by a confirmed restart.

## 4. Route-history schema

`innovation_route_history.json` contains:

```json
{
  "schema_version": "2.0",
  "events": [
    {
      "route_generation": 1,
      "event_type": "SELECTED",
      "innovation_route": "R2_DEPTH_EXTENSION",
      "innovation_form": "F4_ALGORITHM_DEEPENING",
      "primary_forms": ["F4_ALGORITHM_DEEPENING"],
      "primary_profile": "ALGORITHM",
      "selected_by": "USER",
      "user_confirmation": "confirmed",
      "reason": "Deepen the selected algorithm without changing the primary contribution form.",
      "previous_event_sha256": "",
      "event_sha256": "<canonical event hash>"
    }
  ]
}
```

Event hashing excludes `event_sha256`, encodes canonical JSON as UTF-8 with sorted keys,
`ensure_ascii=false` and compact separators, and includes `previous_event_sha256`. The digest is
lowercase 64-character SHA-256. Generations are positive, contiguous and strictly increasing.
The first event is `SELECTED`; later events are only `RESTARTED`.

History is append-only in workflow semantics. An un-rehashed edit, deletion, reorder or
replacement breaks the chain. Recomputing the chain changes the head and therefore invalidates
the state and any bundle/audit bound to the old head. This is tamper-evident process enforcement,
not a claim that a local file can be made cryptographically immutable without an external anchor.

## 5. Drift detection

The route validator emits `INNOVATION_PATH_DRIFT` as `INVALID` when any of these occur:

- state route, form, generation, profile or head hash differs from the history head;
- the form/profile mapping is incompatible;
- a primary inventory claim belongs to an incompatible family;
- no compatible primary claim exists after claim freeze;
- an incompatible supporting claim is promoted to primary within the same generation;
- contribution architecture or scope declares a different primary form;
- computation or final lock is requested without a valid current route lock.

Missing route history or route-head state fields in an existing Schema 2.0 project is
`MIGRATION_REQUIRED`, not a guessed route. Migration is a user-input-required operation: the tool
must not infer the original choice from manuscript vocabulary, `claim_profile`, or artifacts.

## 6. Explicit restart

Path change is allowed only after explicit user confirmation and must be represented by a new
`RESTARTED` event. A restart command performs one recoverable transaction:

1. verify the existing history and state;
2. append a new generation linked to the prior event hash;
3. preserve the prior history and record the user's confirmation and reason;
4. set the new route, form and derived profile;
5. reset workflow to `SCOPE_LOCK`, novelty to `N0-3`, validity to `V0`;
6. increment `validation_epoch`;
7. clear claim bundle, independent audit and compute evidence;
8. set `compute_authorized = false` and `compute_stage = NOT_STARTED`;
9. require new scope, inventory, collision, form, audit and bundle artifacts.

The restart command must create timestamped byte-identical backups of the state and history
before atomic replacement. It refuses operation unless an explicit `--user-confirmed` flag and a
non-empty reason are supplied. Failure at any validation, backup or publish step leaves the
original state and history in place.

The implementation surface is intentionally narrow:

- `validate_innovation_route.py` validates history, state and primary claim compatibility;
- `restart_innovation_route.py` is the only supported route-change writer;
- `validate_all.py` runs route validation before other readiness validators;
- the existing migration command reports the required route-selection action but never chooses
  a route for the user.

## 7. State-machine integration

The route lock is checked before novelty, validity or compute readiness:

```text
ROUTE_LOCK_VALID
  AND existing novelty prerequisites
  AND existing validity prerequisites
```

`CLAIM_FREEZE`, `DIRECTION_LOCK`, `COMPUTE`, `FINAL_VALIDITY_AUDIT`, and `FINAL_LOCK` all require a
current valid route head. Route drift is `INVALID` and therefore outranks external `BLOCKED`
conditions. A route restart invalidates previous V3/V4 audits through the normal epoch and bundle
mechanism. Before `CLAIM_FREEZE`, the route still constrains candidate ranking and artifact
generation; the absence of a frozen claim inventory does not authorize exploration of a second
primary path.

## 8. Skill behavior

The main skill must state these disciplines explicitly:

- Ask the user to choose route and form before collision work becomes directional.
- Repeat the locked route/form in every handoff and next-action report.
- Evaluate discoveries through the locked path: a theorem found during F4 is supporting evidence,
  not permission to switch to F1.
- Never silently reinterpret `claim_profile = MIXED` to legitimize path drift.
- When a different primary path appears attractive, stop and offer an explicit restart; do not
  pursue both primary paths in parallel.

## 9. Testing and acceptance

Tests must demonstrate:

1. F4 plus a primary theorem claim fails with `INNOVATION_PATH_DRIFT`.
2. F4 plus a supporting theorem claim remains valid and retains `ALGORITHM` profile.
3. State/history route, form, profile, generation and head mismatches fail.
4. Old-event mutation or deletion breaks the hash chain.
5. Missing history requires migration rather than route inference.
6. Route drift prevents COMPUTE and FINAL_LOCK.
7. Restart without explicit user confirmation fails without changing files.
8. Confirmed restart appends generation, preserves history/backups and resets all readiness state.
9. Documentation and templates expose the invariant and the one allowed restart procedure.
10. `MIXED` without its originally confirmed multi-form set fails and cannot be synthesized from
    later discoveries.
11. The full skill suite, package validation and standalone minimal fixture remain green.

No paper-specific regression or manuscript review is part of this change.
