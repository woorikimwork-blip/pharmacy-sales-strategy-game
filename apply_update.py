"""Apply a reviewed pharmacy data candidate.

This script is intentionally conservative. It only applies outputs/pharmacy_data_candidate.js
after an explicit --yes flag, and it creates a timestamped backup first.
"""
import argparse
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

DATA_FILE = Path("pharmacy_data.js")
OUTPUT_DIR = Path("outputs")
CANDIDATE_FILE = OUTPUT_DIR / "pharmacy_data_candidate.js"
REPORT_FILE = OUTPUT_DIR / "pharmacy_update_review.json"


def load_pharmacy_rows(path):
    content = path.read_text(encoding="utf-8")
    match = re.search(r"const\s+PHARMACY_DATA\s*=\s*(\[.*\]);\s*$", content, re.DOTALL)
    if not match:
        raise RuntimeError(f"PHARMACY_DATA was not found in {path}")
    rows = json.loads(match.group(1))
    return rows, content


def validate_candidate(rows):
    missing_ids = [row.get("name", "") for row in rows if not row.get("pharmacyId")]
    duplicate_ids = len(rows) - len({row.get("pharmacyId") for row in rows})
    if missing_ids:
        raise RuntimeError(f"Candidate has rows without pharmacyId. First sample: {missing_ids[:5]}")
    if duplicate_ids:
        raise RuntimeError(f"Candidate has {duplicate_ids} duplicate pharmacyId values.")


def print_report_summary():
    if not REPORT_FILE.exists():
        print(f"Review report not found: {REPORT_FILE}")
        return
    report = json.loads(REPORT_FILE.read_text(encoding="utf-8"))
    summary = report.get("summary", {})
    print("Review summary:")
    for key in [
        "current_count",
        "api_count",
        "matched_existing_count",
        "new_pharmacies_count",
        "possibly_closed_count",
        "phone_updates_count",
        "coord_updates_count",
        "candidate_count_if_applied",
    ]:
        if key in summary:
            print(f"  {key}: {summary[key]}")


def parse_args():
    parser = argparse.ArgumentParser(description="Apply reviewed pharmacy data candidate.")
    parser.add_argument("--yes", action="store_true", help="Confirm applying outputs/pharmacy_data_candidate.js to pharmacy_data.js.")
    return parser.parse_args()


def main():
    args = parse_args()
    if not CANDIDATE_FILE.exists():
        raise RuntimeError(f"Candidate file not found: {CANDIDATE_FILE}. Run update_pharmacy_data.py first.")

    current_rows, _ = load_pharmacy_rows(DATA_FILE)
    candidate_rows, candidate_content = load_pharmacy_rows(CANDIDATE_FILE)
    validate_candidate(candidate_rows)

    print("=" * 62)
    print("  Apply reviewed pharmacy candidate")
    print("=" * 62)
    print_report_summary()
    print()
    print(f"Current rows:   {len(current_rows):,}")
    print(f"Candidate rows: {len(candidate_rows):,}")

    if not args.yes:
        print()
        print("No files changed. Re-run with --yes only after reviewing the report and candidate file.")
        return 1

    OUTPUT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = OUTPUT_DIR / f"pharmacy_data_backup_{stamp}.js"
    shutil.copy2(DATA_FILE, backup)
    DATA_FILE.write_text(candidate_content, encoding="utf-8")
    print()
    print(f"Backup saved: {backup}")
    print(f"Applied: {DATA_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
