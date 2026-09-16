# case_ids: HR-003, HR-002, CU-003, PG-013
"""`pre_clean` 夹具层 **fail-closed**：注册表 + 未应用必须进结论（issue #3781）。

## 为什么单开这条守卫

"unknown pre_clean type = 静默跳过" 是**假绿温床**：`_run_pre_clean` 旧实现

```python
return f"未知 pre_clean 类型: {_type}（跳过）"
```

调用侧 `_pre_clean_for_case` 把返回值**当消息打印**（`🧹 pre_clean: …`）——于是
**数据压根没准备，用例照跑**，而它的红/绿会被读成"agent 能力缺陷"
（`migao-acceptance`「空跑：绿了但没跑」同族）。这在"**新增一个 type**"时最危险：
新类型没被 runner 认出来就静默退回成"什么都没做"。

同一族还有两处（本文件一并锁）：
- `employee_reactivate` 查不到目标员工 ⇒ 旧文案「查询 3 次未命中（跳过）」
  （**HR-003 的停用前置根本没复位**，却只有一行日志）；
- `customer_tag_remove` 的标签不在目录里 ⇒ 旧文案「不存在（跳过清理）」。

## 反向的洞（issue #3791，本文件新增）：**过度扩大**同样是缺陷

#3781 把上面那条判据套到了**所有** type 上，但两族的语义**相反**（见
`runner._PRECLEAN_CLEANUP_TYPES` 的注释）：清理型（remove/delete）的前置是**否定式**的
（"该对象**不在**脏状态"）⇒ **目标本就不存在 = 前置已满足**（良性 no-op）。
把它也折进结论的实测代价（判定跑 `34865780382`，SHA `4e5b33db`）：

```
completion.reason = "必须处理的失败 2 条: OR-013, PR-016；关键旅程失败 1 条: CU-003"
cases[CU-003] = {"score": 0.0, "classification": "pass",   # ← 行为侧首跑全绿，被夹具层折成 0
                 "precondition": "PRECONDITION_NOT_APPLIED: 夹具层前置未生效/未应用 …"}
```

`CU-003 ∈ KEY_JOURNEYS_MIBAO` ⇒ 一条良性 no-op **单独压掉整条 B 端腿的 `ok`**；而同一格在
#3781 之前是静默跳过、用例 `score=1.0` **通过**（⑤ 的条目）⇒ 这是**假红**，不是修好的洞。
⚠️ 最容易踩错的一格：`employee_remove`（#3788）也是清理型 —— 首跑还没造出重名员工时它必然
no-op，把它算成失败会**复活 HR-002/HR-003 的恒红**。

## 本文件锁五条

1. **注册表是单一事实源**：用例库里出现的每个 `pre_clean` type ∈ `runner._PRECLEAN_TYPES`
   （漏实现/拼错 ⇒ CI 直接红，而不是静默少做一件事）；
2. **配置错误可辨**：未知 type 返回带稳定前缀的**配置错误**，且
   `check_preclean_not_applied` 能把它捞出来（不再只是一行日志）；
3. **前置未应用 ⇒ 进结论**（**准备型**）：折成 case-level 失败原文 + `precondition` 标记
   （#3751 标记语义从"复位失败"扩到"前置压根没被应用"）；
4. **幂等消息不误判**：正常成功路径的消息（含「无需清理」「幂等」）**不得**被判成配置错误
   —— 否则每个用例都会带着假的"前置未应用"标记；
5. **两族分开**（#3791）：每个 type 必须**显式**归入一族；清理型的"目标不存在"走
   `_PRECLEAN_NOOP`（可见、**不进结论**），准备型的未应用**照旧进结论**。

## 红证

| 断言 | 红证 |
|---|---|
| ①② 今天它是静默跳过 / 改后被标记 | `test_unknown_type_is_a_config_error_not_a_silent_skip` **同时**断言"前缀可辨"与"能进结论"；把前缀改回旧文案（`未知 …（跳过）`）即红 |
| ③ 未应用 ⇒ 标记 | `test_not_applied_folds_into_the_case_verdict` 断言原文进 `failed` 且 `precondition` 被写上；删掉折叠逻辑即红 |
| ④ 幂等不误判 | `test_idempotent_success_messages_are_not_flagged` 用真实成功文案；把判据放宽成 `"跳过" in msg` 即红 |
| ① 注册表 | `test_every_declared_type_is_registered` —— 往任意用例加一个 `type: foo` 即红 |
| ⑤ 清理型 no-op 不判失败（#3791） | `test_real_cu003_shape_is_a_benign_noop_end_to_end` —— 走 CU-003 的**真实分支**（假 HTTP 罐装目录）；把该分支改回 `_PRECONDITION_NOT_APPLIED` 即红（见 PR 红证记录） |
| ⑤ 准备型未应用仍判失败（#3791） | `test_prepare_family_not_applied_still_fails_end_to_end` —— 员工查不到 ⇒ 标记保留 ⇒ KEY_JOURNEY 失败；把 `_classify_preclean_message` 的判据放宽成"所有 type 都降级"即红 |
| ⑤ employee_remove 留在清理型 | `test_employee_remove_absence_is_benign_not_a_failure` —— 把它移出 `_PRECLEAN_CLEANUP_TYPES` 即红 |
"""
import json
import re
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))
CASES_DIR = REPO_ROOT / ".github" / "cases"


