# case_ids: CU-004, OR-017, MC-249
"""评测 harness 三处缺口（issue #8776）的**可判定性**守卫 —— 每条都配"会红"的判据。

## 病灶（run `42127246100`，B 族两条；诊断见 PR #8774）

① **一个标记压两种真相**：`PRECONDITION_NOT_RESTORED` 既表示「写没落库」（**产品缺陷**，
   要修写路径）又表示「夹具被改坏」（**基础设施缺陷**，读数不可信）。当次 CU-004 的
   **产品缺陷**被记成基础设施缺陷 ⇒ 整批读数被打上「不可信」，而该修的写路径从报告上消失。
② **不再参与命名空间串行**：CU-004 在 2026-09-21（#4992）把
   `namespaces[customer_phone:13800138000]` 换成了 `pre`/`post_clean` ⇒ 它不再进
   `customer_phone:13800138000` 争用组（那次 run 的分组逐字只列另外 6 条），而它写的正是
   那位共享客户 —— 真复位只解决**重试前置**，不解决**并行互斥**。
③ **form 卡形状不兼容**：OR-017 的 R2 只声明**纯文本** fallback，而 agent 那一轮发的是
   `interact(component="form", formFields=3)` ⇒ `harness_incompatible(no_fillable_payload)`
   ⇒ R2 被吃、R3 去答一张不存在的 choice 卡、轮次错位（首跑其实把订单建成了 ⇒ 能力没问题）。

## 判据（每条都会红；两个方向都有正控）

| # | 判据 | 红证形态 |
|---|---|---|
| 1 | 定位键不在而**种子值仍在** ⇒ `WRITE_NOT_PERSISTED`（甲） | 判别式关掉 ⇒ 落回乙（infra）标记 |
| 2 | 夹具真被改坏（种子也没了）⇒ `PRECONDITION_NOT_RESTORED`（乙） | 把种子塞回去 ⇒ 误报产品缺陷 |
| 3 | 两种真相**不共用桶**（`write_not_persisted_failures` ⇄ `restore_failures`） | 删桶 ⇒ 产品缺陷重新被读成"读数不可信" |
| 4 | CU-004 在 `customer_phone:13800138000` 争用组里（= 参与串行） | 清掉 `namespaces` ⇒ 它掉出该组 |
| 5 | OR-017 对**真实卡字段**（现取自那次 run 的 `formFields`）有可填载荷 | 删掉载荷 ⇒ `no_fillable_payload` |
| 6 | **负控**：真没有可填载荷的 form 卡**仍**报 `harness_incompatible` | 若哪天改成"猜答案回填"，本条必红 |

⚠️ 判据 6 是本单**必须做**的负控：修完 ①③ 之后 OR-017 不能再报 `harness_incompatible`，
但也**不能**变成"随便什么都通过" —— 「零载荷 ⇒ 判红」是**有意**的 fail-closed，
它防的正是 harness 猜答案把「agent 没问」洗成「通过」。
"""
from __future__ import annotations

import asyncio
import copy
import importlib.util
import sys
import types
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = REPO_ROOT / ".github" / "cases"

SEED_CUSTOMER_PHONE = "13800138000"
#: CU-004 写出的新号（用例 `post_clean` 的定位键）—— run 42127246100 里它**没落库**。
WRITTEN_PHONE = "13900001111"

#: **现取**自 run `42127246100` 的卡片原文：R1 那轮 `interact(component="form")` 的
#: `formFields[].key` 逐字是 `customer_name` / `customer_phone` / `customer_address`
#: （与其它 C 端下单用例的 `auto_fill` 同键；不是按别名表猜的）。
REAL_FORM_CARD_KEYS = ("customer_name", "customer_phone", "customer_address")


# ══════════════════════════════════════════════════════════════════════════════
# 一、装载：runner（L0 job 只有 pytest+pyyaml ⇒ 缺 httpx 时注入替身）
# ══════════════════════════════════════════════════════════════════════════════

def _load_runner():
    sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover - 本地 venv 有 httpx
        stub = types.ModuleType("httpx")

        class _AsyncClient:
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的 HTTP 一律走内存客户库替身")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)
    import local_runner
    return local_runner


lr = _load_runner()


def _all_cases() -> dict:
    """`.github/cases/*.yml` 的原始 dict（**声明层真值**，不是生成物）。"""
    out: dict = {}
    for f in sorted(CASES_DIR.glob("*.yml")):
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for c in doc.get("cases") or []:
            out[str(c.get("id"))] = c
    return out


