# case_ids: OR-051, DF-024
"""**同一真值、两个读面，只落了一面** 的类级元守卫（issue #5651 收口）。

## 病根（本单现场，不是推断）

`order_shipment_items`（issue #5648 / PR #5664）是「这一单**实际**发了多少」的**唯一真值载体**，
但落地时**只有工人读面**（`GET /api/worker/shipment/orders/{orderId}`，工人 session 准入）——
admin-web（销售单三联纸跑在那里）**拿不到实发数量**，只能退回订单行的下单数量投影。
issue #5651 把它逐字登记为「**挂链差一步且原因已实测**」，那一版**纯前端**、补不了后端读面。

这类缺陷的形态是**半成品**：真值有了、写面有了、**一个读面**也有了 —— 于是「已经做完了」的
观感成立，而另一个消费面（桌面/纸面）**静默**退回旧口径。它没有任何机械判据能抓：
① 单测只覆盖已落的那一面 ⇒ 全绿；② 前端退回旧字段 ⇒ 类型合法、渲染正常；
③ 于是「账实不符」在纸面上表现为**一个好看的数**。

## 它锁什么（每条判据都可单独变红，红证见 `test_c7_injected_regressions_are_red`）

| # | 判据 | 红证（怎么让它**单独**变红） |
|---|---|---|
| C1 | **真值登记表非空 + 每个声明的文件/符号真实存在**（路径漂移不得静默跳过） | 清空登记表 / 改坏路径 ⇒ 红 |
| C2 | **必需的面必须落，或**显式登记「未落面 + 理由 + 去向」 | 删掉 `faces[admin]` 而不登记 `pending_faces` ⇒ 红 |
| C3 | **陈旧登记反向判**：已落的 face 不得仍挂在「未落」清单里（防「缺面」变永久标签） | 已落 admin 仍写进 `pending_faces` ⇒ 红 |
| C4 | **单一投影**：真值的**视图键字面量**在 Java 主源里**恰好出现在一个文件**（= owner） | 在 controller / DTO 里再拼一份同名键 ⇒ 红 |
| C5 | **两面同源**：每个面的 controller 都调用**同一个** owner 方法；管理面必须挂 `@RequirePermission` | 让 controller 自己拼字段（不再调 owner）/ 删掉注解 ⇒ 红 |
| C6 | **前端消费正确的面 + 缺值不填 0**：桌面端只许走 admin 面（调工人面必 401）；受管消费方里禁止 | 让 `api.ts` 改调 `/api/worker/shipment` / 在数量列写 `?? 0` ⇒ 红 |
|   | 「数值补位成 0」的渲染形态（`0` = 「实发为零」，与「没有这个数」是两件事） |  |
| C7 | 注入式红证 + **内容指纹**自证（禁 mtime / size，issue #4260） | 注入未生效 ⇒ 红（红证自己是空断言） |

## 为什么判据写在**登记表**上而不是写死 `order_shipments`

写死一个实体 = 只修了这一个实例（§23 G1：修一处 = 没修）。登记表把「这个真值有几个面」变成
**必须显式回答的问题**：新真值只落一面而不登记 ⇒ C2 红；面补齐了不销账 ⇒ C3 红；
谁再拼一份同名视图键 ⇒ C4 红。三条合起来才是「同类进不来」。

⚠️ **判据按仓内**原文**判定，但只认结构化锚点**（路径字面量 / 方法调用 / 视图键字面量）：
本仓反复踩过「把注释里的反例读成代码」（`migao-dev-flow` §23.4 T2），故本文件对注释的处理是
**只读结构化锚点、不做全文语义判断**；被守卫的 Java 文件里出现的同类字样都在注释里带 `{@code }`
包裹，而判据锚点是**带引号的字面量**（`"shipped_quantity"` / `"/api/..."`）⇒ 注释里的散文喂不动判据。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
JAVA_MAIN = REPO_ROOT / "backend/admin-api/src/main/java"
ADMIN_WEB_SRC = REPO_ROOT / "frontend/admin-web/src"
CONSUMER_DIRS = ("src",)
_TS_SUFFIXES = (".ts", ".tsx")


@dataclass(frozen=True)
class Face:
    """一个**读面**：谁承载（controller）+ 路径（类级 + 方法级）+ 准入（谁到得了）。"""

    controller: str
    class_path: str
    method_path: str
    access: str

    @property
    def full_path(self) -> str:
        return f"{self.class_path}{self.method_path}"


@dataclass(frozen=True)
class TruthSpec:
    """一个**真值载体**的登记面：owner 是谁、必须落哪些面、谁在消费。"""

    what: str
    owner: str
    owner_method: str
    view_key: str
    required_faces: tuple[str, ...]
    faces: dict[str, Face]
    pending_faces: dict[str, str]
    consumers: tuple[tuple[str, str], ...]
    api_client: str
    api_method: str
    api_path_template: str
    #: 「缺值补位成 0」判据的**射程**：真正**渲染这个真值**的文件（取数页只负责传递，
    #: 它自己的金额格式化属于另一份真值 —— 判据不许跨界归因，否则红得不是地方）
    zero_fill_scope: tuple[str, ...] = ()
    forbidden_api_prefixes: tuple[str, ...] = ()


#: 🔴 **真值载体登记表**（键 = 表名）。新增一个「多面真值」必须在这里回答：
#: 它有几个面、每个面谁承载、还没落的面**为什么**没落 + 去向。
TRUTH_SURFACES: dict[str, TruthSpec] = {
    "order_shipment_items": TruthSpec(
        what="发货明细（这一单**实际**发了多少：实发套 / 件 / 卷）",
        owner="backend/admin-api/src/main/java/com/migao/admin/service/OrderShipmentService.java",
        owner_method="readShipment",
        #: 该真值在响应里的视图键（**恰好一处**：owner 的 itemView 拼装点）
        view_key='"shipped_quantity"',
        required_faces=("worker", "admin"),
        faces={
            "worker": Face(
                controller="backend/admin-api/src/main/java/com/migao/admin/controller/WorkerShipmentController.java",
                class_path="/api/worker/shipment",
                method_path="/orders/{orderId}",
                access="工人 session（X-Worker-Session-Id；工人 permissions=[]，不挂商家权限码）",
            ),
            "admin": Face(
                controller="backend/admin-api/src/main/java/com/migao/admin/controller/OrderController.java",
                class_path="/api/admin/orders",
                method_path="/{id:[0-9a-fA-F-]+}/shipments",
                access="商家 session（/api/admin/** 门禁；权限码 order:list，与同页详情读面同码）",
            ),
        },
        #: 空 = 两面齐活（issue #5651 收口后）。**再有未落面必须写在这里**（理由 + 去向）。
        pending_faces={},
        consumers=(
            ("frontend/admin-web/src/components/orders/SalesDoc.tsx", "resolveSalesQuantity"),
            ("frontend/admin-web/src/app/(dashboard)/orders/[id]/OrderDetail.tsx", "getOrderShipments"),
        ),
        api_client="frontend/admin-web/src/lib/api.ts",
        api_method="getOrderShipments",
        api_path_template="/api/admin/orders/${id}/shipments",
        #: 渲染实发/数量的两个文件（判据射程；取数页 OrderDetail.tsx 不在射程内）
        zero_fill_scope=(
            "frontend/admin-web/src/components/orders/SalesDoc.tsx",
            "frontend/admin-web/src/lib/sales-shipment.ts",
        ),
        #: 桌面端**到不了**工人面（工人面要工人 session）⇒ 前端出现它就是"接错面"
        forbidden_api_prefixes=("/api/worker/shipment",),
    ),
}

#: 「缺值被显示成 0」的**渲染形态**（受管消费方里禁止）：`0` 会被读成「实发为零」，
#: 而「没有这个数」是另一件事（issue #5651 硬约束；同族：缺口金额栏标「未采集」而非 `0.00`）。
#: 只认「直接进格式化 / 直接进 JSX 表达式」的补位 —— 累加器（`sum + (x ?? 0)`）不在此列
#: （那是算术的中性元，不是渲染）。
_ZERO_FILL_PATTERNS: tuple[tuple[str, str], ...] = (
    ("格式化补位", r"(?:\?\?|\|\|)\s*0\s*\)\s*\.\s*(?:toLocaleString|toFixed)\b"),
    ("字符串化补位", r"String\(\s*[\w$.\[\]'\"?]+\s*(?:\?\?|\|\|)\s*0\s*\)"),
    ("JSX 渲染补位", r"\{\s*[\w$.\[\]'\"?]+\s*(?:\?\?|\|\|)\s*0\s*\}"),
)

#: `@RequirePermission("…")` —— 管理面方法必须带（值本身由 Java 判据钉住）
_ANNOTATION_RE = re.compile(r"@RequirePermission\s*\(\s*\"([^\"]+)\"\s*\)")
#: 面声明里「未落」的条目必须写清去向（这条最容易被糊过去）
_PENDING_MUST_MENTION = ("去向", "#")


def _read(rel: str) -> str:
    """读一个受管文件；**不存在 ⇒ 直接失败**（路径漂移不得退化成静默跳过 = 空跑通过）。"""
    path = REPO_ROOT / rel
    if not path.is_file():
        raise AssertionError(f"受管文件不存在：{rel} —— 路径漂移 / 文件被删 ⇒ 红（**不得**静默跳过）")
    return path.read_text(encoding="utf-8")


def _java_sources() -> dict[str, str]:
    """`backend/admin-api/src/main/java/**/*.java` 全文（真值键的普查面）。"""
    return {
        str(p.relative_to(REPO_ROOT)): p.read_text(encoding="utf-8")
        for p in sorted(JAVA_MAIN.rglob("*.java"))
    }


def _strip_comments(src: str) -> str:
    """剥掉 `//` 与 `/* */` 注释（**字符串字面量内的不剥**）。

    为什么必须有它（`migao-dev-flow` §23.4 T2 的实测形态）：本单的**文案本身**要解释
    「桌面端不许调 `/api/worker/shipment`」「缺值不许写 `?? 0`」—— 这些反例**写在注释里**，
    按原文做文本匹配会把解释性注释判成违规（**被自己的文案喂红**）。
    （与 `test_print_media_matrix_guard.py` 的同类实现各自独立：共享实现会引入「谁先 import 谁生效」
    的隐式耦合。）
    """
    out: list[str] = []
    i, n = 0, len(src)
    quote: str | None = None
    while i < n:
        ch = src[i]
        if quote is not None:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(src[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _frontend_sources() -> dict[str, str]:
    """`frontend/admin-web/src/**` 的 TS/TSX（前端消费面的普查面；**已剥注释**）。

    剥注释的理由见 {@link _strip_comments}：本仓的守卫文案天然要引用反例路径/反例写法，
    按原文判定 = 判据被自己的文档喂红。
    """
    files: dict[str, str] = {}
    for suffix in _TS_SUFFIXES:
        for p in sorted(ADMIN_WEB_SRC.rglob(f"*{suffix}")):
            files[str(p.relative_to(REPO_ROOT))] = _strip_comments(p.read_text(encoding="utf-8"))
    return files


# ── 判据本体（纯函数，便于注入式红证）─────────────────────────────────────────

def _face_problems(surfaces: dict[str, TruthSpec], java: dict[str, str] | None = None) -> list[str]:
    """C1/C2/C3/C5：登记表自身成立（真值有面、未落面显式登记、面真的落在声明的地方）。

    `java` 非空 = 用**给定的源码映射**判定（注入式红证要往内存里注坏形态，不碰工作区）。
    """
    problems: list[str] = []
    if not surfaces:
        return ["真值登记表为空 ⇒ 本守卫会**空跑通过**（判据必须能判红）"]

    def source(rel: str) -> str:
        if java is None:
            return _read(rel)
        if rel not in java:
            raise AssertionError(f"受管文件不在给定的源码面里：{rel} ⇒ 判据无从判定（红）")
        return java[rel]

    for key, spec in sorted(surfaces.items()):
        try:
            controller_cache: dict[str, str] = {}
            owner_src = source(spec.owner)
            if f"{spec.owner_method}(" not in owner_src:
                problems.append(f"{key}: owner 方法 `{spec.owner_method}` 不在 {spec.owner} 里（owner 声明漂移）")
            if not spec.required_faces:
                problems.append(f"{key}: `required_faces` 为空 —— 「这个真值该有几个面」没有回答")
            for face_name in spec.required_faces:
                if face_name in spec.faces:
                    face = spec.faces[face_name]
                    src = controller_cache.setdefault(face.controller, source(face.controller))
                    if face.class_path not in src:
                        problems.append(
                            f"{key}/{face_name}: controller 里找不到类级路径 `{face.class_path}`（{face.controller}）")
                    if face.method_path not in src:
                        problems.append(
                            f"{key}/{face_name}: controller 里找不到方法路径 `{face.method_path}`（{face.controller}）")
                    if f"{spec.owner_method}(" not in src:
                        problems.append(
                            f"{key}/{face_name}: {face.controller} 没有调用 owner 方法 "
                            f"`{spec.owner_method}(` ⇒ 这一面可能自拼了第二份投影（两面必须同源）")
                    if face_name == "admin" and not _admin_method_has_annotation(src, face.method_path):
                        problems.append(
                            f"{key}/{face_name}: 管理面方法 `{face.method_path}` 上找不到 `@RequirePermission` "
                            "（漏注解 = 任何登录用户都能读；权限对账守卫也会判红）")
                elif face_name not in spec.pending_faces:
                    problems.append(
                        f"{key}/{face_name}: 必需的面**没有落**，也没有登记在 `pending_faces` 里 —— "
                        "这正是 issue #5651 的「只落一面」形态（半成品不会自己出声）")
            # C3：已落的 face 不得仍挂在「未落」清单里
            for face_name in sorted(spec.pending_faces):
                if face_name in spec.faces:
                    problems.append(
                        f"{key}/{face_name}: 已在 `faces` 里落地，却仍登记在 `pending_faces` ⇒ "
                        "陈旧登记（「缺面」会退化成永久标签）—— 补齐后必须销账")
                detail = spec.pending_faces[face_name]
                if not any(token in detail for token in _PENDING_MUST_MENTION):
                    problems.append(
                        f"{key}/{face_name}: `pending_faces` 的理由必须写清**去向**（含 issue 号）：{detail!r}")
        except AssertionError as exc:  # 文件不存在
            problems.append(f"{key}: {exc}")
    return problems


def _admin_method_has_annotation(src: str, method_path: str) -> bool:
    """方法路径所在行的**上方 6 行内**必须有一条 `@RequirePermission("…")`。"""
    lines = src.splitlines()
    for idx, line in enumerate(lines):
        if method_path in line:
            window = lines[max(0, idx - 6): idx + 1]
            if any(_ANNOTATION_RE.search(candidate) for candidate in window):
                return True
    return False


def _single_projection_problems(surfaces: dict[str, TruthSpec], java: dict[str, str]) -> list[str]:
    """C4：真值的视图键字面量在 Java 主源里**恰好命中 owner 一个文件**。"""
    problems: list[str] = []
    for key, spec in sorted(surfaces.items()):
        hits = sorted(rel for rel, src in java.items() if spec.view_key in src)
        if hits != [spec.owner]:
            problems.append(
                f"{key}: 视图键 {spec.view_key} 在 Java 主源里命中 {len(hits)} 个文件 {hits}"
                f"（要求**恰好** 1 = owner `{spec.owner}`）—— 再拼一份同名键 = 同一真值两处投影，"
                "两处迟早对不上（少发/错发就再也核不了）")
    return problems


def _consumer_problems(surfaces: dict[str, TruthSpec], frontend: dict[str, str]) -> list[str]:
    """C5/C6：前端消费**正确的面**（admin 面），且受管消费方里没有「数值补位成 0」。"""
    problems: list[str] = []
    for key, spec in sorted(surfaces.items()):
        api_src = frontend.get(spec.api_client)
        if api_src is None:
            problems.append(f"{key}: 前端 API 客户端不存在：{spec.api_client}")
            continue
        if spec.api_path_template not in api_src:
            problems.append(
                f"{key}: {spec.api_client} 里找不到管理面路径 `{spec.api_path_template}` ⇒ "
                "纸面拿不到实发（本单要修的就是这个洞）")
        if f"{spec.api_method}:" not in api_src:
            problems.append(f"{key}: {spec.api_client} 里找不到 `{spec.api_method}:`方法（消费入口漂移）")
        for rel, symbol in spec.consumers:
            src = frontend.get(rel)
            if src is None:
                problems.append(f"{key}: 声明的消费方不存在：{rel}")
                continue
            if symbol not in src:
                problems.append(f"{key}: 消费方 {rel} 里找不到 `{symbol}` ⇒ 「消费实发」这一步没有真的接上")
        for rel in spec.zero_fill_scope:
            src = frontend.get(rel)
            if src is None:
                problems.append(f"{key}: 数值补位判据的射程文件不存在：{rel}")
                continue
            for label, pattern in _ZERO_FILL_PATTERNS:
                for hit in re.findall(pattern, src):
                    problems.append(
                        f"{key}: 消费方 {rel} 出现**数值补位**（{label}）：{hit!r} —— "
                        "缺值被显示成 `0` 会被读成「实发为零」，与「没有这个数」是两件事")
        for prefix in spec.forbidden_api_prefixes:
            offenders = sorted(rel for rel, src in frontend.items() if prefix in src)
            if offenders:
                problems.append(
                    f"{key}: 桌面端出现**工人面**路径 `{prefix}`（{offenders}）—— "
                    "工人面要 `X-Worker-Session-Id`，桌面端拿不到 ⇒ 必 401 / 静默降级；"
                    "两端必须走各自的承载面（能力保留、载体分离）")
    return problems


def _all_problems(
    surfaces: dict[str, TruthSpec],
    java: dict[str, str] | None = None,
    frontend: dict[str, str] | None = None,
) -> list[str]:
    return (
        _face_problems(surfaces, java)
        + _single_projection_problems(surfaces, java if java is not None else _java_sources())
        + _consumer_problems(surfaces, frontend if frontend is not None else _frontend_sources())
    )


# ── C1~C6：现行树必须全绿 ────────────────────────────────────────────────────

def test_c1_registry_is_not_vacuous_and_faces_are_real():
    """C1：登记表非空、真值至少声明一个必需面、每个面的承载文件真实存在。"""
    assert len(TRUTH_SURFACES) >= 1, "真值登记表被清空 ⇒ 本守卫空跑通过（判据必须能判红）"
    spec = TRUTH_SURFACES["order_shipment_items"]
    assert spec.required_faces == ("worker", "admin"), (
        f"必需面被改短：{spec.required_faces} —— issue #5651 的病根正是「只落工人面」，"
        "把 admin 面从必需集里删掉 = 把这条判据的靶子删掉"
    )
    for face_name, face in spec.faces.items():
        _read(face.controller)  # 不存在 ⇒ 抛错
        assert face.full_path.startswith(("/api/worker/", "/api/admin/")), (
            f"{face_name} 面的路径 `{face.full_path}` 不在两个承载面前缀下"
        )


def test_c2_every_required_face_is_landed_or_explicitly_pending():
    """C2/C3/C5：必需的面要么落地（且真的调用 owner 方法 + 管理面带权限注解），要么显式登记未落。"""
    problems = _face_problems(TRUTH_SURFACES)
    assert problems == [], (
        "真值读面的登记面不成立（issue #5651：同一真值两个读面**只落一面** = 半成品形态，"
        "而它不会自己出声）：\n  " + "\n  ".join(problems)
    )


def test_c3_truth_view_key_has_exactly_one_projection():
    """C4：视图键字面量在 Java 主源里恰好一个文件（= owner）。"""
    problems = _single_projection_problems(TRUTH_SURFACES, _java_sources())
    assert problems == [], (
        "同一真值出现了**第二份投影**：\n  " + "\n  ".join(problems)
    )


def test_c4_desktop_consumes_the_admin_face_and_never_renders_missing_as_zero():
    """C5/C6：桌面端只许走 admin 面；受管消费方里禁止「缺值补位成 0」。"""
    problems = _consumer_problems(TRUTH_SURFACES, _frontend_sources())
    assert problems == [], (
        "前端消费面不成立（接错面 / 缺值被显示成 0）：\n  " + "\n  ".join(problems)
    )


# ── C7：注入式红证 + 内容指纹自证 ─────────────────────────────────────────────

def _fingerprint(text: str) -> str:
    """内容指纹（issue #4260 红证卫生：**禁 mtime / size** —— 它们会被同秒写入骗过）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _without_face(spec: TruthSpec, face_name: str) -> TruthSpec:
    return TruthSpec(
        what=spec.what,
        owner=spec.owner,
        owner_method=spec.owner_method,
        view_key=spec.view_key,
        required_faces=spec.required_faces,
        faces={k: v for k, v in spec.faces.items() if k != face_name},
        pending_faces=dict(spec.pending_faces),
        consumers=spec.consumers,
        api_client=spec.api_client,
        api_method=spec.api_method,
        api_path_template=spec.api_path_template,
        zero_fill_scope=spec.zero_fill_scope,
        forbidden_api_prefixes=spec.forbidden_api_prefixes,
    )


