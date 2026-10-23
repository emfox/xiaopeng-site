# 小鹏免费充电站 · 三层地图

**一句话**：打开一个网页，分三层看小鹏的免费权益站和免费停车站——附近的、全城的、某条线路沿路的。

---

## 数据是真的，不是演示数据

| 项 | 说明 |
|---|---|
| 数据源 | 小鹏官网「免费·专享」页面 `static.xiaopeng.com/apps/charge-web/pc-free-stations.html` |
| 接口 | `chargegateway.xiaopeng.com` 的 `queryMapCityLabeling`（按城市列站）+ `queryStationDtl`（站点详情） |
| 需要登录吗 | **不需要**，公开网页接口 |
| 覆盖 | 44 个城市，**3357 个**免费权益站（自营 2841 / 第三方 516），其中 **2643 个有停车优惠** |
| 完整度 | 地址、价格、桩数 **100% 齐全**，0 个失败 |
| 字段 | 站名、坐标、省市区地址、快充/慢充/超充桩数、电费+服务费、**是否免费权益**、**是否有停车优惠**、是否即插即充 |

> 这比高德上的小鹏站全，是因为高德只拿到 POI 坐标，而「免费权益」「停车优惠」这两个字段只有小鹏自己的数据里有。

---

## 怎么用

### 打开页面

**方式一（推荐）：起个本地服务**

```bash
cd out && python3 -m http.server 8000
# 浏览器打开 http://localhost:8000/charge_map.html
```

**方式二：双击 HTML**
页面会回退到内联快照（单文件版才带）。分离版双击会提示起服务，这是浏览器的安全限制，不是 bug。

**方式三：在线访问**（开启 GitHub Pages 后）
`https://emfox.github.io/xiaopeng-site/`

手机上打开会自动切换成底部面板布局。

> 想临时换一份数据集，地址栏加参数即可：`...?data=别的.json`

### ① 附近
自动定位你当前位置，默认 **5 km** 内的站。虚线圆 = 距离圈，可选 3/5/10/20 km 或不限。
> 浏览器会问定位权限，拒绝的话用城市中心代替，不影响使用。

### ② 全城
选城市（下拉里有 44 个），看全市所有站，再按区县细分。列表按离市中心远近排序。
> 定位成功后会自动切到你所在的城市，不用手动选。

### ③ 沿路线
选起点和终点城市，自动套用**高德真实驾车路线**（走真实高速，不是直线），然后：
- **默认给出 3 个推荐停靠站**——按里程把全程均分三段，每段挑「离高速最近 + 有停车优惠 + 自营」的那个
- 拖下面的**行程进度条**，看开到某一段时附近有哪些站
- 点底部按钮，**一键把 3 个站作为途经点发到高德 App**（手机上会直接唤起高德导航）

已内置 9 条真实路线：杭州⇄上海、上海→苏州、上海→南京、上海→宁波、北京→天津、广州→深圳、杭州→宁波、苏州→杭州。

> **手机端**：面板占下方约 58%，地图会自动把路线/站点顶到上方可见区，不会被面板压住。

三个层级都可以叠加筛选：`小鹏免费权益` / `第三方合作` / `仅看免费停车`。

---

## 更新数据（建议 1~2 个月一次）

```bash
# 抓全国 44 城，含地址/价格/停车优惠（约 15 分钟）
python3 fetch_xpeng.py --with-detail --out data/stations.json

# 只抓你常走的城市，快得多
python3 fetch_xpeng.py --cities 杭州,上海,苏州 --with-detail --out data/mine.json

# 生成页面（数据与页面分离：index.html 约 34 KB + data.json 约 1.1 MB）
python3 charge_map.py --data data/stations.json \
  --routes data/route_*.json --out out/charge_map.html

# 想要「双击即用」的单文件版（数据内联，约 2 MB）
python3 charge_map.py --data data/stations.json \
  --routes data/route_*.json --out out/single.html --single-file
```

路线数据（可选，加了才有真实高速线）：
```bash
python3 get_route.py --from-city 杭州 --to-city 上海 --out data/route_hz_sh.json
```

---

## 文件说明

| 文件 | 作用 |
|---|---|
| `index.html` / `out/charge_map.html` | **页面本体**，约 34 KB，不含数据 |
| `data.json` / `out/data.json` | **页面数据**，约 1.1 MB，可直接编辑 |
| `fetch_xpeng.py` | 抓小鹏官方免费站数据（分片落盘、可断点续抓） |
| `fetch_fast.py` | 多线程补抓详情，比逐个抓快 10 倍以上 |
| `get_route.py` | 取高德真实驾车路线（免 key） |
| `charge_map.py` | 把数据 + 路线合成页面和 data.json |
| `template.html` | 页面模板（三层视图 + 高德 JS API，不含数据） |
| `data/stations.json` | 采集产出的原始数据（无路线，未补 city） |
| `data/route_*.json` | 真实路线数据 |
| `legacy/` | 早期版本（导出 Excel/KML/CSV 的路线），仅作留档 |

---

## 为什么数据和页面要分开

原先数据被 inline 写进 HTML，1.7 MB 的文件里有 96% 是 JSON，导致：

- 改一条数据要重新生成整个页面，git 里永远是一次全量 diff
- 浏览器没法单独缓存数据
- 没法用别的前端消费同一份数据

现在页面只管渲染，数据独立成 `data.json`。想手工改某个站的价格或名称，直接编辑 json 就行，刷新页面即生效。

---

## 目录结构

```
.
├── index.html               # 34 KB 页面本体（Pages 首页）
├── data.json                # 1.1 MB 页面数据
├── out/
│   ├── charge_map.html      # 同 index.html
│   └── data.json            # 同根目录 data.json
├── fetch_xpeng.py           # 采集
├── fetch_fast.py            # 并发补抓
├── get_route.py             # 取路线
├── charge_map.py            # 合成页面 + data.json
├── template.html            # 模板
├── data/
│   ├── stations.json        # 采集原始数据
│   └── route_*.json         # 9 条真实路线
└── legacy/                  # 早期产物（不参与构建）
```


---

## 已知限制

1. **接口是网页版的内部接口**，小鹏改版就可能失效。失效时 `fetch_xpeng.py` 会报错，重新从页面抓一次请求路径，改脚本里那两个 path 即可。
2. **只有「免费权益」站**。如果想看全部小鹏合作站（不免费的），要换 `filterCriteriaCodeList` 参数，可以再加。
3. **页面用的是高德官方页面前端 Key**，能用但不保证长期有效。长期用建议去[高德开放平台](https://console.amap.com/dev/key/app)申请自己的 JS API Key，然后 `export AMAP_JS_KEY=你的key`。
4. **停车优惠**是小鹏标注的「有停车优惠」，具体免几小时、是否限车型，到站后看现场说明或小鹏 App 站点详情。
5. **路线是城市中心到城市中心的驾车路线**。要从具体地址出发，用 `get_route.py --from 坐标 --to 坐标` 重算。

---

## 关于抓数据这件事

这是小鹏官网对公众开放的页面在正常浏览时发出的请求，相当于把「人肉一页页翻城市地图」变成脚本跑一遍。建议：
- 保持现在的节奏（0.3 秒一次），不要并发狂刷
- 数据自己用，不要二次分发或商用
- 需要商用/对外服务，走小鹏商务合作
