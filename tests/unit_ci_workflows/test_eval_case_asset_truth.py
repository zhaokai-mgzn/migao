# case_ids: CU-003, PG-013
"""用例资产**真值**必须与种子 / runner 对得上（issue #3832 + #3833，判定跑 34908262839）。

## 为什么单开一条守卫

一次判定跑的两条硬红（CU-003 / PG-013）**都不是产品缺陷**，而是用例资产与种子/runner
对不上 —— 这类缺陷的共同形态是**静默**：

| 用例 | 病灶 | 为什么静默 |
|---|---|---|
| `CU-003` | `pre_clean.tag_name: "VIP2活跃"` 不在种子标签目录（只有 `VIP2` / `活跃`） | `customer_tag_remove` 找不到就整条 **no-op**；#3791 之后连结论都不进 ⇒ 报告里只是一行良性提示（#3794） |
| `CU-003` | 只给姓名「张三」，而同栈 `OR-010` 建单会自动 upsert 出**第二个张三** | 「张三」落点由并行用例决定；`customer_index: 0` 还会命中**最新**那条（= 污染源造的那条） |
| `CU-003` | 收尾轮是裸文本「确认」 | agent 收尾轮才发 confirm 卡时**没有下一轮答卡** ⇒ 写操作永不放行（#3518/#3568 口径） |
| `PG-013` | 没声明 `pre_clean` | `_reset_for_retry` 按 `pre_clean` **opt-in** ⇒ 首跑造出的「订单已 producing + 加工单已存在」留到重试 ⇒ agent 合理地不再调生成工具（#3800 同族新实例） |
| `PG-013` | `forbidden_text` 是**全程**语义 | R1 问答轮如实陈述某单不含加工项被判成"拒绝执行" ⇒ 唯一红点（#3833） |

⇒ 本文件把这几格做成**确定性静态不变式**（零 LLM、秒级），并给每条守卫配**红证**
（把被测行为改坏/喂改前形态，它必须**会红** —— `migao-acceptance`「空断言」治法）。

⚠️ 红证一律用**注入式**（在测试内构造改前形态喂给同一个判据），**不用**"仓库当下恰有该缺陷"
式真值主张 —— 后者修好即红、且报错指向错误方向（`migao-acceptance`「断言形态」表）。
"""
import asyncio
import re
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = REPO_ROOT / ".github" / "cases"
SEED_PATH = REPO_ROOT / "tests" / "agent_eval" / "fixtures" / "mibao_eval_seed.sql"
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))
sys.path.insert(0, str(REPO_ROOT / ".github"))

import assertion_taxonomy as tax  # noqa: E402  （写路径判据的单一源，见 CU-003 的答卡轮守卫）


def _load_runner():
    """导入 `local_runner`（L0 job 只装 pytest+pyyaml → 缺 httpx 时注入最小替身）。"""
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
SEED = SEED_PATH.read_text(encoding="utf-8")


# ── 种子解析（只解析，**不重建**命名规则；产物定位一律来自被读系统本身）──────────────
def _region(start_marker: str, end_marker: str) -> str:
    i = SEED.index(start_marker)
    j = SEED.index(end_marker, i)
    return SEED[i:j]


def seed_tag_names() -> set:
    """种子 `customer_tags` 目录里的标签**名字**集合。"""
    block = _region("INSERT INTO customer_tags", "ON CONFLICT")
    return {m.group(2) for m in re.finditer(r"\(\s*'([^']+)'\s*,\s*\d+\s*,\s*'([^']+)'", block)}


def _split_top_level(s: str) -> list:
    """按**顶层**逗号切分（跳过括号/引号内的逗号）—— SQL 值列表用。"""
    out, buf, depth, quote = [], [], 0, ""
    for ch in s:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "'\"":
            quote = ch
            buf.append(ch)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    out.append("".join(buf))
    return [x.strip() for x in out]


def seed_order_row(order_no: str) -> list:
    """种子里该订单的 `VALUES` 元组，按顶层逗号切分后的字段列表。"""
    block = _region("INSERT INTO orders", "ON CONFLICT")
    block = "\n".join(ln for ln in block.splitlines() if not ln.strip().startswith("--"))
    m = re.search(r"\(([^()]*?'" + re.escape(order_no) + r"'[^()]*?)\)", block, re.S)
    assert m, f"种子里找不到订单 {order_no} 的 VALUES 元组（seed 改了？本守卫前提失效）"
    return _split_top_level(m.group(1))


def _case(cid: str):
    import eval_cases
    return next(c for c in eval_cases.ALL_CASES if c.id == cid)