def test_c7_injected_regressions_are_red():
    """C7：五类回归各自注入一次，判据必须**各自**判红；并用内容指纹自证注入生效。"""
    spec = TRUTH_SURFACES["order_shipment_items"]
    java = _java_sources()
    frontend = _frontend_sources()
    baseline = _all_problems(TRUTH_SURFACES, java, frontend)
    assert baseline == [], f"现行树本应干净（C1~C6 已单独判）：{baseline}"

    # ── 注入 A（C2）：删掉 admin 面且不登记未落 ⇒ 必须红（#5651 的病根本身）──
    dropped = {"order_shipment_items": _without_face(spec, "admin")}
    assert _fingerprint(repr(dropped)) != _fingerprint(repr(TRUTH_SURFACES)), "注入 A 未生效"
    problems = _face_problems(dropped)
    assert any("admin" in p and "pending_faces" in p for p in problems), (
        f"删掉管理面后判据**没判红** ⇒ C2 是空判据：{problems}")

    # ── 注入 B（C3）：已落的 admin 面仍挂在「未落」清单 ⇒ 陈旧登记必须红 ──
    stale = TruthSpec(**{**spec.__dict__, "pending_faces": {"admin": "（陈旧）去向 #5651"}})
    assert _fingerprint(repr(stale)) != _fingerprint(repr(spec)), "注入 B 未生效"
    assert any("陈旧登记" in p for p in _face_problems({"order_shipment_items": stale})), (
        "已落面仍登记为未落却**没判红** ⇒ C3 是空判据")

    # ── 注入 C（C4）：在另一个 Java 文件里再拼一份同名视图键 ⇒ 必须红 ──
    copied = dict(java)
    copied["backend/admin-api/src/main/java/com/migao/admin/controller/OtherController.java"] = (
        'map.put("shipped_quantity", x);\n')
    assert _fingerprint(str(sorted(copied))) != _fingerprint(str(sorted(java))), "注入 C 未生效"
    problems = _single_projection_problems(TRUTH_SURFACES, copied)
    assert any("命中 2 个文件" in p for p in problems), (
        f"第二份投影**没判红** ⇒ C4 是空判据：{problems}")

    # ── 注入 D（C5）：controller 不再调 owner 方法 ⇒ 该面必须红 ──
    broken = dict(java)
    broken[spec.faces["admin"].controller] = broken[spec.faces["admin"].controller].replace(
        "orderShipmentService.readShipment(", "selfMadeProjection(")
    assert _fingerprint(broken[spec.faces["admin"].controller]) != _fingerprint(
        java[spec.faces["admin"].controller]), "注入 D 未生效"
    assert any("没有调用 owner 方法" in p for p in _all_problems(TRUTH_SURFACES, broken, frontend)), (
        "管理面自拼字段却**没判红** ⇒ C5 是空判据")

    # ── 注入 E（C6）：桌面端改调工人面 + 数量列写成 `?? 0` ⇒ 必须红 ──
    leaked = dict(frontend)
    leaked[spec.api_client] = leaked[spec.api_client].replace(
        "/api/admin/orders/${id}/shipments", "/api/worker/shipment/orders/${id}")
    consumer = spec.zero_fill_scope[0]
    leaked[consumer] = leaked[consumer] + (
        "\nconst BadQty = () => <span>{qty.cells[0]?.value ?? 0}</span>\n")
    assert _fingerprint(leaked[spec.api_client]) != _fingerprint(frontend[spec.api_client]), "注入 E 未生效"
    assert _fingerprint(leaked[consumer]) != _fingerprint(frontend[consumer]), "注入 E 未生效（消费方）"
    problems = _consumer_problems(TRUTH_SURFACES, leaked)
    assert any("工人面" in p for p in problems), f"前端接错面**没判红** ⇒ C6 是空判据：{problems}"
    assert any("数值补位" in p for p in problems), f"缺值补位成 0 **没判红** ⇒ C6 是空判据：{problems}"
