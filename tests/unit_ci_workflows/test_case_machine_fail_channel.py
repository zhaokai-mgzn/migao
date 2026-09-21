# case_ids: PG-001, PG-002
"""用例的**机器判红通道**判据 + 只许非增的锚点（issue #5079）。

## 为什么单列这一条（#5079 的前提需要先被**修正**）

#5079 的读数「53/390 用例的可计分断言数为 0 ⇒ 这些用例声明的东西全不满足，评测照样绿」
用的是 `.github/assertion_taxonomy.py` 的 `scoring_assertion_count()` —— 函数用对了，
但**少了一步**：`Case Trust Gate` 的规则 a1（`CASE-TRUST-EMPTY-ASSERTION`）还有一层
**计分通道分流**（#4244 / PR #4276）：

    a1 的前提是「该用例由 runner 计分」（`total_exp == 0` ⇒ `score = 1.0` ⇒ 恒绿）。
    但 `[backend-contract]` 用例**根本不进 agent-eval**（runner 按 `skip_reason` 过滤
    ⇒ 未运行：既不会绿也不会红），它们的机器判红通道是 `traces.tests`（Java / pytest 单测）。

⇒ 「可机器判红」的正确判据 = **「runner 计分断言非空」OR「走 `[backend-contract]` 的
`traces.tests` 通道且引用真实存在」**。实测（本文件 `test_i1_*`）：
53 条 `scoring_assertion_count == 0` 的用例**全部**满足后者 ⇒ 真正的「无任何机器判红通道」
用例数是 **0**，不是 53。⇒ 把它们当债务「燃尽」等于 `migao-acceptance` 明令禁止的
**纸面修复**（把散文改写成含 `success=true` 的形态、运行期零变化）。

## 本文件的判据（三条，均含注入式红证）

  · **I1（绝对不变量，无锚点）**：每条用例都至少有**一个**机器判红通道。
  · **I2（组成不变量）**：`scoring_assertion_count == 0` 的用例**必须**是豁免通道用例
    —— 这条正是 #5079 缺的那一步，也是让「53」这个读数**可解释**的那一步。
  · **I3（锚点，只许非增）**：`no_channel_total` 是**绝对下界 0**，history 链单调非增；
    `backend_contract_scoring_zero`（= 53）是**读数**，记进链里让漂移在 diff 里可见。

## I3 为什么不把 53 当天花板（有意取舍，写清楚）

把 53 设成「只许非增」的天花板会**误伤合法新增**：`[backend-contract]` 用例是设计上
不进 agent-eval 的一类（`skip-exemption-baseline.json` 的 `history` 已逐条记录过这种摩擦
——「每新增一条此类用例都要重锚 ⇒ 摩擦力归零」）。⇒ 真债务（`no_channel_total`）锁死为 0，
读数只锁「变更必须留 `note`」。
"""
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))

import assertion_taxonomy as tax  # noqa: E402
from render_cases import load_case_dicts  # noqa: E402

CASES_DIR = REPO_ROOT / ".github" / "cases"
ANCHOR = Path(__file__).with_name("case_machine_fail_channel_baseline.json")

CHANNEL_SCORING = "runner-scoring"
CHANNEL_TRACES = "backend-contract-traces"
#: 锚点里受管的度量名（history 每行都要有）。
ANCHOR_METRICS = ("no_channel_total", "backend_contract_scoring_zero")


# ══════════════════════════════════════════════════════════════════════════════
# 判据本体（纯函数 —— 注入式红证驱动**同一份**本体）
# ══════════════════════════════════════════════════════════════════════════════

def machine_fail_channel(case, repo_root):
    """该用例的机器判红通道名；`""` = **没有任何**机器判红通道（恒绿形态）。"""
    if tax.scoring_assertion_count(case) > 0:
        return CHANNEL_SCORING
    if tax.backend_contract_scoring_channel(case, repo_root):
        return CHANNEL_TRACES
    return ""


def cases_by_channel(cases, repo_root):
    """`{通道名: [case_id, ...]}`（通道名含 `""`）。"""
    out: dict = {}
    for c in cases:
        out.setdefault(machine_fail_channel(c, repo_root), []).append(str(c.get("id") or "?"))
    for v in out.values():
        v.sort()
    return out


