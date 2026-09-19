# case_ids: MC-012
"""「已被否证的活真值」必须**有地方变红**（issue #4430 / B3）。

## 缺陷（2026-09-19 实测，非推断）

`.github/templates/processing-manage.yml` 里 `[processing-manage.product-link] 加工项关联商品`
是**过期真值**：#4371 已把「商品 ↔ 加工项」绑定彻底解耦（关联表 `product_processing_items`
已由迁移 DROP，加工项改为**店铺级目录**）。而该模板只被 `truths.py check` 消费，它**只校验
引用完整性、不校验真值内容** ⇒ 过期真值**静默存活**：没人引用它，就没有任何东西会红。
形态属 `migao-acceptance` 的「不会红的断言 = 空断言」同族。

## 本守卫锁什么（零 LLM、零网络、不跑真实门禁）

1. **登记完备**：模板里每条 `retired_truths` 必须写 `retired_by`（否证它的 issue 号）
   与 `reason`（否证依据），否则 `truths.py check` 判红（`retired-meta`）；
2. **不留自相矛盾**：被登记的 ID **不得**仍留在 `business_truths`（`retired-live`）——
   否则索引/渲染仍把它当真值；
3. **无残留引用**：被登记的 ID **不得**再被 `.github/cases/**` 的 `truths_ref` 引用（`retired`）；
4. **现状判据**：`processing-manage.product-link` 已登记否证（`retired_by: 4371` + 依据点名
   已 DROP 的表）、已从 `business_truths` 移除、且当前用例库无引用；
5. **红证（注入法，三条形态各一）**：把上述三种坏形态分别**注入**临时模板/用例目录 ⇒
   `truths.py check` 必须 exit 1 且问题类型正确；**同一夹具不注入 ⇒ exit 0**（证明红由注入引起，
   不是夹具/环境本身红）。

⚠️ 本文件自身会被 CI 的 `--check-weak` 扫描（新增测试文件），故正文不得出现字面弱断言模式。
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
TRUTHS_PY = REPO_ROOT / ".github" / "truths.py"
TEMPLATES_DIR = REPO_ROOT / ".github" / "templates"
CASES_DIR = REPO_ROOT / ".github" / "cases"

# 被否证的那条真值（issue #4371 解耦后不再成立）+ 否证它的 issue 号
RETIRED_ID = "processing-manage.product-link"
RETIRED_BY = 4371


def _load_truths_module():
    """按文件路径加载 `truths.py`（`.github/` 不是包，无法 import）。

    取不到 spec/loader 时**抛错 fail-closed**（不用 `assert ... is not None`：那既是弱断言、
    又会在 `-O` 下被剥掉 —— 门禁依赖的加载不允许静默空转）。
    """
    spec = importlib.util.spec_from_file_location("truths_under_test", TRUTHS_PY)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载真值判定本体（判定缺失即门禁空转）：{TRUTHS_PY}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TRUTHS = _load_truths_module()

_CASE_TEMPLATE = """schema: "case-contract/1.0"
domain: injected
cases:
  - id: INJ-001
    title: "注入用用例"
    truths_ref:
      - {ref}
    user_inputs:
      - "注入用输入"
    expectations:
      - tool: direct_reply
"""


def _inject(tmp_path: Path, template_body: str, case_ref: str):
    """造一套最小 templates/cases 夹具 → (templates_dir, cases_dir)。

    `template_body` 决定真值模板内容，`case_ref` 决定用例引用哪条真值 ——
    两者都由调用方给定，故「红」只可能来自被注入的那一处。
    """
    templates = tmp_path / "templates"
    cases = tmp_path / "cases"
    templates.mkdir()
    cases.mkdir()
    (templates / "injected.yml").write_text(template_body, encoding="utf-8")
    (cases / "injected.yml").write_text(_CASE_TEMPLATE.format(ref=case_ref), encoding="utf-8")
    return templates, cases


def _kinds(report):
    return [p["kind"] for p in report["problems"]]


# ── 1~3. 判定本体：三种坏形态各一条红证 ──────────────────────────────────────
# 覆盖真值模板（形态与 `.github/templates/processing-manage.yml` 同风格：yaml_light 可解析）

_RETIRED_OK_TEMPLATE = """name: injected
business_truths:
  - [injected.alive] 仍然成立的真值
