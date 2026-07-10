"""
1. 폐업 의심 약국 제거
2. 신규 약국 지점별 자동 배정 후 추가
"""
import json, re

DATA_FILE = "pharmacy_data.js"

# =============================================
# 지점별 담당 지역 매핑 (시도 + 시군구 기준)
# =============================================
BRANCH_MAPPING = {
    "경남영업지점": {
        "regions": ["부산광역시", "울산광역시"],
        "districts": ["해운대구", "부산진구", "남구", "중구", "북구", "동구", "사상구",
                      "동래구", "연제구", "수영구", "사하구", "금정구", "강서구",
                      "기장군", "서구"],  # 부산 전체 + 울산
        "color": "#FF6B6B",
        "market_type_default": "유동인구",
        "managers": ["김효동", "조순홍"],
        "manager_default": "조순홍",
    },
    "경북영업지점": {
        "regions": ["대구광역시"],
        "districts": [],  # 대구 전체
        "color": "#4ECDC4",
        "market_type_default": "성형·피부과",
        "managers": ["김재영", "김정수"],
        "manager_default": "김재영",
    },
    "서부영업지점": {
        "regions": ["광주광역시", "제주특별자치도", "전라남도", "전라북도"],
        "districts": [],
        "color": "#45B7D1",
        "market_type_default": "유동인구",
        "managers": ["강지훈", "송훈"],
        "manager_default": "강지훈",
    },
    "수도권1지점": {
        "regions": ["인천광역시"],
        "districts": [],  # 인천 전체 + 경기 부천
        "extra": [("경기도", "부천시"), ("경기도", "시흥시"), ("경기도", "김포시")],
        "color": "#96CEB4",
        "market_type_default": "유동인구",
        "managers": ["김창규", "한병훈"],
        "manager_default": "김창규",
    },
    "수도권2지점": {
        "regions": [],
        "districts": [],
        "extra": [
            ("서울특별시", "강남구"), ("서울특별시", "송파구"), ("서울특별시", "강동구"),
            ("서울특별시", "서초구"),
            ("경기도", "성남시"), ("경기도", "안양시"), ("경기도", "과천시"),
            ("경기도", "의왕시"), ("경기도", "군포시"),
        ],
        "color": "#FFEAA7",
        "market_type_default": "성형·피부과",
        "managers": ["한병훈"],
        "manager_default": "한병훈",
    },
    "수도권3지점": {
        "regions": [],
        "districts": [],
        "extra": [
            ("서울특별시", "관악구"), ("서울특별시", "영등포구"), ("서울특별시", "구로구"),
            ("서울특별시", "금천구"), ("서울특별시", "동작구"), ("서울특별시", "양천구"),
            ("서울특별시", "강서구"),
            ("경기도", "수원시"), ("경기도", "화성시"), ("경기도", "오산시"),
            ("경기도", "평택시"), ("경기도", "안산시"),
        ],
        "color": "#DDA0DD",
        "market_type_default": "유동인구",
        "managers": ["김창규", "이현주"],
        "manager_default": "이현주",
    },
    "수도권4지점": {
        "regions": [],
        "districts": [],
        "extra": [
            ("서울특별시", "종로구"), ("서울특별시", "중구"), ("서울특별시", "용산구"),
            ("서울특별시", "마포구"), ("서울특별시", "서대문구"), ("서울특별시", "은평구"),
            ("서울특별시", "성북구"), ("서울특별시", "강북구"), ("서울특별시", "도봉구"),
            ("서울특별시", "노원구"), ("서울특별시", "중랑구"), ("서울특별시", "동대문구"),
            ("서울특별시", "광진구"), ("서울특별시", "성동구"),
            ("경기도", "고양시"), ("경기도", "파주시"), ("경기도", "양주시"),
            ("경기도", "의정부시"), ("경기도", "동두천시"),
        ],
        "color": "#F0E68C",
        "market_type_default": "유동인구",
        "managers": ["유병준", "이현주"],
        "manager_default": "유병준",
    },
    "중부영업지점": {
        "regions": ["대전광역시", "세종특별자치시", "충청남도", "충청북도"],
        "districts": [],
        "color": "#FFB347",
        "market_type_default": "성형·피부과",
        "managers": ["이준대"],
        "manager_default": "이준대",
    },
}