def _shared_cases() -> list:
    """共享 `ALL_CASES` 的深拷贝（`EvalCase` 对象，供 `namespace_*` 纯函数用）。"""
    from unit_ci_workflows import conftest
    return conftest.shared_eval_cases()


# ══════════════════════════════════════════════════════════════════════════════
# 二、`customer_profile_restore` 的两个方向（复用同族守卫的内存客户库替身）
# ══════════════════════════════════════════════════════════════════════════════

def _install_book(monkeypatch, customers):
    from unit_ci_workflows import test_shared_fixture_restore_order_customer as sib
    book = sib._CustomerBook(customers=customers)
    monkeypatch.setattr(lr, "httpx", sib._FakeHttpx(book))
    return book


def _post_clean(spec) -> str:
    return asyncio.run(lr._run_post_clean("tok", spec))


CU004_POST_SPEC = {"type": "customer_profile_restore",
                   "customer_keyword": WRITTEN_PHONE, "phone": SEED_CUSTOMER_PHONE}


class TestTwoTruthsAreDistinguished:
    """判据 1/2：同一场景的两种事实必须报**不同**标记（拆标记的正控，两个方向都有）。"""

    def test_write_not_persisted_when_the_seed_is_still_there(self, monkeypatch):
        """甲（产品缺陷）：写没落库 ⇒ 种子号仍在、写出的新号不在 ⇒ `WRITE_NOT_PERSISTED`。"""
        _install_book(monkeypatch, [{"id": "cust_eval_zhangsan",
                                     "phone": SEED_CUSTOMER_PHONE,
                                     "wechatNickname": "张三"}])
        msg = _post_clean(CU004_POST_SPEC)
        assert msg.startswith(lr._WRITE_NOT_PERSISTED), (
            f"写没落库被报成了非产品缺陷（这是 run 42127246100 的原始误归因）：{msg!r}")
        # **必须**不在基础设施族里 —— 否则整批读数会被打上「不可信」
        assert lr.check_postclean_not_applied([msg]) == [], (
            f"产品缺陷同时落进 `restore_failures` 族 ⇒ 两种真相又压回一个标记：{msg!r}")
        assert lr.check_postclean_write_not_persisted([msg]) == [msg], msg

    def test_precondition_not_restored_when_the_fixture_is_really_broken(self, monkeypatch):
        """乙（基础设施缺陷）：种子号也没了 ⇒ 夹具确实被改坏 ⇒ `PRECONDITION_NOT_RESTORED`。"""
        _install_book(monkeypatch, [])
        msg = _post_clean(CU004_POST_SPEC)
        assert msg.startswith(lr._POSTCLEAN_NOT_APPLIED), (
            f"夹具真被改坏却报成了产品缺陷（会把修夹具的人引去查写路径）：{msg!r}")
        assert lr.check_postclean_write_not_persisted([msg]) == [], msg
        assert lr.check_postclean_not_applied([msg]) == [msg], msg

    def test_happy_path_reports_neither(self, monkeypatch):
        """正控（不许误报）：写**真的**落了库 ⇒ 复位成功，两个坏标记都不出现。"""
        _install_book(monkeypatch, [{"id": "cust_eval_zhangsan",
                                     "phone": WRITTEN_PHONE,
                                     "wechatNickname": "张三"}])
        msg = _post_clean(CU004_POST_SPEC)
        assert "已复位 客户「13900001111」 档案" in msg, msg
        assert "回读一致" in msg, msg
        assert not msg.startswith(lr._PRODUCT_DEFECT_MARKERS), msg
        assert lr.check_postclean_not_applied([msg]) == [], msg

    def test_discriminator_requires_a_written_identity(self):
        """判别式的**必要条件**：定位键 == 复位值 ⇒ 不存在"写没落库"这个解释（保守归 infra）。"""
        assert lr.missing_target_verdict("post", SEED_CUSTOMER_PHONE, SEED_CUSTOMER_PHONE,
                                         seed_present=True) == "not_restored"
        assert lr.missing_target_verdict("pre", WRITTEN_PHONE, SEED_CUSTOMER_PHONE,
                                         seed_present=True) == "not_restored"
        assert lr.missing_target_verdict("post", WRITTEN_PHONE, SEED_CUSTOMER_PHONE,
                                         seed_present=True) == "write_not_persisted"

    def test_red_proof_disabling_the_discriminator_reverts_to_infra(self, monkeypatch):
        """**红证（方向一）**：把"种子仍在"读成假 ⇒ 甲退化成乙（注入生效 + 判据真红）。"""
        _install_book(monkeypatch, [{"id": "cust_eval_zhangsan",
                                     "phone": SEED_CUSTOMER_PHONE,
                                     "wechatNickname": "张三"}])
        good = _post_clean(CU004_POST_SPEC)
        original = lr.missing_target_verdict
        mutated_src = original("post", WRITTEN_PHONE, SEED_CUSTOMER_PHONE, seed_present=False)
        assert mutated_src != "write_not_persisted", "注入未生效（自证）：关掉种子判据仍是甲"
        monkeypatch.setattr(lr, "missing_target_verdict",
                            lambda *a, **k: original(*a, **{**k, "seed_present": False}))
        mutated = _post_clean(CU004_POST_SPEC)
        assert good.startswith(lr._WRITE_NOT_PERSISTED) and \
            mutated.startswith(lr._POSTCLEAN_NOT_APPLIED), (
            f"关掉判别式后仍报产品缺陷 ⇒ 判据没有判别力：{mutated!r}")

    def test_ambiguous_target_is_not_rebranded_as_a_product_defect(self, monkeypatch):
        """**夹具缺陷不许洗成产品缺陷**：定位键命中多位（不唯一）⇒ 仍是乙（基础设施）。"""
        _install_book(monkeypatch, [
            {"id": "c1", "phone": WRITTEN_PHONE, "wechatNickname": "张三"},
            {"id": "c2", "phone": WRITTEN_PHONE, "wechatNickname": "张三"},
            {"id": "cust_eval_zhangsan", "phone": SEED_CUSTOMER_PHONE, "wechatNickname": "张三"},
        ])
        msg = _post_clean(CU004_POST_SPEC)
        assert "不唯一" in msg, msg
        assert msg.startswith(lr._POSTCLEAN_NOT_APPLIED), (
            f"「命中多位」被报成产品缺陷（判别式越界）：{msg!r}")
        assert lr.check_postclean_write_not_persisted([msg]) == [], msg

    def test_missing_keyword_is_still_a_config_error(self, monkeypatch):
        """**配置错误不许被判别式吃掉**：缺 `customer_keyword` ⇒ 仍是稳定标记（不猜目标）。"""
        _install_book(monkeypatch, [{"id": "cust_eval_zhangsan",
                                     "phone": SEED_CUSTOMER_PHONE,
                                     "wechatNickname": "张三"}])
        msg = _post_clean({"type": "customer_profile_restore", "phone": SEED_CUSTOMER_PHONE})
        assert "缺 `customer_keyword`" in msg, msg
        assert msg.startswith(lr._POSTCLEAN_NOT_APPLIED), msg

    def test_red_proof_the_failure_atom_is_a_different_atom(self):
        """**归因身份**必须不同：两条折叠成不同原子（否则指纹层仍把它们当同一件事）。"""
        d = lr._CASE_LEVEL_DETAIL
        a = lr._failure_atom(f"{lr._WRITE_NOT_PERSISTED}: x", d)
        b = lr._failure_atom(f"{lr._POSTCLEAN_NOT_APPLIED}: x", d)
        assert a == "write_not_persisted", a
        assert b == "precondition_not_restored(post_clean)", b
        assert a != b