retired_truths:
  injected.dead:
    retired_by: 9999
    reason: "已被 issue #9999 否证：该绑定已解耦"
"""


def test_injected_reference_to_retired_truth_is_blocking(tmp_path):
    """红证 ①：用例引用了**已登记否证**的真值 ⇒ check exit 1（`retired`），且点名否证它的 issue。"""
    templates, cases = _inject(tmp_path, _RETIRED_OK_TEMPLATE, "injected.dead")
    report, code = TRUTHS.check_cases(str(cases), str(templates))

    assert code == 1, "引用已否证真值却放行 ⇒ 「过期真值」仍然静默存活（本单的缺陷形态）"
    assert _kinds(report) == ["retired"], f"问题类型必须只有 retired，实得 {_kinds(report)}"
    msg = report["problems"][0]["msg"]
    assert "9999" in msg, "报错必须点名否证它的 issue 号（否则没人知道该改用哪条现行真值）"
    assert report["retired_truths"] == 1


def test_control_without_injection_is_green(tmp_path):
    """对照（防「夹具本身红」）：同一模板，用例改引用**活着**的真值 ⇒ exit 0。"""
    templates, cases = _inject(tmp_path, _RETIRED_OK_TEMPLATE, "injected.alive")
    report, code = TRUTHS.check_cases(str(cases), str(templates))

    assert code == 0, f"夹具本身判红 ⇒ 上一条红证不成立：{report['problems']}"
    assert _kinds(report) == [], f"不该有任何问题，实得 {_kinds(report)}"


def test_retired_truth_still_listed_as_alive_is_blocking(tmp_path):
    """红证 ②：被登记否证的 ID 仍留在 `business_truths` ⇒ check exit 1（`retired-live`）。

    危害：索引/渲染仍把它当**活真值**（agent 查得到、报告里也列着）—— 一边否证一边活着。
    """
    body = """name: injected
business_truths:
  - [injected.alive] 仍然成立的真值
  - [injected.dead] 该绑定已解耦（过期条目，仍留在 business_truths）
retired_truths:
  injected.dead:
    retired_by: 9999
    reason: "已被 issue #9999 否证"
