import json
from collections import defaultdict

with open("update_report.json", "r", encoding="utf-8") as f:
    report = json.load(f)

# 현재 게임 파일에서 지점-지역/구 매핑 확인
import re, json as j2

with open("약국_영토점령_게임_v2.html", "r", encoding="utf-8") as f:
    content = f.read()
match = re.search(r'const PHARMACY_DATA = (\[.*?\]);', content, re.DOTALL)
existing = j2.loads(match.group(1))

# 지점별 담당 지역(시도 + 시군구) 파악
branch_regions = defaultdict(lambda: defaultdict(int))
for p in existing:
    branch = p.get("branch", "")
    region = p.get("region", "")
    district = p.get("district", "")
    if branch and region:
        branch_regions[branch][f"{region}|{district}"] += 1

print("=== 지점별 담당 지역(시도+구) ===")
for branch, regions in sorted(branch_regions.items()):
    top = sorted(regions.items(), key=lambda x: -x[1])[:8]
    region_list = ", ".join(f"{r.split('|')[1]}({r.split('|')[0][:2]})" for r, _ in top)
    print(f"\n  [{branch}]")
    print(f"    담당: {region_list}")
