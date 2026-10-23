#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate_source.py —— 把「一个大的 stations.json」拆成「按城市一份」的源数据

为什么要拆：
  全国 3357 个站放在一个文件里，每次采集都要全量重写 1.5 MB，
  git 里永远是整文件 diff，也没法只更新一个城市。

拆完的结构（源数据，可增量维护）：
  data/
    cities.json          44 个城市的中心点/编码
    stations/
      杭州.json          该城市的站点数组
      上海.json
      ...
    routes/
      杭州→上海.json     一条真实驾车路线
      ...
    meta.json            采集时间、来源、各城市站数快照

增量更新时只改 data/stations/<城市>.json 一个文件。
"""
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")


def main():
    src = os.path.join(DATA, "stations.json")
    if not os.path.exists(src):
        print("找不到 data/stations.json，无需迁移")
        return 1

    with open(src, encoding="utf-8") as f:
        raw = json.load(f)

    cities = raw.get("cities", [])
    points = raw.get("points", [])

    os.makedirs(os.path.join(DATA, "stations"), exist_ok=True)

    # 按城市分桶。没有 city 字段的（理论上不该有）归到「未知」
    buckets = {}
    for p in points:
        buckets.setdefault(p.get("city") or "未知", []).append(p)

    # 清理前端不用的字段，源数据保持精简但保留展示所需
    for city, arr in buckets.items():
        for p in arr:
            for k in ("mode", "xpOwner", "labels", "freeNums"):
                p.pop(k, None)
            dc, ac, s4 = p.pop("dc", None), p.pop("ac", None), p.pop("s4", None)
            # 桩数合成可读字符串，页面直接显示
            if "guns" not in p:
                parts = []
                if dc: parts.append(f"快充{dc}")
                if ac: parts.append(f"慢充{ac}")
                if s4: parts.append(f"S4×{s4}")
                p["guns"] = " · ".join(parts)
            p.setdefault("power", "")

    # 写城市文件
    written = []
    for city, arr in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        arr.sort(key=lambda p: (p.get("name") or ""))
        path = os.path.join(DATA, "stations", f"{city}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(arr, f, ensure_ascii=False, indent=1)
        written.append((city, len(arr)))
        print(f"  {city}.json  {len(arr)} 站")

    # 城市表
    with open(os.path.join(DATA, "cities.json"), "w", encoding="utf-8") as f:
        json.dump(cities, f, ensure_ascii=False, indent=1)
    print(f"  cities.json  {len(cities)} 个城市")

    # 元信息：记录每城站数与采集时间，方便判断哪些城市该重抓
    meta = {
        "source": raw.get("source", ""),
        "fetchedAt": raw.get("fetchedAt", ""),
        "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "counts": {c: n for c, n in sorted(written)},
        "total": len(points),
    }
    with open(os.path.join(DATA, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(f"  meta.json  合计 {len(points)} 站")

    return 0


if __name__ == "__main__":
    sys.exit(main())