def _case_yaml(fname: str, cid: str) -> dict:
    import yaml
    doc = yaml.safe_load((CASES_DIR / fname).read_text(encoding="utf-8"))
    return next(c for c in doc["cases"] if c["id"] == cid)


def _tool_action_enum(rel_path: str) -> set:
    """工具源码里 `VALID_ACTIONS = {...}` 的 action 枚举 —— **源码即真值**，不另列一份清单。

    与 `tests/unit_ci_workflows/test_mibao_b_end_readonly.py`（AST 解析）/
    `tests/unit_ci_workflows/test_assertion_specs_wellformed.py`（正则）同款口径：
    用例里声明的 action 必须是工具**当前**枚举里的成员 —— 写 action 被删（#5247）后，
    任何仍指向它的声明都必须变红，而不是"看起来还在测一个已下线的能力"。
    """
    src = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    m = re.search(r"VALID_ACTIONS\s*=\s*[\{\[](.*?)[\}\]]", src, re.S)
    assert m, f"{rel_path} 里找不到 `VALID_ACTIONS = {{...}}`（判据失去目标）"
    actions = set(re.findall(r'"([^"]+)"', m.group(1)))
    assert actions, f"{rel_path} 的 VALID_ACTIONS 解析为空（口径漂移？）：{m.group(1)!r}"
    return actions


CUSTOMER_MANAGE_SRC = "backend/ai-agent-service/app/tools/customer_manage.py"


def _read_only_relapse_violations(case: dict, source_actions: set) -> list:
    """CU-003 **只读形态**的判据本体（纯函数 —— 判据不写在断言里，才能被注入式红证行使）。

    · `expectations` 必须恰好是 `customer_manage(action=list_tags)`（工具级断言，不许降级成文本）；
    · 该 action 必须在**工具源码**的枚举里（死引用即违规）；
    · 写路径声明（`must_succeed` / `must_fail` / `forbidden_args`）一律不得残留（含空壳形态）。
    """
    out = []
    expected = [{"tool": "customer_manage", "args": {"action": "list_tags"}}]
    if case.get("expectations") != expected:
        out.append(f"expectations 不是只读 `list_tags` 工具断言：{case.get('expectations')!r}")
    if expected[0]["args"]["action"] not in source_actions:
        out.append(f"声明的 action `list_tags` 不在工具源码的 action 枚举里：{sorted(source_actions)}")
    for field in ("must_succeed", "must_fail", "forbidden_args"):
        if case.get(field):
            out.append(f"写路径声明残留：`{field}`={case.get(field)!r}")
    return out


class _CaseStub:
    """最小用例替身（`unbacked_customer_tag_removals` 只吃 `id` + `pre_clean`）。"""

    def __init__(self, cid, pre_clean):
        self.id, self.pre_clean = cid, pre_clean


# ── ① 种子标签目录 ↔ `customer_tag_remove.tag_name` 一致性（#3794 / #3832）──────────
class TestCustomerTagRemoveNamesMatchTheSeed:
    def test_seed_catalog_parses(self):
        """守卫的**前提**：种子标签目录能解析出来（解析失败 ⇒ 下面的守卫会空跑通过）。"""
        tags = seed_tag_names()
        assert tags, "没从 mibao_eval_seed.sql 解析出任何标签名（本守卫会静默空跑）"
        assert {"VIP2", "活跃"} <= tags, tags

    def test_no_case_declares_a_tag_that_the_seed_does_not_have(self):
        """**核心不变式**：声明 `customer_tag_remove` 的用例，其 `tag_name` 必须真实存在。

        改前形态（`tag_name: "VIP2活跃"`）必红 —— 见下一条注入式红证。
        """
        bad = lr.unbacked_customer_tag_removals(list(__import__("eval_cases").ALL_CASES),
                                                seed_tag_names())
        assert bad == [], (
            "这些 `customer_tag_remove` 的 tag_name 不在种子目录里 ⇒ 清理**结构性空转**"
            f"（issue #3794 的形态，只在 pre_clean 字段里可见）：{bad}")

    def test_guard_has_teeth_on_the_pre_fix_shape(self):
        """**红证（注入式）**：把改前形态（`CU-003` 的 `VIP2活跃`）喂给同一判据 ⇒ 必报出。

        证明上一条不是"永远绿的空断言"（`migao-acceptance`：每条断言都要有红证）。
        """
        pre_fix = _CaseStub("CU-003", [{"type": "customer_tag_remove",
                                        "customer_keyword": "张三", "customer_index": 0,
                                        "tag_name": "VIP2活跃"}])
        got = lr.unbacked_customer_tag_removals([pre_fix], seed_tag_names())
        assert len(got) == 1 and "VIP2活跃" in got[0], got
        # 同一判据对**修好之后**的形态不报（否则就是"恒红"，同样没有判别力）
        assert lr.unbacked_customer_tag_removals(
            [_CaseStub("CU-003", [{"type": "customer_tag_remove",
                                   "customer_keyword": "13800138000", "tag_name": "VIP2"}])],
            seed_tag_names()) == []

    def test_only_the_tag_removal_type_is_checked(self):
        """别的 `pre_clean` 类型（如 `product_remove`）不在这条不变式的管辖内。"""
        assert lr.unbacked_customer_tag_removals(
            [_CaseStub("PR-016", [{"type": "product_dedupe",
                                   "product_keyword": "遮光窗帘"}])], seed_tag_names()) == []


