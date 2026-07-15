# -*- coding: utf-8 -*-
"""
新鲜度/完整性校验 v2.2
支持全量校验（最终 QA 门）和按节校验（建站时每节写完后即时验证）。
两种模式共用同一套校验逻辑——freshness_check 是唯一的内容验证器，
checkpoint 只记"哪节已通过"，不做独立判断。

共 33 项检查 / 14 节（含 prices_{date}.md 数值交叉验证）：
  meta(2) · head(2) · tape(3) · hero(2) · summary(1) · stance(1)
  I-radar(1) · II-market(3) · III-tech(6) · IV-macro(3)
  V-earnings(2) · VI-stocks(4) · VII-people(2) · finale(2)

用法:
  python freshness_check.py <YYYY-MM-DD>                      # 全量（最终 QA 门）
  python freshness_check.py <YYYY-MM-DD> --section IV-macro   # 单节（建站写完即验）
  python freshness_check.py <YYYY-MM-DD> --list-sections      # 列出所有节与检查项
  --html <path>  覆盖默认 HTML 路径
  --md  <path>   覆盖默认 md 路径

节标识符（建站顺序，建站时按此顺序处理每节后立即 --section 校验）:
  meta · head · tape · hero · summary · stance
  I-radar · II-market · III-tech · IV-macro
  V-earnings · VI-stocks · VII-people · finale

退出码: 0 = 通过  1 = 有失败项  2 = 用法错误

变更史:
  v2.3 (2026-07-15): 修 _chk_stocks_dd_series：dd-series 文件缺失/日期错配曾静默跳过；
        新增 _chk_stocks_dd_build 校验 buildDD() 硬编码 ticker 数组 vs HTML 容器 id
        （07-14 事故根因：buildDD 仍写旧标的，HTML 容器已换新标的，图表全部空白）。
        VI-stocks 增至 4 项，总计 33 项。
  v2.2 (2026-07-09): 修 _load_prices 正则——「⚠️触发」中文后缀致 CL=F/BZ=F pct
        静默取空，改为 [^|]+? + re.search，现能正确解析所有触发标的。
  v2.1 (2026-07-08): 加 4 项仪表盘 gauge JS vs cp-note 校验（III-tech 共 6 项）；
        V-earnings 改用 desc 日期比对（取代首行比对，无财报日不再误报）；加 callout 日期校验。
  v2.0 (2026-07-07): 初版，14 节 28 项，支持 --section，加 prices 交叉验证。

背景: 2026-06 起因 session 中断，宏观地缘/重点个股/关键人物等节静默继承旧页，
四件套机械检查均通过；此脚本补覆盖所有节的内容校验，与 checkpoint 机制配合。
"""
import re, sys, os, glob, argparse

SITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 网站/

# ── 节顺序（建站时按此顺序依次处理，每节完成后即时 --section 校验）─────────────
SECTION_ORDER = [
    "meta", "head", "tape", "hero", "summary", "stance",
    "I-radar", "II-market", "III-tech", "IV-macro",
    "V-earnings", "VI-stocks", "VII-people", "finale",
]


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _snap(pat, src, dotall=True, strip_tags=False):
    """提取正则第 1 组，可选剥 HTML 标签"""
    flags = re.DOTALL if dotall else 0
    m = re.search(pat, src, flags)
    if not m:
        return None
    s = m.group(1).strip()
    if strip_tags:
        s = re.sub(r'<[^>]+>', ' ', s).strip()
    return s


def _pct_close(a, b, tol=0.15):
    """百分比近似比对，容差 tol pp；处理 − (U+2212) vs - 混用及 ⚠️ 等后缀"""
    def norm(s):
        s = s.replace('−', '-').replace('%', '').strip()
        s = re.sub(r'[^\d.\-]', '', s)
        return float(s)
    try:
        return abs(norm(a) - norm(b)) <= tol
    except Exception:
        return False


