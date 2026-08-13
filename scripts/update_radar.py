# -*- coding: utf-8 -*-
"""云端热点雷达生成器（零 API Key 版）
抓取免费公开财经资讯源（RSS/公开JSON），关键词规则打标为 v5 契约（含 region 国内/国外），
输出 data/radar.json。stdlib-only，可直接在 GitHub Actions ubuntu 运行。
用法: python3 scripts/update_radar.py [--out data/radar.json] [--days 31]
"""
import json, os, re, sys, ssl, gzip, argparse, datetime as dt
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

TZ = dt.timezone(dt.timedelta(hours=8))  # Asia/Shanghai
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) radar-daily/1.0"}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

FEEDS = [
    ("华尔街见闻", "https://dedicated.wallstreetcn.com/rss.xml"),
    ("新浪财经·财经要闻", "https://rss.sina.com.cn/roll/finance/hot_roll.xml"),
    ("BBC中文·财经", "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml"),
    ("FT中文网", "https://www.ftchinese.com/rss/news"),
    ("联合早报·即时中国", "https://www.zaobao.com.sg/rss/realtime/china"),
    ("联合早报·即时财经", "https://www.zaobao.com.sg/rss/realtime/finance"),
    ("36氪", "https://36kr.com/feed"),
    ("cnBeta", "https://www.cnbeta.com.tw/backend.php"),
    ("财联社电报(RSSHub)", "https://rsshub.app/cls/telegraph"),
    ("澎湃新闻", "https://rsshub.app/thepaper/featured"),
]

# subDim -> 关键词（命中即归类，按优先级从高到低尝试）
RULES = [
    ("一级宏观", "货币流动性", ["央行", "逆回购", "MLF", "降准", "降息", "LPR", "流动性", "国债收益率", "DR007", "买断式", "资金面"]),
    ("一级宏观", "宏观经济数据", ["GDP", "CPI", "PPI", "PMI", "社融", "进出口", "出口", "零售额", "工业增加值", "失业率", "经济数据"]),
    ("一级宏观", "顶层政策规划", ["政治局", "国常会", "国务院常务会议", "十五五", "五年规划", "全会", "会议指出", "中央经济工作会议"]),
    ("一级宏观", "全球重大地缘", ["美联储", "加息", "特朗普", "关税", "地缘", "伊朗", "俄乌", "霍尔木兹", "中东", "美股", "纳斯达克", "标普", "道指", "制裁"]),
    ("一级宏观", "重大突发事件", ["突发", "地震", "爆炸", "事故", "紧急状态", "袭击"]),
    ("三级资金面", "北向与两融", ["北向资金", "沪深股通", "融资余额", "两融", "南向资金", "南下资金", "开户"]),
    ("三级资金面", "ETF资金与调样", ["ETF", "指数调样", "净申购"]),
    ("三级资金面", "公募申赎与爆款", ["公募基金", "新发基金", "募集", "申赎", "爆款基金", "理财产品", "存款搬家"]),
    ("三级资金面", "发行与交易规则", ["交易规则", "注册制", "退市", "涨跌幅", "T+0"]),
    ("三级资金面", "机构持仓与险资", ["险资", "社保基金", "增持", "减持", "持仓", "私募", "QFII", "主力资金", "回购"]),
    ("四级个股龙头", "业绩预告与暴雷", ["业绩预告", "预增", "预亏", "净利润", "中报", "年报", "一季报", "三季报", "暴雷", "亏损", "扭亏"]),
    ("四级个股龙头", "并购重组", ["并购", "重组", "收购", "借壳", "资产注入"]),
    ("四级个股龙头", "月度经营数据", ["销量", "出货量", "交付量", "订单", "经营数据", "产销"]),
    ("四级个股龙头", "龙头产品发布", ["发布", "新品", "发布会", "上市首日", "申购", "询价", "招股"]),
    ("二级产业", "顶层产业扶持政策", ["扶持政策", "补贴", "行动方案", "指导意见", "产业政策", "支持.*产业", "人工智能\\+"]),
    ("二级产业", "行业监管调整", ["监管", "处罚", "新规", "立案", "国标", "强制性标准", "规范", "整治"]),
    ("二级产业", "行业周期拐点", ["拐点", "景气", "涨价", "库存", "周期", "复苏", "回暖", "修复"]),
    ("二级产业", "产业重磅事件", ["大会", "IPO", "量产", "突破", "签约", "开工", "投产", "首飞", "首航"]),
]

