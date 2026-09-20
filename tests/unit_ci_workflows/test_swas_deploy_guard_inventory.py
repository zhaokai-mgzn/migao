# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""#4828 防再犯机制的**元守卫**：机制本身不许被静默删除 / 掏空。

## 为什么需要这一层（issue #4828 §0「只做一次性修复不算完成」）

#4828 的交付物**不是**「这一次把 `deploy/swas/deploy.sh` 改对」，而是一个**以后每次改部署链都会跑**
的机制 —— `tests/unit_ci_workflows/test_swas_deploy_blue_green.py`：
10 组判据（`judge_*`）+ 36 条注入式红证（`test_injection_*_goes_red`）+ 18 条执行式场景（`test_exec_*`，
桩化 `docker` / `curl` / `flock` / `timeout` 跑**真实** `deploy.sh` 的真实码路）。

而「机制」与「一次性修复」的差别，**只在它还在不在**。实测（2026-09-21，本单）三个形态
**都不会有任何检查变红**，CI 只会「少跑几个测试」然后照旧全绿：

| 形态 | 后果 | 谁会红 |
|---|---|---|
| 删掉整个守卫文件 | 机制消失 | **没有**（`tests/unit_ci_workflows/**` 的 153 个文件统一挂 `# case_ids: MC-012`，而 MC-012 的 `traces.tests` 指向的是**别的**文件 ⇒ 用例库不锚这些文件；`QA Growth Gate` 只查**新增/修改**的测试文件是否带 `case_ids`，不查**删除**） |
| 摘掉 `all_violations()` 里的某一条接线 | 该判据变成**死代码**、静默不生效（最隐蔽） | **没有**（判据函数还在，`test_each_judge_is_clean_on_the_real_script` 仍会**单独**跑它并通过） |
| 删掉一批注入式红证 | 反向判别力消失（判据退化成空断言） | **没有**（剩下的红证照旧通过） |

⇒ 本文件把「机制还在不在」变成**可执行判据**（这正是 §0 要求的「把该机制去掉 ⇒ 必须变红」）：
  ① 守卫文件必须存在，且前 50 行内有 `# case_ids:` 声明（硬约束 A：`growth_gate.extract_case_ids()`
     只扫前 50 行，声明落太深 = 等于没声明 ⇒ QA Growth Gate block）；
  ② **每一组**判据（`judge_*`）都必须出现在 `all_violations()` 里 —— 摘掉接线即判红；
  ③ 判据组数 / 注入式红证条数 / 执行式场景条数都必须**不低于**记录的地板（删一批就红）；
  ④ 反空跑助手 `_inject` 必须对「锚点不存在」「注入没改变文本」**显式失败**（否则注入式红证是空跑）。

## 本文件**不**负责什么（边界，照实登记）

它只保证「机制还在」，**不**保证「机制覆盖得够」—— 覆盖面的扩张靠每次改动按 §14 补判据 + 红证，
以及把地板**上调**（地板只许上调，不许下调；下调等于把「机制规模」这件事也变成可静默削减的）。
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "tests" / "unit_ci_workflows" / "test_swas_deploy_blue_green.py"

# ── 地板（**只许上调**）：记录 #4828 机制的最小规模 ─────────────────────────────
# 上调时机 = 按 §14 给本机制补了新的判据组 / 红证 / 执行式场景时，同一个 PR 里一起改。
JUDGE_FLOOR = 10
INJECTION_FLOOR = 36
EXEC_FLOOR = 18

CASE_IDS_LINE = re.compile(r"^\s*#\s*case_ids\s*[:=]\s*\S", re.M)
JUDGE_DEF = re.compile(r"^def (judge_[a-z0-9_]+)\(", re.M)
INJECTION_DEF = re.compile(r"^def test_injection_[a-z0-9_]+_goes_red\(", re.M)
EXEC_DEF = re.compile(r"^def test_exec_[a-z0-9_]+\(", re.M)