def _load_prices(date):
    """解析 prices_{date}.md → {symbol: {'level': str, 'pct': str}}
    prices 文件格式: | 中文名 | SYMBOL | 价格/水平 | 涨跌幅 |"""
    path = os.path.join(SITE_DIR, "..", "自动日报", "data", f"prices_{date}.md")
    if not os.path.exists(path):
        return {}
    result = {}
    for line in open(path, encoding="utf-8"):
        # 匹配四列的表格行（跳过分割线和标题）
        # 第4列允许任意非管道字符，再单独提取 [+-]数字% 以兼容「⚠️触发」中文后缀
        m = re.match(
            r'\|\s*[^|]+\|\s*([^\s|]+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|',
            line
        )
        if not m:
            continue
        sym = m.group(1).strip()
        level = m.group(2).strip().strip('*').replace(',', '')
        raw_pct = m.group(3).strip()
        pm = re.search(r'([+\-]\d+\.?\d*%)', raw_pct)
        pct = pm.group(1) if pm else ''
        if sym and re.match(r'[\^A-Z=\-\.]+', sym):
            result[sym] = {'level': level, 'pct': pct}
    return result


def _get_prev(date):
    """返回 (prev_html_text, prev_label)，找不到则返回 (None, None)"""
    cands = sorted(glob.glob(os.path.join(SITE_DIR, "????-??-??.html")))
    cands = [p for p in cands if os.path.basename(p) < f"{date}.html"]
    if not cands:
        return None, None
    label = os.path.basename(cands[-1]).replace(".html", "")
    return open(cands[-1], encoding="utf-8").read(), label


# ── 校验函数：fn(date, html, md, prices, prev, prev_label) → None | str ───────

# ——— meta ———
def _chk_cutoff(date, html, md, prices, prev, plabel):
    m = re.search(r'var CUTOFF="([\d-]+)"', html)
    if not m or m.group(1) != date:
        return f"CUTOFF={m.group(1) if m else '未找到'}，应为 {date}"

def _chk_data_thru(date, html, md, prices, prev, plabel):
    y, mo, d = date.split("-")
    expect = f"{y} 年 {int(mo)} 月 {int(d)} 日"
    errs = []
    for m in re.finditer(r'数据截至 ([^<]+?)收盘', html):
        if expect not in m.group(1):
            errs.append(m.group(1).strip())
    if errs:
        return f"「数据截至」含旧日期 {errs}，应含「{expect}」"

# ——— head ———
def _chk_head_title(date, html, md, prices, prev, plabel):
    if not prev:
        return None
    cur = _snap(r'<title>([^<]+)', html, dotall=False)
    prv = _snap(r'<title>([^<]+)', prev, dotall=False)
    if cur and prv and cur.strip() == prv.strip():
        return f"<title> 与 {plabel} 相同（head 未更新）：「{cur.strip()[:60]}」"

def _chk_head_desc(date, html, md, prices, prev, plabel):
    if not prev:
        return None
    cur = _snap(r'<meta name="description" content="([^"]+)"', html, dotall=False)
    prv = _snap(r'<meta name="description" content="([^"]+)"', prev, dotall=False)
    if cur and prv and cur == prv:
        return f"<meta description> 与 {plabel} 相同（head 未更新）"

# ——— tape ———
def _chk_tape_date(date, html, md, prices, prev, plabel):
    m = re.search(r'(\d{4}-\d{2}-\d{2}) 美东收盘', html)
    if not m or m.group(1) != date:
        return f"跑马灯日期戳={m.group(1) if m else '未找到'}，应为 {date}"

def _chk_tape_vix(date, html, md, prices, prev, plabel):
    """跑马灯 VIX 硬编码值 vs 技术面 stat-grid VIX（两者应一致）"""
    tape = _snap(r'"tk">VIX</span><span class="num">([\d.]+)', html, dotall=False)
    stat = _snap(r'VIX 恐慌指数</div><div class="v"[^>]*>([\d.]+)', html, dotall=False)
    if tape and stat and not _pct_close(tape, stat, tol=0.01):
        return f"跑马灯 VIX {tape} ≠ stat-grid VIX {stat}（跑马灯硬编码未与 stat-grid 同步）"

def _chk_tape_fg(date, html, md, prices, prev, plabel):
    """跑马灯 F&G 硬编码值 vs 技术面 stat-grid F&G（两者应一致）"""
    tape = _snap(r'恐惧贪婪指数</span><span[^>]*>([\d.]+)', html, dotall=False)
    stat = _snap(r'CNN 恐惧贪婪指数</div><div class="v"[^>]*>([\d.]+)', html, dotall=False)
    if tape and stat and not _pct_close(tape, stat, tol=0.1):
        return f"跑马灯 F&G {tape} ≠ stat-grid F&G {stat}（跑马灯硬编码未与 stat-grid 同步）"

