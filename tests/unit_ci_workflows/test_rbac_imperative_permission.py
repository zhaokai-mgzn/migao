# case_ids: MC-158
"""判据 8 认得**命令式**权限校验（issue #6378）。

## 病（现取，不是假说）

RBAC 单一源判据的判据 8（`test_agent_permission_parity.py::problems_registered_decisions`）
此前只读**注解式** `@RequirePermission(...)` ⇒ 真实的**命令式**校验
（`PermissionInterceptor.requirePermission(...)`，issue #4148 的既有机制，与 AOP 拦截**走同一份**判定）
被读成「没有校验」⇒ 那条端点被记进「未注解台账」`UNANNOTATED_ENDPOINTS`。

后果 = **台账虚高**：看上去有 N 个端点没权限校验，实际它们有，只是写法不同
（issue #6367 包 P2 因此不得不把上限从 18 显式放宽到 19；issue #6378 要求退债）。

## 判据（每条都配注入式红证，见文件末尾两节）

| # | 判什么 | 会怎么红 |
|---|---|---|
| ① | 注解式端点仍被认出（**负控**：不许把已认的弄丢） | 注解解析被改坏 ⇒ `permission` 不为 `order:list` |
| ② | 命令式端点被认出，且码与注解式**共用同一个提取函数**（同一字面量正反例） | 命令式识别被摘掉 ⇒ `checked` 为假；两种写法各写一套正则 ⇒ 正反例漂 |
| ③ | 同一文件里两种形态**混合**也能逐端点正确归因（含「注释里提到不算」「无关 helper 不算」） | 归因串味（把 `if` 块 / 无关 helper / 注释当成校验）⇒ 该红的那几条必红 |
| ④ | 台账**真读得出来**（不是写死）：把真实命令式校验从源码里摘掉 ⇒ 判据 8 当场报「未登记」 | 台账若写死/绕过解析 ⇒ 摘掉校验后不报 |
| ⑤ | 台账上限**真的收紧了**：现值 24（原 26）；命令式识别一旦失效 ⇒ 需回涨 2 条 ⇒ 现上限红、旧上限 26 兜不住 | 上限改回旧值 ⇒ 该回归不再必红（本判据当场红） |

## 边界（照实登记，不粉饰）

- 本判据只判「**有没有**命令式校验」（`JavaEndpoint.checked`），**不判**它的码选得对不对
  （逐 target 的 `product:create` / `order:create` 由 `ImageRecognitionController*Test` 的 Java 判据兜）；
- 码只有在**字面量实参**时才静态可得；动态实参（`requirePermission(permission)`）**判不出码**，
  如实记成「有校验、码不可静态判定」（`imperative_permissions` 为空）—— 不猜；
- 载体识别只跟「**同一文件**内的方法定义」且签名参数里不含嵌套括号；认不出的签名**不猜**（保守方向）；
- 判据 2（工具码 ≡ 端点码）仍按 `ep.permission`（注解）取码：工具若调用一个**只有**命令式校验的
  端点，仍会要求它登记进 `UNANNOTATED_ENDPOINTS`（**已知未覆盖面**，现取无工具命中该形态）。
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTROLLER_DIR = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java" / "com" / "migao" / "admin" / "controller"
ATTR_PATH = REPO_ROOT / "backend" / "ai-agent-service" / "tests" / "tool_http_attribution.py"
PARITY_PATH = REPO_ROOT / "tests" / "unit_ci_workflows" / "test_agent_permission_parity.py"
MANIFEST_PATH = REPO_ROOT / "tests" / "unit_ci_workflows" / "test_rbac_single_source_manifest.py"

#: 夹具用的相对路径（机具只裁路径里含 `/controller/` 的文件）。
REL = "com/migao/admin/controller/Probe6378Controller.java"

#: 夹具控制器的头（类级 base 路径 + 依赖字段；`PermissionInterceptor` 就是真实那一个）。
_HEAD = """package com.migao.admin.controller;

@RestController
@RequestMapping("/api/admin/probe")
public class Probe6378Controller {

