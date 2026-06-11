# -*- coding: utf-8 -*-
"""呈现语言 lint：扫描展示用网页中的内部流程用语/禁用表述。
用法: python presentation_lint.py <html文件>
规则来源: US Stock Market/CLAUDE.md 呈现规则。退出码非 0 = 不通过。
只检查读者可见文本（正文 + title/alt 属性），跳过 <script>/<style> 与注释。
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
    (r"其余关注池[^。<]{0,80}无", "关注池无异动清单（仅存于 Markdown）"),
    (r"（常驻|（强制|（触发式", "模板指令标注"),
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
    return text + "\n" + "\n".join(titles)

def main(path):
    text = visible_text(open(path, encoding="utf-8").read())
    for a in ALLOW:
        text = re.sub(a, " ", text)
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    bad = warn = 0
    for pat, why in HARD:
        for l in lines:
            for m in re.finditer(pat, l):
                bad += 1
                print(f"❌ [{why}] …{l[max(0,m.start()-18):m.end()+18]}…")
    for pat, why in WARN:
        for l in lines:
            for m in re.finditer(pat, l):
                warn += 1
                print(f"⚠️  [{why}] …{l[max(0,m.start()-18):m.end()+18]}…")
    print(f"\nlint 结果: {bad} 个违规, {warn} 个提示")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
