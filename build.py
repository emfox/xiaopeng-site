#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build.py —— 把「按城市拆分的源数据」打包成「网页要的格式」

源数据（人工/脚本增量维护）        产物（仓库根目录，不手工改、由本脚本生成）
  data/cities.json            ─┐
  data/stations/*.json        ─┼─►  index.html            页面
  data/routes/*.json          ─┘    data.json             全量包
                                    data.json.gz          全量包压缩（页面优先用它）
                                    split/index.json      城市索引（首屏先加载）
                                    split/<城市>.json.gz  按城市分包

产物是确定性的：内容没变就不重写文件，重跑不会产生 git diff。

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
PUBLISH = ROOT          # 直接输出到仓库根目录，Pages 从根目录发布


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_if_changed(path, data: bytes) -> bool:
    """内容一样就不写，避免 mtime 变动导致 git 上一堆假 diff。返回是否真的写了。"""
    try:
        with open(path, "rb") as f:
            if f.read() == data:
                return False
    except OSError:
        pass
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return True


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
    ap.add_argument("--out", default=PUBLISH, help="输出目录，默认仓库根目录")
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
    json_path = os.path.join(a.out, "data.json")
    gz_path = json_path + ".gz"

    # builtAt 只反映「数据真的变了」的时间。内容没变时沿用上次的值，
    # 配合 write_if_changed，重跑 build.py 不会产生任何 git diff。
    fresh = {"cities": cities, "points": points, "routes": routes}
    prev = _read_json(json_path)
    if prev and {k: prev.get(k) for k in fresh} == fresh and prev.get("builtAt"):
        built_at = prev["builtAt"]
    else:
        built_at = datetime.now().isoformat(timespec="seconds")

    payload = json.dumps({**fresh, "builtAt": built_at},
                         ensure_ascii=False, separators=(",", ":"))
    write_if_changed(json_path, payload.encode("utf-8"))
    # gzip 的 mtime 固定为 0，否则同样的内容每次压缩出的字节都不一样
    write_if_changed(gz_path, gzip.compress(payload.encode("utf-8"), 9, mtime=0))

    # ---------- 页面 ----------
    html = build_html(a.amap_key)
    html_path = os.path.join(a.out, "index.html")
    write_if_changed(html_path, html.encode("utf-8"))

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
        written = 0
        for city, arr in by_city.items():
            one = {"city": city, "points": arr}
            s = json.dumps(one, ensure_ascii=False, separators=(",", ":"))
            b = gzip.compress(s.encode("utf-8"), 9, mtime=0)
            if write_if_changed(os.path.join(split_dir, f"{city}.json.gz"), b):
                written += 1
            total_split += len(b)
            index["counts"][city] = len(arr)

        # 清掉源数据里已经不存在的城市包（比如某城市被并入别的城市）
        alive = {f"{c}.json.gz" for c in by_city}
        for old in os.listdir(split_dir):
            if old.endswith(".json.gz") and old not in alive:
                os.remove(os.path.join(split_dir, old))
                print(f"  清理过期分包 {old}")

        idx_s = json.dumps(index, ensure_ascii=False, separators=(",", ":"))
        write_if_changed(os.path.join(split_dir, "index.json"), idx_s.encode("utf-8"))

        print(f"  {split_dir}/   {len(by_city)} 个城市包，合计 {total_split/1024:.0f} KB"
              f"（单城平均 {total_split/1024/len(by_city):.0f} KB，本次更新 {written} 个）")

    print()
    print(f"  合计 城市 {len(cities)} · 站点 {len(points)} · 路线 {len(routes)}")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