SECTOR_KWS = ["人工智能", "AI", "半导体", "芯片", "存储", "算力", "机器人", "新能源", "光伏", "储能", "电池",
              "医药", "创新药", "CXO", "军工", "黄金", "有色", "地产", "消费", "白酒", "银行", "券商", "保险",
              "汽车", "智能驾驶", "低空经济", "核电", "电力", "煤炭", "钢铁", "航运", "农业", "游戏", "传媒",
              "通信", "CPO", "光模块", "云计算", "大数据", "量子", "商业航天"]

# 地区口径（契约 v5）：海外关键词命中数 > 国内关键词命中数 → 国外；国内有命中 → 国内；
# 均无命中时按信源兜底（海外媒体默认国外，其余默认国内）
FOREIGN_KWS = ["美国", "美联储", "特朗普", "美股", "纳斯达克", "标普", "道指", "美元", "美债", "英伟达",
               "特斯拉", "苹果", "微软", "谷歌", "亚马逊", "Meta", "OpenAI", "欧盟", "欧洲", "欧洲央行",
               "英国央行", "日本", "日经", "日元", "韩国", "三星", "海力士", "台积电", "印度", "越南",
               "俄罗斯", "乌克兰", "伊朗", "中东", "欧佩克", "沙特", "巴菲特", "摩根大通", "高盛", "花旗",
               "SpaceX", "马斯克", "AMD", "英特尔", "诺和诺德", "丰田", "日产", "香奈儿", "LVMH", "Lucid",
               "Google", "Pixel", "iPhone", "Grok", "Twitch", "Coherent", "思科", "Nebius", "OPEC"]
DOMESTIC_KWS = ["中国", "A股", "沪指", "上证", "深证", "创业板", "科创板", "港股", "恒指", "中概", "央行",
                "国务院", "政治局", "国常会", "发改委", "证监会", "财政部", "工信部", "商务部", "北向",
                "南向", "人民币", "公募", "十五五", "国产", "城投", "国资", "内地"]
FOREIGN_FEEDS = {"BBC中文·财经", "FT中文网"}

DIM_PRODUCT = {
    "一级宏观": ["通用"],
    "二级产业": ["主动权益", "指数增强"],
    "三级资金面": ["指数增强"],
    "四级个股龙头": ["主动权益"],
}
HIGH_KWS = ["央行", "政治局", "美联储", "降准", "降息", "国常会", "十五五", "暴涨", "暴跌", "创新高", "创新低"]
LOW_KWS = ["据悉", "传闻", "或", "小幅"]

TAG_RE = re.compile(r"<[^>]+>")


