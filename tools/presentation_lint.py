# -*- coding: utf-8 -*-
"""呈现语言 lint：扫描展示用网页中的内部流程用语/禁用表述。
用法: python presentation_lint.py <html文件>
规则来源: US Stock Market/CLAUDE.md 呈现规则。退出码非 0 = 不通过。
只检查读者可见文本（正文 + title/alt 属性），跳过 <script>/<style> 与注释。

写作原则（人工守 + 部分机检）：
- **不要直接翻译英语**：英文金融词直译成中文常常生硬（如 hedge leg→"对冲腿"、rerate→"重定价腿"），
  一律改成符合中文阅读习惯的专业表述（如 hedge leg→"宏观逆风/利空面"、long/short leg→"多头方/空头方"）。
  下方 HARD 里已收录发生过的直译词，发现新的直译请补进去。
- **一句话定调（finale-title）= 单一 headline**：只写当日最重要的**一个**方面，**不放数字/涨跌幅**，单句不堆砌
  （规则见 每日建站指南.md 用户偏好清单）。本 lint 已对 finale-title 做机检（禁数字、限长），见下 check_finale。
"""
import re, sys

HARD = [  # 出现即不通过
    (r"待核|待确认|待精确核实", "无数据占位（应整行省略）"),
    (r"无触发|触发线|触发阈值|达阈值", "模板触发机制用语"),
    (r"搜索未命中|未能确认|未获取|无稳定来源|无可靠来源", "过程性备注"),
    (r"详见存档|见 \d+/\d+ 日报|信息来源 \d+/\d+", "存档交叉引用"),
    (r"日报模板|模板 v\d|判定基准：|详尽版（", "模板元信息"),
    (r"依[^，。;<]{0,12}(计算|核验|断言|推算)", "内部口径备注"),
    (r"[(（][^）)]*存疑[^）)]+[)）]", "存疑附带原因（只允许裸存疑）"),
    (r"≈", "约等号（应给单一值+存疑）"),
    (r"约 ?[\d$]", "『约』+数字（应给单一值+存疑）"),
    (r"D[0-4] ?[·)）]|（D[0-4]", "财报 D0/D1 内部标签"),
    (r"关注池", "关注池内部概念（应改为重点公司/今日最强/追踪标的等读者友好表述）"),
    (r"列表外|列表内", "列表内外内部分类标签（应直接写公司名）"),
    (r"未达触发|接近触发", "触发阈值内部用语（应直接写涨跌幅，删除触发描述）"),
    (r"触发\s*\d+\s*只|\d+\s*只\s*触发", "内部触发计数（应改为大幅异动 N 只，注意正反两种词序）"),
    (r"%\s*触发|触发[）)]|收[涨跌]\s*触发|触发披露", "触发用语的变体写法（内部阈值/计数概念，应直接写涨跌幅/数量，不点名触发机制）"),
    (r"（常驻|（强制|（触发式", "模板指令标注"),
    (r"取数器", "内部工具名（取数器/取数脚本，不应出现在读者可见文案，含纠错/修正/真实收盘/不存疑等变体）"),
    (r"初版依.{0,20}(口径|WebSearch|搜索)", "初版/口径内部过程注释"),
    (r"经.{0,10}(Yahoo|v8|真实收盘).{0,10}核对", "内部数据核验注释"),
    (r"方向(全部|均)?(相反|错误|误记)", "内部方向纠错注释"),
    (r"此前误记|误记为|误标为", "内部纠错用语"),
    (r"经.{2,15}财报日历交叉确认", "内部数据来源交叉确认注释"),
    (r"INTERNAL:", "INTERNAL 标记泄漏（应被建站 agent 剥离，不得出现在可见文本）"),
    (r"方向更正[：:　]|⚠️.{0,8}方向更正", "内部方向更正标注"),
    (r"已逐一核[对查实].{0,30}(财报|交叉确认|家)?", "内部核验说明"),
    (r"不再复述|按 ?D[0-4][+]? ?(规则|篇幅)", "内部篇幅/复述规则备注"),
    (r"官方接口(直取|当日读数)?|来源[：:　]\s*\S*接口", "内部取数接口备注（数据来源说明属建站口径，不面向读者）"),
    (r"雷达综合评分", "已弃用的雷达综合评分（雷达图 06-17 已弃用）"),
    (r"窗口边界|窗口外|超本扫描窗口|本扫描窗口", "事件雷达内部扫描窗口备注（应直接写事件本身，不点名雷达覆盖范围）"),
    (r"对冲腿|多头腿|空头腿", "英文直译（leg→腿）：换成符合中文习惯的专业词，如 宏观逆风/利空面/多头方/空头方"),
]
WARN = [  # 提示人工复核
    (r"\d+(\.\d+)?\s*[–—-]\s*\d+(\.\d+)?%", "疑似数值区间（日期窗口描述可豁免）"),
    (r"推算|估算", "派生值表述，确认是否面向读者自然"),
]

