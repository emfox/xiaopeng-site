#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_amap.py —— 把小鹏站点导出成「高德地图小程序」可批量导入的格式

高德 App 里的「地图小程序」(wia.amap.com) 支持在 PC 端批量导入 xls/xlsx/csv，
导入后手机高德 App → 我的 → 地图小程序 就能看到，而且支持一键导航、顺路规划。
这是唯一能把自定义点位「放进高德 App 本体」的官方途径。

模板列固定为：名称 / 经纬度 / 地址 / 颜色 / 描述（不能自定义列名）

颜色（前端看到的色块顺序）：
  1 绿色  免费权益 + 有停车优惠   ← 最想要的一类
  2 蓝色  免费权益、无停车优惠
  3 橙色  第三方合作 + 有停车优惠
  4 灰色  第三方合作、无停车优惠

用法：
  python3 export_amap.py                 # 每个城市一个文件 → amap/
  python3 export_amap.py --all           # 额外生成全部城市合一的文件
  python3 export_amap.py --cities 上海,杭州
  python3 export_amap.py --park-only     # 只要带停车优惠的
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "amap")
HEADER = ["名称", "经纬度", "地址", "颜色", "描述"]

# 颜色编码 → 含义
COLOR_FREE_PARK = 1
COLOR_FREE = 2
COLOR_THIRD_PARK = 3
COLOR_THIRD = 4


def color_of(p) -> int:
    free = p.get("type") != "third"
    park = bool(p.get("park"))
    if free and park:
        return COLOR_FREE_PARK
    if free:
        return COLOR_FREE
    if park:
        return COLOR_THIRD_PARK
    return COLOR_THIRD


def clean_price(price) -> str:
    """价格形如 "0.64+0.61"（电费+服务费）。接口有时返回 "None+None"，要清掉。"""
    if not price:
        return ""
    s = str(price).replace("None", "").replace("none", "")
    parts = [x.strip() for x in s.split("+") if x.strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return f"电费{parts[0]} 服务费{parts[1]}"


def describe(p) -> str:
    bits = []
    if p.get("type") == "third":
        bits.append(f"第三方·{p.get('oper') or '合作站'}")
    else:
        bits.append("小鹏免费权益")
    if p.get("park"):
        bits.append("有停车优惠")
    if p.get("guns"):
        bits.append(p["guns"])
    price = clean_price(p.get("price"))
    if price:
        bits.append(price)
    return "；".join(bits)


def rows_for(points):
    """按高德模板生成行。经纬度用「经度,纬度」一列。"""
    rows = []
    for p in points:
        lng, lat = p.get("lng"), p.get("lat")
        if lng is None or lat is None:
            continue
        rows.append([
            p.get("name", ""),
            f"{lng:.6f},{lat:.6f}",
            p.get("addr", ""),
            color_of(p),
            describe(p),
        ])
    return rows


def write_csv(path, rows):
    # utf-8-sig：带 BOM，Excel 双击打开不乱码
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cities", default="", help="只导出这些城市，逗号分隔")
    ap.add_argument("--all", action="store_true", help="额外生成全部城市合一的大文件")
    ap.add_argument("--park-only", action="store_true", help="只导出有停车优惠的站")
    ap.add_argument("--out", default=OUT, help="输出目录，默认 amap/")
    a = ap.parse_args()

    src = os.path.join(ROOT, "data.json")
    if not os.path.exists(src):
        sys.exit("找不到 data.json，先跑 python3 build.py")
    data = json.load(open(src, encoding="utf-8"))
    points = data["points"]

    if a.park_only:
        points = [p for p in points if p.get("park")]

    if a.cities:
        want = {c.strip() for c in a.cities.split(",") if c.strip()}
        points = [p for p in points if p.get("city") in want]

    by_city = {}
    for p in points:
        by_city.setdefault(p.get("city") or "未知", []).append(p)

    os.makedirs(a.out, exist_ok=True)
    print(f"导出目录：{a.out}")

    # 清掉上次的产物，避免城市改名后留垃圾
    for old in os.listdir(a.out):
        if old.endswith(".csv"):
            os.remove(os.path.join(a.out, old))

    total = 0
    for city in sorted(by_city, key=lambda c: -len(by_city[c])):
        rows = rows_for(by_city[city])
        n = write_csv(os.path.join(a.out, f"{city}.csv"), rows)
        total += n
        print(f"  {city}.csv  {n} 个站")

    if a.all:
        n = write_csv(os.path.join(a.out, "全部城市.csv"), rows_for(points))
        print(f"  全部城市.csv  {n} 个站")

    # 附带一个说明，免得过几个月忘了颜色含义
    readme = os.path.join(a.out, "导入说明.txt")
    with open(readme, "w", encoding="utf-8") as f:
        f.write(
            "导入方法\n"
            "1. 电脑浏览器打开 https://wia.amap.com 并登录高德账号\n"
            "2. 左上「我加入的」→ 创建新地图，起个名字（如「小鹏免费站」）\n"
            "3. 点右上「批量导入」→ 数据来源选「高德地图」→ 上传这里的 .csv\n"
            "4. 手机高德 App → 我的 → 地图小程序 → 就能看到，可一键导航\n\n"
            "颜色含义\n"
            "  1 绿色   小鹏免费权益 + 有停车优惠\n"
            "  2 蓝色   小鹏免费权益、无停车优惠\n"
            "  3 橙色   第三方合作 + 有停车优惠\n"
            "  4 灰色   第三方合作、无停车优惠\n\n"
            "注意\n"
            "  - 导入一次最多 50000 行，单城市文件远低于上限，建议一个城市一个文件\n"
            "  - 高德目前不支持覆盖更新，重新导入前要先删除旧地图或新建一张\n"
        )
    print(f"  导入说明.txt")
    print(f"\n合计 {len(by_city)} 个城市 · {total} 个站")


if __name__ == "__main__":
    main()