def fetch(url):
    req = urllib.request.Request(url, headers={**UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return raw


def to_text(raw):
    for enc in ("utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", "replace")


CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def parse_feed(name, url, since):
    items = []
    try:
        raw = fetch(url)
    except Exception as e:
        print(f"[feed] {name} 抓取失败: {e}")
        return items
    try:
        text = CTRL_RE.sub("", to_text(raw))
        root = ET.fromstring(text)
        nodes = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
        rows = []
        for it in nodes[:80]:
            def txt(*tags, _it=it):
                for t in tags:
                    el = _it.find(t)
                    if el is not None and el.text:
                        return el.text.strip()
                    el = _it.find("{http://www.w3.org/2005/Atom}" + t.split(":")[-1])
                    if el is not None and el.text:
                        return el.text.strip()
                return ""
            rows.append((txt("title"), txt("description", "summary", "content"),
                         txt("pubDate", "date", "published", "updated", "dc:date")))
    except Exception:
        # 兜底：非严格 XML 用正则粗解析 <item> 块
        text = CTRL_RE.sub("", to_text(raw))
        blocks = re.findall(r"<item\b.*?</item>", text, re.S)[:80]
        is_atom = False
        if not blocks:
            blocks = re.findall(r"<entry\b.*?</entry>", text, re.S)[:80]
            is_atom = True
        rows = []
        for b in blocks:
            def grab(tag, _b=b):
                m = re.search(r"<%s[^>]*>(.*?)</%s>" % (tag, tag), _b, re.S)
                if not m:
                    return ""
                s = m.group(1).strip()
                s = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", s, flags=re.S)
                return TAG_RE.sub("", s).strip()
            date_str = grab("pubDate") or grab("date") or grab("dc:date")
            if is_atom:
                date_str = date_str or grab("published") or grab("updated")
                desc_str = grab("summary") or grab("content")
            else:
                desc_str = grab("description")
            rows.append((grab("title"), desc_str, date_str))
        if not rows:
            print(f"[feed] {name} 解析失败（严格+兜底均无条目）")
            return items
    for title_raw, desc_raw, ds in rows:
        title = TAG_RE.sub("", title_raw).strip()
        desc = TAG_RE.sub("", desc_raw).strip()[:200]
        if not title:
            continue
        try:
            when = parsedate_to_datetime(ds).astimezone(TZ)
        except Exception:
            try:
                when = dt.datetime.fromisoformat(ds.replace("Z", "+00:00")).astimezone(TZ)
            except Exception:
                when = dt.datetime.now(TZ)
        if when < since:
            continue
        items.append({"title": title, "desc": desc[:200], "when": when, "feed": name})
    print(f"[feed] {name}: {len(items)} 条候选")
    return items


def classify(text):
    for dim, sub, kws in RULES:
        for kw in kws:
            if re.search(kw, text):
                return dim, sub
    return None, None


def priority_of(text):
    if any(k in text for k in HIGH_KWS):
        return "高"
    if any(k in text for k in LOW_KWS):
        return "低"
    return "中"


def sectors_of(text):
    hits = [s for s in SECTOR_KWS if s in text]
    return "、".join(hits[:4]) if hits else "全市场"


def region_of(text, feed):
    fs = sum(1 for k in FOREIGN_KWS if k in text)
    ds = sum(1 for k in DOMESTIC_KWS if k in text)
    if fs > ds:
        return "国外"
    if ds > 0:
        return "国内"
    return "国外" if feed in FOREIGN_FEEDS else "国内"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/radar.json")
    ap.add_argument("--days", type=int, default=31)
    args = ap.parse_args()

    now = dt.datetime.now(TZ)
    today = now.date()
    since = dt.datetime.combine(today - dt.timedelta(days=args.days), dt.time.min, TZ)
    week_ago = today - dt.timedelta(days=7)

    cands = []
    for name, url in FEEDS:
        cands.extend(parse_feed(name, url, since))

    seen, events = set(), []
    for c in sorted(cands, key=lambda x: x["when"], reverse=True):
        key = re.sub(r"\W", "", c["title"])[:30]
        if key in seen:
            continue
        seen.add(key)
        text = c["title"] + " " + c["desc"]
        dim, sub = classify(text)
        if not dim:
            continue
        d = c["when"].date()
        title = c["title"]
        if len(title) > 60:
            title = title[:58] + "…"
        events.append({
            "date": d.strftime("%m-%d"),
            "region": region_of(text, c["feed"]),
            "timeBucket": "近一周" if d >= week_ago else "本月",
            "dim": dim, "subDim": sub,
            "priority": priority_of(text),
            "title": title,
            "productLines": DIM_PRODUCT[dim],
            "sectors": sectors_of(text),
            "source": f"{c['feed']}（{d.strftime('%m-%d')}）",
        })
        if len(events) >= 40:
            break

    # topTopics：每个 dim 取一条最高优先级的近一周事件
    topics = []
    for dim in ["一级宏观", "二级产业", "三级资金面", "四级个股龙头"]:
        pool = [e for e in events if e["dim"] == dim and e["timeBucket"] == "近一周"] or \
               [e for e in events if e["dim"] == dim]
        if not pool:
            continue
        best = sorted(pool, key=lambda e: {"高": 0, "中": 1, "低": 2}[e["priority"]])[0]
        t = best["title"][:20]
        topics.append({"dim": dim, "title": t,
                       "note": f"{best['subDim']}方向，关注{best['sectors']}，可做联合运营专题（云端自动归纳）"[:60]})

    data = {
        "kind": "radar",
        "asOf": today.isoformat(),
        "window": f"近一月，重点近一周，截至{today.isoformat()}（云端零Key自动版）",
        "topTopics": topics,
        "events": events,
    }

    # 契约校验（v5：含 region）
    REQ = ["date", "region", "timeBucket", "dim", "subDim", "priority", "title", "productLines", "sectors", "source"]
    DIMS = {"一级宏观", "二级产业", "三级资金面", "四级个股龙头"}
    for e in events:
        assert list(e.keys()) == REQ
        assert e["region"] in ("国内", "国外")
        assert e["timeBucket"] in ("近一周", "本月") and e["dim"] in DIMS
        assert e["priority"] in ("高", "中", "低")
    print(f"[validate] OK: {len(events)} events, {len(topics)} topTopics")
    if len(events) < 10:
        print("[warn] 事件数偏少，请检查资讯源可用性")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[done] {args.out} written ({os.path.getsize(args.out)} bytes), asOf={data['asOf']}")


if __name__ == "__main__":
    main()
