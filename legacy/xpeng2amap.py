#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xpeng2amap —— 把「小鹏充电站清单」变成「高德地图上能用的图层」

一条命令产出 4 种交付物：
  *.xlsx   全量站点台账（可直接给高德「收藏夹批量导入」用）
  *.html   离线高德地图页面（高德底图 + 按权益分类的站点标记 + 续航圈 + 路线）
  *.kml    给奥维/Google Earth/其他工具通用的交换格式
  route.txt 高德 App 直达链接（带途经点的一键导航，最实用的那个）

用法：
  python3 xpeng2amap.py --input stations.csv --center 121.4737,31.2304 --range 150
  python3 xpeng2amap.py --input stations.csv --self-test     # 用内置演示数据
"""
import argparse
import csv
import json
import math
import os
import re
import sys
import urllib.parse

# ---------------------------------------------------------------- 数据模型
FIELDS = {
    # 字段名 : (中文列名, 同义词)
    "name":   ("站点名称", ["name", "名称", "站点", "站名", "title"]),
    "lng":    ("经度",   ["lng", "lon", "longitude", "经度"]),
    "lat":    ("纬度",   ["lat", "latitude", "纬度"]),
    "type":   ("权益类型", ["type", "类型", "权益", "是否免费"]),
    "park":   ("停车优惠", ["park", "停车", "停车优惠"]),
    "guns":   ("桩数",   ["guns", "桩数", "枪数", "充电桩数量"]),
    "power":  ("功率",   ["power", "功率", "最大功率"]),
    "price":  ("价格",   ["price", "价格", "单价", "电价"]),
    "addr":   ("地址",   ["addr", "address", "地址"]),
    "status": ("状态",   ["status", "状态", "是否可用"]),
}

TRUE_WORDS = {"1", "true", "yes", "y", "是", "有", "免费", "自营", "小鹏自营", "ok", "✓"}
FREE_WORDS = {"free", "自营", "免费", "小鹏自营", "小鹏", "self", "xpeng"}


def norm_bool(v):
    if isinstance(v, bool):
        return v
    s = str(v or "").strip().lower()
    return s in TRUE_WORDS or s.startswith("是") or "免费" in s or "自营" in s


def norm_type(v):
    s = str(v or "").strip().lower()
    return "free" if (s in FREE_WORDS or "自营" in s or "免费" in s) else "third"


def pick(row, key):
    """在原始行里找该字段（兼容中英文表头、大小写、空格）"""
    cn, aliases = FIELDS[key]
    cands = [cn] + aliases
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for c in cands:
        if c.lower() in lowered and str(lowered[c.lower()]).strip() != "":
            return lowered[c.lower()]
    return ""


def load_rows(path):
    """支持 .csv / .json / .xlsx。xlsx 里若有多列经纬度，取第一个非空的。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".json",):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else data.get("points", [])
    if ext in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        head = [str(h or "").strip() for h in rows[0]]
        return [dict(zip(head, r)) for r in rows[1:]]
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def to_points(rows):
    pts, bad = [], 0
    for r in rows:
        try:
            lng = float(str(pick(r, "lng")).split(",")[0])
            lat = float(str(pick(r, "lat")).split(",")[0])
        except ValueError:
            bad += 1
            continue
        name = str(pick(r, "name") or f"未命名站点 {len(pts)+1}").strip()
        pts.append({
            "name": name,
            "lng": round(lng, 6),
            "lat": round(lat, 6),
            "type": norm_type(pick(r, "type")),
            "park": norm_bool(pick(r, "park")),
            "guns": str(pick(r, "guns") or ""),
            "power": str(pick(r, "power") or ""),
            "price": str(pick(r, "price") or ""),
            "addr": str(pick(r, "addr") or ""),
            "status": str(pick(r, "status") or ""),
        })
    return pts, bad