def guard_violations(text: str) -> list:
    """守卫文件文本 ⇒ 违规清单（空 = 机制完整）。

    纯文本判据（不 import 那个模块）：这样「文件被删 / 被掏空」与「函数被改名」都能判出来，
    而 import 式判据在文件被删时只会 ImportError（形态不同、信息更差）。
    """
    v = []
    # ① case_ids 声明必须在**前 50 行**内（硬约束 A）
    if not CASE_IDS_LINE.search("\n".join(text.splitlines()[:50])):
        v.append("守卫文件前 50 行内没有 `# case_ids:` 声明 ⇒ QA Growth Gate 会 block 合并")

    # ② 每一条判据都必须被 all_violations() 接线（摘掉接线 = 死代码、静默不生效）
    judges = sorted(set(JUDGE_DEF.findall(text)))
    if len(judges) < JUDGE_FLOOR:
        v.append(f"判据组只剩 {len(judges)} 组（地板 {JUDGE_FLOOR}）⇒ 机制被掏空")
    i_av = text.find("def all_violations(")
    if i_av < 0:
        v.append("找不到 `all_violations()` —— 判据的唯一接线点没了（等于整个机制不执行）")
    else:
        rest = text[i_av:]
        j = rest.find("\ndef ", 1)
        av_body = rest[:j] if j > 0 else rest
        for name in judges:
            if name not in av_body:
                v.append(f"判据 `{name}` 没有被 `all_violations()` 接线 ⇒ 死代码、静默不生效")

    # ③ 反向红证 / 执行式场景的地板（防空断言）
    n_inj = len(INJECTION_DEF.findall(text))
    if n_inj < INJECTION_FLOOR:
        v.append(f"注入式红证只剩 {n_inj} 条（地板 {INJECTION_FLOOR}）⇒ 判据的反向判别力被删")
    n_exec = len(EXEC_DEF.findall(text))
    if n_exec < EXEC_FLOOR:
        v.append(f"执行式场景只剩 {n_exec} 条（地板 {EXEC_FLOOR}）⇒ 真实码路的桩化验证被删")

    # ④ 反空跑助手 `_inject` 必须还在，且**在它自己的函数体里**对「锚点不存在 / 注入没改变文本」
    #    显式失败。
    #    ⚠️ 判据必须收窄到 `_inject` 的**函数体**：那句「注入没有改变文本」在文件里还有若干处
    #    （各条红证自己的 `assert injected != text`）⇒ 全文检索会让「拿掉 `_inject` 的自断言」
    #    这个注入**查不出来**（本判据第一版就这样假绿过一次）。
    i_inj = text.find("def _inject(")
    if i_inj < 0:
        v.append("反空跑助手 `_inject` 没了 ⇒ 注入式红证可能是空跑")
    else:
        rest = text[i_inj:]
        j = rest.find("\ndef ", 1)
        inj_body = rest[:j] if j > 0 else rest
        if "注入没有改变文本" not in inj_body:
            v.append("`_inject` 函数体里没有「注入没有改变文本」的自断言 ⇒ 注入式红证可能空跑")
        if "锚点不存在" not in inj_body:
            v.append("`_inject` 函数体里没有「锚点不存在」的自断言 ⇒ 锚点过期时会静默 no-op")
    return v


def read_guard() -> str:
    """读守卫文件的**当前文本**（不读 `origin/main` 的可变引用）。取不到 ⇒ 显式失败。"""
    assert GUARD.is_file(), (
        f"反空跑锚点：#4828 的守卫文件不存在 → {GUARD}（机制被删除）—— 这不是「通过」"
    )
    text = GUARD.read_text(encoding="utf-8")
    assert "all_violations" in text, "反空跑锚点：读到的文件里没有 all_violations（判据已过期）"
    return text


# ══════════════════════════════════════════════════════════════════════════
# 一、真实文件：机制必须完整
# ══════════════════════════════════════════════════════════════════════════