    private final PermissionInterceptor permissionInterceptor;
"""

#: 注解式端点（① 的负控）。
_ANNOTATED = """
    @GetMapping("/annotated")
    @RequirePermission("order:list")
    public Object annotated() {
        return null;
    }
"""

#: 命令式端点：**只有**直接调用，没有注解（② 的主角）。
_IMPERATIVE = """
    @PostMapping("/imperative")
    public Object imperative() {
        permissionInterceptor.requirePermission("order:refund");
        return null;
    }
"""

#: 两种形态都没有（③ 的负控）。
_NEITHER = """
    @GetMapping("/neither")
    public Object neither() {
        return null;
    }
"""

#: 注释里提到 `requirePermission(...)` **不算**校验（本仓大量 javadoc 逐字这样写）。
_COMMENT_ONLY = """
    /**
     * 本方法**没有**注解 —— 说明里会提到 permissionInterceptor.requirePermission("order:refund")，
     * 但那是散文，不是代码。
     */
    @GetMapping("/comment-only")
    public Object commentOnly() {
        // permissionInterceptor.requirePermission("order:refund");
        return null;
    }
"""

#: 载体形态（与真实 `ImageRecognitionController.requireTargetPermission` 同形）：
#: 端点体只调私有判定，真正的 `requirePermission(...)` 在 helper 里、实参是**变量** ⇒ 码判不出。
_HELPER_DYNAMIC = """
    @PostMapping("/helper-dynamic")
    public Object helperDynamic(String target) {
        requireTargetPermission(target);
        return null;
    }

    private void requireTargetPermission(String target) {
        String permission = "product".equals(target) ? "product:create" : null;
        permissionInterceptor.requirePermission(permission);
    }
"""

#: 载体形态里码是**字面量** ⇒ 码静态可得（② 的第二个正例）。
_HELPER_LITERAL = """
    @GetMapping("/helper-literal")
    public Object helperLiteral() {
        requireRefund();
        return null;
    }

    private void requireRefund() {
        permissionInterceptor.requirePermission("order:refund");
    }
"""

#: 无关 helper（不碰权限）⇒ 端点**不得**被读成有校验（③ 的假阳方向）。
_PLAIN_HELPER = """
    @GetMapping("/plain-helper")
    public Object plainHelper() {
        return helperWithoutCheck();
    }

