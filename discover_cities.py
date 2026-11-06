#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
discover_cities.py —— 摸清小鹏免费站到底覆盖了哪些城市

为什么需要这个：
    小鹏的按城市查站接口 queryMapCityLabeling 只认「高德 cityCode」（电话区号，
    如杭州 0571），而 cityCode 在高德那边要靠逆地理编码从经纬度换出来，没有现成的
    城市清单接口。之前是手工维护了 49 个城市，结果漏了 280 个——比如信阳、许昌的
    京港澳高速服务区站，压根没查过这两个城市。

    这里的办法是直接枚举所有可能的区号，逐个探一遍，把真正有站的城市找出来。
    一次性成本约 1~2 分钟，结果缓存到 data/city_codes.json，之后不用再扫。

用法：
    python3 discover_cities.py            # 扫描并写入 data/city_codes.json
    python3 discover_cities.py --force    # 忽略缓存，重扫
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "data", "city_codes.json")

GATEWAY = "https://chargegateway.xiaopeng.com"
PATH = "/front/charge/station/search/queryMapCityLabeling"
HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://static.xiaopeng.com",
    "Referer": "https://static.xiaopeng.com/apps/charge-web/pc-free-stations.html",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
}

_lock = threading.Lock()


def candidates() -> list[str]:
    """所有可能的高德 cityCode。中国电话区号都是 0 开头，3~4 位。"""
    codes = ["010"]
    # 02X：直辖市与部分省会（020 广州 … 029 西安，026 空号）
    codes += [f"02{i}" for i in range(1, 10)]
    # 03XX ~ 09XX：普通地级市
    for p in range(3, 10):
        codes += [f"0{p}{i:02d}" for i in range(0, 100)]
    return codes


def probe(code: str) -> tuple[str, int, float | None, float | None]:
    """返回 (code, 站数, 首个站经度, 首个站纬度)"""
    body = {"source": 2, "cityCode": code, "filterCriteriaCodeList": ["freeCharging"]}
    req = urllib.request.Request(GATEWAY + PATH, data=json.dumps(body).encode(), headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            d = json.loads(r.read().decode())
    except Exception:
        return code, -1, None, None      # -1 表示探测失败，稍后重试
    data = d.get("data") or {}
    arr = []
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                arr = v
                break
    if not arr:
        return code, 0, None, None
    first = arr[0]
    return code, len(arr), first.get("longitude"), first.get("latitude")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="忽略已有结果，重扫")
    ap.add_argument("--workers", type=int, default=5, help="并发数，默认 5（别开太大）")
    a = ap.parse_args()

    done: dict[str, dict] = {}
    if os.path.exists(OUT) and not a.force:
        with open(OUT, encoding="utf-8") as f:
            done = json.load(f).get("codes", {})
        print(f"已有结果 {len(done)} 条，接着补")

    todo = [c for c in candidates() if c not in done]
    print(f"待探测 {len(todo)} 个区号，并发 {a.workers}")

    t0 = time.time()
    finished = 0
    failed: list[str] = []

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(probe, c): c for c in todo}
        for f in as_completed(futs):
            code, n, lng, lat = f.result()
            finished += 1
            if n < 0:
                failed.append(code)
            else:
                with _lock:
                    done[code] = {"num": n, "lng": lng, "lat": lat}
            if finished % 50 == 0:
                el = time.time() - t0
                print(f"  {finished}/{len(todo)}  已用 {el:.0f}s  "
                      f"命中 {sum(1 for v in done.values() if v['num'] > 0)}")

    # 失败的重试一轮
    if failed:
        print(f"重试 {len(failed)} 个失败项")
        for code in failed:
            code, n, lng, lat = probe(code)
            if n >= 0:
                done[code] = {"num": n, "lng": lng, "lat": lat}
            time.sleep(0.3)

    hit = {c: v for c, v in done.items() if v.get("num", 0) > 0}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"scannedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "totalCodes": len(done), "hitCodes": len(hit),
                   "codes": dict(sorted(done.items()))},
                  f, ensure_ascii=False, indent=1)

    print(f"\n扫描完成：{len(done)} 个区号，其中 {len(hit)} 个城市有站")
    print(f"站数合计 {sum(v['num'] for v in hit.values())}")
    print(f"写入 {OUT}")


if __name__ == "__main__":
    main()
