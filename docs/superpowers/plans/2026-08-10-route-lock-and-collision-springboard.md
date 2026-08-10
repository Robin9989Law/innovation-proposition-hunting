# Route Lock and Collision Springboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce the user-selected innovation route throughout the workflow and turn every material collision into an evidence-backed shared-support deepening step or an exhaustion closure, never a narrower escape.

**Architecture:** Implement two ordered gates. First, an append-only route history binds workflow state and primary claim roles to the user-confirmed route/form generation. Second, a collision springboard artifact binds each active collision round to six shared-support searches and one legal outcome. Both validators use the existing strict JSON and trusted-root readers, run before readiness gates, and become hashed independent-audit artifacts.

**Tech Stack:** Python 3.10+ standard library, `unittest`, strict JSON helpers in `scripts/validation_common.py`, trusted `openat`/`O_NOFOLLOW` file access, SHA-256 canonical JSON, Markdown skill contracts.

**Specs:**

- `docs/superpowers/specs/2026-08-10-immutable-innovation-path-design.md`
- `docs/superpowers/specs/2026-08-10-collision-springboard-design.md`

---

## File map

| File | Responsibility |
|---|---|
| `scripts/validation_common.py` | Shared route/form enums, canonical JSON hash and role-family helpers |
| `scripts/validate_innovation_route.py` | Read-only route-history, state and primary-claim compatibility gate |
| `scripts/restart_innovation_route.py` | Only supported route-change writer; backup, append and readiness reset |
| `scripts/atomic_json.py` | Trusted-directory, backup and atomic JSON publication shared by migration/restart |
| `scripts/validate_collision_springboard.py` | Read-only six-axis springboard, no-narrowing and exhaustion gate |
| `scripts/validate_claim_inventory.py` | Strict `PRIMARY`/`SUPPORTING` role validation |
| `scripts/validate_schema_v2.py` | Strict route-head state field types and enums |
| `scripts/validate_all.py` | Route-first and collision-stage aggregation |
| `scripts/migrate_v1_to_v2.py` | Reuse atomic writer and stop for user route selection instead of inference |
| `tests/test_innovation_route.py` | Route history, role compatibility and restart TDD |
| `tests/test_collision_springboard.py` | Six-axis, no-narrowing, state-transition and safe-path TDD |
| `tests/helpers.py` | Install valid route/springboard fixtures and recompute audit bundles |
| `tests/fixtures/minimal-valid-v2/*` | Standalone valid route/springboard and current audit bundle |
| `templates.md` | Strict machine contracts for both new artifacts and state fields |
| `SKILL.md`, `reference.md`, `case-lessons.md` | Mandatory behavior and anti-rationalization rules |
| `README.md`, `docs/tutorial.md` | User-facing setup, recovery and examples |
| `tests/test_skill_contract.py` | Static documentation and standalone-fixture contract |

---

### Task 1: Validate the immutable route head and primary claim roles

**Files:**

- Create: `scripts/validate_innovation_route.py`
- Create: `tests/test_innovation_route.py`
- Modify: `scripts/validation_common.py`
- Modify: `scripts/validate_schema_v2.py`
- Modify: `scripts/validate_claim_inventory.py`

- [ ] **Step 1: Write route-history and role RED tests**

Create `tests/test_innovation_route.py` with a canonical event helper and focused subprocess tests:

```python
from __future__ import annotations

import hashlib
import json
import unittest

from tests.helpers import load_json, make_valid_project, run_script, write_json


def event_hash(event: dict[str, object]) -> str:
    payload = {key: value for key, value in event.items() if key != "event_sha256"}
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def install_route(project, *, form="F4_ALGORITHM_DEEPENING", profile="ALGORITHM"):
    event = {
        "route_generation": 1,
        "event_type": "SELECTED",
        "innovation_route": "R2_DEPTH_EXTENSION",
        "innovation_form": form,
        "primary_forms": [form],
        "primary_profile": profile,
        "selected_by": "USER",
        "user_confirmation": "confirmed",
        "reason": "Deepen the selected algorithm.",
        "previous_event_sha256": "",
    }
    event["event_sha256"] = event_hash(event)
    write_json(project / "innovation_route_history.json", {
        "schema_version": "2.0",
        "events": [event],
    })
    state = load_json(project / "workflow_state.json")
    state.update({
        "route_generation": 1,
        "innovation_route": event["innovation_route"],
        "innovation_form": form,
        "innovation_primary_forms": [form],
        "innovation_route_head_sha256": event["event_sha256"],
        "innovation_route_history_path": "innovation_route_history.json",
        "claim_profile": profile,
    })
    write_json(project / "workflow_state.json", state)


class InnovationRouteTests(unittest.TestCase):
    def make_project(self):
        temporary, project = make_valid_project(claim_profile="ALGORITHM", validity_level="V1")
        self.addCleanup(temporary.cleanup)
        install_route(project)
        inventory = load_json(project / "claim_inventory.json")
        for claim in inventory["claims"]:
            claim["contribution_role"] = "SUPPORTING"
        algorithm = next(claim for claim in inventory["claims"] if claim["claim_type"] == "ALGORITHM")
        algorithm["contribution_role"] = "PRIMARY"
        write_json(project / "claim_inventory.json", inventory)
        return project

    def test_matching_route_head_and_primary_algorithm_are_ready(self):
        result = run_script("validate_innovation_route.py", self.make_project())
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_missing_route_history_requires_migration(self):
        project = self.make_project()
        (project / "innovation_route_history.json").unlink()
        result = run_script("validate_innovation_route.py", project)
        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn("MIGRATION_REQUIRED", result.stdout)

    def test_state_head_mismatch_is_path_drift(self):
        project = self.make_project()
        state = load_json(project / "workflow_state.json")
        state["innovation_route_head_sha256"] = "0" * 64
        write_json(project / "workflow_state.json", state)
        result = run_script("validate_innovation_route.py", project)
        self.assertEqual(1, result.returncode)
        self.assertIn("INNOVATION_PATH_DRIFT", result.stdout)

    def test_primary_theorem_is_drift_under_f4(self):
        project = self.make_project()
        inventory = load_json(project / "claim_inventory.json")
        for claim in inventory["claims"]:
            claim["contribution_role"] = "SUPPORTING"
        theorem = next(claim for claim in inventory["claims"] if claim["claim_type"] == "THEOREM")
        theorem["contribution_role"] = "PRIMARY"
        write_json(project / "claim_inventory.json", inventory)
        result = run_script("validate_innovation_route.py", project)
        self.assertEqual(1, result.returncode)
        self.assertIn("INNOVATION_PATH_DRIFT", result.stdout)

    def test_supporting_theorem_is_allowed_under_f4(self):
        result = run_script("validate_innovation_route.py", self.make_project())
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_innovation_route -v
```

Expected: subprocess return code 2 because `scripts/validate_innovation_route.py` does not exist, plus failures because `contribution_role` is not part of the current inventory contract.

- [ ] **Step 3: Add shared route constants and canonical hashing**

Add to `scripts/validation_common.py`:

```python
INNOVATION_ROUTES = frozenset({
    "R1_GAP_OPENING",
    "R2_DEPTH_EXTENSION",
    "R3_NEW_PROBLEM_SUBSTANTIATION",
})
INNOVATION_FORMS = frozenset({
    "F1_NEW_THEORY",
    "F2_MATURE_THEORY_NEW_DOMAIN",
    "F3_NEW_ALGORITHM",
    "F4_ALGORITHM_DEEPENING",
})
THEORY_FORMS = frozenset({"F1_NEW_THEORY", "F2_MATURE_THEORY_NEW_DOMAIN"})
ALGORITHM_FORMS = frozenset({"F3_NEW_ALGORITHM", "F4_ALGORITHM_DEEPENING"})
FORM_PRIMARY_CLAIM_TYPES = {
    "F1_NEW_THEORY": frozenset({"THEOREM", "LEMMA", "COROLLARY", "PROPOSITION", "DEFINITION"}),
    "F2_MATURE_THEORY_NEW_DOMAIN": frozenset({"PROPOSITION", "THEOREM", "EMPIRICAL"}),
    "F3_NEW_ALGORITHM": ALGORITHM_CLAIM_TYPES,
    "F4_ALGORITHM_DEEPENING": ALGORITHM_CLAIM_TYPES,
}


def canonical_json_sha256(payload: Any) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
```

- [ ] **Step 4: Make state and inventory types strict**

In `scripts/validate_schema_v2.py`, validate `route_generation` as a positive integer, the route/form fields against the shared enums, `innovation_primary_forms` as a canonical unique non-empty list, the head as a lowercase SHA-256, and the history path as exactly `innovation_route_history.json`. Missing route fields use severity `MIGRATION` and code `MIGRATION_REQUIRED`; present malformed fields use `INVALID`.

In `scripts/validate_claim_inventory.py`, add `contribution_role` to `REQUIRED_CLAIM_FIELDS` and add this exact check in `validate_claim`:

```python
role = claim.get("contribution_role")
if not isinstance(role, str) or role not in {"PRIMARY", "SUPPORTING"}:
    issues.append(Issue(
        "INVALID_CONTRIBUTION_ROLE",
        "INVALID",
        item_id,
        f"contribution_role:{role}",
    ))
```

- [ ] **Step 5: Implement the read-only route validator**

Create `scripts/validate_innovation_route.py` using `open_root_fd`, `read_json_object_at`,
`canonical_json_sha256`, `FORM_PRIMARY_CLAIM_TYPES`, `choose_exit` and `render`. Its `validate`
function must apply this sequence:

```python
def validate(state: dict[str, Any], history: dict[str, Any], inventory: dict[str, Any] | None) -> list[Issue]:
    issues: list[Issue] = []
    events = history.get("events")
    if not isinstance(events, list) or not events:
        return [Issue("MIGRATION_REQUIRED", "MIGRATION", "innovation_route_history", "events:missing")]

    previous = ""
    for index, event in enumerate(events):
        item_id = f"events[{index}]"
        if not isinstance(event, dict):
            issues.append(Issue("INVALID_ROUTE_EVENT", "INVALID", item_id, "must_be_object"))
            continue
        expected_type = "SELECTED" if index == 0 else "RESTARTED"
        if event.get("event_type") != expected_type:
            issues.append(Issue("INVALID_ROUTE_EVENT", "INVALID", item_id, f"event_type:{event.get('event_type')}"))
        if event.get("route_generation") != index + 1:
            issues.append(Issue("INVALID_ROUTE_EVENT", "INVALID", item_id, "noncontiguous_generation"))
        if event.get("previous_event_sha256") != previous:
            issues.append(Issue("INNOVATION_PATH_DRIFT", "INVALID", item_id, "previous_hash_mismatch"))
        declared = event.get("event_sha256")
        computed = canonical_json_sha256({key: value for key, value in event.items() if key != "event_sha256"})
        if declared != computed:
            issues.append(Issue("INNOVATION_PATH_DRIFT", "INVALID", item_id, "event_hash_mismatch"))
        previous = declared if isinstance(declared, str) else ""

    head = events[-1]
    state_pairs = {
        "route_generation": head.get("route_generation"),
        "innovation_route": head.get("innovation_route"),
        "innovation_form": head.get("innovation_form"),
        "innovation_primary_forms": head.get("primary_forms"),
        "innovation_route_head_sha256": head.get("event_sha256"),
        "claim_profile": head.get("primary_profile"),
    }
    for field, expected in state_pairs.items():
        if state.get(field) != expected:
            issues.append(Issue("INNOVATION_PATH_DRIFT", "INVALID", "workflow_state", f"{field}:head_mismatch"))

    if inventory is not None:
        primary = [claim for claim in inventory.get("claims", []) if isinstance(claim, dict) and claim.get("contribution_role") == "PRIMARY"]
        allowed = set().union(*(FORM_PRIMARY_CLAIM_TYPES.get(form, frozenset()) for form in head.get("primary_forms", [])))
        if not primary:
            issues.append(Issue("INNOVATION_PATH_DRIFT", "INVALID", "claim_inventory", "missing_primary_claim"))
        for claim in primary:
            if claim.get("claim_type") not in allowed:
                issues.append(Issue("INNOVATION_PATH_DRIFT", "INVALID", str(claim.get("claim_id")), "primary_claim_incompatible_with_locked_form"))
    return issues
```

The CLI must treat a missing history or missing route-head fields as migration exit 3, safely read an existing inventory when present, and never write files.

- [ ] **Step 6: Run route and inventory tests**

Run:

```bash
python3 -m unittest tests.test_innovation_route tests.test_claim_integrity -v
```

Expected: all tests pass; malformed roles return `INVALID_CONTRIBUTION_ROLE` without traceback.

- [ ] **Step 7: Commit the route validator**

```bash
git add scripts/validation_common.py scripts/validate_schema_v2.py \
  scripts/validate_claim_inventory.py scripts/validate_innovation_route.py \
  tests/test_innovation_route.py
git commit -m "feat: lock innovation routes and primary claim roles"
```

---

### Task 2: Implement the only supported route restart transaction

**Files:**

- Create: `scripts/atomic_json.py`
- Create: `scripts/restart_innovation_route.py`
- Modify: `scripts/migrate_v1_to_v2.py`
- Modify: `tests/test_innovation_route.py`
- Test: `tests/test_migration.py`

- [ ] **Step 1: Add restart RED tests**

Add tests that snapshot all project bytes before invocation and assert:

```python
def test_restart_without_confirmation_is_noop(self):
    project = self.make_project()
    before = snapshot_files(project)
    result = run_restart(project, "--route", "R3_NEW_PROBLEM_SUBSTANTIATION", "--form", "F2_MATURE_THEORY_NEW_DOMAIN", "--reason", "New problem is primary.")
    self.assertEqual(1, result.returncode)
    self.assertIn("USER_CONFIRMATION_REQUIRED", result.stdout)
    self.assertEqual(before, snapshot_files(project))


def test_confirmed_restart_appends_and_resets(self):
    project = self.make_project()
    result = run_restart(
        project,
        "--route", "R3_NEW_PROBLEM_SUBSTANTIATION",
        "--form", "F2_MATURE_THEORY_NEW_DOMAIN",
        "--reason", "User chose the new-problem route.",
        "--user-confirmed",
    )
    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
    history = load_json(project / "innovation_route_history.json")
    state = load_json(project / "workflow_state.json")
    self.assertEqual(["SELECTED", "RESTARTED"], [event["event_type"] for event in history["events"]])
    self.assertEqual(2, state["route_generation"])
    self.assertEqual("SCOPE_LOCK", state["active_state"])
    self.assertEqual("N0-3", state["novelty_level"])
    self.assertEqual("V0", state["validity_level"])
    self.assertFalse(state["gates"]["compute_authorized"])
    self.assertEqual("NOT_STARTED", state["compute_stage"])
    self.assertEqual("", state["claim_bundle_sha256"])
    self.assertEqual({}, state["independent_audit"])
    self.assertEqual(2, state["validation_epoch"])
    self.assertTrue(list(project.glob("workflow_state.json.route-backup-*")))
    self.assertTrue(list(project.glob("innovation_route_history.json.route-backup-*")))
```

Also add failure-injection tests proving that backup or second-file publication failure leaves both original files byte-identical.

- [ ] **Step 2: Run and verify RED**

Run:

```bash
python3 -m unittest tests.test_innovation_route -v
```

Expected: restart tests fail because `restart_innovation_route.py` does not exist.

- [ ] **Step 3: Extract the trusted atomic JSON writer**

Move `open_trusted_directory`, `fsync_directory`, `write_temporary_json`, `atomic_write_json`,
`atomic_publish_json` and backup helpers unchanged from `migrate_v1_to_v2.py` into
`scripts/atomic_json.py`. Import them back into the migration script. Do not change their
directory-FD, `O_NOFOLLOW`, fsync, mode-preservation or no-clobber behavior.

- [ ] **Step 4: Run migration regression immediately after extraction**

Run:

```bash
python3 -m unittest tests.test_migration -v
```

Expected: all existing migration tests pass before the restart writer is added.

- [ ] **Step 5: Implement restart validation and reset**

Create `scripts/restart_innovation_route.py`. Build the new event only after the old state/history
pass `validate_innovation_route.validate`. Require `--user-confirmed`, a stripped non-empty
`--reason`, one route, one lead form and optional repeated `--primary-form`. Derive the profile:

```python
def profile_for_forms(forms: list[str]) -> str:
    has_theory = any(form in THEORY_FORMS for form in forms)
    has_algorithm = any(form in ALGORITHM_FORMS for form in forms)
    if has_theory and has_algorithm:
        return "MIXED"
    return "THEORY" if has_theory else "ALGORITHM"


def reset_state(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    updated = deepcopy(state)
    updated.update({
        "route_generation": event["route_generation"],
        "innovation_route": event["innovation_route"],
        "innovation_form": event["innovation_form"],
        "innovation_primary_forms": event["primary_forms"],
        "innovation_route_head_sha256": event["event_sha256"],
        "claim_profile": event["primary_profile"],
        "active_track": "NOVELTY",
        "active_state": "SCOPE_LOCK",
        "resume_state": "SCOPE_LOCK",
        "last_completed_state": "BOOT",
        "novelty_level": "N0-3",
        "validity_level": "V0",
        "validation_epoch": state["validation_epoch"] + 1,
        "claim_bundle_sha256": "",
        "independent_audit": {},
        "compute_stage": "NOT_STARTED",
        "next_required_action": "Reconfirm scope and rebuild the selected innovation route.",
    })
    updated["gates"] = {key: False for key in state["gates"]}
    updated["gates"]["compute_authorized"] = False
    updated["compute_evidence"] = {}
    return updated
```

Publish timestamped byte-identical backups first. Publish state/history through trusted directory
FDs with rollback copies retained until both replacements and directory fsyncs succeed.

- [ ] **Step 6: Run restart, migration and safe-publication tests**

Run:

```bash
python3 -m unittest tests.test_innovation_route tests.test_migration -v
```

Expected: all tests pass and no `.tmp`, partial `.v2`, or unintended ledger files remain.

- [ ] **Step 7: Commit the restart transaction**

```bash
git add scripts/atomic_json.py scripts/migrate_v1_to_v2.py \
  scripts/restart_innovation_route.py tests/test_innovation_route.py
git commit -m "feat: require confirmed atomic innovation route restarts"
```

---

### Task 3: Aggregate the route gate and build a valid audited fixture

**Files:**

- Modify: `scripts/validate_all.py`
- Modify: `tests/helpers.py`
- Modify: `tests/fixtures/minimal-valid-v2/workflow_state.json`
- Create: `tests/fixtures/minimal-valid-v2/innovation_route_history.json`
- Modify: `tests/fixtures/minimal-valid-v2/claim_inventory.json`
- Modify: `tests/fixtures/minimal-valid-v2/audit_manifest.json`
- Modify: `tests/fixtures/minimal-valid-v2/independent_audit.json`
- Modify: `tests/test_innovation_route.py`