def _load_runner():
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover - 本地 venv 有 httpx
        stub = types.ModuleType("httpx")

        class _AsyncClient:
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)
    import local_runner
    return local_runner


lr = _load_runner()


def _declared_types() -> dict:
    """用例库（单一源）里所有 `pre_clean.type` → 声明它的用例 ID。"""
    from render_cases import load_case_dicts
    out: dict = {}
    for c in load_case_dicts(str(CASES_DIR)):
        for spec in (c.get("pre_clean") or []):
            t = str((spec or {}).get("type") or "")
            if t:
                out.setdefault(t, []).append(c.get("id", "?"))
    return out


class TestRegistryIsTheSingleSource:
    def test_registry_is_nonempty_and_a_frozenset(self):
        assert isinstance(lr._PRECLEAN_TYPES, frozenset) and lr._PRECLEAN_TYPES

    def test_every_declared_type_is_registered(self):
        """**核心 L0 不变式**：用例声明的 type 必须已实现（拼错/漏实现 ⇒ CI 红）。"""
        declared = _declared_types()
        assert declared, "用例库里一个 pre_clean 都没有？本守卫的前提失效（解析失败？）"
        unknown = {t: ids for t, ids in declared.items() if t not in lr._PRECLEAN_TYPES}
        assert unknown == {}, (
            "这些 pre_clean 类型没有在 runner 注册表中（会走配置错误 / 静默不生效）："
            f"{unknown}\n合法类型: {sorted(lr._PRECLEAN_TYPES)}")

    def test_registry_entries_all_have_an_inline_branch(self):
        """注册表里的每个 type 都必须在 `_run_pre_clean` 里有实现（防「登记了没实现」）。

        `customer_tag_remove` 走的是**兜底分支**（`if _type != "customer_tag_remove": 报配置错误`
        —— 它排在最后，落到那里即它），故两种形态都算「有实现」。

        ⚠️ 源码切片的锚点是 `_run_pre_clean_action`（**实现体**）而不是 `_run_pre_clean`
        （issue #3791 之后后者只是"按族归类"的薄入口，切它会切到空壳 ⇒ 本守卫静默空跑，
        正是本仓库"绿了但没跑"的形态）。
        """
        src = Path(REPO_ROOT / "tests" / "agent_eval" / "local_runner.py").read_text(encoding="utf-8")
        start = src.index("async def _run_pre_clean_action(")
        body = src[start:src.index("\nasync def ", start + 10)]
        assert "_type ==" in body, (
            "源码切片切到了空壳（锚点漂移）——本守卫会静默空跑，必须改锚点")

        def _implemented(t: str) -> bool:
            return f'_type == "{t}"' in body or f'_type != "{t}"' in body

        missing = [t for t in sorted(lr._PRECLEAN_TYPES) if not _implemented(t)]
        assert missing == [], f"注册表里有但没实现分支的 type：{missing}"