# ── ② CU-003 的资产真值（#3832）───────────────────────────────────────────────
class TestCU003AssetIsSatisfiableAndNotRelaxed:
    def test_premise_is_the_seed_tag_catalog(self):
        """前提成立：`pre_clean.tag_name` 是种子目录里真有的，且输入是**只读问法**。

        原断言（留档）：`assert "VIP2" in str(c["user_inputs"][0])` —— 前提是「首轮输入必须
        点名**待写入**的那个标签（`VIP2`）」，即 CU-003 是一条**打标签**用例。
        #5247（B 端只读化）把 CU-003 改判成**只读查标签**（`customer_manage(list_tags)`），
        写动词「加/打标签」已从工具源码删除 ⇒ 该前提被证伪：输入里再出现 `VIP2` 反而意味着
        用例又回到了已下线的写形态。

        换成对新事实**等效更强**的两条（不是放宽）：
        ① 输入必须带**不可变键**（客户手机号）—— 保住原前提的实质「指代唯一」
           （与 `test_target_customer_is_identified_by_the_seed_phone` 同源）；
        ② 输入**不得含写动词**（加标签 / 打标签）—— 把"只读"钉在**输入面**上，
           而不是只靠 `expectations` 里的一句声明（问法与声明不一致时这里先红）。
        """
        c = _case_yaml("customer.yml", "CU-003")
        tags = seed_tag_names()
        assert c["pre_clean"][0]["tag_name"] in tags, c["pre_clean"]
        first = str(c["user_inputs"][0])
        seed_phone = seed_order_row("EVAL-MB-ORD-0002")[5].strip().strip("'")
        assert seed_phone in first, f"只读问法仍须用不可变键（手机号）定位客户：{first!r}"
        for verb in ("加标签", "打个标签", "打标签"):
            assert verb not in first, (
                f"只读问法的输入里出现写动词「{verb}」⇒ 与 #5247 已下线的写能力不一致：{first!r}")

    def test_target_customer_is_identified_by_the_seed_phone(self):
        """**唯一指代**（#3568 对 CU-004 的同一改法）：姓名会撞 OR-010 建单 upsert 出的同名张三，
        手机号不会（`CustomerService` 按 `phone` 唯一匹配）。

        改前形态（`customer_keyword: "张三"` + `customer_index: 0`）必红 —— 见下条红证。
        """
        c = _case_yaml("customer.yml", "CU-003")
        seed_phone = seed_order_row("EVAL-MB-ORD-0002")[5].strip().strip("'")
        assert c["pre_clean"][0]["customer_keyword"] == seed_phone, c["pre_clean"]
        assert seed_phone in str(c["user_inputs"][0]), c["user_inputs"]

    def test_index_zero_is_only_safe_because_the_keyword_is_unique(self):
        """**红证（注入式）**：仅按姓名定位会命中"最新建的"同名客户 ⇒ 清理打在**错的人**身上。

        模型 = admin-api `CustomerService.getCustomerPage` 的 `order by created_at DESC`
        （种子的张三先建、OR-010 建单 upsert 的张三后建）⇒ `customer_index: 0` 取到后者。
        """
        seed_customer = {"id": "cust_eval_zhangsan", "created_at": "2026-09-14T00:00:00Z"}
        polluted = {"id": "34a72014e6edabd95b740a0822a0c05c", "created_at": "2026-09-15T07:40:11Z"}
        page = sorted([seed_customer, polluted], key=lambda x: x["created_at"], reverse=True)

        def target_of(keyword: str, index: int) -> dict:
            # 关键字=姓名 ⇒ 两条都命中；关键字=手机号 ⇒ 只剩种子的那条
            hits = ([seed_customer, polluted] if keyword == "张三"
                    else [c for c in (seed_customer, polluted)
                          if c["id"] == "cust_eval_zhangsan"])
            hits = sorted(hits, key=lambda x: x["created_at"], reverse=True)
            return hits[index]

        assert target_of("张三", 0) is polluted, "改前形态没复现「打错人」（红证无判别力）"
        assert target_of("13800138000", 0) is seed_customer
        assert page[0] is polluted                      # 观测值：列表首条就是污染源造的那条

    def test_single_read_only_round_needs_no_answer_card_turn(self):
        """只读单轮**不需要答卡轮** —— 但「写路径必须有答卡轮」这条守卫不许消失。

        原断言（留档）：`assert isinstance(last, dict) and last.get("auto_respond")` ——
        「收尾轮必须是答 confirm 卡的轮」（#3518/#3568 口径：agent 末轮才发 confirm 卡时
        写操作永不放行）。#5247 把 CU-003 改成**只读单轮查标签**：没有任何写操作要放行
        ⇒「答卡轮」这个要求**没有对象**（继续要求它反而会把只读用例钉回写形态）。

        改成两条（不是放宽）：
        ① 现状面：单轮只读问法 —— 末轮是纯文本问句，且整条用例不留写确认答卡轮；
        ② **fail-closed 条件守卫**：一旦用例重新声明写路径（#5247 删掉的那几个 action /
           `assertion_taxonomy.is_write_case` 认的写期望），末轮必须重新是答卡轮 ——
           否则「写操作永不放行」这条原缺陷会随退役静默复活。
        """
        c = _case_yaml("customer.yml", "CU-003")
        last = c["user_inputs"][-1]
        declares_write = tax.is_write_case(c) or any(
            marker in str(c.get("expectations")) or marker in str(c.get("must_succeed"))
            for marker in ("add_tag", "remove_tag"))
        if declares_write:
            assert isinstance(last, dict) and last.get("auto_respond"), (
                f"重新声明了写路径却没有答卡轮 —— 写操作永不放行（#3518/#3568）：{last!r}")
        else:
            assert isinstance(last, str) and last.strip(), (
                f"只读单轮的末轮必须是纯文本问句（已无写操作要答卡）：{last!r}")
            assert not any(isinstance(t, dict) and t.get("auto_respond")
                           for t in c["user_inputs"]), (
                f"只读用例里残留了写确认答卡（`auto_respond`）轮：{c['user_inputs']}")

    def test_no_auto_select_round_is_left_behind(self):
        """删掉 `auto_select` 轮：无卡时它会发字面量「第一个」（`resolve_auto_select_turn` 的
        ③ 档，CU-004 的注释已实证），唯一指代之后该轮没有意义。"""
        c = _case_yaml("customer.yml", "CU-003")
        assert not any(isinstance(t, dict) and t.get("auto_select")
                       for t in c["user_inputs"]), c["user_inputs"]

    def test_assertion_strength_is_unchanged(self):
        """**反向守卫（不许降级）**：断言面必须停在**只读工具调用**上，写路径声明不得残留。

        原断言（留档）：`expectations == [customer_manage(add_tag)]`，并逐字禁止
        `direct_reply` / `must_fail` / `forbidden_args` 出现在用例里（`blob` 级串扫）——
        前提是 CU-003 为**打标签（写）**用例。#5247 证伪该前提：`add_tag` 已从
        `customer_manage` 源码的 action 枚举删除（`VALID_ACTIONS` 只剩 list/detail/list_tags）
        ⇒ 原断言**不可能再满足**（被测对象已不存在），必须改判成新的只读形态。

        改判后的判据（等效或更强，不是放宽）：
        ① `expectations` **恰好**是 `customer_manage(action=list_tags)` —— 仍是**工具级**断言
           （"调用了 ≠ 成了"的计分口径不变），只是动作换成仅存的只读查标签；
        ② `list_tags` 必须真的在**工具源码**的 action 枚举里 —— 用例声明的动作不许是死引用
           （源码删了它这里就红；这正是从 `add_tag` 学到的一课）；
        ③ 写路径的三类声明（`must_succeed` / `must_fail` / `forbidden_args`）**一律不得残留**
           —— 空列表/空 dict 同样不行（`must_succeed: []` 是"断言空壳"，比不声明更坏）；
        ④ `data_checks` 里必须仍有**正向约束**「不得声称已加标签」—— 原断言是"落库断言仍在"
           （`add_tag` 真落库）；写路径下线后，等效守卫 = "不得**谎报**已加标签"，
           它与"标签逐条来自服务端"合起来仍是可判的只读正确性约束；
        ⑤ 它仍是**活跃正常档**用例（`skip_reason` 为空）—— 退役会让以上守卫全都不进运行期。
        """
        c = _case_yaml("customer.yml", "CU-003")
        violations = _read_only_relapse_violations(c, _tool_action_enum(CUSTOMER_MANAGE_SRC))
        assert violations == [], (
            f"CU-003 的只读形态判据报出违规（期望恰好 `list_tags`、无写路径声明）：{violations}")
        checks = " ".join(str(d) for d in c["data_checks"])
        assert "不得声称已加标签" in checks, (
            f"CU-003 丢了「不得谎报已加标签」这条正向约束：{c['data_checks']}")
        assert not str(c.get("skip_reason") or "").strip(), (
            f"CU-003 已退役 ⇒ 上面这些守卫不进运行期（退役 ≠ 守卫生效）：{c.get('skip_reason')!r}")

    def test_the_read_only_form_judge_goes_red_on_a_write_relapse(self):
        """**红证（注入式）**：把改前形态（`add_tag` 期望 + `must_succeed` / `must_fail`）
        喂给上面那条判据 ⇒ 必逐项报出（改判后的判据不是恒真断言 —— `migao-acceptance`
        「不会红的断言 = 空断言」）。**负控**：当前只读形态必须零违规（判据不是"永远红"的噪音）。
        """
        actions = _tool_action_enum(CUSTOMER_MANAGE_SRC)
        relapse = {"expectations": [{"tool": "customer_manage", "args": {"action": "add_tag"}}],
                   "must_succeed": [{"tool": "customer_manage"}],
                   "must_fail": [{"tool": "customer_manage"}]}
        got = _read_only_relapse_violations(relapse, actions)
        assert len(got) == 3, f"改前形态没有逐项报出（红证无判别力）：{got}"
        assert any("add_tag" in g for g in got), got
        assert _read_only_relapse_violations(_case_yaml("customer.yml", "CU-003"),
                                             actions) == [], "负控：当前只读形态被误判违规"

    def test_declares_a_namespace_that_is_actually_contested(self):
        """`namespaces` 必须声明在**真实争用**的键上 —— 声明一个没人争的键等于隔离没生效
        （`namespace_conflict_groups` 只对 ≥2 条声明的键分组）。"""
        c = _case_yaml("customer.yml", "CU-003")
        claims = c.get("namespaces") or []
        assert claims, "CU-003 没声明 namespaces（#3800 扫描表的「只有 pre_clean」档）"
        import eval_cases
        groups = lr.namespace_conflict_groups(list(eval_cases.ALL_CASES))
        for key in claims:
            assert len(groups.get(key, [])) > 1, (
                f"声明的命名空间键 {key!r} 没有任何别的用例争用 ⇒ 隔离形同虚设"
                f"（争用组：{groups.get(key)}）")


