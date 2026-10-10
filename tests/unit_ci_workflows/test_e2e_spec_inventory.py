# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 —— 见同目录
#   `test_gate_coverage_and_same_source.py` 的同款声明。本 PR 不新建用例族：仓库没有「开发工具链」用例族。）
r"""**e2e spec 库存不变量**（issue #6724）——「注册了但从未跑过」不许匿名存在。

## 病根（一类缺陷：**文件在树里 ≠ 有东西跑它**）

`tests/e2e/specs/**/*.spec.ts` 里 45 个 spec，只有 6 个被 workflow 的 run 命令**逐字引用**
（`pr-check.yml` 的显式列表）。唯一的兜底腿 `nightly-verification.yml` 的 `schedule` **已被注释掉**
（只剩 `workflow_dispatch`，注释写明「待失败根因排查 + 本地验证提速落地后再恢复」；其最近 4 次运行
2026-09-14/15 **全部 failure**）⇒ **其余 39 个 spec 在 CI 里哪儿都不跑**。

后果与「#5396 半成品落 main」同族：**没有东西会因为"这个 spec 没人跑"而变红**；后来者看到树里有 spec
会以为该类有真浏览器判据，最终大概率当死代码删掉（真实损失是**覆盖悄悄消失**）。

## 判据（两条，各自能单独变红）

1. **未登记即红**：`计算出的未跑集合 ⊄ 台账` ⇒ 红（新写的 spec 若没人引用会当场爆）。
2. **逐项相等（只许缩短）**：`台账 ⊄ 计算出的未跑集合` ⇒ 红（spec 被并进 workflow 后**必须删台账条目**，
   否则留下僵尸条目 = 台账在撒谎）；`计数` 与 `集合` 双向比对，任一侧多一条都红。

## 红证（`TestRedProofs`，注入式，不依赖真实文件）

- 造假一个「没人引用的 spec」⇒ **未登记即红**；
- 从台账里删掉一条 ⇒ **未登记即红**（同一条 spec 既在计算集合里又不在台账里）；
- 让某 spec 变成「被 workflow 引用」但仍留在台账 ⇒ **僵尸条目红**。

## 边界（判据说不了的）

- 判据**不判断**「该不该让它跑」（PR 侧跑全部 = CI 成本决策，属产品/流程裁定），只保证**缺口具名**；
- 判据**不校验** spec 内容（是不是空壳、是不是真断言）——那是另一类判据；
- `nightly-verification.yml` 恢复后本台账应清到 0 条；**判据不会自动清**，是**人/包**按「只许缩短」手动清。
"""

from __future__ import annotations

import json
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SPECS_GLOB = "tests/e2e/specs/**/*.spec.ts"
LEDGER = REPO_ROOT / "tests/unit_ci_workflows/e2e_spec_inventory_ledger.json"


def _discover_specs(root: pathlib.Path = REPO_ROOT) -> list[str]:
    """仓内 spec 的相对路径（相对 `tests/`，与 workflow 里的写法一致）。"""
    base = root / "tests"
    return sorted(p.relative_to(base).as_posix() for p in (base / "e2e/specs").rglob("*.spec.ts"))


def _workflow_texts(root: pathlib.Path = REPO_ROOT) -> list[str]:
    wf = root / ".github/workflows"
    return [p.read_text(encoding="utf-8", errors="ignore") for p in sorted(wf.glob("*.yml"))]


def _computed_unrun(specs: list[str], texts: list[str]) -> list[str]:
    """未被**任何** workflow 的文本逐字引用的 spec。"""
    return [s for s in specs if not any(s in t for t in texts)]


def _ledger():
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def test_new_unrun_spec_must_be_registered():
    """未登记即红：计算出的未跑集合必须被台账覆盖。"""
    computed = set(_computed_unrun(_discover_specs(), _workflow_texts()))
    registered = set(_ledger()["specs"])
    missing = sorted(computed - registered)
    assert not missing, (
        "以下 spec **没有任何 workflow 引用、也不在本台账里** ⇒ 它不会在 CI 里跑，且没人知道：\n  "
        + "\n  ".join(missing)
        + f"\n（要么把它加进某条 workflow 的 run 命令，要么登记进 {LEDGER.name} 并写明载体/重启条件）"
    )


def test_ledger_has_no_zombie_entries():
    """逐项相等（只许缩短）：台账条目若已被 workflow 引用，必须删掉。"""
    computed = set(_computed_unrun(_discover_specs(), _workflow_texts()))
    registered = set(_ledger()["specs"])
    zombie = sorted(registered - computed)
    assert not zombie, (
        "台账里有**僵尸条目**（这些 spec 已被 workflow 引用，却仍留在台账里 ⇒ 台账在撒谎）：\n  "
        + "\n  ".join(zombie)
    )


def test_ledger_shape_is_pinned():
    """元数据必须齐（载体/理由/重启条件不许缺）——否则台账会退化成一张无解释的名单。"""
    led = _ledger()
    for key in ("schema", "issue", "_what", "_why_this_shape", "_reason", "specs"):
        assert key in led, f"台账缺字段 {key}"
    assert led["issue"] == 6724
    assert isinstance(led["specs"], list) and led["specs"] == sorted(set(led["specs"])), (
        "specs 必须是**去重且有序**的列表（顺序无关的集合语义 + 稳定 diff）"
    )


class TestRedProofs:
    """注入式红证：证明上面两条判据**真的会红**（不依赖真实文件被改坏）。"""

    def test_fake_unrun_spec_is_red(self, monkeypatch):
        import tests.unit_ci_workflows.test_e2e_spec_inventory as mod

        fake = "e2e/specs/__injected__/nobody-runs-me.spec.ts"
        monkeypatch.setattr(mod, "_discover_specs", lambda root=None: _discover_specs() + [fake])
        computed = set(_computed_unrun(mod._discover_specs(), mod._workflow_texts()))
        registered = set(mod._ledger()["specs"])
        assert fake in computed - registered, "注入的没人跑的 spec 必须落进「未登记」⇒ 判据①会红"

    def test_dropping_a_ledger_entry_is_red(self, monkeypatch):
        import tests.unit_ci_workflows.test_e2e_spec_inventory as mod

        led = mod._ledger()
        dropped = sorted(led["specs"])[0]
        led["specs"] = [s for s in led["specs"] if s != dropped]
        monkeypatch.setattr(mod, "_ledger", lambda: led)
        computed = set(mod._computed_unrun(mod._discover_specs(), mod._workflow_texts()))
        registered = set(mod._ledger()["specs"])
        assert dropped in computed - registered, "删掉台账条目后该 spec 必须落进「未登记」⇒ 判据①会红"

    def test_zombie_entry_is_red(self, monkeypatch):
        import tests.unit_ci_workflows.test_e2e_spec_inventory as mod

        led = mod._ledger()
        referenced = "e2e/specs/quality/api-contract.spec.ts"  # 已被 pr-check.yml 逐字引用
        led["specs"] = sorted(set(led["specs"]) | {referenced})
        monkeypatch.setattr(mod, "_ledger", lambda: led)
        computed = set(mod._computed_unrun(mod._discover_specs(), mod._workflow_texts()))
        registered = set(mod._ledger()["specs"])
        assert referenced in registered - computed, "已被引用的 spec 留在台账 ⇒ 僵尸条目判据会红"
