#!/usr/bin/env bash
# archive_month.sh — 把指定月份的日报页归档到 archive/YYYY-MM/（方案二：只归档过去月份）
#
# 用法:
#   tools/archive_month.sh            # 不传参 → 自动归档"上个月"(按系统实际日期,动态)
#   tools/archive_month.sh 2026-07    # 归档指定月份
#
# 做的事(全自动)：
#   1) git mv  YYYY-MM-*.html + dd-series-YYYY-MM-*.js  →  archive/YYYY-MM/
#   2) 归档页对共享资源(site.css/market_data.js/dates.js)的引用加 ../../ 前缀
#      (dd-series 与页面一起移动，同目录引用不变；nav 已是 pageURL 也顺手兜底)
#   3) 把 "YYYY-MM" 加入 dates.js 的 ARCHIVED_MONTHS(去重+升序)
#   4) QA: node --check dates.js + 抽检归档页内联脚本
#   最后打印 commit+push 命令(不自动推送，留人工过目)。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SITE_DIR="$(dirname "$SCRIPT_DIR")"   # 网站/
cd "$SITE_DIR"

# 月份：默认上个月(macOS BSD date)，始终按真实日期算，不硬编码
MONTH="${1:-$(date -v-1m +%Y-%m)}"
[[ "$MONTH" =~ ^[0-9]{4}-[0-9]{2}$ ]] || { echo "❌ 月份格式应为 YYYY-MM，收到: $MONTH"; exit 1; }

DEST="archive/$MONTH"
shopt -s nullglob
PAGES=( ${MONTH}-*.html )
DDS=( dd-series-${MONTH}-*.js )

if (( ${#PAGES[@]} == 0 )); then
  echo "❌ 根目录没有 ${MONTH}-*.html —— 该月无页面或已归档，终止。"; exit 1
fi

echo "== 归档 $MONTH：移动 ${#PAGES[@]} 个页面 + ${#DDS[@]} 个 dd-series → $DEST =="
mkdir -p "$DEST"
git mv "${PAGES[@]}" "$DEST"/
(( ${#DDS[@]} > 0 )) && git mv "${DDS[@]}" "$DEST"/

echo "== 修正归档页引用(共享资源→ ../../；nav→ pageURL 兜底) =="
perl -pi -e '
  s{src="market_data\.js"}{src="../../market_data.js"}g;
  s{src="dates\.js"}{src="../../dates.js"}g;
  s{href="site\.css}{href="../../site.css}g;
  s{location\.href=iso\+"\.html"}{location.href=pageURL(iso)}g;
' "$DEST"/${MONTH}-*.html

echo "== 登记 ARCHIVED_MONTHS =="
python3 - "$MONTH" <<'PY'
import re, sys
m = sys.argv[1]; f = "dates.js"
s = open(f, encoding="utf-8").read()
mo = re.search(r'const ARCHIVED_MONTHS=\[(.*?)\];', s)
if not mo:
    sys.exit("❌ dates.js 里找不到 ARCHIVED_MONTHS")
items = [x.strip().strip('"') for x in mo.group(1).split(",") if x.strip()]
if m not in items:
    items = sorted(set(items + [m]))
new = 'const ARCHIVED_MONTHS=[' + ",".join('"%s"' % x for x in items) + '];'
open(f, "w", encoding="utf-8").write(s[:mo.start()] + new + s[mo.end():])
print("  ARCHIVED_MONTHS =", items)
PY

echo "== QA: 语法检查 =="
node --check dates.js && echo "  ✓ dates.js"
for f in "$DEST"/${MONTH}-*.html; do
  node -e 'const fs=require("fs");const h=fs.readFileSync(process.argv[1],"utf8");
    let re=/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g,m,b=0;
    while((m=re.exec(h))){try{new Function(m[1])}catch(e){b++;console.log("  ✗",process.argv[1],e.message)}}
    process.exit(b?1:0)' "$f" || { echo "❌ 内联脚本语法错误: $f"; exit 1; }
done
echo "  ✓ 归档页内联脚本全部通过"

echo ""
echo "✅ $MONTH 归档完成（文件已 git 暂存）。请过目后提交推送："
echo "    cd \"$SITE_DIR\""
echo "    git add -A && git commit -m \"chore: 归档 $MONTH 日报页到 archive/$MONTH/\" && git push"