# ── ③ PG-013 的自清理与复位红线（#3833 / #3800 同族）───────────────────────────
class _FakeConn:
    """最小 asyncpg 连接替身：按 SQL 形状更新**内存态**，并记录被执行的语句。"""

    def __init__(self, db):
        self._db = db

    async def fetch(self, sql, *args):
        self._db.statements.append(("fetch", sql, args))
        order_no = args[0]
        if "UPDATE processing_orders" in sql:
            hit = [p for p in self._db.processing
                   if p["order_no"] == order_no and p["deleted"] == 0]
            for p in hit:
                p["deleted"] = 1
            return [{"id": f"po_{i}"} for i, _ in enumerate(hit)]
        raise AssertionError(f"未预期的 fetch SQL：{sql}")

    async def fetchrow(self, sql, *args):
        self._db.statements.append(("fetchrow", sql, args))
        order_no = args[0]
        if "UPDATE orders" in sql:
            if order_no not in self._db.orders:
                return None
            self._db.orders[order_no] = re.search(r"status = '([^']+)'", sql).group(1)
            return {"id": f"ord_{order_no}"}
        raise AssertionError(f"未预期的 fetchrow SQL：{sql}")

    async def close(self):
        return None


class _FakeAsyncpg:
    def __init__(self, db):
        self._db = db

    async def connect(self, *a, **k):
        self._db.connections += 1
        return _FakeConn(self._db)


