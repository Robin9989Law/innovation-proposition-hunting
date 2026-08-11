> **状态：已归档（2026-08-11）**。本文件是 Schema 2.0 实施前的设计/计划档案，内容可能已过时；现行规范以 SKILL.md、templates.md 与 scripts/ 校验器为准。

# Schema v2 Claim Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the skill's structurally valid but semantically weak Schema 1.x workflow with mandatory Schema 2.0 novelty-plus-validity gates that catch stale audits, self-review, unsupported theorem strength, protocol/code mismatches and frontier-evidence downgrades.

**Architecture:** Keep the existing novelty workflow, rename its highest pre-validity result to `N0-4C`, and add form-sensitive V0–V4 claim-validity readiness. Implement small read-only validators sharing one result model, orchestrate them through `validate_all.py`, and use content hashes plus different-agent provenance to invalidate stale audits. Develop every behavior test-first and validate the documentation change with fresh-agent pressure tests.

**Tech Stack:** Python 3 standard library (`argparse`, `dataclasses`, `enum`, `hashlib`, `json`, `pathlib`, `re`, `unittest`), Markdown skill resources, Git.

---

## File map

### New runtime files

- `scripts/validation_common.py`: shared issue/result types, exit-code selection, JSON/text CLI rendering and safe path/hash helpers.
- `scripts/validate_schema_v2.py`: mandatory Schema 2.0, state/track/readiness and form-routing checks.
- `scripts/validate_claim_inventory.py`: manuscript high-risk-claim scanner and inventory completeness checks.
- `scripts/validate_theory_obligations.py`: F1 theorem/lemma/corollary obligation and witness checks.
- `scripts/validate_protocol_contract.py`: algorithm protocol and baseline-budget checks.
- `scripts/validate_claim_code_trace.py`: algorithm claim-to-pseudocode/code/test trace checks.
- `scripts/validate_frontier_integrity.py`: coverage-matrix, importance-history, downgrade and evidence-tier checks.
- `scripts/validate_audit_provenance.py`: author/reviewer separation and exact-bundle audit checks.
- `scripts/validate_artifact_hashes.py`: manifest path, file hash, bundle hash and epoch checks.
- `scripts/migrate_v1_to_v2.py`: explicit recoverable migration that resets validity to V0.

### Modified runtime files

- `scripts/validate_all.py`: state-aware orchestration without hiding contradictions.
- `scripts/validate_workflow_state.py`: either delegate to Schema v2 or become a thin compatibility entry point returning migration-required for 1.x.
- `scripts/validate_evidence_chain.py`: distinguish metadata/abstract/fulltext evidence and consume importance history.
- `scripts/validate_literature_registry.py`: retain URL/identity checks and add Schema 2.0 registry version enforcement.

### Documentation and templates

- `SKILL.md`: concise Schema 2.0 mandatory router and stop rules.
- `templates.md`: complete state, claim inventory, theory obligation, protocol, code trace, audit and coverage templates.
- `reference.md`: V-axis adjudication, proof/protocol gates and high-risk claim semantics.
- `evidence-pipeline.md`: evidence-kind semantics, append-only importance history and reclassification contract.
- `compute-funnel.md`: require N0-4C+V3 before compute and V4 before final lock.
- `case-lessons.md`: generalize the paper-1 failure into reusable lessons without project-specific narrative.

### Tests

- `tests/helpers.py`: temporary-project builder and JSON helpers.
- `tests/test_schema_v2.py`
- `tests/test_claim_integrity.py`
- `tests/test_theory_obligations.py`
- `tests/test_protocol_contract.py`
- `tests/test_frontier_integrity.py`
- `tests/test_audit_invalidation.py`
- `tests/test_migration.py`
- `tests/fixtures/minimal-valid-v2/`: smallest fully valid mixed-profile project.
- `tests/fixtures/paper1-failure-case/`: anonymous raw theory/protocol/frontier traps.
- `tests/pressure/current-skill-baseline.json`: RED pressure-test prompt, agent provenance and observed misses.
- `tests/pressure/schema-v2-forward.json`: GREEN forward-test prompt, agent provenance and findings.

---

### Task 1: Establish the RED baseline before changing production files

**Files:**
- Create: `tests/fixtures/paper1-failure-case/manuscript.md`
- Create: `tests/fixtures/paper1-failure-case/online_eval.py`
- Create: `tests/fixtures/paper1-failure-case/workflow_state.json`
- Create: `tests/fixtures/paper1-failure-case/near_neighbor_registry.json`
- Create: `tests/pressure/current-skill-baseline.json`
- Create: `tests/test_schema_v2.py`