def assign_branch(region, district):
    """지역 + 구 기준으로 지점 자동 배정"""
    for branch, info in BRANCH_MAPPING.items():
        # 시도 전체 담당
        if region in info.get("regions", []):
            # 구 필터가 있으면 확인
            districts = info.get("districts", [])
            if not districts or district in districts:
                return branch, info
        # 특정 (시도, 구) 조합
        for r, d in info.get("extra", []):
            if region == r and district == d:
                return branch, info
    return None, None

# =============================================
# 메인 처리
# =============================================
print("=" * 55)
print("  약국 데이터 정리 + 신규 추가")
print("=" * 55)

# 1. 기존 게임 데이터 로드
print("\n[1] 기존 게임 데이터 로드...")
with open(DATA_FILE, "r", encoding="utf-8") as f:
    content = f.read()
match = re.search(r'const PHARMACY_DATA = (\[.*?\]);', content, re.DOTALL)
existing = json.loads(match.group(1))
print(f"  기존: {len(existing)}개")

# 2. 폐업 의심 약국 제거
print("\n[2] 폐업 의심 약국 제거...")
with open("update_report.json", "r", encoding="utf-8") as f:
    report = json.load(f)

closed_set = set()
for item in report["possibly_closed"]:
    key = f"{item['name']}|{item['address'][:30].replace(' ','')}"
    closed_set.add(key)

cleaned = []
removed_count = 0
for p in existing:
    key = f"{p['name']}|{p['address'][:30].replace(' ','')}"
    if key in closed_set:
        removed_count += 1
    else:
        cleaned.append(p)

print(f"  제거: {removed_count}개 (폐업 의심)")
print(f"  남은 약국: {len(cleaned)}개")

# 3. 신규 약국 지점 배정 및 추가
print("\n[3] 신규 약국 지점 배정 중...")
new_pharmacies = report["new_pharmacies"]

assigned = 0
skipped = 0
branch_counts = {}

new_added = []
for p in new_pharmacies:
    region = p.get("region", "")
    district = p.get("district", "")
    branch, info = assign_branch(region, district)

    if not branch:
        skipped += 1
        continue

    # 지점 정보 배정
    p["branch"] = branch
    p["color"] = info["color"]
    p["market_type"] = info["market_type_default"]
    p["manager"] = info["manager_default"]
    # _is_new 플래그 제거
    p.pop("_is_new", None)

    new_added.append(p)
    assigned += 1
    branch_counts[branch] = branch_counts.get(branch, 0) + 1

print(f"  배정 성공: {assigned}개")
print(f"  담당 지역 없음 (미추가): {skipped}개")
print()
print("  지점별 신규 추가:")
for branch, cnt in sorted(branch_counts.items(), key=lambda x: -x[1]):
    print(f"    {branch}: +{cnt}개")

# 4. 최종 데이터 합치기
final_data = cleaned + new_added
print(f"\n[4] 최종 약국 수: {len(final_data)}개")
print(f"     (기존 {len(cleaned)}개 + 신규 {len(new_added)}개)")

# 5. HTML 저장
print("\n[5] 게임 파일 저장...")
json_str = json.dumps(final_data, ensure_ascii=False, separators=(",", ":"))

# 상단 약국 수 표시도 업데이트
new_content = re.sub(
    r'const PHARMACY_DATA = \[.*?\];',
    f'const PHARMACY_DATA = {json_str};',
    content, flags=re.DOTALL
)
new_content = re.sub(
    r'총 [\d,]+개 약국',
    f'총 {len(final_data):,}개 약국',
    new_content
)

with open(DATA_FILE, "w", encoding="utf-8") as f:
    f.write(new_content)

print(f"  저장 완료: {DATA_FILE}")
print()
print("=" * 55)
print(f"  완료! 총 {len(final_data):,}개 약국")
print(f"  - 폐업 의심 {removed_count}개 제거")
print(f"  - 신규 {len(new_added)}개 추가")
print("=" * 55)