def no_channel_cases(cases, repo_root):
    """I1 的违规集：没有任何机器判红通道的用例。"""
    return cases_by_channel(cases, repo_root).get("", [])


def scoring_zero_unexempt(cases, repo_root):
    """I2 的违规集：`scoring_assertion_count == 0` 却**不走**豁免通道的用例。"""
    return sorted(
        str(c.get("id") or "?") for c in cases
        if tax.scoring_assertion_count(c) == 0
        and not tax.backend_contract_scoring_channel(c, repo_root)
    )


def scoring_zero_total(cases):
    """#5079 的原始读数：`scoring_assertion_count == 0` 的用例数（**含**豁免通道用例）。"""
    return sum(1 for c in cases if tax.scoring_assertion_count(c) == 0)


#: 「像测试」的引用 = 代码扩展名 + 文件名含 test/spec（不含 conftest）。
#: 判据源与 `growth_gate._is_test_file` 同口径（**不另造一套**）：它已在别处被
#: 「弱断言扫描 / G5 用例追溯」共用，此处只做形状判定，不复制其过滤逻辑。
TEST_FILE_EXTS = (".py", ".java", ".ts", ".tsx", ".js")
_NOT_A_TEST_BASENAME = ("conftest.py", "conftest.ts")


def looks_like_test_file(ref):
    """该 `traces.tests` 引用是否**像测试文件**（防「拿任意存在的文件当计分通道」）。"""
    base = str(ref).split("/")[-1]
    if base in _NOT_A_TEST_BASENAME:
        return False
    if not base.endswith(TEST_FILE_EXTS):
        return False
    return re.search(r"(test|spec)", base, re.I) is not None


def exempt_channel_problems(cases, repo_root):
    """豁免通道的**健全性**问题列表（空 = 健全）。

    这几条把「豁免」从**万金油**收成**可判定的通道** —— 否则写个
    `skip_reason: [backend-contract]` + 随便一个存在的文件路径就能把任意用例
    从 I1 里摘出去（= 豁免自身变成假绿）：
      · `skip_reason` 必须以 `[backend-contract]` 开头；
      · `traces.tests` **至少一条像测试文件**且**真实存在**
        （允许同列引用被契约的产物，如 `DA-010` 并引 `DailyBriefingServiceTest.java`
         + `V44__create_daily_briefings.sql` —— 故判「≥1 条」而不是「全部」，
        否则会把真实合规形态判红）；
      · `traces.ci` 非空，且**每个** workflow 文件都真实存在
        （证明它指的是一个真实 CI job，而不是编出来的名字）。
    """
    problems = []
    for c in cases:
        cid = str(c.get("id") or "?")
        if not str(c.get("skip_reason") or "").strip().startswith(tax.BACKEND_CONTRACT_MARKER):
            problems.append(f"{cid}: 走了豁免通道却没有 `{tax.BACKEND_CONTRACT_MARKER}` skip_reason")
            continue
        refs = [str(r) for r in ((c.get("traces") or {}).get("tests") or [])]
        if not refs:
            problems.append(f"{cid}: `[backend-contract]` 但 `traces.tests` 为空")
        else:
            tests = [r for r in refs if looks_like_test_file(r)]
            if not tests:
                problems.append(
                    f"{cid}: `traces.tests` 里**没有任何像测试文件**的引用 {refs} —— "
                    f"拿任意存在的文件当计分通道 = 豁免退化成万金油"
                )
            for r in tests:
                if not (repo_root / r).is_file():
                    problems.append(f"{cid}: `traces.tests` 引用的 `{r}` 不存在")
        ci = [str(r) for r in ((c.get("traces") or {}).get("ci") or [])]
        if not ci:
            problems.append(f"{cid}: 走了豁免通道却没有 `traces.ci`（未指明哪个 CI job 跑它）")
        for r in ci:
            if not (repo_root / ".github" / "workflows" / r).is_file():
                problems.append(f"{cid}: `traces.ci` 引用的 workflow `{r}` 不存在")
    return problems