    private Object helperWithoutCheck() {
        return null;
    }
"""

#: 控制流陷阱：`if (...) { requirePermission(...) }` 只属于**它自己那个**端点；
#: 同文件的另一个带 `if`、但没有校验的端点不得被串味（`_NOT_A_DEFINITION` 的回归判据）。
_IF_WITH_CHECK = """
    @PostMapping("/if-with-check")
    public Object ifWithCheck(String action) {
        if ("refund".equals(action)) {
            permissionInterceptor.requirePermission("order:refund");
        }
        return null;
    }
"""

_IF_WITHOUT_CHECK = """
    @PostMapping("/if-without-check")
    public Object ifWithoutCheck(String action) {
        if ("x".equals(action)) {
            return null;
        }
        return null;
    }
"""


def _load_module(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    assert path.is_file(), f"被判据引用的机具不存在：{path}（路径漂移 ⇒ 红，不得静默跳过）"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ATTR = _load_module("migao_rbac_imperative_attribution", ATTR_PATH)
PARITY = _load_module("migao_rbac_imperative_parity", PARITY_PATH)
MANIFEST = _load_module("migao_rbac_imperative_manifest", MANIFEST_PATH)


def _src(*methods: str) -> str:
    return _HEAD + "\n".join(methods) + "\n}\n"


def _parse(*methods: str):
    """夹具控制器 → `{(verb, 归一化路径): JavaEndpoint}`（走**真实**解析器，不另造一份）。"""
    index = ATTR.java_endpoints(None, {REL: _src(*methods)})
    out = {}
    for (verb, path), eps in index.items():
        assert len(eps) == 1, f"夹具端点解析出 {len(eps)} 条（夹具写坏了）：{verb} {path}"
        out[(verb, path)] = eps[0]
    assert out, "夹具解析出 0 个端点 ⇒ 本判据会空跑（fail-closed）"
    return out


def _real_controller_sources() -> dict[str, str]:
    """实盘 controller 源码（`{相对 java 根路径: 源码}`，与守卫**同一口径**；只读）。"""
    return {
        f"com/migao/admin/controller/{p.relative_to(CONTROLLER_DIR).as_posix()}": p.read_text(
            encoding="utf8"
        )
        for p in sorted(CONTROLLER_DIR.rglob("*.java"))
    }


# ══════════════════════════════════════════════════════════════════════════════
# 判据 ①：注解式端点仍被认出（负控 —— 不许把已认的弄丢）
# ══════════════════════════════════════════════════════════════════════════════


def test_annotation_form_is_still_recognized():
    ep = _parse(_ANNOTATED)[("GET", "/api/admin/probe/annotated")]
    assert ep.permission == "order:list", f"注解式端点的生效码丢了：{ep.permission!r}"
    assert ep.checked is True
    assert ep.imperative_permissions == frozenset(), (
        f"注解式端点不该被记上命令式码：{sorted(ep.imperative_permissions)}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 判据 ②：命令式端点被认出 + 两种形态共用同一个提取函数（同一字面量正反例）
# ══════════════════════════════════════════════════════════════════════════════


def test_imperative_form_is_recognized():
    ep = _parse(_IMPERATIVE)[("POST", "/api/admin/probe/imperative")]
    assert ep.permission is None, "夹具必须**没有**注解（否则这条判据没对准命令式那一半）"
    assert ep.checked is True, "命令式校验没被认出 ⇒ 该端点会被记进「未注解台账」（issue #6378 的病）"
    assert ep.imperative_permissions == frozenset({"order:refund"}), (
        f"命令式取到的码不对：{sorted(ep.imperative_permissions)}"
    )


def test_both_forms_extract_the_same_code_literal_identically():
    """**同一把码字面量**：注解式与命令式必须得到逐字相同的值（正例）。