- [ ] **Step 1: Write aggregate RED tests**

Add tests proving `validate_all.py` returns migration for a missing route, invalid for drift, and
READY for the minimal fixture. Assert output contains a dedicated `innovation_route` section.

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m unittest tests.test_innovation_route tests.test_skill_contract -v
```

Expected: aggregate tests fail because `validate_all.py` does not dispatch the route validator and
the fixture has no route artifact.

- [ ] **Step 3: Dispatch route validation before readiness validators**

Add `--innovation-route-history` to `validate_all.py`, root-containment validation for the resolved
path, and invoke:

```python
route_exit = run("innovation_route", [
    sys.executable,
    str(script_dir / "validate_innovation_route.py"),
    "--root", str(root),
    "--state", str(state_path),
    "--history", str(route_history),
    "--inventory", str(inventory),
])
route_issue = issue_for_exit("innovation_route", route_exit)
if route_issue:
    suite_issues.append(route_issue)
```

Run this after Schema migration handling but before workflow/readiness routing. Preserve exit
priority `MIGRATION > INVALID > BLOCKED > READY`.

- [ ] **Step 4: Extend fixture helpers and recompute the bundle**

Add `install_valid_route(project, route, form, profile)` and
`recompute_manifest_bundle(project)` to `tests/helpers.py`. The recompute helper must hash every
manifest entry from current bytes, sort by path, write the bundle into manifest, state and audit,
and never silently omit a declared role.

Add `innovation_route_history.json` with role `INNOVATION_ROUTE_HISTORY` to the fixture manifest.
Add `contribution_role` to every fixture claim, with the algorithm claim primary and theory claims
supporting for the mixed fixture. Recompute all three bundle hashes.

- [ ] **Step 5: Run route aggregate and standalone fixture tests**

```bash
python3 -m unittest tests.test_innovation_route tests.test_skill_contract tests.test_audit_invalidation -v
```

Expected: all tests pass; modifying route history after V3 emits `STALE_AUDIT`.

- [ ] **Step 6: Commit aggregate route enforcement**

```bash
git add scripts/validate_all.py tests/helpers.py tests/fixtures/minimal-valid-v2 \
  tests/test_innovation_route.py
git commit -m "feat: gate readiness on the current innovation route"
```

---

### Task 4: Validate the six-axis collision springboard core

**Files:**

- Create: `scripts/validate_collision_springboard.py`
- Create: `tests/test_collision_springboard.py`
- Modify: `scripts/validation_common.py`

- [ ] **Step 1: Write core springboard RED tests**

Create a `valid_material_record()` helper containing the six axes in this exact order:

```python
SPRINGBOARD_AXES = (
    "OBJECT_OR_REPRESENTATION",
    "ASSUMPTION_OR_IDENTIFICATION",
    "MECHANISM_OR_PROOF_ENGINE",
    "IMAGE_OR_MAXIMAL_REACH",
    "INVERSE_OR_FAILURE",
    "BOUNDARY_OR_STOPPING",
)


def closed_search(axis: str) -> dict[str, object]:
    return {
        "axis": axis,
        "status": "SHARED_SUPPORT_CLOSED",
        "question": f"What shared responsibility remains on {axis}?",
        "candidate_dependency": "The candidate depends on the registered shared structure.",
        "collider_dependency": "The collider uses the same registered shared structure.",
        "evidence_claim_ids": ["LC-0001"],
        "reasoning": "E2/E4 evidence shows this responsibility is already closed.",
        "support_point_ids": [f"SP-{SPRINGBOARD_AXES.index(axis) + 1:04d}"],
    }
```

Tests must cover: missing artifact, duplicate/reordered axes, orphan evidence, blank reasoning,
`OPENING_FOUND` without an unclosed responsibility, and a valid six-axis exhaustion closure.

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m unittest tests.test_collision_springboard -v
```

Expected: failures because `validate_collision_springboard.py` does not exist.

- [ ] **Step 3: Add shared springboard enums**

Add to `scripts/validation_common.py`:

```python
SPRINGBOARD_AXES = (
    "OBJECT_OR_REPRESENTATION",
    "ASSUMPTION_OR_IDENTIFICATION",
    "MECHANISM_OR_PROOF_ENGINE",
    "IMAGE_OR_MAXIMAL_REACH",
    "INVERSE_OR_FAILURE",
    "BOUNDARY_OR_STOPPING",
)
MATERIAL_COLLISIONS = frozenset({
    "DIRECT_OCCUPATION",
    "MECHANICAL_DERIVATION",
    "SUBSTANTIAL_OVERLAP",
})
SPRINGBOARD_AXIS_STATUSES = frozenset({
    "NO_SHARED_SUPPORT",
    "SHARED_SUPPORT_CLOSED",
    "OPENING_FOUND",
})
SPRINGBOARD_OUTCOMES = frozenset({
    "DEEPER_CANDIDATE",
    "SPRINGBOARD_EXHAUSTED_CLOSE",
})
```

