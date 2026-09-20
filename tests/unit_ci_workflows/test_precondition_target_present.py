# case_ids: AS-003, AS-005, CH-011, CH-016, CH-024, CH-025, CH-035, DF-020, DF-021, HR-003, OR-008, OR-012, OR-013, PG-013
"""「前置靶子消失了却不判红」的**防再犯守卫**（issue #4838）。

## 病灶（假绿缺口，与本仓反复登记的「无因果红/绿」同族，方向相反）

`check_precondition_drift` 的基线判据（`before != expect`）**只在用例声明 `expect` 时生效**，
而本仓既有口径是「只声明 `precondition`、**有意不给** `expect`」（给精确值 = 依赖栈的恒红
判据，反模式已由 `CH-034` 登记）⇒ 这类用例在「**靶子本来就不存在 / 被清零**」时 `before`
与 `after` 可以**一致地**都是 0 ⇒ 三条判据全不触发 ⇒ **静默拿到绿**，而结论是在靶子不存在
的情况下得出的（与「agent 行为正确」无因果）。

## 机制（本文件锁的就是它，两条腿）

1. **runner 侧**：`_PRECONDITION_TYPES` 的每个 type 必须**显式**声明靶子存在性下界 `min`
   （计数型 = 1；非计数型 = `None`，由自己的判定函数承重），`check_precondition_drift`
   **恒**判 `min(capture, after) < 下界`（下界 = `expect_min` > `expect: 0` ⇒ 0 > 类型 `min`）；
   缺 `min` 键 ⇒ `check_precondition_declared` 报 config_error（fail-closed）。
2. **本文件**：扫**真实用例库**的每一条计数前置，把「靶子不存在」注入进去，要求**必须变红**。

## 它以后会拦住什么

- ① **新增计数型前置类型却漏掉下界**（`min` 缺键 / 被调成 0）⇒ 直接 config_error 或本文件判红
  ⇒ 不会再出现「一类新用例的靶子没了也判绿」；
- ② **任何「靶子被清零 / 本来就不存在」的运行** ⇒ 判红并明说「本次红/绿**不可归因于 agent
  行为**」—— 把「**没测到**」与「**测了且通过**」在报告里分开（进 `case_asset_failures`，不进
  `deterministic_failures`）；
- ③ **有人把下界逻辑删掉 / 调成 0 / 只判 `before`** ⇒ 本文件的注入式红证（
  `TestRedProofOfTheMechanism`）与行为判据同时变红。

## 为什么**不**用「补个 `expect: <N>`」

`before != expect` 的精确值随种子/栈而变（同一手机号叠加 B 端种子后订单数不同）⇒ 恒红，
属 `CH-034` 登记的反模式。下界只取**结构最小值 1**（「靶子还在不在」），不随栈漂移。
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / ".github") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / ".github"))

from render_cases import load_case_dicts  # noqa: E402

_RUNNER_CACHE = {}


def _runner():
    """加载 runner（缓存：注入式红证要 monkeypatch **同一个** module 对象）。"""
    if "mod" not in _RUNNER_CACHE:
        path = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"
        spec = importlib.util.spec_from_file_location("local_runner_precond_bound", path)
        assert spec and spec.loader, f"无法加载 runner: {path}"
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        _RUNNER_CACHE["mod"] = mod
    return _RUNNER_CACHE["mod"]


def _cases() -> dict:
    """真实用例库（`id → case`）—— 判据**不写死用例清单**，新增用例自动进入扫描。"""
    return {c["id"]: c for c in load_case_dicts(REPO_ROOT / ".github" / "cases")
            if isinstance(c, dict) and c.get("id")}


def _registered_specs(cases: dict) -> list:
    """全库**可运行**的前置声明 → `[(case_id, type, source, spec)]`（散文形态不计）。"""
    out = []
    for cid, case in sorted(cases.items()):
        for s in (case.get("precondition") or []):
            if not isinstance(s, dict):
                continue
            t = str(s.get("type") or "")
            src = str(s.get("source") or "")
            if not t or not src:
                continue
            out.append((cid, t, src, s))
    return out


def _classify(lr, spec: dict, t: str) -> str:
    """按**有效下界**给声明分类（与 runner 同一份取值口径，不复制规则）。"""
    lower = lr.precondition_lower_bound(spec, t)
    if lower is None:
        return "non_count"          # 不按件数判存在性（由自己的判定函数承重）
    return "existence" if lower >= 1 else "absence"


def _silent_green_gaps(lr, specs: list) -> list:
    """把「靶子不存在」注入给定的**存在性前置**列表 ⇒ 返回**仍静默判绿**的条目（空 = 无缺口）。

    两个注入场景（对应 issue #4838 的两个真实失效方向）：
      · `capture=0, after=0` —— 靶子**开跑前就不在**（种子没生成 / 数据被清零 / 换栈）；
      · `capture=1, after=0` —— 靶子在**运行期间被清零**（只判 `before` 会漏掉这一格；
        取 1 = 「本来正好一份」，是**结构最小值**，不依赖任何栈相关量）。

    ⚠️ 入参 `specs` 由调用方（用**未被注入的**类型表）算好传入 —— 红证要在**已注入**
    的 runner 上评估读数，若在这里重新分类就会把注入后的分类结果当成靶子清单（空跑）。
    """
    gaps = []
    for cid, t, src, spec in specs:
        key = f"{t}:{src}"
        for before, after, label in ((0, 0, "开跑前就不在"), (1, 0, "运行期间被清零")):
            if not lr.check_precondition_drift([spec], {key: before}, {key: after}):
                gaps.append((cid, t, src, label))
    return gaps


def _existence_specs(lr, cases: dict) -> list:
    """全库中**「靶子必须存在」**类的前置声明（本单要判红的那一类）。"""
    return [(cid, t, src, s) for cid, t, src, s in _registered_specs(cases)
            if _classify(lr, s, t) == "existence"]


def _library_gaps(lr, cases: dict) -> list:
    """修复后应有的答案：**空**（库里的存在性前置在靶子被清零时都会判红）。"""
    return _silent_green_gaps(lr, _existence_specs(lr, cases))


class TestLibraryScanIsNotVacuous:
    """防「空跑」：扫描必须真的覆盖到本单的那一类声明（否则守卫绿得毫无意义）。"""

    def test_gap_class_exists_in_the_library(self):
        """「只声明 precondition、不给 expect」这一类必须**真的在库里**（本单的靶子）。"""
        lr, cases = _runner(), _cases()
        gap_class = [(cid, t, src, s) for cid, t, src, s in _registered_specs(cases)
                     if _classify(lr, s, t) == "existence" and s.get("expect") is None]
        assert gap_class, (
            "全库找不到「只声明 precondition、不给 expect」的计数前置 ⇒ 本守卫是**空跑**："
            "要么这一类被清空了（请同步删掉本文件），要么 runner 的取值口径变了")

    @pytest.mark.parametrize("kind", ["existence", "absence", "non_count"])
    def test_every_class_has_real_instances(self, kind):
        """三类都必须有真实实例 —— 否则对应那条判据（判红 / 防假红 / 豁免）从未被行使。"""
        lr, cases = _runner(), _cases()
        got = [cid for cid, t, src, s in _registered_specs(cases)
               if _classify(lr, s, t) == kind]
        assert got, f"「{kind}」这一类在库里没有实例 ⇒ 该分支的判据无判别力可言"

    def test_every_registered_spec_is_classified(self):
        """完整性：库里的每一条可运行前置都必须落进某一类（不许有被扫描静默跳过的）。"""
        lr, cases = _runner(), _cases()
        specs = _registered_specs(cases)
        assert specs, "全库没有任何可运行的前置声明 ⇒ 扫描是空跑"
        assert all(_classify(lr, s, t) in ("existence", "absence", "non_count")
                   for _, t, _, s in specs)


class TestAbsentTargetIsNeverSilentlyGreen:
    """**行为判据**：靶子不存在 / 被清零时，真实用例库的每一条存在性前置都必须判红。"""

    def test_library_scan_finds_no_silent_green(self):
        gaps = _library_gaps(_runner(), _cases())
        assert gaps == [], (
            "以下前置在「靶子不存在 / 被清零」时**静默判绿**（= #4838 的假绿缺口，"
            f"结论与 agent 行为无因果）：{gaps}")

    def test_absent_target_message_says_not_attributable(self):
        """判红还不够：消息必须**明说不可归因于 agent**（否则又被读成 agent 失败）。"""
        lr = _runner()
        spec = [{"type": "order_count_for_phone", "source": "13800138000"}]
        key = "order_count_for_phone:13800138000"
        issues = lr.check_precondition_drift(spec, {key: 0}, {key: 0})
        assert issues, "靶子不存在却判绿（#4838 的缺口本身）"
        assert "不可归因于 agent" in issues[0], f"消息没把归因说清：{issues[0]}"
        assert "靶子不存在" in issues[0], f"消息没点名失效形态：{issues[0]}"
        assert "capture=0" in issues[0], f"消息缺读数（无法复核）：{issues[0]}"

    def test_zeroed_during_run_message_says_cleared(self):
        """只判 `before` 会漏掉「运行期间被清零」—— 这一格必须单独可辨。"""
        lr = _runner()
        spec = [{"type": "order_count_for_phone", "source": "13800138000"}]
        key = "order_count_for_phone:13800138000"
        issues = lr.check_precondition_drift(spec, {key: 3}, {key: 0})
        assert issues, "靶子在运行期间被清零却判绿"
        assert "被清零" in issues[0], f"没点名「运行期间消失」：{issues[0]}"
        assert "capture=3 → after=0" in issues[0], f"消息缺两个读数：{issues[0]}"


class TestNoFalseRed:
    """**防恒红**（本单的硬约束）：正常路径与「靶子必须不存在」的语义都不得被判红。"""

    def test_healthy_target_stays_green(self):
        """未声明 expect、靶子在且稳定 ⇒ 必须**无**问题（下界不是恒红判据）。"""
        lr = _runner()
        spec = [{"type": "order_count_for_phone", "source": "13800138000"}]
        key = "order_count_for_phone:13800138000"
        assert lr.check_precondition_drift(spec, {key: 3}, {key: 3}) == []

    def test_lower_bound_is_stable_across_stack_values(self):
        """下界只认「还在不在」：读数 1 / 3 / 17 都必须绿（不随栈漂移 = 不退回 CH-034）。"""
        lr = _runner()
        spec = [{"type": "order_count_for_phone", "source": "13800138000"}]
        key = "order_count_for_phone:13800138000"
        for n in (1, 3, 17):
            assert lr.check_precondition_drift(spec, {key: n}, {key: n}) == [], f"读数 {n} 被判红"

    def test_absence_premise_is_not_flagged(self):
        """`expect: 0` = 「靶子**必须不存在**」（HR-002 创建前置）⇒ 下界 0，自建成功不得判红。"""
        lr = _runner()
        spec = [{"type": "employee_count_for_phone", "source": "13812345678",
                 "expect": 0, "max_growth": 1}]
        key = "employee_count_for_phone:13812345678"
        assert lr.check_precondition_drift(spec, {key: 0}, {key: 1}) == [], (
            "把「自建成功」判成了「靶子消失」⇒ 归因污染（比原缺口更坏）")

    def test_non_count_type_has_no_bound(self):
        """非计数型（HR-009/HR-010 的权限前置）不得被编一个件数下界。"""
        lr = _runner()
        spec = [{"type": "debug_permissions_effective", "source": "employee:list"}]
        key = "debug_permissions_effective:employee:list"
        assert lr.precondition_lower_bound(spec[0], spec[0]["type"]) is None
        assert lr.check_precondition_drift(spec, {key: 0}, {key: 0}) == []


class TestExistingAssertionsUnchanged:
    """**不得削弱既有断言**：①② 两条原有判据的语义与措辞逐条锁定。"""

    def test_exact_expect_still_red_on_mismatch(self):
        lr = _runner()
        spec = [{"type": "product_count_for_keyword", "source": "遮光窗帘", "expect": 1}]
        key = "product_count_for_keyword:遮光窗帘"
        issues = lr.check_precondition_drift(spec, {key: 2}, {key: 2})
        assert issues, "`expect` 基线判据被削弱了"
        assert "本就不成立" in issues[0] and "expect=1" in issues[0]

    def test_growth_drift_still_red(self):
        lr = _runner()
        spec = [{"type": "product_count_for_keyword", "source": "遮光窗帘"}]
        key = "product_count_for_keyword:遮光窗帘"
        issues = lr.check_precondition_drift(spec, {key: 1}, {key: 2})
        assert issues, "漂移判据被削弱了"
        assert "漂移" in issues[0]

    def test_max_growth_still_tolerates(self):
        lr = _runner()
        spec = [{"type": "product_count_for_keyword", "source": "星夜",
                 "expect": 0, "max_growth": 1}]
        key = "product_count_for_keyword:星夜"
        assert lr.check_precondition_drift(spec, {key: 0}, {key: 1}) == []

    def test_probe_failure_is_still_not_reported(self):
        """取不到读数（环境层）仍**不报** —— 不得把网络抖动伪装成「前置不成立」。"""
        lr = _runner()
        spec = [{"type": "order_count_for_phone", "source": "13800138000"}]
        assert lr.check_precondition_drift(spec, {}, {}) == []

    def test_unknown_type_still_fail_closed(self):
        lr = _runner()
        bad = lr.check_precondition_declared([{"type": "no_such_type", "source": "x"}])
        assert bad and "没有实现" in bad[0]


class TestTypeTableCarriesTheBound:
    """类型表本身：每个 type 必须**显式**声明下界（缺键 = fail-closed，不静默当无下界）。"""

    def test_every_type_declares_what_and_min_explicitly(self):
        for t, meta in _runner()._PRECONDITION_TYPES.items():
            assert isinstance(meta, dict), f"{t} 的值不是元数据字典（旧形态 = 无下界）"
            assert "min" in meta, f"{t} 缺 `min` 键 ⇒ 该类型的靶子被清零时静默判绿"
            assert isinstance(meta.get("what"), str) and meta["what"].strip(), (
                f"{t} 缺可读措辞 `what`（报告里读不出「哪个靶子坏了」）")

    def test_count_types_have_a_positive_bound(self):
        """**形态判据**（不写死类型清单）：名字含 `_count_` ⇒ 计数型 ⇒ 下界必须 ≥ 1。

        残留（如实登记）：名字**不含** `_count_` 的计数型会漏过本条 —— 它仍被
        `TestAbsentTargetIsNeverSilentlyGreen` 的**行为**判据覆盖（注入读数必须变红），
        故不构成静默绿的逃生口。
        """
        for t, meta in _runner()._PRECONDITION_TYPES.items():
            if "_count_" in t:
                assert isinstance(meta.get("min"), int) and meta["min"] >= 1, (
                    f"计数型 {t} 的下界是 {meta.get('min')!r} ⇒ 靶子被清零时判绿（#4838）")

    def test_missing_min_key_is_a_config_error(self, monkeypatch):
        """**注入**：注册一个漏掉下界的新类型 ⇒ 声明层必须 fail-closed 报错（不静默放行）。"""
        lr = _runner()
        patched = dict(lr._PRECONDITION_TYPES)
        patched["brand_new_count_for_thing"] = {"what": "漏了下界的新类型"}
        monkeypatch.setattr(lr, "_PRECONDITION_TYPES", patched)
        issues = lr.check_precondition_declared(
            [{"type": "brand_new_count_for_thing", "source": "x"}])
        assert issues, "缺 `min` 的新类型被静默放行 ⇒ 假绿缺口可被重新引入"
        assert "min" in issues[0]

    def test_malformed_expect_min_is_a_config_error(self):
        lr = _runner()
        for bad_value in (-1, None, True, "abc"):
            bad = lr.check_precondition_declared(
                [{"type": "order_count_for_phone", "source": "13800138000",
                  "expect_min": bad_value}])
            assert bad and "expect_min" in bad[0], (
                f"非法 expect_min={bad_value!r} 被静默跳过：{bad}")
        assert lr.check_precondition_declared(
            [{"type": "order_count_for_phone", "source": "13800138000", "expect_min": 1}]) == []

    def test_malformed_expect_min_does_not_disable_the_bound(self):
        """**关键逃生口**：`expect_min: null`（YAML 里写成 `expect_min:` 空值）**不得**
        把下界变成「无」—— 那等于用一行空声明把本单的缺口重新打开。

        判据：形态非法 ⇒ 回退到 ②③（这里 = 类型结构下界 1）⇒ 靶子不存在**仍然判红**；
        同时该声明被 `check_precondition_declared` 判 config_error（两处都不放过）。
        """
        lr = _runner()
        spec = [{"type": "order_count_for_phone", "source": "13800138000", "expect_min": None}]
        key = "order_count_for_phone:13800138000"
        assert lr.precondition_lower_bound(spec[0], spec[0]["type"]) == 1, (
            "`expect_min: null` 把下界抹掉了 ⇒ 缺口可被一行空声明重新打开")
        assert lr.check_precondition_drift(spec, {key: 0}, {key: 0}), (
            "`expect_min: null` 之后靶子不存在却判绿")
        assert lr.check_precondition_declared(spec), "非法 `expect_min` 没被判 config_error"

    def test_expect_min_raises_the_bound(self):
        """显式 `expect_min` 可抬高下界（用例自己声明最小可判定条件）。"""
        lr = _runner()
        spec = [{"type": "product_count_for_keyword", "source": "遮光窗帘", "expect_min": 2}]
        key = "product_count_for_keyword:遮光窗帘"
        assert lr.check_precondition_drift(spec, {key: 1}, {key: 1}), "expect_min 没生效"
        assert lr.check_precondition_drift(spec, {key: 2}, {key: 2}) == []

    def test_expect_min_zero_is_an_explicit_opt_out(self):
        """显式 `expect_min: 0` = 「本前置不判靶子存在性」—— **必须写在用例里**才生效。"""
        lr = _runner()
        spec = [{"type": "product_count_for_keyword", "source": "遮光窗帘", "expect_min": 0}]
        key = "product_count_for_keyword:遮光窗帘"
        assert lr.check_precondition_drift(spec, {key: 0}, {key: 0}) == []


class TestRedProofOfTheMechanism:
    """**注入式红证**：把机制退回**修复前**的形态 ⇒ 本文件的判据必须变红。

    红证不是"再跑一遍绿"：它把**修复前的行为**当成被测对象。若有人删掉 runner 的下界逻辑、
    把某个 type 的 `min` 调成 `None`/0、或只判 `before`，下面的断言即红。
    """

    @staticmethod
    def _old_behaviour_metadata(lr) -> dict:
        """修复前的类型表形态：只有措辞、**没有任何下界**（= `min` 恒为 None）。"""
        return {t: {"what": m.get("what"), "min": None}
                for t, m in lr._PRECONDITION_TYPES.items()}

    def test_scan_goes_red_when_the_bound_is_removed(self, monkeypatch):
        lr, cases = _runner(), _cases()
        targets = _existence_specs(lr, cases)          # 用**未被注入**的类型表算靶子清单
        assert targets, "库里没有存在性前置 ⇒ 本红证是空跑"
        assert _silent_green_gaps(lr, targets) == [], "修复后本应无缺口（先确立对照）"
        monkeypatch.setattr(lr, "_PRECONDITION_TYPES", self._old_behaviour_metadata(lr))
        gaps = _silent_green_gaps(lr, targets)
        assert gaps, (
            "把靶子存在性下界退回**修复前**的形态（`min` 全为 None）后，扫描仍报「无缺口」"
            "⇒ 本守卫是空断言，抓不住 #4838")
        # 判别力必须覆盖**全部**存在性前置（不是偶然命中一两条）
        assert {g[0] for g in gaps} == {cid for cid, _, _, _ in targets}, (
            "注入旧形态后，仍有一部分存在性前置**判绿**（那些用例的靶子没了也看不出来）")

    def test_behavioural_criterion_goes_red_when_bound_is_removed(self, monkeypatch):
        """同一注入下的**单条行为**红证（读起来最直白的那一条）。"""
        lr = _runner()
        spec = [{"type": "order_count_for_phone", "source": "13800138000"}]
        key = "order_count_for_phone:13800138000"
        assert lr.check_precondition_drift(spec, {key: 0}, {key: 0}), "修复后：必须判红"
        monkeypatch.setattr(lr, "_PRECONDITION_TYPES", self._old_behaviour_metadata(lr))
        assert lr.check_precondition_drift(spec, {key: 0}, {key: 0}) == [], (
            "修复前的形态本应静默判绿（红证的对照项）—— 它变了说明红证的对照已失效")
