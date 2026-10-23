#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快速补抓站点详情（并发版），已抓过的自动跳过。"""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_xpeng import post, fetch_city, CITIES, CITY_CENTER

CACHE = "data/detail_cache"
LIST = "data/city_list_cache.json"


def load_list():
    if os.path.exists(LIST):
        pts = json.load(open(LIST, encoding="utf-8"))
        print(f"复用列表缓存 {len(pts)} 个站")
        return pts
    pts, seen = [], set()
    for c, code in CITIES.items():
        for s in fetch_city(c, code):
            sid = str(s.get("stationId"))
            if sid in seen:
                continue
            seen.add(sid)
            pts.append({"id": sid, "name": s.get("stationName", ""),
                        "lng": float(s.get("longitude") or 0), "lat": float(s.get("latitude") or 0),
                        "city": c, "mode": int(s.get("operationMode") or 0),
                        "type": "free" if int(s.get("operationMode") or 0) == 1 else "third",
                        "dc": int(s.get("dcNum") or 0), "ac": int(s.get("acNum") or 0),
                        "s4": int(s.get("s4Num") or 0), "xpOwner": bool(s.get("showXpOwner"))})
        print(f"  {c} 累计 {len(pts)}")
    json.dump(pts, open(LIST, "w", encoding="utf-8"), ensure_ascii=False)
    return pts


def one(p):
    fp = os.path.join(CACHE, p["id"] + ".json")
    if os.path.exists(fp):
        return
    try:
        d = post("/front/charge/free/station/queryStationDtl", {"source": 2, "stationId": p["id"]})
        d = d.get("data") or {}
        rec = {"park": "停车优惠" in (d.get("labels") or []),
               "addr": d.get("stationAddr") or "", "oper": d.get("operName") or "",
               "price": f"{d.get('chargeAmt','')}+{d.get('serviceAmt','')}",
               "freeNums": d.get("freeNums") or 0, "labels": d.get("labels") or []}
    except Exception as e:
        rec = {"park": False, "addr": "", "oper": "", "price": "", "freeNums": 0,
               "labels": [], "error": str(e)[:60]}
    json.dump(rec, open(fp, "w", encoding="utf-8"), ensure_ascii=False)


def main():
    os.makedirs(CACHE, exist_ok=True)
    pts = load_list()
    todo = [p for p in pts if not os.path.exists(os.path.join(CACHE, p["id"] + ".json"))]
    print(f"总计 {len(pts)}，已有 {len(pts)-len(todo)}，待抓 {len(todo)}")
    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        for _ in ex.map(one, todo):
            done += 1
            if done % 100 == 0:
                el = time.time() - t0
                eta = el / done * (len(todo) - done)
                print(f"  {done}/{len(todo)}  已用{el:.0f}s  预计剩余{eta:.0f}s", flush=True)
    print(f"详情抓取完成，用时 {time.time()-t0:.0f}s")

    for p in pts:
        fp = os.path.join(CACHE, p["id"] + ".json")
        if os.path.exists(fp):
            p.update(json.load(open(fp, encoding="utf-8")))

    cities = [{"name": c, "code": CITIES[c], "center": CITY_CENTER.get(c, [0, 0]), "zoom": 11}
              for c in CITIES if CITY_CENTER.get(c)]
    out = {"cities": cities, "points": pts, "source": "小鹏官方 pc-free-stations",
           "fetchedAt": time.strftime("%Y-%m-%d %H:%M")}
    json.dump(out, open("data/stations.json", "w", encoding="utf-8"), ensure_ascii=False)
    free = sum(1 for p in pts if p["type"] == "free")
    park = sum(1 for p in pts if p.get("park"))
    print(f"写入 data/stations.json：{len(pts)} 站，自营 {free}，有停车优惠 {park}")


if __name__ == "__main__":
    main()
