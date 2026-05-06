"""
심평원 약국정보 API → 게임 데이터 업데이트 스크립트
HTTP 엔드포인트 사용 (HTTPS 401 오류)
"""
import requests
import json
import re
import time

SERVICE_KEY = "9d0dab2e69b917b41ce64b1fdb7e5974cce193e23eb593819259578cceb2dc67"
BASE_URL = "http://apis.data.go.kr/B551182/pharmacyInfoService/getParmacyBasisList"
GAME_FILE = "약국_영토점령_게임_v2.html"

# 게임에 포함된 지역의 심평원 시도코드
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
    "410000": "제주특별자치도",
}

def fetch_page(page_no, num_of_rows=1000, sido_cd=""):
    """API 1페이지 호출"""
    url = f"{BASE_URL}?serviceKey={SERVICE_KEY}&pageNo={page_no}&numOfRows={num_of_rows}&_type=json"
    if sido_cd:
        url += f"&sidoCd={sido_cd}"
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            print(f"    HTTP {resp.status_code} 오류")
            return None
        return resp.json()
    except Exception as e:
        print(f"    요청 오류: {e}")
        return None

def fetch_all_by_region():
    """지역별 전체 약국 수집"""
    all_items = []
    for sido_cd, sido_name in SIDO_CODES.items():
        print(f"  [{sido_name}] 수집 중...", end="", flush=True)
        page_no = 1
        region_count = 0
        while True:
            data = fetch_page(page_no, 1000, sido_cd)
            if not data:
                break
            try:
                body = data["response"]["body"]
                total = int(body["totalCount"])
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
            except Exception as e:
                print(f"\n    파싱 오류: {e}")
                break
        print(f" {region_count}개")
    return all_items

def load_game_data():
    """기존 게임 HTML에서 PHARMACY_DATA 추출"""
    with open(GAME_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    match = re.search(r'const PHARMACY_DATA = (\[.*?\]);', content, re.DOTALL)
    if not match:
        raise Exception("PHARMACY_DATA를 찾을 수 없음")
    existing = json.loads(match.group(1))
    print(f"  기존 약국: {len(existing)}개")
    return existing, content

def build_key(name, addr):
    """매칭용 고유키"""
    n = re.sub(r'\s+', '', name or "")
    a = re.sub(r'\s+', '', addr or "")[:25]
    return f"{n}|{a}"

def get_coord(item):
    """API 항목에서 위도/경도 추출"""
    for yk, xk in [("YPos","XPos"), ("yPos","xPos"), ("latitude","longitude"), ("lat","lon")]:
        y = item.get(yk)
        x = item.get(xk)
        if y and x:
            try:
                return float(y), float(x)
            except:
                pass
    return None, None

def merge(existing, api_items):
    """기존 데이터 + API 데이터 병합"""
    print(f"\n🔄 병합 중...")

    # 기존 인덱싱
    ex_lookup = {build_key(d["name"], d["address"]): d for d in existing}

    # API 인덱싱
    api_lookup = {}
    for item in api_items:
        name = item.get("yadmNm", "")
        addr = item.get("addr", "")
        if name and addr:
            api_lookup[build_key(name, addr)] = item

    coord_updated = 0
    phone_updated = 0
    matched = 0
    possibly_closed = []
    new_pharmacies = []

    result = []
    for key, ex in ex_lookup.items():
        merged = dict(ex)
        if key in api_lookup:
            matched += 1
            api = api_lookup[key]
            # 좌표 없으면 API에서 가져오기
            if merged.get("lat") is None or merged.get("lng") is None:
                lat, lng = get_coord(api)
                if lat and lng:
                    merged["lat"] = lat
                    merged["lng"] = lng
                    coord_updated += 1
            # 전화번호 없으면 업데이트
            if not merged.get("phone") and api.get("telno"):
                merged["phone"] = api.get("telno", "")
                phone_updated += 1
        else:
            possibly_closed.append({"name": ex["name"], "address": ex["address"]})
        result.append(merged)

    # 신규 약국 (API에만 있는 것)
    for key, api in api_lookup.items():
        if key not in ex_lookup:
            name = api.get("yadmNm", "")
            addr = api.get("addr", "")
            if not name:
                continue
            addr_parts = addr.split(" ")
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
            })

    print(f"  ✅ 기존 매칭: {matched}개")
    print(f"  📍 좌표 업데이트: {coord_updated}개")
    print(f"  📞 전화번호 업데이트: {phone_updated}개")
    print(f"  ⚠️  API 미존재 (폐업 의심): {len(possibly_closed)}개")
    print(f"  🆕 신규 발견: {len(new_pharmacies)}개 (담당자 배정 필요)")

    return result, new_pharmacies, possibly_closed

def save_html(content, merged_data):
    """HTML 파일에 새 데이터 삽입"""
    json_str = json.dumps(merged_data, ensure_ascii=False, separators=(",", ":"))
    new_content = re.sub(
        r'const PHARMACY_DATA = \[.*?\];',
        f'const PHARMACY_DATA = {json_str};',
        content, flags=re.DOTALL
    )
    with open(GAME_FILE, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"  ✅ 저장 완료: {GAME_FILE} ({len(merged_data)}개)")

def save_report(new_pharmacies, possibly_closed):
    """신규/폐업 보고서 저장"""
    report = {
        "new_pharmacies_count": len(new_pharmacies),
        "possibly_closed_count": len(possibly_closed),
        "new_pharmacies": new_pharmacies,
        "possibly_closed": possibly_closed,
    }
    with open("update_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  📄 보고서 저장: update_report.json")

# ===== 실행 =====
print("=" * 55)
print("  심평원 약국정보 API → 게임 데이터 업데이터")
print("=" * 55)

# 1. API 연결 확인
print("\n[1] API 연결 확인...")
test = fetch_page(1, 3)
if not test:
    print("❌ API 연결 실패")
    exit(1)
total_count = test["response"]["body"]["totalCount"]
print(f"  ✅ 연결 성공! 전국 약국 총 {total_count:,}개")

# 2. 기존 데이터 로드
print("\n[2] 기존 게임 데이터 로드...")
existing, html_content = load_game_data()

# 3. API 전체 수집
print(f"\n[3] 지역별 API 데이터 수집 ({len(SIDO_CODES)}개 지역)...")
api_items = fetch_all_by_region()
print(f"\n  총 수집: {len(api_items):,}개")

# 4. 병합
merged, new_pharmacies, possibly_closed = merge(existing, api_items)

# 5. 보고서 저장
print("\n[4] 보고서 저장...")
save_report(new_pharmacies, possibly_closed)

# 6. HTML 업데이트
print("\n[5] 게임 파일 업데이트...")
save_html(html_content, merged)

print("\n" + "=" * 55)
print("  완료!")
print(f"  - 기존 데이터(좌표/전화번호 업데이트) 반영")
print(f"  - 신규 약국 {len(new_pharmacies)}개 → update_report.json 확인")
print(f"  - 폐업 의심 {len(possibly_closed)}개 → update_report.json 확인")
print("=" * 55)
