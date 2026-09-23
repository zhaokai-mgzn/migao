#!/usr/bin/env python3
"""#5159 红证驱动（前端组件/助手）：对页面 / 助手做单点变异 ⇒ 对应判据必须变红（然后原样恢复）。

与 `scripts/saving-metrics-red-proof-backend.py`（后端真库）同理：判据没有判别力 = 空断言。

## 用法
    python3 scripts/saving-metrics-red-proof-web.py           # 实跑（需 node + npm，admin-web 已装依赖）
    python3 scripts/saving-metrics-red-proof-web.py --check   # 前提自检（门禁调用的面；零副作用）

退出码（实跑面）：`0` = 全部变异都被对应判据抓到且恢复后全绿；`1` = 有判据没有判别力 / 恢复不干净。
退出码（`--check` 面）：`0` = 全部前提成立；`1` = 有腐烂（**具名**）；`3` = 无法判定。
"""
import pathlib
import subprocess
import sys
from functools import partial

import red_proof_harness as h  # noqa: E402  #5193 门禁调用的是 --check 面（零 Maven/零副作用）

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
TOOL_REL = "scripts/saving-metrics-red-proof-web.py"


def _probe(path, old: str, title: str) -> None:
    """一条变异的前提探针（**只读**）：判据文件都在 + 注入锚点命中 1 次。

    ⚠️ 判据文件的存在性**折进每条变异**（而不是另立一条声明）：声明条数必须等于变异条数，
    否则登记表下限（只许增）就量不到「有人删了一条变异」这个形态。
    """
    for rel in TESTS:
        h.require_file(f"frontend/admin-web/{rel}", what=f"变异 [{title}] 的判据文件")
    src = path.relative_to(ROOT).as_posix()
    h.require_anchor(h.read_source(src, what=f"变异 [{title}] 的被测源码"), old,
                     what=f"变异 [{title}] 的注入锚点")


def check() -> int:
    """前提自检（`--check`）：不注入、不跑判据、不写任何文件。"""
    decls = [h.declare(title, "、".join(TESTS), partial(_probe, path, old, title))
             for title, path, old, _new in MUTATIONS]
    return h.report_and_exit(TOOL_REL, decls)


def run():
    proc = subprocess.run(["npm", "test", "--", *TESTS], cwd=WEB, capture_output=True, text=True)
    tail = "\n".join(l for l in proc.stdout.splitlines()
                     if "Tests " in l or "Test Files" in l or "FAIL " in l)
    return proc.returncode, tail


def main():
    if "--check" in sys.argv:
        sys.exit(check())
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
