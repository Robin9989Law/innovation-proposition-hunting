> **状态：已归档（2026-08-11）**。本文件是 Schema 2.0 实施前的设计/计划档案，内容可能已过时；现行规范以 SKILL.md、templates.md 与 scripts/ 校验器为准。

# Innovation Proposition Hunting Schema v2: Claim Integrity Design

Date: 2026-08-10
Status: Approved design; implementation not started
Branch: `schema-v2-claim-integrity`

## 1. Objective

Upgrade `innovation-proposition-hunting` from a literature-traceability workflow into a dual-axis research gate that separately establishes:

1. novelty readiness: whether a contribution is unoccupied and non-mechanical; and
2. validity readiness: whether its theorem, algorithm, protocol and empirical claims are correct and audited.

The upgrade is intentionally breaking. Schema 1.x projects must migrate to Schema 2.0 before any research-state action can continue. A migration never inherits a prior `N0-4 LOCKED`, evidence-validity claim or compute authorization as trusted validity evidence.

## 2. Accepted constraints

- Use mandatory Schema 2.0; do not provide a legacy execution mode.
- Require an independent reviewer agent for V3 and V4. The reviewer agent must differ from every authoring agent for the audited claim bundle.
- If independent-agent capability is unavailable, fail closed with `BLOCKED_CAPABILITY`.
- Keep novelty and validity as orthogonal axes.
- Permit computation only after novelty candidate approval and pre-compute validity review.
- Permit final lock or submission only after post-compute validity review and artifact-hash freeze.
- Preserve detailed procedures in supporting resources and validators; keep `SKILL.md` focused on mandatory routing and stop rules.
- Develop all changes with failing tests first and forward-test the revised skill with fresh agents that receive raw artifacts rather than the expected diagnoses.

## 3. Architecture

### 3.1 Dual readiness axes

Novelty remains an N0 classification, but the highest pre-validity level is renamed `N0-4C`, meaning “novelty candidate,” not “locked contribution.”

```text
NOVELTY
K -> U -> Delta -> N0_AUDIT -> N0-1 | N0-2 | N0-3 | N0-4C

VALIDITY
V0 UNINVENTORIED
 -> V1 CLAIMS_FROZEN
 -> V2 INTERNAL_FALSIFICATION_PASS
 -> V3 INDEPENDENT_PRECOMPUTE_AUDIT_PASS
 -> V4 POSTCOMPUTE_AUDIT_AND_HASH_FREEZE
```

Authorization conditions:

```text
compute_ready = N0-4C AND V3 AND compute_authorized
submission_ready = N0-4C AND V4 AND independent_audit_current
```

An N0 result never implies mathematical correctness, protocol fidelity or empirical confirmation.

### 3.2 Single execution state

The project records both readiness axes but permits actions on only one active track at a time.

```text
N0_AUDIT
 -> CLAIM_FREEZE
 -> VALIDITY_AUDIT
 -> INDEPENDENT_REVIEW
 -> DIRECTION_LOCK
 -> COMPUTE
 -> POSTCOMPUTE_CLAIM_FREEZE
 -> FINAL_VALIDITY_AUDIT
 -> FINAL_LOCK
```

`active_track` is one of `NOVELTY`, `VALIDITY` or `COMPUTE`. State prerequisites determine which track may advance. Material changes invalidate completed validity stages instead of silently reusing an older audit.

### 3.3 Form-sensitive routing

`claim_profile` is one of `THEORY`, `ALGORITHM` or `MIXED`.

- `THEORY` requires a claim inventory, theory-obligation registry, internal falsification evidence, independent proof audit and hash manifest.
- `ALGORITHM` requires a claim inventory, protocol contract, claim-code trace, baseline-budget contract, executable chronology/fairness tests, independent reproduction audit and hash manifest.
- `MIXED` requires both paths.

The state machine must not require irrelevant algorithm fields for a pure theorem contribution or omit theorem gates for a mixed paper.

## 4. Schema 2.0

The authoritative state contains at least:

```json
{
  "schema_version": "2.0",
  "active_track": "NOVELTY | VALIDITY | COMPUTE",
  "novelty_level": "N0-1 | N0-2 | N0-3 | N0-4C",
  "validity_level": "V0 | V1 | V2 | V3 | V4",
  "claim_profile": "THEORY | ALGORITHM | MIXED",
  "validation_epoch": 1,
  "claim_bundle_sha256": "sha256",
  "independent_audit": {
    "author_agent_ids": ["author-agent-id"],
    "reviewer_agent_id": "reviewer-agent-id",
    "reviewer_thread_id": "reviewer-thread-id",
    "audited_bundle_sha256": "sha256",
    "verdict": "PASS | FAIL | BLOCKED"
  }
}
```

The complete template must retain output-type, contribution-contract, layer, collision-round, search, artifact and decision-log fields needed by the existing workflow while replacing ambiguous lock fields with explicit novelty and validity readiness.

### 4.1 Audit independence