class _Db:
    def __init__(self, orders, processing):
        self.orders, self.processing = orders, processing
        self.statements, self.connections = [], 0

    def active_processing(self, order_no):
        return [p for p in self.processing
                if p["order_no"] == order_no and p["deleted"] == 0]


def _patch_asyncpg(monkeypatch, db):
    fake = types.ModuleType("asyncpg")
    impl = _FakeAsyncpg(db)
    fake.connect = impl.connect
    monkeypatch.setitem(sys.modules, "asyncpg", fake)
    return db


class TestPG013DeclaresItsOwnReset:
    SEED_ORDER = "EVAL-MB-ORD-0002"

    def test_targets_the_seed_order_that_the_seed_marks_for_pg013(self):
        """复位对象必须是**种子为 PG-013 点名的那张专用订单**（seed remark 逐字含
        「PG-013 加工单生成用」），而不是随便一张已确认订单。"""
        c = _case_yaml("processing-order.yml", "PG-013")
        spec = (c.get("pre_clean") or [{}])[0]
        assert spec.get("type") == "processing_order_reset", c.get("pre_clean")
        order_no = spec.get("order_no")
        row = seed_order_row(str(order_no))
        assert any("PG-013" in f for f in row), (
            f"种子没有把 {order_no} 标给 PG-013（复位对象可能撞别的用例的专用订单）：{row}")
        # 同族另两张专用订单（#3658 分给 PG-015/PG-016）不得被本用例复位
        for other in ("EVAL-MB-ORD-0003", "EVAL-MB-ORD-0004"):
            assert other != order_no

    def test_initial_state_written_by_the_reset_matches_the_seed(self):
        """复位写的初始态必须**从种子取值**（`status = 'confirmed'`）——
        手写一份"初始状态"就会在 seed 改动后漂移（`test_eval_preclean_seed_parity.py`
        对 AS-004 的同一条教训）。"""
        seeded_status = seed_order_row(self.SEED_ORDER)[8].strip().strip("'")
        assert seeded_status == "confirmed", seeded_status
        assert f"status = '{seeded_status}'" in lr._RESTORE_ORDER_STATUS_SQL

    def test_reset_is_exact_match_only_never_substring_or_fuzzy(self):
        """**红线**（#3800 记录过 `product_remove` 的连带误删）：复位只能按 `order_no`
        **精确等值**命中，禁止 `LIKE` / 子串 / 模糊匹配，且 spec 只允许 `type` + `order_no`。"""
        sql = lr._RESET_PROCESSING_ORDER_SQL + lr._RESTORE_ORDER_STATUS_SQL
        assert "order_no = $1" in lr._RESTORE_ORDER_STATUS_SQL
        assert "order_no = $1" in lr._RESET_PROCESSING_ORDER_SQL
        for bad in ("LIKE", "ILIKE", "SIMILAR TO", "IN ("):
            assert bad not in sql, f"复位语句用了 {bad} —— 会连带命中别的订单：{sql}"
        spec = _case_yaml("processing-order.yml", "PG-013")["pre_clean"][0]
        assert set(spec) == {"type", "order_no"}, spec

    def test_reset_targets_only_the_named_order(self, monkeypatch):
        """**只动点名的订单**：同库里别的订单（含 PG-015 的 0003）状态与加工单不受影响。"""
        db = _Db(orders={self.SEED_ORDER: "producing", "EVAL-MB-ORD-0003": "confirmed"},
                 processing=[{"order_no": self.SEED_ORDER, "deleted": 0},
                             {"order_no": "EVAL-MB-ORD-0003", "deleted": 0}])
        _patch_asyncpg(monkeypatch, db)
        msg = asyncio.run(lr._reset_processing_order(self.SEED_ORDER))
        assert msg.startswith("已复位"), msg
        assert db.orders[self.SEED_ORDER] == "confirmed"
        assert db.active_processing(self.SEED_ORDER) == []
        assert db.orders["EVAL-MB-ORD-0003"] == "confirmed"
        assert len(db.active_processing("EVAL-MB-ORD-0003")) == 1, "误伤了别的订单的加工单"

    def test_success_message_avoids_the_reset_failure_wording(self):
        """措辞红线（#3751）：成功路径不得含「未复位」/「失败」，否则 `_reset_for_retry`
        会把结论误标成"前置与首次不等价"（不可归因于 agent）。"""
        msg = "已复位订单 EVAL-MB-ORD-0002 → confirmed（清掉 1 张在途加工单）"
        assert "未复位" not in msg and "失败" not in msg

    def test_missing_order_is_fail_closed_not_a_silent_pass(self, monkeypatch):
        """栈缺 seed（点名的订单不在）⇒ 必须报「未复位」⇒ 折进结论，不得静默放过。"""
        db = _Db(orders={}, processing=[])
        _patch_asyncpg(monkeypatch, db)
        msg = asyncio.run(lr._reset_processing_order(self.SEED_ORDER))
        assert "未复位" in msg and "没有订单" in msg, msg

    def test_asyncpg_unavailable_is_reported_with_the_consequence(self, monkeypatch):
        """`asyncpg` 缺失（L0 job 只装 pytest+pyyaml）⇒ 消息必须写明**后果**
        （重试前置不等价），否则归因时与"能力缺陷"同形（#3511）。"""
        monkeypatch.setitem(sys.modules, "asyncpg", None)
        msg = asyncio.run(lr._reset_processing_order(self.SEED_ORDER))
        assert "未复位" in msg and "不等价" in msg, msg


