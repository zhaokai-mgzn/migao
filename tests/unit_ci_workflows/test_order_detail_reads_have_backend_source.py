# case_ids: OR-068
"""订单详情**读面键**的类级守卫：页面读的 `order.<键>` 必须在后端 DTO 里真存在（issue #7110；同族 #6882 / #7078）。

## 病根（一类缺陷，不是一个缺陷）

同一份文件 —— 订单详情页 `frontend/admin-web/src/app/(dashboard)/orders/[id]/OrderDetail.tsx` ——
在两天内长出**两次**同一个病：

| 出处 | 屏幕面读的键 | 后端真值 | 实测后果 |
|---|---|---|---|
| #7078 | `paidAt` / `receivedAt` / `paymentNo` | 详情面只下发过 `shippedAt`（`LogisticsInfo` 里的） | 「支付时间 / 确认收货时间」等行**恒 `-`**，与同屏状态引导「已付款 ✓」自相矛盾 |
| #7110 | `paymentDeadline` | **完全没有**（`orders` 无列、无任何写入点、无「超时未付」规则） | 「支付倒计时」**从未渲染过**（前置判断恒假：连「--:--」都不会出现） |

共因：**屏幕面的读点是"自由"的**。TS 类型里的可选键（`xxx?: string`）谁都能加，而运行时读到
`undefined` 既**不报错**、也**不渲染**（条件渲染直接跳过）⇒ **编译器与测试都不拦**。
`paymentDeadline?: string` 就这样在类型里躺了很久，直到有人拿 DTO 逐键对账才发现后端根本没有。

## 本判据（四条，均含注入式红证）

* **A 真语料零漂移**：`OrderDetail.tsx` 里每个 `order.<键>` / `order?.<键>`（含 `const { … } = order` 解构）
  都必须是 `OrderDetailResponse` 的**顶层字段**，或登记在 `EXEMPT` 且**带理由**。
  口径依据：本仓 Jackson **未开** `SNAKE_CASE`（`spring.jackson` 未配命名策略）⇒ Java 字段名 = 下发 JSON 键；
  且本 DTO **无** `@JsonProperty` 改名（改写名的读取归 issue #6890 的读面键台账）。
* **B 豁免表 fail-closed**：`EXEMPT` 每条必须有非空理由，**且该键必须真的被读到** ——
  登记了却没人读 = 陈旧豁免 ⇒ 红（防豁免表变垃圾场，同 §19.1「存量基线只许缩短」）。
  **空表是健康态**：撤下 `paymentDeadline` 之后，本页 20 个读点**全部有据**。
* **C 解析不许空转**：字段数 / 读点数**下限**断言 —— 解析器被改坏（正则不匹配了）必须**红**，
  不许因为「没解析到任何读点」而**静默变绿**（「没跑」≠「通过」）。
* **D 判别力自证 + 负控**：注入幽灵读点 / 从 DTO 文本里摘掉一个真字段 / 空理由豁免 / 陈旧豁免
  ⇒ **各自判红**；**只改注释与空白 ⇒ 不红**（防判据被自己的文案喂红）。

## 边界（照实登记，§19.1）

* 只覆盖**这一份文件**（两次事故都出在这里）；它**不是**全仓前端↔后端的字段对账。
* 只判**存在性**：字段存在但从不下发（如 `spring.jackson.default-property-inclusion: non_null`
  下值为 null）判不了 —— 那一半由 #6890 的读面键台账 + §15.7 真机多模态验收承担。
* 判不了 `order?.[动态键]`、`(order as any).xxx` 这类**形态学之外的**取值（正则射程边界）。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PAGE = REPO_ROOT / "frontend/admin-web/src/app/(dashboard)/orders/[id]/OrderDetail.tsx"
DTO = REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/dto/OrderDetailResponse.java"
DTO_CLASS = "OrderDetailResponse"

#: 允许「读了但后端没有该键」的**显式**豁免（键 → 理由）。**空表是健康态**。
#: 加条目必须写理由（判据 B），且该键必须真的被读取 —— 否则是陈旧豁免。
EXEMPT: dict[str, str] = {}

READ_RE = re.compile(r"\border\s*\??\.\s*([A-Za-z_]\w*)")
DESTRUCTURE_RE = re.compile(r"const\s*\{([^}]*)\}\s*=\s*order\b")
FIELD_RE = re.compile(r"^\s*private\s+(?:static\s+|final\s+)*[\w.$<>\[\],? ]+?\s+([a-zA-Z_]\w*)\s*;")

# ── 纯函数本体（判据与红证驱动**同一份**实现）─────────────────────────────────


def strip_comments(text: str) -> str:
    """剥掉 `//` 行注释与 `/* … */` 块注释（含 JSX 的 `{/* … */}`）。

    为什么先剥：本文件里有用来说明「这里原本读过 `order.paymentDeadline`」的解释性注释 ——
    不剥的话**注释也会被当成读点** ⇒ 判据既会漏判（真正的幽灵键藏在注释里也算"已读"），
    也会误判（合法注释把页面读点集合污染）。「只改注释 ⇒ 不红」正是本判据的负控。
    """
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def page_reads(text: str) -> list[str]:
    """页面读到的 `order.*` 键（去重排序）。`order.x` 与 `order?.x` 都算；注释里的不算。"""
    keys = set(READ_RE.findall(strip_comments(text)))
    for group in DESTRUCTURE_RE.findall(strip_comments(text)):
        for part in group.split(","):
            name = part.split("=")[0].split(":")[0].strip()
            if name:
                keys.add(name)
    return sorted(keys)


def dto_top_level_fields(text: str, class_name: str = DTO_CLASS) -> set[str]:
    """`class_name` **自身**的字段名（按花括号深度只取顶层，不混入嵌套类字段）。

    fail-closed：找不到类声明 ⇒ 断言失败（DTO 改名 / 删了就必须来改本判据，不许静默空转）。
    """
    decl = re.search(rf"\bclass\s+{re.escape(class_name)}\b[^{{]*\{{", text)
    assert decl, (
        f"没找到 `class {class_name}` 声明 —— DTO 改名或删除了就必须同步改本判据"
        f"（否则本守卫会在「字段集为空」上静默变绿）"
    )
    depth, fields = 1, set()
    for line in text[decl.end():].splitlines():
        if depth == 1:
            m = FIELD_RE.match(line)
            if m:
                fields.add(m.group(1))
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            break
    return fields


def unbacked_reads(reads, fields, exempt) -> list[str]:
    """读了、但后端 DTO 没有、也没登记豁免的键 ⇒ 幽灵字段。"""
    return [k for k in reads if k not in fields and k not in exempt]


def exemption_problems(reads, exempt) -> list[str]:
    """豁免表本身的问题：无理由 / 已不再被读取（陈旧）。空 = 健康。"""
    read_set = set(reads)
    out = []
    for key, reason in exempt.items():
        if not str(reason or "").strip():
            out.append(f"{key}: 豁免必须写理由（否则它就是没登记的幽灵字段）")
        if key not in read_set:
            out.append(f"{key}: 已不再被页面读取 ⇒ 陈旧豁免，删掉它（豁免表不许当垃圾场）")
    return out


def _page_text() -> str:
    return PAGE.read_text(encoding="utf-8")


def _dto_text() -> str:
    return DTO.read_text(encoding="utf-8")


# ── A. 真语料零漂移 ──────────────────────────────────────────────────────────

def test_a_page_reads_are_all_backed_by_dto_fields():
    reads = page_reads(_page_text())
    fields = dto_top_level_fields(_dto_text())
    bad = unbacked_reads(reads, fields, EXEMPT)
    assert not bad, (
        f"订单详情页读了后端**没有**的键（{len(bad)} 个）⇒ 这些行/块恒空或恒不渲染：\n  "
        + "\n  ".join(f"`order.{k}`" for k in bad)
        + "\n处置二选一：① 后端补真值（迁移 + 写入点 + DTO 透出，口径见 #7078 的修法）；"
          "② 撤下屏幕面并删掉类型键（口径见 #7110 撤下 `paymentDeadline`）。"
          "\n例外：确实没有后端来源、但有正当理由保留读点的 ⇒ 登记进本文件 `EXEMPT` 并写清理由。"
    )


# ── B. 豁免表 fail-closed ────────────────────────────────────────────────────

def test_b_exemptions_carry_a_reason_and_are_live():
    problems = exemption_problems(page_reads(_page_text()), EXEMPT)
    assert not problems, "豁免表不健全（空表才是健康态）：\n  " + "\n  ".join(problems)


# ── C. 解析不许空转（「没解析到」≠「没问题」）────────────────────────────────

def test_c_parsers_are_not_vacuous():
    reads = page_reads(_page_text())
    fields = dto_top_level_fields(_dto_text())
    assert len(fields) >= 20, (
        f"只从 DTO 解析到 {len(fields)} 个顶层字段 —— 疑似解析器失配（真值 ≈ 28）⇒ "
        f"此时「零漂移」是假绿"
    )
    assert len(reads) >= 12, (
        f"只从页面解析到 {len(reads)} 个读点 —— 疑似解析器失配（真值 ≈ 20）⇒ 同上"
    )


# ── D. 判别力自证 + 负控 ────────────────────────────────────────────────────

def test_d_guard_has_discriminating_power():
    """四种坏形态各自判红；负控（只改注释/空白）不红。"""
    page, dto = _page_text(), _dto_text()
    fields = dto_top_level_fields(dto)

    # ① 注入一个幽灵读点 ⇒ 必须点名它
    injected = page + "\nconst ghost = order.ghostDeadline\n"
    assert unbacked_reads(page_reads(injected), fields, EXEMPT) == ["ghostDeadline"]

    # ② 从 DTO 文本里摘掉一个**真实存在**的字段（模拟「后端根本没这个键」）⇒ 对应读点变幽灵
    assert "private OffsetDateTime paidAt;" in dto
    shrunk = dto.replace("private OffsetDateTime paidAt;", "")
    assert "paidAt" in unbacked_reads(page_reads(page), dto_top_level_fields(shrunk), EXEMPT)

    # ③ 同一份输入 + 带理由的豁免 ⇒ 不红（豁免的口径本身也要能通过）
    assert unbacked_reads(page_reads(page), dto_top_level_fields(shrunk), {"paidAt": "测试用理由"}) == []

    # ④ 豁免表的两条坏形态：无理由 / 陈旧
    assert exemption_problems(["paidAt"], {"paidAt": ""}), "空理由豁免必须红"
    assert exemption_problems(["paidAt"], {"ghostDeadline": "有理由但没人读"}), "陈旧豁免必须红"

    # ⑤ 负控：只改注释 / 空白 ⇒ 不红
    assert unbacked_reads(page_reads(page.replace("  ", "    ")), fields, EXEMPT) == []
    assert unbacked_reads(
        page_reads(page + "\n// issue #7110：注释里提到 order.paymentDeadline 不算读点\n"),
        fields,
        EXEMPT,
    ) == []