# ——— hero ———
def _chk_hero_theme(date, html, md, prices, prev, plabel):
    if not prev:
        return None
    cur = _snap(r'hero-theme-text[^>]*>(.*?)</(?:div|p|h\d)>', html, strip_tags=True)
    prv = _snap(r'hero-theme-text[^>]*>(.*?)</(?:div|p|h\d)>', prev, strip_tags=True)
    if cur and prv and cur == prv:
        return f"hero-theme-text 与 {plabel} 相同（hero 未更新）：「{cur[:60]}」"

def _chk_hero_color(date, html, md, prices, prev, plabel):
    """方向色：GSPC 跌日 hero-inner 应含 --accent:var(--red)"""
    gspc_pct = prices.get('^GSPC', {}).get('pct', '')
    if not gspc_pct:
        return None
    try:
        is_down = float(gspc_pct.replace('%', '').replace('−', '-')) < 0
    except Exception:
        return None
    m = re.search(r'class="hero-inner"[^>]*style="([^"]*)"', html)
    style = m.group(1) if m else ''
    if is_down and 'var(--red)' not in style:
        return f"今日 GSPC {gspc_pct}（跌），hero-inner 未见 var(--red)（方向色未更新）"
    if not is_down and 'var(--red)' in style:
        return f"今日 GSPC {gspc_pct}（涨），hero-inner 含 var(--red)（方向色未更新）"

# ——— summary ———
def _chk_summary(date, html, md, prices, prev, plabel):
    if not prev:
        return None
    cur = _snap(r'class="sum-card"[^>]*>.*?<h3>([^<]+)', html)
    prv = _snap(r'class="sum-card"[^>]*>.*?<h3>([^<]+)', prev)
    if cur and prv and cur.strip() == prv.strip():
        return f"摘要首卡标题与 {plabel} 相同（摘要未更新）：「{cur.strip()[:60]}」"

# ——— stance ———
def _chk_stance(date, html, md, prices, prev, plabel):
    if not prev:
        return None
    cur = _snap(r'stance-tone[^>]*>(.*?)</div>', html, strip_tags=True)
    prv = _snap(r'stance-tone[^>]*>(.*?)</div>', prev, strip_tags=True)
    if cur and prv and cur == prv:
        return f"研判定调与 {plabel} 相同（今日研判未更新）：「{cur[:60]}」"

# ——— I-radar ———
def _chk_radar(date, html, md, prices, prev, plabel):
    if not prev:
        return None
    cur = _snap(r'id="page-radar".*?<tbody>(.*?)</tr>', html, strip_tags=True)
    prv = _snap(r'id="page-radar".*?<tbody>(.*?)</tr>', prev, strip_tags=True)
    if cur and prv and cur[:80].strip() == prv[:80].strip():
        return f"事件雷达首条与 {plabel} 相同（I-radar 未更新）"

# ——— II-market ———
def _chk_market_core(date, html, md, prices, prev, plabel):
    if not prev:
        return None
    cur = _snap(r'核心读法[：:]</strong>(.*?)</div>', html, strip_tags=True)
    prv = _snap(r'核心读法[：:]</strong>(.*?)</div>', prev, strip_tags=True)
    if cur and prv and cur == prv:
        return f"大盘总览核心读法与 {plabel} 相同（II-market 未更新）：「{cur[:60]}」"

def _chk_market_gspc(date, html, md, prices, prev, plabel):
    pct = prices.get('^GSPC', {}).get('pct', '')
    if not pct:
        return None
    html_pct = _snap(r'标普 500.*?<span class="val[^"]*">([-−+\d.]+%)</span>', html)
    if html_pct and not _pct_close(html_pct, pct):
        return f"大盘总览 GSPC 涨跌幅 HTML={html_pct} vs prices={pct}"

def _chk_market_ixic(date, html, md, prices, prev, plabel):
    pct = prices.get('^IXIC', {}).get('pct', '')
    if not pct:
        return None
    html_pct = _snap(r'纳斯达克综合.*?<span class="val[^"]*">([-−+\d.]+%)</span>', html)
    if html_pct and not _pct_close(html_pct, pct):
        return f"大盘总览 IXIC 涨跌幅 HTML={html_pct} vs prices={pct}"

