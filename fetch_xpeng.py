#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_xpeng.py —— 从小鹏官方「免费·专享」网页接口获取真实站点数据

数据来源（公开网页，无需登录）：
  https://static.xiaopeng.com/apps/charge-web/pc-free-stations.html
  ├─ POST /front/charge/station/search/queryMapCityLabeling   按城市取免费站
  └─ POST /front/charge/free/station/queryStationDtl          取站点详情（地址/价格/标签）

用法：
  python3 fetch_xpeng.py                 # 抓全国 44 城
  python3 fetch_xpeng.py --cities 杭州,上海
  python3 fetch_xpeng.py --with-detail   # 同时抓详情（含"停车优惠"标签），慢一些
"""
import argparse
import json
import os
import sys
import time
import urllib.request

GATEWAY = "https://chargegateway.xiaopeng.com"
HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://static.xiaopeng.com",
    "Referer": "https://static.xiaopeng.com/apps/charge-web/pc-free-stations.html",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
}

# 小鹏免费站已覆盖的城市（citycode 来自高德城市编码表）
CITIES = {
    "北京": "010", "上海": "021", "广州": "020", "深圳": "0755", "杭州": "0571", "成都": "028",
    "重庆": "023", "武汉": "027", "南京": "025", "苏州": "0512", "西安": "029", "长沙": "0731",
    "东莞": "0769", "佛山": "0757", "宁波": "0574", "青岛": "0532", "天津": "022", "郑州": "0371",
    "厦门": "0592", "合肥": "0551", "无锡": "0510", "温州": "0577", "昆明": "0871", "福州": "0591",
    "济南": "0531", "南宁": "0771", "南昌": "0791", "嘉兴": "0573", "台州": "0576", "金华": "0579",
    "中山": "0760", "惠州": "0752", "珠海": "0756", "汕头": "0754", "常州": "0519", "海口": "0898",
    "石家庄": "0311", "徐州": "0516", "潍坊": "0536", "保定": "0312", "肇庆": "0758", "泉州": "0595",
    "江门": "0750", "黄石": "0714",
}

# 城市中心坐标（用于地图初始定位、以及「沿线」规划）
CITY_CENTER = {
    "北京": [116.4074, 39.9042], "上海": [121.4737, 31.2304], "广州": [113.2644, 23.1291],
    "深圳": [114.0579, 22.5431], "杭州": [120.1551, 30.2741], "成都": [104.0665, 30.5723],
    "重庆": [106.5516, 29.5630], "武汉": [114.3055, 30.5928], "南京": [118.7969, 32.0603],
    "苏州": [120.5853, 31.2989], "西安": [108.9398, 34.3416], "长沙": [112.9388, 28.2282],
    "东莞": [113.7518, 23.0207], "佛山": [113.1220, 23.0288], "宁波": [121.5503, 29.8746],
    "青岛": [120.3826, 36.0671], "天津": [117.1902, 39.1252], "郑州": [113.6254, 34.7466],
    "厦门": [118.0894, 24.4798], "合肥": [117.2272, 31.8206], "无锡": [120.3119, 31.4912],
    "温州": [120.6994, 27.9944], "昆明": [102.8329, 24.8801], "福州": [119.2965, 26.0745],
    "济南": [117.1201, 36.6512], "南宁": [108.3665, 22.8170], "南昌": [115.8582, 28.6829],
    "嘉兴": [120.7555, 30.7461], "台州": [121.4286, 28.6564], "金华": [119.6474, 29.0791],
    "中山": [113.3824, 22.5211], "惠州": [114.4162, 23.1115], "珠海": [113.5767, 22.2707],
    "汕头": [116.6819, 23.3541], "常州": [119.9741, 31.8112], "海口": [110.3312, 20.0311],
    "石家庄": [114.5149, 38.0428], "徐州": [117.1848, 34.2618], "潍坊": [119.1071, 36.7093],
    "保定": [115.4646, 38.8739], "肇庆": [112.4653, 23.0472], "泉州": [118.5895, 24.8741],
    "江门": [113.0819, 22.5789], "黄石": [115.0389, 30.1997],
}


def post(path, body, retry=2):
    for i in range(retry + 1):
        try:
            req = urllib.request.Request(GATEWAY + path, data=json.dumps(body).encode(), headers=HEADERS)
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode())
        except Exception:
            if i == retry:
                raise
            time.sleep(1.2)


def fetch_city(city, code):
    r = post("/front/charge/station/search/queryMapCityLabeling",
             {"source": 2, "cityCode": code, "filterCriteriaCodeList": ["freeCharging"]})
    return ((r.get("data") or {}).get("result")) or []


def fetch_detail(station_id):
    r = post("/front/charge/free/station/queryStationDtl", {"source": 2, "stationId": str(station_id)})
    return r.get("data") or {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cities", help="逗号分隔，如 杭州,上海；默认全部")
    ap.add_argument("--with-detail", action="store_true", help="抓详情（地址/价格/停车优惠标签）")
    ap.add_argument("--out", default="data/stations.json")
    ap.add_argument("--sleep", type=float, default=0.35)
    ap.add_argument("--detail-dir", default="data/detail_cache", help="详情分片缓存目录（支持断点续抓）")
    a = ap.parse_args()

    want = CITIES if not a.cities else {c: CITIES[c] for c in a.cities.split(",") if c in CITIES}
    if not want:
        sys.exit("城市名不在内置列表里：" + a.cities)

    list_cache = "data/city_list_cache.json"
    allpts, seen = [], set()
    if not a.cities and os.path.exists(list_cache):
        with open(list_cache, encoding="utf-8") as f:
            allpts = json.load(f)
        seen = set(p["id"] for p in allpts)
        want = {}
        print(f"复用列表缓存：{len(allpts)} 个站（删除 {list_cache} 可强制重抓）", flush=True)
    for i, (city, code) in enumerate(want.items(), 1):
        try:
            rows = fetch_city(city, code)
        except Exception as e:
            print(f"[{i}/{len(want)}] {city} 失败：{e}")
            continue
        new = 0
        for s in rows:
            sid = str(s.get("stationId"))
            if sid in seen:
                continue
            seen.add(sid)
            # operationMode: 1=小鹏自营/直连, 3=第三方合作
            allpts.append({
                "id": sid,
                "name": s.get("stationName", ""),
                "lng": float(s.get("longitude") or 0),
                "lat": float(s.get("latitude") or 0),
                "city": city,
                "mode": int(s.get("operationMode") or 0),
                "type": "free" if int(s.get("operationMode") or 0) == 1 else "third",
                "dc": int(s.get("dcNum") or 0),
                "ac": int(s.get("acNum") or 0),
                "s4": int(s.get("s4Num") or 0),
                "xpOwner": bool(s.get("showXpOwner")),
            })
            new += 1
        print(f"[{i}/{len(want)}] {city:4} {len(rows):4} 条（新增 {new}）")
        time.sleep(a.sleep)

    allpts = [p for p in allpts if p["lng"] and p["lat"]]
    if not a.cities:
        with open(list_cache, "w", encoding="utf-8") as f:
            json.dump(allpts, f, ensure_ascii=False)
    print(f"\n合计 {len(allpts)} 个站点，{len(set(p['city'] for p in allpts))} 个城市")

    if a.with_detail:
        import glob
        os.makedirs(a.detail_dir, exist_ok=True)
        print("抓取详情（地址 / 价格 / 停车优惠），支持断点续抓…", flush=True)
        todo = [p for p in allpts if not os.path.exists(os.path.join(a.detail_dir, p["id"] + ".json"))]
        print(f"  已有缓存 {len(allpts)-len(todo)} 个，待抓 {len(todo)} 个", flush=True)
        for i, p in enumerate(todo, 1):
            try:
                d = fetch_detail(p["id"])
                rec = {
                    "park": "停车优惠" in (d.get("labels") or []),
                    "addr": d.get("stationAddr") or "",
                    "oper": d.get("operName") or "",
                    "price": f"{d.get('chargeAmt','')}+{d.get('serviceAmt','')}",
                    "freeNums": d.get("freeNums") or 0,
                    "labels": d.get("labels") or [],
                }
            except Exception as e:
                rec = {"park": False, "addr": "", "oper": "", "price": "", "freeNums": 0,
                       "labels": [], "error": str(e)[:80]}
            # 每个站单独落盘，中断不丢
            with open(os.path.join(a.detail_dir, p["id"] + ".json"), "w", encoding="utf-8") as fh:
                json.dump(rec, fh, ensure_ascii=False)
            if i % 25 == 0:
                print(f"  {i}/{len(todo)}", flush=True)
            time.sleep(a.sleep)

        # 汇总缓存
        for p in allpts:
            fp = os.path.join(a.detail_dir, p["id"] + ".json")
            if os.path.exists(fp):
                p.update(json.load(open(fp, encoding="utf-8")))

    cities_json = [{"name": c, "code": CITIES[c], "center": CITY_CENTER.get(c, [0, 0]), "zoom": 11}
                   for c in want if CITY_CENTER.get(c)]
    out = {"cities": cities_json, "points": allpts, "source": "小鹏官方 pc-free-stations",
           "fetchedAt": time.strftime("%Y-%m-%d %H:%M")}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print("已写入", a.out)


if __name__ == "__main__":
    main()
