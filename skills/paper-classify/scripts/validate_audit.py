#!/usr/bin/env python3
"""Validate that rejected PaperDB audit records contain specific reasons."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

COLLECTION_KEYS = ("decisions", "results", "papers", "assessments")
GENERIC_REASONS = {
    "failed",
    "failed_gates",
    "failed_one_or_more_gates",
    "failed_strategy_gates",
    "not_qualified",
    "rejected",
}


def records_from(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        records = next(
            (payload[key] for key in COLLECTION_KEYS if isinstance(payload.get(key), list)),
            None,
        )
        if records is None:
            raise ValueError("expected a list or an object containing " + ", ".join(COLLECTION_KEYS))
    else:
        raise ValueError("audit root must be a list or object")
    if not all(isinstance(record, dict) for record in records):
        raise ValueError("every audit record must be an object")
    return records


def validate(records: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for index, record in enumerate(records):
        if record.get("decision") != "rejected":
            continue
        identity = record.get("filename") or record.get("title") or record.get("paper_id") or f"record[{index}]"
        reasons = record.get("rejection_reasons")
        if not isinstance(reasons, list) or not reasons:
            errors.append(f"{identity}: rejected record needs a non-empty rejection_reasons list")
            continue
        normalized: list[str] = []
        for reason in reasons:
            if not isinstance(reason, str) or not reason.strip():
                errors.append(f"{identity}: rejection reasons must be non-empty strings")
                continue
            value = reason.strip().lower().replace(" ", "_")
            normalized.append(value)
            if value in GENERIC_REASONS:
                errors.append(f"{identity}: generic rejection reason is not auditable: {reason!r}")
        if len(normalized) != len(set(normalized)):
            errors.append(f"{identity}: rejection_reasons contains duplicates")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit", type=Path)
    args = parser.parse_args()
    try:
        records = records_from(json.loads(args.audit.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"invalid audit: {exc}", file=sys.stderr)
        return 2
    errors = validate(records)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    rejected = sum(record.get("decision") == "rejected" for record in records)
    print(f"validated {len(records)} records ({rejected} rejected)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