# ——— III-tech ———
def _chk_tech_vix(date, html, md, prices, prev, plabel):
    if not prev:
        return None
    cur = _snap(r'VIX 恐慌指数</div><div class="v"[^>]*>([\d.]+)', html, dotall=False)
    prv = _snap(r'VIX 恐慌指数</div><div class="v"[^>]*>([\d.]+)', prev, dotall=False)
    if cur and prv and cur == prv:
        return f"技术面 stat-grid VIX {cur} 与 {plabel} 相同（III-tech 未更新）"

def _chk_tech_fg(date, html, md, prices, prev, plabel):
    if not prev:
        return None
    cur = _snap(r'CNN 恐惧贪婪指数</div><div class="v"[^>]*>([\d.]+)', html, dotall=False)
    prv = _snap(r'CNN 恐惧贪婪指数</div><div class="v"[^>]*>([\d.]+)', prev, dotall=False)
    if cur and prv and cur == prv:
        return f"技术面 stat-grid F&G {cur} 与 {plabel} 相同（III-tech 未更新）"

def _chk_tech_gauge_vix(date, html, md, prices, prev, plabel):
    """仪表盘 VIX gauge JS 指针值 vs cp-note 文字值（复制旧页后 gauge JS 常被遗漏）"""
    gauge = _snap(r'getElementById\("gVIX"\)\s*,\s*gaugeOpt\(([\d.]+)', html, dotall=False)
    note  = _snap(r'id="gVIX".*?cp-note">([\d.]+)', html)
    if gauge and note and not _pct_close(gauge, note, tol=0.01):
        return f"仪表盘 VIX 指针={gauge} ≠ cp-note={note}（gauge JS 未同步）"

def _chk_tech_gauge_fg(date, html, md, prices, prev, plabel):
    """仪表盘 F&G gauge JS 指针值 vs cp-note 文字值"""
    gauge = _snap(r'getElementById\("gFG"\)\s*,\s*gaugeOpt\(([\d.]+)', html, dotall=False)
    note  = _snap(r'id="gFG".*?cp-note">([\d.]+)', html)
    if gauge and note and not _pct_close(gauge, note, tol=0.1):
        return f"仪表盘 F&G 指针={gauge} ≠ cp-note={note}（gauge JS 未同步）"

def _chk_tech_gauge_rsi(date, html, md, prices, prev, plabel):
    """仪表盘 RSI gauge JS 指针值 vs cp-note 文字值"""
    gauge = _snap(r'getElementById\("gRSI"\)\s*,\s*gaugeOpt\(([\d.]+)', html, dotall=False)
    note  = _snap(r'id="gRSI".*?cp-note">([\d.]+)', html)
    if gauge and note and not _pct_close(gauge, note, tol=0.1):
        return f"仪表盘 RSI 指针={gauge} ≠ cp-note={note}（gauge JS 未同步）"

def _chk_tech_gauge_br(date, html, md, prices, prev, plabel):
    """仪表盘广度(BR) gauge JS 指针值 vs cp-note 文字值（可为负；含 U+2212 处理）"""
    gauge    = _snap(r'getElementById\("gBR"\)\s*,\s*gaugeOpt\(([-\d.]+)', html, dotall=False)
    note_raw = _snap(r'id="gBR".*?cp-note">([+\-\d.−]+)pp', html)
    if not gauge or not note_raw:
        return None
    note = note_raw.replace('−', '-').replace('+', '')
    try:
        if abs(float(gauge) - float(note)) > 0.01:
            return f"仪表盘广度指针={gauge}pp ≠ cp-note={note_raw}（gauge JS 未同步）"
    except Exception:
        pass

# ——— IV-macro ———
def _chk_macro_desc(date, html, md, prices, prev, plabel):
    if not prev:
        return None
    cur = _snap(r'id="page-macro".*?class="desc">([^<]{10,})', html)
    prv = _snap(r'id="page-macro".*?class="desc">([^<]{10,})', prev)
    if cur and prv and cur.strip() == prv.strip():
        return f"宏观地缘 desc 与 {plabel} 相同（IV-macro 未更新）：「{cur.strip()[:60]}」"

def _chk_macro_wti(date, html, md, prices, prev, plabel):
    """宏观地缘 WTI 涨跌幅 vs prices 文件"""
    pct = prices.get('CL=F', {}).get('pct', '')
    if not pct:
        return None
    # 匹配 WTI 表格行中价格列之后的涨跌幅列
    html_pct = _snap(
        r'原油 WTI.*?<td class="num[^"]*"><strong>\$[^<]+</strong></td>'
        r'<td class="num[^"]*"><strong>([+\-\d.]+%)',
        html
    )
    if html_pct and not _pct_close(html_pct, pct):
        return f"宏观地缘 WTI 涨跌幅 HTML={html_pct} vs prices={pct}"