- [ ] **Step 1: Create the anonymous raw pressure fixture**

Put these exact traps in `manuscript.md`:

```markdown
# Anonymous candidate

For ridge residuals, contamination gives
\(e_i=e_i^0+(1-h_{ii})\eta\). Therefore the exact inverse is
\(e_i/(1-h_{ii})=e_i^0+\eta\).

If \(r_t=r_1/[1+(t-1)c]\), the final visible update is
\(T^*=\lceil |r_1|/(c\tau)-1\rceil\).

For a full-rank design, rank saturation implies \(df\to n\) at fixed
positive regularization. Algorithm 1 uses per-sample test-then-train.
```

Put this exact implementation in `online_eval.py`:

```python
def evaluate(model, xs, ys, block=1000):
    predictions = []
    for start in range(0, len(xs), block):
        stop = min(start + block, len(xs))
        predictions.extend(model.predict(xs[start:stop]))
        for index in range(start, stop):
            model.update(xs[index], ys[index])
    return predictions
```

Create a Schema 1.0 state declaring `N0-4 LOCKED`, an old audit hash and all evidence gates true. Create a literature registry whose history/log identifies `W-0001` as CRITICAL while its mutable current importance is CONTEXT and only an abstract is available.

- [ ] **Step 2: Run a fresh subagent against the current skill**

Use this exact prompt without supplying the expected findings:

```text
Use $innovation-proposition-hunting at /Users/robinlaw/.agents/skills/innovation-proposition-hunting to decide whether the anonymous candidate in tests/fixtures/paper1-failure-case is ready to remain locked and proceed. Inspect the raw files and report the state transition and unique next action. Do not modify files.
```

Record the agent ID, thread/task ID, prompt, full verdict, issues found and issues missed in `tests/pressure/current-skill-baseline.json`. This is the required writing-skills RED observation.

- [ ] **Step 3: Write the first deterministic failing test**

```python
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SchemaV2Tests(unittest.TestCase):
    def test_schema_1_requires_explicit_migration(self):
        state = ROOT / "tests/fixtures/paper1-failure-case/workflow_state.json"
        result = subprocess.run(
            ["python3", str(ROOT / "scripts/validate_all.py"),
             "--root", str(state.parent), "--state", str(state)],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 3)
        self.assertIn("MIGRATION_REQUIRED", result.stdout)
```

- [ ] **Step 4: Run RED and verify the failure is meaningful**

Run:

```bash
python3 -m unittest tests.test_schema_v2.SchemaV2Tests.test_schema_1_requires_explicit_migration -v
```

Expected: FAIL because the current validator accepts Schema 1.0 or returns an exit code other than 3.

- [ ] **Step 5: Commit only RED artifacts and tests**

```bash
git add tests
git commit -m "test: capture schema v1 and claim-integrity failures"
```

---

### Task 2: Add the shared result model and mandatory Schema 2.0

**Files:**
- Create: `scripts/validation_common.py`
- Create: `scripts/validate_schema_v2.py`
- Create: `scripts/migrate_v1_to_v2.py`
- Modify: `scripts/validate_all.py`
- Modify: `scripts/validate_workflow_state.py`
- Test: `tests/test_schema_v2.py`
- Test: `tests/test_migration.py`

- [ ] **Step 1: Add failing exit-precedence and reviewer-independence tests**

```python
def test_author_cannot_review_own_bundle(self):
    project = make_valid_project(claim_profile="THEORY")
    state = load_json(project / "workflow_state.json")
    state["independent_audit"]["author_agent_ids"] = ["agent-a"]
    state["independent_audit"]["reviewer_agent_id"] = "agent-a"
    write_json(project / "workflow_state.json", state)
    result = run_validator(project)
    self.assertEqual(result.returncode, 1)
    self.assertIn("AUDITOR_NOT_INDEPENDENT", result.stdout)

def test_missing_reviewer_capability_is_blocked(self):
    project = make_valid_project(claim_profile="THEORY")
    state = load_json(project / "workflow_state.json")
    state["independent_audit"] = {"capability_available": False}
    write_json(project / "workflow_state.json", state)
    result = run_validator(project)
    self.assertEqual(result.returncode, 2)
    self.assertIn("BLOCKED_CAPABILITY", result.stdout)
```

Run `python3 -m unittest tests.test_schema_v2 -v`; expect both new tests to fail.

- [ ] **Step 2: Implement `validation_common.py`**

Use this public interface:

```python
from dataclasses import asdict, dataclass
from enum import IntEnum
import hashlib
import json
from pathlib import Path


class ExitCode(IntEnum):
    READY = 0
    INVALID = 1
    BLOCKED = 2
    MIGRATION_REQUIRED = 3


@dataclass(frozen=True)
class Issue:
    code: str
    severity: str  # INVALID | BLOCKED | MIGRATION
    item_id: str
    detail: str


def choose_exit(issues: list[Issue]) -> ExitCode:
    severities = {issue.severity for issue in issues}
    if "MIGRATION" in severities:
        return ExitCode.MIGRATION_REQUIRED
    if "INVALID" in severities:
        return ExitCode.INVALID
    if "BLOCKED" in severities:
        return ExitCode.BLOCKED
    return ExitCode.READY


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render(name: str, issues: list[Issue], as_json: bool = False) -> str:
    exit_code = choose_exit(issues)
    payload = {
        "validator": name,
        "status": exit_code.name,
        "exit_code": int(exit_code),
        "issues": [asdict(issue) for issue in issues],
    }
    if as_json:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    lines = [f"{name}_status={exit_code.name}", f"{name}_issues={len(issues)}"]
    lines.extend(
        f"{issue.severity}\t{issue.code}\t{issue.item_id}\t{issue.detail}"
        for issue in issues
    )
    return "\n".join(lines)
```

- [ ] **Step 3: Implement mandatory Schema 2.0 validation**

`validate_schema_v2.py` must reject non-2.0 schemas before checking other fields, validate `active_track`, `novelty_level`, `validity_level`, `claim_profile`, `validation_epoch`, and require disjoint reviewer/author IDs at V3/V4. If capability is explicitly unavailable, emit BLOCKED rather than INVALID.

Expose:

```python
def validate(root: Path, state: dict) -> list[Issue]:
    if state.get("schema_version") != "2.0":
        return [Issue("MIGRATION_REQUIRED", "MIGRATION", "workflow_state",
                      f"found:{state.get('schema_version')}")]
    # enum, state, profile, epoch and independence checks follow
```

- [ ] **Step 4: Make `validate_all.py` honor four exit codes**

Load the state, run Schema 2.0 first, stop only for `MIGRATION_REQUIRED`, and otherwise aggregate issues. Do not convert BLOCKED into success and do not skip contradictions in existing artifacts.

- [ ] **Step 5: Implement explicit migration**

`migrate_v1_to_v2.py` accepts `--root`, `--state`, optional `--output` and `--in-place`. It must set:

```python
state["schema_version"] = "2.0"
state["active_track"] = "VALIDITY"
state["active_state"] = "CLAIM_FREEZE"
state["novelty_level"] = "N0-4C" if old_n0_locked else "N0-3"
state["validity_level"] = "V0"
state["validation_epoch"] = 1
state["claim_bundle_sha256"] = ""
state["independent_audit"] = {}
state["gates"]["compute_authorized"] = False
```

Default output is `workflow_state.v2.json`. For `--in-place`, create `workflow_state.json.v1-backup-<UTC timestamp>` before replacing the state.

- [ ] **Step 6: Run schema and migration tests**

Run:

```bash
python3 -m unittest tests.test_schema_v2 tests.test_migration -v
```

Expected: PASS, including exit codes 0/1/2/3 and recoverable migration.

- [ ] **Step 7: Commit**

```bash
git add scripts tests/test_schema_v2.py tests/test_migration.py tests/helpers.py
git commit -m "feat: require schema v2 and explicit validity migration"
```

---

### Task 3: Inventory every high-risk manuscript claim

**Files:**
- Create: `scripts/validate_claim_inventory.py`
- Create: `tests/test_claim_integrity.py`
- Create: `tests/fixtures/minimal-valid-v2/claim_inventory.json`
- Modify: `tests/helpers.py`

- [ ] **Step 1: Write failing unregistered-claim tests**

```python
def test_unregistered_exact_claim_fails(self):
    project = make_valid_project(claim_profile="THEORY")
    (project / "manuscript.md").write_text(
        "The exact inverse recovers every anomaly losslessly.\n", encoding="utf-8"
    )
    write_json(project / "claim_inventory.json", {"schema_version": "2.0", "claims": []})
    result = run_script("validate_claim_inventory.py", project)
    self.assertEqual(result.returncode, 1)
    self.assertIn("UNREGISTERED_HIGH_RISK_CLAIM", result.stdout)

def test_claim_promotion_after_audit_fails(self):
    project = make_valid_project(claim_profile="THEORY", validity_level="V3")
    append_text(project / "manuscript.md", "The result is universally bounded.\n")
    result = run_validator(project)
    self.assertEqual(result.returncode, 1)
    self.assertIn("CLAIM_PROMOTION_UNAUDITED", result.stdout)
```

