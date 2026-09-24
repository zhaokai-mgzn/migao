# case_ids: HR-009, MC-021
# （沿用 tests/unit_ci_workflows/** 既有惯例：本文件判的是 **B 端/米宝失败兜底面**
#   —— HR-009「米宝无某能力时须如实说明并给后台开通路径（不得自旋重试）」与
#   MC-021「B 端能力面不谎报」同族。本 PR **不新建用例族**、**不新增 [backend-contract] 用例**。）
"""**族 6（善后与补救）的「失败 → 原因 → 补救」登记表类级元守卫**（issue #5441，§23 G1/G2/G5）。

## 立案理由：失败兜底这件事过去**根本没有面**

族 1~5 在做「让 Agent 能做事」；族 6 做「做不成时怎么办」。而「做不成」这一面在本仓过去是
**散落的**：`tool_not_found` 的话术在 `react_turn`，授权拒绝的话术在 `app/tools/base.py`，
后台页面路径又在 `references/base/principles.md` —— 三处各自维护，**没有任何东西会因为
「失败码没有对应的用户话术」而变红**（§19「不会红的判据」形态）。

## 四个判据面

| 面 | 判据 |
|---|---|
| 登记面 | 登记表**必须覆盖运行时真实会出现的失败码全集**（未登记 ⇒ 走默认话术，且**默认话术本身**受同一批判据约束）；未登记码冻结在 `remedy_registry_ledger.json` 的 `awaiting_rows`，**逐值相等、涨跌都红** |
| 重试面 | 「可重试」**不是**表里手写的第三个真相源 —— 由**既有单一口径**现取推导（`app/tools/base.py` 的 `NON_RETRYABLE_ERROR_CODES` + 工具类 `idempotent` 标注），表里的 `retry=` 是**被校验的声明**；不可重试 ⇒ 话术**不得**出现重试字样 |
| 引用面 | 🔴 **复用** `test_dead_capability_meta_guard.py` 的 `problems_dead_refs` —— 登记表文本已由该判据**同批登记为射程内文本面**（`remedy:` 源，见该文件 `remedy_texts` / `surface_sources`）⇒ 「指点去哪里」的文本点名了**任何 skill 都调不到**的工具即红，**不另立第二套** |
| 文本面 | 用户可见文本 = **纯中文短句**（无 ASCII 字母 ⇒ 结构上不可能回显短码 / 工具名 / 异常原文 / `Traceback`）；话术里点名的入口**必须被声明**（工具 → 必须在工具词汇表里；页面 → 必须是真实侧边栏菜单项） |

## 为什么「可重试/不可重试」必须派生而不许手写（本单最关键的一条）

幂等性不成立的操作（下单 / 支付 / 批量写）**绝不能建议重试** —— 否则用户按提示重来一次
就是**重复写入**。既有单一口径已经在两处：

1. **按码**：`app/tools/base.py::NON_RETRYABLE_ERROR_CODES`（授权/认证类，换参数也不可能成功）；
2. **按操作**：`BaseTool.idempotent`（`app/tools/order_create.py` 明写 `idempotent = False # 每次调用创建新订单`），
   而 `app/graph/skills/base_skill.py::_self_correct_retry` 已在消费它（非幂等写工具抑制自动重试）。

⇒ 本表**不新增**第三个真相源：`retry=` 只是**声明**，判据拿上面两个源**现取**推导后校验它；
且**取不到证据一律判不可重试**（与 `base_skill` 的 fail-safe 同向）。

## 红证（§23 G7：**前提自证**，不是「锚点可命中」）

`test_every_judgement_can_go_red` 的每条注入都自证：① **注入生效**（文本真的变了）；
② 注入的**对象真的进了被判定面**；③ 判据**变红**。其中一条就是本单任务书点名的注入式红证：
把下单（非幂等）失败的建议改成「请重试」⇒ **必须变红**。

## 未固化 / 已知边界（照实登记，§19.1）

- **码集口径**：AST 现取 `app/**/*.py` 里**静态可见**的失败**短码**（`error_code=` 关键字、
  `{"error"|"error_code": "<短码>"}` 字典字面量、`*ERROR_CODES` 冻结集），短码形态 = `^[A-Za-z][A-Za-z0-9_]*$`。
  形如 `"No tool context available"`（自由文本，不是短码）**有意排除**；运行期由服务端**动态回传**的
  未登记码走**默认话术**（默认话术受本文件全部文本面判据约束）；
- **页面入口的可达口径 = 「真实侧边栏节点」**（`frontend/admin-web/src/config/menu.ts` 是**唯一真值源**，
  `Sidebar.tsx` 只读它 —— 复用 `test_menu_three_sources_are_isomorphic.py` 的解析函数，不另立第二套）。
  🔴 **射程自 issue #5454 起覆盖存量**（本文件原登记「`_denial_suggestion` / `principles.md` 的存量措辞
  **不在本判据射程内**……**不假装本判据覆盖了它**」—— 那条欠账**已收口**，见「一·B 存量页面指针面」）：
  `legacy_pointer_problems` 现取「模型可见文本面 ∪ `app/**/*.py` 字面量」里**所有**页面指针，
  首级必须是 `sidebar_nodes()`（组名 ∪ 菜单项 ∪ **独立项**）之一。**存量不一致已逐条改对**：
  「角色管理」→「组织管理 → 岗位权限」（与 admin-api 的 403 文案同源，那边本来就写「岗位权限」）、
  「商品管理」→「商品列表」、「客户管理」→「客户列表」、「知识卡片」→「知识库」、
  「系统设置」/「AI 配置」→「企业基础信息」、「库存」/「商品分类」/「加工项」→ 真实菜单项。
  显式不判表 `LEGACY_POINTER_EXEMPTIONS` 现取 **2 条**（C 端「我的」页、看板字段名「应做数量」），
  条数冻结在 `LEGACY_POINTER_EXEMPTION_COUNT`，**只许缩短**；
- **本文件不判**「话术在真实对话里是否被采用」（那要 LLM 层评测，本单不派发评测）；
  它判的是**登记表本身的机械性质** —— 表里的行与运行时真实失败码是否对齐、建议会不会导致重复写入、
  点名的入口存不存在。
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from unit_ci_workflows import test_dead_capability_meta_guard as dc
from unit_ci_workflows import test_menu_three_sources_are_isomorphic as menu

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = REPO_ROOT / "backend" / "ai-agent-service" / "app"
REGISTRY_PATH = AGENT_ROOT / "utils" / "remedy_registry.py"
REGISTRY_SURFACE = f"remedy:{REGISTRY_PATH.relative_to(REPO_ROOT)}"
CONSUMER_PATH = AGENT_ROOT / "graph" / "skills" / "execution" / "react_turn.py"
LEDGER_PATH = Path(__file__).with_name("remedy_registry_ledger.json")

#: 失败**短码**的形态（自由文本，如 `"No tool context available"`，**不是**短码 ⇒ 不在码集里）。
CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

#: **重试字样**（不可重试的行出现任一 ⇒ 红）。
RETRY_MARKERS = ("重试", "再试", "重新提交", "重新发起", "retry", "Retry", "RETRY")

#: 用户可见文本里**不许**出现的兜底/归因形态（ASCII 字母已由「纯中文」判据结构性排除）。
#: ⚠️ 含**「转人工」族**（hard 纪律 ③）：用户已裁定下线（2026-09-19「不应该存在 human_handoff
#: 这种东西，以后全是 AI 来判断」）⇒ 补救路径里出现它就是**回退**（`app/tools/human_handoff.py`
#: 文件头逐字写明它不在注册表、不在任何 skill 的 `tool_names` 里，模型拿不到）。
FORBIDDEN_TEXT = ("未知错误", "incident=", "Traceback", "Exception", "Error",
                  "转人工", "人工客服", "找人工")

#: 工具名单里太短的词会与自然语言碰撞（与 MC-021 的 `MIN_TOOL_NAME_LEN` 同口径）。
MIN_TOOL_NAME_LEN = 4

REPRO = ("复算（零依赖、秒级）：python3 -m pytest "
         "tests/unit_ci_workflows/test_remedy_registry_guard.py -q -s")


# ══════════════════════════════════════════════════════════════════════════════
# 一、读源：现状（现取），不是抄清单
# ══════════════════════════════════════════════════════════════════════════════


def _string(node: ast.AST):
    """静态字符串取值（字面量 / 隐式拼接）：取不到 ⇒ `None`（保守，不猜）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in ast.walk(node)
                       if isinstance(v, ast.Constant) and isinstance(v.value, str))
    return None