class TestUnknownTypeIsNotASilentSkip:
    def test_unknown_type_is_a_config_error_not_a_silent_skip(self):
        """**红证**：未知 type 必须返回**可辨的配置错误**（旧实现是「（跳过）」）。"""
        import asyncio
        msg = asyncio.run(lr._run_pre_clean("tok", {"type": "employee_dedupe_typo"}))
        assert msg.startswith(lr._PRECLEAN_CONFIG_ERR), (
            f"未知 type 没有走配置错误前缀（旧行为是静默跳过）：{msg!r}")
        assert "未执行" in msg, f"配置错误消息没有说明「数据准备未执行」：{msg!r}"
        # 且必须能被折叠器捞出来（否则"可辨"只是文案，进不了结论）
        assert lr.check_preclean_not_applied([msg]) == [msg]

    def test_registered_but_unimplemented_type_is_also_a_config_error(self, monkeypatch):
        """登记了但漏写实现体 ⇒ 同样走配置错误（不许退回静默）。"""
        import asyncio
        monkeypatch.setattr(lr, "_PRECLEAN_TYPES", lr._PRECLEAN_TYPES | {"ghost_type"})
        msg = asyncio.run(lr._run_pre_clean("tok", {"type": "ghost_type"}))
        assert msg.startswith(lr._PRECLEAN_CONFIG_ERR), msg
        assert "未实现" in msg, msg

    def test_not_applied_marker_folds_into_the_case_verdict(self):
        """**红证**：`前置未应用` 必须折成 case-level 失败 + `precondition` 标记。"""
        msg = (f"{lr._PRECONDITION_NOT_APPLIED}: 员工「王五」查询 3 次未命中 —— 前置未复位")
        folded = lr.check_preclean_not_applied([msg])
        assert folded == [msg], f"未应用的 pre_clean 没有被折叠：{folded}"
        # 折叠后的原文必须与行为失败**分属不同签名**（否则两次尝试会被误判 unstable）
        atom = lr._failure_atom(msg, lr._CASE_LEVEL_DETAIL)
        assert atom == "precondition_not_applied(pre_clean)", (
            f"前置未应用的失败身份应固定为 precondition_not_applied(pre_clean)，实得 {atom!r}")
        # 配置错误同样有稳定身份（保留 type 名 → 不同 type 不同根因）
        cfg = lr._failure_atom(
            f"{lr._PRECLEAN_CONFIG_ERR}: 'bogus'（数据准备未执行）", lr._CASE_LEVEL_DETAIL)
        assert cfg == "config_error(pre_clean)", cfg

    def test_retry_boundary_treats_not_applied_as_not_restored(self):
        """#3751 标记语义扩展：**前置压根没被应用**也必须算"未复位"。"""
        src = Path(REPO_ROOT / "tests" / "agent_eval" / "local_runner.py").read_text(encoding="utf-8")
        assert "_PRECLEAN_BAD_MARKERS" in src, "重试边界没有复用前置坏消息标记"
        marker = lr._PRECLEAN_BAD_MARKERS
        assert isinstance(marker, tuple) and lr._PRECLEAN_CONFIG_ERR in marker
        assert lr._PRECONDITION_NOT_APPLIED in marker


class TestIdempotentSuccessIsNotFlagged:
    def test_idempotent_success_messages_are_not_flagged(self):
        """**红证**：正常成功/幂等文案不得被判成配置错误（判据必须是稳定前缀，不是"跳过"）。"""
        ok_msgs = [
            "无 「王五」（手机号 13812345678）员工需清理（幂等）",
            "员工「王五」（手机号 13700137000）状态 active，无需恢复",
            "「遮光窗帘」无重复（1 件），无需去重",
            "客户无「VIP2活跃」标签，无需清理",
            "已恢复「王五」为 active（防存量消耗）",
            "已清理 1 个测试员工 「王五」（手机号 13812345678）",
        ]
        assert lr.check_preclean_not_applied(ok_msgs) == [], (
            "正常成功文案被误判成前置未应用 —— 会让每个用例带上假的失败标记")
        # 反向：判据放宽成"含『跳过』"就会误伤（旧文案里带跳过字样）
        for m in ok_msgs:
            assert not m.startswith(lr._PRECLEAN_BAD_MARKERS), m

    def test_success_messages_avoid_the_reset_failure_wording(self):
        """措辞红线（#3751）：成功路径的消息不得含「未复位」/「失败」。

        它们会被重试边界读成"复位失败" ⇒ 结论被错误标成不可归因于 agent。
        """
        ok = [
            "无 「王五」（手机号 13812345678）员工需清理（幂等）",
            "已恢复 「王五」（手机号 13700137000）为 active（防存量消耗）",
        ]
        for m in ok:
            assert "未复位" not in m and "失败" not in m, m


