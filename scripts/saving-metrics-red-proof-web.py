#!/usr/bin/env python3
"""#5159 红证驱动（前端组件/助手）：对页面 / 助手做单点变异 ⇒ 对应判据必须变红（然后原样恢复）。

与 `scripts/saving-metrics-red-proof-backend.py`（后端真库）同理：判据没有判别力 = 空断言。
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB = ROOT / "frontend/admin-web"
LIB = WEB / "src/lib/saving-board.ts"
PAGE = WEB / "src/app/(dashboard)/production/saving-board/page.tsx"

MUTATIONS = [
    (
        "判据4 空数据不冒充 0：无值渲染成 0",
        LIB,
        "  if (n === null) return NO_DATA\n  return digits === 0 ? String(Math.round(n)) : trimTrailingZeros(n.toFixed(digits))",
        "  if (n === null) return '0'\n  return digits === 0 ? String(Math.round(n)) : trimTrailingZeros(n.toFixed(digits))",
    ),
    (
        "判据3 两条指标都用：页面上只剩指标①",
        PAGE,
        "        {cards.map((card) => (",
        "        {cards.slice(0, 1).map((card) => (",
    ),
    (
        "判据3 说明文案：删掉「单看①会被排料误导」的因果",
        LIB,
        "    + '单看①会被排料省料误导 —— 排料省料 ⇒ 批次剩得更多 ⇒ 只留①会把效率提升显示成变差。'",
        "    + '两条指标一起看即可。'",
    ),
    (
        "判据2 存量单列：存量卡显示「切换后」的占比（两组混算）",
        PAGE,
        "                    {formatShare(c.le0_2Share)}",
        "                    {formatShare(cohorts[0]?.le0_2Share)}",
    ),
    (
        "§22 文案不写死数字：档位文案硬编码「≤0.2 米」",
        LIB,
        "  const bucketLabel = board?.cohorts?.[0]?.buckets?.[0]?.label\n  const purchase = board?.cohorts?.find((c) => c.cohort === 'purchase')",
        "  const bucketLabel = '≤0.2 米'\n  const purchase = board?.cohorts?.find((c) => c.cohort === 'purchase')",
    ),
]

TESTS = ["tests/unit/components/SavingBoard.test.tsx", "tests/unit/lib/saving-board.test.ts"]


def run():
    proc = subprocess.run(["npm", "test", "--", *TESTS], cwd=WEB, capture_output=True, text=True)
    tail = "\n".join(l for l in proc.stdout.splitlines()
                     if "Tests " in l or "Test Files" in l or "FAIL " in l)
    return proc.returncode, tail


def main():
    bad = []
    for title, path, old, new in MUTATIONS:
        original = path.read_text(encoding="utf8")
        if old not in original:
            print(f"❌ 注入点失配（驱动脚本坏了）：{title}")
            bad.append(title)
            continue
        try:
            path.write_text(original.replace(old, new, 1), encoding="utf8")
            rc, tail = run()
            red = rc != 0
            print(f"{'✅ 红（判据有判别力）' if red else '❌ 绿（空断言！）'} | {title} | rc={rc}", flush=True)
            if red:
                print("      实测红读数: " + tail.replace("\n", " | ")[:300], flush=True)
            else:
                bad.append(title)
        finally:
            path.write_text(original, encoding="utf8")
    print("\n=== 恢复后复跑（必须全绿）===", flush=True)
    rc, tail = run()
    print(f"rc={rc} ({'全绿' if rc == 0 else '仍有红 ⇒ 恢复不干净'}）{tail}")
    if bad or rc != 0:
        sys.exit(1)


main()