def _literal_codes(node: ast.AST) -> set:
    """冻结集右值的取码：`frozenset({...})` / `set(...)` / 裸 `{...}` 都要拆（**单一真相源**）。

    ⚠️ 不能直接 `ast.literal_eval` —— `frozenset({...})` 不是字面量，会被判非法
    ⇒ `NON_RETRYABLE_ERROR_CODES` 与 `AUTHENTICATION_ERROR_CODES` 的码**静默取不到**，
    码集凭空少 4 条而判据照样「绿」（实测踩到：本判据的 `unknown` 检查把它抓了出来）。
    """
    target = node
    if isinstance(target, ast.Call):
        fn = getattr(target.func, "id", None)
        if fn not in ("frozenset", "set", "tuple", "list") or not target.args:
            return set()
        target = target.args[0]
    try:
        values = ast.literal_eval(target)
    except (ValueError, SyntaxError):
        return set()
    if not isinstance(values, (set, frozenset, list, tuple)):
        return set()
    return {v for v in values if isinstance(v, str) and CODE_RE.match(v)}


def _codes_in(tree: ast.AST) -> set:
    """一棵 AST 里现取的短码（`error_code=` 关键字 / `{"error"|"error_code": "<短码>"}` / 冻结集）。"""
    out: set = set()

    def add(value):
        if isinstance(value, str) and CODE_RE.match(value):
            out.add(value)

    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id.endswith("ERROR_CODES")):
            out |= _literal_codes(node.value)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "error_code":
                    add(_string(kw.value))
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value in ("error", "error_code"):
                    add(_string(value))
    return out


def live_failure_codes() -> dict[str, set]:
    """现取：`app/**/*.py` 里**静态可见**的失败短码 → 出处集合（`文件:行`）。"""
    out: dict[str, set] = {}
    assert AGENT_ROOT.is_dir(), f"读源失效：{AGENT_ROOT} 不存在 ⇒ 本判据会空跑成绿（fail-closed）"
    for path in sorted(AGENT_ROOT.rglob("*.py")):
        rel = str(path.relative_to(AGENT_ROOT))
        try:
            tree = ast.parse(path.read_text(encoding="utf8"))
        except SyntaxError as exc:  # 语法错 = 读源坏了，不许静默跳过
            raise AssertionError(f"{rel} 解析失败 ⇒ 失败码码集不完整：{exc}") from exc
        for code in _codes_in(tree):
            out.setdefault(code, set()).add(rel)
    assert out, "现取失败码为 0 ⇒ 读源坏了（判据会空跑）"
    return out


class Row:
    """登记表的一行（AST 现取：`Remedy(...)` 的关键字实参）。"""

    def __init__(self, code, reason, remedy, entry="", scope="", retry=None,
                 lineno=0, where=""):
        self.code = code
        self.reason = reason
        self.remedy = remedy
        self.entry = entry
        self.scope = scope
        self.retry = retry
        self.lineno = lineno
        self.where = where

    @property
    def key(self) -> str:
        return f"{self.code}@{self.scope}" if self.scope else (self.code or "<默认>")

    @property
    def text(self) -> str:
        return f"{self.reason}。{self.remedy}"

    def replaced(self, **changes) -> "Row":
        merged = dict(code=self.code, reason=self.reason, remedy=self.remedy, entry=self.entry,
                      scope=self.scope, retry=self.retry, lineno=self.lineno, where=self.where)
        merged.update(changes)
        return Row(**merged)


def registry_source(sources: dict[str, str] | None = None) -> str:
    src = (sources or {}).get(REGISTRY_SURFACE)
    if src is not None:
        return src
    assert REGISTRY_PATH.exists(), (
        f"登记表 `{REGISTRY_PATH.relative_to(REPO_ROOT)}` 不存在 ⇒ 族 6 的登记面为空（fail-closed）。{REPRO}"
    )
    return REGISTRY_PATH.read_text(encoding="utf8")


def registry_rows(sources: dict[str, str] | None = None) -> list[Row]:
    """现取登记表全部行（含 `DEFAULT_REMEDY` —— 它的 `code` 是空串，是未登记码的唯一出口）。"""
    rows: list[Row] = []
    for node in ast.walk(ast.parse(registry_source(sources))):
        if not isinstance(node, ast.Call):
            continue
        called = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if called != "Remedy":
            continue
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        retry = kw.get("retry")
        rows.append(Row(
            code=_string(kw["code"]) if "code" in kw else None,
            reason=_string(kw["reason"]) if "reason" in kw else None,
            remedy=_string(kw["remedy"]) if "remedy" in kw else None,
            entry=(_string(kw["entry"]) if "entry" in kw else "") or "",
            scope=(_string(kw["scope"]) if "scope" in kw else "") or "",
            # ⚠️ **缺席 = False = 不可重试**（fail-safe 方向，与运行期 `Remedy.retry` 的缺省同向）
            # ⇒ 只有「声明可重试」才需要显式写 `retry=True`，而它正是被校验的那条声明。
            retry=bool(retry.value) if isinstance(retry, ast.Constant) else False,
            lineno=node.lineno,
            where=f"{REGISTRY_PATH.name}:{node.lineno}",
        ))
    assert rows, (
        "登记表现取 0 行 ⇒ 判据会空跑成绿；要么表被清空，要么 `Remedy(...)` 的构造形态变了"
        f"（本判据按关键字实参取值）。{REPRO}"
    )
    return rows


