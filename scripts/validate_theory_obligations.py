#!/usr/bin/env python3
"""Validate exact theorem obligations and falsification witness evidence."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from validation_common import (
    Issue,
    UnsafePathError,
    canonical_relative_path,
    choose_exit,
    lexical_relative_cli_path,
    nonempty_string,
    open_root_fd,
    positive_integer,
    read_json_object_at,
    read_regular_file_at,
    render,
    string_list,
)


THEORY_PROFILES = {"THEORY", "MIXED"}
THEOREM_CLAIM_TYPES = {"THEOREM", "LEMMA", "COROLLARY"}
REQUIRED_WITNESSES = {
    "MINIMAL_POSITIVE",
    "NONZERO_NUISANCE",
    "BOUNDARY_OR_LIMIT",
    "PREMISE_REMOVAL",
}
PASS_WITNESSES = {
    "MINIMAL_POSITIVE",
    "NONZERO_NUISANCE",
    "BOUNDARY_OR_LIMIT",
    "RANDOM_PROPERTY",
}
ALLOWED_WITNESSES = REQUIRED_WITNESSES | {"RANDOM_PROPERTY"}
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


def statement_sha256(statement: str) -> str:
    return hashlib.sha256(statement.encode("utf-8")).hexdigest()


def canonical_identifier(value: Any) -> bool:
    return nonempty_string(value) and value.strip() == value


def missing_issue(code: str, item_id: str, field: str) -> Issue:
    return Issue(code, "INVALID", item_id, f"missing_or_empty:{field}")


def load_required_json(
    root_fd: int, relative_path: str, label: str
) -> tuple[dict[str, Any] | None, list[Issue]]:
    try:
        snapshot = read_regular_file_at(root_fd, relative_path, include_data=True)
    except FileNotFoundError:
        return None, []
    except UnsafePathError as error:
        return None, [Issue("VALIDATOR_ERROR", "INVALID", label, str(error))]
    except OSError as error:
        return None, [
            Issue("VALIDATOR_ERROR", "INVALID", label, type(error).__name__)
        ]
    assert snapshot.data is not None
    try:
        payload = json.loads(snapshot.data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeError) as error:
        code = (
            "INVALID_THEORY_REGISTRY_JSON"
            if label == "theory_obligation_registry"
            else "INVALID_CLAIM_INVENTORY_JSON"
        )
        return None, [Issue(code, "INVALID", label, type(error).__name__)]
    if not isinstance(payload, dict):
        code = (
            "INVALID_THEORY_REGISTRY"
            if label == "theory_obligation_registry"
            else "INVALID_CLAIM_INVENTORY"
        )
        return None, [Issue(code, "INVALID", label, "top_level_not_object")]
    return payload, []


def collect_theorem_claims(
    inventory: dict[str, Any], state_epoch: Any
) -> tuple[dict[str, dict[str, Any]], list[Issue]]:
    issues: list[Issue] = []
    if inventory.get("schema_version") != "2.0":
        issues.append(
            Issue(
                "INVALID_CLAIM_INVENTORY",
                "INVALID",
                "claim_inventory",
                f"schema_version:{inventory.get('schema_version')}",
            )
        )
    inventory_epoch = inventory.get("validation_epoch")
    if not positive_integer(inventory_epoch):
        issues.append(
            Issue(
                "INVALID_CLAIM_INVENTORY",
                "INVALID",
                "claim_inventory",
                "validation_epoch:expected_positive_integer",
            )
        )
    elif positive_integer(state_epoch) and inventory_epoch != state_epoch:
        issues.append(
            Issue(
                "THEOREM_STATEMENT_STALE",
                "INVALID",
                "claim_inventory",
                f"inventory_epoch:{inventory_epoch};state_epoch:{state_epoch}",
            )
        )

    raw_claims = inventory.get("claims")
    if not isinstance(raw_claims, list):
        issues.append(
            Issue(
                "INVALID_CLAIM_INVENTORY",
                "INVALID",
                "claim_inventory",
                "claims:expected_list",
            )
        )
        return {}, issues

    theorem_claims: dict[str, dict[str, Any]] = {}
    theorem_ids: list[str] = []
    for index, claim in enumerate(raw_claims):
        if not isinstance(claim, dict):
            issues.append(
                Issue(
                    "INVALID_CLAIM_INVENTORY",
                    "INVALID",
                    f"claim[{index}]",
                    "expected_object",
                )
            )
            continue
        claim_type = claim.get("claim_type")
        if not nonempty_string(claim_type):
            issues.append(
                Issue(
                    "INVALID_CLAIM_INVENTORY",
                    "INVALID",
                    f"claim[{index}]",
                    "claim_type:expected_nonempty_string",
                )
            )
            continue
        if claim_type not in THEOREM_CLAIM_TYPES:
            continue
        claim_id = claim.get("claim_id")
        statement = claim.get("statement")
        claim_epoch = claim.get("validation_epoch")
        item_id = claim_id if nonempty_string(claim_id) else f"claim[{index}]"
        if not nonempty_string(claim_id):
            issues.append(
                Issue(
                    "INVALID_CLAIM_INVENTORY",
                    "INVALID",
                    item_id,
                    "claim_id:expected_nonempty_string",
                )
            )
            continue
        theorem_ids.append(claim_id)
        if not nonempty_string(statement):
            issues.append(
                Issue(
                    "INVALID_CLAIM_INVENTORY",
                    "INVALID",
                    item_id,
                    "statement:expected_nonempty_string",
                )
            )
        if not positive_integer(claim_epoch):
            issues.append(
                Issue(
                    "INVALID_CLAIM_INVENTORY",
                    "INVALID",
                    item_id,
                    "validation_epoch:expected_positive_integer",
                )
            )
        elif positive_integer(state_epoch) and claim_epoch != state_epoch:
            issues.append(
                Issue(
                    "THEOREM_STATEMENT_STALE",
                    "INVALID",
                    item_id,
                    f"claim_epoch:{claim_epoch};state_epoch:{state_epoch}",
                )
            )
        theorem_claims.setdefault(claim_id, claim)

    for claim_id, count in Counter(theorem_ids).items():
        if count > 1:
            issues.append(
                Issue(
                    "DUPLICATE_CLAIM_ID",
                    "INVALID",
                    claim_id,
                    f"count:{count}",
                )
            )
    return theorem_claims, issues


def validate_random_property_na(
    obligation: dict[str, Any], state: dict[str, Any], item_id: str
) -> list[Issue]:
    issues: list[Issue] = []
    random_property = obligation.get("random_property")
    if not isinstance(random_property, dict):
        return [
            Issue(
                "MISSING_WITNESS_RANDOM_PROPERTY",
                "INVALID",
                item_id,
                "provide_witness_or_audited_not_applicable_reason",
            )
        ]
    if random_property.get("status") != "NOT_APPLICABLE":
        issues.append(
            Issue(
                "INVALID_RANDOM_PROPERTY_NA",
                "INVALID",
                item_id,
                f"status:{random_property.get('status')}",
            )
        )
    if not nonempty_string(random_property.get("mathematical_reason")):
        issues.append(
            Issue(
                "RANDOM_PROPERTY_NA_REASON_REQUIRED",
                "INVALID",
                item_id,
                "mathematical_reason:expected_nonempty_string",
            )
        )

    acceptance = random_property.get("independent_audit_acceptance")
    state_audit = state.get("independent_audit")
    accepted = isinstance(acceptance, dict) and acceptance.get("accepted") is True
    acceptance_reviewer = (
        acceptance.get("reviewer_agent_id") if isinstance(acceptance, dict) else None
    )
    state_reviewer = (
        state_audit.get("reviewer_agent_id") if isinstance(state_audit, dict) else None
    )
    state_authors = (
        state_audit.get("author_agent_ids") if isinstance(state_audit, dict) else None
    )
    valid_authors = (
        isinstance(state_authors, list)
        and bool(state_authors)
        and all(canonical_identifier(author) for author in state_authors)
        and len(set(state_authors)) == len(state_authors)
    )
    author_ids = state_authors if valid_authors else []
    if not valid_authors:
        issues.append(
            Issue(
                "INVALID_RANDOM_PROPERTY_AUDIT_AUTHORS",
                "INVALID",
                item_id,
                "author_agent_ids:expected_nonempty_unique_canonical_string_list",
            )
        )
    valid_reviewer = (
        canonical_identifier(state_reviewer)
        and canonical_identifier(acceptance_reviewer)
        and state_reviewer == acceptance_reviewer
        and valid_authors
        and state_reviewer not in author_ids
    )
    if not valid_reviewer:
        issues.append(
            Issue(
                "INVALID_RANDOM_PROPERTY_AUDIT_REVIEWER",
                "INVALID",
                item_id,
                "reviewer_must_be_canonical_matching_and_independent",
            )
        )
    audit_accepts = (
        accepted
        and valid_reviewer
        and isinstance(state_audit, dict)
        and state_audit.get("capability_available") is True
        and state_audit.get("verdict") == "PASS"
    )
    if not audit_accepts:
        issues.append(
            Issue(
                "RANDOM_PROPERTY_NA_NOT_AUDIT_ACCEPTED",
                "INVALID",
                item_id,
                "requires_explicit_acceptance_by_current_independent_reviewer",
            )
        )
    return issues


def validate_witnesses(
    root_fd: int,
    obligation: dict[str, Any],
    state: dict[str, Any],
    item_id: str,
) -> list[Issue]:
    issues: list[Issue] = []
    raw_witnesses = obligation.get("witnesses")
    if not isinstance(raw_witnesses, list):
        return [
            Issue(
                "INVALID_OBLIGATION_FIELD",
                "INVALID",
                item_id,
                "witnesses:expected_list",
            )
        ]

    kinds: list[str] = []
    output_paths: defaultdict[str, list[str]] = defaultdict(list)
    output_identities: defaultdict[tuple[int, int], list[str]] = defaultdict(list)
    for index, witness in enumerate(raw_witnesses):
        witness_id = f"{item_id}:witness[{index}]"
        if not isinstance(witness, dict):
            issues.append(
                Issue(
                    "INVALID_WITNESS_FIELD",
                    "INVALID",
                    witness_id,
                    "expected_object",
                )
            )
            continue
        kind = witness.get("kind")
        if "kind" not in witness:
            issues.append(missing_issue("MISSING_WITNESS_KIND", witness_id, "kind"))
        elif not nonempty_string(kind) or kind not in ALLOWED_WITNESSES:
            issues.append(
                Issue(
                    "INVALID_WITNESS_KIND",
                    "INVALID",
                    witness_id,
                    f"kind:{kind}",
                )
            )
        else:
            kinds.append(kind)
            witness_id = f"{item_id}:{kind}"

        for field, code in (
            ("command", "MISSING_WITNESS_COMMAND"),
            ("exit_code", "MISSING_WITNESS_EXIT_CODE"),
            ("output_file", "MISSING_WITNESS_OUTPUT_FILE"),
            ("output_sha256", "MISSING_WITNESS_OUTPUT_SHA256"),
        ):
            if field not in witness:
                issues.append(missing_issue(code, witness_id, field))

        for field in ("expected", "observed"):
            value = witness.get(field)
            if field not in witness:
                issues.append(
                    missing_issue(f"MISSING_WITNESS_{field.upper()}", witness_id, field)
                )
            elif not isinstance(value, str) or value not in {"PASS", "FAIL"}:
                issues.append(
                    Issue(
                        "INVALID_WITNESS_FIELD",
                        "INVALID",
                        witness_id,
                        f"{field}:expected_PASS_or_FAIL",
                    )
                )
        if "command" in witness and not nonempty_string(witness.get("command")):
            issues.append(
                Issue(
                    "INVALID_WITNESS_FIELD",
                    "INVALID",
                    witness_id,
                    "command:expected_nonempty_string",
                )
            )
        exit_code = witness.get("exit_code")
        if "exit_code" in witness and (
            isinstance(exit_code, bool) or not isinstance(exit_code, int) or exit_code < 0
        ):
            issues.append(
                Issue(
                    "INVALID_WITNESS_FIELD",
                    "INVALID",
                    witness_id,
                    "exit_code:expected_nonnegative_integer",
                )
            )

        if kind == "PREMISE_REMOVAL" and (
            witness.get("expected") != "FAIL"
            or witness.get("observed") != "FAIL"
            or isinstance(exit_code, bool)
            or not isinstance(exit_code, int)
            or exit_code == 0
        ):
            issues.append(
                Issue(
                    "EXPECTED_FAILURE_DID_NOT_FAIL",
                    "INVALID",
                    witness_id,
                    "requires_expected_FAIL_observed_FAIL_and_nonzero_exit",
                )
            )
        elif isinstance(kind, str) and kind in PASS_WITNESSES and (
            witness.get("expected") != "PASS"
            or witness.get("observed") != "PASS"
            or isinstance(exit_code, bool)
            or exit_code != 0
        ):
            issues.append(
                Issue(
                    "WITNESS_CONTRACT_MISMATCH",
                    "INVALID",
                    witness_id,
                    "requires_expected_PASS_observed_PASS_and_zero_exit",
                )
            )

        output_path = witness.get("output_file")
        output_hash = witness.get("output_sha256")
        if "output_file" in witness and not canonical_relative_path(output_path):
            issues.append(
                Issue(
                    "UNSAFE_WITNESS_OUTPUT",
                    "INVALID",
                    witness_id,
                    "path_must_be_canonical_and_relative",
                )
            )
            continue
        if "output_sha256" in witness and (
            not isinstance(output_hash, str)
            or SHA256_PATTERN.fullmatch(output_hash) is None
        ):
            issues.append(
                Issue(
                    "INVALID_WITNESS_FIELD",
                    "INVALID",
                    witness_id,
                    "output_sha256:expected_lowercase_sha256",
                )
            )
        if not canonical_relative_path(output_path):
            continue
        output_paths[output_path].append(witness_id)
        try:
            snapshot = read_regular_file_at(root_fd, output_path)
        except FileNotFoundError:
            issues.append(
                Issue(
                    "MISSING_WITNESS_OUTPUT",
                    "INVALID",
                    witness_id,
                    output_path,
                )
            )
        except UnsafePathError as error:
            issues.append(
                Issue(
                    "UNSAFE_WITNESS_OUTPUT",
                    "INVALID",
                    witness_id,
                    str(error),
                )
            )
        except OSError as error:
            issues.append(
                Issue(
                    "UNREADABLE_WITNESS_OUTPUT",
                    "INVALID",
                    witness_id,
                    type(error).__name__,
                )
            )
        else:
            output_identities[snapshot.identity].append(witness_id)
            if isinstance(output_hash, str) and SHA256_PATTERN.fullmatch(output_hash):
                if snapshot.sha256 != output_hash:
                    issues.append(
                        Issue(
                            "WITNESS_OUTPUT_HASH_MISMATCH",
                            "INVALID",
                            witness_id,
                            f"declared:{output_hash};current:{snapshot.sha256}",
                        )
                    )

    for kind, count in Counter(kinds).items():
        if count > 1:
            issues.append(
                Issue(
                    "DUPLICATE_WITNESS_KIND",
                    "INVALID",
                    item_id,
                    f"kind:{kind};count:{count}",
                )
            )
    for kind in sorted(REQUIRED_WITNESSES - set(kinds)):
        issues.append(
            Issue(
                f"MISSING_WITNESS_{kind}",
                "INVALID",
                item_id,
                "required_witness_kind",
            )
        )

    if "RANDOM_PROPERTY" not in kinds:
        issues.extend(validate_random_property_na(obligation, state, item_id))
    elif "random_property" in obligation:
        issues.append(
            Issue(
                "RANDOM_PROPERTY_NA_WITH_WITNESS",
                "INVALID",
                item_id,
                "choose_witness_or_not_applicable_not_both",
            )
        )

    for path, owners in output_paths.items():
        if len(owners) > 1:
            issues.append(
                Issue(
                    "DUPLICATE_WITNESS_OUTPUT",
                    "INVALID",
                    item_id,
                    f"path:{path};owners:{','.join(owners)}",
                )
            )
    for owners in output_identities.values():
        if len(owners) > 1 and len({owner.rsplit(":", 1)[-1] for owner in owners}) > 1:
            issues.append(
                Issue(
                    "DUPLICATE_WITNESS_OUTPUT",
                    "INVALID",
                    item_id,
                    f"same_file_identity:{','.join(owners)}",
                )
            )
    return issues


def validate(
    root_fd: int,
    state: dict[str, Any],
    inventory: dict[str, Any],
    registry: dict[str, Any],
) -> list[Issue]:
    issues: list[Issue] = []
    state_epoch = state.get("validation_epoch")
    if not positive_integer(state_epoch):
        issues.append(
            Issue(
                "INVALID_STATE_VALIDATION_EPOCH",
                "INVALID",
                "workflow_state",
                f"validation_epoch:{state_epoch}",
            )
        )
    theorem_claims, claim_issues = collect_theorem_claims(inventory, state_epoch)
    issues.extend(claim_issues)

    if registry.get("schema_version") != "2.0":
        issues.append(
            Issue(
                "INVALID_THEORY_REGISTRY_FIELD",
                "INVALID",
                "theory_obligation_registry",
                f"schema_version:{registry.get('schema_version')}",
            )
        )
    registry_epoch = registry.get("validation_epoch")
    if not positive_integer(registry_epoch):
        issues.append(
            Issue(
                "INVALID_THEORY_REGISTRY_FIELD",
                "INVALID",
                "theory_obligation_registry",
                "validation_epoch:expected_positive_integer",
            )
        )
    elif positive_integer(state_epoch) and registry_epoch != state_epoch:
        issues.append(
            Issue(
                "THEOREM_STATEMENT_STALE",
                "INVALID",
                "theory_obligation_registry",
                f"registry_epoch:{registry_epoch};state_epoch:{state_epoch}",
            )
        )

    raw_obligations = registry.get("obligations")
    if not isinstance(raw_obligations, list):
        issues.append(
            Issue(
                "INVALID_THEORY_REGISTRY_FIELD",
                "INVALID",
                "theory_obligation_registry",
                "obligations:expected_list",
            )
        )
        return issues

    obligation_ids: list[str] = []
    for index, obligation in enumerate(raw_obligations):
        item_id = f"obligation[{index}]"
        if not isinstance(obligation, dict):
            issues.append(
                Issue(
                    "INVALID_OBLIGATION_FIELD",
                    "INVALID",
                    item_id,
                    "expected_object",
                )
            )
            continue
        claim_id = obligation.get("claim_id")
        if nonempty_string(claim_id):
            item_id = claim_id
            obligation_ids.append(claim_id)
        else:
            issues.append(
                Issue(
                    (
                        "MISSING_OBLIGATION_CLAIM_ID"
                        if "claim_id" not in obligation
                        else "INVALID_OBLIGATION_FIELD"
                    ),
                    "INVALID",
                    item_id,
                    "claim_id:expected_nonempty_string",
                )
            )

        for field, code in (
            ("exact_statement", "MISSING_EXACT_STATEMENT"),
            ("premises", "MISSING_PREMISES"),
            ("quantifiers", "MISSING_QUANTIFIERS"),
            ("proof_locator", "MISSING_PROOF_LOCATOR"),
        ):
            if field not in obligation:
                issues.append(missing_issue(code, item_id, field))

        if "exact_statement" in obligation and not nonempty_string(
            obligation.get("exact_statement")
        ):
            issues.append(
                Issue(
                    "INVALID_OBLIGATION_FIELD",
                    "INVALID",
                    item_id,
                    "exact_statement:expected_nonempty_string",
                )
            )
        for field in ("premises", "quantifiers"):
            if field in obligation and not string_list(obligation.get(field)):
                issues.append(
                    Issue(
                        "INVALID_OBLIGATION_FIELD",
                        "INVALID",
                        item_id,
                        f"{field}:expected_nonempty_string_list",
                    )
                )
        if "proof_locator" in obligation and not nonempty_string(
            obligation.get("proof_locator")
        ):
            issues.append(
                Issue(
                    "INVALID_OBLIGATION_FIELD",
                    "INVALID",
                    item_id,
                    "proof_locator:expected_nonempty_string",
                )
            )
        obligation_hash = obligation.get("exact_statement_sha256")
        if "exact_statement_sha256" not in obligation:
            issues.append(
                missing_issue(
                    "MISSING_EXACT_STATEMENT_SHA256",
                    item_id,
                    "exact_statement_sha256",
                )
            )
        if not isinstance(obligation_hash, str) or SHA256_PATTERN.fullmatch(
            obligation_hash
        ) is None:
            issues.append(
                Issue(
                    "INVALID_OBLIGATION_FIELD",
                    "INVALID",
                    item_id,
                    "exact_statement_sha256:expected_lowercase_sha256",
                )
            )
        obligation_epoch = obligation.get("validation_epoch")
        if "validation_epoch" not in obligation:
            issues.append(
                missing_issue(
                    "MISSING_OBLIGATION_VALIDATION_EPOCH",
                    item_id,
                    "validation_epoch",
                )
            )
        if not positive_integer(obligation_epoch):
            issues.append(
                Issue(
                    "INVALID_OBLIGATION_FIELD",
                    "INVALID",
                    item_id,
                    "validation_epoch:expected_positive_integer",
                )
            )

        claim = theorem_claims.get(claim_id) if nonempty_string(claim_id) else None
        stale = claim is None
        if claim is not None:
            claim_statement = claim.get("statement")
            claim_epoch = claim.get("validation_epoch")
            expected_hash = (
                statement_sha256(claim_statement)
                if isinstance(claim_statement, str)
                else None
            )
            stale = (
                obligation.get("exact_statement") != claim_statement
                or obligation_hash != expected_hash
                or obligation_epoch != claim_epoch
                or claim_epoch != state_epoch
            )
        if stale:
            issues.append(
                Issue(
                    "THEOREM_STATEMENT_STALE",
                    "INVALID",
                    item_id,
                    "claim_id_exact_statement_hash_or_epoch_mismatch",
                )
            )
        if nonempty_string(claim_id) and claim_id not in theorem_claims:
            issues.append(
                Issue(
                    "ORPHAN_THEORY_OBLIGATION",
                    "INVALID",
                    claim_id,
                    "claim_not_found_or_not_theorem_lemma_corollary",
                )
            )
        issues.extend(validate_witnesses(root_fd, obligation, state, item_id))

    counts = Counter(obligation_ids)
    for claim_id, count in counts.items():
        if count > 1:
            issues.append(
                Issue(
                    "DUPLICATE_THEORY_OBLIGATION",
                    "INVALID",
                    claim_id,
                    f"count:{count}",
                )
            )
    for claim_id in sorted(theorem_claims):
        if counts.get(claim_id, 0) == 0:
            issues.append(
                Issue(
                    "MISSING_THEORY_OBLIGATION",
                    "INVALID",
                    claim_id,
                    "theorem_lemma_or_corollary_requires_exactly_one_obligation",
                )
            )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root_fd: int | None = None
    try:
        root_fd = open_root_fd(args.root)
        state_relative = lexical_relative_cli_path(args.root, args.state, "state")
        inventory_path = args.inventory or (args.root / "claim_inventory.json")
        registry_path = args.registry or (args.root / "theory_obligation_registry.json")
        inventory_relative = lexical_relative_cli_path(
            args.root, inventory_path, "inventory"
        )
        registry_relative = lexical_relative_cli_path(
            args.root, registry_path, "registry"
        )
        state = read_json_object_at(root_fd, state_relative, "workflow_state")
        profile = state.get("claim_profile")
        if not isinstance(profile, str) or profile not in {
            "THEORY",
            "MIXED",
            "ALGORITHM",
        }:
            issues = [
                Issue(
                    "INVALID_CLAIM_PROFILE",
                    "INVALID",
                    "workflow_state",
                    f"claim_profile:{profile}",
                )
            ]
        else:
            registry, registry_issues = load_required_json(
                root_fd, registry_relative, "theory_obligation_registry"
            )
            if registry is None and not registry_issues:
                issues = (
                    [
                        Issue(
                            "THEORY_OBLIGATION_REGISTRY_REQUIRED",
                            "INVALID",
                            "theory_obligation_registry",
                            registry_relative,
                        )
                    ]
                    if profile in THEORY_PROFILES
                    else []
                )
            elif registry is None:
                issues = registry_issues
            else:
                inventory, inventory_issues = load_required_json(
                    root_fd, inventory_relative, "claim_inventory"
                )
                if inventory is None and not inventory_issues:
                    issues = [
                        Issue(
                            "CLAIM_INVENTORY_REQUIRED",
                            "INVALID",
                            "claim_inventory",
                            inventory_relative,
                        )
                    ]
                elif inventory is None:
                    issues = inventory_issues
                else:
                    issues = registry_issues + inventory_issues + validate(
                        root_fd, state, inventory, registry
                    )
    except Exception as error:
        issues = [
            Issue(
                "VALIDATOR_ERROR",
                "INVALID",
                "theory_obligation_registry",
                str(error),
            )
        ]
    finally:
        if root_fd is not None:
            os.close(root_fd)

    print(render("theory_obligations", issues, args.json))
    return int(choose_exit(issues))


if __name__ == "__main__":
    raise SystemExit(main())