def anchor_drift(entries, history):
    """锚点链一致性 → 违规列表（空 = 一致）。

    规则：① `history` 非空；② `entries` 的两个度量 == `history` 末行同名键
    （改读数必须同时追加一行，让变更在 diff 里可见）；
    ③ `no_channel_total` 链上**恒为 0** 且单调非增（真债务只许清零，不许抬高）；
    ④ 相邻两行度量有变却无 `note` ⇒ 红（漂移必须写明理由）。
    """
    out = []
    if not history:
        return ["锚点 `history` 为空 —— 「只许非增的锚点」没有链可判"]
    tail = history[-1]
    for m in ANCHOR_METRICS:
        if entries.get(m) != tail.get(m):
            out.append(
                f"`entries.{m}`={entries.get(m)!r} ≠ history 末行 {tail.get(m)!r} —— "
                f"改读数必须**同时**追加一行 history（否则读数变化在 diff 里无声）"
            )
    prev = None
    for i, row in enumerate(history):
        v = row.get("no_channel_total")
        if v != 0:
            out.append(
                f"history[{i}].no_channel_total={v!r} ≠ 0 —— 本度量是**绝对下界**："
                f"任何用例都不得没有机器判红通道；回归必须**修**，不许抬锚点"
            )
        if prev is not None and isinstance(v, int) and v > prev:
            out.append(f"history[{i}].no_channel_total 上升（{prev} → {v}）—— 只许非增")
        if prev is not None:
            changed = [m for m in ANCHOR_METRICS if row.get(m) != history[i - 1].get(m)]
            if changed and not str(row.get("note") or "").strip():
                out.append(f"history[{i}] 改了 {changed} 却无 `note` —— 读数漂移必须写明理由")
        if isinstance(v, int):
            prev = v
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 真实仓库读数
# ══════════════════════════════════════════════════════════════════════════════

def _real_cases():
    cases = load_case_dicts(str(CASES_DIR))
    assert cases, "用例库读不到任何用例 —— 判据的扫描面失效（0 命中会是假绿）"
    return cases


def test_i1_every_case_has_a_machine_fail_channel():
    """I1：每条用例都至少有一个机器判红通道（绝对不变量，无锚点）。"""
    cases = _real_cases()
    bad = no_channel_cases(cases, REPO_ROOT)
    assert not bad, (
        f"{len(bad)} 条用例**没有任何机器判红通道**（既无 runner 计分断言，也不走 "
        f"`[backend-contract]` 的 `traces.tests`）⇒ `total_exp == 0` ⇒ `score = 1.0` 恒绿：\n  "
        + "\n  ".join(bad[:20])
        + "\n修法：补 `expectations` / 机器计分型 `data_checks`（`success=true` / `error.code=` / "
          "`未被调用`），或按 `[backend-contract]` 声明 `skip_reason` + 非空且**真实存在**的 "
          "`traces.tests`。**不许**把纯散文改写成看起来机器化的句子来骗计分（#5079 要治的就是这个）。"
    )


def test_i2_scoring_zero_cases_are_all_channel_exempt():
    """I2：`scoring_assertion_count == 0` 的用例必须**全部**走豁免通道（组成不变量）。"""
    cases = _real_cases()
    bad = scoring_zero_unexempt(cases, REPO_ROOT)
    assert not bad, (
        f"{len(bad)} 条用例 `scoring_assertion_count == 0` 且**不走**豁免通道：\n  "
        + "\n  ".join(bad[:20])
        + "\n这些才是 #5079 说的「恒绿」形态（runner 会给满分 1.0）"
    )


def test_i2_exempt_channel_is_actually_complete():
    """I2 的前提守卫：豁免通道必须**健全**（不能靠「写个 skip_reason + 随便一个存在的路径」拿到豁免）。

    否则「豁免」会退化成万金油：任意用例都能从 I1 里摘出去 ⇒ I1 变成空断言。
    """
    cases = _real_cases()
    exempt = [c for c in cases if machine_fail_channel(c, REPO_ROOT) == CHANNEL_TRACES]
    assert exempt, (
        "当前没有任何用例走 `traces.tests` 通道 —— 豁免通道的判定面失效（0 命中会是假绿），"
        "或 `backend_contract_scoring_channel` 的实现被改坏了"
    )
    problems = exempt_channel_problems(exempt, REPO_ROOT)
    assert not problems, (
        f"豁免通道不健全（{len(problems)} 项）⇒ I1 的「已豁免」是假绿：\n  "
        + "\n  ".join(problems[:20])
    )


