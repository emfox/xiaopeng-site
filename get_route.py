#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
get_route.py —— 用高德网页版路线接口取真实驾车路线（含高速），免 key

接口：https://amap-pc-ssr.amap.com/ssr/api/getCarRoutePlan
输出：{"polyline": [[lng,lat],...], "distanceKm": 176.3, "durationMin": 151, "roads": [...]}

用法：
  python3 get_route.py --from 120.1551,30.2741 --to 121.4737,31.2304 --out data/route_hz_sh.json
  python3 get_route.py --from-city 杭州 --to-city 上海 --out data/route_hz_sh.json
"""
import argparse
import json
import os
import urllib.request

CITY_CENTER = {
    "北京": [116.4074, 39.9042], "上海": [121.4737, 31.2304], "广州": [113.2644, 23.1291],
    "深圳": [114.0579, 22.5431], "杭州": [120.1551, 30.2741], "成都": [104.0665, 30.5723],
    "重庆": [106.5516, 29.5630], "武汉": [114.3055, 30.5928], "南京": [118.7969, 32.0603],
    "苏州": [120.5853, 31.2989], "西安": [108.9398, 34.3416], "长沙": [112.9388, 28.2282],
    "宁波": [121.5503, 29.8746], "青岛": [120.3826, 36.0671], "天津": [117.1902, 39.1252],
    "厦门": [118.0894, 24.4798], "合肥": [117.2272, 31.8206], "温州": [120.6994, 27.9944],
    "福州": [119.2965, 26.0745], "济南": [117.1201, 36.6512], "嘉兴": [120.7555, 30.7461],
    "台州": [121.4286, 28.6564], "金华": [119.6474, 29.0791], "无锡": [120.3119, 31.4912],
    "郑州": [113.6254, 34.7466], "昆明": [102.8329, 24.8801], "南昌": [115.8582, 28.6829],
}


def get_route(a, b):
    url = ("https://amap-pc-ssr.amap.com/ssr/api/getCarRoutePlan"
           f"?fromX={a[0]}&fromY={a[1]}&toX={b[0]}&toY={b[1]}"
           "&originid=&start_poitype=&destinationid=&end_poitype=&policy2=10&dataTime=now")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
        "Referer": "https://ditu.amap.com/",
    })
    j = json.loads(urllib.request.urlopen(req, timeout=30).read())
    paths = j["data"]["route"]["paths"]
    if not paths:
        raise RuntimeError("没有返回路线")
    p = paths[0]
    pts, roads = [], []
    for road in p.get("roads", []):
        if road.get("road_name"):
            roads.append(road["road_name"])
        for st in road.get("steps", []):
            for xy in (st.get("polyline") or "").split(";"):
                if xy:
                    lng, lat = xy.split(",")[:2]
                    pts.append([round(float(lng), 6), round(float(lat), 6)])
    # 抽稀：相邻点太密（<60m）就跳过，减少前端负担
    keep = [pts[0]]
    for p2 in pts[1:]:
        dx = (p2[0] - keep[-1][0]) * 111 * 0.87
        dy = (p2[1] - keep[-1][1]) * 111
        if (dx * dx + dy * dy) ** 0.5 >= 0.06:
            keep.append(p2)
    if keep[-1] != pts[-1]:
        keep.append(pts[-1])
    return {
        "polyline": keep,
        "rawPoints": len(pts),
        "distanceKm": round(float(p["distance"]) / 1000, 1),
        "durationMin": round(float(p["duration"]) / 60),
        "roads": [r for i, r in enumerate(roads) if i == 0 or r != roads[i - 1]],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm")
    ap.add_argument("--to", dest="to")
    ap.add_argument("--from-city")
    ap.add_argument("--to-city")
    ap.add_argument("--out", default="data/route.json")
    a = ap.parse_args()

    if a.from_city:
        a.frm, a.to = CITY_CENTER[a.from_city], CITY_CENTER[a.to_city]
    if not a.frm or not a.to:
        ap.error("需要 --from/--to 坐标，或 --from-city/--to-city")
    f = [float(x) for x in (a.frm.split(",") if isinstance(a.frm, str) else a.frm)]
    t = [float(x) for x in (a.to.split(",") if isinstance(a.to, str) else a.to)]

    r = get_route(f, t)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(r, fh, ensure_ascii=False)
    print(f"{r['distanceKm']} km / 约 {r['durationMin']} 分钟，{len(r['polyline'])} 个点")
    print("主要道路:", " → ".join(r["roads"][:10]))
    print("已写入", a.out)


if __name__ == "__main__":
    main()
