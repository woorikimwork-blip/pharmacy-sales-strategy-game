"""Update pharmacy master data from the public pharmacy API.

Secrets are read from .env or the process environment. Do not hard-code API keys.
"""
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ENV_FILE = Path(".env")
DATA_FILE = Path("pharmacy_data.js")
REPORT_FILE = Path("update_report.json")
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
    service_key = get_service_key()
    url = (
        f"{BASE_URL}?serviceKey={service_key}"
        f"&pageNo={page_no}&numOfRows={num_of_rows}&_type=json"
    )
    if sido_cd:
        url += f"&sidoCd={sido_cd}"
    return url


def fetch_page(page_no, num_of_rows=1000, sido_cd=""):
    try:
        with urlopen(build_url(page_no, num_of_rows, sido_cd), timeout=30) as resp:
            status = resp.getcode()
            if status != 200:
                print(f"    HTTP {status} error")
                return None
            text = resp.read().decode("utf-8-sig")
            return json.loads(text)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"    request error: {exc}")
        return None


def fetch_all_by_region():
    all_items = []
    for sido_cd, sido_name in SIDO_CODES.items():
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
                items_raw = body.get("items", {})
                if not items_raw:
                    break
                item_list = items_raw.get("item", [])
                if isinstance(item_list, dict):
                    item_list = [item_list]
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


def normalize_key(name, addr):
    normalized_name = re.sub(r"\s+", "", name or "")
    normalized_addr = re.sub(r"\s+", "", addr or "")[:80]
    return f"{normalized_name}|{normalized_addr}"


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


def merge(existing, api_items):
    print("\nMerging data...")
    existing_lookup = {normalize_key(row.get("name"), row.get("address")): row for row in existing}

    api_lookup = {}
    for item in api_items:
        name = item.get("yadmNm", "")
        addr = item.get("addr", "")
        if name and addr:
            api_lookup[normalize_key(name, addr)] = item

    coord_updated = 0
    phone_updated = 0
    matched = 0
    possibly_closed = []
    new_pharmacies = []

    result = []
    for key, current in existing_lookup.items():
        merged = dict(current)
        api = api_lookup.get(key)
        if api:
            matched += 1
            if merged.get("lat") is None or merged.get("lng") is None:
                lat, lng = get_coord(api)
                if lat is not None and lng is not None:
                    merged["lat"] = lat
                    merged["lng"] = lng
                    coord_updated += 1
            if not merged.get("phone") and api.get("telno"):
                merged["phone"] = api.get("telno", "")
                phone_updated += 1
        else:
            possibly_closed.append({"name": current.get("name", ""), "address": current.get("address", "")})
        result.append(merged)

    for key, api in api_lookup.items():
        if key in existing_lookup:
            continue
        name = api.get("yadmNm", "")
        addr = api.get("addr", "")
        if not name or not addr:
            continue
        addr_parts = addr.split()
        lat, lng = get_coord(api)
        new_pharmacies.append({
            "name": name,
            "address": addr,
            "phone": api.get("telno", ""),
            "market_type": "",
            "color": "#888888",
            "branch": "",
            "region": addr_parts[0] if addr_parts else "",
            "district": addr_parts[1] if len(addr_parts) > 1 else "",
            "manager": "",
            "is_trading": False,
            "lat": lat,
            "lng": lng,
            "claimed_by": None,
            "claimed_at": None,
            "review_status": "pending",
            "active": True,
        })

    print(f"  matched existing: {matched:,}")
    print(f"  coordinates updated: {coord_updated:,}")
    print(f"  phone numbers updated: {phone_updated:,}")
    print(f"  possibly closed: {len(possibly_closed):,}")
    print(f"  new pharmacies found: {len(new_pharmacies):,}")
    return result, new_pharmacies, possibly_closed


def save_pharmacy_data(original_content, merged_data):
    json_str = json.dumps(merged_data, ensure_ascii=False, separators=(",", ":"))
    new_content = re.sub(
        r"const\s+PHARMACY_DATA\s*=\s*\[.*\];\s*$",
        f"const PHARMACY_DATA = {json_str};\n",
        original_content,
        flags=re.DOTALL,
    )
    DATA_FILE.write_text(new_content, encoding="utf-8")
    print(f"  saved: {DATA_FILE} ({len(merged_data):,} rows)")


def save_report(new_pharmacies, possibly_closed):
    report = {
        "new_pharmacies_count": len(new_pharmacies),
        "possibly_closed_count": len(possibly_closed),
        "new_pharmacies": new_pharmacies,
        "possibly_closed": possibly_closed,
    }
    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  saved: {REPORT_FILE}")


def main():
    print("=" * 55)
    print("  Pharmacy data updater")
    print("=" * 55)

    print("\n[1] Checking API connection...")
    test = fetch_page(1, 3)
    if not test:
        print("API connection failed")
        return 1
    total_count = test["response"]["body"].get("totalCount")
    print(f"  API connection OK. totalCount={total_count}")

    print("\n[2] Loading current pharmacy_data.js...")
    existing, data_content = load_pharmacy_data()

    print(f"\n[3] Fetching public API data ({len(SIDO_CODES)} regions)...")
    api_items = fetch_all_by_region()
    print(f"\n  fetched total: {len(api_items):,}")

    print("\n[4] Merging...")
    merged, new_pharmacies, possibly_closed = merge(existing, api_items)

    print("\n[5] Saving report...")
    save_report(new_pharmacies, possibly_closed)

    print("\n[6] Saving pharmacy_data.js...")
    save_pharmacy_data(data_content, merged)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(f"Setup error: {exc}")
        sys.exit(1)