class TestPG013RetryPreconditionIsEquivalent:
    """**确定性复算**（零 LLM）：首跑 → 重试 的前置是否回到 seed 初始态。

    模型严格照实测：首跑把 `EVAL-MB-ORD-0002` 转 `producing` 并生成一张加工单；
    `_reset_for_retry` 只在用例声明了 `pre_clean` 时执行（opt-in）。
    """

    ORDER = "EVAL-MB-ORD-0002"

    def _after_first_attempt(self):
        db = _Db(orders={self.ORDER: "confirmed"}, processing=[])
        db.orders[self.ORDER] = "producing"                      # 首跑的产物①
        db.processing.append({"order_no": self.ORDER, "deleted": 0})   # 首跑的产物②
        return db

    def test_pre_fix_shape_leaves_the_retry_precondition_broken(self, monkeypatch):
        """**红证（改前 ⇒ 不等价）**：没有 `pre_clean` ⇒ 什么都不执行 ⇒
        订单停在 `producing`、加工单还在 ⇒ 第 2 次尝试的前置 ≠ 首跑
        （实测症状：R1 `orders=1`、R2「加工单早已生成，无需重复生成」⇒ agent 合理地不调工具）。"""
        db = self._after_first_attempt()
        _patch_asyncpg(monkeypatch, db)
        # 改前的 PG-013（YAML 里没有 pre_clean 键）—— 走**真实 opt-in 判据**
        pre_fix_case = _CaseStub("PG-013", [])
        assert lr.preclean_specs_for_retry(pre_fix_case) == [], "opt-in 判据变了？本红证前提失效"
        assert db.connections == 0, "改前形态竟然执行了复位"
        seeded = seed_order_row(self.ORDER)[8].strip().strip("'")
        assert db.orders[self.ORDER] == "producing" != seeded, "改前形态没复现前置不等价"
        assert db.active_processing(self.ORDER), "改前形态没留下加工单（红证无判别力）"

    def test_post_fix_shape_restores_the_seed_state(self, monkeypatch):
        """**红证（改后 ⇒ 等价）**：按**用例真实声明的** `pre_clean` 走真实复位分支 ⇒
        订单回 seed 状态、加工单被清 ⇒ 第 2 次尝试的前置与首跑等价。

        ⚠️ 这里刻意从 **YAML 单一源**读 spec（不是手写一份），否则测的是我编的 spec 而不是用例。
        """
        db = self._after_first_attempt()
        _patch_asyncpg(monkeypatch, db)
        declared_case = _CaseStub("PG-013",
                                  _case_yaml("processing-order.yml", "PG-013")["pre_clean"])
        specs = lr.preclean_specs_for_retry(declared_case)
        assert specs, "PG-013 仍然没有 pre_clean（#3800 同族病灶未修）"
        for spec in specs:
            msg = asyncio.run(lr._run_pre_clean("tok", spec))
            assert msg.startswith("已复位"), msg
        seeded = seed_order_row(self.ORDER)[8].strip().strip("'")
        assert db.orders[self.ORDER] == seeded, db.orders
        assert db.active_processing(self.ORDER) == [], db.processing
        # 前置条件的观测值：真的查了库（不是空跑）—— `migao-acceptance` v1.7 的要求
        assert db.connections == len(specs) and db.statements, db.statements


