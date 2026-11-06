#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_nationwide.py —— 按「区号清单」抓全国所有城市的免费站

前置：先跑 discover_cities.py 生成 data/city_codes.json

流程：
  1. 按区号逐个抓站点列表，先落到 data/_bycode/<区号>.json（可断点续抓）
  2. 抓全部站点详情（地址/价格/停车优惠），缓存在 data/detail_cache/
  3. 从详情地址反推每个区号对应的城市名
  4. 写成正式源数据 data/stations/<城市>.json

为什么按区号抓：小鹏接口只认高德 cityCode（电话区号），没有城市名可用，
而城市名要靠地址反推。所以先抓再命名。

用法：
    python3 fetch_nationwide.py                # 全流程
    python3 fetch_nationwide.py --stage list   # 只抓列表
    python3 fetch_nationwide.py --stage detail # 只补详情
    python3 fetch_nationwide.py --stage name   # 只做命名归类
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
BYCODE = os.path.join(DATA, "_bycode")
DETAIL = os.path.join(DATA, "detail_cache")
STATIONS = os.path.join(DATA, "stations")
CODES = os.path.join(DATA, "city_codes.json")

GATEWAY = "https://chargegateway.xiaopeng.com"
HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://static.xiaopeng.com",
    "Referer": "https://static.xiaopeng.com/apps/charge-web/pc-free-stations.html",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
}

PROVINCES = [
    "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
    "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "内蒙古",
    "广西", "西藏", "宁夏", "新疆",
]


def post(path: str, body: dict, timeout: int = 25) -> dict:
    req = urllib.request.Request(GATEWAY + path, data=json.dumps(body).encode(), headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def fetch_list(code: str) -> list[dict]:
    d = post("/front/charge/station/search/queryMapCityLabeling",
             {"source": 2, "cityCode": code, "filterCriteriaCodeList": ["freeCharging"]})
    data = d.get("data") or {}
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    return []


def fetch_detail(sid: str):
    try:
        d = post("/front/charge/free/station/queryStationDtl",
                 {"source": 2, "stationId": str(sid)})
        return sid, d.get("data")
    except Exception:
        return sid, None


def stage_list(workers: int = 5):
    raw = json.load(open(CODES, encoding="utf-8"))["codes"]
    codes = [c for c, v in raw.items() if v.get("num", 0) > 0]
    os.makedirs(BYCODE, exist_ok=True)

    todo = [c for c in codes if not os.path.exists(os.path.join(BYCODE, f"{c}.json"))]
    print(f"列表：共 {len(codes)} 城，待抓 {len(todo)}")

    def job(code):
        arr = fetch_list(code)
        with open(os.path.join(BYCODE, f"{code}.json"), "w", encoding="utf-8") as f:
            json.dump(arr, f, ensure_ascii=False)
        return code, len(arr)

    done = 0
    total = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(job, c) for c in todo]
        for f in as_completed(futs):
            done += 1
            try:
                _, n = f.result()
                total += n
            except Exception:
                pass
            if done % 40 == 0 or done == len(todo):
                print(f"  {done}/{len(todo)}  本次已取 {total} 站")

    # 汇总
    all_ids, per_code = set(), {}
    for c in codes:
        p = os.path.join(BYCODE, f"{c}.json")
        if os.path.exists(p):
            arr = json.load(open(p, encoding="utf-8"))
            per_code[c] = len(arr)
            for s in arr:
                all_ids.add(str(s.get("stationId")))
    print(f"列表完成：{len(per_code)} 城，去重后 {len(all_ids)} 站")
    return per_code