# ---------------------------------------------------------------- 地理工具
def haversine_km(a, b):
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, [a[1], a[0], b[1], b[0]])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def dist_to_segment_km(p, a, b):
    """点到线段的近似距离（小范围内用平面近似）"""
    kx = 111.0 * math.cos(math.radians(p[1]))
    def xy(q):
        return ((q[0] - a[0]) * kx, (q[1] - a[1]) * 111.0)
    px, py = xy(p)
    bx, by = xy(b)
    L2 = bx * bx + by * by
    if L2 == 0:
        return math.hypot(px, py)
    t = max(0.0, min(1.0, (px * bx + py * by) / L2))
    return math.hypot(px - t * bx, py - t * by)


# ---------------------------------------------------------------- 高德 App 链接
def amap_route_link(start, end, vias, sname="我的位置", dname="目的地"):
    """生成能在手机高德 App 里直接唤起「多途经点导航」的 URI"""
    q = {
        "slon": f"{start[0]:.6f}", "slat": f"{start[1]:.6f}", "sname": sname,
        "dlon": f"{end[0]:.6f}", "dlat": f"{end[1]:.6f}", "dname": dname,
        "t": "0", "sourceApplication": "xpeng2amap",
    }
    if vias:
        q["vian"] = str(len(vias))
        q["vialons"] = "|".join(f"{v['lng']:.6f}" for v in vias)
        q["vialats"] = "|".join(f"{v['lat']:.6f}" for v in vias)
        q["vianames"] = "|".join(safe_name(v["name"]) for v in vias)
    return "amapuri://route/plan/?" + urllib.parse.urlencode(q)


def safe_name(s, limit=16):
    """高德对名称里的特殊字符敏感，做一次清洗"""
    s = re.sub(r"[|&?#\n\r\t]", "·", str(s)).strip()
    return s[:limit]


def amap_marker_link(p):
    return ("https://uri.amap.com/marker?position=%s,%s&name=%s&src=xpeng2amap&coordinate=gaode&callnative=1"
            % (p["lng"], p["lat"], urllib.parse.quote(safe_name(p["name"], 40))))


# ---------------------------------------------------------------- 导出：Excel
def export_xlsx(points, center, range_km, out):
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "站点台账"
    head = ["站点名称", "经度", "纬度", "权益类型", "停车优惠", "桩数", "功率", "价格", "地址", "距中心(km)", "高德链接"]
    ws.append(head)
    for i, c in enumerate(ws[1], 1):
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F2937")
        c.alignment = Alignment(horizontal="center")
    for p in points:
        d = haversine_km(center, (p["lng"], p["lat"]))
        ws.append([p["name"], p["lng"], p["lat"], "自营/免费" if p["type"] == "free" else "三方合作",
                   "是" if p["park"] else "否", p["guns"], p["power"], p["price"], p["addr"],
                   round(d, 2), amap_marker_link(p)])
    widths = [38, 11, 10, 12, 10, 8, 10, 12, 44, 12, 40]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    # 第二个 sheet：只保留自营/免费，方便直接导入高德收藏夹
    ws2 = wb.create_sheet("收藏夹导入用")
    ws2.append(["名称", "地址", "经度", "纬度", "备注"])
    for p in points:
        if p["type"] == "free":
            ws2.append([p["name"], p["addr"], p["lng"], p["lat"],
                        ("停车优惠；" if p["park"] else "") + f"{p['guns']}桩 {p['power']} {p['price']}".strip()])
    wb.save(out)