# ══════════════════════════════════════════════════════════════════════════════
# 三、判定层：两种真相**不共用桶**（否则拆了标记还是分不清）
# ══════════════════════════════════════════════════════════════════════════════

def _verdict(**result) -> dict:
    base = {"case_id": "CU-004", "score": 0.0, "restore": [], "failed": []}
    base.update(result)
    return lr.completion_verdict([base])


class TestVerdictBucketsStayApart:
    def test_write_not_persisted_lands_in_the_product_bucket(self):
        msg = f"{lr._WRITE_NOT_PERSISTED}: 客户「13900001111」不在库里"
        v = _verdict(restore=[msg], write_not_persisted=[msg])
        assert v["write_not_persisted_failures"] == ["CU-004"], v
        assert v["restore_failures"] == [], (
            f"产品缺陷同时进了 `restore_failures` ⇒ 整批读数又被标成不可信：{v}")
        assert v["ok"] is False, "写没落库竟然不阻塞（fail-closed 被削）"

    def test_infra_failure_lands_in_the_restore_bucket(self):
        msg = f"{lr._POSTCLEAN_NOT_APPLIED}: 客户「13900001111」不在库里"
        v = _verdict(restore=[msg])
        assert v["restore_failures"] == ["CU-004"], v
        assert v["write_not_persisted_failures"] == [], v
        assert v["ok"] is False, v

    def test_red_proof_dropping_the_bucket_rebrands_a_product_defect(self):
        """**红证（方向二）**：删掉产品缺陷桶 ⇒ 一条产品缺陷重新落回"基础设施"清单。"""
        msg = f"{lr._WRITE_NOT_PERSISTED}: 客户「13900001111」不在库里"
        before = _verdict(restore=[msg], write_not_persisted=[msg])
        after = _verdict(restore=[msg])          # 等价于"判定层不知道这个标记"
        assert before["write_not_persisted_failures"] == ["CU-004"], before
        assert after["write_not_persisted_failures"] == [], after
        assert after["deterministic_failures"] == ["CU-004"], (
            f"删桶后该条无处安放（这正是归因错人的形态）：{after}")
        # 两条都**阻塞**（fail-closed 未削），差别只在归因桶 —— 这才是"拆标记"要的效果
        assert before["ok"] is False and after["ok"] is False, (before["ok"], after["ok"])
        assert lr._failure_atom(f"{lr._WRITE_NOT_PERSISTED}: x",
                                lr._CASE_LEVEL_DETAIL) == "write_not_persisted"

    def test_blocking_keys_and_return_points_agree(self):
        """声明 / 早退分支 / 正常分支三处键集必须一致（`_BLOCKING_VERDICT_KEYS` 同源）。"""
        expected = set(lr._BLOCKING_VERDICT_KEYS) | {
            "ok", "reason", "flake_released", "total", "passed"}
        assert "write_not_persisted_failures" in lr._BLOCKING_VERDICT_KEYS
        assert set(lr.completion_verdict([])) == expected, sorted(lr.completion_verdict([]))
        assert set(_verdict(score=1.0)) == expected, sorted(_verdict(score=1.0))


