#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
store.py —— 源数据的统一读写层

所有脚本都不直接碰文件路径，统一走这里，保证结构一致。

目录约定
  data/
    cities.json            44 个城市（name / code / center / zoom）
    meta.json              采集元信息（时间、来源、各城站数）
    stations/
      杭州.json            该城站点数组（按站名排序）
      上海.json
    routes/
      杭州→上海.json        一条真实驾车路线
    detail_cache/          抓取中间缓存（不入库）
"""
import glob
import json
import os
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
STATIONS = os.path.join(DATA, "stations")
ROUTES = os.path.join(DATA, "routes")


def _ensure():
    os.makedirs(STATIONS, exist_ok=True)
    os.makedirs(ROUTES, exist_ok=True)


def _read(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write(path, obj, indent=1):
    _ensure()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
    os.replace(tmp, path)          # 原子替换，中途崩了不会写坏


# ---------------- 城市 ----------------
def load_cities():
    return _read(os.path.join(DATA, "cities.json"), [])


def save_cities(cities):
    _write(os.path.join(DATA, "cities.json"), cities)


# ---------------- 站点 ----------------
def city_names():
    """源数据里已有的城市（按文件名）"""
    return sorted(os.path.splitext(os.path.basename(p))[0]
                  for p in glob.glob(os.path.join(STATIONS, "*.json")))


def load_city(city):
    return _read(os.path.join(STATIONS, f"{city}.json"), [])


def save_city(city, points, merge=True):
    """写入单个城市。这是增量更新的核心：只碰一个文件。

    merge=True 时按 id 合并旧记录：新抓到的列表字段（名称/坐标/桩数）覆盖旧的，
    但旧记录里已有的详情字段（地址/价格/停车优惠）如果新数据没有，就保留下来。
    这样「只刷列表不抓详情」不会把地址价格清空。
    """
    if merge:
        old = {str(p.get("id")): p for p in load_city(city)}
        keep_keys = ("addr", "price", "park", "oper", "freeNums", "labels", "guns", "power")
        for p in points:
            prev = old.get(str(p.get("id")))
            if not prev:
                continue
            for k in keep_keys:
                if (p.get(k) in (None, "", 0, False)) and prev.get(k) not in (None, "", 0, False):
                    p[k] = prev[k]

    points = sorted(points, key=lambda p: (p.get("name") or ""))
    for p in points:
        p["city"] = city
    _write(os.path.join(STATIONS, f"{city}.json"), points)
    bump_meta(city, len(points))


def normalize(p):
    """统一站点字段：把 dc/ac/s4 合成可读的 guns，并去掉前端不用的字段。

    源数据里保留 dc/ac/s4（原始事实，便于以后换展示方式），
    输出前统一转成 guns/power 两个字符串，页面直接用。
    """
    dc, ac, s4 = p.get("dc") or 0, p.get("ac") or 0, p.get("s4") or 0
    if dc or ac or s4:
        parts = []
        if dc: parts.append(f"快充{dc}")
        if ac: parts.append(f"慢充{ac}")
        if s4: parts.append(f"S4×{s4}")
        p["guns"] = " · ".join(parts)
        p["power"] = "S4超充" if s4 else ("直流快充" if dc else "交流慢充")
    else:
        p.setdefault("guns", "")
        p.setdefault("power", "")
    for k in ("mode", "xpOwner", "freeNums", "labels", "dc", "ac", "s4"):
        p.pop(k, None)
    return p


def load_all():
    """读全部站点，带跨城去重（同一站可能在不同城市文件里出现）"""
    out, seen = [], {}
    for c in city_names():
        for p in load_city(c):
            p["city"] = c
            key = (p.get("name"), round(float(p.get("lng", 0)), 5), round(float(p.get("lat", 0)), 5))
            if key in seen:
                continue
            seen[key] = 1
            out.append(normalize(p))
    return out


# ---------------- 路线 ----------------
def route_label(path):
    return os.path.splitext(os.path.basename(path))[0]


def load_routes():
    routes = {}
    for fp in sorted(glob.glob(os.path.join(ROUTES, "*.json"))):
        r = _read(fp)
        if not r:
            continue
        r.pop("rawPoints", None)
        routes[r.get("label") or route_label(fp)] = r
    return routes


def save_route(label, route):
    _ensure()
    route = dict(route)
    route["label"] = label
    route.pop("rawPoints", None)
    _write(os.path.join(ROUTES, f"{label}.json"), route)


# ---------------- 元信息 ----------------
def load_meta():
    return _read(os.path.join(DATA, "meta.json"), {})


def bump_meta(city, count):
    """记录某城市最后一次更新的时间和站数"""
    meta = load_meta()
    meta.setdefault("counts", {})[city] = count
    meta.setdefault("updated", {})[city] = datetime.now().isoformat(timespec="seconds")
    meta["updatedAt"] = meta["updated"][city]
    meta["total"] = sum(meta["counts"].values())
    meta.setdefault("source", "小鹏官方 pc-free-stations")
    _write(os.path.join(DATA, "meta.json"), meta)


def stale_cities(days=30):
    """返回超过 N 天没更新过的城市，方便增量刷新"""
    meta = load_meta()
    updated = meta.get("updated", {})
    now = datetime.now()
    out = []
    for c in city_names():
        ts = updated.get(c)
        if not ts:
            out.append(c)
            continue
        try:
            if (now - datetime.fromisoformat(ts)).days >= days:
                out.append(c)
        except ValueError:
            out.append(c)
    return out