# ---------------------------------------------------------------- 导出：KML
def export_kml(points, out):
    def esc(s):
        return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    styles = {
        "free": '<Style id="free"><IconStyle><color>ff78b500</color><scale>1.1</scale>'
                '<Icon><href>http://maps.google.com/mapfiles/kml/paddle/grn-circle.png</href></Icon></IconStyle></Style>',
        "third": '<Style id="third"><IconStyle><color>ffff7e3d</color><scale>1.0</scale>'
                 '<Icon><href>http://maps.google.com/mapfiles/kml/paddle/blu-circle.png</href></Icon></IconStyle></Style>',
    }
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
             "<name>小鹏充电站</name>"]
    parts += list(styles.values())
    for tag, label in (("free", "小鹏自营 / 免费权益"), ("third", "第三方合作站")):
        parts.append(f"<Folder><name>{label}</name>")
        for p in (x for x in points if x["type"] == tag):
            desc = (f"权益：{label}<br/>停车优惠：{'有' if p['park'] else '无'}<br/>"
                    f"桩数：{p['guns']}<br/>功率：{p['power']}<br/>价格：{p['price']}<br/>地址：{p['addr']}")
            parts.append(
                f'<Placemark><name>{esc(p["name"])}</name><styleUrl>#{tag}</styleUrl>'
                f'<description><![CDATA[{desc}]]></description>'
                f'<Point><coordinates>{p["lng"]},{p["lat"]},0</coordinates></Point></Placemark>')
        parts.append("</Folder>")
    parts.append("</Document></kml>")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))


# ---------------------------------------------------------------- 导出：HTML
TEMPLATE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>小鹏充电站 · 高德叠加地图</title>
<style>
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;background:#eef1f5;color:#1a1a1a}
#map{position:absolute;inset:0}
#panel{position:absolute;top:14px;left:14px;width:344px;max-height:calc(100% - 28px);background:rgba(255,255,255,.97);
  border-radius:14px;box-shadow:0 8px 30px rgba(0,0,0,.16);overflow:hidden;display:flex;flex-direction:column;z-index:20}