Run `python3 -m unittest tests.test_claim_integrity -v`; expect failures because no scanner exists.

- [ ] **Step 2: Implement stable occurrence scanning**

Scan Markdown and TeX manuscript sources declared in `claim_inventory.json`. Use case-insensitive English and Chinese patterns for the approved high-risk vocabulary plus theorem/lemma/corollary headings/environments. Build occurrence IDs from relative path, normalized containing line, term and duplicate ordinal:

```python
def occurrence_id(relative_path: str, line: str, term: str, ordinal: int) -> str:
    normalized = " ".join(line.split()).casefold()
    raw = f"{relative_path}\0{term.casefold()}\0{normalized}\0{ordinal}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
```

Every occurrence must appear in exactly one claim's `occurrence_ids`. Every claim requires `claim_id`, `statement`, `claim_type`, `locations`, `evidence_responsibility`, `risk_terms`, `status` and `validation_epoch`.

- [ ] **Step 3: Detect post-audit promotion**

At V3/V4, an occurrence not included in the audited bundle emits `CLAIM_PROMOTION_UNAUDITED`; at V0–V2 it emits `UNREGISTERED_HIGH_RISK_CLAIM`. Both are INVALID.

- [ ] **Step 4: Run claim tests**

```bash
python3 -m unittest tests.test_claim_integrity -v
```

Expected: PASS for exact/universal/bounded, Chinese equivalents, duplicate lines and normal prose without risk terms.

- [ ] **Step 5: Commit**

```bash
git add scripts/validate_claim_inventory.py tests/test_claim_integrity.py tests/helpers.py tests/fixtures/minimal-valid-v2
git commit -m "feat: inventory high-risk research claims"
```

---

### Task 4: Enforce F1 theorem obligations and falsification evidence

**Files:**
- Create: `scripts/validate_theory_obligations.py`
- Create: `tests/test_theory_obligations.py`
- Create: `tests/fixtures/minimal-valid-v2/theory_obligation_registry.json`

- [ ] **Step 1: Write failing obligation tests**

```python
def test_missing_nonzero_nuisance_case_fails(self):
    project = make_valid_project(claim_profile="THEORY")
    obligations = load_json(project / "theory_obligation_registry.json")
    obligations["obligations"][0]["witnesses"] = [
        witness("MINIMAL_POSITIVE", expected="PASS", observed="PASS"),
        witness("PREMISE_REMOVAL", expected="FAIL", observed="FAIL"),
    ]
    write_json(project / "theory_obligation_registry.json", obligations)
    result = run_script("validate_theory_obligations.py", project)
    self.assertIn("MISSING_WITNESS_NONZERO_NUISANCE", result.stdout)

def test_premise_removal_must_actually_fail(self):
    project = make_valid_project(claim_profile="THEORY")
    obligations = load_json(project / "theory_obligation_registry.json")
    replace_witness(obligations, "PREMISE_REMOVAL", expected="FAIL", observed="PASS")
    write_json(project / "theory_obligation_registry.json", obligations)
    result = run_script("validate_theory_obligations.py", project)
    self.assertIn("EXPECTED_FAILURE_DID_NOT_FAIL", result.stdout)
```

Also add cases for missing exact statement, premises, quantifiers, proof locator, boundary witness, output file, command, exit code and output hash.

Run `python3 -m unittest tests.test_theory_obligations -v`; expect failure before implementation.

- [ ] **Step 2: Implement form routing and required witness kinds**

For THEORY and MIXED profiles require every inventory claim of type `THEOREM`, `LEMMA` or `COROLLARY` to have one obligation. Required witness kinds are:

```python
REQUIRED_WITNESSES = {
    "MINIMAL_POSITIVE",
    "NONZERO_NUISANCE",
    "BOUNDARY_OR_LIMIT",
    "PREMISE_REMOVAL",
}
```

Allow `RANDOM_PROPERTY` to be inapplicable only with a non-empty mathematical reason accepted by the independent audit. Verify witness output paths and hashes with shared safe-path utilities.

- [ ] **Step 3: Enforce exact-statement identity**

The obligation's `claim_id`, `exact_statement_sha256` and `validation_epoch` must match the claim inventory. A mismatch emits `THEOREM_STATEMENT_STALE`.

- [ ] **Step 4: Run theory tests**

```bash
python3 -m unittest tests.test_theory_obligations -v
```

