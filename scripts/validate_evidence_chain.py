#!/usr/bin/env python3
"""Validate literature identity, archived full text, atomic claims, and output traceability."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


IMPORTANCE = {"CRITICAL", "IMPORTANT", "CONTEXT"}
ARCHIVED = {"FULLTEXT_ARCHIVED", "OFFICIAL_HTML_ARCHIVED"}
SEARCH_PHASES = {"RECENT_FRONTIER_PASS", "FOUNDATIONAL_BACKFILL"}
CLAIM_TYPES = {
    "VIEWPOINT",
    "CONCLUSION",
    "METHOD",
    "ASSUMPTION",
    "LIMITATION",
    "COUNTEREXAMPLE",
}
EVIDENCE_LEVELS = {"E0", "E1", "E2", "E3", "E4"}
VERIFIED_CLAIM_STATUSES = {"VERIFIED_FULLTEXT", "VERIFIED_OFFICIAL_HTML"}
SUPPORT_ROLES = {"SUPPORTS", "CONTRADICTS", "QUALIFIES", "METHOD_FOR"}
USE_STATUSES = {"UNUSED", "USED", "EXCLUDED_WITH_REASON"}
OUTPUT_KINDS = {
    "FACT",
    "SYNTHESIS",
    "METHOD_COMPARISON",
    "NOVELTY_VERDICT",
    "CLOSURE",
    "PROPOSITION_RATIONALE",
}
INFERENCE_TYPES = {"DIRECT", "SYNTHESIS", "CONTRAST", "INFERENCE"}


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: top level must be an object")
    return payload


def records(payload: dict[str, Any], field: str = "records") -> list[dict[str, Any]]:
    value = payload.get(field)
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    if not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{field} entries must be objects")
    return value


def nonempty(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value)
    return value is not None


def valid_http_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parts = urlsplit(value.strip())
    return parts.scheme in {"http", "https"} and bool(parts.netloc)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_local_path(root: Path, raw_path: str) -> Path | None:
    if not raw_path:
        return None
    candidate = (root / raw_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def add(errors: list[str], code: str, item_id: str, detail: str) -> None:
    errors.append(f"{code}\t{item_id}\t{detail}")


def validate(
    root: Path,
    literature: dict[str, Any],
    claims: dict[str, Any],
    outputs: dict[str, Any],
    current_year: int,
) -> list[str]:
    errors: list[str] = []
    works = records(literature)
    claim_records = records(claims)
    output_records = records(outputs, "output_claims")

    window = literature.get("recent_window")
    if not isinstance(window, dict):
        add(errors, "RECENT_WINDOW", "__registry__", "missing_recent_window")
        window = {}
    expected_start = current_year - 2
    if literature.get("current_year") != current_year:
        add(
            errors,
            "RECENT_WINDOW",
            "__registry__",
            f"current_year:{literature.get('current_year')};expected:{current_year}",
        )
    if window.get("start_year") != expected_start or window.get("end_year") != current_year:
        add(
            errors,
            "RECENT_WINDOW",
            "__registry__",
            f"window:{window.get('start_year')}-{window.get('end_year')};expected:{expected_start}-{current_year}",
        )
    if window.get("status") != "COMPLETE":
        add(errors, "RECENT_WINDOW", "__registry__", "status_not_complete")
    if not nonempty(window.get("completed_at")):
        add(errors, "RECENT_WINDOW", "__registry__", "missing_completed_at")
    if not nonempty(window.get("queries")):
        add(errors, "RECENT_WINDOW", "__registry__", "missing_queries")

    rounds = {
        literature.get("current_collision_round"),
        claims.get("current_collision_round"),
        outputs.get("current_collision_round"),
    }
    if len(rounds) != 1 or not all(isinstance(value, int) and value >= 1 for value in rounds):
        add(errors, "ROUND", "__registry__", f"inconsistent_rounds:{sorted(map(str, rounds))}")
        current_round = 1
    else:
        current_round = next(iter(rounds))

    work_by_id: dict[str, dict[str, Any]] = {}
    for work in works:
        work_id = work.get("registry_id")
        if not nonempty(work_id):
            add(errors, "WORK", "<missing>", "missing_registry_id")
            continue
        if work_id in work_by_id:
            add(errors, "WORK", str(work_id), "duplicate_registry_id")
            continue
        work_by_id[str(work_id)] = work
        for field in ("canonical_title", "authors", "year", "identity_verification_url", "identity_verified_at"):
            if not nonempty(work.get(field)):
                add(errors, "IDENTITY", str(work_id), f"missing:{field}")
        if not isinstance(work.get("canonical_title"), str):
            add(errors, "IDENTITY", str(work_id), "canonical_title_not_string")
        authors = work.get("authors")
        if not isinstance(authors, list) or not authors or not all(nonempty(author) for author in authors):
            add(errors, "IDENTITY", str(work_id), "authors_not_nonempty_list")
        if work.get("identity_status") != "VERIFIED":
            add(errors, "IDENTITY", str(work_id), f"status:{work.get('identity_status')}")
        if not valid_http_url(work.get("identity_verification_url")):
            add(errors, "IDENTITY", str(work_id), "invalid_identity_verification_url")
        year = work.get("year")
        if not isinstance(year, int) or year > current_year:
            add(errors, "WORK", str(work_id), f"invalid_year:{year}")
        phase = work.get("search_phase")
        if phase not in SEARCH_PHASES:
            add(errors, "WORK", str(work_id), f"invalid_search_phase:{phase}")
        elif isinstance(year, int):
            expected_phase = (
                "RECENT_FRONTIER_PASS"
                if expected_start <= year <= current_year
                else "FOUNDATIONAL_BACKFILL"
            )
            if phase != expected_phase:
                add(errors, "WORK", str(work_id), f"search_phase:{phase};expected:{expected_phase}")
        importance = work.get("importance")
        if importance not in IMPORTANCE:
            add(errors, "WORK", str(work_id), f"invalid_importance:{importance}")
        download = work.get("download")
        if not isinstance(download, dict):
            add(errors, "DOWNLOAD", str(work_id), "missing_download_object")
            download = {}
        if importance in {"CRITICAL", "IMPORTANT"}:
            status = download.get("status")
            if status not in ARCHIVED:
                add(errors, "DOWNLOAD", str(work_id), f"important_not_archived:{status}")
            if not valid_http_url(download.get("source_url")):
                add(errors, "DOWNLOAD", str(work_id), "invalid_or_missing_source_url")
            if not nonempty(download.get("downloaded_at")):
                add(errors, "DOWNLOAD", str(work_id), "missing_downloaded_at")
            if download.get("verified_against_metadata") is not True:
                add(errors, "DOWNLOAD", str(work_id), "metadata_match_not_verified")
            path = safe_local_path(root, str(download.get("local_path") or ""))
            if path is None:
                add(errors, "DOWNLOAD", str(work_id), "invalid_or_missing_local_path")
            elif not path.is_file():
                add(errors, "DOWNLOAD", str(work_id), f"file_not_found:{path}")
            else:
                declared_hash = str(download.get("sha256") or "").lower()
                actual_hash = sha256(path)
                if declared_hash != actual_hash:
                    add(errors, "DOWNLOAD", str(work_id), "sha256_mismatch")
            if work.get("claim_extraction_status") != "COMPLETE":
                add(errors, "CLAIM_EXTRACTION", str(work_id), "important_claims_not_complete")

    claim_by_id: dict[str, dict[str, Any]] = {}
    claims_by_work: dict[str, list[str]] = {}
    for claim in claim_records:
        claim_id = claim.get("claim_id")
        if not nonempty(claim_id):
            add(errors, "CLAIM", "<missing>", "missing_claim_id")
            continue
        claim_id = str(claim_id)
        if claim_id in claim_by_id:
            add(errors, "CLAIM", claim_id, "duplicate_claim_id")
            continue
        claim_by_id[claim_id] = claim
        source_id = str(claim.get("source_registry_id") or "")
        if source_id not in work_by_id:
            add(errors, "CLAIM", claim_id, f"unknown_source:{source_id}")
        else:
            claims_by_work.setdefault(source_id, []).append(claim_id)
        if claim.get("claim_type") not in CLAIM_TYPES:
            add(errors, "CLAIM", claim_id, f"invalid_type:{claim.get('claim_type')}")
        if not nonempty(claim.get("normalized_statement")):
            add(errors, "CLAIM", claim_id, "missing_normalized_statement")
        if not nonempty(claim.get("scope")):
            add(errors, "CLAIM", claim_id, "missing_scope")
        if not isinstance(claim.get("conditions"), list):
            add(errors, "CLAIM", claim_id, "conditions_not_list")
        if claim.get("evidence_level") not in EVIDENCE_LEVELS:
            add(errors, "CLAIM", claim_id, f"invalid_evidence_level:{claim.get('evidence_level')}")
        elif claim.get("evidence_level") not in {"E2", "E3", "E4"}:
            add(errors, "CLAIM", claim_id, f"important_claim_below_E2:{claim.get('evidence_level')}")
        if claim.get("verification_status") not in VERIFIED_CLAIM_STATUSES:
            add(errors, "CLAIM", claim_id, f"not_fulltext_verified:{claim.get('verification_status')}")
        locator = claim.get("locator")
        if not isinstance(locator, dict) or not any(nonempty(value) for value in locator.values()):
            add(errors, "TRACE", claim_id, "missing_locator")
        if claim.get("support_role") not in SUPPORT_ROLES:
            add(errors, "CLAIM", claim_id, f"invalid_support_role:{claim.get('support_role')}")
        if claim.get("importance") not in {"CRITICAL", "IMPORTANT"}:
            add(errors, "CLAIM", claim_id, f"invalid_importance:{claim.get('importance')}")
        discovered_round = claim.get("discovered_round")
        if not isinstance(discovered_round, int) or discovered_round < 1 or discovered_round > current_round:
            add(errors, "ROUND", claim_id, f"invalid_discovered_round:{discovered_round}")
        use_status = claim.get("use_status")
        if use_status not in USE_STATUSES:
            add(errors, "USAGE", claim_id, f"invalid_use_status:{use_status}")
        output_uses = claim.get("used_by_output_claim_ids") or []
        collision_uses = claim.get("used_in_collision_ids") or []
        if not isinstance(output_uses, list):
            add(errors, "USAGE", claim_id, "used_by_output_claim_ids_not_list")
            output_uses = []
        if not isinstance(collision_uses, list):
            add(errors, "USAGE", claim_id, "used_in_collision_ids_not_list")
            collision_uses = []
        if use_status == "USED" and not output_uses and not collision_uses:
            add(errors, "USAGE", claim_id, "used_without_target")
        if use_status == "EXCLUDED_WITH_REASON" and not nonempty(claim.get("exclusion_reason")):
            add(errors, "USAGE", claim_id, "excluded_without_reason")

    for work_id, work in work_by_id.items():
        if work.get("importance") in {"CRITICAL", "IMPORTANT"} and not claims_by_work.get(work_id):
            add(errors, "CLAIM_EXTRACTION", work_id, "important_work_without_claims")

    output_by_id: dict[str, dict[str, Any]] = {}
    referenced_claims: set[str] = set()
    for output in output_records:
        output_id = output.get("output_claim_id")
        if not nonempty(output_id):
            add(errors, "OUTPUT", "<missing>", "missing_output_claim_id")
            continue
        output_id = str(output_id)
        if output_id in output_by_id:
            add(errors, "OUTPUT", output_id, "duplicate_output_claim_id")
            continue
        output_by_id[output_id] = output
        if not nonempty(output.get("statement")):
            add(errors, "OUTPUT", output_id, "missing_statement")
        if not nonempty(output.get("output_location")):
            add(errors, "OUTPUT", output_id, "missing_output_location")
        if output.get("claim_kind") not in OUTPUT_KINDS:
            add(errors, "OUTPUT", output_id, f"invalid_claim_kind:{output.get('claim_kind')}")
        inference_type = output.get("inference_type")
        if inference_type not in INFERENCE_TYPES:
            add(errors, "OUTPUT", output_id, f"invalid_inference_type:{inference_type}")
        if inference_type in {"SYNTHESIS", "CONTRAST", "INFERENCE"} and not nonempty(output.get("reasoning")):
            add(errors, "OUTPUT", output_id, "inference_without_reasoning")
        supporting = output.get("supporting_claim_ids")
        if not isinstance(supporting, list) or not supporting:
            add(errors, "OUTPUT", output_id, "no_supporting_claim_ids")
            supporting = []
        counters = output.get("counter_claim_ids") or []
        if not isinstance(counters, list):
            add(errors, "OUTPUT", output_id, "counter_claim_ids_not_list")
            counters = []
        for claim_id in [*supporting, *counters]:
            if claim_id not in claim_by_id:
                add(errors, "TRACE", output_id, f"unknown_claim:{claim_id}")
                continue
            referenced_claims.add(str(claim_id))
            claim = claim_by_id[str(claim_id)]
            source_id = str(claim.get("source_registry_id") or "")
            work = work_by_id.get(source_id, {})
            if work.get("importance") not in {"CRITICAL", "IMPORTANT"}:
                add(errors, "TRACE", output_id, f"claim_from_nonimportant_work:{claim_id}")
            if claim.get("verification_status") not in VERIFIED_CLAIM_STATUSES:
                add(errors, "TRACE", output_id, f"unverified_claim:{claim_id}")
            if claim_id in supporting and claim.get("support_role") == "CONTRADICTS":
                add(errors, "TRACE", output_id, f"contradictory_claim_used_as_support:{claim_id}")
            if claim_id in counters and claim.get("support_role") not in {"CONTRADICTS", "QUALIFIES"}:
                add(errors, "TRACE", output_id, f"noncounter_claim_used_as_counter:{claim_id}")
            if claim.get("use_status") != "USED":
                add(errors, "USAGE", str(claim_id), f"referenced_but_status:{claim.get('use_status')}")
            if output_id not in (claim.get("used_by_output_claim_ids") or []):
                add(errors, "TRACE", output_id, f"missing_reverse_link:{claim_id}")
        if output.get("trace_status") != "VERIFIED":
            add(errors, "TRACE", output_id, f"trace_status:{output.get('trace_status')}")

    for claim_id, claim in claim_by_id.items():
        for output_id in claim.get("used_by_output_claim_ids") or []:
            if output_id not in output_by_id:
                add(errors, "TRACE", claim_id, f"unknown_output_reverse_link:{output_id}")
            elif claim_id not in (output_by_id[output_id].get("supporting_claim_ids") or []) and claim_id not in (
                output_by_id[output_id].get("counter_claim_ids") or []
            ):
                add(errors, "TRACE", claim_id, f"one_way_output_link:{output_id}")

    unused_prior = sorted(
        claim_id
        for claim_id, claim in claim_by_id.items()
        if isinstance(claim.get("discovered_round"), int)
        and claim["discovered_round"] < current_round
        and claim.get("use_status") == "UNUSED"
    )
    gate = outputs.get("collision_gate")
    if not isinstance(gate, dict):
        add(errors, "COLLISION_GATE", "__output__", "missing_collision_gate")
        gate = {}
    if unused_prior:
        add(errors, "COLLISION_GATE", "__output__", f"unused_prior_claims:{','.join(unused_prior)}")
    expected_drained = not unused_prior
    if gate.get("prior_round_claims_drained") is not expected_drained:
        add(errors, "COLLISION_GATE", "__output__", f"drained_flag_should_be:{expected_drained}")
    declared_unused = sorted(gate.get("unused_prior_claim_ids") or [])
    if declared_unused != unused_prior:
        add(errors, "COLLISION_GATE", "__output__", f"unused_list:{declared_unused};actual:{unused_prior}")
    if not nonempty(gate.get("checked_at")):
        add(errors, "COLLISION_GATE", "__output__", "missing_checked_at")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--literature-registry", type=Path, required=True)
    parser.add_argument("--claim-registry", type=Path, required=True)
    parser.add_argument("--output-support", type=Path, required=True)
    parser.add_argument("--current-year", type=int, default=datetime.now().year)
    args = parser.parse_args()

    root = args.root.resolve()
    errors = validate(
        root,
        load_json(args.literature_registry.resolve()),
        load_json(args.claim_registry.resolve()),
        load_json(args.output_support.resolve()),
        args.current_year,
    )
    print(f"evidence_chain_errors={len(errors)}")
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