class TestRealCasesUseTheNewTypeMinimally:
    def test_hr_pair_uses_name_plus_phone(self):
        """HR-002 的清理与 HR-003 的复位都必须带**唯一标识**（手机号）—— 只按姓名裸匹配
        就是今天这个坑本身（命中同名残留 ⇒ 目标不确定）。"""
        import yaml
        hr = yaml.safe_load((CASES_DIR / "hr.yml").read_text(encoding="utf-8"))
        by_id = {c["id"]: c for c in hr["cases"]}
        h2 = by_id["HR-002"]["pre_clean"]
        assert [s["type"] for s in h2] == ["employee_remove"], h2
        assert h2[0].get("employee_phone") == "13812345678", h2
        h3 = by_id["HR-003"]["pre_clean"]
        assert h3[0].get("employee_phone") == "13700137000", (
            f"HR-003 的复位没有用手机号精确定位（会命中 HR-002 造的同名「王五」）：{h3}")
        assert re.fullmatch(r"\d{11}", str(h3[0]["employee_phone"]))


class TestCreateCasesDeclareTheirOwnCleanup:
    """写类「创建全局可命名对象」用例必须能**自清理**（issue #3800）。

    为什么单锁一条（PR-016）：`namespaces` 只给**并行互斥**，**不解决重试前置等价性** ——
    #3751 的重试复位按 `pre_clean` **opt-in**（`_reset_for_retry` 对未声明者返回 None）
    ⇒ 没有 `pre_clean` 的建品用例，首跑造出的商品会留到重试 ⇒ agent **正确地**拒绝建重复
    ⇒ 两次前置不同 ⇒ 指纹漂移 ⇒ 误判 `unstable`（本 run 的 PR-016 实红）。

    ⚠️ **2026-09-15 口径升级（issue #3835，本类的守卫随之改写）**：`product_dedupe{共享名}`
    只治"重试前置等价性"，**治不了"运行期副本对外可见"** —— 库级实证（run 34908262839）
    PR-016 造的「遮光窗帘」副本在它自己结束后仍存活 3 分钟（23:37:45→23:40:46），期间
    PP-001/PR-017/OR-014 首跑全部看到 `product_search(products=2)` 而判红。故本类的新口径是
    **"写方不得写共享名"**：自建对象必须用例自有（`product_remove{自有名}` 把前置复位成"不存在"）。
    改写保留了原守卫的**两条判别力**（"必须有自清理"+"不得对共享名用破坏性 remove"），
    并把它们从"单锁 PR-016"一般化到"全部建品用例"，见
    `tests/unit_ci_workflows/test_eval_product_name_pollution.py`。
    """

    def _by_id(self, fname: str) -> dict:
        import yaml
        doc = yaml.safe_load((CASES_DIR / fname).read_text(encoding="utf-8"))
        return {c["id"]: c for c in doc["cases"]}

    def test_pr016_cleans_its_own_case_owned_product(self):
        """PR-016 的商品名下**必须用例自有**（不再是种子里就有的「遮光窗帘」）⇒
        清理目标 = 自己的名字、类型 = `product_remove`（把前置复位成"**不存在**"，
        而 `product_dedupe` 只会留下 1 件、运行期全程对外可见 —— #3835）。"""
        c = self._by_id("product.yml")["PR-016"]
        inputs = str(c.get("user_inputs") or "")
        assert "遮光窗帘" not in inputs, (
            "PR-016 又在写种子名「遮光窗帘」了（`prod_eval_blackout` 就叫这个）——"
            "运行期会造出第二件同名商品，令按名读它的 PP-001/PR-017/OR-014 首跑岔路（#3835）")
        own = "E2E建品流程样品帘"
        assert own in inputs, f"PR-016 的商品名不是预期自有名 {own!r}（改名了？同步本守卫）：{inputs!r}"
        pc = c.get("pre_clean") or []
        assert [s.get("type") for s in pc] == ["product_remove"], (
            f"PR-016 缺自清理（或类型退回 dedupe）⇒ 重试前置与首跑不等价（#3800）：{pc}")
        assert pc[0].get("product_keyword") == own, (
            f"PR-016 的清理目标必须**正好是它自己造的那个名字**（否则又是「清别人/清不到自己」）：{pc}")
        assert f"product_name:{own}" in (c.get("namespaces") or []), c.get("namespaces")

    def test_pr016_does_not_use_the_destructive_remove_on_a_shared_name(self):
        """**红证锚点**：`product_remove` 会删**全部**子串命中项 —— 对「遮光窗帘」这种
        5 条用例共享的种子前置是破坏性的，必须被本守卫挡住（旧形态）。"""
        pc = self._by_id("product.yml")["PR-016"].get("pre_clean") or []
        for s in pc:
            if s.get("type") == "product_remove":
                kw = str(s.get("product_keyword") or "")
                assert kw != "遮光窗帘", (
                    "PR-016 用 product_remove 点掉了共享种子名「遮光窗帘」——"
                    "子串删全部会连种子一起删（PR-005/PR-007/CR-001/CR-003/OR-015 的共享前置）")