Expected: all theory-obligation tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/validate_theory_obligations.py tests/test_theory_obligations.py tests/fixtures/minimal-valid-v2
git commit -m "feat: require falsifiable theory obligations"
```

---

### Task 5: Enforce algorithm protocol, claim-code trace and fair baselines

**Files:**
- Create: `scripts/validate_protocol_contract.py`
- Create: `scripts/validate_claim_code_trace.py`
- Create: `tests/test_protocol_contract.py`
- Create: `tests/fixtures/minimal-valid-v2/protocol_contract.json`
- Create: `tests/fixtures/minimal-valid-v2/claim_code_trace.json`
- Create: `tests/fixtures/minimal-valid-v2/baseline_budget.json`

- [ ] **Step 1: Write failing online-chronology and baseline tests**

```python
def test_per_sample_online_claim_requires_passing_chronology_test(self):
    project = make_valid_project(claim_profile="ALGORITHM")
    protocol = load_json(project / "protocol_contract.json")
    protocol["prediction_unit"] = "SAMPLE"
    protocol["chronology_test"]["status"] = "MISSING"
    write_json(project / "protocol_contract.json", protocol)
    result = run_script("validate_protocol_contract.py", project)
    self.assertIn("ONLINE_CHRONOLOGY_UNVERIFIED", result.stdout)

def test_strong_baseline_requires_common_tuning_contract(self):
    project = make_valid_project(claim_profile="ALGORITHM")
    budgets = load_json(project / "baseline_budget.json")
    del budgets["comparators"][0]["regularization_search_space"]
    write_json(project / "baseline_budget.json", budgets)
    result = run_script("validate_protocol_contract.py", project)
    self.assertIn("BASELINE_BUDGET_INCOMPLETE", result.stdout)
```

Add a fixture trace that points the per-sample claim to the block implementation and lacks an executable test. Run the test module and observe RED.

- [ ] **Step 2: Implement protocol validation**

Require exact fields for prediction/update units, order, labels, chronological ordering, split, tuning/development/sealed roles and test accesses. For a `SAMPLE` prediction unit require a chronology-test artifact whose output hash is current and status is PASS.

Reject test-label updates unless the protocol explicitly declares supervised online adaptation, pre-update scoring, operational label availability and a non-confirmatory evaluation role.

- [ ] **Step 3: Implement baseline-budget validation**

For every `strong`, `fair`, `matched-budget` or `same-budget` inventory claim, require comparator contracts covering width/parameter budget, seeds, regularization search, tuning data, label access, update frequency, compute budget and stopping rules.

- [ ] **Step 4: Implement claim-code trace validation**

Each algorithm claim requires manuscript location, pseudocode symbol, implementation path and symbol, implementation SHA-256, executable test path/hash and PASS output path/hash. Reject missing symbols, unsafe paths, hash mismatches and tests that do not list the target claim ID.

- [ ] **Step 5: Run protocol tests**

```bash
python3 -m unittest tests.test_protocol_contract -v
```

Expected: PASS for the minimal valid algorithm fixture and FAIL cases converted to passing assertions.

- [ ] **Step 6: Commit**

```bash
git add scripts/validate_protocol_contract.py scripts/validate_claim_code_trace.py tests/test_protocol_contract.py tests/fixtures/minimal-valid-v2
git commit -m "feat: bind algorithm claims to protocol and code"
```

---

### Task 6: Make independent audits and artifact hashes authoritative

**Files:**
- Create: `scripts/validate_artifact_hashes.py`
- Create: `scripts/validate_audit_provenance.py`
- Create: `tests/test_audit_invalidation.py`
- Create: `tests/fixtures/minimal-valid-v2/audit_manifest.json`
- Create: `tests/fixtures/minimal-valid-v2/independent_audit.json`

- [ ] **Step 1: Write failing stale-audit tests**

```python
def test_modified_theorem_invalidates_v3(self):
    project = make_valid_project(claim_profile="THEORY", validity_level="V3")
    append_text(project / "manuscript.md", "A material theorem change.\n")
    result = run_validator(project)
    self.assertEqual(result.returncode, 1)
    self.assertIn("STALE_AUDIT", result.stdout)

def test_audit_of_different_bundle_fails(self):
    project = make_valid_project(claim_profile="MIXED", validity_level="V4")
    audit = load_json(project / "independent_audit.json")
    audit["audited_bundle_sha256"] = "0" * 64
    write_json(project / "independent_audit.json", audit)
    result = run_validator(project)
    self.assertIn("AUDIT_BUNDLE_MISMATCH", result.stdout)
```

Run `python3 -m unittest tests.test_audit_invalidation -v`; observe RED.

- [ ] **Step 2: Implement canonical bundle hashing**

Recompute each manifest file hash, then compute the bundle hash from canonical JSON sorted by path:

```python
def bundle_sha256(entries: list[dict]) -> str:
    normalized = [
        {"path": item["path"], "role": item["role"], "sha256": item["sha256"]}
        for item in sorted(entries, key=lambda value: value["path"])
    ]
    raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