def stage_detail(workers: int = 6):
    os.makedirs(DETAIL, exist_ok=True)
    all_ids = set()
    for fn in os.listdir(BYCODE):
        if not fn.endswith(".json"):
            continue
        for s in json.load(open(os.path.join(BYCODE, fn), encoding="utf-8")):
            sid = str(s.get("stationId"))
            if sid:
                all_ids.add(sid)

    todo = [s for s in all_ids if not os.path.exists(os.path.join(DETAIL, f"{s}.json"))]
    print(f"详情：共 {len(all_ids)} 站，缓存已有 {len(all_ids)-len(todo)}，待抓 {len(todo)}")
    if not todo:
        return

    done = 0
    fail = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(fetch_detail, s) for s in todo]
        for f in as_completed(futs):
            sid, d = f.result()
            done += 1
            if d:
                with open(os.path.join(DETAIL, f"{sid}.json"), "w", encoding="utf-8") as fp:
                    json.dump(d, fp, ensure_ascii=False)
            else:
                fail += 1
            if done % 100 == 0 or done == len(todo):
                el = time.time() - t0
                print(f"  {done}/{len(todo)}  失败 {fail}  已用 {el:.0f}s")
    print(f"详情完成：成功 {done-fail}，失败 {fail}")


CITY_RE = re.compile(r"^(.+?)(市|地区|盟|自治州)")

# 民族名，用于从「恩施土家族苗族自治州」里剥出「恩施」
ETHNIC = re.compile(
    r"(维吾尔|土家族|苗族|藏族|彝族|壮族|回族|白族|傣族|蒙古族|朝鲜族|哈尼族|傈僳族|"
    r"侗族|瑶族|黎族|羌族|景颇族|拉祜族|布朗族|布依族|仡佬族|水族|纳西族|德昂族|"
    r"阿昌族|普米族|怒族|独龙族|基诺族|门巴族|珞巴族|哈萨克族|柯尔克孜族)$"
)

MUNICIPALITIES = ("北京", "上海", "天津", "重庆")


def guess_city(addr: str) -> str:
    """从地址里抠城市名。

    '河南省信阳市浉河区…'            -> '信阳'
    '上海市浦东新区…'                -> '上海'   （直辖市直接返回）
    '广西壮族自治区南宁市青秀区…'      -> '南宁'
    '湖北省恩施土家族苗族自治州…'      -> '恩施'
    """
    if not addr:
        return ""

    # 直辖市：地址开头就是城市名
    for m in MUNICIPALITIES:
        if addr.startswith(m):
            return m

    s = addr
    for p in sorted(PROVINCES, key=len, reverse=True):
        if s.startswith(p):
            s = s[len(p):]
            break

    # 去掉省/市/自治区（含「维吾尔」这类不带「族」的前缀）
    s = re.sub(r"^(省|市)", "", s)
    s = re.sub(r"^(维吾尔|[\u4e00-\u9fa5]{1,4}族)?自治区", "", s)

    m = CITY_RE.match(s)
    if not m:
        return ""
    name = m.group(1)
    # 反复剥掉尾部的民族名
    while True:
        new = ETHNIC.sub("", name)
        if new == name:
            break
        name = new
    return name


def det_fields(d: dict | None) -> dict:
    """详情接口有两套字段名，这里统一成一套。

    旧（早期缓存）：addr / dc / ac / s4 / oper / price / park
    新（现在接口）：stationAddr / dcNums / acNums / s4Nums / operName
                   / chargeAmt+serviceAmt / park 要看 labels 里有没有「停车优惠」
    """
    if not d:
        return {}
    labels = d.get("labels") or []
    park = d.get("park")
    if park is None:
        park = "停车优惠" in labels

    def pick(key, alt, default=None):
        v = d.get(key)
        return v if v is not None else d.get(alt, default)

    price = d.get("price")
    if not price:
        ca, sa = d.get("chargeAmt"), d.get("serviceAmt")
        if ca not in (None, "") and sa not in (None, ""):
            price = f"{ca}+{sa}"

    return {
        "addr": pick("addr", "stationAddr", "") or "",
        "oper": pick("oper", "operName", ""),
        "price": price,
        "park": park,
        "labels": labels,
        "freeNums": d.get("freeNums"),
        "dc": pick("dc", "dcNums", 0),
        "ac": pick("ac", "acNums", 0),
        "s4": pick("s4", "s4Nums", 0),
    }