- `reviewer_agent_id` must not occur in `author_agent_ids`.
- The reviewer must audit the exact `claim_bundle_sha256` recorded in the state.
- The audit artifact must record the reviewer thread, inputs, verdict, findings and timestamp.
- A same-agent new session is not an acceptable substitute.
- Missing independent-agent capability yields `BLOCKED_CAPABILITY`, not a self-audit waiver.

### 4.2 Epoch and hash invalidation

A material change to any frozen theorem, claim wording, pseudocode, protocol, implementation, baseline contract, experiment result or conclusion must:

1. increment `validation_epoch`;
2. recompute the claim-bundle manifest;
3. invalidate V3 and V4;
4. retain the old audit only as history; and
5. return to the earliest affected validity state.

Adding or strengthening high-risk language such as `exact`, `universal`, `provably`, `guaranteed`, `bounded`, `necessary`, `sufficient`, `for any`, `lossless`, `online`, `strong baseline`, `interpolation`, `first` or `zero regret` is a material claim change.

Rhetorical instructions such as “positive-results mainline” have no authority to change validity levels.

## 5. Required artifacts

### 5.1 Common artifacts

#### `claim_inventory.json`

Register every substantive manuscript claim with a stable ID, exact wording, location, claim type, evidence responsibility, risk vocabulary and current validity status. A scanner compares theorem environments and high-risk terms in manuscript sources against this inventory.

#### `audit_manifest.json`

Record every audited path, SHA-256, artifact role, validation epoch, generating command and output hash. Validators recompute hashes rather than trusting declared values.

#### `independent_audit.json`

Record author-agent identities, reviewer-agent identity, reviewer thread, exact audited bundle hash, findings, verdict and blocking conditions.

#### `frontier_coverage.json`

Record the recent-window search coverage across method names and synonyms, target tasks, theory terms, algorithm structures, author continuations, backward citations, forward citations and at least two independent discovery/verification routes.

### 5.2 Theory artifacts

#### `theory_obligation_registry.json`

Each theorem, lemma and corollary records:

- exact statement;
- premises and quantifiers;
- proof locator;
- minimal positive witness;
- minimal counterexample search;
- non-zero nuisance or baseline case;
- equality, limit and degenerate boundary cases;
- a premise-removal case expected to fail;
- randomized small-instance property test when applicable;
- commands, outputs and hashes; and
- independent reviewer verdict.

Tests must exercise the published statement itself, not a nearby identity or weaker consequence.

### 5.3 Algorithm artifacts

#### `protocol_contract.json`

Freeze prediction unit, update unit, predict/update order, label availability, time order, split strategy, hyperparameter-selection data, development data, sealed confirmation data, test-access count and update semantics.

#### `claim_code_trace.json`

Map each algorithmic manuscript claim to the manuscript location, pseudocode symbol, implementation symbol, source-file hash and executable test. Source symbols and hashes are authoritative; unstable line numbers are explanatory only.

#### `baseline_budget.json`

Freeze parameter count or width, feature budget, initialization count, regularization search space, tuning data, label access, update frequency, compute budget and stopping rules for every “strong,” “fair” or “same-budget” comparison.

## 6. Validators

Add the following deterministic validators:

```text
validate_schema_v2.py
validate_claim_inventory.py
validate_theory_obligations.py
validate_protocol_contract.py
validate_claim_code_trace.py
validate_frontier_integrity.py
validate_audit_provenance.py
validate_artifact_hashes.py
```

`validate_all.py` dispatches validators based on the active state and `claim_profile`. State determines which artifacts are required; it does not suppress contradictions in artifacts that already exist.

### 6.1 Exit semantics

```text
0 READY
1 INVALID
2 BLOCKED
3 MIGRATION_REQUIRED
```

- `INVALID`: internal contradiction, stale audit, false evidence level, author self-review or malformed artifact.
- `BLOCKED`: unavailable critical full text, independent-agent capability or sealed data.
- `MIGRATION_REQUIRED`: Schema 1.x detected.
- `READY`: every gate required at the current state genuinely passes.

Machine-readable results include a stable code, severity, artifact/claim ID and detail. Required codes include:

```text
BLOCKED_CAPABILITY
BLOCKED_FULLTEXT
STALE_AUDIT
CLAIM_PROMOTION_UNAUDITED
MIGRATION_REQUIRED
VALIDATOR_ERROR
```

Validators are read-only. They must never mutate research state to make their own run pass.

### 6.2 Frontier integrity

- A work maintains append-only `importance_history`.
- Downgrading `CRITICAL` or `IMPORTANT` requires full-text evidence and an independent reviewer audit.
- If full text is unavailable, importance cannot be downgraded to escape the full-text gate.
- Evidence distinguishes official metadata, official abstract, full article HTML, full PDF and proof/appendix.
- `VERIFIED_OFFICIAL_HTML` does not by itself imply E2; the archived content and locator must support the registered claim.
- Recent-frontier completeness requires every coverage axis, not merely a non-empty query list.