```

Reject missing, unsafe, duplicate or mismatched entries. State, manifest and independent audit must agree on epoch and bundle hash.

- [ ] **Step 3: Implement provenance checks**

At V3/V4 require non-empty author IDs, reviewer ID, reviewer thread ID, PASS verdict and exact bundle hash. Reject any author/reviewer overlap with `AUDITOR_NOT_INDEPENDENT`.

- [ ] **Step 4: Run audit tests**

```bash
python3 -m unittest tests.test_audit_invalidation -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/validate_artifact_hashes.py scripts/validate_audit_provenance.py tests/test_audit_invalidation.py tests/fixtures/minimal-valid-v2
git commit -m "feat: invalidate stale and self-authored audits"
```

---

### Task 7: Harden frontier completeness and evidence semantics

**Files:**
- Create: `scripts/validate_frontier_integrity.py`
- Create: `tests/test_frontier_integrity.py`
- Modify: `scripts/validate_evidence_chain.py`
- Modify: `scripts/validate_literature_registry.py`
- Create: `tests/fixtures/minimal-valid-v2/frontier_coverage.json`

- [ ] **Step 1: Write failing downgrade, E2 and coverage tests**

```python
def test_critical_downgrade_requires_fulltext_and_independent_review(self):
    project = make_valid_project()
    registry = load_json(project / "near_neighbor_registry.json")
    registry["records"][0]["importance_history"] = [
        {"importance": "CRITICAL", "at": "2026-08-01", "reason": "direct neighbor"},
        {"importance": "CONTEXT", "at": "2026-08-02", "reason": "full text blocked"},
    ]
    write_json(project / "near_neighbor_registry.json", registry)
    result = run_script("validate_frontier_integrity.py", project)
    self.assertIn("UNJUSTIFIED_IMPORTANCE_DOWNGRADE", result.stdout)

def test_abstract_cannot_support_e2(self):
    project = make_valid_project()
    claims = load_json(project / "literature_claim_registry.json")
    claims["records"][0]["evidence_level"] = "E2"
    claims["records"][0]["source_artifact_kind"] = "OFFICIAL_ABSTRACT"
    write_json(project / "literature_claim_registry.json", claims)
    result = run_script("validate_frontier_integrity.py", project)
    self.assertIn("E2_REQUIRES_FULLTEXT", result.stdout)

def test_missing_author_continuation_axis_blocks_frontier(self):
    project = make_valid_project()
    coverage = load_json(project / "frontier_coverage.json")
    del coverage["axes"]["author_continuations"]
    write_json(project / "frontier_coverage.json", coverage)
    result = run_script("validate_frontier_integrity.py", project)
    self.assertIn("FRONTIER_AXIS_MISSING", result.stdout)
```

Run the module and observe RED.

- [ ] **Step 2: Implement append-only importance checks**

Current importance must equal the last history event. Any downward transition from CRITICAL/IMPORTANT to CONTEXT requires a reclassification record with fulltext artifact ID, E2/E4 evidence, independent reviewer ID/thread and audited artifact hash. `DOWNLOAD_BLOCKED` can never justify a downgrade.

- [ ] **Step 3: Implement evidence-kind semantics**

Recognize `OFFICIAL_METADATA`, `OFFICIAL_ABSTRACT`, `FULL_ARTICLE_HTML`, `FULL_ARTICLE_PDF`, `PROOF_OR_APPENDIX`. E2 requires full article; E4 requires proof/appendix or an explicit fulltext locator covering the proof machine.

- [ ] **Step 4: Implement coverage axes**

Require method synonyms, target tasks, theory terms, algorithm structures, author continuations, backward citations, forward citations and at least two independent routes. Missing capability is BLOCKED only when recorded with a concrete unavailable capability; simply omitting an axis is INVALID.

- [ ] **Step 5: Run frontier and legacy evidence tests**

```bash
python3 -m unittest tests.test_frontier_integrity -v
python3 -m unittest discover -s tests -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/validate_frontier_integrity.py scripts/validate_evidence_chain.py scripts/validate_literature_registry.py tests/test_frontier_integrity.py tests/fixtures/minimal-valid-v2
git commit -m "feat: prevent frontier and evidence gate downgrades"
```

---

### Task 8: Integrate readiness routing and computation locks

**Files:**
- Modify: `scripts/validate_all.py`
- Modify: `scripts/validate_workflow_state.py`
- Modify: `tests/test_schema_v2.py`
- Modify: `tests/test_audit_invalidation.py`

- [ ] **Step 1: Add failing compute/final-lock routing tests**

```python
def test_compute_requires_n04c_and_v3(self):
    project = make_valid_project(validity_level="V2", novelty_level="N0-4C")
    state = load_json(project / "workflow_state.json")
    state["active_state"] = "COMPUTE"
    write_json(project / "workflow_state.json", state)
    result = run_validator(project)
    self.assertIn("COMPUTE_REQUIRES_V3", result.stdout)