# ══════════════════════════════════════════════════════════════════════════════
# 四、CU-004 必须**参与命名空间串行**（②）
# ══════════════════════════════════════════════════════════════════════════════

NS_KEY = f"customer_phone:{SEED_CUSTOMER_PHONE}"


class TestNamespaceSerialization:
    def test_cu004_is_in_the_seed_phone_contest_group(self):
        """CU-004 写的正是那位共享客户 ⇒ 必须与同键组一起串行（否则真并发改同一客户）。"""
        groups = lr.namespace_conflict_groups(_shared_cases())
        group = groups.get(NS_KEY) or []
        assert "CU-004" in group, (
            f"CU-004 不在 `{NS_KEY}` 争用组里 ⇒ 它写的共享客户不再参与串行（issue #8776 ②）；"
            f"现取分组={ {k: v for k, v in groups.items() if k == NS_KEY} }")
        assert len(group) >= 2, f"该键只剩 {group} ⇒ 隔离形同虚设（单一声明者 = 零隔离）"

    def test_red_proof_dropping_namespaces_takes_cu004_out_of_the_group(self):
        """**红证**：清掉 CU-004 的 `namespaces` ⇒ 它立刻掉出该争用组（判据真红）。"""
        cases = _shared_cases()
        before = lr.namespace_conflict_groups(cases).get(NS_KEY) or []
        target = next(c for c in cases if c.id == "CU-004")
        target.namespaces = []
        after = lr.namespace_conflict_groups(cases).get(NS_KEY) or []
        assert "CU-004" in before, f"注入前就不在组里（判据无对象）：{before}"
        assert "CU-004" not in after, f"清掉声明后仍在组里 ⇒ 判据不是从声明推出来的：{after}"


# ══════════════════════════════════════════════════════════════════════════════
# 五、OR-017 的可填载荷（③）+ **负控** ④
# ══════════════════════════════════════════════════════════════════════════════

def _form_turn(keys=REAL_FORM_CARD_KEYS) -> list:
    """上一轮 agent 发的那张 form 卡（形状照 run 42127246100 的卡片原文）。"""
    return [{"interactive": [{"type": "form", "title": "请确认收货信息（可直接修改）",
                              "formFields": [{"key": k, "label": k} for k in keys]}]}]


def _case_form_values(case: dict) -> dict:
    """与 `run_case` 同一装配顺序：用例级 `auto_fill` 作基座 → 并入轮级声明。"""
    fv = dict(case.get("auto_fill") or {})
    for m in (case.get("user_inputs") or []):
        if isinstance(m, dict):
            fv.update(m.get("auto_fill") or {})
            fv.update((m.get("auto_respond") or {}).get("form_values") or {})
            fv.update(m.get("form_values") or {})
    return fv


