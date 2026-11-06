#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""add_meta.py —— 给 cities.json 补「省份」，并生成 data/districts.json

为什么要单独跑一个脚本：
  小鹏接口只给了一个 cityCode（电话区号），没有省份、也没有区县。
  页面上要做省市两级筛选、要按区县细分，只能从站点地址里反推。

省份怎么来：
  绝大多数地址带省名（`浙江省杭州市…`）。直辖市不带省，城市名就是省名。
  实在没有省名的（`三明三元区火车站停车场`），用同城市其他站投票出来的省，
  一个城市只可能属于一个省，所以按城市补全就够了。

区县怎么来：
  地址形如 `浙江省杭州市余杭区鸬鸟镇…`。之前用的正则是在开头抓
  「2~4 个汉字 + 区/县/市」，结果抓出来的是「杭州市」——市级地名，
  于是杭州凭 10 条以「杭州市」开头的地址就多出一个区县选项。
  正确做法是先剥掉「省 + 地级市」，再抓第一个 `xx区/xx县/xx市/xx旗`。

用法：
  python3 add_meta.py            # 写回 cities.json + districts.json
  python3 add_meta.py --check    # 只看统计，不写文件
"""
import argparse
import json
import os
import re
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
CITIES = os.path.join(ROOT, "data", "cities.json")
DISTRICTS = os.path.join(ROOT, "data", "districts.json")
STATIONS = os.path.join(ROOT, "data", "stations")

MUNICIPALITIES = ("北京", "天津", "上海", "重庆")

# 完整省名，长的在前，避免「内蒙古」被「内蒙」之类截断
PROVINCES = [
    "内蒙古自治区", "广西壮族自治区", "西藏自治区", "宁夏回族自治区", "新疆维吾尔自治区",
    "香港特别行政区", "澳门特别行政区",
    "黑龙江省", "河北省", "山西省", "辽宁省", "吉林省", "江苏省", "浙江省", "安徽省",
    "福建省", "江西省", "山东省", "河南省", "湖北省", "湖南省", "广东省", "海南省",
    "四川省", "贵州省", "云南省", "陕西省", "甘肃省", "青海省", "台湾省",
]
# 去掉后缀的简称，用来比对已被切碎的地址
PROV_SHORT = {
    "内蒙古", "广西", "西藏", "宁夏", "新疆", "香港", "澳门",
    "黑龙江", "河北", "山西", "辽宁", "吉林", "江苏", "浙江", "安徽", "福建", "江西",
    "山东", "河南", "湖北", "湖南", "广东", "海南", "四川", "贵州", "云南", "陕西",
    "甘肃", "青海", "台湾",
}

# 规范省名（二分省名不用「黑龙」「内蒙」这种半截写法，显示和分组都要用）
PROV_NAME = {
    "内蒙古自治区": "内蒙古", "广西壮族自治区": "广西", "西藏自治区": "西藏",
    "宁夏回族自治区": "宁夏", "新疆维吾尔自治区": "新疆",
    "香港特别行政区": "香港", "澳门特别行政区": "澳门",
    "黑龙江省": "黑龙江", "河北省": "河北", "山西省": "山西", "辽宁省": "辽宁",
    "吉林省": "吉林", "江苏省": "江苏", "浙江省": "浙江", "安徽省": "安徽",
    "福建省": "福建", "江西省": "江西", "山东省": "山东", "河南省": "河南",
    "湖北省": "湖北", "湖南省": "湖南", "广东省": "广东", "海南省": "海南",
    "四川省": "四川", "贵州省": "贵州", "云南省": "云南", "陕西省": "陕西",
    "甘肃省": "甘肃", "青海省": "青海", "台湾省": "台湾",
}
# 按简称也能认出来（地址里常写「广西柳州市」而不是全称）
PROV_SHORT = {v for v in PROV_NAME.values()}
# 简称 → 内部排序键，用于把省份按地理大区排，而不是拼音
PROV_ORDER = [
    "北京", "天津", "河北", "山西", "内蒙古",
    "辽宁", "吉林", "黑龙江",
    "上海", "江苏", "浙江", "安徽", "福建", "江西", "山东",
    "河南", "湖北", "湖南", "广东", "广西", "海南",
    "重庆", "四川", "贵州", "云南", "西藏",
    "陕西", "甘肃", "青海", "宁夏", "新疆",
    "香港", "澳门", "台湾",
]

DIST_RE = re.compile(r"^([\u4e00-\u9fa5]{1,8}?(?:自治县|自治旗|新区|区|县|市|旗))")

# 地址里没写省名的城市，人工兜一下。这类都是只属于一个省的城市名，不会歧义
CITY_PROVINCE_FALLBACK = {
    "伊春": "黑龙江", "巴彦淖尔": "内蒙古", "阿里": "西藏", "哈密": "新疆",
    "石嘴山": "宁夏", "齐齐哈尔": "黑龙江", "佳木斯": "黑龙江", "牡丹江": "黑龙江",
    "大庆": "黑龙江", "绥化": "黑龙江", "黑河": "黑龙江", "加格达奇": "黑龙江",
    "鄂尔多斯": "内蒙古", "呼伦贝尔": "内蒙古", "乌兰察布": "内蒙古", "通辽": "内蒙古",
    "赤峰": "内蒙古", "锡林郭勒": "内蒙古", "兴安盟": "内蒙古", "阿拉善": "内蒙古",
    "日喀则": "西藏", "林芝": "西藏", "昌都": "西藏", "山南": "西藏", "那曲": "西藏",
    "喀什": "新疆", "伊犁": "新疆", "阿克苏": "新疆", "库尔勒": "新疆", "克拉玛依": "新疆",
    "吐鲁番": "新疆", "昌吉": "新疆", "和田": "新疆", "塔城": "新疆", "阿勒泰": "新疆",
    "固原": "宁夏", "吴忠": "宁夏", "中卫": "宁夏",
    "海东": "青海", "格尔木": "青海",
    "酒泉": "甘肃", "嘉峪关": "甘肃", "张掖": "甘肃", "武威": "甘肃", "金昌": "甘肃",
    "天水": "甘肃", "平凉": "甘肃", "庆阳": "甘肃", "定西": "甘肃", "陇南": "甘肃",
    "延安": "陕西", "榆林": "陕西", "宝鸡": "陕西", "咸阳": "陕西", "渭南": "陕西",
    "汉中": "陕西", "安康": "陕西", "商洛": "陕西", "铜川": "陕西",
    "宜昌": "湖北", "襄阳": "湖北", "荆州": "湖北", "十堰": "湖北", "黄石": "湖北",
    "鄂州": "湖北", "荆门": "湖北", "孝感": "湖北", "黄冈": "湖北", "咸宁": "湖北",
    "随州": "湖北", "恩施": "湖北",
    "岳阳": "湖南", "常德": "湖南", "衡阳": "湖南", "株洲": "湖南", "湘潭": "湖南",
    "邵阳": "湖南", "郴州": "湖南", "永州": "湖南", "怀化": "湖南", "娄底": "湖南",
    "益阳": "湖南", "张家界": "湖南", "湘西": "湖南",
    "洛阳": "河南", "开封": "河南", "新乡": "河南", "安阳": "河南", "许昌": "河南",
    "平顶山": "河南", "信阳": "河南", "南阳": "河南", "商丘": "河南", "周口": "河南",
    "驻马店": "河南", "焦作": "河南", "濮阳": "河南", "三门峡": "河南", "鹤壁": "河南",
    "漯河": "河南", "济源": "河南",
    "赣州": "江西", "九江": "江西", "上饶": "江西", "宜春": "江西", "吉安": "江西",
    "抚州": "江西", "景德镇": "江西", "萍乡": "江西", "新余": "江西", "鹰潭": "江西",
    "芜湖": "安徽", "蚌埠": "安徽", "安庆": "安徽", "马鞍山": "安徽", "阜阳": "安徽",
    "宿州": "安徽", "六安": "安徽", "滁州": "安徽", "亳州": "安徽", "宣城": "安徽",
    "池州": "安徽", "铜陵": "安徽", "淮北": "安徽", "淮南": "安徽", "黄山": "安徽",
    "徐州": "江苏", "苏州": "江苏", "无锡": "江苏", "常州": "江苏", "南通": "江苏",
    "连云港": "江苏", "淮安": "江苏", "盐城": "江苏", "扬州": "江苏", "镇江": "江苏",
    "泰州": "江苏", "宿迁": "江苏",
    "宁波": "浙江", "温州": "浙江", "嘉兴": "浙江", "湖州": "浙江", "绍兴": "浙江",
    "金华": "浙江", "衢州": "浙江", "舟山": "浙江", "台州": "浙江", "丽水": "浙江",
    "泉州": "福建", "厦门": "福建", "漳州": "福建", "莆田": "福建", "三明": "福建",
    "南平": "福建", "龙岩": "福建", "宁德": "福建",
    "青岛": "山东", "烟台": "山东", "潍坊": "山东", "临沂": "山东", "淄博": "山东",
    "济宁": "山东", "泰安": "山东", "威海": "山东", "日照": "山东", "东营": "山东",
    "德州": "山东", "聊城": "山东", "滨州": "山东", "菏泽": "山东", "枣庄": "山东",
    "东莞": "广东", "佛山": "广东", "珠海": "广东", "中山": "广东", "惠州": "广东",
    "江门": "广东", "汕头": "广东", "湛江": "广东", "肇庆": "广东", "茂名": "广东",
    "揭阳": "广东", "梅州": "广东", "清远": "广东", "韶关": "广东", "阳江": "广东",
    "河源": "广东", "潮州": "广东", "汕尾": "广东", "云浮": "广东",
    "柳州": "广西", "桂林": "广西", "梧州": "广西", "北海": "广西", "玉林": "广西",
    "钦州": "广西", "贵港": "广西", "百色": "广西", "河池": "广西", "来宾": "广西",
    "贺州": "广西", "崇左": "广西", "防城港": "广西",
    "绵阳": "四川", "德阳": "四川", "宜宾": "四川", "泸州": "四川", "南充": "四川",
    "乐山": "四川", "自贡": "四川", "内江": "四川", "遂宁": "四川", "眉山": "四川",
    "广元": "四川", "达州": "四川", "雅安": "四川", "广安": "四川", "巴中": "四川",
    "资阳": "四川", "攀枝花": "四川", "凉山": "四川", "阿坝": "四川", "甘孜": "四川",
    "遵义": "贵州", "六盘水": "贵州", "安顺": "贵州", "毕节": "贵州", "铜仁": "贵州",
    "黔东南": "贵州", "黔南": "贵州", "黔西南": "贵州",
    "大理": "云南", "丽江": "云南", "曲靖": "云南", "玉溪": "云南", "保山": "云南",
    "昭通": "云南", "普洱": "云南", "临沧": "云南", "楚雄": "云南", "红河": "云南",
    "文山": "云南", "西双版纳": "云南", "德宏": "云南", "怒江": "云南", "迪庆": "云南",
    "唐山": "河北", "保定": "河北", "廊坊": "河北", "邯郸": "河北", "邢台": "河北",
    "沧州": "河北", "承德": "河北", "张家口": "河北", "秦皇岛": "河北", "衡水": "河北",
    "大同": "山西", "临汾": "山西", "运城": "山西", "长治": "山西", "晋城": "山西",
    "晋中": "山西", "忻州": "山西", "吕梁": "山西", "朔州": "山西", "阳泉": "山西",
    "大连": "辽宁", "鞍山": "辽宁", "抚顺": "辽宁", "本溪": "辽宁", "丹东": "辽宁",
    "锦州": "辽宁", "营口": "辽宁", "阜新": "辽宁", "辽阳": "辽宁", "盘锦": "辽宁",
    "铁岭": "辽宁", "朝阳": "辽宁", "葫芦岛": "辽宁",
    "吉林市": "吉林", "延边": "吉林", "四平": "吉林", "通化": "吉林", "白山": "吉林",
    "松原": "吉林", "白城": "吉林", "辽源": "吉林",
    "三亚": "海南", "儋州": "海南", "琼海": "海南", "文昌": "海南", "万宁": "海南",
}


def strip_province(addr: str) -> tuple[str, str]:
    """返回 (省规范名, 剥掉省之后的地址)"""
    for p in PROVINCES:
        if addr.startswith(p):
            return PROV_NAME.get(p, p), addr[len(p):]
    for s in sorted(PROV_SHORT, key=len, reverse=True):
        if addr.startswith(s):
            rest = addr[len(s):]
            rest = re.sub(r"^(省|市|自治区|特别行政区)", "", rest)
            return s, rest
    return "", addr


def find_district(addr: str, city: str) -> str:
    """从地址里抽区县；抽到市级地名的一律视为「没有区县」"""
    if not addr:
        return ""
    if city in MUNICIPALITIES:
        # 直辖市地址有 `上海市浦东新区…`、`上海市市辖区徐汇区…`、以及被截断的 `海市浦东新区…`
        rest = addr
        for pre in (city + "市市辖区", city + "市", city, city[1:] + "市"):
            if rest.startswith(pre):
                rest = rest[len(pre):]
                break
        rest = re.sub(r"^市辖区", "", rest)
    else:
        _, rest = strip_province(addr)
        # 剥掉省之后紧跟着的市级名（`杭州市…`、`柳州市…`、`延边朝鲜族自治州…`）
        m = re.match(r"^([\u4e00-\u9fa5]{2,10}?(?:市|自治州|地区|盟))", rest)
        if m:
            rest = rest[m.end():]
        elif rest.startswith(city):
            rest = rest[len(city):]
            rest = re.sub(r"^(市|地区|自治州|盟)", "", rest)

    m = DIST_RE.match(rest)
    if not m:
        return ""
    name = m.group(1)
    # 「市辖区」「省直辖县级行政区划」这种不是真区县；带景区/开发区后缀的也不是
    if name in ("市辖区", "省直辖县级行政区划", "县", "区", "新区"):
        return ""
    if any(w in name for w in ("开发区", "旅游区", "风景区", "工业区", "高新区", "度假区")):
        return ""
    # 兜底：剩下的和城市同名（`杭州市`）也丢掉
    if name.rstrip("市县区") == city:
        return ""
    return name


def load_city_points() -> dict[str, list[dict]]:
    out = {}
    for fn in os.listdir(STATIONS):
        if not fn.endswith(".json"):
            continue
        name = fn[:-5]
        with open(os.path.join(STATIONS, fn), encoding="utf-8") as f:
            arr = json.load(f)
        out[name] = arr if isinstance(arr, list) else arr.get("points", [])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    city_pts = load_city_points()

    # 第一轮：能直接从地址判断的省份
    prov_of_city: dict[str, Counter] = defaultdict(Counter)
    for city, pts in city_pts.items():
        for p in pts:
            addr = p.get("addr") or ""
            if city in MUNICIPALITIES:
                prov_of_city[city][city] += 1
                continue
            prov, _ = strip_province(addr)
            if prov:
                prov_of_city[city][prov] += 1

    provinces = {}
    unknown = []
    for city in city_pts:
        c = prov_of_city.get(city)
        if c:
            provinces[city] = c.most_common(1)[0][0]
        elif city in CITY_PROVINCE_FALLBACK:
            provinces[city] = CITY_PROVINCE_FALLBACK[city]
        else:
            unknown.append(city)

    # 第二轮：整城都没有省名的，返回空让页面自己兜（极少）
    print(f"城市 {len(city_pts)} 个，省份判定成功 {len(provinces)} 个，失败 {len(unknown)} 个")
    if unknown:
        print("  未判定：", unknown[:20])

    pset = Counter(provinces.values())
    print("省份数", len(pset))
    for k, v in sorted(pset.items(), key=lambda x: -x[1]):
        print(f"  {k:6} {v} 个城市")

    # 区县
    districts: dict[str, list[tuple[str, int]]] = {}
    for city, pts in city_pts.items():
        c = Counter()
        for p in pts:
            d = find_district(p.get("addr") or "", city)
            if d:
                c[d] += 1
        districts[city] = c.most_common()

    with_dist = [c for c, v in districts.items() if v]
    print(f"\n有区县信息的城市 {len(with_dist)} 个")
    for probe in ("杭州", "柳州", "上海", "信阳", "深圳"):
        print(f"  {probe}: {districts.get(probe) or '（无）'}")

    if a.check:
        return

    # 写 cities.json：保持原有顺序，补 province
    with open(CITIES, encoding="utf-8") as f:
        cities = json.load(f)
    for c in cities:
        c["province"] = provinces.get(c["name"], "")
    with open(CITIES, "w", encoding="utf-8") as f:
        json.dump(cities, f, ensure_ascii=False, indent=1)

    out = {
        "provinces": sorted({p for p in provinces.values() if p}),
        "districts": {k: [{"name": n, "count": c} for n, c in v] for k, v in districts.items() if v},
    }
    with open(DISTRICTS, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    total_d = sum(len(v) for v in out["districts"].values())
    print(f"\n已写 {CITIES}、{DISTRICTS}")
    print(f"  省份 {len(out['provinces'])} 个，区县共 {total_d} 条，涉及 {len(out['districts'])} 个城市")


if __name__ == "__main__":
    main()
