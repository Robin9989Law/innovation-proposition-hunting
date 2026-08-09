#!/usr/bin/env python3
"""Validate that academic URLs in research records map to a literature registry."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


URL_RE = re.compile(r"https?://[^\s<>)\"`\]]+")
ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|html|pdf)/(\d{4}\.\d{4,5})", re.I)
ACADEMIC_HOST_MARKERS = (
    "aclanthology.org",
    "arxiv.org",
    "doi.org",
    "openreview.net",
    "openaccess.thecvf.com",
    "proceedings.mlr.press",
    "papers.neurips.cc",
    "neurips.cc",
    "icml.cc",
    "proceedings.iclr.cc",
    "ojs.aaai.org",
    "ecva.net",
    "ijcai.org",
    "papers.miccai.org",
    "jmlr.org",
    "research.google",
    "github.io",
    "uni-saarland.de",
    "uwaterloo.ca",
    "ohiolink.edu",
    "upv.es",
    "fas.harvard.edu",
    "link.springer.com",
    "dl.acm.org",
    "pmc.ncbi.nlm.nih.gov",
    "ieeexplore.ieee.org",
    "springer.com",
    "sciencedirect.com",
)
PUBLICATION_STATUSES = {
    "PUBLISHED",
    "PUBLISHED_WITH_PREPRINT_ALIAS",
    "ACCEPTED_NOT_PUBLISHED",
    "PREPRINT_ONLY",
    "SUBMISSION_ONLY",
    "FORMAL_NON_PEER_REVIEWED",
    "STATUS_UNVERIFIED",
}
QUALIFIED_PUBLICATION_STATUSES = {
    "PUBLISHED",
    "PUBLISHED_WITH_PREPRINT_ALIAS",
}
PEER_REVIEW_STATUSES = {
    "PEER_REVIEWED_PUBLISHED",
    "PEER_REVIEWED_ACCEPTED_NOT_PUBLISHED",
    "NON_PEER_REVIEWED",
    "PEER_REVIEW_STATUS_UNVERIFIED",
}


def clean_url(url: str) -> str:
    return url.rstrip(".,;:")


def canonical_url_key(url: str) -> str:
    """Normalize common paper aliases without discarding the original URL."""
    cleaned = clean_url(url)
    arxiv = ARXIV_RE.search(cleaned)
    if arxiv:
        return f"arxiv:{arxiv.group(1)}"
    parts = urlsplit(cleaned)
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    query = parts.query
    return urlunsplit(("https", host, path, query, ""))


def is_academic_url(url: str) -> bool:
    host = urlsplit(url).netloc.lower()
    return any(marker in host for marker in ACADEMIC_HOST_MARKERS)


def load_registry(
    path: Path,
) -> tuple[
    set[str],
    dict[str, str],
    list[tuple[str, str, str]],
    list[str],
    list[tuple[str, str]],
]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload["records"] if isinstance(payload, dict) else payload
    keys: set[str] = set()
    owners: dict[str, str] = {}
    conflicts: list[tuple[str, str, str]] = []
    duplicate_ids: list[str] = []
    publication_errors: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
    for record in records:
        record_id = record.get("registry_id") or record.get("id")
        if record_id in seen_ids:
            duplicate_ids.append(record_id)
        seen_ids.add(record_id)
        publication_status = record.get("publication_status")
        eligibility = record.get("terminal_rejection_eligibility")
        verification_url = record.get("publication_verification_url")
        peer_review_status = record.get("peer_review_status")
        peer_review_verification_url = record.get("peer_review_verification_url")
        if publication_status not in PUBLICATION_STATUSES:
            publication_errors.append(
                (record_id, f"invalid_or_missing_status:{publication_status}")
            )
        expected_eligibility = (
            "QUALIFIED"
            if publication_status in QUALIFIED_PUBLICATION_STATUSES
            else "NOT_QUALIFIED"
        )
        if eligibility != expected_eligibility:
            publication_errors.append(
                (
                    record_id,
                    f"eligibility:{eligibility};expected:{expected_eligibility}",
                )
            )
        if expected_eligibility == "QUALIFIED" and not verification_url:
            publication_errors.append(
                (record_id, "qualified_without_publication_verification_url")
            )
        if peer_review_status not in PEER_REVIEW_STATUSES:
            publication_errors.append(
                (
                    record_id,
                    f"invalid_or_missing_peer_review_status:{peer_review_status}",
                )
            )
        if (
            peer_review_status == "PEER_REVIEWED_PUBLISHED"
            and not peer_review_verification_url
        ):
            publication_errors.append(
                (record_id, "peer_reviewed_published_without_verification_url")
            )
        urls = [
            record.get("canonical_url") or record.get("url"),
            *(record.get("alternate_urls") or []),
        ]
        for url in filter(None, urls):
            key = canonical_url_key(url)
            if key in owners and owners[key] != record_id:
                conflicts.append((key, owners[key], record_id))
            keys.add(key)
            owners[key] = record_id
    return keys, owners, conflicts, duplicate_ids, publication_errors


def scan(
    root: Path, ignored: set[Path]
) -> tuple[list[dict[str, object]], list[str]]:
    rows: list[dict[str, object]] = []
    path_errors: list[str] = []
    for path in sorted(root.rglob("*")):
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError):
            path_errors.append(f"{path.relative_to(root)}->{path.resolve()}")
            continue
        if not resolved.is_file() or resolved in ignored:
            continue
        if path.suffix.lower() not in {".md", ".json", ".txt", ".tex", ".bib"}:
            continue
        for line_no, line in enumerate(
            resolved.read_text(encoding="utf-8", errors="ignore").splitlines(),
            start=1,
        ):
            for match in URL_RE.finditer(line):
                url = clean_url(match.group(0))
                if not is_academic_url(url):
                    continue
                rows.append(
                    {
                        "url": url,
                        "canonical_key": canonical_url_key(url),
                        "source_file": str(path.relative_to(root)),
                        "line": line_no,
                    }
                )
    return rows, path_errors


def print_path_error(item_id: str, detail: str) -> int:
    print("literature_registry_status=INVALID")
    print("literature_registry_errors=1")
    print(f"INVALID\tPATH_OUTSIDE_ROOT\t{item_id}\t{detail}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument(
        "--ledger-output", type=Path, default=Path("near_neighbor_url_ledger.csv")
    )
    ledger_mode = parser.add_mutually_exclusive_group()
    ledger_mode.add_argument(
        "--write-ledger",
        action="store_true",
        help="Explicitly create or replace the URL ledger.",
    )
    ledger_mode.add_argument(
        "--read-only",
        action="store_true",
        help="Compatibility flag; read-only is the default.",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    registry = args.registry.resolve()
    ledger = (
        args.ledger_output
        if args.ledger_output.is_absolute()
        else root / args.ledger_output
    ).resolve()
    if not root.is_dir():
        return print_path_error("root", f"not_directory:{root}")
    for item_id, path in (("registry", registry), ("ledger", ledger)):
        try:
            path.relative_to(root)
        except ValueError:
            return print_path_error(item_id, f"outside_root:{path}")
    (
        registered_keys,
        owners,
        conflicts,
        duplicate_ids,
        publication_errors,
    ) = load_registry(registry)
    payload = json.loads(registry.read_text(encoding="utf-8"))
    records = payload["records"] if isinstance(payload, dict) else payload
    actual_peer_reviewed_count = sum(
        record.get("peer_review_status") == "PEER_REVIEWED_PUBLISHED"
        for record in records
    )
    declared_peer_reviewed_count = (
        payload.get("peer_reviewed_published_count")
        if isinstance(payload, dict)
        else None
    )
    search_mode = payload.get("search_mode") if isinstance(payload, dict) else None
    threshold = (
        payload.get("synthesis_lock_threshold", 100)
        if isinstance(payload, dict)
        else 100
    )
    if declared_peer_reviewed_count != actual_peer_reviewed_count:
        publication_errors.append(
            (
                "__registry__",
                "peer_reviewed_published_count:"
                f"{declared_peer_reviewed_count};actual:{actual_peer_reviewed_count}",
            )
        )
    allowed_modes = (
        {"SYNTHESIS_LOCK", "EXCEPTION_REOPEN"}
        if actual_peer_reviewed_count >= threshold
        else {"SEARCH_OPEN"}
    )
    if search_mode not in allowed_modes:
        publication_errors.append(
            (
                "__registry__",
                f"search_mode:{search_mode};allowed:{sorted(allowed_modes)}",
            )
        )
    rows, path_errors = scan(root, {registry, ledger})

    if args.write_ledger and not path_errors:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "url",
                    "canonical_key",
                    "source_file",
                    "line",
                    "registry_id",
                    "registered",
                ],
            )
            writer.writeheader()
            for row in rows:
                key = str(row["canonical_key"])
                row["registry_id"] = owners.get(key, "")
                row["registered"] = "YES" if key in registered_keys else "NO"
                writer.writerow(row)

    missing = sorted({str(row["canonical_key"]) for row in rows} - registered_keys)
    print(f"academic_url_occurrences={len(rows)}")
    print(f"registered_url_keys={len(registered_keys)}")
    print(f"unregistered_url_keys={len(missing)}")
    print(f"duplicate_registry_ids={len(duplicate_ids)}")
    print(f"cross_record_url_conflicts={len(conflicts)}")
    print(f"publication_metadata_errors={len(publication_errors)}")
    print(f"path_boundary_errors={len(path_errors)}")
    print(f"peer_reviewed_published_count={actual_peer_reviewed_count}")
    print(f"search_mode={search_mode}")
    for key in missing:
        print(f"UNREGISTERED\t{key}")
    for record_id in duplicate_ids:
        print(f"DUPLICATE_ID\t{record_id}")
    for key, left, right in conflicts:
        print(f"URL_CONFLICT\t{key}\t{left}\t{right}")
    for record_id, error in publication_errors:
        print(f"PUBLICATION_ERROR\t{record_id}\t{error}")
    for error in path_errors:
        print(f"INVALID\tPATH_OUTSIDE_ROOT\tscan\t{error}")
    return 1 if missing or duplicate_ids or conflicts or publication_errors or path_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
