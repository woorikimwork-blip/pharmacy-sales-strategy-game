import re

with open('약국_영토점령_게임_v2.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. CDN 주입
cdn_old = """    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.css"/>
    <script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js"></script>"""
cdn_new = """    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.css"/>
    <script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js"></script>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet.markercluster@1.5.3/dist/MarkerCluster.css"/>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css"/>
    <script src="https://cdn.jsdelivr.net/npm/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>"""

if cdn_old in content:
    content = content.replace(cdn_old, cdn_new)
    print("CDN 교체 성공")
else:
    print("CDN 교체 실패 (이미 적용되었을 수 있음)")

# 2. initMap 재작성
map_old = """// =================== MAP ===================
function initMap() {
    map = L.map('map', {
        center: [36.5, 127.8],
        zoom: 7,
        zoomControl: true,
        preferCanvas: true
    });

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '©CartoDB',
        subdomains: 'abcd',
        maxZoom: 19
    }).addTo(map);

    // Draw all pharmacy markers
    PHARMACY_DATA.forEach((pharm, idx) => {
        // lat/lng 없는 약국은 건너뜀
        if (!pharm.lat || !pharm.lng) {
            pharmacyMarkers.push(null);
            return;
        }
        const state = gameState.pharmacyStates[idx];
        const color = state ? state.color : getBaseColor(pharm.market_type);
        const opacity = state ? 0.95 : 0.65;
        const radius = state ? 9 : 6;
        const weight = state ? 3 : 1.5;

        const marker = L.circleMarker([pharm.lat, pharm.lng], {
            color: color,
            fillColor: color,
            fillOpacity: opacity,
            radius: radius,
            weight: weight
        });

        marker.pharmacyIdx = idx;
        marker.bindPopup(() => buildPopup(idx), { maxWidth: 260, className: 'game-popup' });
        marker.addTo(map);
        pharmacyMarkers.push(marker);
    });
}"""

map_new = """// =================== MAP ===================
let markerClusterGroup = null;

function initMap() {
    map = L.map('map', {
        center: [36.5, 127.8],
        zoom: 7,
        zoomControl: true,
        preferCanvas: false // CircleMarker 호환성을 위해 수정
    });

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '©CartoDB',
        subdomains: 'abcd',
        maxZoom: 19
    }).addTo(map);

    // MarkerCluster 초기화
    markerClusterGroup = L.markerClusterGroup({
        maxClusterRadius: 60,
        chunkedLoading: true,
        disableClusteringAtZoom: 15,
        spiderfyOnMaxZoom: true,
        showCoverageOnHover: false,
        iconCreateFunction: function(cluster) {
            const count = cluster.getChildCount();
            let size = 'small';
            if (count >= 100) size = 'large';
            else if (count >= 20) size = 'medium';
            const color = count >= 100 ? '#e94560' : count >= 20 ? '#f39c12' : '#4AABDB';
            return L.divIcon({
                html: `<div style="
                    background:${color};
                    color:#fff;
                    border-radius:50%;
                    width:${size==='large'?44:size==='medium'?36:28}px;
                    height:${size==='large'?44:size==='medium'?36:28}px;
                    display:flex;align-items:center;justify-content:center;
                    font-weight:900;font-size:${size==='large'?14:12}px;
                    border:2px solid rgba(255,255,255,0.4);
                    box-shadow:0 0 8px rgba(0,0,0,0.5);
                ">${count}</div>`,
                className: 'custom-cluster',
                iconSize: [size==='large'?44:size==='medium'?36:28, size==='large'?44:size==='medium'?36:28]
            });
        }
    });

    // Draw all pharmacy markers
    PHARMACY_DATA.forEach((pharm, idx) => {
        // lat/lng 없는 약국은 건너뜀
        if (!pharm.lat || !pharm.lng) {
            pharmacyMarkers.push(null);
            return;
        }
        const state = gameState.pharmacyStates[idx];
        const color = state ? state.color : getBaseColor(pharm.market_type);
        const opacity = state ? 0.95 : 0.65;
        const radius = state ? 9 : 6;
        const weight = state ? 3 : 1.5;

        const marker = L.circleMarker([pharm.lat, pharm.lng], {
            color: color,
            fillColor: color,
            fillOpacity: opacity,
            radius: radius,
            weight: weight
        });

        marker.pharmacyIdx = idx;
        marker.bindPopup(() => buildPopup(idx), { maxWidth: 260, className: 'game-popup' });
        
        pharmacyMarkers.push(marker);
        markerClusterGroup.addLayer(marker);
    });
    
    map.addLayer(markerClusterGroup);
}"""

if map_old in content:
    content = content.replace(map_old, map_new)
    print("initMap 교체 성공")
else:
    print("initMap 교체 실패 (이미 적용되었을 수 있음)")

# 3. applyVisibility 재작성
vis_old = """    if (show) {
        if (!map.hasLayer(m)) map.addLayer(m);
    } else {
        if (map.hasLayer(m)) map.removeLayer(m);
    }"""

vis_new = """    if (!markerClusterGroup) return;
    if (show) {
        if (!markerClusterGroup.hasLayer(m)) markerClusterGroup.addLayer(m);
    } else {
        if (markerClusterGroup.hasLayer(m)) markerClusterGroup.removeLayer(m);
    }"""

if vis_old in content:
    content = content.replace(vis_old, vis_new)
    print("applyVisibility 교체 성공")
else:
    print("applyVisibility 교체 실패 (이미 적용되었을 수 있음)")

with open('약국_영토점령_게임_v2.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("저장 완료")