    反例 = 打错一个字母 ⇒ 不相等（证明这条判据真的在比字面量，不是恒真）。
    """
    same = (
        '@RequirePermission(value = "order:refund")\n'
        'permissionInterceptor.requirePermission("order:refund");'
    )
    assert ATTR.permission_codes(same, form=ATTR.FORM_ANNOTATION) == ["order:refund"]
    assert ATTR.permission_codes(same, form=ATTR.FORM_IMPERATIVE) == ["order:refund"]
    assert ATTR.permission_codes(same) == ["order:refund", "order:refund"]

    typo = 'permissionInterceptor.requirePermission("order:refnd");'
    assert ATTR.permission_codes(typo, form=ATTR.FORM_IMPERATIVE) == ["order:refnd"]
    assert ATTR.permission_codes(typo, form=ATTR.FORM_IMPERATIVE) != ["order:refund"]


def test_annotation_and_imperative_forms_land_in_the_same_normalized_value():
    """两种形态在**端点解析**里也落到同一个值（不是只有那个函数里一致）。"""
    eps = _parse(
        """
    @GetMapping("/by-annotation")
    @RequirePermission("order:refund")
    public Object byAnnotation() {
        return null;
    }
""",
        """
    @GetMapping("/by-imperative")
    public Object byImperative() {
        permissionInterceptor.requirePermission("order:refund");
        return null;
    }
""",
    )
    annotated = eps[("GET", "/api/admin/probe/by-annotation")]
    imperative = eps[("GET", "/api/admin/probe/by-imperative")]
    assert annotated.permission == "order:refund"
    assert imperative.permission is None
    assert imperative.imperative_permissions == frozenset({annotated.permission}), (
        "注解式与命令式取同一把码却解析成两个值 ⇒ 两种写法已在漂"
    )


def test_helper_mediated_imperative_check_is_recognized():
    """载体形态：码在私有 helper 里（真实 `requireTargetPermission` 的同一形状）。"""
    literal = _parse(_HELPER_LITERAL)[("GET", "/api/admin/probe/helper-literal")]
    assert literal.checked is True, "helper 里的命令式校验没被跟进 ⇒ 真实图片识别两条会漏"
    assert literal.imperative_permissions == frozenset({"order:refund"})

    dynamic = _parse(_HELPER_DYNAMIC)[("POST", "/api/admin/probe/helper-dynamic")]
    assert dynamic.checked is True, "helper 的实参是变量时仍必须认出「有校验」"
    assert dynamic.imperative_permissions == frozenset(), (
        f"动态实参的码**判不出**，不该猜一个：{sorted(dynamic.imperative_permissions)}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 判据 ③：同一文件里两种形态混合 ⇒ 逐端点正确归因
# ══════════════════════════════════════════════════════════════════════════════


def test_mixed_file_attributes_each_endpoint_separately():
    eps = _parse(
        _ANNOTATED,
        _IMPERATIVE,
        _NEITHER,
        _COMMENT_ONLY,
        _PLAIN_HELPER,
        _IF_WITH_CHECK,
        _IF_WITHOUT_CHECK,
        _HELPER_DYNAMIC,
    )
    checked = {key for key, ep in eps.items() if ep.checked}
    assert checked == {
        ("GET", "/api/admin/probe/annotated"),
        ("POST", "/api/admin/probe/imperative"),
        ("POST", "/api/admin/probe/if-with-check"),
        ("POST", "/api/admin/probe/helper-dynamic"),
    }, f"混合文件的归因串味了：实际认成有校验的 = {sorted(checked)}"
    # 三个假阳方向的具名负控
    assert eps[("GET", "/api/admin/probe/comment-only")].checked is False, (
        "**注释里**提到 requirePermission(...) 被当成了校验（本仓 javadoc 大量这样写 ⇒ 会假绿）"
    )
    assert eps[("GET", "/api/admin/probe/plain-helper")].checked is False, (
        "调用了不碰权限的 helper 就被当成有校验（假阳）"
    )
    assert eps[("POST", "/api/admin/probe/if-without-check")].checked is False, (
        "同文件另一个端点 `if (...) { requirePermission(...) }` 的块被串到了这个端点（假阳）"
    )
    assert eps[("GET", "/api/admin/probe/neither")].checked is False


def test_real_repo_endpoints_are_attributed_by_form():
    """实盘：注解 + 命令式**共存**的端点（`AgentOrderController.updateOrder`）逐面取到各自的值。"""
    index = ATTR.JavaEndpointIndex(java_sources=_real_controller_sources())
    eps = index.endpoints()
    update = eps[("PATCH", "/api/admin/agent/orders/{}")]
    assert len(update) == 1
    assert update[0].permission == "order:update", "注解码（门槛码）被命令式码顶掉了"
    assert update[0].imperative_permissions == frozenset({"order:refund"}), (
        "退款 action 的命令式复检没被认出"
    )
    for key in (("POST", "/api/admin/image-recognition"), ("POST", "/api/admin/image-recognition/interpret")):
        ep = eps[key][0]
        assert ep.permission is None
        assert ep.checked is True, f"{key} 的命令式校验没被认出 ⇒ 台账又要虚高一条"


# ══════════════════════════════════════════════════════════════════════════════
# 判据 ④：台账**真读得出来**（不是写死的）
# ══════════════════════════════════════════════════════════════════════════════


def test_ledger_is_derived_not_hardcoded():
    """把真实命令式校验摘掉 ⇒ 判据 8 必须当场报「未登记」（那两条已从台账删除）。"""
    sources = PARITY._source_map()
    clean = PARITY.problems_registered_decisions(PARITY.build_world(sources))
    assert [p for p in clean if "image-recognition" in p] == [], (
        f"落地态就不该报这两条（否则台账/识别不一致）：{clean}"
    )

    key = "java:controller/ImageRecognitionController.java"
    before = sources[key]
    needle = "permissionInterceptor.requirePermission(permission);"
    assert before.count(needle) == 1, f"注入锚点不唯一（{before.count(needle)} 处）⇒ 本红证无效"
    mutated = dict(sources)
    # 「改回注解缺失形态」= 命令式校验不存在（端点从此真的没有任何校验）
    mutated[key] = before.replace(needle, "")
    assert mutated[key] != before, "注入没生效（源码未变）⇒ 本红证是空跑"

    problems = PARITY.problems_registered_decisions(PARITY.build_world(mutated))
    for endpoint in ("POST /api/admin/image-recognition", "POST /api/admin/image-recognition/interpret"):
        assert any(endpoint in p and "未登记" in p for p in problems), (
            f"命令式校验被摘掉后，`{endpoint}` 必须被报成「未登记」（台账条目已删除、上限已降）"
            f"—— 实际 problems = {problems}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 判据 ⑤：红证 —— 摘掉识别 / 把上限改回旧值，各自必红
# ══════════════════════════════════════════════════════════════════════════════


def test_red_proof_without_imperative_recognition_the_check_disappears(monkeypatch):
    """注入式红证 ①：把命令式锚换成一个永不匹配的模式 ⇒ 判据 ② 的那条断言必红。"""
    monkeypatch.setattr(ATTR, "_IMPERATIVE_ANCHOR_RE", re.compile(r"(?!x)x"))
    ep = _parse(_IMPERATIVE)[("POST", "/api/admin/probe/imperative")]
    assert ep.checked is False, "摘掉命令式识别后端点仍被认成有校验 ⇒ 判据 ② 是空断言"
    assert ep.imperative_permissions == frozenset()


def test_red_proof_ceiling_is_pinned_to_the_lowered_reading():
    """注入式红证 ②：上限从 26 降到 24 是**承重**的。