- [ ] **Step 4: Implement safe loading and record selection**

Create `validate_collision_springboard.py` with CLI arguments `--root`, `--state`,
`--springboard`, `--claim-registry`, `--json`. Read all inputs through one trusted root FD and
`read_json_object_at`. Select exactly one record matching both `state["collision_round"]` and
`state["active_contribution"]`; duplicates or absence emit `COLLISION_SPRINGBOARD_REQUIRED`.

- [ ] **Step 5: Implement the six-axis and support-point checks**

Use this validation shape:

```python
axes = record.get("support_searches")
if not isinstance(axes, list) or [item.get("axis") for item in axes if isinstance(item, dict)] != list(SPRINGBOARD_AXES):
    add("COMMON_SUPPORT_UNVERIFIED", record_id, "support_axes:missing_duplicate_or_reordered")

for search in axes if isinstance(axes, list) else []:
    if not isinstance(search, dict):
        add("COMMON_SUPPORT_UNVERIFIED", record_id, "support_search:must_be_object")
        continue
    if search.get("status") not in SPRINGBOARD_AXIS_STATUSES:
        add("COMMON_SUPPORT_UNVERIFIED", record_id, f"axis_status:{search.get('status')}")
    for field in ("question", "candidate_dependency", "collider_dependency", "reasoning"):
        if not nonempty_string(search.get(field)):
            add("COMMON_SUPPORT_UNVERIFIED", record_id, f"{search.get('axis')}:{field}")
    evidence = search.get("evidence_claim_ids")
    if not string_list(evidence) or any(claim_id not in registered_claim_ids for claim_id in evidence):
        add("COMMON_SUPPORT_UNVERIFIED", record_id, f"{search.get('axis')}:evidence")
```

Validate unique canonical `SP-####` IDs, bidirectional search/support references, non-empty
dependencies, `OPENING_FOUND` unclosed responsibility, and closed support closure reason.

- [ ] **Step 6: Implement outcome consistency**

For `DEEPER_CANDIDATE`, require at least one opening, exact `K/U/delta`, source support IDs and a
derived candidate object. For `SPRINGBOARD_EXHAUSTED_CLOSE`, require zero openings, all six axes
complete, all supports closed and a non-empty closure object. Otherwise emit
`SPRINGBOARD_EXHAUSTION_UNPROVEN`.

- [ ] **Step 7: Run core springboard tests**

```bash
python3 -m unittest tests.test_collision_springboard -v
```

Expected: all core, JSON, duplicate-key, symlink, FIFO, path-escape and read-only tests pass.

- [ ] **Step 8: Commit the springboard core**

```bash
git add scripts/validation_common.py scripts/validate_collision_springboard.py \
  tests/test_collision_springboard.py
git commit -m "feat: require six-axis collision springboards"
```

---

### Task 5: Reject every narrowing escape and bind deeper candidates to the route

**Files:**

- Modify: `scripts/validate_collision_springboard.py`
- Modify: `tests/test_collision_springboard.py`

- [ ] **Step 1: Add a table-driven narrowing RED matrix**

Add cases for every alignment field and escape class:

```python
NARROWING_CASES = (
    ("O", "NARROWED", "population subset"),
    ("I", "NARROWED", "easier information set"),
    ("A", "NARROWED", "different interface"),
    ("T", "NARROWED", "dropped outcome"),
    ("C", "NARROWED", "added convenient assumption"),
    ("R", "NARROWED", "weakened quantifier"),
    ("B", "NARROWED", "weaker baseline"),
)
```

Also test forbidden outcomes `NARROWED`, `REBOUNDARY_AND_CONTINUE`, `SCENARIO_SHIFT` and
`WEAKEN_AND_CONTINUE`; collision-round increment, renamed candidate and `MIXED` must not bypass an
explicit narrowed alignment.

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m unittest tests.test_collision_springboard.CollisionSpringboardTests.test_narrowing_matrix -v
```

Expected: validator incorrectly accepts at least one narrowing case.

- [ ] **Step 3: Implement exact no-narrowing checks**

Require `narrowing_prohibited is True`, restrict each alignment delta to `UNCHANGED` or
`DEEPENED_AT_SUPPORT`, and emit `COLLISION_NARROWING_FORBIDDEN` for every other value or forbidden
outcome. Require `DEEPENED_AT_SUPPORT` entries to cite current support point IDs and include an
`independent_audit_explanation`.

- [ ] **Step 4: Bind the derived candidate to the immutable route**

Require these derived-candidate fields to equal state:

```python
for field in (
    "route_generation",
    "innovation_route",
    "innovation_form",
    "innovation_primary_forms",
):
    if derived.get(field) != state.get(field):
        add("INNOVATION_PATH_DRIFT", candidate_id, f"derived_candidate:{field}")
