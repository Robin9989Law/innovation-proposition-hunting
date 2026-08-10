# Collision Springboard Gate Design

**Date:** 2026-08-10  
**Status:** Approved for implementation
**Scope:** `innovation-proposition-hunting` Schema 2.x novelty contract

## 1. Problem

The skill already advises agents to up-drill a covering result instead of escaping to a smaller
scenario. That discipline is not executable. `reference.md` still permits narrowing after the
six up-drill questions are exhausted, and no required artifact or validator prevents an agent
from changing the dataset, population, assumptions, interface, quantifier or conclusion and then
presenting the smaller remainder as innovation.

A material collision must become a springboard into the shared support of the candidate and its
strongest collider. The only valid terminal outcomes are a deeper candidate derived from an
unclosed responsibility inside that shared support, or a documented exhaustion closure. Scope
narrowing is never an outcome.

## 2. Decision

Add a mandatory `collision_springboard.json` and a deterministic
`validate_collision_springboard.py`. Every active `(collision_round, active_contribution)` pair at
`SYNTHESIZE_COLLISION` or later must have exactly one current candidate record. This uses fields
that already exist in `workflow_state.json`; it does not invent an unbound “active candidate”
state field. The record either establishes that no material collision exists or records every
material collider and completes the springboard gate.

For a material collision, the legal outcomes are:

- `DEEPER_CANDIDATE`: at least one verified shared-support opening produces a new candidate;
- `SPRINGBOARD_EXHAUSTED_CLOSE`: all required support-search axes are exhausted and the covered
  candidate is closed.

There is no `NARROWED`, `REBOUNDARY_AND_CONTINUE`, `SCENARIO_SHIFT`, `WEAKEN_AND_CONTINUE` or
equivalent outcome. A narrower remainder cannot inherit novelty from the covered candidate.

## 3. What counts as a material collision

Each current candidate comparison declares one of:

- `NO_MATERIAL_COLLISION`;
- `DIRECT_OCCUPATION`;
- `MECHANICAL_DERIVATION`;
- `SUBSTANTIAL_OVERLAP`.

The last three are material collisions. They require at least one canonical collider registry ID,
E2 evidence for an empirical or algorithmic coverage decision, E4 evidence where the decision
depends on a theorem, proof machine, reduction or equivalence, and registered literature claim
IDs that carry the collision reasoning.

The validator can enforce completeness, canonical IDs, evidence links, hashes and enumerations.
Whether `NO_MATERIAL_COLLISION` is scientifically honest remains a semantic judgment and must be
reviewed in the current independent bundle before V3/V4.

## 4. Required shared-support search

Every material collision must search these six axes exactly once and in canonical order:

1. `OBJECT_OR_REPRESENTATION`: shared object, representation or state space;
2. `ASSUMPTION_OR_IDENTIFICATION`: shared assumption, information boundary or identification
   condition;
3. `MECHANISM_OR_PROOF_ENGINE`: shared mechanism, reduction, invariant, lemma or proof step;
4. `IMAGE_OR_MAXIMAL_REACH`: image, attainable set or maximal reach of the collider;
5. `INVERSE_OR_FAILURE`: converse, inverse construction, obstruction or failure mechanism;
6. `BOUNDARY_OR_STOPPING`: equality, limit, degeneracy, protection boundary or reason the
   collider stops.

Each axis records:

- `axis` and `status`;
- the exact question asked;
- candidate-side dependency;
- collider-side dependency;
- registered evidence claim IDs and locators;
- reasoning that distinguishes source facts from the agent's inference;
- zero or more `support_point_ids`.

Allowed axis statuses are:

- `NO_SHARED_SUPPORT`: evidence shows that this axis does not connect the two claims;
- `SHARED_SUPPORT_CLOSED`: a shared support exists, but its relevant responsibility is already
  closed;
- `OPENING_FOUND`: the shared support contains a precise unclosed responsibility.

Blank reasoning, an abstract-level locator, an unregistered source, or the phrase “not studied”
without an internal structural responsibility does not complete an axis.

## 5. Shared support points

A support point is not a topic shared by two papers. It is a specific dependency needed by both
the covered candidate and the collider, such as the same representation map, identifiability
condition, proof invariant, update mechanism, attainable set, converse obstruction or boundary
case.