# ── httpx 替身：零网络、零 LLM 地走**真实分支**（issue #3791 的红证手段）──────────
# 为什么需要它：本文件的其余用例只能断言**纯函数**（消息 → 是否折叠）。而 #3791 的病灶
# 长在**分支里**（`customer_tag_remove` 的"标签不在目录"那一格）—— 只测纯函数会漏掉它，
# 且无法证明"这次确实走到了那一格"（`migao-acceptance` v1.7：重放要给出**前置条件的观测值**，
# 否则"绿了但路径没被行使"）。故用罐装响应把真实分支跑通，并断言**真的查了目录**。
class _FakeResp:
    def __init__(self, payload: bytes = b"{}", status_code: int = 200):
        # `_safe_json` 读 `.content`（不是 `.json()`），照它的口径造
        self.content = payload
        self.status_code = status_code


class _FakeAsyncClient:
    def __init__(self, routes: dict, calls: list):
        self._routes, self._calls = routes, calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def _resp(self, url: str) -> _FakeResp:
        self._calls.append(url)
        for key, payload in self._routes.items():
            if key in url:
                return _FakeResp(json.dumps(payload).encode("utf-8"))
        return _FakeResp(b"{}", 404)

    async def get(self, url, **kw):
        return self._resp(url)

    async def delete(self, url, **kw):
        return self._resp(url)

    async def put(self, url, **kw):
        return self._resp(url)


class _FakeHttpx:
    """`httpx` 模块替身：只提供 runner 用到的 `AsyncClient`（零网络）。"""

    def __init__(self, routes: dict):
        self._routes, self.calls = routes, []

    def AsyncClient(self, *a, **k):          # noqa: N802 —— 与 httpx 同名
        return _FakeAsyncClient(self._routes, self.calls)


def _cat(name: str, payload) -> _FakeHttpx:
    return _FakeHttpx({name: payload})


