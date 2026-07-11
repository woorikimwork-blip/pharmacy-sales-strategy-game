"""Apply only workbook-approved pharmacy update rows.

Default mode is conservative:
- reads outputs/review_workbook/pharmacy_update_review_workbook.xlsx
- reads current pharmacy_data.js and a generated candidate file
- applies only rows whose Review Status is Approve
- writes outputs/pharmacy_data_approved_candidate.js and a JSON report
- does NOT overwrite pharmacy_data.js unless --apply --yes is supplied

Workbook sheets expected from the review workbook:
- New Candidates: Approve adds candidate rows
- Possibly Closed: Approve removes current rows
- Phone Updates: Approve updates phone from candidate rows
- Coordinate Updates: Approve updates lat/lng from candidate rows
"""
import argparse
import copy
import json
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

DATA_FILE = Path("pharmacy_data.js")
OUTPUT_DIR = Path("outputs")
DEFAULT_WORKBOOK = OUTPUT_DIR / "review_workbook" / "pharmacy_update_review_workbook.xlsx"
DEFAULT_CANDIDATE = OUTPUT_DIR / "pharmacy_data_candidate_full.js"
DEFAULT_OUTPUT = OUTPUT_DIR / "pharmacy_data_approved_candidate.js"
DEFAULT_REPORT = OUTPUT_DIR / "pharmacy_approved_apply_report.json"

NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
}

APPROVE_VALUES = {"approve", "approved", "yes", "y", "true", "1", "??"}
REVIEW_SHEETS = {
    "New Candidates": "add",
    "Possibly Closed": "remove",
    "Phone Updates": "phone",
    "Coordinate Updates": "coord",
}


def load_pharmacy_rows(path):
    content = path.read_text(encoding="utf-8")
    match = re.search(r"const\s+PHARMACY_DATA\s*=\s*(\[.*\]);\s*$", content, re.DOTALL)
    if not match:
        raise RuntimeError(f"PHARMACY_DATA was not found in {path}")
    rows = json.loads(match.group(1))
    return rows, content


def render_data_file(original_content, rows):
    match = re.search(r"const\s+PHARMACY_DATA\s*=\s*(\[.*\]);\s*$", original_content, re.DOTALL)
    if not match:
        raise RuntimeError("PHARMACY_DATA block was not found in current data file")
    body = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return original_content[: match.start(1)] + body + original_content[match.end(1) :]


def validate_rows(rows, label):
    ids = [row.get("pharmacyId") for row in rows]
    missing = [row.get("name", "") for row in rows if not row.get("pharmacyId")]
    duplicate_count = len(ids) - len(set(ids))
    if missing:
        raise RuntimeError(f"{label} has rows without pharmacyId. Samples: {missing[:5]}")
    if duplicate_count:
        raise RuntimeError(f"{label} has {duplicate_count} duplicate pharmacyId values")


def col_to_index(cell_ref):
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch.upper()) - 64)
    return idx - 1


def read_shared_strings(zf):
    try:
        xml = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(xml)
    strings = []
    for si in root.findall("main:si", NS):
        parts = [t.text or "" for t in si.findall(".//main:t", NS)]
        strings.append("".join(parts))
    return strings


def workbook_sheet_paths(zf):
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_targets = {}
    for rel in rels.findall("pkgrel:Relationship", NS):
        rid = rel.attrib.get("Id")
        target = rel.attrib.get("Target", "")
        if not target.startswith("/"):
            target = "xl/" + target
        else:
            target = target.lstrip("/")
        rel_targets[rid] = target

    paths = {}
    for sheet in workbook.findall("main:sheets/main:sheet", NS):
        name = sheet.attrib.get("name")
        rid = sheet.attrib.get(f"{{{NS['rel']}}}id")
        if name and rid in rel_targets:
            paths[name] = rel_targets[rid]
    return paths