Each `support_points` entry contains:

```json
{
  "support_point_id": "SP-0001",
  "kind": "MECHANISM_OR_PROOF_ENGINE",
  "statement": "<exact shared dependency>",
  "candidate_dependency": "<how the covered candidate depends on it>",
  "collider_dependency": "<how the collider depends on it>",
  "unclosed_responsibility": "<precise internal responsibility or empty when closed>",
  "evidence_claim_ids": ["LC-0001"],
  "status": "OPENING_FOUND"
}
```

IDs are canonical and unique. Evidence references must resolve to current, registered claims and
their E2/E4 locators. An `OPENING_FOUND` support point requires a non-empty unclosed
responsibility; a closed support point requires a non-empty closure reason.

## 6. Deeper-candidate continuity and the no-narrowing rule

`DEEPER_CANDIDATE` requires a `derived_candidate` that:

- cites one or more `OPENING_FOUND` support points;
- states one exact `K → U → Δ` in which `U` is internal to the shared support;
- remains in the same research chain and contribution;
- matches the current immutable innovation route, form and route generation;
- provides before/after O/I/A/T/C/R/B alignment;
- classifies every alignment change as `UNCHANGED` or `DEEPENED_AT_SUPPORT`;
- supplies an independent-audit explanation for every `DEEPENED_AT_SUPPORT` field.

The following are always narrowing and therefore invalid:

- changing only the dataset, population, domain label, interface or task name;
- adding a convenient assumption or constraint merely to leave the collider's coverage;
- weakening a universal or exact claim to an unprincipled subset;
- changing the denominator, metric or baseline without an internal shared-support reason;
- dropping a difficult outcome, quantifier or failure case;
- calling the remainder a new collision round, contribution or `MIXED` profile without a
  user-confirmed route restart.

If any alignment field is declared `NARROWED`, or the record selects a narrowing outcome, the
validator emits `COLLISION_NARROWING_FORBIDDEN`. Determining whether prose falsely labels a
narrowing move as `DEEPENED_AT_SUPPORT` is a mandatory semantic responsibility of the independent
reviewer. The springboard artifact is therefore included in the audited bundle and any change to
it invalidates the audit through the existing hash/epoch rules.

## 7. Exhaustion closure

`SPRINGBOARD_EXHAUSTED_CLOSE` is permitted only when:

- all six axes are present and none has `OPENING_FOUND`;
- every `NO_SHARED_SUPPORT` or `SHARED_SUPPORT_CLOSED` result has current E2/E4 evidence and
  non-empty reasoning;
- every discovered support point is explicitly closed;
- the record gives a precise closure statement and explains why no internal responsibility
  remains;
- the candidate is marked closed and is not reused under a narrower statement in the same route
  generation.

Exhaustion closure does not authorize a smaller substitute. A later attempt to reuse the covered
claim with a narrower scope is a new `COLLISION_NARROWING_FORBIDDEN` finding. A genuinely different
primary path requires the separate, explicit, user-confirmed innovation-route restart.

## 8. Artifact shape

`collision_springboard.json` is append-preserving by collision round:

```json
{
  "schema_version": "2.0",
  "records": [
    {
      "collision_round": 1,
      "active_contribution": "M",
      "candidate_claim_id": "C-0001",
      "comparison_status": "DIRECT_OCCUPATION",
      "collider_registry_ids": ["W-0001"],
      "collision_evidence_claim_ids": ["LC-0001"],
      "comparison_reasoning": "<source facts separated from the coverage inference>",
      "narrowing_prohibited": true,
      "support_searches": ["<six complete axis records>"],
      "support_points": ["<zero or more support-point records>"],
      "outcome": "DEEPER_CANDIDATE",
      "derived_candidate": "<required only for DEEPER_CANDIDATE>",
      "closure": "<required only for SPRINGBOARD_EXHAUSTED_CLOSE>"
    }
  ]
}
```

The pair `(collision_round, active_contribution)` is unique. Previous round records remain
present. The state’s current pair must resolve to exactly one record before leaving
`SYNTHESIZE_COLLISION`. The record-local candidate ID is later bound by output and claim artifacts;
it is not silently inferred from prose. A `NO_MATERIAL_COLLISION` record still requires the
comparison set, collision evidence and reasoning, but has no springboard outcome.