def named_rows(rows: list[Row]) -> list[Row]:
    return [r for r in rows if r.code]


def default_row(rows: list[Row]) -> Row:
    """默认话术行（`code` 为空串）—— 未登记码的出口，必须**恰好一条**。"""
    found = [r for r in rows if r.code == ""]
    assert len(found) == 1, (
        f"默认话术行必须**恰好一条**（现取 {len(found)} 条）—— 0 条 ⇒ 未登记码没有任何话术（静默裸奔）；"
        f"多条 ⇒ 两个真相源。「未登记 ⇒ 有默认话术」就靠它。{REPRO}"
    )
    row = found[0]
    assert row.reason and row.remedy, (
        f"{row.where} 默认话术的 reason / remedy 不得为空 —— 空话术比「未知错误」更糟（用户什么都看不到）。"
    )
    return row


# ── 单一真相源（现取）：非重试码集 / 工具幂等标注 / 工具词汇 / 页面词汇 ────────


def non_retryable_codes() -> set:
    """`app/tools/base.py::NON_RETRYABLE_ERROR_CODES` ——**既有单一口径**，不另立清单。"""
    tree = ast.parse((AGENT_ROOT / "tools" / "base.py").read_text(encoding="utf8"))
    out: set = set()
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "NON_RETRYABLE_ERROR_CODES"):
            # 右值是 `frozenset({...})` ⇒ 必须走 `_literal_codes` 拆包装（`ast.literal_eval` 不认它）
            out |= _literal_codes(node.value)
    assert out, "取不到 NON_RETRYABLE_ERROR_CODES ⇒ 重试面判据会空跑（fail-closed）"
    return out