class TestCleanupFamilyNoopIsNotAFailure:
    """issue #3791：清理型的"目标不存在"是**良性 no-op**，不得进结论。

    判定跑 `34865780382` 的 CU-003 就是被这一格折成 `score=0` ⇒ 它 ∈ `KEY_JOURNEYS_MIBAO`
    ⇒ 整条 B 端腿 `completion.ok=false`（而它行为侧 `classification=pass`）。

    ⚠️ `CU003_SPEC` 是**修复前的历史形态**（issue #3832 已把用例的 `tag_name` 改成种子目录
    真有的 `VIP2`）—— 本类锁的是**清理型分族机制**（"目录里没有该标签"这一格），
    不是"CU-003 当前长什么样"；用例当前形态的真值由
    `test_eval_case_asset_truth.py` 守卫。留在这里是因为它是该机制唯一的**真实来源**形态。
    """

    CU003_SPEC = {"type": "customer_tag_remove", "customer_keyword": "张三",
                  "customer_index": 0, "tag_name": "VIP2活跃"}

    def test_every_type_is_classified_into_exactly_one_family(self):
        """**根因不变式**：每个注册 type 必须**显式**归族 —— 不允许默认落到任何一边。"""
        assert isinstance(lr._PRECLEAN_CLEANUP_TYPES, frozenset)
        assert lr._PRECLEAN_CLEANUP_TYPES <= lr._PRECLEAN_TYPES, (
            "清理型登记表里有不在总注册表里的 type（`_run_pre_clean` 会走配置错误）："
            f"{sorted(lr._PRECLEAN_CLEANUP_TYPES - lr._PRECLEAN_TYPES)}")
        prepare = lr._PRECLEAN_TYPES - lr._PRECLEAN_CLEANUP_TYPES
        assert prepare, "准备型为空？两族语义就无从区分了（注册表被改坏了）"
        # 准备型的代表必须留在准备型（降级它 = 掏空 #3781）
        assert "employee_reactivate" in prepare and "aftersales_ticket_prepare" in prepare

    def test_employee_remove_absence_is_benign_not_a_failure(self):
        """⚠️ **本任务最容易踩错的一格**：`employee_remove`（#3788）是清理型 ——
        HR-002 首跑还没造出重名「王五」时，它必然 no-op；把它算成"前置未应用"
        会**复活 HR-002/HR-003 的恒红**。"""
        spec = {"type": "employee_remove", "employee_name": "王五",
                "employee_phone": "13812345678"}
        assert "employee_remove" in lr._PRECLEAN_CLEANUP_TYPES, (
            "employee_remove 被移出清理型了 —— 它的 no-op 会开始判失败（HR-002/HR-003 复活）")
        # ① 现状文案（幂等）本就不进结论
        assert lr.check_preclean_not_applied(
            ["无 「王五」（手机号 13812345678） 员工需清理（幂等）"]) == []
        # ② 即便将来某次实现把它标成"前置未应用"，也必须被降级（单点保证）
        demoted = lr._classify_preclean_message(
            spec, f"{lr._PRECONDITION_NOT_APPLIED}: 员工「王五」查询 3 次未命中")
        assert demoted.startswith(lr._PRECLEAN_NOOP), demoted
        assert lr.check_preclean_not_applied([demoted]) == []

    def test_real_cu003_shape_is_a_benign_noop_end_to_end(self, monkeypatch):
        """**红证①**：CU-003 的**修复前历史形态**（标签目录里没有 `VIP2活跃`）走**真实分支**
        ⇒ 良性 no-op：不进结论、不折 score、CU-003 不再压整腿 `ok`。

        罐装数据取自判定跑的 trace（`customer_manage(tags=2 count=2)` + 种子的
        `VIP2`/`活跃`）—— 断言里同时证明**目录真被查了**（否则本用例会空跑通过）。
        """
        import asyncio
        fake = _FakeHttpx({
            "/api/admin/customers": {"data": {"items": [
                {"id": "cust_eval_zhangsan", "name": "张三", "tags": []}]}},
            "/api/admin/customer-tags": {"data": [
                {"id": "tag_eval_vip2", "name": "VIP2"},
                {"id": "tag_eval_active", "name": "活跃"}]},
        })
        monkeypatch.setattr(lr, "httpx", fake)
        msg = asyncio.run(lr._run_pre_clean("tok", self.CU003_SPEC))

        # 前置条件的观测值：目录**真的被查过**（不是空跑）
        assert any("customer-tags" in u for u in fake.calls), fake.calls
        assert msg.startswith(lr._PRECLEAN_NOOP), (
            f"清理型的目标不存在没有走良性 no-op（#3791 的假红形态）：{msg!r}")
        # 不进结论 ⇒ 失败身份也不是"前置未应用"
        assert lr.check_preclean_not_applied([msg]) == [], "良性清理被折进了结论"
        assert lr._failure_atom(msg, lr._CASE_LEVEL_DETAIL) != "precondition_not_applied(pre_clean)"
        # 结论层：CU-003 是**关键旅程** ⇒ 它不进结论 = 不再压整腿 ok
        v = lr.completion_verdict(
            [{"case_id": "CU-003", "score": 1.0, "classification": "pass"}],
            lr.KEY_JOURNEYS_MIBAO)
        assert v["ok"] is True and v["journey_failures"] == [], v

    def test_cleanup_noop_wording_avoids_the_reset_failure_wording(self):
        """措辞红线（#3751）：良性 no-op 文案不得含「未复位」/「失败」——
        否则重试边界会把它读成"前置未复位"（`PRECONDITION_NOT_RESTORED`）。"""
        msg = lr._cleanup_noop_message(self.CU003_SPEC, "标签「VIP2活跃」不在标签目录里")
        assert "未复位" not in msg and "失败" not in msg, msg
        assert not msg.startswith(lr._PRECLEAN_BAD_MARKERS), msg

    def test_prepare_family_not_applied_still_fails_end_to_end(self, monkeypatch):
        """**红证②**：准备型（`employee_reactivate`）查不到目标 ⇒ 标记**保留** ⇒ 折叠 ⇒
        HR-003 这条 KEY_JOURNEY 判失败。证明本修复**没有**把准备型一起放掉（#3781 不退化）。"""
        import asyncio
        spec = {"type": "employee_reactivate", "employee_name": "王五",
                "employee_phone": "13700137000"}
        fake = _cat("/api/admin/users", {"data": {"items": []}})
        monkeypatch.setattr(lr, "httpx", fake)
        msg = asyncio.run(lr._run_pre_clean("tok", spec))

        assert any("/api/admin/users" in u for u in fake.calls), fake.calls
        assert msg.startswith(lr._PRECONDITION_NOT_APPLIED), msg
        assert lr.check_preclean_not_applied([msg]) == [msg], (
            "准备型未应用没有被折叠 —— #3781 的成果退化了")
        v = lr.completion_verdict(
            [{"case_id": "HR-003", "score": 0.0, "classification": "pass"}],
            lr.KEY_JOURNEYS_MIBAO)
        assert v["ok"] is False and v["journey_failures"] == ["HR-003"], v


