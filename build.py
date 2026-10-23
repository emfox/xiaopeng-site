#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build.py —— 把「按城市拆分的源数据」打包成「网页要的格式」

源数据（人工/脚本增量维护）        产物（dist/，不手工改）
  data/cities.json            ─┐
  data/stations/*.json        ─┼─►  dist/index.html
  data/routes/*.json          ─┘    dist/data.json      全量包（890 KB）
                                    dist/data.json.gz   全量包压缩（261 KB）
                                    dist/split/index.json      城市索引（首屏先加载）
                                    dist/split/<城市>.json.gz  按城市分包

用法：
  python3 build.py                 # 全量打包
  python3 build.py --check         # 只检查源数据完整性，不写文件
"""
import argparse
import gzip
import json
import os
import sys
from datetime import datetime

import store

ROOT = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(ROOT, "template.html")
DIST = os.path.join(ROOT, "dist")


def load_source():
    """读源数据，返回 {cities, points, routes}；站点已在 store 层去重"""
    cities = store.load_cities()
    if not cities:
        sys.exit("缺少 data/cities.json，先跑 migrate_source.py 或 fetch_xpeng.py")

    points = store.load_all()
    if not points:
        sys.exit("data/stations/ 下没有城市文件，先跑采集脚本")

    routes = store.load_routes()
    return cities, points, routes


def check(cities, points, routes):
    """检查源数据有没有明显问题"""
    problems = []

    city_names = {c["name"] for c in cities}
    for p in points:
        if p.get("city") not in city_names:
            problems.append(f"站点 {p.get('name')} 的城市 {p.get('city')} 不在 cities.json 里")
        if not p.get("lng") or not p.get("lat"):
            problems.append(f"站点 {p.get('name')} 缺坐标")

    for label, r in routes.items():
        if not r.get("polyline") or len(r["polyline"]) < 2:
            problems.append(f"路线 {label} 没有有效 polyline")

    return problems[:20]


def build_html(amap_key, data_file="data.json"):
    with open(TEMPLATE, encoding="utf-8") as f:
        tpl = f.read()
    return (tpl
            .replace("__AMAP_JS__", f"https://webapi.amap.com/maps?v=2.0&key={amap_key}")
            .replace("__DATA_FILE__", data_file)
            .replace("__INLINE_DATA__", "null"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DIST)
    ap.add_argument("--amap-key", default=os.environ.get("AMAP_JS_KEY", "2f282f369e388ef01bae260cbc35edce"))
    ap.add_argument("--check", action="store_true", help="只检查源数据，不写文件")
    ap.add_argument("--no-split", action="store_true", help="不生成按城市分包")
    a = ap.parse_args()

    cities, points, routes = load_source()

    problems = check(cities, points, routes)
    if problems:
        print("源数据检查发现问题：")
        for p in problems:
            print("  -", p)
    else:
        print("源数据检查通过")

    if a.check:
        print(f"\n城市 {len(cities)} · 站点 {len(points)} · 路线 {len(routes)}")
        return 0 if not problems else 1

    os.makedirs(a.out, exist_ok=True)

    # ---------- 全量包 ----------
    bundle = {
        "cities": cities,
        "points": points,
        "routes": routes,
        "builtAt": datetime.now().isoformat(timespec="seconds"),
    }
    payload = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    json_path = os.path.join(a.out, "data.json")
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(payload)

    gz_path = json_path + ".gz"
    with open(gz_path, "wb") as f:
        f.write(gzip.compress(payload.encode("utf-8"), 9))

    # ---------- 页面 ----------
    html = build_html(a.amap_key)
    html_path = os.path.join(a.out, "index.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print()
    print(f"  {html_path}   {len(html)/1024:.0f} KB")
    print(f"  {json_path}   {len(payload)/1024:.0f} KB")
    print(f"  {gz_path}   {os.path.getsize(gz_path)/1024:.0f} KB")

    # ---------- 按城市分包（首屏只加载当前城市） ----------
    if not a.no_split:
        split_dir = os.path.join(a.out, "split")
        os.makedirs(split_dir, exist_ok=True)

        by_city = {}
        for p in points:
            by_city.setdefault(p["city"], []).append(p)

        index = {"cities": cities, "routes": routes, "counts": {}}
        total_split = 0
        for city, arr in by_city.items():
            one = {"city": city, "points": arr}
            s = json.dumps(one, ensure_ascii=False, separators=(",", ":"))
            b = gzip.compress(s.encode("utf-8"), 9)
            with open(os.path.join(split_dir, f"{city}.json.gz"), "wb") as f:
                f.write(b)
            total_split += len(b)
            index["counts"][city] = len(arr)

        idx_s = json.dumps(index, ensure_ascii=False, separators=(",", ":"))
        with open(os.path.join(split_dir, "index.json"), "w", encoding="utf-8") as f:
            f.write(idx_s)

        print(f"  {split_dir}/   {len(by_city)} 个城市包，合计 {total_split/1024:.0f} KB"
              f"（单城平均 {total_split/1024/len(by_city):.0f} KB）")

    print()
    print(f"  合计 城市 {len(cities)} · 站点 {len(points)} · 路线 {len(routes)}")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