The complete strict field schema belongs in `templates.md`; this design fixes its semantics.

## 9. State and validator integration

`validate_collision_springboard.py` uses the existing strict JSON decoder and trusted root-relative
file reading. It is read-only, rejects duplicate keys, non-scalar Unicode, symlinks, FIFOs,
out-of-root paths, malformed types, duplicate IDs, orphan evidence references and stale round or
candidate bindings.

`validate_all.py` invokes it whenever:

- `active_state` is `SYNTHESIZE_COLLISION` or later and the current round comparison is due;
- `collision_springboard.json` already exists; or
- novelty is claimed at N0-4C or any validity/compute/final state is requested.

The artifact is mandatory for leaving `SYNTHESIZE_COLLISION`. N0-4C, `CLAIM_FREEZE`, COMPUTE and
FINAL_LOCK all require a current passing springboard gate. Existing artifacts are still validated
under external capability blocking; local invalidity outranks `BLOCKED`.

The only state transitions are:

- `NO_MATERIAL_COLLISION` → `OUTPUT_CLAIM_BIND` for the same round and candidate;
- `DEEPER_CANDIDATE` → increment `collision_round`, preserve the route/form and contribution,
  return to `PRIOR_CLAIM_DRAIN`, and use the derived candidate as the next round's lineage source;
- `SPRINGBOARD_EXHAUSTED_CLOSE` → close the candidate and return to `LAYER_DECISION`; no successor
  may inherit a narrower remainder.

A material collision never transitions directly to `OUTPUT_CLAIM_BIND`.

## 10. Stable findings

The validator and aggregate suite use these stable findings:

- `COLLISION_SPRINGBOARD_REQUIRED`: the current collision round lacks a complete record;
- `COLLISION_NARROWING_FORBIDDEN`: a narrowing action, alignment classification or outcome is
  present;
- `COMMON_SUPPORT_UNVERIFIED`: the six-axis search, support point or evidence binding is invalid;
- `SPRINGBOARD_EXHAUSTION_UNPROVEN`: closure is requested without complete, evidence-backed
  exhaustion.

All four are `INVALID` and return exit code 1. They are not capability blocks and cannot be
downgraded to warnings.

## 11. Skill and documentation behavior

The main skill, `reference.md`, `case-lessons.md`, `templates.md`, README and tutorial must say:

- a collision is a springboard, not permission to shrink the problem;
- the agent must search shared structural support before proposing a successor;
- “the collider did not study X” is not a shared support point;
- narrowing remains forbidden even after all six axes are exhausted;
- exhaustion permits closure only;
- every handoff reports the collision round, springboard outcome, support point IDs and sole next
  action.

Existing statements that permit “close or narrow” after up-drill exhaustion must be removed.

## 12. Testing and acceptance

Tests must demonstrate:

1. A current material collision without `collision_springboard.json` is invalid.
2. Missing, duplicate or reordered support axes are invalid.
3. Abstract-only evidence, orphan claims and stale locators are invalid.
4. Dataset, population, scenario, interface, assumption, quantifier, outcome, metric and baseline
   narrowing attacks emit `COLLISION_NARROWING_FORBIDDEN`.
5. Renaming a narrowed candidate, incrementing the collision round or using `MIXED` does not
   bypass the gate.
6. A current shared support point plus an internally derived, route-compatible candidate passes.
7. An opening that changes the locked innovation form fails unless the result stays supporting
   or the user performs the separate explicit route restart.
8. Exhaustion closure passes only when all six axes are current, evidence-backed and contain no
   unresolved opening.
9. Exhaustion followed by a narrower substitute is invalid.
10. `NO_MATERIAL_COLLISION` requires current comparison evidence and independent audit coverage.
11. Missing files, invalid JSON, duplicate keys, nonregular files, symlinks, path escape, stale
    hashes and read-only behavior follow existing safety contracts.
12. The minimal Schema 2 fixture remains READY after adding a valid no-material-collision record.
13. The full skill suite and package validation remain green.

No paper-specific regression, manuscript analysis or rerun of paper1 is part of this change.