def test_i3_anchor_matches_reality_and_is_only_shrinking():
    """I3：锚点与实测一致，且 `history` 链单调非增（`no_channel_total` 恒 0）。"""
    anchor = json.loads(ANCHOR.read_text(encoding="utf-8"))
    entries, history = anchor.get("entries") or {}, anchor.get("history") or []

    drift = anchor_drift(entries, history)
    assert not drift, "锚点链自身不一致：\n  " + "\n  ".join(drift)

    cases = _real_cases()
    actual = {
        "no_channel_total": len(no_channel_cases(cases, REPO_ROOT)),
        "backend_contract_scoring_zero": scoring_zero_total(cases),
    }
    assert actual == entries, (
        f"实测读数 {actual} 与锚点 `entries` {entries} 不一致 ⇒ 必须在**同一 PR** 里重锚："
        f"追加一行 history（`no_channel_total` 只许为 0；`backend_contract_scoring_zero` 变化"
        f"须写 `note` 说明来由），并把 `entries` 对齐到新末行"
    )
    assert entries["no_channel_total"] == 0, (
        "`no_channel_total` 必须为 0 —— 它是本判据真正的债务度量（#5079 的 53 是**读数**不是债务）"
    )


def test_i3_anchor_records_the_issue_premise_provenance():
    """锚点必须留**出处**：说明 #5079 的 53 是如何被复核成 0 债务的（可复查）。

    判据 = `_note` 同时提到「53」（被复核的读数）与「traces.tests」（分流依据）；
    否则下次读者无从判断这个 0 是怎么来的。
    """
    note = str(json.loads(ANCHOR.read_text(encoding="utf-8")).get("_note") or "")
    assert "53" in note, "锚点 `_note` 未记下被复核的原始读数（#5079 的 53）"
    assert "traces.tests" in note, "锚点 `_note` 未记下分流依据（`[backend-contract]` 的 `traces.tests`）"
    assert re.search(r"#5079|5079", note), "锚点 `_note` 未给出 issue 出处"


# ══════════════════════════════════════════════════════════════════════════════
# 注入式红证 —— 每条判据都必须能**单独**变红
# ══════════════════════════════════════════════════════════════════════════════

def _case(cid, **kw):
    base = {"id": cid, "skip_reason": "", "expectations": [], "data_checks": [], "traces": {}}
    base.update(kw)
    return base