def test_final_lock_requires_v4(self):
    project = make_valid_project(validity_level="V3", novelty_level="N0-4C")
    state = load_json(project / "workflow_state.json")
    state["active_state"] = "FINAL_LOCK"
    write_json(project / "workflow_state.json", state)
    result = run_validator(project)
    self.assertIn("FINAL_LOCK_REQUIRES_V4", result.stdout)
```

Run the two modules and observe RED.

- [ ] **Step 2: Implement complete state prerequisites**

Add the approved states and enforce:

```text
CLAIM_FREEZE requires N0-4C
VALIDITY_AUDIT requires V1
INDEPENDENT_REVIEW requires V2
DIRECTION_LOCK requires N0-4C and V3
COMPUTE requires N0-4C, V3 and compute_authorized
POSTCOMPUTE_CLAIM_FREEZE requires completed authorized compute evidence
FINAL_VALIDITY_AUDIT requires new epoch claim bundle
FINAL_LOCK requires N0-4C, V4 and current independent audit
```

At BLOCKED, validate every existing artifact and return exit 2 for declared external blockers; never print a READY suite merely because later checks are skipped.

- [ ] **Step 3: Run complete deterministic suite**

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests PASS with no warnings or tracebacks.

- [ ] **Step 4: Commit**

```bash
git add scripts/validate_all.py scripts/validate_workflow_state.py tests
git commit -m "feat: enforce novelty and validity readiness locks"
```

---

### Task 9: Update the skill contract and templates

**Files:**
- Modify: `SKILL.md`
- Modify: `templates.md`
- Modify: `reference.md`
- Modify: `evidence-pipeline.md`
- Modify: `compute-funnel.md`
- Modify: `case-lessons.md`

- [ ] **Step 1: Add a failing documentation contract test**

Create `tests/test_skill_contract.py`:

```python
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SkillContractTests(unittest.TestCase):
    def test_main_skill_exposes_schema_v2_hard_gates(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for required in (
            "schema_version = 2.0",
            "N0-4C",
            "V3",
            "V4",
            "BLOCKED_CAPABILITY",
            "MIGRATION_REQUIRED",
            "reviewer_agent_id",
        ):
            self.assertIn(required, text)

    def test_description_is_trigger_only(self):
        frontmatter = (ROOT / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[1]
        self.assertIn("description: Use when", frontmatter)
```

Run `python3 -m unittest tests.test_skill_contract -v`; observe RED.

- [ ] **Step 2: Rewrite the frontmatter trigger**

Use this trigger-only description:

```yaml
description: >-
  Use when defining, auditing, revising, computing, or preparing to submit
  innovation propositions for dissertations or journal articles, especially
  when recent-literature coverage, dangerous near neighbors, theorem
  correctness, algorithm/protocol fidelity, evidence traceability, or research
  claim readiness must be adjudicated.
```

- [ ] **Step 3: Update `SKILL.md` as the mandatory router**

Replace Schema 1.x lock language with Schema 2.0, N0-4C and V0–V4. Add the form router, different-agent requirement, material-change invalidation, four exit codes, compute/final-lock formulas and migration stop rule. Link directly to supporting resources for detailed schemas. Keep the file under 500 lines and avoid repeating template fields.

- [ ] **Step 4: Update supporting resources**

- `templates.md`: add complete JSON/Markdown templates for every new artifact.
- `reference.md`: make G9 proof audit and protocol/code audit binding components of V2–V4.
- `evidence-pipeline.md`: add artifact-kind semantics, importance history and downgrade contract.
- `compute-funnel.md`: replace old N0-4 compute prerequisite with N0-4C+V3 and require post-compute V4 before final claims.
- `case-lessons.md`: add general lessons on testing the exact claim, nonzero nuisance cases, empirical-to-theorem promotion and stale audits; do not mention hospital data or paper-specific identifiers.

- [ ] **Step 5: Run documentation and all tests**

```bash
python3 -m unittest tests.test_skill_contract -v
python3 -m unittest discover -s tests -v
wc -l SKILL.md
```

Expected: all tests PASS and `SKILL.md` has at most 500 lines.

- [ ] **Step 6: Commit**

```bash
git add SKILL.md templates.md reference.md evidence-pipeline.md compute-funnel.md case-lessons.md tests/test_skill_contract.py
git commit -m "docs: make claim validity a mandatory skill gate"
```

---

### Task 10: Validate migration and the anonymous paper-1 regression fixture

**Files:**
- Modify: `tests/fixtures/paper1-failure-case/*`
- Modify: `tests/fixtures/minimal-valid-v2/*`
- Modify: `tests/test_migration.py`
- Create: `tests/test_paper1_regression.py`

- [ ] **Step 1: Write the end-to-end regression test**

```python
def test_anonymous_failure_case_is_not_ready(self):
    fixture = ROOT / "tests/fixtures/paper1-failure-case"
    migrated = migrate_fixture_to_temp(fixture)
    result = run_validator(migrated)
    self.assertNotEqual(result.returncode, 0)
    for code in (
        "UNREGISTERED_HIGH_RISK_CLAIM",
        "MISSING_WITNESS_NONZERO_NUISANCE",
        "ONLINE_CHRONOLOGY_UNVERIFIED",
        "UNJUSTIFIED_IMPORTANCE_DOWNGRADE",
        "E2_REQUIRES_FULLTEXT",
        "STALE_AUDIT",
    ):
        self.assertIn(code, result.stdout)
```

Run it and verify RED if any expected trap is not yet surfaced.

- [ ] **Step 2: Make the minimal integration fixes**

Only adjust dispatch, fixture metadata or issue aggregation needed to expose all six independently. Do not teach validators the paper-specific formulas; formula correctness remains the theory-obligation and independent-agent responsibility.

- [ ] **Step 3: Test migration safety**

Verify default migration leaves the source unchanged, in-place migration creates a byte-identical backup, validity resets to V0, compute authorization is false, and the migrated project cannot proceed until its new artifacts exist.

- [ ] **Step 4: Run complete suite**

```bash
python3 -m unittest discover -s tests -v
git diff --check
```

Expected: all tests PASS and no diff errors.

- [ ] **Step 5: Commit**

```bash
git add tests
git commit -m "test: lock paper claim-integrity regressions"
```

---

### Task 11: Forward-test with an independent agent and close rationalization gaps

**Files:**
- Create: `tests/pressure/schema-v2-forward.json`
- Modify as needed: `SKILL.md`, supporting resources, validators and tests

- [ ] **Step 1: Dispatch a fresh independent forward-test agent**

Use the same raw prompt as Task 1, now pointing at the revised branch. Do not provide baseline misses, expected issue codes, the design document or the implementation plan. Record agent and thread IDs.

- [ ] **Step 2: Compare behavior against acceptance criteria**

The agent must identify the incorrect theorem strength, threshold boundary, fixed-regularization rank claim, block-versus-sample protocol, importance downgrade, abstract/E2 mismatch and stale audit. It must refuse lock/compute, produce a valid rollback or blocker and give one next action.

- [ ] **Step 3: If the agent finds a loophole, add a new RED test first**

Add a minimal unit or pressure test reproducing the rationalization, run it to observe failure, make the smallest validator or skill wording change, and rerun the full suite. Repeat until the pressure test passes without answer leakage.

- [ ] **Step 4: Record the GREEN result**

Write `tests/pressure/schema-v2-forward.json` with prompt, provenance, audited bundle hash, findings, verdict and a comparison to acceptance criteria. Do not store hidden chain-of-thought; store only observable output and issue coverage.

- [ ] **Step 5: Validate the skill package**

Run:

```bash
python3 -m unittest discover -s tests -v
python3 /Users/robinlaw/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
python3 scripts/validate_all.py --root tests/fixtures/minimal-valid-v2 --state tests/fixtures/minimal-valid-v2/workflow_state.json
git diff --check
git status --short --branch
```

Expected:

```text
all unittests PASS
skill validation PASS
minimal-valid-v2 exit 0 READY
git diff --check produces no output
only intentional forward-test/refactor files are modified before final commit
```

- [ ] **Step 6: Commit final forward-test hardening**

```bash
git add SKILL.md scripts tests templates.md reference.md evidence-pipeline.md compute-funnel.md case-lessons.md
git commit -m "test: verify schema v2 with independent agents"
```

- [ ] **Step 7: Final repository verification**

```bash
git status --short --branch
git log --oneline --decorate -12
```

Expected: clean `schema-v2-claim-integrity` branch with separate design, RED, Schema 2.0, claim, theory, protocol, audit, frontier, documentation, regression and forward-test commits.
