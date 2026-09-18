# case_ids: MC-012
"""商家冒烟 spec 判据可信度守卫 —— issue #4226（三处判据不可信：空判据 / 假红 / 假绿）。

守的东西：`scripts/ui-smoke-merchant/spec.mjs` 是商家后台的**主要 UI 回归网**（31 旅程），
而它的**判据本身**曾不可信 —— 判据坏了不会有人因此变红，反而会（a）恒假（空判据）、
（b）把真回归淹没在长期红灯里、（c）把失败豁免掉（假绿）。三处互相独立，本文件是它们的**形状判据**
（静态可判；运行期真跑需要线上/真实商家数据，见下）：

① **空判据**：判「加工单块出现」用 `text=/PO-[0-9-]+|PG-[0-9-]+/`，而真实加工单号前缀是 `JG-`
   （实测 `JG-20260918-9049`）⇒ 正则永不命中 ⇒ 证据恒为「加工单可见=false」。
② **假红淹没回归**：`16-` 的「发加工」等流转按钮用**定长 sleep 后单次 `isVisible()`** 判定 ⇒
   偶发不可见 ⇒ 加工单不完成 ⇒ `17-order-ship` 被「须先完成加工单后再发货」守卫阻断（A/B 两轮均红）。
③ **假绿**：404 探测豁免条件是「**错误消息文本**含 404」⇒ 旅程自身抛出、文案里恰好带 404 的错误
   被一并豁免。

判据源单点：本文件**不复制**判据逻辑，只做两件事 ——
  · 静态扫描 spec.mjs 的形状（① 不再猜前缀 / ② 用 waitFor 而非定长 sleep / ③ 结构化 404 豁免）；
  · 以子进程跑 `node --test scripts/ui-smoke-merchant/criteria.test.mjs`，把 ①③ 的**可执行判据级红证**
    纳入 CI（`node:test` + `node:assert`，无新依赖）。
node 缺失时**判红而不是跳过**（fail-closed：判据没被行使不得读成通过）。

case_ids 口径：与同族开发/CI 工具链守卫（`test_red_proof_guard.py` #4260、`test_stranding_check.py`
#4065、`test_dev_worktree_rebase.py` #3972）沿用 `MC-012` —— 仓库没有「开发工具链」用例族，
塞进行为用例库会污染覆盖矩阵（同族 PR 的既有裁定）。

**运行期验证照实登记**：本轮本机云 dev 库不可达（`admin-api` 日志 `PSQLException: 尝试连线已失败`
/ `nc -z <RDS_HOST> 5432` FAIL）⇒ 无法跑真旅程，「`17-` 连续 ≥3 轮稳定绿」**未做运行期验证**，
故 ② 用「源码形状判据 + 改动前后形态 diff」兜底（issue #4226「红证的替代口径」允许口径）。
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_DIR = REPO_ROOT / "scripts" / "ui-smoke-merchant"
SPEC = SMOKE_DIR / "spec.mjs"
CRITERIA = SMOKE_DIR / "criteria.mjs"
CRITERIA_TEST = SMOKE_DIR / "criteria.test.mjs"

# 改动前的三处判据原文（红证形态：这些字面量必须消失/被替代）
OLD_PREFIX_LOCATOR = "text=/PO-[0-9-]+|PG-[0-9-]+/"
OLD_TEXT_EXEMPTION = "errors.every(e => e.includes('404'))"
NODE_TIMEOUT_SECONDS = 120


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _journey_body(name: str) -> str:
    """取 `async function <name>(...)` 的函数体（到下一个章节分隔注释为止）。

    取不到即判红（fail-closed）：判据的定位方式失效时**不得**静默退化成「空字符串扫描通过」。
    """
    src = _read(SPEC)
    start = src.find(f"async function {name}(")
    if start < 0:
        pytest.fail(f"spec.mjs 里找不到旅程函数 {name}（判据定位失效 ⇒ 本守卫未行使，不得读成通过）")
    tail = src[start:]
    end = re.search(r"\n// ─", tail)
    body = tail[: end.start()] if end else tail
    if len(body) < 200:
        pytest.fail(f"{name} 函数体只取到 {len(body)} 字符（判据定位失效 ⇒ 不得读成通过）")
    return body


def _flow_loop_body() -> str:
    """取 16- 旅程里「发加工 → 开始加工 → 加工完成」流转循环体。"""
    src = _read(SPEC)
    m = re.search(r"for \(const \[btn, [^\]]+\] of \[", src)
    if not m:
        pytest.fail("spec.mjs 里找不到流转循环（判据定位失效 ⇒ 不得读成通过）")
    tail = src[m.start():]
    end = tail.find("if (!poVisible")
    if end < 0:
        pytest.fail("流转循环取不到结束边界（判据定位失效 ⇒ 不得读成通过）")
    return tail[:end]


def _wait_helper_line() -> str:
    """取「等元素出现」助手 `const waitVisible = ...` 的定义（判据本体，不得退化成恒真）。"""
    src = _read(SPEC)
    start = src.find("const waitVisible =")
    if start < 0:
        pytest.fail("spec.mjs 里找不到等元素助手 waitVisible（判据定位失效 ⇒ 不得读成通过）")
    # 箭头函数跨行书写：取定义处起 3 行（足够覆盖 waitFor + catch 两段）
    return "\n".join(src[start:].split("\n")[:3])


def test_no_prefix_guessing_processing_order_no():
    """① 空判据：不得再用 PO-/PG- 前缀猜真实加工单号。"""
    src = _read(SPEC)
    assert OLD_PREFIX_LOCATOR not in src, (
        f"spec.mjs 仍在使用永不命中的旧判据 {OLD_PREFIX_LOCATOR!r}"
        "（真实加工单号前缀是 JG-，实测 JG-20260918-9049 ⇒ 证据恒为「加工单可见=false」）"
    )
    # 同族漏改处扫描：文件里不得再出现**任何** PO-/PG- 单号正则形态（注释里提旧写法不算，
    # 故判据锚在正则本体 `PO-[0-9-]`/`PG-[0-9-]` 上，不锚裸前缀）
    assert "PO-[0-9-]" not in src and "PG-[0-9-]" not in src, "spec.mjs 仍残留 PO-/PG- 单号正则（同族漏改处）"
    body = _journey_body("orderDetailJourney")
    assert "matchProcessingOrderNo(" in body, "16- 旅程未用「不猜前缀」的形态判据（criteria.mjs 的 matchProcessingOrderNo）"
    assert "'.po-print-area'" in body, (
        "16- 未把单号判据限定在「加工单块容器」内（全页按形态取号会命中同页其它 XX-日期-序号 单号 ⇒ 换个形态的假绿）"
    )


def test_processing_order_block_uses_shared_criteria_module():
    """① 判据源单点：形态判据/404 豁免必须来自 criteria.mjs（可独立执行的判据级红证载体）。"""
    src = _read(SPEC)
    assert "from './criteria.mjs'" in src, "spec.mjs 未从同目录 criteria.mjs 导入判据（判据又会退回内联不可验证态）"
    assert CRITERIA.exists(), "criteria.mjs 缺失 ⇒ criteria.test.mjs 的判据级红证无处可跑"
    assert CRITERIA_TEST.exists(), "criteria.test.mjs 缺失 ⇒ ①③ 的可执行红证不在仓库里"


def test_flow_buttons_wait_for_element_not_fixed_sleep():
    """② 假红：流转按钮必须以「等元素出现」判定，不得定长 sleep 后单次 isVisible。"""
    loop = _flow_loop_body()
    for label in ("发加工", "开始加工", "加工完成"):
        assert label in loop, f"流转循环里找不到「{label}」步骤（判据定位失效）"
    assert "waitVisible(" in loop, "流转按钮未用「等元素出现」助手判定（② 的判据形态）"
    assert ".isVisible()" not in loop, "流转循环里仍有单次 isVisible 判定（偶发不可见 ⇒ 假红 ⇒ 17- 被守卫阻断）"
    assert "waitForTimeout" not in loop, "流转循环里仍有定长 sleep（issue #4226② 要求改为等元素出现）"


def test_wait_helper_waits_and_fails_closed():
    """② 判据本体不得退化：等元素助手必须真的 waitFor，且超时返回 false（不是恒真）。"""
    line = _wait_helper_line()
    assert "waitFor({ state: 'visible'" in line, f"等元素助手未用 waitFor 等可见：{line.strip()!r}"
    assert ".catch(() => false)" in line, f"等元素助手超时未返回 false ⇒ 判定恒真（空判据）：{line.strip()!r}"


def test_journey16_waits_instead_of_fixed_sleep():
    """② 同族：16- 旅程整段不得再靠定长 sleep 后判 isVisible 决定流程。"""
    body = _journey_body("orderDetailJourney")
    assert "waitForTimeout" not in body, "16- 旅程仍有定长 sleep（等页面/等状态就位应改为 waitFor）"
    assert ".isVisible()" not in body, "16- 旅程仍有单次 isVisible 判定（同族假红形态）"
    assert body.count("waitVisible(") >= 5, "16- 旅程的「等元素出现」判定数量异常（付款/生成/单号/流转/状态回显都该等元素）"


def test_journey17_waits_for_form_or_guard():
    """② `17-order-ship`：必须等「发货表单 或 加工单守卫」出现再判，不得定长 sleep 后数控件。"""
    body = _journey_body("orderShipJourney")
    assert "waitForTimeout" not in body, "17- 旅程仍有定长 sleep（1500ms 内加工单状态未回来 ⇒ 判「无表单」= 假红）"
    assert "waitVisible(" in body, "17- 旅程未用「等元素出现」判定页面稳定"
    assert "须先完成加工单后再发货" in body, (
        "17- 未区分「被加工单前置守卫阻断」与「页面无表单」——两者都判同一句 ⇒ 归因不可读"
    )


def test_404_exemption_is_structural_not_text_scan():
    """③ 假绿：404 豁免必须按结构化响应判定，不得扫错误文本。"""
    src = _read(SPEC)
    assert OLD_TEXT_EXEMPTION not in src, f"spec.mjs 仍有「错误文本含 404 就豁免」的写法：{OLD_TEXT_EXEMPTION!r}"
    assert "includes('404')" not in src, "spec.mjs 仍在按错误文本判 404（同族漏改处）"
    assert "Failed to load resource" not in src, "spec.mjs 仍在扫 console 文案以决定豁免（应为结构化判据）"
    body = _journey_body("orderDetailJourney")
    assert "page.on('response'" in body, "16- 旅程未收集结构化响应（无 response.status() 可供判定）"
    assert "isProbe404Exempt(" in body, "404 豁免未走 criteria.mjs 的结构化判据 isProbe404Exempt()"


def test_executable_criteria_red_proofs_pass():
    """①③ 的可执行判据级红证（node:test，无新依赖）必须全绿 —— 红证不在仓库外。"""
    node = shutil.which("node")
    if node is None:
        pytest.fail("node 不可用 ⇒ ①③ 的可执行判据未行使（不得读成通过；本仓库 CI/本地均依赖 node 跑 playwright）")
    proc = subprocess.run(
        [node, "--test", str(CRITERIA_TEST)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=NODE_TIMEOUT_SECONDS,
    )
    assert proc.returncode == 0, (
        "criteria.test.mjs 未通过（① JG- 形态命中 / ③ 结构化 404 豁免的判据级红证）\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