def _answer(case: dict, values=None) -> str:
    spec = next(m for m in (case.get("user_inputs") or [])
                if isinstance(m, dict) and m.get("auto_respond"))
    fallback = str((spec.get("auto_respond") or {}).get("fallback") or "确认")
    fv = _case_form_values(case) if values is None else values
    return lr.resolve_auto_respond(_form_turn(), fallback=fallback, form_values=fv)


class TestOr017HasAFillablePayload:
    def test_the_real_form_card_gets_filled(self):
        """对**真实卡字段**能交付 `__FORM__|{json}`（甲：改用例补载荷，不改 harness）。"""
        out = _answer(_all_cases()["OR-017"])
        assert out.startswith("__FORM__|"), f"form 卡仍填不上（harness_incompatible）：{out!r}"
        assert lr.parse_harness_incompatible(out) is None, out
        assert '"customer_phone": "13800138000"' in out, out

    def test_alias_group_covers_the_common_card_key_variants(self):
        """别名已覆盖：卡字段改用 `name`/`phone`/`address`/`收货人` 等变体仍能回填。"""
        payload = _case_form_values(_all_cases()["OR-017"])
        for keys in (("name", "phone", "address"),
                     ("receiver", "mobile", "addr"),
                     ("收货人", "手机号", "地址")):
            filled = lr.match_form_values(list(keys), payload)
            assert set(filled) == set(keys), f"别名组没覆盖 {keys}：{filled}"

    def test_payload_window_audit_passes(self):
        """载荷**窗口**（#3804）：最后一个可作答轮次也能交付 —— 否则发卡晚一轮即不可完成。"""
        audit = lr.payload_window_audit(_all_cases()["OR-017"])
        assert audit["applies"] is True, audit
        assert audit["violation"] == "", audit

    def test_red_proof_dropping_the_payload_reports_incompatible(self):
        """**红证**：删掉载荷 ⇒ 真实卡形状下立刻 `harness_incompatible(no_fillable_payload)`。"""
        case = copy.deepcopy(_all_cases()["OR-017"])
        case.pop("auto_fill", None)
        for m in case.get("user_inputs") or []:
            if isinstance(m, dict):
                m.pop("auto_fill", None)
                (m.get("auto_respond") or {}).pop("form_values", None)
                m.pop("form_values", None)
        out = _answer(case)
        inc = lr.parse_harness_incompatible(out)
        assert inc is not None and inc.get("kind") == "no_fillable_payload", (
            f"删掉载荷后没报形状不兼容 ⇒ 判据没有判别力：{out!r}")
        assert inc.get("card") == "form", inc
        assert inc.get("card_fields") == list(REAL_FORM_CARD_KEYS), inc


class TestNegativeControlNoPayloadStillRed:
    """④ **负控**（本单必须做）：修完 ③ 不能变成"随便什么都通过"。

    「零载荷 ⇒ 判红」是**有意**的 fail-closed —— 它防止 harness 猜答案，把
    「agent 没问」伪装成「通过」。这一组判据在"有人把纯文本解析回填塞进 harness"时必红。
    """

    def test_empty_payload_still_reports_no_fillable_payload(self):
        out = lr.resolve_auto_respond(
            _form_turn(), fallback="我是张三，手机13800138000，地址杭州市西湖区文三路1号",
            form_values={})
        inc = lr.parse_harness_incompatible(out)
        assert inc is not None and inc.get("kind") == "no_fillable_payload", (
            f"纯文本 fallback 被拿去回填了 form 卡 ⇒ fail-closed 纪律被削弱（乙方案被误走）：{out!r}")
        # 且**不发**回填串：本轮仍发 fallback 文本（流程继续，不被误判成"填上了"）
        assert lr.unwrap_harness_signature(out, "我是张三", []) == "我是张三", out

    def test_zero_match_payload_still_reports_form_fields_mismatch(self):
        out = lr.resolve_auto_respond(_form_turn(), fallback="确认",
                                      form_values={"不相关字段": "值"})
        inc = lr.parse_harness_incompatible(out)
        assert inc is not None and inc.get("kind") == "form_fields_mismatch", out
        assert inc.get("case_fields") == ["不相关字段"], inc

    def test_a_different_shaped_card_is_not_silently_accepted(self):
        """卡形状漂移（字段全是别名表外的键）⇒ 有载荷也必须报 `form_fields_mismatch`。"""
        card = _form_turn(("order_remark", "invoice_title", "delivery_slot"))
        out = lr.resolve_auto_respond(card, fallback="确认",
                                      form_values=_case_form_values(_all_cases()["OR-017"]))
        inc = lr.parse_harness_incompatible(out)
        assert inc is not None and inc.get("kind") == "form_fields_mismatch", out