def _chk_macro_10y(date, html, md, prices, prev, plabel):
    """宏观地缘 10Y 收益率绝对值 vs prices 文件"""
    tnx = prices.get('^TNX', {})
    level = tnx.get('level', '').rstrip('%')
    if not level:
        return None
    html_level = _snap(r'10Y 美债</td><td class="num"><strong>([\d.]+)%', html, dotall=False)
    if html_level:
        try:
            if abs(float(html_level) - float(level)) > 0.005:
                return f"宏观地缘 10Y HTML={html_level}% vs prices={level}%"
        except Exception:
            pass

# ——— V-earnings ———
def _chk_earnings(date, html, md, prices, prev, plabel):
    """V-earnings desc 中的日期应为今日 M/D（比首行比对更可靠——无财报日首行相同）"""
    _, mo, d = date.split("-")
    expected = f"{int(mo)}/{int(d)}"
    got = _snap(r'id="page-earnings".*?class="desc">今日（(\d+/\d+)）', html)
    if got is None:
        return None
    if got != expected:
        return f"V-earnings desc 日期「{got}」≠ 今日「{expected}」（财报节 desc 未更新）"

def _chk_earnings_callout(date, html, md, prices, prev, plabel):
    """V-earnings callout 内嵌日期应为今日"""
    got = _snap(r'今日财报排查结论.*?(\d{4}-\d{2}-\d{2}) 重点追踪', html)
    if got is None:
        return None
    if got != date:
        return f"V-earnings callout 日期「{got}」≠ 今日「{date}」（callout 未更新）"

# ——— VI-stocks ———
def _chk_stocks_spcap(date, html, md, prices, prev, plabel):
    if not prev:
        return None
    cur = _snap(r'class="sp-cap">([^<]{10,60})', html, dotall=False)
    prv = _snap(r'class="sp-cap">([^<]{10,60})', prev, dotall=False)
    if cur and prv and cur.strip() == prv.strip():
        return f"重点个股聚光灯首条与 {plabel} 相同（VI-stocks 未更新）：「{cur.strip()[:60]}」"

def _chk_stocks_dd_series(date, html, md, prices, prev, plabel):
    """深读卡 dd-series JS：① 存在 ② 日期匹配今日 ③ ticker 与 HTML 容器一致"""
    m_src = re.search(r'<script src="(dd-series-([\d-]+)\.js)">', html)
    if not m_src:
        return None
    fname, file_date = m_src.group(1), m_src.group(2)
    if file_date != date:
        return f"dd-series 引用日期 {file_date} ≠ 今日 {date}（复制上一期后未更新 src）"
    dd_path = os.path.join(SITE_DIR, fname)
    if not os.path.exists(dd_path):
        return f"dd-series-{date}.js 文件缺失（HTML 引用存在但文件未生成/未提交）"
    dd_js = open(dd_path, encoding="utf-8").read()
    series_keys = set(re.findall(r'"([A-Z]{2,6})":\{', dd_js))
    html_ids = set(re.findall(r'id="dd-([A-Z]{2,6})"', html))
    if series_keys and html_ids and series_keys != html_ids:
        return (f"深读卡容器 id {sorted(html_ids)} 与 dd-series JS ticker "
                f"{sorted(series_keys)} 不一致（深读卡未随 dd-series 同步）")

def _chk_stocks_dd_build(date, html, md, prices, prev, plabel):
    """buildDD() 硬编码 ticker 数组 vs HTML 容器 id（错配→图表空白，07-14 事故根因）"""
    build_tickers = set(re.findall(r'\["([A-Z]{2,6})","dd-[A-Z]{2,6}",[\d.]+,[\d.]+\]', html))
    html_ids = set(re.findall(r'id="dd-([A-Z]{2,6})"', html))
    if not build_tickers or not html_ids:
        return None
    if build_tickers != html_ids:
        return (f"buildDD() 硬编码标的 {sorted(build_tickers)} ≠ HTML 深读容器 {sorted(html_ids)}"
                f"（图表将空白——复制上一期后未更新 buildDD 数组）")

