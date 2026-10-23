#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_amap.py —— 用小鹏站点数据填充「高德地图小程序」官方模板

为什么不自己从零造 xlsx：高德的解析器比较挑，表头、单元格类型、甚至列宽
都可能影响。最稳的办法是直接打开高德官方模板，只替换数据区。

模板要求（见官方「导入说明」工作表）：
    名称         选填，≤40 字
    *经度/*纬度  必填，GCJ-02（小鹏数据本身就是 GCJ-02，不用转换）
    *地址        填了经纬度可以不填
    颜色         选填，1..8，对应「颜色说明」里的色值
    描述         选填，≤600 字
    文件夹       选填，多级用 "/" 分隔，可自动建文件夹

坑（踩过了，别再犯）：
  1. 经纬度必须是「经度」「纬度」两列，不能合成 "lng,lat" 一列
  2. 表头要带星号：*经度 *纬度 *地址
  3. 单元格要写成字符串，模板里就是 '113.681' 这种，不是数字
  4. 用 .xlsx，别用 .csv

用法：
  python3 export_amap.py                 # 每个城市一个 xlsx → amap/
  python3 export_amap.py --all           # 额外生成全部城市合一的文件
  python3 export_amap.py --cities 上海,杭州
  python3 export_amap.py --park-only     # 只要带停车优惠的
  python3 export_amap.py --template 路径  # 指定官方模板
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

from openpyxl import load_workbook

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "amap")
# 官方模板：优先用仓库里的，其次用户上传的
TEMPLATE_CANDIDATES = [
    os.path.join(ROOT, "templates", "导入模板.xlsx"),
    "/root/uploads/wb-agentserver-afd6ae3e-35a4-4b0c-8dd0-e164c40960b9-uploads-1792758/导入模板.xlsx",
]

# 高德「颜色说明」里的 8 个色值（按第 n 个的顺序）
#   1 #7E97FF 浅蓝紫   2 #7AB1F5 蓝     3 #4CC7FF 天蓝   4 #12E3AA 青绿
#   5 #FFBF00 琥珀     6 #FF983F 橙     7 #EA7864 珊瑚   8 #FF6968 红
COLOR_FREE_PARK = 8    # 红：免费权益 + 有停车优惠（最想要，最显眼）
COLOR_FREE = 1         # 浅蓝紫：免费权益、无停车优惠
COLOR_THIRD_PARK = 5   # 琥珀：第三方 + 有停车优惠
COLOR_THIRD = 3        # 天蓝：第三方、无停车优惠

COLOR_MEANING = {
    COLOR_FREE_PARK: "红 · 免费权益 + 有停车优惠",
    COLOR_FREE: "浅蓝紫 · 免费权益、无停车优惠",
    COLOR_THIRD_PARK: "琥珀 · 第三方 + 有停车优惠",
    COLOR_THIRD: "天蓝 · 第三方、无停车优惠",
}

SHEET = "标记位置"


def find_template(explicit: str | None) -> str:
    if explicit:
        if not os.path.exists(explicit):
            sys.exit(f"模板不存在：{explicit}")
        return explicit
    for p in TEMPLATE_CANDIDATES:
        if os.path.exists(p):
            return p
    sys.exit("找不到高德官方导入模板，用 --template 指定路径")


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
    """描述列上限 600 字，这里远低于，不用截断。"""
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


def row_for(p):
    """按模板顺序返回 9 个值。全部用字符串，和官方模板保持一致。"""
    lng, lat = p.get("lng"), p.get("lat")
    if lng is None or lat is None:
        return None
    name = (p.get("name") or "")[:40]          # 名称上限 40 字
    desc = describe(p)[:600]                    # 描述上限 600 字
    return [
        name,
        f"{float(lng):.6f}",                    # 字符串
        f"{float(lat):.6f}",
        p.get("addr") or "",
        str(color_of(p)),                       # 字符串，模板里就是 '1'
        "",                                     # 图标(外轮廓)
        "",                                     # 图标(填充物)
        desc,
        p.get("city") or "",                    # 文件夹：按城市分组，地图里自动建文件夹
    ]


def build(template: str, out_path: str, points, keep_other_sheets=False):
    """复制官方模板，清空「标记位置」的数据区，再写入新数据。

    keep_other_sheets=False 时会删掉「导入说明」「颜色说明」两个工作表。
    那两个表里塞了 4 张说明截图（约 1.9 MB），对上传毫无用处，
    删掉后文件从 1.9 MB 降到 7 KB，导入更快也不容易超限。
    表头、列宽、单元格类型都来自模板本身，不受影响。
    """
    shutil.copyfile(template, out_path)
    wb = load_workbook(out_path)
    ws = wb[SHEET]

    # 表头照抄模板，不改一个字
    header = [c.value for c in ws[1]]
    if header[:4] != ["名称", "*经度", "*纬度", "*地址"]:
        sys.exit(f"模板表头不符合预期：{header}")

    # 清掉模板里的示例行（保留第 1 行表头和样式）
    if ws.max_row > 1:
        ws.delete_rows(2, ws.max_row - 1)

    n = 0
    for p in points:
        vals = row_for(p)
        if not vals:
            continue
        r = n + 2
        for c, v in enumerate(vals, 1):
            ws.cell(row=r, column=c, value=v)
        n += 1

    if not keep_other_sheets:
        for name in list(wb.sheetnames):
            if name != SHEET:
                del wb[name]

    wb.save(out_path)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cities", default="", help="只导出这些城市，逗号分隔")
    ap.add_argument("--all", action="store_true", help="额外生成全部城市合一的大文件")
    ap.add_argument("--park-only", action="store_true", help="只导出有停车优惠的站")
    ap.add_argument("--out", default=OUT, help="输出目录，默认 amap/")
    ap.add_argument("--template", default=None, help="高德官方导入模板路径")
    ap.add_argument("--per-file", type=int, default=0,
                    help="每个文件最多多少行（高德上限 50000），0 不限")
    a = ap.parse_args()

    tpl = find_template(a.template)
    print(f"模板：{tpl}")

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
    print(f"输出：{a.out}")

    for old in os.listdir(a.out):
        if old.endswith((".csv", ".xlsx")):
            os.remove(os.path.join(a.out, old))

    total = 0
    for city in sorted(by_city, key=lambda c: -len(by_city[c])):
        n = build(tpl, os.path.join(a.out, f"{city}.xlsx"), by_city[city])
        total += n
        print(f"  {city}.xlsx  {n} 个站")

    if a.all:
        n = build(tpl, os.path.join(a.out, "全部城市.xlsx"), points)
        print(f"  全部城市.xlsx  {n} 个站")

    with open(os.path.join(a.out, "导入说明.txt"), "w", encoding="utf-8") as f:
        f.write(
            "这些 xlsx 是基于高德官方模板填充的，表头/单元格格式与模板完全一致。\n\n"
            "导入方法\n"
            "1. 电脑打开 https://wia.amap.com 登录高德账号\n"
            "2. 左上「我加入的」→ 创建新地图，起个名字（如「小鹏免费站」）\n"
            "3. 顶部「批量导入」→ 数据来源选「高德地图」→ 上传 .xlsx\n"
            "4. 手机高德 App → 我的 → 地图小程序 → 就能看到，可一键导航\n\n"
            "颜色含义（对应模板「颜色说明」工作表里的第 n 个色块）\n"
        )
        for k in (COLOR_FREE_PARK, COLOR_FREE, COLOR_THIRD_PARK, COLOR_THIRD):
            f.write(f"  {k}  {COLOR_MEANING[k]}\n")
        f.write(
            "\n文件夹\n"
            "  已按城市自动填了「文件夹」列，导入后地图里会生成按城市分的文件夹。\n\n"
            "注意\n"
            "  - 单次上传 ≤ 50000 行、≤ 20 MB\n"
            "  - 高德不支持覆盖更新，重新导入前要先删旧地图或新建一张\n"
            "  - 坐标系 GCJ-02，和高德一致，不用转换\n"
        )
    print("  导入说明.txt")
    print(f"\n合计 {len(by_city)} 个城市 · {total} 个站")


if __name__ == "__main__":
    main()