class TestPG013ForbiddenTextIsRoundScoped:
    """`PG-013` 的禁用词必须**声明成轮次作用域**（#3833）—— 反向守卫。

    为什么要在**用例资产侧**再锁一遍（机制侧已有 `test_eval_runner_assertion_scope.py`）：
    机制支持了轮次作用域，但用例仍可能写成全程裸字符串 ⇒ 假红**照旧**。
    本类锁的是"用例**真的用了**这个能力"，并用**派生注入**证明它有效：
    把声明的 dict 压平成全程裸串（= 改前语义），R1 的良性原文立刻又红。
    """

    CAPABILITY_DENIAL = ["暂不支持", "功能不存在", "没有这个功能", "生成未成功", "生成失败"]
    WRITE_ROUND_WORDS = ["无加工项", "无法生成加工单", "系统判定为"]
    BENIGN_R1 = (
        "📦 已确认（待发货）订单共 2 个，其中 **1 个含加工项**：\n"
        "✅ **可生成加工单**：EVAL-MB-ORD-0002（含加工项，已确认待发货，符合生成条件）\n"
        "⚠️ 20260915030240002 未见加工项，无法生成加工单。")

    def _declared(self):
        return _case_yaml("processing-order.yml", "PG-013")["forbidden_text"]

    def test_write_round_words_are_round_scoped_not_bare(self):
        declared = self._declared()
        bare = {w for w in declared if isinstance(w, str)}
        scoped = [w for w in declared if isinstance(w, dict)]
        for word in self.WRITE_ROUND_WORDS:
            assert word not in bare, (
                f"「{word}」仍是**全程**裸串 ⇒ R1 问答轮如实陈述会被判红（#3833 的假红形态）")
        rounds = {w.get("round"): set(w.get("any_of") or []) for w in scoped}
        assert set(rounds) == {2, 3}, f"写操作轮（R2 生成请求 / R3 确认）没有全部受限：{rounds}"
        for rnd, words in rounds.items():
            assert set(self.WRITE_ROUND_WORDS) <= words, (rnd, words)

    def test_capability_denial_words_stay_all_run(self):
        """**不降强度**：能力自我否定 / 编造失败类措辞必须仍是全程（任何一轮说出来都错）。"""
        bare = {w for w in self._declared() if isinstance(w, str)}
        assert set(self.CAPABILITY_DENIAL) <= bare, (self.CAPABILITY_DENIAL, bare)

    def test_flattening_the_declaration_brings_the_false_red_back(self):
        """**红证（派生注入）**：把声明的 dict 压平成全程裸串（= 改前语义）⇒
        R1 的**良性原文**立刻又红 ⇒ 证明轮次作用域是这条用例"不假红"的**充要**条件。"""
        declared = self._declared()
        flattened = []
        for w in declared:
            if isinstance(w, str):
                flattened.append(w)
            else:
                flattened.extend(w.get("any_of") or [])
        assert "无法生成加工单" in flattened and {"round": 2, "any_of": self.WRITE_ROUND_WORDS} \
            not in flattened, "派生注入没有还原成全程语义（红证无判别力）"
        tx = [{"__round": 1, "final_text": self.BENIGN_R1}, {"__round": 2, "final_text": "…"},
              {"__round": 3, "final_text": "…"}]
        # 压平会把同一个词重复登记两次（R2/R3 各一次）⇒ 断言集合而不是列表
        _got = lr.check_forbidden_text(tx, flattened)
        assert _got and set(_got) == {
            "forbidden_text: 回复含反模式词「无法生成加工单」（R1）"}, ("压平后没有复现假红", _got)
        assert lr.check_forbidden_text(tx, declared) == [], (
            "按**声明原样**跑良性 transcript 仍判红 ⇒ 用例形态没修好")

    def test_expectations_and_required_args_reflect_the_read_only_form(self):
        """`#3833` 的修法原话是「**只动 `pre_clean` 与 `forbidden_text`**，行为面断言原样」。

        ⚠️ #5247（B 端只读化）改判了这条的前提：PG-013 断言的写工具
        `processing_order_generate` 已从 B 端解绑 ⇒ 用例**退役**（`skip_reason` 非空）、
        `expectations` 收缩为只读 `order_query`、`required_args` / `must_succeed` 清空。
        原三条断言（`expectations` 含 `processing_order_generate`、`required_args` 里
        `order_ids` 必填、`must_succeed` 非空）在被测对象不存在后**无法复现**。

        改判成新事实的**等价形态**（不是放宽）：
        ① `expectations` **恰好**是只读 `order_query` —— 写工具不得残留（残留即死引用）；
        ② `required_args` 为空（写工具的参数契约随之失效，不许留空壳）；
        ③ `must_succeed` 为空（同上，`must_succeed: []` 这类空壳声明也不许有）；
        ④ 退役必须**显式登记**（`skip_reason` 非空且指向 #5247）——「退役 ≠ 删除」：
           条目留在用例库、理由可追溯。
        ——`forbidden_text` 的**轮次作用域**判据（本类其余三条）**一字未改**：那部分与写工具
        是否解绑无关（它判的是「R1 问答轮的良性原文不得被判红」），仍逐条生效。
        """
        c = _case_yaml("processing-order.yml", "PG-013")
        assert c["expectations"] == [{"tool": "order_query"}], c["expectations"]
        assert not (c.get("required_args") or []), c["required_args"]
        assert not (c.get("must_succeed") or []), c["must_succeed"]
        assert "#5247" in str(c.get("skip_reason") or ""), (
            "PG-013 的写能力已下线 ⇒ 必须以 skip_reason 显式退役"
            f"（不得静默留成活跃用例）：{c.get('skip_reason')!r}")