# ── ⑦ 新增类型的**分族**必须显式选择（issue #3833，`#3800` 同族的新实例）────────────
class TestProcessingOrderResetIsPrepareFamily:
    """加工单用例的自清理（`PG-013`）必须是**准备型**，不能落进清理型。

    为什么单锁一格：两族的"目标不存在"处置**相反**（#3791）——
      · 清理型：目标不存在 = 前置**已满足** ⇒ 良性 no-op，**不进结论**；
      · 准备型：目标不在位 = 用例带着**假前置**跑完 ⇒ `_PRECONDITION_NOT_APPLIED` ⇒ 进结论。
    `processing_order_reset` 要的是**肯定式**前置（"点名的订单在、且是 confirmed 且无在途加工单"）
    ⇒ 与 `aftersales_ticket_prepare` 同族。**误归清理型**会把"栈缺 seed"静默放行
    （`#3781` 要堵的正是这个）；**误归准备型**对 `employee_remove` 才是灾难（HR-002/003 恒红，
    见上一条守卫）。本类型的判据是"点名对象在不在"，与 `employee_remove`（谁造的谁清）不同。
    """

    def test_registered(self):
        assert "processing_order_reset" in lr._PRECLEAN_TYPES, (
            "PG-013 声明的 pre_clean 类型没登记 ⇒ 会走配置错误（数据准备未执行）")

    def test_is_prepare_family_not_cleanup(self):
        assert "processing_order_reset" not in lr._PRECLEAN_CLEANUP_TYPES, (
            "被归进清理型了 —— 栈缺 seed（点名的订单不在）会被静默放行，#3781 的成果退化")

    def test_missing_target_folds_into_the_conclusion(self, monkeypatch):
        """**红证**：走**真实分支**（DB 里没有点名订单）⇒ 必须产出可折叠的「未应用」标记。"""
        import asyncio
        import types as _types

        class _Conn:
            async def fetch(self, sql, *a):
                return []

            async def fetchrow(self, sql, *a):
                return None                     # 点名的订单不在库里

            async def close(self):
                return None

        class _Mod:
            async def connect(self, *a, **k):
                return _Conn()

        fake = _types.ModuleType("asyncpg")
        fake.connect = _Mod().connect
        monkeypatch.setitem(sys.modules, "asyncpg", fake)
        msg = asyncio.run(lr._run_pre_clean("tok", {"type": "processing_order_reset",
                                                    "order_no": "EVAL-MB-ORD-0002"}))
        assert msg.startswith(lr._PRECONDITION_NOT_APPLIED), msg
        assert "未复位" in msg, msg          # 重试边界据此判"前置不等价"
        assert lr.check_preclean_not_applied([msg]) == [msg], (
            f"准备型未应用没有被折叠 —— 又会变成「绿了但没跑」：{msg!r}")