def stage_name(per_code: dict | None = None):
    os.makedirs(STATIONS, exist_ok=True)
    files = [f for f in os.listdir(BYCODE) if f.endswith(".json")]

    # 用每个区号下的站点地址投票决定城市名
    code_name: dict[str, str] = {}
    code_stations: dict[str, list] = {}
    for fn in files:
        code = fn[:-5]
        arr = json.load(open(os.path.join(BYCODE, fn), encoding="utf-8"))
        votes: dict[str, int] = {}
        merged = []
        for s in arr:
            sid = str(s.get("stationId"))
            det = None
            p = os.path.join(DETAIL, f"{sid}.json")
            if os.path.exists(p):
                det = json.load(open(p, encoding="utf-8"))
            f = det_fields(det)
            addr = f.get("addr") or ""
            # 地址里没有城市名时，用站名兜底（很多站名里也带「XX市」）
            n = guess_city(addr) or guess_city(s.get("stationName") or "")
            if n:
                votes[n] = votes.get(n, 0) + 1
            item = {
                "id": sid,
                "name": s.get("stationName"),
                "lng": s.get("longitude"),
                "lat": s.get("latitude"),
                # 桩数以详情为准（详情更全），没有则用列表值
                "dc": f.get("dc") if f.get("dc") is not None else (s.get("dcNum") or 0),
                "ac": f.get("ac") if f.get("ac") is not None else (s.get("acNum") or 0),
                "s4": f.get("s4") if f.get("s4") is not None else (s.get("s4Num") or 0),
                "mode": s.get("operationMode"),
                # 和 fetch_xpeng.py 保持一致：operationMode==1 是小鹏自营
                "type": "free" if int(s.get("operationMode") or 0) == 1 else "third",
                "xpOwner": s.get("showXpOwner"),
                "freeNums": f.get("freeNums"),
                "labels": f.get("labels"),
                "addr": addr,
                "price": f.get("price"),
                "park": f.get("park"),
                "oper": f.get("oper"),
            }
            merged.append(item)
        if votes:
            code_name[code] = max(votes.items(), key=lambda kv: kv[1])[0]
            code_stations[code] = merged
        else:
            print(f"  [警告] {code} 无法从地址推断城市名，跳过（{len(merged)} 站）")

    # 同名城市（跨区号）合并
    by_name: dict[str, list] = {}
    for code, name in code_name.items():
        by_name.setdefault(name, []).extend(code_stations[code])

    import store
    for name, arr in by_name.items():
        store.save_city(name, arr, merge=True)

    # 把「城市名 -> 区号」存下来，方便以后按城市增量更新
    meta: dict[str, dict] = {}
    for code, name in code_name.items():
        m = meta.setdefault(name, {"codes": [], "count": 0})
        m["codes"].append(code)
        m["count"] += len(code_stations[code])
    with open(os.path.join(DATA, "city_meta.json"), "w", encoding="utf-8") as f:
        json.dump(dict(sorted(meta.items())), f, ensure_ascii=False, indent=1)

    print(f"命名完成：{len(code_name)} 个区号 -> {len(by_name)} 个城市")
    top = sorted(by_name.items(), key=lambda kv: -len(kv[1]))[:10]
    for n, a in top:
        print(f"  {n}: {len(a)} 站")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["list", "detail", "name", "all"], default="all")
    ap.add_argument("--workers", type=int, default=5)
    a = ap.parse_args()

    if not os.path.exists(CODES):
        sys.exit("缺 data/city_codes.json，先跑 python3 discover_cities.py")

    if a.stage in ("list", "all"):
        stage_list(a.workers)
    if a.stage in ("detail", "all"):
        stage_detail(a.workers + 1)
    if a.stage in ("name", "all"):
        stage_name()


if __name__ == "__main__":
    main()