"""
    templates, cases = _inject(tmp_path, body, "injected.alive")
    report, code = TRUTHS.check_cases(str(cases), str(templates))

    assert code == 1, "既否证又活着必须判红（否则「否证」只是纸面动作）"
    assert _kinds(report) == ["retired-live"], f"实得 {_kinds(report)}"


@pytest.mark.parametrize("missing", ["retired_by", "reason"])
def test_retired_entry_without_evidence_is_blocking(tmp_path, missing):
    """红证 ③：否证登记缺 `retired_by` / `reason` ⇒ check exit 1（`retired-meta`）。

    没有依据的「否证」与「随手删掉一条真值」不可区分 —— 后者正是本单要治的静默形态。
    """
    lines = {"retired_by": "    retired_by: 9999", "reason": '    reason: "依据"'}
    lines.pop(missing)
    body = ("name: injected\n"
            "business_truths:\n"
            "  - [injected.alive] 仍然成立的真值\n"
            "retired_truths:\n"
            "  injected.dead:\n"
            + "\n".join(lines.values()) + "\n")
    templates, cases = _inject(tmp_path, body, "injected.alive")
    report, code = TRUTHS.check_cases(str(cases), str(templates))

    assert code == 1, f"否证登记缺 {missing} 必须判红"
    assert _kinds(report) == ["retired-meta"], f"实得 {_kinds(report)}"
    assert missing in report["problems"][0]["msg"], "报错必须点名缺的是哪个字段"


# ── 4. 现状判据（本 PR 的交付物真的落地了）────────────────────────────────────
def test_product_link_is_registered_as_retired_with_evidence():
    """`processing-manage.product-link` 必须**已登记否证**，且依据点名「表已 DROP」这一事实。"""
    retired, problems = TRUTHS.load_all_retired(str(TEMPLATES_DIR))

    assert problems == [], f"模板里的否证登记自身不完整：{problems}"
    assert RETIRED_ID in retired, (
        f"{RETIRED_ID} 未登记否证 —— 它已被 issue #{RETIRED_BY} 否证（关联表已 DROP），"
        "留在模板里就是「过期真值静默存活」"
    )
    meta = retired[RETIRED_ID]
    assert int(meta["retired_by"]) == RETIRED_BY, (
        f"否证它的 issue 号必须是 #{RETIRED_BY}，实得 {meta['retired_by']!r}"
    )
    assert "product_processing_items" in str(meta["reason"]), (
        "否证依据必须点名「关联表已 DROP」这个可核对的事实（不能只写「已过时」）"
    )


def test_product_link_is_no_longer_a_live_truth():
    """过期条目必须从 `business_truths` 移除（否则它仍是「活真值」）。"""
    index, conflicts, _ = TRUTHS.load_all_truths(str(TEMPLATES_DIR))

    assert conflicts == [], f"真值 ID 冲突：{conflicts}"
    assert RETIRED_ID not in index, (
        f"{RETIRED_ID} 仍在 business_truths 里 —— 与 retired_truths 自相矛盾"
    )


def test_no_case_references_a_retired_truth():
    """当前用例库不得引用任何已否证真值（本 PR 的「① 删掉/改判」侧的落地判据）。"""
    report, code = TRUTHS.check_cases(str(CASES_DIR), str(TEMPLATES_DIR))

    assert code == 0, f"用例库存在阻塞问题：{[p for p in report['problems'] if p['kind'] != 'gap']}"
    assert [p for p in report["problems"] if p["kind"].startswith("retired")] == []
    assert report["retired_truths"] >= 1, "至少应有 1 条已否证登记（否则本判据空转）"


# ── 5. 门禁入口（与 CI `case-truth-check` / `verify-all.sh` **同命令**）────────
def test_ci_command_passes_and_query_reports_retired_actionably():
    """跑 CI 的同一条命令（真值引用校验）⇒ exit 0；`query` 查已否证真值 ⇒ exit 1 且可行动。

    红证：`query` 若不区分「已被否证」与「不存在」，agent 只会看到「真值不存在」，
    分不清是打错字还是该改用现行真值（本单要治的「过期真值无人可查」形态）。
    """
    check = subprocess.run(
        [sys.executable, str(TRUTHS_PY), "check",
         "--templates", str(TEMPLATES_DIR), "--cases", str(CASES_DIR)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert check.returncode == 0, f"真值引用校验判红：{check.stdout[-2000:]}"
    assert "已否证" in check.stdout, "check 的输出必须报告已否证条目数（否则该判据不可见）"

    query = subprocess.run(
        [sys.executable, str(TRUTHS_PY), "query", RETIRED_ID, "--templates", str(TEMPLATES_DIR)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert query.returncode == 1, "查已否证真值必须非零退出（它已不是可用真值）"
    assert "已被否证" in query.stderr, f"报错必须区分「已否证」与「不存在」：{query.stderr}"
    assert str(RETIRED_BY) in query.stderr, "必须点名否证它的 issue 号"


def test_retired_lookup_reads_the_same_templates_dir_as_the_gate():
    """哨兵：夹具指向的就是 CI 消费的那两个目录（防「守卫扫了别的目录 ⇒ 恒绿」）。"""
    assert TRUTHS_PY.exists(), f"真值判定本体不存在：{TRUTHS_PY}"
    assert (TEMPLATES_DIR / "processing-manage.yml").exists(), (
        "被否证的条目所在模板不存在 ⇒ 现状判据扫的是空气"
    )
    assert CASES_DIR.is_dir() and any(CASES_DIR.glob("*.yml")), "用例库目录为空 ⇒ 判定空转"
    assert TRUTHS.BLOCKING_PROBLEM_KINDS >= {"unresolved", "duplicate", "retired",
                                             "retired-meta", "retired-live"}, (
        "阻塞类型集合必须含全部否证形态（少一个 ⇒ 该形态静默放行）"
    )