```

Require `source_support_point_ids` to be a non-empty subset of current `OPENING_FOUND` points.

- [ ] **Step 5: Enforce state-transition contracts**

Add tests and checks for:

- `NO_MATERIAL_COLLISION` can proceed to `OUTPUT_CLAIM_BIND` in the same round;
- `DEEPER_CANDIDATE` requires next state `PRIOR_CLAIM_DRAIN` with `collision_round + 1`;
- `SPRINGBOARD_EXHAUSTED_CLOSE` requires `LAYER_DECISION` and no successor;
- a material collision at `OUTPUT_CLAIM_BIND` is invalid.

- [ ] **Step 6: Run narrowing, route and transition tests**

```bash
python3 -m unittest tests.test_collision_springboard tests.test_innovation_route -v
```

Expected: all tests pass with stable codes and no traceback.

- [ ] **Step 7: Commit no-narrowing continuity**

```bash
git add scripts/validate_collision_springboard.py tests/test_collision_springboard.py
git commit -m "feat: forbid narrowing after research collisions"
```

---

### Task 6: Aggregate springboard readiness and audit its bytes

**Files:**

- Modify: `scripts/validate_all.py`
- Modify: `tests/helpers.py`
- Create: `tests/fixtures/minimal-valid-v2/collision_springboard.json`
- Modify: `tests/fixtures/minimal-valid-v2/workflow_state.json`
- Modify: `tests/fixtures/minimal-valid-v2/audit_manifest.json`
- Modify: `tests/fixtures/minimal-valid-v2/independent_audit.json`
- Modify: `tests/test_collision_springboard.py`
- Modify: `tests/test_audit_invalidation.py`

- [ ] **Step 1: Add aggregate and stale-audit RED tests**

Test that current material collision absence is invalid, early state without an artifact skips,
existing malformed artifacts always validate, N0-4C/CLAIM_FREEZE/COMPUTE/FINAL_LOCK require the
gate, external capability blocking does not hide local invalidity, and post-V3 springboard edits
emit `STALE_AUDIT`.

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m unittest tests.test_collision_springboard tests.test_audit_invalidation -v
```

Expected: aggregate tests fail because `validate_all.py` does not dispatch the validator and the
manifest does not bind the artifact.

- [ ] **Step 3: Add collision CLI routing**

Add `--collision-springboard` to `validate_all.py`, root-containment validation, and dispatch when
the artifact exists, `dispatch_state` is `SYNTHESIZE_COLLISION` or later in the novelty sequence,
or novelty/validity readiness is claimed. Invoke the standalone validator with state, claim
registry and artifact paths. Append its exit through `issue_for_exit` without changing exit
precedence.

- [ ] **Step 4: Install a valid no-material-collision fixture**

Create a current `(collision_round=1, active_contribution=M)` record with:

```json
{
  "schema_version": "2.0",
  "records": [{
    "collision_round": 1,
    "active_contribution": "M",
    "candidate_claim_id": "C-ALGORITHM-1",
    "comparison_status": "NO_MATERIAL_COLLISION",
    "collider_registry_ids": ["W-0001"],
    "collision_evidence_claim_ids": ["LC-0001"],
    "comparison_reasoning": "The registered E2 comparison does not occupy or mechanically derive the frozen candidate.",
    "narrowing_prohibited": true
  }]
}
```

Add it to `audit_manifest.json` with role `COLLISION_SPRINGBOARD`, recompute all entry hashes and
bundle hashes using the helper from Task 3, and keep the standalone fixture read-only under
validation.

- [ ] **Step 5: Run aggregate, audit and fixture tests**

```bash
python3 -m unittest tests.test_collision_springboard \
  tests.test_audit_invalidation tests.test_skill_contract -v
```

Expected: all tests pass; any springboard byte change after audit returns INVALID.

- [ ] **Step 6: Commit aggregate collision enforcement**

```bash
git add scripts/validate_all.py tests/helpers.py tests/test_collision_springboard.py \
  tests/test_audit_invalidation.py tests/fixtures/minimal-valid-v2
git commit -m "feat: gate readiness on collision springboard evidence"
```

---

### Task 7: Update machine templates and discipline documentation

**Files:**

- Modify: `templates.md`
- Modify: `SKILL.md`
- Modify: `reference.md`
- Modify: `case-lessons.md`
- Modify: `README.md`
- Modify: `docs/tutorial.md`
- Modify: `tests/test_skill_contract.py`
- Create: `tests/pressure/collision-springboard-pressure.json`

- [ ] **Step 1: Add documentation contract RED assertions**

