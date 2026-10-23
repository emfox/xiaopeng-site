#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
charge_map.py —— 小鹏充电站三层查看地图生成器

三个层级，一个页面搞定：
  ① 附近    —— 以「我的位置」为圆心，按 3 / 5 / 10 / 20 km 圈层筛
  ② 全城    —— 按城市 + 区县 + 权益类型筛
  ③ 沿线    —— 输入起点/终点（如 杭州→上海），自动按路线里程挑停靠站，一键发高德导航

使用：
  python3 charge_map.py                          # 用 data/demo_stations.json 生成 out/charge_map.html
  python3 charge_map.py --data 我的站点.json --out out/charge_map.html
"""
import argparse
import json
import os
import urllib.parse

TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template.html")


def haversine_km(a, b):
    import math
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, [a[1], a[0], b[1], b[0]])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def build(data, key, data_file="data.json", inline=None):
    """渲染页面模板。

    data_file : 前端 fetch 的数据文件名（与 html 同目录）
    inline    : 若要生成「单文件版」，传入数据对象，会内联成 file:// 兜底副本
    """
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        tpl = f.read()
    return (tpl
            .replace("__AMAP_JS__", f"https://webapi.amap.com/maps?v=2.0&key={key}")
            .replace("__DATA_FILE__", data_file)
            .replace("__INLINE_DATA__",
                     json.dumps(inline, ensure_ascii=False, separators=(",", ":")) if inline else "null"))


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--data", default=os.path.join(here, "data", "demo_stations.json"))
    ap.add_argument("--out", default=os.path.join(here, "out", "charge_map.html"))
    ap.add_argument("--csv", help="站点 CSV（中文表头），与 --data 二选一；城市中心取 --data 里的 cities")
    ap.add_argument("--routes", nargs="*", default=[], help="路线 json 文件（get_route.py 产出），可多个")
    ap.add_argument("--amap-key", default=os.environ.get("AMAP_JS_KEY", "2f282f369e388ef01bae260cbc35edce"))
    ap.add_argument("--data-out", default="data.json",
                    help="数据文件名（与 --out 同目录），默认 data.json")
    ap.add_argument("--single-file", action="store_true",
                    help="生成单文件版：数据内联进 html，双击 file:// 也能用（体积大）")
    a = ap.parse_args()

    with open(a.data, encoding="utf-8") as f:
        data = json.load(f)

    if a.csv:
        import csv as _csv
        rows = list(_csv.DictReader(open(a.csv, encoding="utf-8-sig")))
        data["points"] = []
        for r in rows:
            try:
                lng, lat = float(r["经度"]), float(r["纬度"])
            except (KeyError, ValueError):
                continue
            data["points"].append({
                "name": (r.get("站点名称") or "").strip(),
                "lng": lng, "lat": lat,
                "type": "free" if ("自营" in (r.get("权益类型") or "") or "免费" in (r.get("权益类型") or "")) else "third",
                "park": (r.get("停车优惠") or "").strip() in ("是", "有", "1", "true", "免费"),
                "guns": (r.get("桩数") or "").strip(),
                "power": (r.get("功率") or "").strip(),
                "price": (r.get("价格") or "").strip(),
                "addr": (r.get("地址") or "").strip(),
            })
    # 每个站归属最近的城市，前端「全城」层直接用
    for p in data["points"]:
        best = min(data["cities"], key=lambda c: haversine_km(c["center"], [p["lng"], p["lat"]]))
        p["city"] = best["name"]

    # 合并真实路线
    routes = {}
    for rf in a.routes:
        r = json.load(open(rf, encoding="utf-8"))
        routes[r["label"]] = r
    data["routes"] = routes

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)

    # 数据单独落盘，和 html 放同一目录，页面用 fetch 读
    data_json_path = os.path.join(os.path.dirname(os.path.abspath(a.out)),
                                  os.path.basename(a.data_out))
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    with open(data_json_path, "w", encoding="utf-8") as f:
        f.write(payload)

    html = build(data, a.amap_key,
                 data_file=os.path.basename(a.data_out),
                 inline=(data if a.single_file else None))
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(html)

    free = sum(1 for p in data["points"] if p["type"] == "free")
    print(f"已生成 {a.out}")
    print(f"  数据 {data_json_path}（{len(payload)/1024:.0f} KB，可单独编辑）")
    print(f"  页面 {len(html)/1024:.0f} KB{'（单文件版，含内联数据）' if a.single_file else '（不含数据）'}")
    print(f"  站点 {len(data['points'])} 个（自营/免费 {free}，三方 {len(data['points'])-free}）")
    print(f"  城市 {', '.join(c['name'] for c in data['cities'][:8])}{'…' if len(data['cities'])>8 else ''}")
    if routes:
        desc = "、".join("%s(%skm)" % (k, v.get("distanceKm", "?")) for k, v in routes.items())
        print("  路线 " + desc)


if __name__ == "__main__":
    main()