class TestInjectionRedProofs:
    """喂变异样例 ⇒ 判据必须红；同时给负控，防「恒真」与「过度敏感」两种坏形态。"""

    def test_inject_zero_scoring_no_channel_reds_i1(self):
        """纯散文 data_checks + 无 skip_reason ⇒ 无通道 ⇒ I1 红（这就是 #5079 的病）。"""
        c = _case("ZZ-001", data_checks=["生成加工单成功（价格落库）"])
        assert machine_fail_channel(c, REPO_ROOT) == ""
        assert no_channel_cases([c], REPO_ROOT) == ["ZZ-001"]

    def test_prose_rewrite_does_not_create_a_channel(self):
        """**反作弊红证**：把散文「改写」成看起来机器化的句子**不得**产生通道。

        这是本单要治的病 —— 判据必须对「纸面修复」免疫：只要没命中 runner 的真实
        计分标记（`MACHINE_DATA_CHECK_MARKERS`），通道就仍然是空。
        """
        fake = _case("ZZ-002", data_checks=[
            "工具返回 success 为真",          # 没写 `success=true`
            "校验通过（等价于 success = true）",  # 有空格，不得命中
            "order_query 被调用过",            # 不是 `未被调用`
        ])
        assert machine_fail_channel(fake, REPO_ROOT) == "", (
            "判据被「看起来机器化」的措辞喂绿了 —— 说明通道判定没有复用 runner 的标记集"
        )
        # 正控：真正命中标记的形态必须产生通道
        real = _case("ZZ-003", data_checks=["生成成功（$.data[i].success=true）"])
        assert machine_fail_channel(real, REPO_ROOT) == CHANNEL_SCORING

    def test_inject_backend_contract_without_traces_reds_i1(self):
        """`[backend-contract]` 但 `traces.tests` 为空 ⇒ 豁免不成立 ⇒ I1 红。"""
        c = _case("ZZ-004", skip_reason="[backend-contract] 由某测试验证")
        assert machine_fail_channel(c, REPO_ROOT) == ""
        assert no_channel_cases([c], REPO_ROOT) == ["ZZ-004"]

    def test_inject_nonexistent_trace_file_reds_i1(self):
        """`traces.tests` 指向不存在的文件 ⇒ 豁免不成立（fail-closed）⇒ I1 红。"""
        c = _case("ZZ-005", skip_reason="[backend-contract] 由某测试验证",
                  traces={"tests": ["backend/does/not/exist/NoSuchTest.java"]})
        assert machine_fail_channel(c, REPO_ROOT) == "", (
            "引用不存在的测试文件却拿到了豁免 ⇒ 豁免会退化成万金油"
        )

    def test_inject_non_test_file_as_exemption_reds_guard(self):
        """**反作弊红证**：拿一个存在但**不是测试**的文件当豁免 ⇒ 健全性守卫必红。

        这是豁免通道最容易变成万金油的那条路：只要文件存在就行的话，
        `pom.xml` / 任意 `.md` / 迁移 SQL 都能把用例从 I1 里摘出去。
        """
        c = _case("ZZ-008", skip_reason="[backend-contract] 声称有测试",
                  traces={"tests": ["backend/admin-api/pom.xml"], "ci": ["pr-check.yml"]})
        # 注意：`backend_contract_scoring_channel` 只看存在性，所以它在 I1 层面确实「有通道」
        # —— 正因如此，健全性守卫必须是**独立**的一道，否则这个洞无人把守。
        assert machine_fail_channel(c, REPO_ROOT) == CHANNEL_TRACES
        problems = exempt_channel_problems([c], REPO_ROOT)
        assert any("没有任何像测试文件" in p for p in problems), (
            "拿 `pom.xml`（存在但非测试）当豁免却没被健全性守卫拦下 ⇒ 豁免是万金油"
        )

    def test_inject_missing_or_empty_ci_reds_guard(self):
        """`traces.ci` 空 / 指向不存在的 workflow ⇒ 健全性守卫必红。"""
        base = {"skip_reason": "[backend-contract] x",
                "traces": {"tests": ["backend/admin-api/pom.xml"]}}
        no_ci = _case("ZZ-009", **base)
        assert any("没有 `traces.ci`" in p for p in exempt_channel_problems([no_ci], REPO_ROOT))
        bad_ci = _case("ZZ-010", skip_reason="[backend-contract] x",
                       traces={"tests": ["backend/admin-api/pom.xml"],
                               "ci": ["no-such-workflow.yml"]})
        assert any("workflow `no-such-workflow.yml` 不存在" in p
                   for p in exempt_channel_problems([bad_ci], REPO_ROOT)), (
            "`traces.ci` 编了个不存在的 workflow 名字却没判红 ⇒ 它证明不了「有真实 CI job 跑它」"
        )

    def test_negative_control_real_exempt_cases_are_sound(self):
        """负控：真实存在的豁免用例**全部**通过健全性守卫（防守卫过严造成假红）。"""
        cases = _real_cases()
        exempt = [c for c in cases if machine_fail_channel(c, REPO_ROOT) == CHANNEL_TRACES]
        assert exempt, "豁免通道判定面失效"
        problems = exempt_channel_problems(exempt, REPO_ROOT)
        assert not problems, (
            f"真实用例被健全性守卫判红（{len(problems)} 项）⇒ 守卫过严：\n  "
            + "\n  ".join(problems[:10])
        )

    def test_looks_like_test_file_discriminates(self):
        """形状判定的判别力 + 负控（含 `DA-010` 真实形态：测试 + 迁移产物并列）。"""
        assert looks_like_test_file("backend/admin-api/src/test/java/com/migao/admin/service/DailyBriefingServiceTest.java")
        assert looks_like_test_file("tests/unit_ci_workflows/test_migration_idempotency.py")
        # 负控：非测试文件不得被判成测试（否则守卫过严/过松都失效）
        for ref in ("backend/admin-api/pom.xml",
                    "backend/admin-api/src/main/resources/db/migration/V44__create_daily_briefings.sql",
                    "docs/testing/mibao-verification-cases.md",
                    "tests/unit_ci_workflows/conftest.py"):
            assert not looks_like_test_file(ref), f"{ref} 被误判成测试文件 ⇒ 形状判定不判别"

    def test_negative_control_real_exempt_case_has_channel(self):
        """负控：真实存在的 `[backend-contract]` 用例（PG-002）必须拿到豁免通道。"""
        cases = {c.get("id"): c for c in _real_cases()}
        assert "PG-002" in cases, "用例库缺少 PG-002 —— 本判据的负控失去对象（请改用真实存在的 ID）"
        pg = cases["PG-002"]
        assert tax.scoring_assertion_count(pg) == 0, (
            "PG-002 的 `scoring_assertion_count` 已非 0 ⇒ 本文档里「53 条读数」的形态变了，"
            "请重新复核 #5079 的前提并更新锚点 `_note`"
        )
        assert machine_fail_channel(pg, REPO_ROOT) == CHANNEL_TRACES

    def test_negative_control_pg001_is_runner_scored_not_exempt(self):
        """负控 ②：PG-001 **不在** 53 里（它有 `success=true` 机器计分断言）——防「53=全处理单域」。

        `processing-order.yml` 的 19 条是**该域的子集**，不是全文件：`PG-001` 的
        `data_checks` 含 `success=true` ⇒ runner 计分通道。这条负控钉住这个区别，
        防止后人把「19」误读成「整个文件都要燃尽」。
        """
        cases = {c.get("id"): c for c in _real_cases()}
        assert "PG-001" in cases, "用例库缺少 PG-001"
        pg1 = cases["PG-001"]
        assert tax.scoring_assertion_count(pg1) > 0, (
            "PG-001 已变成「无 runner 计分断言」⇒ #5079 的 53 分布变了，请重新复核读数"
        )
        assert machine_fail_channel(pg1, REPO_ROOT) == CHANNEL_SCORING

    def test_i2_injection_zero_scoring_non_exempt(self):
        """I2 红证：`scoring==0` 且不走豁免通道 ⇒ 进 I2 违规集。"""
        c = _case("ZZ-006", data_checks=["散文一条"])
        assert scoring_zero_unexempt([c], REPO_ROOT) == ["ZZ-006"]
        assert scoring_zero_unexempt(
            [_case("ZZ-007", skip_reason="[backend-contract] x",
                   traces={"tests": ["backend/admin-api/pom.xml"]})], REPO_ROOT
        ) == [], "已豁免的用例不该被判进 I2 —— 否则 I2 会把 53 条全部假红"
    def test_i3_injection_raised_anchor_reds(self):
        """锚点红证 ①：把 `entries` 抬到 1（真债务不为 0）⇒ 链判红。"""
        hist = [{"no_channel_total": 1, "backend_contract_scoring_zero": 53}]
        drift = anchor_drift({"no_channel_total": 1, "backend_contract_scoring_zero": 53}, hist)
        assert any("绝对下界" in d for d in drift), (
            "把 `no_channel_total` 抬到 1 却没判红 ⇒ 「只许非增」是空断言"
        )

    def test_i3_injection_history_increase_reds(self):
        """锚点红证 ②：`history` 链出现上升 ⇒ 判红（只许非增）。"""
        hist = [
            {"no_channel_total": 0, "backend_contract_scoring_zero": 53},
            {"no_channel_total": 0, "backend_contract_scoring_zero": 54, "note": "新增 backend-contract 用例"},
        ]
        # 读数**允许**增长（有 note）；此处验证 note 规则生效、且无 note 时必红
        assert not anchor_drift({"no_channel_total": 0, "backend_contract_scoring_zero": 54}, hist)
        hist[1].pop("note")
        assert any("无 `note`" in d for d in anchor_drift(
            {"no_channel_total": 0, "backend_contract_scoring_zero": 54}, hist)), (
            "读数漂移且无 `note` 却没判红 ⇒ 漂移会在 diff 里无声"
        )

    def test_i3_injection_entries_out_of_sync_reds(self):
        """锚点红证 ③：`entries` 与 history 末行不一致 ⇒ 判红。"""
        hist = [{"no_channel_total": 0, "backend_contract_scoring_zero": 53}]
        drift = anchor_drift({"no_channel_total": 0, "backend_contract_scoring_zero": 52}, hist)
        assert any("≠ history 末行" in d for d in drift)

    def test_i3_injection_empty_history_reds(self):
        """锚点红证 ④：空 `history` ⇒ 判红（没有链就没有「只许非增」）。"""
        assert anchor_drift({"no_channel_total": 0, "backend_contract_scoring_zero": 53}, [])