def cell_value(cell, shared_strings):
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(t.text or "" for t in cell.findall(".//main:t", NS))
    value_node = cell.find("main:v", NS)
    if value_node is None or value_node.text is None:
        return ""
    raw = value_node.text
    if cell_type == "s":
        try:
            return shared_strings[int(raw)]
        except (ValueError, IndexError):
            return ""
    if cell_type == "b":
        return raw == "1"
    return raw


def read_sheet_rows(xlsx_path, sheet_name):
    with zipfile.ZipFile(xlsx_path) as zf:
        shared_strings = read_shared_strings(zf)
        paths = workbook_sheet_paths(zf)
        if sheet_name not in paths:
            return []
        root = ET.fromstring(zf.read(paths[sheet_name]))
        rows = []
        for row in root.findall(".//main:sheetData/main:row", NS):
            values = []
            for cell in row.findall("main:c", NS):
                idx = col_to_index(cell.attrib.get("r", "A1"))
                while len(values) <= idx:
                    values.append("")
                values[idx] = cell_value(cell, shared_strings)
            rows.append(values)
        return rows


def normalize_header(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def find_table(rows):
    for i, row in enumerate(rows):
        headers = [str(v or "").strip() for v in row]
        normalized = [normalize_header(v) for v in headers]
        if "reviewstatus" in normalized and "pharmacyid" in normalized:
            return headers, rows[i + 1 :]
    return [], []


def approved_ids_from_sheet(xlsx_path, sheet_name):
    rows = read_sheet_rows(xlsx_path, sheet_name)
    headers, data_rows = find_table(rows)
    if not headers:
        return set(), {"sheet": sheet_name, "approved": 0, "rows": 0, "missing_id": 0}

    header_map = {normalize_header(h): idx for idx, h in enumerate(headers)}
    status_idx = header_map.get("reviewstatus")
    id_idx = header_map.get("pharmacyid")
    approved = set()
    missing_id = 0
    seen_rows = 0
    for row in data_rows:
        if not any(str(v or "").strip() for v in row):
            continue
        seen_rows += 1
        status = str(row[status_idx] if status_idx is not None and status_idx < len(row) else "").strip().lower()
        pharmacy_id = str(row[id_idx] if id_idx is not None and id_idx < len(row) else "").strip()
        if status in APPROVE_VALUES:
            if pharmacy_id:
                approved.add(pharmacy_id)
            else:
                missing_id += 1
    return approved, {"sheet": sheet_name, "approved": len(approved), "rows": seen_rows, "missing_id": missing_id}


def collect_approvals(workbook_path):
    approvals = {}
    stats = []
    for sheet_name, action in REVIEW_SHEETS.items():
        ids, sheet_stats = approved_ids_from_sheet(workbook_path, sheet_name)
        approvals[action] = ids
        stats.append({"action": action, **sheet_stats})
    return approvals, stats


def apply_approvals(current_rows, candidate_rows, approvals):
    current_by_id = {row.get("pharmacyId"): row for row in current_rows}
    candidate_by_id = {row.get("pharmacyId"): row for row in candidate_rows}

    remove_ids = approvals.get("remove", set())
    add_ids = approvals.get("add", set())
    phone_ids = approvals.get("phone", set())
    coord_ids = approvals.get("coord", set())

    skipped = {"remove_missing_current": [], "add_missing_candidate": [], "phone_missing_candidate": [], "coord_missing_candidate": []}
    applied = {"removed": 0, "added": 0, "phone_updated": 0, "coord_updated": 0}

    final_rows = []
    for row in current_rows:
        pharmacy_id = row.get("pharmacyId")
        if pharmacy_id in remove_ids:
            applied["removed"] += 1
            continue
        new_row = copy.deepcopy(row)
        candidate = candidate_by_id.get(pharmacy_id)
        if pharmacy_id in phone_ids:
            if candidate:
                new_row["phone"] = candidate.get("phone", new_row.get("phone", ""))
                applied["phone_updated"] += 1
            else:
                skipped["phone_missing_candidate"].append(pharmacy_id)
        if pharmacy_id in coord_ids:
            if candidate:
                new_row["lat"] = candidate.get("lat", new_row.get("lat"))
                new_row["lng"] = candidate.get("lng", new_row.get("lng"))
                applied["coord_updated"] += 1
            else:
                skipped["coord_missing_candidate"].append(pharmacy_id)
        final_rows.append(new_row)

    for pharmacy_id in sorted(remove_ids):
        if pharmacy_id not in current_by_id:
            skipped["remove_missing_current"].append(pharmacy_id)

    existing_ids = {row.get("pharmacyId") for row in final_rows}
    for pharmacy_id in sorted(add_ids):
        candidate = candidate_by_id.get(pharmacy_id)
        if not candidate:
            skipped["add_missing_candidate"].append(pharmacy_id)
            continue
        if pharmacy_id in existing_ids:
            continue
        final_rows.append(copy.deepcopy(candidate))
        existing_ids.add(pharmacy_id)
        applied["added"] += 1

    return final_rows, applied, skipped


def parse_args():
    parser = argparse.ArgumentParser(description="Apply only Approve rows from the pharmacy review workbook.")
    parser.add_argument("--workbook", default=str(DEFAULT_WORKBOOK), help="Review workbook path.")
    parser.add_argument("--candidate", default=str(DEFAULT_CANDIDATE), help="Full candidate pharmacy_data.js path.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Approved-only candidate output path.")
    parser.add_argument("--report", default=str(DEFAULT_REPORT), help="Approved-only apply report path.")
    parser.add_argument("--apply", action="store_true", help="Overwrite pharmacy_data.js with approved-only result. Requires --yes.")
    parser.add_argument("--yes", action="store_true", help="Confirm applying to pharmacy_data.js when --apply is used.")
    return parser.parse_args()


def main():
    args = parse_args()
    workbook_path = Path(args.workbook)
    candidate_path = Path(args.candidate)
    output_path = Path(args.output)
    report_path = Path(args.report)

    if not workbook_path.exists():
        raise RuntimeError(f"Review workbook not found: {workbook_path}")
    if not candidate_path.exists():
        raise RuntimeError(f"Candidate file not found: {candidate_path}")

    current_rows, current_content = load_pharmacy_rows(DATA_FILE)
    candidate_rows, _ = load_pharmacy_rows(candidate_path)
    validate_rows(current_rows, "current data")
    validate_rows(candidate_rows, "candidate data")

    approvals, sheet_stats = collect_approvals(workbook_path)
    final_rows, applied, skipped = apply_approvals(current_rows, candidate_rows, approvals)
    validate_rows(final_rows, "approved result")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_data_file(current_content, final_rows), encoding="utf-8")

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "workbook": str(workbook_path),
        "candidate": str(candidate_path),
        "output": str(output_path),
        "current_count": len(current_rows),
        "approved_result_count": len(final_rows),
        "sheet_stats": sheet_stats,
        "applied": applied,
        "skipped": skipped,
        "mode": "applied" if args.apply and args.yes else "review_only",
        "next_step": "Review output JS and report. Run with --apply --yes only when ready.",
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 62)
    print("  Apply approved pharmacy review rows")
    print("=" * 62)
    print(f"Workbook: {workbook_path}")
    print(f"Current rows: {len(current_rows):,}")
    print(f"Approved result rows: {len(final_rows):,}")
    print("Applied changes:")
    for key, value in applied.items():
        print(f"  {key}: {value:,}")
    print(f"Output candidate: {output_path}")
    print(f"Report: {report_path}")

    if args.apply:
        if not args.yes:
            print("\nNo live data changed. Add --yes with --apply to overwrite pharmacy_data.js.")
            return 1
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = OUTPUT_DIR / f"pharmacy_data_backup_approved_{stamp}.js"
        shutil.copy2(DATA_FILE, backup)
        DATA_FILE.write_text(render_data_file(current_content, final_rows), encoding="utf-8")
        print(f"\nBackup saved: {backup}")
        print(f"Applied to: {DATA_FILE}")
    else:
        print("\nLive data was not changed. This was a review-only run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