#panel header{padding:14px 16px 10px;border-bottom:1px solid #eef0f3}
#panel h1{font-size:15px;margin:0 0 2px}
#panel .sub{font-size:12px;color:#8a929e}
.toolbar{display:flex;gap:6px;padding:10px 12px;flex-wrap:wrap;border-bottom:1px solid #eef0f3}
.chip{border:1px solid #dfe3e9;background:#fff;border-radius:999px;padding:5px 10px;font-size:12px;cursor:pointer;
  display:flex;align-items:center;gap:5px;transition:.15s;user-select:none}
.chip[data-on="1"]{border-color:#111;background:#111;color:#fff}
.chip .dot{width:8px;height:8px;border-radius:50%}
#list{overflow:auto;flex:1}
.item{padding:10px 14px;border-bottom:1px solid #f2f4f7;cursor:pointer}
.item:hover{background:#f7f9fc}
.item .nm{font-size:13px;font-weight:600;line-height:1.35}
.item .meta{font-size:11.5px;color:#7d8694;margin-top:4px}
.badge{display:inline-block;font-size:10px;padding:1px 5px;border-radius:4px;margin-right:4px;color:#fff;vertical-align:1px}
.b-free{background:#00b578} .b-third{background:#3d7eff} .b-park{background:#ff8f1f}
#routeBox{padding:12px 14px;border-top:1px solid #eef0f3;font-size:12px;color:#4a5260;display:none;max-height:34%;overflow:auto}
#routeBox b{color:#111}
.legend{position:absolute;right:14px;bottom:14px;background:rgba(255,255,255,.95);border-radius:10px;padding:10px 12px;
  font-size:12px;box-shadow:0 4px 16px rgba(0,0,0,.12);z-index:15;line-height:1.9}
.pin{position:relative;width:24px;height:24px;border-radius:50% 50% 50% 4px;transform:rotate(-45deg);
  border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.32);display:flex;align-items:center;justify-content:center;cursor:pointer}
.pin span{transform:rotate(45deg);font-size:11px;color:#fff;font-weight:700;line-height:1}
.pin.free{background:#00b578} .pin.third{background:#3d7eff}
.pin .fee{position:absolute;right:-5px;top:-5px;width:9px;height:9px;border-radius:50%;background:#ff8f1f;border:1.5px solid #fff}
.iw{font-size:12.5px;line-height:1.65;min-width:200px}
.iw h3{font-size:13.5px;margin:0 0 5px}
.iw a{color:#3d7eff}
</style></head><body>
<div id="map"></div>
<div id="panel">
  <header><h1>小鹏充电站 · 高德底图</h1><div class="sub" id="stat">加载中…</div></header>
  <div class="toolbar" id="filters">
    <div class="chip" data-on="1" data-f="free"><i class="dot" style="background:#00b578"></i>自营/免费</div>
    <div class="chip" data-on="1" data-f="third"><i class="dot" style="background:#3d7eff"></i>三方合作</div>
    <div class="chip" data-on="0" data-f="park"><i class="dot" style="background:#ff8f1f"></i>仅停车优惠</div>
    <div class="chip" data-on="__REACH_ON__" data-f="reach">续航可达</div>
  </div>
  <div id="list"></div>
  <div id="routeBox"></div>
</div>
<div class="legend">
  <div><i style="display:inline-block;width:9px;height:9px;border-radius:50%;background:#00b578;margin-right:6px"></i>小鹏自营 / 免费权益</div>
  <div><i style="display:inline-block;width:9px;height:9px;border-radius:50%;background:#3d7eff;margin-right:6px"></i>第三方合作站</div>
  <div><i style="display:inline-block;width:9px;height:9px;border-radius:50%;background:#ff8f1f;margin-right:6px"></i>角标 = 有停车优惠</div>
</div>
<script src="__AMAP_JS__"></script>
<script>
const DATA = __DATA__;
const RANGE_KM = DATA.rangeKm || 0;
let map, markers = [], infoWindow, circle;
const state = { free: true, third: true, park: false, reach: true };

function km(p) {
  const R = 6371, r = Math.PI / 180;
  const [lng1, lat1, lng2, lat2] = [DATA.center[0], DATA.center[1], p.lng, p.lat];
  const dLat = (lat2 - lat1) * r, dLng = (lng2 - lng1) * r;
  const a = Math.sin(dLat/2)**2 + Math.cos(lat1*r)*Math.cos(lat2*r)*Math.sin(dLng/2)**2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

function pinHtml(p) {
  const cls = p.type === 'free' ? 'free' : 'third';
  const txt = p.type === 'free' ? '鹏' : '合';
  return `<div class="pin ${cls}" title="${p.name}"><span>${txt}</span>${p.park ? '<i class="fee"></i>' : ''}</div>`;
}

function infoHtml(p) {
  return `<div class="iw"><h3>${p.name}</h3>
    ${p.type === 'free' ? '<span class="badge b-free">自营/免费</span>' : '<span class="badge b-third">三方合作</span>'}
    ${p.park ? '<span class="badge b-park">停车优惠</span>' : ''}
    <div>桩数 ${p.guns || '-'} · ${p.power || '-'}</div>
    <div>价格 ${p.price || '-'}</div>
    <div>地址 ${p.addr || '-'}</div>
    <div>距离中心 ${p._d.toFixed(1)} km</div>
    <div style="margin-top:6px"><a href="https://uri.amap.com/marker?position=${p.lng},${p.lat}&name=${encodeURIComponent(p.name)}&coordinate=gaode" target="_blank">在高德打开</a></div>
  </div>`;
}

function openInfo(p, m) {
  if (!infoWindow) infoWindow = new AMap.InfoWindow({ offset: new AMap.Pixel(0, -26) });
  infoWindow.setContent(infoHtml(p));
  infoWindow.open(map, m.getPosition());
}

function currentList() {
  return DATA.points
    .filter(p => (p.type === 'free' ? state.free : state.third)
              && (!state.park || p.park)
              && (!state.reach || !RANGE_KM || p._d <= RANGE_KM))
    .sort((a, b) => a._d - b._d);
}

function render(list) {
  markers.forEach(m => m.setMap(null));
  markers = list.map(p => {
    const m = new AMap.Marker({
      position: [p.lng, p.lat], content: pinHtml(p), offset: new AMap.Pixel(-12, -24),
      zIndex: p.type === 'free' ? 120 : 110
    });
    m.on('click', () => openInfo(p, m));
    m.setMap(map);
    return m;
  });
  document.getElementById('stat').textContent =
    `显示 ${list.length} / ${DATA.points.length} 个站点` + (RANGE_KM ? ` · 续航 ${RANGE_KM} km` : '');
  document.getElementById('list').innerHTML = list.map((p, i) => `
    <div class="item" data-i="${i}">
      <div class="nm">${p.name}</div>
      <div class="meta">
        ${p.type === 'free' ? '<span class="badge b-free">自营</span>' : '<span class="badge b-third">三方</span>'}
        ${p.park ? '<span class="badge b-park">停车优惠</span>' : ''}
        ${p._d.toFixed(1)} km · ${p.guns || '-'} 桩 · ${p.price || ''}
      </div>
    </div>`).join('') || '<div style="padding:16px;color:#8a929e;font-size:12px">当前筛选条件下没有站点</div>';
  document.querySelectorAll('.item').forEach(el => el.onclick = () => {
    const p = list[+el.dataset.i];
    map.setZoomAndCenter(15, [p.lng, p.lat]);
    openInfo(p, markers[+el.dataset.i]);
  });
}

window.renderRoute = function (route) {
  if (!route || !route.polyline || !route.polyline.length) return;
  new AMap.Polyline({ map, path: route.polyline, strokeColor: '#1a1a1a', strokeWeight: 5,
                      strokeOpacity: .5, lineJoin: 'round', showDir: true }).setMap(map);
  const s = route.polyline[0], e = route.polyline[route.polyline.length - 1];
  const tag = (t, bg) => `<div style="background:${bg};color:#fff;padding:2px 7px;border-radius:5px;font-size:11px;font-weight:600">${t}</div>`;
  new AMap.Marker({ map, position: s, offset: new AMap.Pixel(-16,-30), content: tag('起点','#1a1a1a') });
  new AMap.Marker({ map, position: e, offset: new AMap.Pixel(-16,-30), content: tag('终点','#e0192a') });
  const box = document.getElementById('routeBox');
  box.style.display = 'block';
  const via = route.via || [];
  box.innerHTML = `<b>路线</b> ${(route.distanceKm||0).toFixed(0)} km · 沿线可停靠 <b>${via.length}</b> 个站点` +
    (via.length ? '<div style="margin-top:6px;line-height:1.9">' + via.map(v =>
      `<span class="badge b-free">+${Math.round(v.cumKm)}km</span>${v.name}${v.park ? ' <span class="badge b-park">停</span>' : ''}`
    ).join('<br>') + '</div>' : '') +
    `<div style="margin-top:8px;font-size:11.5px;color:#8a929e">路线为演示示意，可用于大致判断站点与路线的相对位置；导航请以高德实时规划为准。</div>`;
  if (via.length) {
    const w = route.polyline;
  }
};

window.initMap = function () {
  DATA.points.forEach(p => p._d = km(p));
  map = new AMap.Map('map', { zoom: DATA.zoom || 11, center: DATA.center, viewMode: '2D', showLabel: true });
  if (RANGE_KM) {
    circle = new AMap.Circle({
      map, center: DATA.center, radius: RANGE_KM * 1000,
      strokeColor: '#00b578', strokeWeight: 1.5, strokeOpacity: .55,
      fillColor: '#00b578', fillOpacity: .05, strokeStyle: 'dashed'
    });
  }
  if (DATA.route) renderRoute(DATA.route);
  render(currentList());
  document.querySelectorAll('#filters .chip').forEach(el => {
    el.onclick = () => {
      const f = el.dataset.f;
      state[f] = !state[f];
      el.dataset.on = state[f] ? '1' : '0';
      render(currentList());
    };
  });
  // 让页面把筛选后的站点列表暴露给自动化脚本（一键分发到手机）
  window.__viewport = () => ({ zoom: map.getZoom(), center: [map.getCenter().lng, map.getCenter().lat] });
};
initMap();
</script></body></html>"""


def export_html(points, center, zoom, range_km, route, out, amap_key=None):
    if not amap_key:
        amap_key = os.environ.get("AMAP_JS_KEY", "2f282f369e388ef01bae260cbc35edce")
    data = {
        "center": center, "zoom": zoom, "rangeKm": range_km,
        "points": [{k: p[k] for k in ("name", "lng", "lat", "type", "park", "guns", "power", "price", "addr")}
                   for p in points],
        "route": route,
    }
    html = (TEMPLATE
            .replace("__AMAP_JS__", f"https://webapi.amap.com/maps?v=2.0&key={amap_key}")
            .replace("__REACH_ON__", "1" if range_km else "0")
            .replace("__DATA__", json.dumps(data, ensure_ascii=False)))
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)


# ---------------------------------------------------------------- 路线相关
def plan_vias(points, polyline, max_stops, prefer_free=True, park_only=False, cum_km=None):
    """沿路线挑停靠点：把路线按里程切段，每段内挑一个最合适的站"""
    if not polyline:
        return []
    cums = cum_km or [0]
    total = cums[-1]
    cand = [p for p in points if (p["type"] == "free" or not prefer_free) and (p["park"] or not park_only)]
    chosen = []
    for k in range(1, max_stops + 1):
        lo, hi = total * (k - 1) / max_stops, total * k / max_stops
        best, best_score, best_cum = None, 1e9, 0
        for p in cand:
            if p in chosen:
                continue
            bestd, cum = 1e9, 0
            for i in range(len(polyline) - 1):
                d = dist_to_segment_km((p["lng"], p["lat"]), polyline[i], polyline[i + 1])
                if d < bestd:
                    bestd, cum = d, cums[i]
            if not (lo <= cum <= hi) or bestd > 8:   # 8km 以外的站不算顺路
                continue
            score = bestd + (0 if p["park"] else 1.5) + (0 if p["type"] == "free" else 6)
            if score < best_score:
                best, best_score, best_cum = p, score, cum
        if best:
            chosen.append(best)
            best["cumKm"] = best_cum
    return chosen


def demo():
    """内置演示数据：上海周边 20 个虚构站点，用来跑通全流程"""
    base = [
        ("小鹏超充·虹桥天地", 121.3178, 31.1952, "free", True, 12, "480kW", "1.45 元/度"),
        ("小鹏超充·徐汇滨江", 121.4562, 31.1836, "free", True, 8, "360kW", "1.39 元/度"),
        ("小鹏超充·张江人工智能岛", 121.6027, 31.2056, "free", True, 10, "480kW", "1.35 元/度"),
        ("小鹏超充·五角场", 121.5150, 31.3010, "free", False, 6, "250kW", "1.48 元/度"),
        ("小鹏超充·嘉定新城", 121.2600, 31.3800, "free", True, 8, "480kW", "1.32 元/度"),
        ("小鹏超充·松江大学城", 121.2200, 31.0350, "free", False, 6, "250kW", "1.30 元/度"),
        ("小鹏超充·浦东金桥", 121.5900, 31.2600, "free", True, 10, "360kW", "1.41 元/度"),
        ("小鹏超充·青浦奥莱", 121.1100, 31.1500, "free", True, 6, "250kW", "1.28 元/度"),
        ("特来电·人民广场", 121.4750, 31.2330, "third", True, 20, "120kW", "1.62 元/度"),
        ("星星充电·陆家嘴", 121.5050, 31.2400, "third", False, 16, "180kW", "1.78 元/度"),
        ("国网·世博园区", 121.4870, 31.1855, "third", True, 24, "100kW", "1.55 元/度"),
        ("云快充·中山公园", 121.4210, 31.2200, "third", False, 12, "120kW", "1.70 元/度"),
        ("小桔·虹桥枢纽", 121.3300, 31.1920, "third", True, 30, "120kW", "1.60 元/度"),
        ("万马·莘庄地铁站", 121.3900, 31.1120, "third", False, 10, "90kW", "1.45 元/度"),
    ]
    pts = []
    for n, lng, lat, t, pk, g, pw, pr in base:
        pts.append({"name": n + "站", "lng": lng, "lat": lat, "type": t, "park": pk,
                    "guns": str(g), "power": pw, "price": pr, "addr": "演示地址（虚构）", "status": "营业中"})
        # 每个站再派生 2 个周边站，模拟真实密度
        for j, (dx, dy) in enumerate([(0.055, 0.02), (-0.045, -0.03)]):
            pts.append({"name": f"{n.split('·')[0]}·{['北', '南'][j]}{j+1}号站", "lng": round(lng + dx, 5),
                        "lat": round(lat + dy, 5), "type": t, "park": (j == 0), "guns": str(6 + j * 2),
                        "power": pw, "price": pr, "addr": "演示地址（虚构）", "status": "营业中"})
    return pts


def main():
    ap = argparse.ArgumentParser(description="小鹏充电站 → 高德地图图层")
    ap.add_argument("--input", help="站点清单 csv / json / xlsx")
    ap.add_argument("--self-test", action="store_true", help="用内置演示数据跑一遍")
    ap.add_argument("--center", default="121.4737,31.2304", help="地图中心，lng,lat")
    ap.add_argument("--range", type=float, default=0, help="续航半径 km，0=不启用")
    ap.add_argument("--zoom", type=int, default=11)
    ap.add_argument("--route", help="路线 polyline 文件(json 数组或 'a,b;c,d;...')")
    ap.add_argument("--stops", type=int, default=3, help="路线自动挑几个停靠站")
    ap.add_argument("--outdir", default=".")
    a = ap.parse_args()

    center = [float(x) for x in a.center.split(",")]
    if a.self_test:
        points, bad = demo(), 0
    elif a.input:
        points, bad = to_points(load_rows(a.input))
    else:
        ap.error("需要 --input 或 --self-test")

    route = None
    if a.route:
        with open(a.route, encoding="utf-8") as f:
            raw = f.read().strip()
        polyline = json.loads(raw) if raw.startswith("[") else \
            [[float(p.split(",")[0]), float(p.split(",")[1])] for p in raw.split(";") if p.strip()]
        cums = [0.0]
        for i in range(1, len(polyline)):
            cums.append(cums[-1] + haversine_km(polyline[i - 1], polyline[i]))
        vias = plan_vias(points, polyline, a.stops, cum_km=cums)
        route = {"polyline": polyline, "distanceKm": cums[-1],
                 "via": [{k: v[k] for k in ("name", "lng", "lat", "park", "cumKm")} for v in vias]}

    os.makedirs(a.outdir, exist_ok=True)
    p = lambda n: os.path.join(a.outdir, n)
    export_xlsx(points, center, a.range, p("小鹏充电站台账.xlsx"))
    export_html(points, center, a.zoom, a.range, route, p("充电站地图.html"))
    export_kml(points, p("小鹏充电站.kml"))

    free = [x for x in points if x["type"] == "free"]
    lines = ["# 高德 App 直达链接（在手机浏览器打开，或生成二维码扫）", ""]
    for x in sorted(free, key=lambda y: haversine_km(center, (y["lng"], y["lat"])))[:12]:
        lines.append(f"{x['name']}  {amap_marker_link(x)}")
    if route:
        lines += ["", "# 带途经点的一键导航（高德 App 支持 vian 多途经点）",
                  amap_route_link(center, route["polyline"][-1], route["via"])]
    with open(p("高德链接.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"站点 {len(points)} 个（自营 {len(free)} / 三方 {len(points)-len(free)}），坐标非法跳过 {bad} 个")
    print(f"输出目录：{os.path.abspath(a.outdir)}")


if __name__ == "__main__":
    main()