def _chk_stocks_dd_tickers(date, html, md, prices, prev, plabel):
    """⑤ 深读卡 ticker vs md「今日 N 只」"""
    if not md:
        return None
    m = re.search(r'个股深读（今日\s*\d+\s*只[：:]\s*([^）)]+)）', md)
    if not m:
        return None  # md 无此标题格式，静默跳过
    ticker_part = m.group(1).split("——")[0]
    md_tickers = set(re.findall(r'\b[A-Z]{2,6}\b', ticker_part))
    html_tickers = set(re.findall(r'dd-tkr">([A-Z]{2,6})', html))
    if md_tickers != html_tickers:
        return f"深读卡 ticker md={sorted(md_tickers)} html={sorted(html_tickers)}"

# ——— VII-people ———
def _chk_people_prev_date(date, html, md, prices, prev, plabel):
    """⑨ 关键人物节不应含前一日 M/D 日期"""
    if not plabel:
        return None
    _, pm, pd = plabel.split("-")
    prev_mdfmt = f"{int(pm)}/{int(pd)}"
    section = _snap(r'id="page-people"(.*?)(?=id="page-|</body>)', html)
    if section and prev_mdfmt in section:
        return f"关键人物节仍含前一日日期「{prev_mdfmt}」（从 {plabel} 复制后未更新）"

def _chk_people_cur_date(date, html, md, prices, prev, plabel):
    """关键人物节应含今日 M/D 日期"""
    y, mo, d = date.split("-")
    cur_mdfmt = f"{int(mo)}/{int(d)}"
    section = _snap(r'id="page-people"(.*?)(?=id="page-|</body>)', html)
    if section and cur_mdfmt not in section:
        return f"关键人物节未含今日日期「{cur_mdfmt}」（表格日期未更新）"

# ——— finale ———
def _chk_finale_gen(date, html, md, prices, prev, plabel):
    m = re.search(r'finale-gen">美股日报 · ([\d-]+) ·', html)
    if not m or m.group(1) != date:
        return f"finale-gen 日期={m.group(1) if m else '未找到'}，应为 {date}"

def _chk_finale_title(date, html, md, prices, prev, plabel):
    if not prev:
        return None
    cur = _snap(r'finale-title[^>]*>\s*([^<\n]{5,})', html, dotall=False)
    prv = _snap(r'finale-title[^>]*>\s*([^<\n]{5,})', prev, dotall=False)
    if cur and prv and cur.strip() == prv.strip():
        return f"finale-title 与 {plabel} 相同（finale 未更新）：「{cur.strip()[:60]}」"


# ── 校验项注册表（建站顺序） ───────────────────────────────────────────────────
# (section_id, check_name, fn)
CHECKS = [
    # section        name                              fn
    ("meta",         "① CUTOFF 变量",                 _chk_cutoff),
    ("meta",         "④ 数据截至日期",                 _chk_data_thru),
    ("head",         "head <title> ≠ 前一期",          _chk_head_title),
    ("head",         "head meta-description ≠ 前一期", _chk_head_desc),
    ("tape",         "③ 跑马灯日期戳",                 _chk_tape_date),
    ("tape",         "跑马灯 VIX vs stat-grid",        _chk_tape_vix),
    ("tape",         "跑马灯 F&G vs stat-grid",        _chk_tape_fg),
    ("hero",         "hero 主题句 ≠ 前一期",            _chk_hero_theme),
    ("hero",         "hero 方向色与 GSPC 涨跌一致",     _chk_hero_color),
    ("summary",      "摘要首卡标题 ≠ 前一期",           _chk_summary),
    ("stance",       "研判定调 ≠ 前一期",               _chk_stance),
    ("I-radar",      "事件雷达首条 ≠ 前一期",           _chk_radar),
    ("II-market",    "大盘总览核心读法 ≠ 前一期",        _chk_market_core),
    ("II-market",    "大盘总览 GSPC 涨跌幅 vs prices",  _chk_market_gspc),
    ("II-market",    "大盘总览 IXIC 涨跌幅 vs prices",  _chk_market_ixic),
    ("III-tech",     "技术面 VIX stat-grid ≠ 前一期",       _chk_tech_vix),
    ("III-tech",     "技术面 F&G stat-grid ≠ 前一期",       _chk_tech_fg),
    ("III-tech",     "仪表盘 VIX gauge JS vs cp-note",      _chk_tech_gauge_vix),
    ("III-tech",     "仪表盘 F&G gauge JS vs cp-note",      _chk_tech_gauge_fg),
    ("III-tech",     "仪表盘 RSI gauge JS vs cp-note",      _chk_tech_gauge_rsi),
    ("III-tech",     "仪表盘广度(BR) gauge JS vs cp-note",  _chk_tech_gauge_br),
    ("IV-macro",     "宏观地缘 desc ≠ 前一期",           _chk_macro_desc),
    ("IV-macro",     "宏观地缘 WTI 涨跌幅 vs prices",    _chk_macro_wti),
    ("IV-macro",     "宏观地缘 10Y 收益率 vs prices",    _chk_macro_10y),
    ("V-earnings",   "财报节 desc 日期 = 今日",            _chk_earnings),
    ("V-earnings",   "财报节 callout 日期 = 今日",         _chk_earnings_callout),
    ("VI-stocks",    "重点个股聚光灯首条 ≠ 前一期",          _chk_stocks_spcap),
    ("VI-stocks",    "⑧ 深读卡 dd-series 文件/日期/ticker", _chk_stocks_dd_series),
    ("VI-stocks",    "buildDD() 硬编码 ticker vs HTML 容器", _chk_stocks_dd_build),
    ("VI-stocks",    "⑤ 深读卡 ticker vs md",              _chk_stocks_dd_tickers),
    ("VII-people",   "⑨ 关键人物无前一日日期",            _chk_people_prev_date),
    ("VII-people",   "关键人物含今日日期",                _chk_people_cur_date),
    ("finale",       "② finale-gen 日期",               _chk_finale_gen),
    ("finale",       "finale-title ≠ 前一期",            _chk_finale_title),
]


