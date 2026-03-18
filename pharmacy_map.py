
import pandas as pd
import folium
from folium.plugins import MarkerCluster, HeatMap
from pyproj import Transformer
import warnings
warnings.filterwarnings('ignore')

# ─── 데이터 로드 ───
df = pd.read_csv('fulldata_01_01_06_P_약국_영업중.csv', encoding='utf-8-sig', low_memory=False)
df['_주소'] = df['소재지전체주소'].fillna('') + ' ' + df['도로명전체주소'].fillna('')

# ─── EPSG5174 → WGS84 변환 ───
transformer = Transformer.from_crs("epsg:5174", "epsg:4326", always_xy=True)

def to_wgs84(x, y):
    try:
        lon, lat = transformer.transform(float(x), float(y))
        # 한국 범위 검증
        if 33 < lat < 39 and 124 < lon < 132:
            return lat, lon
    except:
        pass
    return None, None

df['lat'], df['lon'] = zip(*df.apply(
    lambda r: to_wgs84(r['좌표정보x(epsg5174)'], r['좌표정보y(epsg5174)']), axis=1))
df = df.dropna(subset=['lat', 'lon'])
print(f'좌표 유효 약국: {len(df):,}개')

# ─── 상권 키워드 정의 (pharmacy_zone_filter.py와 동일) ───
tourist_kw = [
    '서울특별시 중구 명동', '서울특별시 용산구 이태원', '서울특별시 종로구 인사동',
    '서울특별시 종로구 삼청동', '서울특별시 종로구 북촌', '서울특별시 종로구 관훈동',
    '서울특별시 마포구 서교동', '서울특별시 마포구 상수동', '서울특별시 중구 광희동',
    '서울특별시 중구 을지로', '서울특별시 중구 남대문로', '서울특별시 용산구 한남동',
    '부산광역시 해운대구', '부산광역시 중구 광복동', '부산광역시 중구 남포동',
    '부산광역시 중구 보수동',
    '제주특별자치도 제주시 연동', '제주특별자치도 제주시 노형동', '제주특별자치도 서귀포시',
    '경상북도 경주시 황남동', '경상북도 경주시 보문동',
    # 전주 (2024.1.18 전북특별자치도 출범 → 행정구역명 변경)
    '전북특별자치도 전주시 완산구 교동', '전북특별자치도 전주시 완산구 풍남동',
    # 인천 (차이나타운은 행정명 아님 → 실제 법정동 사용)
    '인천광역시 중구 북성동', '인천광역시 중구 신포동',
]
hightraffic_kw = [
    '서울특별시 강남구 역삼동', '서울특별시 강남구 논현동',
    '서울특별시 마포구 합정동', '서울특별시 마포구 망원동',
    '서울특별시 서대문구 신촌동', '서울특별시 서대문구 창천동',
    '서울특별시 광진구 화양동', '서울특별시 광진구 구의동',
    '서울특별시 관악구 신림동', '서울특별시 동작구 노량진동',
    '서울특별시 종로구 혜화동', '서울특별시 종로구 명륜동',
    '서울특별시 송파구 잠실동', '서울특별시 영등포구 영등포동',
    '서울특별시 동대문구 회기동', '서울특별시 성북구 안암동',
    '경기도 수원시 영통구', '경기도 수원시 팔달구 인계동',
    '경기도 성남시 분당구 서현동', '경기도 고양시 일산동구',
    '경기도 안양시 만안구', '경기도 부천시 원미구',
    '인천광역시 부평구 부평동',
    '대전광역시 서구 둔산동',
    # 광주 (상무지구는 행정명 아님 → 해당 법정동 직접 사용)
    '광주광역시 동구 충장로', '광주광역시 동구 충장동',
    '광주광역시 서구 치평동', '광주광역시 서구 쌍촌동',
    # 대구
    '대구광역시 중구 동성로',
    # 부산 (서면은 통칭, 법정동 아님 → 부전동/범천동으로 교체)
    '부산광역시 부산진구 부전동', '부산광역시 부산진구 범천동',
    '울산광역시 남구 삼산동',
]
medical_kw = [
    '서울특별시 강남구 압구정동', '서울특별시 강남구 청담동',
    '서울특별시 강남구 신사동', '서울특별시 강남구 역삼동',
    '서울특별시 강남구 논현동', '서울특별시 서초구 방배동',
    '서울특별시 서초구 반포동', '서울특별시 강남구 대치동',
    '서울특별시 종로구 종로3가',  # 종로3(오탈자) → 종로3가로 수정
    '서울특별시 중구 을지로',
    '부산광역시 부산진구 부전동', '부산광역시 부산진구 전포동',
    '대구광역시 중구 동성로', '대구광역시 수성구 범어동',
    '광주광역시 남구 봉선동',
    '대전광역시 서구 둔산동',
    '제주특별자치도 제주시 연동',
]