ALLOW = [  # 官方陈述本身就是区间/近似的合法情形
    r"3\.50–3\.75%",          # 联储目标区间
    r"\+27–29%|\+57–64%",     # 公司官方指引区间
    r"滞后约 30–45 天",          # STOCK Act 法定窗口
    r"窗口约 8 月",              # 13F 披露窗口
    r"全球约 20%",               # 世界常识近似
    r"未来 1–2 周",              # 栏目时间窗描述
]

def visible_text(src):
    src = re.sub(r"<script\b.*?</script>", " ", src, flags=re.S | re.I)
    src = re.sub(r"<style\b.*?</style>", " ", src, flags=re.S | re.I)
    src = re.sub(r"<!--.*?-->", " ", src, flags=re.S)
    titles = re.findall(r'(?:title|alt)="([^"]+)"', src)
    text = re.sub(r"<[^>]+>", " ", src)
    text = re.sub(r"[ \t]+", " ", text)
    return text + "\n" + "\n".join(titles)

def check_stockcards(raw):
    """AI 超大厂卡成员机检：该卡固定＝MSFT/GOOGL/AMZN/META + NVDA/AAPL(±2%才并入)，
    严禁建站按叙事把非成员（如 AVGO 属定制芯片、TSLA 属电车）塞成 stock-tile 方块。
    只查 st-tkr 方块（叙事文字里提及非成员是允许的，方块不行）。"""
    out = []
    ALLOWED = {"MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "AAPL"}
    for ch in raw.split('<div class="stock-card">')[1:]:
        if "超大厂" not in ch[:400]:      # 只认 AI 超大厂那张卡（头部含"超大厂"）
            continue
        for t in re.findall(r'st-tkr">([A-Z]{1,5})<', ch):
            if t not in ALLOWED:
                out.append((f"AI 超大厂卡混入非成员 {t}（该卡固定＝MSFT/GOOGL/AMZN/META+NVDA/AAPL；"
                            f"{t} 应回其所属板块卡，勿照叙事擅自塞方块——建站须逐一照搬 md 的卡成员）", t))
        break
    return out

def check_finale(raw):
    """finale-title 专项机检：一句话定调 = 单一 headline，禁数字/涨跌幅，宜短单句。"""
    out = []
    for m in re.finditer(r'class="finale-title"[^>]*>(.*?)</div>', raw, re.S):
        t = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        if re.search(r"\d", t):
            out.append(("一句话定调禁含数字（只写当日最重要的一个方面、不放涨跌幅）", t))
        if len(t) > 34:
            out.append((f"一句话定调过长（{len(t)}字，应为单句 headline、只讲一个方面）", t))
    return out

def main(path):
    raw = open(path, encoding="utf-8").read()
    text = visible_text(raw)
    for a in ALLOW:
        text = re.sub(a, " ", text)
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    bad = warn = 0
    for pat, why in HARD:
        for l in lines:
            for m in re.finditer(pat, l):
                bad += 1
                print(f"❌ [{why}] …{l[max(0,m.start()-18):m.end()+18]}…")
    for why, t in check_finale(raw):
        bad += 1
        print(f"❌ [{why}] …{t[:44]}…")
    for why, t in check_stockcards(raw):
        bad += 1
        print(f"❌ [{why}]")
    for pat, why in WARN:
        for l in lines:
            for m in re.finditer(pat, l):
                warn += 1
                print(f"⚠️  [{why}] …{l[max(0,m.start()-18):m.end()+18]}…")
    print(f"\nlint 结果: {bad} 个违规, {warn} 个提示")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