# ── 主入口 ────────────────────────────────────────────────────────────────────

def run(date, html_path=None, md_path=None, section_filter=None):
    html_path = html_path or os.path.join(SITE_DIR, f"{date}.html")
    md_path = md_path or os.path.join(
        os.path.dirname(SITE_DIR), "美股日报", f"美股日报_{date}.md")

    if not os.path.exists(html_path):
        print(f"❌ HTML 文件不存在：{html_path}")
        return 1

    html = open(html_path, encoding="utf-8").read()
    md = open(md_path, encoding="utf-8").read() if os.path.exists(md_path) else ""
    prices = _load_prices(date)
    prev, plabel = _get_prev(date)

    if not prices:
        print(f"（prices_{date}.md 未找到，跳过 prices 比对项，不计入失败）")
    if not md:
        print(f"（md 文件未找到，跳过 md 比对项，不计入失败）")
    if not prev:
        print("（无前一期 HTML，跳过所有「≠ 前一期」校验，不计入失败）")

    # 过滤当前节的校验项
    active = [(sec, name, fn) for sec, name, fn in CHECKS
              if section_filter is None or sec == section_filter]

    if section_filter and not active:
        print(f"未知节标识「{section_filter}」，可用: {', '.join(SECTION_ORDER)}")
        return 2

    bad = []
    for sec, name, fn in active:
        try:
            err = fn(date, html, md, prices, prev, plabel)
        except Exception as e:
            err = f"校验异常: {e}"
        if err:
            label = f"[{sec}] {name}"
            bad.append(f"{label}：{err}")

    prefix = f"[--section {section_filter}] " if section_filter else ""
    if bad:
        for b in bad:
            print(f"❌ {b}")
        print(f"\n{prefix}新鲜度校验: {len(bad)} 处疑似残留旧内容")
        return 1

    print(f"{prefix}新鲜度校验: 0 处疑似残留旧内容")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="美股日报网页新鲜度校验 v2.0")
    parser.add_argument("date", nargs="?", help="YYYY-MM-DD")
    parser.add_argument("--html", help="覆盖默认 HTML 路径")
    parser.add_argument("--md",   help="覆盖默认 md 路径")
    parser.add_argument("--section", help="只跑该节的校验项")
    parser.add_argument("--list-sections", action="store_true",
                        help="列出所有节标识符和对应校验项")
    args = parser.parse_args()

    if args.list_sections:
        for sec in SECTION_ORDER:
            checks = [(name, fn.__name__) for s, name, fn in CHECKS if s == sec]
            print(f"\n[{sec}]")
            for name, _ in checks:
                print(f"  · {name}")
        sys.exit(0)

    if not args.date:
        parser.print_help()
        sys.exit(2)

    sys.exit(run(args.date, args.html, args.md, args.section))