def idempotent_tools() -> dict[str, bool]:
    """工具类声明里的 `idempotent`（`BaseTool` 缺省 True）——**既有单一口径**，不另立清单。"""
    out: dict[str, bool] = {}
    for path in sorted((AGENT_ROOT / "tools").glob("*.py")):
        if path.name in ("__init__.py", "base.py", "registry.py", "langchain_adapter.py"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf8"))):
            if not isinstance(node, ast.ClassDef):
                continue
            name, idem = None, None
            for st in node.body:
                if not (isinstance(st, ast.Assign) and len(st.targets) == 1
                        and isinstance(st.targets[0], ast.Name)):
                    continue
                if st.targets[0].id == "name":
                    name = _string(st.value)
                elif st.targets[0].id == "idempotent" and isinstance(st.value, ast.Constant):
                    idem = bool(st.value.value)
            if isinstance(name, str):
                out[name] = True if idem is None else idem
    assert out, "取不到任何工具类 ⇒ 幂等口径判据会空跑（fail-closed）"
    return out


def page_labels() -> frozenset:
    """真实侧边栏**页面**（菜单项 ∪ 独立项）—— 复用菜单三源同构守卫的解析函数，不另立第二套。

    ⚠️ issue #5454 修：原实现只取 `_parse_frontend` 的**组内项**，漏掉 `standaloneItems`
    （`Sidebar.tsx` 渲染的是两者之和）⇒ 「通知中心」这类独立项被判「不在侧边栏」（**假红**）。
    真值源缺项会让判据把**正确**话术判红，与射程不足同样有害。
    """
    src = menu.MENU_TS.read_text(encoding="utf8")
    groups = menu._parse_frontend(src)
    out = {name for _key, _group, items in groups for name in items}
    out |= set(menu._parse_standalone(src))
    assert out, "侧边栏菜单项解析为 0 ⇒ 页面入口判据会空跑（fail-closed）"
    return frozenset(out)


def derived_retry(code: str, scope: str) -> bool:
    """**推导**可重试性（不读表）：取不到证据一律不可重试（与 `base_skill` 的 fail-safe 同向）。"""
    if code in non_retryable_codes():
        return False
    return bool(scope) and idempotent_tools().get(scope, False)


# ══════════════════════════════════════════════════════════════════════════════
# 一·B、**存量**页面指针面（issue #5454）：既有话术点名的后台入口必须真实存在
# ══════════════════════════════════════════════════════════════════════════════
#
# 为什么必须补这一段：上面的 `entry_problems` 已经落了「话术里点名的入口必须存在」这条口径，
# 但它的射程**只覆盖族 6 自己那张新增的表**（`registry_rows()`）。**既有**文本 ——
# 工具 description、references/prompts、skills 自述、`app/tools/base.py::_denial_suggestion`
# 的运行期话术、`app/graph/skills/base_skill.py` 注入 system prompt 的权限范围段 ——
# **从未被核过**，而它们恰恰是「用户照着找不到入口」的现场（§23 G5：扩面时存量逐条处置）。
#
# 判据本体**复用**：真值源 = 上方的 `page_labels()` / `sidebar_nodes()`（`menu.ts` 是唯一真值源）；
# 口径 = 同一条「点名的入口必须真实存在」。**不另立第二套页面词汇、不另写扫描器**。

AGENT_SERVICE_ROOT = REPO_ROOT / "backend" / "ai-agent-service"

#: 指向后台页面的**文风锚点**（由本仓既有话术反推，不是凭空发明）：
#: ① 前面紧邻导航词 —— `商户后台「通知中心」页`；
#: ② 后面紧邻页面词 —— `「商品管理 → 分类」页面` / `「岗位权限」中开通`；
#: ③ `「A」或「B」` / `「A」/「B」` 并列的备选入口 —— 同一「去哪一页」槽位的同位语，
#:    一侧是指针 ⇒ 另一侧同属指针（`「员工管理 → 编辑员工 → 权限」或「角色管理 → 岗位权限」`）。
#: ⚠️ `入口` **有意不入锚点**：`「订单列表」页(/orders)的「新建订单」入口` 里的后一个是**页内按钮**，
#:    不是侧边栏节点 —— 把它算进来就是把正确文风喂红（§17.3「判据被自己的文案喂红」）。
_NAV_BEFORE = re.compile(r"(?:后台|侧边栏|菜单|导航)[（(：:，,\s]*$")
_NAV_AFTER = re.compile(r"^(?:(?:页|页面|节点)|(?:中)?开通)")
_POINTER = re.compile(r"「([^」]{1,24})」")
_POINTER_PAIR = re.compile(r"「([^」]{1,24})」\s*[或/]\s*「([^」]{1,24})」")

#: 显式不判表（**只许缩短**）：与 admin-web 侧边栏无关的页面指针。每条必须带理由。
LEGACY_POINTER_EXEMPTIONS: tuple[str, ...] = (
    "app/api/products.py::「我的」",      # C 端小程序「我的」页（小布面）—— 不在 admin-web 侧边栏
    "app/api/internal.py::「应做数量」",  # 看板**字段名**，不是页面入口
)
#: 冻结账户：条数**现取**比对，涨跌都红（与 `dead_object_ledger.json` 的 `anchor.not_judged` 同纪律）。
LEGACY_POINTER_EXEMPTION_COUNT = 2


def sidebar_nodes() -> frozenset:
    """真实侧边栏的**可导航节点** = 分组名 ∪ 页面（菜单项 ∪ 独立项）。

    为什么分组名也算（issue #5454）：`「组织管理 → 岗位权限」` 是**组 → 项**的真实导航路径
    （#5271 后侧边栏就是七大组 + 组内项）。只认页面会把这条**正确**指路判红 ⇒ 假红。
    """
    src = menu.MENU_TS.read_text(encoding="utf8")
    out = {name for _key, name, _items in menu._parse_frontend(src)} | set(page_labels())
    out |= set(menu._parse_standalone(src))
    assert out, "侧边栏可导航节点解析为 0 ⇒ 页面指针判据会空跑（fail-closed）"
    return frozenset(out)


def page_pointers(text: str) -> list[tuple[str, str]]:
    """抽出文本里的**页面指针** → `[(完整 token, 首级名)]`。

    **只看首级**：`「员工管理 → 编辑员工 → 权限」` 的后两级是**页内步骤**（编辑对话框里的权限栏），
    侧边栏可达性只取决于首级 —— 判据**不假装**能判页内步骤是否存在（见文末「未固化」）。
    """
    marks = list(_POINTER.finditer(text))
    judged: dict[int, bool] = {}
    for m in marks:
        judged[m.start()] = bool(_NAV_BEFORE.search(text[:m.start()])
                                 or _NAV_AFTER.match(text[m.end():]))
    for pair in _POINTER_PAIR.finditer(text):
        left = text.index(f"「{pair.group(1)}」", pair.start())
        right = text.index(f"「{pair.group(2)}」", pair.start())
        if judged.get(left) or judged.get(right):
            judged[left] = judged[right] = True
    return [(m.group(1), m.group(1).split("→")[0].strip()) for m in marks if judged.get(m.start())]


def legacy_pointer_texts(sources: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """现取**存量**页面指针语料 = 模型可见文本面 ∪ `app/**/*.py` 的字符串字面量。

    两处都要，各补一半：
      · **模型可见文本面**（`dc.Scan._surfaces`）= 已登记读源（工具 description / 参数 description /
        运行期 suggestion·message / references·prompts / skill 自述 / agent 直答 / 族 6 登记表）；
      · **`app/**/*.py` 的字面量** = 补上读源里**没有**的那两处模型可见文本 ——
        `app/tools/base.py::_denial_suggestion`（运行期按码回灌的话术）与
        `app/graph/skills/base_skill.py`（注入 system prompt 的权限范围段）。
        它们正是本单立案时点名「从未被核过」的那几处（**新增声明面 ⇒ 同批登记进读源**）。
    """
    src = sources if sources is not None else dc.surface_sources()
    out: list[tuple[str, str]] = []
    for surface, _allowed, text, _kind in dc.Scan(src, dc.ledger())._surfaces(src):
        if text:
            out.append((surface, text))
    for path in sorted((AGENT_SERVICE_ROOT / "app").rglob("*.py")):
        rel = path.relative_to(AGENT_SERVICE_ROOT)
        try:
            tree = ast.parse(path.read_text(encoding="utf8"))
        except SyntaxError as exc:  # 语法错 = 读源坏了，不许静默跳过
            raise AssertionError(f"{rel} 解析失败 ⇒ 存量指针语料不完整：{exc}") from exc
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                out.append((f"{rel}:{node.lineno}", node.value))
    assert out, "存量指针语料取空 ⇒ 判据会空跑成绿（fail-closed）"
    return out


def _pointer_site(where: str) -> str:
    """指针站点的稳定键：字面量键去掉末尾的行号后缀，面键（`ref:` / `tool:` / `sugg:` 等）原样。"""
    return re.sub(r":\d+$", "", where)


def legacy_pointer_problems(texts: list[tuple[str, str]] | None = None) -> list[str]:
    """存量页面指针面：**首级必须能在真实侧边栏里找到**（找不到 ⇒ 用户按话术找不到入口）。"""
    nodes = sidebar_nodes()
    problems: list[str] = []
    for where, text in (texts if texts is not None else legacy_pointer_texts()):
        for token, first in page_pointers(text):
            if first in nodes:
                continue
            if f"{_pointer_site(where)}::「{token}」" in LEGACY_POINTER_EXEMPTIONS:
                continue
            problems.append(
                f"{where} 把用户指向「{token}」，但首级「{first}」**不在真实侧边栏里**"
                f" ⇒ 用户照着找不到入口（话术比不说更糟）。真实可导航节点："
                f"{'、'.join(sorted(nodes))}。"
            )
    return problems


# ══════════════════════════════════════════════════════════════════════════════
# 二、判据
# ══════════════════════════════════════════════════════════════════════════════


def problems_registration(face: dict, rows: list[Row], ledger: dict) -> list[str]:
    """登记面：现取码集必须「有行」或「在燃尽账户里」；账户逐值相等（涨跌都红）。"""
    registered = {r.code for r in named_rows(rows) if not r.scope}
    awaiting = set(ledger.get("awaiting_rows") or [])
    problems: list[str] = []
    unknown = sorted(registered - set(face))
    if unknown:
        problems.append(
            "登记表里有**现取码集里不存在**的行：" + ", ".join(unknown)
            + " ⇒ 码写错了（拼写/大小写），或它已经不是短码形态。"
        )
    unaccounted = sorted(set(face) - registered - awaiting)
    if unaccounted:
        problems.append(
            "以下失败码**既没有登记行、也不在燃尽账户里**（用户会看到默认话术，而它未必贴切）：\n"
            + "\n".join(f"  - {c}（出处：{', '.join(sorted(face[c]))}）" for c in unaccounted)
            + "\n修法（二选一）：① 在登记表补一行 `Remedy(code=..., reason=..., remedy=...)`（首选）；"
              "② 确属低优先 ⇒ 同 PR 显式写进 `remedy_registry_ledger.json` 的 `awaiting_rows`"
              "（登记 = **可见欠账**，不是豁免）。"
        )
    stale = sorted(awaiting - (set(face) - registered))
    if stale:
        problems.append(
            "燃尽账户 `awaiting_rows` 里的条目**已经不需要了**（该码已登记，或已不在码集里）："
            + ", ".join(stale)
            + " ⇒ 账户**只许缩短**：修好一条必须同 PR 删除对应条目（陈旧条目会让账户变成永久豁免）。"
        )
    return problems


def problems_retry(rows: list[Row]) -> list[str]:
    """重试面：`retry=` 声明必须与**现取推导**一致；不可重试 ⇒ 话术不得出现重试字样。"""
    problems: list[str] = []
    for row in named_rows(rows):
        want = derived_retry(row.code, row.scope)
        if row.retry and not want:
            why = ("失败码 ∈ NON_RETRYABLE_ERROR_CODES"
                   if row.code in non_retryable_codes()
                   else (f"操作 `{row.scope}` 非幂等（idempotent=False）" if row.scope
                         else "没有点名任何**已证明幂等**的操作"))
            problems.append(
                f"{row.where}（{row.key}）声明 `retry=True`，但现取推导为**不可重试**（{why}）"
                f" ⇒ 该声明与既有单一口径冲突（「可重试」不许在这里变成第三个真相源）。"
            )
        if not row.retry:
            hit = [m for m in RETRY_MARKERS if m in row.text]
            if hit:
                problems.append(
                    f"{row.where}（{row.key}）是**不可重试**的一条，但话术里出现了重试字样 {hit}：\n"
                    f"      {row.text}\n"
                    f"      ⇒ 用户按提示重来一次就是**重复写入**（下单/支付/批量写这类幂等性不成立的"
                    f"操作绝不能建议重试）。"
                )
    return problems


def entry_problems(row: Row, tools: frozenset, labels: frozenset,
                   dead_tools: frozenset) -> list[str]:
    """引用面：声明的入口必须存在；话术里点名的入口必须被声明（否则永久免检）。"""
    problems: list[str] = []
    entry = row.entry or ""
    if entry.startswith("tool:"):
        name = entry[len("tool:"):]
        if name not in tools:
            problems.append(
                f"{row.where}（{row.key}）声明的工具入口 `{name}` **不存在于工具词汇表**"
                f" ⇒ 补救路径不可达（按它去调必然撞 tool_not_found）。"
            )
        elif name in dead_tools:
            problems.append(
                f"{row.where}（{row.key}）声明的工具入口 `{name}` **全局不可达**（不被任何 skill 绑定）"
                f" —— 引用面判据 `problems_dead_refs` 同批会红。"
            )
    elif entry.startswith("page:"):
        label = entry[len("page:"):]
        if label not in labels:
            problems.append(
                f"{row.where}（{row.key}）声明的页面入口「{label}」**不在真实侧边栏菜单项里**"
                f" ⇒ 用户照着找找不到（真实菜单项：{'、'.join(sorted(labels))}）。"
            )
    elif entry:
        problems.append(f"{row.where}（{row.key}）的 `entry={entry!r}` 形态非法 —— "
                        f"只认 `tool:<工具名>` / `page:<菜单项名>` / `\"\"`（无入口）。")
    declared = {entry} if entry else set()
    mentioned = [f"tool:{t}" for t in sorted(tools)
                 if len(t) >= MIN_TOOL_NAME_LEN
                 and re.search(rf"(?<![A-Za-z0-9_]){re.escape(t)}(?![A-Za-z0-9_])", row.text)]
    mentioned += [f"page:{label}" for label in sorted(labels) if label in row.text]
    undeclared = sorted(set(mentioned) - declared)
    if undeclared:
        problems.append(
            f"{row.where}（{row.key}）话术里点名了入口 {undeclared}，但**没有**在 `entry=` 里声明"
            f" ⇒ 该入口落在判定面之外（永远不会被判「不可达」）= 永久免检（§23 G5）。"
        )
    return problems


def problems_text(row: Row) -> list[str]:
    """文本面：用户可见文本必须纯中文（低学历用户约定）+ 无归因形态。"""
    problems: list[str] = []
    if row.reason is None or row.remedy is None:
        problems.append(f"{row.where}（{row.key}）reason / remedy **取不到静态文本** ⇒ 本判据会对它空跑"
                        f"（写法必须是字面量或隐式拼接）。")
        return problems
    for field, value in (("reason", row.reason), ("remedy", row.remedy)):
        letters = sorted({ch for ch in value if ch.isascii() and ch.isalpha()})
        if letters:
            problems.append(
                f"{row.where}（{row.key}）的 `{field}` 含 ASCII 字母 {letters} ⇒ 不是纯中文短句"
                f"（面向低学历用户的既有约定）：{value}\n"
                f"      ASCII 字母正是**短码 / 工具名 / 异常原文**的形态 ⇒ 这一条同时守住"
                f"「用户可见文本 ≠ 归因」的边界（`app/utils/error_incident.py`）。"
            )
        hit = [m for m in FORBIDDEN_TEXT if m in value]
        if hit:
            problems.append(f"{row.where}（{row.key}）的 `{field}` 含归因/兜底形态 {hit}：{value}")
    return problems


def all_problems(sources: dict[str, str] | None = None, rows: list[Row] | None = None,
                 face: dict | None = None, ledger: dict | None = None) -> list[str]:
    """全部判据的合成入口（注入式红证 = 换掉其中任一项后重建读数，不缓存）。"""
    src = sources if sources is not None else dc.surface_sources()
    rows = rows if rows is not None else registry_rows(src)
    ledger = ledger if ledger is not None else load_ledger()
    face = face if face is not None else live_failure_codes()
    tools, labels = dc.tool_vocab(src), page_labels()
    dead = dc.Scan(src, dc.ledger()).dead_tools
    problems = list(problems_registration(face, rows, ledger)) + problems_retry(rows)
    for row in rows:
        problems += entry_problems(row, tools, labels, dead)
        problems += problems_text(row)
    return problems


def load_ledger() -> dict:
    assert LEDGER_PATH.exists(), (
        f"缺 `{LEDGER_PATH.name}` ⇒ 燃尽账户没有载体（未登记码会静默走默认话术、没人知道欠了多少）。{REPRO}"
    )
    data = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{LEDGER_PATH.name} 必须是 JSON 对象"
    assert "awaiting_rows" in data, f"{LEDGER_PATH.name} 缺 `awaiting_rows`（冻结账户，**只许缩短**）"
    return data


# ── 常驻断言 ────────────────────────────────────────────────────────────────


def test_registry_is_consumed() -> None:
    """登记表必须是**活的**（有运行时消费方）—— 一张没人读的表等于死代码。"""
    src = CONSUMER_PATH.read_text(encoding="utf8")
    assert "remedy_for(" in src, (
        f"{CONSUMER_PATH.relative_to(REPO_ROOT)} 没有消费登记表 ⇒ 「失败 → 原因 → 补救」只在表里、"
        f"到不了任何话术面（登记表变成死代码）。{REPRO}"
    )


def test_every_live_failure_code_is_registered_or_accounted() -> None:
    problems = problems_registration(live_failure_codes(), registry_rows(), load_ledger())
    assert not problems, "\n".join(problems) + f"\n{REPRO}"


def test_registry_covers_the_reference_surface_without_dead_refs() -> None:
    """🔴 **复用** #5331 的引用面判据本体（不另立第二套）：登记表文本已在它的射程内。"""
    sources = dc.surface_sources()
    assert REGISTRY_SURFACE in sources, (
        f"登记表**不在** #5331 的判据读源里 ⇒ 它的文本落在判定面之外（永久免检）："
        f"`test_dead_capability_meta_guard.surface_sources()` 必须收录它。{REPRO}"
    )
    texts = dc.remedy_texts(sources)
    assert texts, ("登记表文本现取为 0 ⇒ 引用面判据对它是**空跑**（绿得没有计数）"
                   f"—— `dc.remedy_texts()` 取不到 `Remedy(...)` 的 reason/remedy。{REPRO}")
    problems = dc.problems_dead_refs(dc.Scan(sources, dc.ledger()))
    assert not problems, "\n".join(problems) + f"\n{REPRO}"


def test_remedy_entries_exist_and_are_declared() -> None:
    tools, labels = dc.tool_vocab(dc.surface_sources()), page_labels()
    dead = dc.Scan(dc.surface_sources(), dc.ledger()).dead_tools
    problems = [p for row in registry_rows() for p in entry_problems(row, tools, labels, dead)]
    assert not problems, "\n".join(problems) + f"\n{REPRO}"


def test_default_wording_is_not_unknown_error() -> None:
    """判据 1 的括号：**未登记 ⇒ 有默认话术，但默认话术不得是「未知错误」**。"""
    row = default_row(registry_rows())
    assert row.reason.strip() not in ("", "未知错误", "系统错误", "操作失败"), (
        f"{row.where} 默认话术是「{row.reason}」—— 这类话术对 B 端用户零信息量"
        f"（既不知道为什么、也不知道下一步），正是本族要消灭的形态。{REPRO}"
    )
    assert len(row.remedy.strip()) >= 8, (
        f"{row.where} 默认话术的补救太短（「{row.remedy}」）⇒ 没有给出任何下一步。{REPRO}"
    )
    assert not [m for m in RETRY_MARKERS if m in row.text], (
        f"{row.where} 默认话术含重试字样 —— 默认出口对**未知操作**生效，而下单/付款这类非幂等操作"
        f"就可能走这里 ⇒ 默认话术一律不得建议重试。{REPRO}"
    )


def test_non_retryable_remedies_never_suggest_retry() -> None:
    problems = problems_retry(registry_rows())
    assert not problems, "\n".join(problems) + f"\n{REPRO}"


def test_user_visible_text_is_pure_chinese_without_attribution() -> None:
    """判据 4：用户可见文本不含短码 / 异常原文（沿用 `error_incident.py` 的边界）。"""
    problems = [p for row in registry_rows() for p in problems_text(row)]
    assert not problems, "\n".join(problems) + f"\n{REPRO}"


# ── 存量页面指针面（issue #5454）：既有话术点名的后台入口必须真实存在 ──────────

#: 本单立案时点名的存量站点（**现取必须在面内** —— 抽取规则或读源一旦失灵，这里先红）。
#: 与 `legacy_pointer_problems` 的分工：这条守「**判据有没有看见**」，那条守「看见的都对不对」。
LEGACY_KNOWN_SITES: tuple[tuple[str, str], ...] = (
    ("app/tools/base.py", "员工管理 → 编辑员工 → 权限"),
    ("app/tools/base.py", "组织管理 → 岗位权限"),
    ("app/graph/skills/base_skill.py", "岗位权限"),
    ("ref:base/principles.md", "岗位权限"),
    ("tool:customer_manage", "客户列表"),
    ("sugg:settings_manage", "企业基础信息"),
)
#: 厚度下限（**现取读数**，不是解释性上限）：低于它说明抽取规则或读源坏了 ⇒ 红。
LEGACY_POINTER_FLOOR = 60


def test_legacy_page_pointers_match_the_real_sidebar() -> None:
    """🔴 本单的常驻判据：**既有**话术点名的后台入口必须真实存在（射程覆盖存量，不只新增）。"""
    problems = legacy_pointer_problems()
    assert not problems, "\n".join(problems) + f"\n{REPRO}"


def test_legacy_pointer_face_is_alive_and_printed() -> None:
    """§23 G2/G7：读数**现取打印** + 前置自证（已知站点必须在面内、抽取不得空跑）。"""
    texts = legacy_pointer_texts()
    pointers = [(w, t, f) for w, body in texts for t, f in page_pointers(body)]
    seen = {(_pointer_site(w), t) for w, t, _f in pointers}
    print(f"[#5454 · 存量页面指针面现取] 语料 {len(texts)} 条 / 指针 {len(pointers)} 处 / "
          f"不一致 {len(legacy_pointer_problems(texts))} 处 / 豁免 {len(LEGACY_POINTER_EXEMPTIONS)} 条")
    print("[#5454 · 真实可导航节点] " + "、".join(sorted(sidebar_nodes())))
    missing = sorted(k for k in LEGACY_KNOWN_SITES if k not in seen)
    assert not missing, (
        f"已知存量站点不在被判定面内 {missing} ⇒ 判据对它们**空跑**（绿得没有计数）。"
        f"现取站点键：{sorted(seen)}")
    assert len(pointers) >= LEGACY_POINTER_FLOOR, (
        f"现取指针只有 {len(pointers)} 处（下限 {LEGACY_POINTER_FLOOR}）⇒ 抽取规则或读源坏了"
        f"（fail-closed：宁可红，不许静默空跑成绿）")


def test_legacy_pointer_exemptions_only_shrink() -> None:
    """豁免面**只许缩短**：条数冻结（涨跌都红）+ 每条必须**活着**（陈旧条目同 PR 删掉）。"""
    pointers = [(w, t, f) for w, body in legacy_pointer_texts() for t, f in page_pointers(body)]
    assert len(LEGACY_POINTER_EXEMPTIONS) <= LEGACY_POINTER_EXEMPTION_COUNT, (
        f"显式不判表 **{len(LEGACY_POINTER_EXEMPTIONS)} 条 > 冻结账户 "
        f"{LEGACY_POINTER_EXEMPTION_COUNT}** —— 豁免面只许缩短；确需新增 ⇒ "
        f"同 PR 显式上调本常量并给出理由（一次可评审的动作）。")
    nodes = sidebar_nodes()
    live = {f"{_pointer_site(w)}::「{t}」" for w, t, f in pointers if f not in nodes}
    stale = sorted(k for k in LEGACY_POINTER_EXEMPTIONS if k not in live)
    assert not stale, (
        f"豁免条目已**陈旧**（它指向的指针不再出现，或那处文本已改对）{stale} ⇒ "
        f"同 PR 删掉它（豁免面只许缩短，不许留成解释性上限）。")


def test_legacy_pointer_rule_is_precise() -> None:
    """负控：**页内按钮 / 字段名 / 域术语**不得被判（否则正确文风被整片喂红）+ 真值源正控。"""
    # 正控①：真实**菜单项** ⇒ 判为指针
    assert page_pointers("请让用户通过商户后台「企业基础信息」页查看") == [
        ("企业基础信息", "企业基础信息")]
    # 正控②：**独立项**（`standaloneItems`，`Sidebar.tsx` 渲染它）必须可判 —— 本单修的真值源缺口
    assert "通知中心" in sidebar_nodes()
    assert not legacy_pointer_problems([("注入:正控", "并引导其到商户后台「通知中心」页自助处理")])
    # 正控③：**组名**做首级（`组 → 项` 的真实导航路径）⇒ 一致（只认页面会把正确指路判红）
    assert "组织管理" in sidebar_nodes()
    assert not legacy_pointer_problems([("注入:正控", "引导用户到后台「组织管理 → 岗位权限」页操作")])
    # 负控①：页内按钮（后面是「入口」而不是「页」）⇒ 不入面
    assert page_pointers("请到「订单列表」页(/orders)的「新建订单」入口操作") == [
        ("订单列表", "订单列表")]
    # 负控②：与导航无关的引号词（域术语 / 数据映射）⇒ 不入面
    assert page_pointers("知识单元为「知识卡片」，卡片展示「改前 → 改后」") == []
    assert page_pointers("请到后台「订单列表」页展示「改前 → 改后」") == [("订单列表", "订单列表")]
    # 显式不判表**是活的**（它不是装饰）：两条豁免各自挡住一个真实的非侧边栏指针
    assert page_pointers("商家后台「应做数量」退化成订单数") == [("应做数量", "应做数量")]
    # 行号由变量拼出（引用纪律禁写裸行号）：判据仍需证明「带行号的字面量键」能命中豁免表
    line = 1
    assert not legacy_pointer_problems(
        [(f"app/api/internal.py:{line}", "商家后台「应做数量」退化成订单数")])
    assert not legacy_pointer_problems(
        [(f"app/api/products.py:{line}", "提供对话/「我的」页的数据端点")])


def test_burn_down_anchor_is_printed() -> None:
    """§23 G2：读数**现取打印**，不写死解释性上限。"""
    face, rows, ledger = live_failure_codes(), registry_rows(), load_ledger()
    named = named_rows(rows)
    registered = {r.code for r in named if not r.scope}
    awaiting = set(ledger["awaiting_rows"] or [])
    print("[族 6 · 失败码登记面现取] " + str({
        "现取失败码": len(face),
        "有登记行": len(registered),
        "燃尽账户（走默认话术）": len(awaiting),
        "登记行总数（含操作级）": len(named),
        "可重试行": sum(1 for r in named if r.retry),
    }))
    print("[族 6 · 燃尽账户明细] " + "、".join(sorted(awaiting)))
    print("[族 6 · 引用面登记行] " + str(dc.remedy_texts(dc.surface_sources())))
    anchor = ledger.get("anchor") or {}
    assert (anchor.get("face"), anchor.get("registered"), anchor.get("awaiting")) == (
        len(face), len(registered), len(awaiting)), (
        f"燃尽锚点与现取读数不等（锚点 {anchor.get('face')}/{anchor.get('registered')}/"
        f"{anchor.get('awaiting')}，现取 {len(face)}/{len(registered)}/{len(awaiting)}）"
        f" ⇒ 锚点是**现取打印的冻结读数**，同 PR 一并更新，不许让它腐烂成解释性上限。{REPRO}"
    )
    assert registered | awaiting == set(face), (
        "登记行 ∪ 燃尽账户 ≠ 现取失败码集 ⇒ 有码两头都不占（判据 1 的「每个失败码都有出口」失守）。"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 三、注入式红证（§23 G7：前提自证 —— 注入生效 + 对象真的进了被判定面 + 判据变红）
# ══════════════════════════════════════════════════════════════════════════════

_BASE: dict = {}


def base() -> tuple[dict, list[Row], dict, dict]:
    """基线（进程内缓存；注入式红证都从它出发）。"""
    if not _BASE:
        src = dc.surface_sources()
        _BASE.update(src=src, rows=registry_rows(src), face=live_failure_codes(),
                     ledger=load_ledger(),
                     scan=dc.Scan(src, dc.ledger()))
    return _BASE["src"], _BASE["rows"], _BASE["face"], _BASE["ledger"]


def _pick(rows: list[Row], key: str) -> Row:
    found = [r for r in rows if r.key == key]
    assert len(found) == 1, (
        f"现取行集里没有 `{key}`（或有多条同名）⇒ 红证的注入对象不在被判定面上，红证会是空的。"
        f"现取键集：{sorted(r.key for r in rows)}"
    )
    return found[0]


def _swapped(rows: list[Row], key: str, **changes) -> Row:
    """把 `key` 那一行换成改过的版本，并返回**改过的那一行**（调用方拿它继续断言）。"""
    return _pick(rows, key).replaced(**changes)


def _swap(rows: list[Row], key: str, **changes) -> list[Row]:
    row = _pick(rows, key)
    return [row.replaced(**changes) if r is row else r for r in rows]


def _bump_face(face: dict) -> dict:
    """模拟「工具/技能里新增了一个失败短码」（读源注入的等价复算）。"""
    out = {c: set(v) for c, v in face.items()}
    out["BRAND_NEW_FAILURE_CODE"] = {"注入:1"}
    return out


def test_every_judgement_can_go_red() -> None:
    sources, rows, face, ledger = base()
    assert not all_problems(sources=sources, rows=rows, face=face, ledger=ledger), (
        "基线必须是绿的 —— 否则下面的注入式红证分不清「本来就是红的」和「注入让它红的」。"
    )

    # ① 新增失败码 ⇒ 登记面红（未登记 + 不在燃尽账户里）
    injected_face = _bump_face(face)
    assert set(injected_face) != set(face), "注入没生效"
    problems = problems_registration(injected_face, rows, ledger)
    assert any("BRAND_NEW_FAILURE_CODE" in p for p in problems), (
        "新增失败码没有让登记面变红 ⇒ 判据 1（每个失败码都有出口）失守。"
    )

    # ② 默认话术改成「未知错误」⇒ 默认话术判据红
    bad = _swapped(rows, "<默认>", reason="未知错误")
    assert bad.key == "<默认>" and bad.reason == "未知错误", "注入没进面"
    assert any("未知错误" in p or "零信息量" in p for p in problems_text(bad)), (
        "默认话术被改成「未知错误」却没有变红 ⇒ 判据 1 的括号是空断言。"
    )

    # ③ 🔴 本单任务书点名的注入式红证：把**下单**（非幂等）失败的建议改成「请重试」⇒ 必须变红
    order_key = "tool_execution_failed@order_create"
    _pick(rows, order_key)  # 前提：登记表里确有下单失败行（取不到 ⇒ 直接断言失败）
    poisoned = _swap(rows, order_key, remedy="请重试")
    problems = problems_retry(poisoned)
    assert any(order_key in p and "重试" in p for p in problems), (
        "把下单（`idempotent=False`）失败的建议改成「请重试」**没有**变红"
        " ⇒ 判据 2 是空断言（用户按提示重来一次就是重复下单）。"
    )

    # ④ 把不可重试的行声明成 `retry=True` ⇒ 与既有单一口径冲突（校验的是**声明**，不只是文案）
    lying = _swap(rows, order_key, retry=True)
    assert any("不可重试" in p for p in problems_retry(lying)), (
        "非幂等操作被声明为可重试却没有变红 ⇒ 重试面只校验了文案、没校验声明。"
    )

    # ⑤ 入口不可达：工具不存在 / 工具全局不可达 / 页面不在侧边栏
    tools, labels, dead = dc.tool_vocab(sources), page_labels(), _BASE["scan"].dead_tools
    anchor = _pick(rows, "tool_not_found")
    for entry, needle in (("tool:nonexistent_tool_xyz", "不存在于工具词汇表"),
                          ("tool:order_manage", "全局不可达"),
                          ("page:不存在的页面项", "不在真实侧边栏")):
        problems = entry_problems(anchor.replaced(entry=entry), tools, labels, dead)
        assert any(needle in p for p in problems), f"入口 `{entry}` 没有让引用面变红（期望含「{needle}」）"

    # ⑥ 未声明的入口点名（话术里写了后台菜单项但 `entry=` 没声明）⇒ 红（防「永久免检」）
    label = sorted(labels)[0]
    undeclared = anchor.replaced(entry="", remedy=f"请到「{label}」里处理。")
    problems = entry_problems(undeclared, tools, labels, dead)
    assert any("永久免检" in p for p in problems), (
        "话术点名了入口却没声明 ⇒ 该入口永久免检（§23 G5），判据必须红。"
    )

    # ⑦ 用户可见文本回显短码 / 工具名 ⇒ 文本面红
    assert problems_text(anchor.replaced(remedy="请重试 order_create")), (
        "用户可见文本里出现 ASCII 短码/工具名却没有变红 ⇒ 判据 4 失守。"
    )

    # ⑧ 引用面判据对登记表**有判别力**（前提自证：把**全局不可达工具**写进话术 ⇒ 该判据必红）
    assert "order_manage" in dead, "前提不成立：order_manage 现在可达了 ⇒ 换一个全局不可达工具再注入"
    poisoned_src = dict(sources)
    poisoned_src[REGISTRY_SURFACE] = registry_source(sources).replace(
        "这次没有办成", "这次没有办成（可改用 order_manage 处理）", 1)
    assert poisoned_src[REGISTRY_SURFACE] != registry_source(sources), "注入没生效"
    after = dc.remedy_texts(poisoned_src)
    assert after != dc.remedy_texts(sources) and any("order_manage" in v for v in after.values()), (
        "注入的死工具名没有进到引用面文本里 ⇒ 下面那条红证会是空的"
    )
    assert dc.problems_dead_refs(dc.Scan(poisoned_src, dc.ledger())), (
        "把**全局不可达工具** `order_manage` 写进登记表话术，引用面判据却没有红"
        " ⇒ 判据 3 的复用是空断言（登记表其实不在判据射程内）。"
    )

    # ⑨ 读源被回退（登记表不再被收录）⇒ 复用判据必须红
    stripped = {k: v for k, v in sources.items() if k != REGISTRY_SURFACE}
    assert REGISTRY_SURFACE not in stripped and not dc.remedy_texts(stripped), (
        "读源剔除没生效 ⇒ 这条红证打在空对象上"
    )

    # ⑩ 🔴 **存量**页面指针面（issue #5454）：把一条**既有**话术改成指向不存在的菜单项 ⇒ 必须变红
    texts = legacy_pointer_texts(sources)
    assert not legacy_pointer_problems(texts), (
        "对照组：未注入时存量指针面必须全绿（否则红证无从归因）")
    target = [w for w, _t in texts if w == "tool:role_manage"]
    assert target, "注入对象（`tool:role_manage` 的话术）不在被判定面内 ⇒ 这条红证会是空的"
    poisoned = [(w, t.replace("「组织管理 → 岗位权限」", "「角色管理 → 岗位权限」"))
                for w, t in texts]
    assert poisoned != texts, "注入没生效（锚点失配）—— 同步本判据"
    assert (target[0], "角色管理 → 岗位权限") in {
        (w, tok) for w, t in poisoned for tok, _f in page_pointers(t)}, (
        "注入的假菜单项没有进到被判定面 ⇒ 下面那条断言是空的")
    problems = legacy_pointer_problems(poisoned)
    assert any("「角色管理 → 岗位权限」" in p and "找不到入口" in p for p in problems), (
        "把既有话术改成指向**不存在的菜单项**「角色管理」却没有变红 ⇒ 本判据是空断言"
        "（它只覆盖了新增文本、没有覆盖存量）。")