def mask_kw(df, kws):
    m = pd.Series(False, index=df.index)
    for kw in kws:
        m |= df['_주소'].str.contains(kw, na=False)
    return m

m_t = mask_kw(df, tourist_kw)
m_h = mask_kw(df, hightraffic_kw)
m_m = mask_kw(df, medical_kw)

# 우선순위: 성형·피부 > 관광 > 유동 (복수 해당 시 최우선 1개만)
def assign_zone(row_mask_t, row_mask_h, row_mask_m):
    zones = []
    if row_mask_m: zones.append('성형·피부과')
    if row_mask_t: zones.append('외국인관광')
    if row_mask_h: zones.append('유동인구')
    return zones[0] if zones else None

df['zone'] = [assign_zone(t,h,m) for t,h,m in zip(m_t, m_h, m_m)]
df_map = df[df['zone'].notna()].copy()
print(f'지도 표시 약국: {len(df_map):,}개')
print(df_map['zone'].value_counts())

# ─── 색상 및 아이콘 매핑 ───
zone_style = {
    '외국인관광':  {'color': '#E84040', 'icon': 'globe',        'folium_color': 'red'},
    '유동인구':    {'color': '#4AABDB', 'icon': 'users',         'folium_color': 'blue'},
    '성형·피부과': {'color': '#8E3DFF', 'icon': 'heart',         'folium_color': 'purple'},
}

# ─── Folium 지도 생성 ───
m = folium.Map(
    location=[36.5, 127.8],
    zoom_start=7,
    tiles='CartoDB positron',
    attr='CartoDB'
)

# 레이어 그룹
layers = {z: folium.FeatureGroup(name=f'{z} 약국', show=True) for z in zone_style}

for _, row in df_map.iterrows():
    z = row['zone']
    style = zone_style[z]
    name = str(row.get('사업장명', '약국'))
    addr = str(row.get('도로명전체주소', row.get('소재지전체주소', '')))
    tel  = str(row.get('소재지전화', '-'))

    popup_html = f"""
    <div style='font-family:Malgun Gothic,sans-serif;min-width:200px'>
      <b style='color:{style["color"]};font-size:13px'>{name}</b><br>
      <span style='color:#555;font-size:11px'>{z}</span><hr style='margin:4px 0'>
      📍 {addr}<br>📞 {tel}
    </div>"""

    folium.CircleMarker(
        location=[row['lat'], row['lon']],
        radius=6,
        color=style['color'],
        fill=True,
        fill_color=style['color'],
        fill_opacity=0.75,
        weight=1.5,
        popup=folium.Popup(popup_html, max_width=280),
        tooltip=name,
    ).add_to(layers[z])

for layer in layers.values():
    layer.add_to(m)

# 레이어 컨트롤
folium.LayerControl(collapsed=False).add_to(m)

# 히트맵 레이어 (밀도 표시)
heat_data = [[r['lat'], r['lon']] for _, r in df_map.iterrows()]
HeatMap(heat_data, radius=14, blur=10, min_opacity=0.3,
        name='밀도 히트맵', show=False).add_to(m)

# ─── 범례 HTML ───
legend_html = """
<div style='position:fixed;bottom:30px;left:30px;z-index:9999;
     background:white;padding:14px 18px;border-radius:10px;
     box-shadow:0 2px 12px rgba(0,0,0,0.18);font-family:Malgun Gothic,sans-serif;
     border-left:5px solid #333'>
  <b style='font-size:13px;color:#1A1F5E'>📍 상권 유형별 약국</b><br><br>
  <span style='color:#E84040'>●</span> <b>외국인 관광객 상권</b> ({t}개)<br>
  <span style='color:#4AABDB'>●</span> <b>유동인구 많은 상권</b> ({h}개)<br>
  <span style='color:#8E3DFF'>●</span> <b>성형·피부과 집중 상권</b> ({m}개)<br><br>
  <small style='color:#888'>※ 레이어 컨트롤로 개별 ON/OFF 가능<br>팝업 클릭 시 상세 정보 표시</small>
</div>
""".format(
    t=len(df_map[df_map['zone']=='외국인관광']),
    h=len(df_map[df_map['zone']=='유동인구']),
    m=len(df_map[df_map['zone']=='성형·피부과']),
)
m.get_root().html.add_child(folium.Element(legend_html))

# 페이지 타이틀
title_html = """
<div style='position:fixed;top:15px;left:50%;transform:translateX(-50%);
     z-index:9999;background:white;padding:10px 24px;border-radius:20px;
     box-shadow:0 2px 10px rgba(0,0,0,0.15);font-family:Malgun Gothic,sans-serif'>
  <b style='font-size:15px;color:#1A1F5E'>🗺️ 영업 전략 약국 지도 — 상권 유형별</b>
</div>"""
m.get_root().html.add_child(folium.Element(title_html))

m.save('약국_상권별_지도.html')
print('\n저장 완료: 약국_상권별_지도.html')