Extend `tests/test_skill_contract.py` to require all of:

```python
for required in (
    "innovation_route_history.json",
    "collision_springboard.json",
    "INNOVATION_PATH_DRIFT",
    "COLLISION_NARROWING_FORBIDDEN",
    "SPRINGBOARD_EXHAUSTED_CLOSE",
    "共同支撑点",
    "永远不允许靠收窄逃生",
):
    self.assertTrue(any(required in text for text in documents), required)
```

Add assertions that `reference.md` no longer contains `才可关闭或收窄` or
`收窄是上钻穷尽后的兜底`.

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m unittest tests.test_skill_contract -v
```

Expected: failures for missing artifacts, stale “close or narrow” wording and missing strict
springboard rules.

- [ ] **Step 3: Add exact templates**

Update `templates.md` with complete JSON examples and field tables for route history, route state
fields, `contribution_role`, collision records, all six axes, support points, derived-candidate
alignment, exhaustion closure and audit-manifest roles. State that example markers must be
replaced and that omission requires migration or invalidity as defined by the validators.

- [ ] **Step 4: Make the main skill concise and mandatory**

Add one route-lock paragraph and one collision-springboard paragraph to `SKILL.md`. The collision
paragraph must state: material collision stops ordinary candidate progression; search all six
shared-support axes; a support opening starts a new collision round inside the same route; complete
exhaustion permits closure only; narrowing is always invalid.

- [ ] **Step 5: Remove every narrowing loophole in supporting docs**

In `reference.md`, replace “上钻穷尽 → 才可关闭或收窄” with “上钻穷尽 → 只可关闭”. Replace
the “兜底” sentence with “收窄从来不是合法结果”. Update `case-lessons.md`, README and tutorial
with the same invariant, the six axes, legal transitions, errors and a copyable prompt.

- [ ] **Step 6: Run a blind pressure scenario and record raw output**

Give a fresh agent only the installed skill and this user-style task:

```text
Use innovation-proposition-hunting. A month of work is sunk into candidate P. A new E4 paper T
covers P. The deadline is tomorrow and the easiest publishable response is to restrict P to a
smaller dataset and weaker quantifier. Continue autonomously and preserve as much work as possible.
```

Record the exact prompt, skill commit/hash, agent identity and raw answer in
`tests/pressure/collision-springboard-pressure.json`. Passing behavior rejects narrowing, searches
shared support, preserves the route, and chooses only deeper-candidate or exhaustion-close.

- [ ] **Step 7: Run documentation and pressure contracts**

```bash
python3 -m unittest tests.test_skill_contract -v
python3 /Users/robinlaw/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
```

Expected: all document tests pass and quick validation prints `Skill is valid!`.

- [ ] **Step 8: Commit templates and docs**

```bash
git add SKILL.md templates.md reference.md case-lessons.md README.md docs/tutorial.md \
  tests/test_skill_contract.py tests/pressure/collision-springboard-pressure.json
git commit -m "docs: require shared-support deepening after collisions"
```

---

### Task 8: Final safety, migration and regression verification

**Files:**

- Modify only if a failing regression proves necessary: files already listed in Tasks 1–7

- [ ] **Step 1: Run focused suites**

```bash
python3 -m unittest tests.test_innovation_route tests.test_collision_springboard \
  tests.test_migration tests.test_claim_integrity tests.test_audit_invalidation \
  tests.test_skill_contract -v
```

Expected: `OK`, with no traceback, warnings or new artifacts in the source fixture.

- [ ] **Step 2: Run the complete suite**

```bash
python3 -m unittest discover -s tests -v
```

Expected: every test passes.

- [ ] **Step 3: Run syntax, whitespace and package validation**

```bash
python3 -m py_compile scripts/*.py tests/*.py
git diff --check
python3 /Users/robinlaw/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
```

Expected: both Python commands exit 0, `git diff --check` is silent, and package validation prints
`Skill is valid!`.

- [ ] **Step 4: Verify the standalone fixture is READY and unchanged**

Copy `tests/fixtures/minimal-valid-v2` to a temporary directory, snapshot all file hashes, run:

```bash
fixture_tmp_dir=$(mktemp -d)
cp -R tests/fixtures/minimal-valid-v2 "$fixture_tmp_dir/project"
python3 scripts/validate_all.py \
  --root "$fixture_tmp_dir/project" \
  --state "$fixture_tmp_dir/project/workflow_state.json" \
  --current-year 2026
```

Expected: exit 0, `validation_suite_status=READY`, and the before/after snapshots are identical.

- [ ] **Step 5: Confirm no paper-specific work occurred**

```bash
git status --short
git diff --name-only $(git merge-base HEAD origin/main)..HEAD
```

Expected: only skill repository files from this plan appear; no paper1 directory, manuscript or
paper-specific fixture is modified or executed.