## 7. Migration

Add `migrate_v1_to_v2.py`.

- Default behavior writes a new state file and leaves the original unchanged.
- `--in-place` first creates a timestamped backup.
- Structural fields may be transformed, but validity cannot be inferred.
- Every migrated project starts at `validity_level=V0` and `active_state=CLAIM_FREEZE`.
- A prior `N0-4 LOCKED` becomes an unverified novelty candidate pending a new N0 and validity adjudication.
- Prior `evidence_validated` and `compute_authorized` values do not confer V1–V4 status.

## 8. Test strategy

### 8.1 RED baseline

Before editing production skill files or validators, run a fresh agent against the current skill and a raw minimal paper package containing known but undisclosed traps:

- a correct residual-change identity paired with an incorrect absolute LOO identity;
- a threshold `ceil`/`floor` error;
- full rank at fixed positive regularization with degrees of freedom below sample count;
- block prediction code described as per-sample online prediction;
- a critical neighbor silently downgraded to context;
- abstract-only evidence labeled E2; and
- a theorem changed after the recorded audit hash.

Record what the agent misses and its exact rationalizations. This is the required failing skill test.

### 8.2 Deterministic regression tests

Use Python standard-library `unittest`. Tests cover at least:

1. Schema 1.x returns `MIGRATION_REQUIRED`.
2. Reviewer and author agent identity overlap fails.
3. A changed audited artifact invalidates V3/V4.
4. An unregistered high-risk claim fails.
5. An F1 obligation without a non-zero nuisance case fails.
6. An F1 obligation without a premise-removal expected failure fails.
7. A per-sample online claim without an executable predict/update chronology test fails.
8. A critical downgrade without full text and independent audit fails.
9. Metadata or abstract evidence cannot satisfy E2.
10. A missing recent-frontier coverage axis fails.
11. A V3 project with changed theorem or algorithm artifacts cannot enter compute.
12. A post-compute high-risk claim addition prevents final lock.

Test layout:

```text
tests/
  test_schema_v2.py
  test_claim_integrity.py
  test_theory_obligations.py
  test_protocol_contract.py
  test_frontier_integrity.py
  test_audit_invalidation.py
  fixtures/
    minimal-valid-v2/
    paper1-failure-case/
```

The paper-1 fixture contains only anonymous minimal matrices, pseudocode and JSON. It excludes hospital source data and the full manuscript.

### 8.3 GREEN and forward testing

After deterministic tests pass, run another fresh agent with the revised skill and the same raw package. Do not provide the diagnosis or expected findings. Success requires the agent to:

- find every priority-zero trap;
- refuse empirical-to-theorem promotion without a new audit;
- prevent importance downgrading from bypassing full-text requirements;
- return the correct blocked or rollback state; and
- emit one exact next action.

If the forward test exposes a new rationalization, add a failing test, make the minimal rule or validator change and rerun the complete suite.

## 9. Implementation sequence

Work on branch `schema-v2-claim-integrity` in small reviewable commits:

1. Add the RED deterministic fixtures and current-skill pressure test.
2. Implement Schema 2.0 and exit semantics.
3. Implement claim inventory and high-risk claim scanning.
4. Implement theory obligations and falsification gates.
5. Implement protocol, claim-code and baseline-budget gates.
6. Implement independent audit provenance and hash invalidation.
7. Implement frontier reclassification, evidence-level and coverage integrity.
8. Implement migration and update templates.
9. Update `SKILL.md`, `reference.md`, `evidence-pipeline.md`, `compute-funnel.md` and `case-lessons.md` without duplicating detailed schemas.
10. Run deterministic tests, the anonymous paper-1 fixture and fresh-agent forward tests.
11. Refactor only while tests remain green.
12. Run skill validation, repository diff checks and final verification.

## 10. Error handling and safety

- Treat unavailable external evidence or review capability as blocking, not invalid science.
- Treat malformed or contradictory local state as invalid.
- Treat validator crashes separately from project verdicts.
- Preserve historical audits, but never let them authorize a different artifact bundle.
- Never auto-relabel literature, invent evidence, infer reviewer independence or repair a manuscript claim inside a validator.
- Preserve source data and use anonymous minimal fixtures.
- Make migration recoverable and explicit.

## 11. Acceptance criteria

The upgrade is complete only when:

- every new deterministic test was observed failing before its implementation;
- all tests pass with pristine output;
- Schema 1.x is rejected until explicit migration;
- N0-4C cannot enter compute without V3;
- final lock cannot occur without V4;
- author self-review cannot satisfy the independent audit gate;
- material claim or artifact changes invalidate the relevant audit;
- the anonymous paper-1 fixture triggers the intended theory, protocol, frontier and evidence failures;
- a fresh independent agent using the revised skill identifies all priority-zero traps without leaked answers;
- `SKILL.md` remains a concise mandatory router rather than duplicating supporting references; and
- the repository is clean and the final commit history preserves the staged implementation.
