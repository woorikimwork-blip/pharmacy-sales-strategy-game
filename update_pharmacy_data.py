"""Review pharmacy master data updates from the public pharmacy API.

Secrets are read from .env or the process environment. Do not hard-code API keys.

Default behavior is intentionally safe: fetch public API data, compare it with
pharmacy_data.js, and write review artifacts under outputs/. It does not modify
pharmacy_data.js unless --apply is passed.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ENV_FILE = Path(".env")
DATA_FILE = Path("pharmacy_data.js")
OUTPUT_DIR = Path("outputs")
DEFAULT_REPORT_FILE = OUTPUT_DIR / "pharmacy_update_review.json"
DEFAULT_CANDIDATE_FILE = OUTPUT_DIR / "pharmacy_data_candidate.js"
SERVICE_KEY_ENV = "PUBLIC_DATA_SERVICE_KEY"
BASE_URL = "http://apis.data.go.kr/B551182/pharmacyInfoService/getParmacyBasisList"

SIDO_CODES = {
    "110000": "서울특별시",
    "210000": "부산광역시",
    "220000": "대구광역시",
    "230000": "인천광역시",
    "240000": "광주광역시",
    "250000": "대전광역시",
    "260000": "울산광역시",
    "290000": "세종특별자치시",
    "310000": "경기도",
    "320000": "강원특별자치도",
    "330000": "충청북도",
    "340000": "충청남도",
    "350000": "전북특별자치도",
    "360000": "전라남도",
    "370000": "경상북도",
    "380000": "경상남도",
    "390000": "제주특별자치도",
}

PRESERVED_FIELDS = {
    "pharmacyId",
    "market_type",
    "color",
    "branch",
    "region",
    "district",
    "dong",
    "manager",
    "is_trading",
    "claimed_by",
    "claimed_at",
    "priority_target",
    "priority_rank",
    "priority_region",
    "priority_source",
    "priority_flatfarm",
    "priority_rating",
    "priority_reviews",
}


def load_dotenv(path=ENV_FILE):
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_service_key():
    load_dotenv()
    service_key = os.environ.get(SERVICE_KEY_ENV, "").strip()
    if not service_key:
        raise RuntimeError(
            f"{SERVICE_KEY_ENV} is missing. Create .env from .env.example and put your API key there."
        )
    return service_key


def build_url(page_no, num_of_rows=1000, sido_cd=""):
    params = {
        "serviceKey": get_service_key(),
        "pageNo": page_no,
        "numOfRows": num_of_rows,
        "_type": "json",
    }
    if sido_cd:
        params["sidoCd"] = sido_cd
    return BASE_URL + "?" + urlencode(params)


def fetch_page(page_no, num_of_rows=1000, sido_cd=""):
    try:
        request = Request(build_url(page_no, num_of_rows, sido_cd), headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=30) as resp:
            if resp.getcode() != 200:
                print(f"    HTTP {resp.getcode()} error")
                return None
            text = resp.read().decode("utf-8-sig")
            return json.loads(text)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"    request error: {exc}")
        return None


def parse_items_from_body(body):
    items_raw = body.get("items", {})
    if not items_raw:
        return []
    item_list = items_raw.get("item", [])
    if isinstance(item_list, dict):
        return [item_list]
    return item_list or []


def fetch_all_pages():
    all_items = []
    page_no = 1
    total = None
    print("  [all regions] fetching...", end="", flush=True)
    while True:
        data = fetch_page(page_no, 1000)
        if not data:
            break
        try:
            body = data["response"]["body"]
            total = int(body.get("totalCount") or 0)
            if total == 0:
                break
            item_list = parse_items_from_body(body)
            if not item_list:
                break
            all_items.extend(item_list)
            if page_no * 1000 >= total:
                break
            page_no += 1
            time.sleep(0.2)
        except Exception as exc:
            print(f" parse error: {exc}")
            break
    suffix = f" / expected {total:,}" if total else ""
    print(f" {len(all_items):,} rows{suffix}")
    return all_items


def fetch_all_by_region(limit_regions=None):
    all_items = []
    region_items = list(SIDO_CODES.items())
    if limit_regions:
        wanted = set(limit_regions)
        region_items = [(code, name) for code, name in region_items if code in wanted or name in wanted]

    for sido_cd, sido_name in region_items:
        print(f"  [{sido_name}] fetching...", end="", flush=True)
        page_no = 1
        region_count = 0
        while True:
            data = fetch_page(page_no, 1000, sido_cd)
            if not data:
                break
            try:
                body = data["response"]["body"]
                total = int(body.get("totalCount") or 0)
                if total == 0:
                    break
                item_list = parse_items_from_body(body)
                if not item_list:
                    break
                all_items.extend(item_list)
                region_count += len(item_list)
                if page_no * 1000 >= total:
                    break
                page_no += 1
                time.sleep(0.2)
            except Exception as exc:
                print(f" parse error: {exc}")
                break
        print(f" {region_count} rows")
    return all_items


def load_pharmacy_data():
    content = DATA_FILE.read_text(encoding="utf-8")
    match = re.search(r"const\s+PHARMACY_DATA\s*=\s*(\[.*\]);\s*$", content, re.DOTALL)
    if not match:
        raise RuntimeError(f"PHARMACY_DATA was not found in {DATA_FILE}")
    existing = json.loads(match.group(1))
    print(f"  current pharmacies: {len(existing):,}")
    return existing, content


def compact(value):
    return re.sub(r"\s+", "", str(value or ""))


def normalize_key(name, addr):
    normalized_name = compact(name)
    normalized_addr = compact(addr)[:100]
    return f"{normalized_name}|{normalized_addr}"


def phone_key(phone):
    return re.sub(r"\D+", "", str(phone or ""))


def stable_pharmacy_id(name, address):
    raw = normalize_key(name, address)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"ph_{digest}"


def split_region(addr):
    parts = str(addr or "").split()
    return (parts[0] if parts else "", parts[1] if len(parts) > 1 else "")


def extract_dong(addr):
    text = str(addr or "")
    suffixes = ("\ub3d9", "\uac00", "\uc74d", "\uba74", "\ub9ac")

    for group in re.findall(r"\(([^)]*)\)", text):
        for token in re.split(r"[\s,]+", group):
            cleaned = re.sub(r"[^0-9A-Za-z\uac00-\ud7a3]", "", token)
            if cleaned.endswith(suffixes):
                return cleaned

    found = []
    for token in re.split(r"\s+", text):
        cleaned = re.sub(r"[^0-9A-Za-z\uac00-\ud7a3]", "", token)
        if cleaned.endswith(suffixes):
            found.append(cleaned)
    return found[-1] if found else ""


def get_coord(item):
    for y_key, x_key in [("YPos", "XPos"), ("yPos", "xPos"), ("latitude", "longitude"), ("lat", "lon")]:
        y = item.get(y_key)
        x = item.get(x_key)
        if y and x:
            try:
                return float(y), float(x)
            except (TypeError, ValueError):
                pass
    return None, None


def api_to_candidate(api):
    name = api.get("yadmNm", "")
    address = api.get("addr", "")
    region, district = split_region(address)
    lat, lng = get_coord(api)
    return {
        "name": name,
        "address": address,
        "phone": api.get("telno", ""),
        "market_type": "",
        "color": "#888888",
        "branch": "",
        "region": region,
        "district": district,
        "dong": extract_dong(address),
        "manager": "",
        "is_trading": False,
        "lat": lat,
        "lng": lng,
        "claimed_by": None,
        "claimed_at": None,
        "pharmacyId": stable_pharmacy_id(name, address),
        "review_status": "new_pending",
        "active": True,
    }


def build_api_lookup(api_items):
    lookup = {}
    duplicates = []
    for item in api_items:
        name = item.get("yadmNm", "")
        addr = item.get("addr", "")
        if not name or not addr:
            continue
        key = normalize_key(name, addr)
        if key in lookup:
            duplicates.append({"name": name, "address": addr})
            continue
        lookup[key] = item
    return lookup, duplicates


def row_summary(row):
    return {
        "pharmacyId": row.get("pharmacyId", ""),
        "name": row.get("name", ""),
        "address": row.get("address", ""),
        "phone": row.get("phone", ""),
        "branch": row.get("branch", ""),
    }


def merge_for_review(existing, api_items):
    print("\nComparing data...")
    existing_lookup = {normalize_key(row.get("name"), row.get("address")): row for row in existing}
    api_lookup, api_duplicates = build_api_lookup(api_items)

    matched = 0
    coord_updates = []
    phone_updates = []
    possibly_closed = []
    candidate_rows = []

    for key, current in existing_lookup.items():
        merged = dict(current)
        if not merged.get("pharmacyId"):
            merged["pharmacyId"] = stable_pharmacy_id(merged.get("name"), merged.get("address"))

        api = api_lookup.get(key)
        if api:
            matched += 1
            lat, lng = get_coord(api)
            if lat is not None and lng is not None:
                if merged.get("lat") != lat or merged.get("lng") != lng:
                    coord_updates.append({**row_summary(merged), "old_lat": merged.get("lat"), "old_lng": merged.get("lng"), "new_lat": lat, "new_lng": lng})
                    merged["lat"] = lat
                    merged["lng"] = lng
            api_phone = api.get("telno", "")
            if api_phone and phone_key(api_phone) != phone_key(merged.get("phone")):
                phone_updates.append({**row_summary(merged), "old_phone": merged.get("phone", ""), "new_phone": api_phone})
                merged["phone"] = api_phone
        else:
            closed = row_summary(merged)
            closed["review_status"] = "possibly_closed"
            possibly_closed.append(closed)
        candidate_rows.append(merged)

    new_pharmacies = []
    for key, api in api_lookup.items():
        if key in existing_lookup:
            continue
        candidate = api_to_candidate(api)
        new_pharmacies.append(row_summary(candidate) | {
            "region": candidate.get("region", ""),
            "district": candidate.get("district", ""),
            "dong": candidate.get("dong", ""),
            "lat": candidate.get("lat"),
            "lng": candidate.get("lng"),
            "review_status": "new_pending",
        })
        candidate_rows.append(candidate)

    summary = {
        "current_count": len(existing),
        "api_count": len(api_lookup),
        "matched_existing_count": matched,
        "new_pharmacies_count": len(new_pharmacies),
        "possibly_closed_count": len(possibly_closed),
        "phone_updates_count": len(phone_updates),
        "coord_updates_count": len(coord_updates),
        "api_duplicate_count": len(api_duplicates),
        "candidate_count_if_applied": len(candidate_rows),
    }
    details = {
        "new_pharmacies": new_pharmacies,
        "possibly_closed": possibly_closed,
        "phone_updates": phone_updates,
        "coord_updates": coord_updates,
        "api_duplicates": api_duplicates[:200],
    }
    print(f"  matched existing: {matched:,}")
    print(f"  phone updates: {len(phone_updates):,}")
    print(f"  coordinate updates: {len(coord_updates):,}")
    print(f"  possibly closed: {len(possibly_closed):,}")
    print(f"  new pharmacies: {len(new_pharmacies):,}")
    return candidate_rows, summary, details


def render_data_file(original_content, rows):
    json_str = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return re.sub(
        r"const\s+PHARMACY_DATA\s*=\s*\[.*\];\s*$",
        f"const PHARMACY_DATA = {json_str};\n",
        original_content,
        flags=re.DOTALL,
    )


def save_review(report_file, summary, details, args):
    OUTPUT_DIR.mkdir(exist_ok=True)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if args.apply else "review_only",
        "source": BASE_URL,
        "summary": summary,
        "details": details,
        "next_step": "Review this report. Run with --apply only after confirming the candidate data.",
    }
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  saved report: {report_file}")


def save_candidate(candidate_file, original_content, candidate_rows):
    OUTPUT_DIR.mkdir(exist_ok=True)
    candidate_file.write_text(render_data_file(original_content, candidate_rows), encoding="utf-8")
    print(f"  saved candidate data: {candidate_file}")


def parse_args():
    parser = argparse.ArgumentParser(description="Review pharmacy public API updates safely.")
    parser.add_argument("--apply", action="store_true", help="Overwrite pharmacy_data.js after writing review artifacts.")
    parser.add_argument("--report", default=str(DEFAULT_REPORT_FILE), help="Review report path.")
    parser.add_argument("--candidate", default=str(DEFAULT_CANDIDATE_FILE), help="Candidate pharmacy_data.js path.")
    parser.add_argument("--region", action="append", help="Limit fetch to a sido code or name for smoke tests. Can be used multiple times.")
    parser.add_argument("--skip-candidate", action="store_true", help="Do not write the candidate data file.")
    return parser.parse_args()


def main():
    args = parse_args()
    report_file = Path(args.report)
    candidate_file = Path(args.candidate)

    print("=" * 62)
    print("  Pharmacy data update review")
    print("=" * 62)

    print("\n[1] Checking API connection...")
    test = fetch_page(1, 3)
    if not test:
        print("API connection failed")
        return 1
    total_count = test["response"]["body"].get("totalCount")
    print(f"  API connection OK. totalCount={total_count}")

    print("\n[2] Loading current pharmacy_data.js...")
    existing, data_content = load_pharmacy_data()

    print(f"\n[3] Fetching public API data...")
    if args.region:
        api_items = fetch_all_by_region(args.region)
    else:
        api_items = fetch_all_pages()
    print(f"\n  fetched total: {len(api_items):,}")

    print("\n[4] Building review and candidate data...")
    candidate_rows, summary, details = merge_for_review(existing, api_items)

    print("\n[5] Saving review artifacts...")
    save_review(report_file, summary, details, args)
    if not args.skip_candidate:
        save_candidate(candidate_file, data_content, candidate_rows)

    if args.apply:
        print("\n[6] Applying candidate to pharmacy_data.js...")
        DATA_FILE.write_text(render_data_file(data_content, candidate_rows), encoding="utf-8")
        print(f"  applied: {DATA_FILE} ({len(candidate_rows):,} rows)")
    else:
        print("\n[6] Review only. pharmacy_data.js was not changed.")
        print("    To apply after review: python update_pharmacy_data.py --apply")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(f"Setup error: {exc}")
        sys.exit(1)