def test_guard_mechanism_is_intact():
    """#4828 的防再犯机制在真实文件上必须完整（判据齐 + 全接线 + 红证齐 + 反空跑助手在）。"""
    v = guard_violations(read_guard())
    assert not v, "防再犯机制不完整：\n- " + "\n- ".join(v)


def test_floors_match_reality_and_are_not_vacuous():
    """🔴 反空跑锚点：地板必须**真的**卡在当前规模上，而不是恒真的摆设。

    没有这一条，`JUDGE_FLOOR = 0` 这类「把地板调没」的改动会让上面那条判据永远通过。
    """
    text = read_guard()
    actual = {
        "judge": len(set(JUDGE_DEF.findall(text))),
        "injection": len(INJECTION_DEF.findall(text)),
        "exec": len(EXEC_DEF.findall(text)),
    }
    floors = {"judge": JUDGE_FLOOR, "injection": INJECTION_FLOOR, "exec": EXEC_FLOOR}
    assert actual == floors, (
        f"地板与实际规模不一致（地板只许上调、且必须与现状一致）：实际 {actual} / 地板 {floors}"
    )
    assert min(floors.values()) > 0, f"地板里出现 0 ⇒ 该条判据退化成恒真：{floors}"


# ══════════════════════════════════════════════════════════════════════════
# 二、注入式红证（§0 的「把该机制去掉 ⇒ 必须变红」，四个形态各一条）
# ══════════════════════════════════════════════════════════════════════════

def _inject(text: str, old: str, new: str) -> str:
    """替换注入；**没替换到 / 没改变文本 ⇒ 显式失败**（否则红证是空跑）。"""
    assert old in text, f"注入锚点不存在（判据已过期）：{old[:60]!r}"
    out = text.replace(old, new, 1)
    assert out != text, "注入没有改变文本（空跑）"
    return out


def test_injection_delete_the_guard_file_goes_red(monkeypatch, tmp_path):
    """🔴 红证①：**整个守卫文件被删除** ⇒ 必须红（这正是「把机制去掉」的直接形态）。"""
    import sys
    mod = sys.modules[__name__]
    monkeypatch.setattr(mod, "GUARD", tmp_path / "test_swas_deploy_blue_green.py")
    with pytest.raises(AssertionError) as ei:
        mod.read_guard()
    assert "机制被删除" in str(ei.value)


def test_injection_gut_one_judge_wiring_goes_red():
    """🔴 红证②：摘掉 `all_violations()` 里的一条接线（判据还在、但静默不生效）⇒ 必须红。"""
    text = read_guard()
    injected = _inject(text, "        + judge_switch_scope_follows_gate(text)\n", "")
    v = guard_violations(injected)
    assert any("judge_switch_scope_follows_gate" in x and "接线" in x for x in v), v


def test_injection_drop_injection_proofs_goes_red():
    """🔴 红证③：把注入式红证**全删**（判据退化成空断言）⇒ 必须红。"""
    text = read_guard()
    stripped = INJECTION_DEF.sub("def _removed_placeholder(", text)
    assert stripped != text and not INJECTION_DEF.search(stripped), "反空跑锚点：注入没生效"
    v = guard_violations(stripped)
    assert any("注入式红证" in x for x in v), v


def test_injection_drop_case_ids_declaration_goes_red():
    """🔴 红证④：删掉 `# case_ids:` 声明（QA Growth Gate 会 block）⇒ 必须红。"""
    text = read_guard()
    injected = _inject(text, "# case_ids: MC-012\n", "")
    v = guard_violations(injected)
    assert any("case_ids" in x for x in v), v


def test_injection_remove_anti_vacuity_helper_goes_red():
    """🔴 红证⑤：拿掉 `_inject` 的「注入没有改变文本」自断言（红证变空跑）⇒ 必须红。"""
    text = read_guard()
    injected = _inject(text, '    assert out != text, "注入没有改变文本（空跑）"\n', "")
    v = guard_violations(injected)
    assert any("_inject" in x or "空跑" in x for x in v), v