    回归形态 = 命令式识别失效（判据 ④ 实测那条注入）⇒ 那两条端点必须重新登记 ⇒ 台账 24 + 2 = 26：
    · 上限 26（旧值）⇒ `24+2 > 26` **不成立** ⇒ 该回归**看起来没事**（这正是「退回 19」那种放宽的形态）；
    · 上限 24（现值）⇒ `26 > 24` **成立** ⇒ 报「只许缩短」。
    """
    readings = MANIFEST.load_generator().build_readings()
    counts = readings["ledger_counts"]
    ledger_len = len(PARITY.UNANNOTATED_ENDPOINTS)
    assert counts["UNANNOTATED_ENDPOINTS"] == ledger_len == 24, (
        f"台账现值不是 24（读数 {counts['UNANNOTATED_ENDPOINTS']} / 条数 {ledger_len}）"
        "—— 若这是有意的，请同批把本判据与上限一起更新"
    )
    assert MANIFEST.LEDGER_CEILINGS["UNANNOTATED_ENDPOINTS"] == 24, "上限没跟着降到现值"
    for pattern in ("POST /api/admin/image-recognition", "POST /api/admin/image-recognition/interpret"):
        assert pattern not in PARITY.UNANNOTATED_ENDPOINTS, f"`{pattern}` 还在台账里（识别没落地）"

    assert MANIFEST.ledger_growth_problems(counts, MANIFEST.LEDGER_CEILINGS) == [], (
        "落地态就超上限（前提不成立）"
    )
    regressed = dict(counts, UNANNOTATED_ENDPOINTS=counts["UNANNOTATED_ENDPOINTS"] + 2)
    hit = MANIFEST.ledger_growth_problems(regressed, MANIFEST.LEDGER_CEILINGS)
    assert any("UNANNOTATED_ENDPOINTS" in p and "只许缩短" in p for p in hit), (
        f"回涨 2 条没被现上限拦住：{hit}"
    )
    old_ceilings = dict(MANIFEST.LEDGER_CEILINGS, UNANNOTATED_ENDPOINTS=26)
    assert MANIFEST.ledger_growth_problems(regressed, old_ceilings) == [], (
        "旧的 26 竟然也能拦住同一次回涨 ⇒ 本红证没有判别力（上限收紧是假的）"
    )
