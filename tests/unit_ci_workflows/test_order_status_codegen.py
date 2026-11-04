# case_ids: MC-204
r"""订单状态**单一源 → 两端生成物**的判据（issue #8198 的 P2-2b）。

## 病（一类缺陷，不是一个缺陷）

P2-2a（`#8198` 评论 2026-10-31 裁定「**加常量、不加类型**」）把订单状态在 Java 侧收敛成
`OrderStatusTransitions` 的 7 个常量 + 三张表 —— **一处取值**。但"一处取值"只治了 Java：
前端与 Agent 侧的同一份取值仍是**手抄的第二份**（TS 的两套定义、4 个工具 schema 的枚举），
它们与单一源分叉时**没有任何东西会红**（`producing` 被抄成 `producin`，页面与工具都静默降级）。

本判据把"抄"这条路堵死：取值**只能来自生成物**，生成物**只能来自** Java 单一源。

## 四条判据（每条都能单独变红）

1. **生成物与源逐值相等（TS）**：独立解析**入库的** `order-status.generated.ts`
   （不调用生成器，那会变成"生成器自己证明自己"），逐值比对 Java 单一源里的
   常量 / 标签 / 流转 / 可编辑集合；
2. **生成物与源逐值相等（Python）**：同上，用 `ast.literal_eval` 读入库的 `.py`；
3. **删掉生成步骤 ⇒ 判红**：`python3 scripts/order_status_codegen.py --check` 是本仓
   **唯一**的新鲜度入口（`0` 同步 / `1` 陈旧 / `3` 无法判定）。红证在内存/临时树里实跑：
   只改源不重生成 ⇒ 具名报出两个产物陈旧；删掉生成物 / 挪走单一源 ⇒ **`3` 无法判定**
   （绝不是绿）；重生成后 ⇒ 回到绿（证明它读的是**源**，不是一张写死的表）；
4. **手写再出现同名字面量 ⇒ 判红**：扫两处手写面（TS 的 `types/index.ts`、4 个 Agent 工具
   schema），命中即**具名**报出「文件 + 行 + 值 + 该行原文」。取值走仓内唯一一份引号感知实现
   （`#5323`）⇒ **注释里写同样的词不算**；非订单域的同名用法逐条按**原文**登记豁免，
   台账**只许缩短**（某条不再出现 ⇒ 红并要求销账）。

## 为什么扫面词只有四个

`confirmed` / `producing` / `packed` / `cancelled` —— 判据面里**既有**后端取值、又有大量
**同名不同域**的用法，词表不能凭"订单状态有 7 个值"直取：
`pending` 是跨域通用词（售后 / 注册 / 通知 / 财务流水都在用），`shipped` / `completed`
在 TS 里**同时是前端展示口径**（`OrderStatus` 的成员）⇒ 纳进来会把前端自己的词汇判成违规。
**缺口照实登记**：新写 `'pending'` / `'shipped'` / `'completed'` 的裸字面量**不会**被本条抓到
（取值等价那一半仍由判据 1/2 挡着 —— 手抄一份不同的取值表会红）。

## 边界（照实登记，§19.1）

- 判的是**文本形态 + 取值相等**，判不了「这个状态值该不该从这里写」这类业务口径；
- `entity/` / `mapper/` 里同名但不同域的状态（加工单 / 入库单 / 盘点单）不在面内；
- 前端 `OrderStatus`（`pending_payment` / `pending_shipment` / …）是 **UI 侧词汇**，
  Java 侧没有对应取值 ⇒ **不是**本判据的生成对象，也不该生成（由 `FrontendToBackendStatus`
  显式映射，取值来自生成物）；
- Agent 面今天**有意只暴露 6 个状态**（不含 `packed`）：`packed` 是工人动作、放开它属于
  行为变更 ⇒ 窄化写在 `backend/ai-agent-service/app/constants/order_status.py`（一处），
  本判据只保证**它不是手抄的**。
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import order_status_codegen as codegen  # noqa: E402
from unit_ci_workflows._source_parsing import (  # noqa: E402
    python_string_literals,
    typescript_literals,
)

SOURCE_REL = codegen.SOURCE_REL
TS_REL = codegen.TS_REL
PY_REL = codegen.PY_REL

#: 扫面词（理由见模块 docstring 的「为什么扫面词只有四个」）。
SCAN_WORDS = ("cancelled", "confirmed", "packed", "producing")

#: 两处手写面 → 词法种类。**面是登记表**（不是"我改过的文件清单"）⇒ 新增文件要在这里登记。
HAND_WRITTEN_FACES: dict[str, str] = {
    "frontend/admin-web/src/types/index.ts": "ts",
    "backend/ai-agent-service/app/tools/order_manage.py": "py",
    "backend/ai-agent-service/app/tools/validate_input.py": "py",
    "backend/ai-agent-service/app/tools/order_query.py": "py",
    "backend/ai-agent-service/app/tools/customer_order_query.py": "py",
}

#: 接线锚（类级元守卫）：删掉"取值来自生成物"这条线 ⇒ 即使一个字面量都没有，也判红。
WIRING_ANCHORS: dict[str, str] = {
    "frontend/admin-web/src/types/index.ts": "(typeof ORDER_STATUS_VALUES)['PACKED']",
    "backend/ai-agent-service/app/tools/order_manage.py": "list(AGENT_ORDER_STATUSES)",
    "backend/ai-agent-service/app/tools/validate_input.py": "list(AGENT_ORDER_STATUSES)",
    "backend/ai-agent-service/app/tools/order_query.py": "list(AGENT_ORDER_STATUSES)",
    "backend/ai-agent-service/app/tools/customer_order_query.py": "list(AGENT_ORDER_STATUSES)",
}

#: **非订单域**的同名用法：逐条给出**原文**（`line.strip()` 逐字相等才算命中）。
#: 台账**只许缩短** —— 某条不再出现（重构 / 被误改成订单状态字面量）⇒ 红并要求销掉这条。
NON_ORDER_STATUS_USAGES: dict[str, tuple[str, ...]] = {
    "frontend/admin-web/src/types/index.ts": (
        # 加工单（processing order）的状态机 —— `cancelled` 是它的终态，与订单状态同名不同域。
        "status: 'generated' | 'issued' | 'in_processing' | 'completed' | 'cancelled'",
        # 入库单（inbound order）的状态 —— 同样同名不同域。
        "export type InboundOrderStatus = 'draft' | 'posted' | 'cancelled'",
    ),
    # 两个查询工具的**状态中文映射**：键集是状态值（与单一源同源），但它是**消费者文案**
    # （B 端把 confirmed 说成「已确认（待发货）」）⇒ 改成生成物要先裁定文案口径，见重启条件。
    "backend/ai-agent-service/app/tools/order_query.py": (
        '"confirmed": "已确认（待发货）",',
        '"producing": "生产中",',
        '"cancelled": "已取消",',
    ),
    "backend/ai-agent-service/app/tools/customer_order_query.py": (
        '"confirmed": "已确认（待发货）",',
        '"producing": "生产中",',
        '"cancelled": "已取消",',
    ),
}

#: 生成物抬头里必须出现的两行（产物被手改 / 被换成"看起来像生成物"的手写文件 ⇒ 红）。
ARTIFACT_ANCHORS: dict[str, tuple[str, ...]] = {
    TS_REL: ("不要手改", "python3 scripts/order_status_codegen.py --write"),
    PY_REL: ("不要手改", "python3 scripts/order_status_codegen.py --write"),
}


# ── 独立解析（**不调用生成器**：否则等于让生成器自己证明自己）────────────────────


def _ts_block(text: str, marker: str) -> list[str]:
    """取 `marker` 那一**行之后**、到收尾 `}` / `]` 之间的条目行（生成物形态固定）。"""
    start = text.index(marker) + len(marker)
    rest = text[start:]
    first_newline = rest.find("\n")
    assert first_newline >= 0, f"生成物形态变了（`{marker}` 之后没有续行）"
    out: list[str] = []
    for line in rest[first_newline + 1:].splitlines():
        stripped = line.strip()
        if stripped in ("}", "]", "] as const", "} as const"):
            break
        if stripped:
            out.append(stripped)
    return out


def _json_tail(stripped: str, sep: str) -> str:
    """`左边<sep>右边` 取右边（去掉行尾逗号）—— 只做字符串切分，不猜语义。"""
    _left, found, right = stripped.partition(sep)
    assert found == sep, f"生成物形态变了（这一行没有 {sep!r}）：{stripped[:120]}"
    return right.rstrip().rstrip(",")


def parse_ts_artifact(text: str) -> dict:
    """独立解析 `order-status.generated.ts`（`json.loads` 读字面量，不依赖生成器）。"""
    values = [json.loads(ln.rstrip(",")) for ln in _ts_block(text, "export const ORDER_STATUSES = [")]
    labels = {}
    for ln in _ts_block(text, "export const ORDER_STATUS_LABELS"):
        key, _sep, _rest = ln.partition(": ")
        labels[json.loads(key)] = json.loads(_json_tail(ln, ": "))
    transitions = {}
    for ln in _ts_block(text, "export const ORDER_STATUS_TRANSITIONS"):
        key, _sep, _rest = ln.partition(": ")
        transitions[json.loads(key)] = tuple(json.loads(_json_tail(ln, ": ")))
    editable_line = [ln for ln in text.splitlines() if ln.startswith("export const CONTENT_EDITABLE_STATUSES")]
    assert len(editable_line) == 1, "生成物里应有且仅有一行 CONTENT_EDITABLE_STATUSES 声明"
    editable = tuple(json.loads(_json_tail(editable_line[0], "= ")))
    const_block = {}
    for ln in _ts_block(text, "export const ORDER_STATUS_VALUES"):
        key, _sep, _rest = ln.partition(": ")
        const_block[key] = json.loads(_json_tail(ln, ": "))
    return {
        "values": tuple(values),
        "labels": labels,
        "transitions": transitions,
        "content_editable": editable,
        "constants": const_block,
    }


def parse_py_artifact(text: str) -> dict:
    """独立解析 `order_status_generated.py`（`ast.literal_eval` 读模块级取值，不依赖生成器）。"""
    tree = ast.parse(text)
    found: dict[str, object] = {}
    for node in tree.body:
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
        if target is None or node.value is None:
            continue
        try:
            found[target] = ast.literal_eval(node.value)
        except ValueError:  # 不是字面量（本生成物里不该出现）
            raise AssertionError(f"生成物里的 {target} 不是字面量 ⇒ 有人手改了生成物")
    return found


# ── 期望值：从 Java 单一源取（并把解析**钉回原文**）──────────────────────────────


def java_source() -> codegen.OrderStatusSource:
    return codegen.parse_source((REPO_ROOT / SOURCE_REL).read_text(encoding="utf-8"))


def expected_from_java() -> dict:
    source = java_source()
    raw = (REPO_ROOT / SOURCE_REL).read_text(encoding="utf-8")
    # 解析结果必须**逐字**能在原文里找到（防"解析器凭空造值"）：常量声明原文 + 标签原文。
    for name, value in source.constants:
        anchor = f'public static final String {name} = "{value}";'
        assert raw.count(anchor) == 1, f"单一源里应恰有一处常量声明原文：{anchor}"
    for value, label in source.labels.items():
        assert f'"{label}"' in raw, f"单一源里找不到标签原文：{value} → {label}"
    return {
        "values": source.values,
        "labels": dict(source.labels),
        "transitions": {k: tuple(v) for k, v in source.transitions.items()},
        "content_editable": tuple(source.content_editable),
        "constants": {name: value for name, value in source.constants},
    }


# ── 扫面（判据 4）─────────────────────────────────────────────────────────────


def _hits(rel: str, text: str, kind: str) -> list[tuple[int, str]]:
    """`[(行号, 字面量值), …]`（注释里的不算；TS 单/双引号都算，Python 走 tokenize）。"""
    if kind == "ts":
        return [(text.count("\n", 0, pos) + 1, value) for pos, value in typescript_literals(text)]
    return list(python_string_literals(text, rel))


def scan_hand_written(repo: Path, faces: dict[str, str] | None = None,
                      ledger: dict[str, tuple[str, ...]] | None = None) -> list[str]:
    """扫两处手写面里的裸状态字面量；返回**具名**问题行（空 = 干净）。"""
    faces = HAND_WRITTEN_FACES if faces is None else faces
    ledger = NON_ORDER_STATUS_USAGES if ledger is None else ledger
    problems: list[str] = []
    for rel in faces:
        path = repo / rel
        if not path.is_file():
            problems.append(f"{rel}：判据面里的文件不存在（面被掏空 ⇒ 判红，不是跳过）")
            continue
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        exempt = ledger.get(rel, ())
        for line_no, value in _hits(rel, text, faces[rel]):
            if value not in SCAN_WORDS:
                continue
            stripped = lines[line_no - 1].strip()
            if stripped in exempt:
                continue
            problems.append(
                f"{rel} 第 {line_no} 行：手写订单状态字面量 {value!r} —— 取值只许来自生成物"
                f"（`order-status.generated.ts` / `order_status_generated.py`）；原文：{stripped[:120]}")
    return problems


def stale_exemptions(repo: Path, ledger: dict[str, tuple[str, ...]] | None = None) -> list[str]:
    """豁免台账**只许缩短**：登记原文不再逐字出现 ⇒ 红并要求销账。"""
    ledger = NON_ORDER_STATUS_USAGES if ledger is None else ledger
    problems: list[str] = []
    for rel, entries in ledger.items():
        path = repo / rel
        if not path.is_file():
            problems.append(f"{rel}：豁免台账指向的文件不存在（台账陈旧）")
            continue
        stripped_lines = {ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()}
        for entry in entries:
            if entry not in stripped_lines:
                problems.append(
                    f"{rel}：豁免台账的这条原文已不存在 ⇒ 销账（台账只许缩短）：{entry}")
    return problems


# ── 判据 1 / 2：生成物与源逐值相等 ─────────────────────────────────────────────


def test_ts_artifact_matches_single_source() -> None:
    text = (REPO_ROOT / TS_REL).read_text(encoding="utf-8")
    for anchor in ARTIFACT_ANCHORS[TS_REL]:
        assert anchor in text, f"{TS_REL} 缺抬头锚点 {anchor!r} ⇒ 这不是生成物"
    assert parse_ts_artifact(text) == expected_from_java()


def test_python_artifact_matches_single_source() -> None:
    text = (REPO_ROOT / PY_REL).read_text(encoding="utf-8")
    for anchor in ARTIFACT_ANCHORS[PY_REL]:
        assert anchor in text, f"{PY_REL} 缺抬头锚点 {anchor!r} ⇒ 这不是生成物"
    found = parse_py_artifact(text)
    expected = expected_from_java()
    got = {
        "values": tuple(found["ORDER_STATUSES"]),
        "labels": dict(found["ORDER_STATUS_LABELS"]),
        "transitions": {k: tuple(v) for k, v in found["STATUS_TRANSITIONS"].items()},
        "content_editable": tuple(found["CONTENT_EDITABLE_STATUSES"]),
        "constants": {name: found[name] for name in expected["constants"]},
    }
    assert got == expected


# ── 判据 3：删掉生成步骤 ⇒ 判红（含"读的是源不是写死的表"的自证）──────────────


def _temp_repo(root: Path) -> Path:
    """把「单一源 + 两份生成物」复制到临时树（**不碰工作树**）。"""
    for rel in (SOURCE_REL, TS_REL, PY_REL):
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text((REPO_ROOT / rel).read_text(encoding="utf-8"), encoding="utf-8")
    return root


def test_freshness_gate_is_green_on_the_committed_tree() -> None:
    """入库树必须是同步的；同一条命令也是 CI/本地共用的入口（**单一实现**）。"""
    report = codegen.check(REPO_ROOT)
    assert report["verdict"] == "fresh", report["problems"]
    assert report["artifacts"] == [TS_REL, PY_REL]


def test_freshness_gate_goes_red_when_generation_step_is_skipped(tmp_path: Path) -> None:
    root = _temp_repo(tmp_path)
    assert codegen.check(root)["verdict"] == "fresh"

    # ① 只改源、不重生成 ⇒ 两个产物都判红（具名 + 差量读数）。
    source = root / SOURCE_REL
    changed = source.read_text(encoding="utf-8").replace(
        'public static final String PRODUCING = "producing";',
        'public static final String PRODUCING = "producingg";')
    assert changed != source.read_text(encoding="utf-8"), "注入没生效（锚点漂移）⇒ 本判据无从判红"
    source.write_text(changed, encoding="utf-8")
    drifted = codegen.check(root)
    assert drifted["verdict"] == "drifted", drifted["problems"]
    assert {d["artifact"] for d in drifted["drifted"]} == {TS_REL, PY_REL}
    assert any("producingg" in line for line in drifted["problems"]), drifted["problems"]
    # 🔴 判红的**承载体是命令的退出码**（CI 读的就是它）：`1` = 陈旧。
    assert codegen.main(["--repo", str(root), "--check"]) == 1

    # ② 重生成 ⇒ 回到绿（证明它读的是**源**，不是一张写死的表）。
    codegen.write(root)
    assert codegen.check(root)["verdict"] == "fresh"

    # ③ 删掉生成物 ⇒ **无法判定**（fail-closed：绝不当「跳过/通过」）。
    (root / PY_REL).unlink()
    missing = codegen.check(root)
    assert missing["verdict"] == "undecidable"
    assert any(PY_REL in line for line in missing["problems"])
    assert codegen.main(["--repo", str(root), "--check"]) == 3

    # ④ 挪走单一源 ⇒ 同样无法判定（没有源就没有"新鲜"这回事）。
    (root / TS_REL).unlink()
    (root / SOURCE_REL).rename(root / (SOURCE_REL + ".bak"))
    no_source = codegen.check(root)
    assert no_source["verdict"] == "undecidable"
    assert any("单一源缺失" in line for line in no_source["problems"])


def test_generation_is_deterministic_and_has_no_environment_fingerprint(tmp_path: Path) -> None:
    """同样的源 ⇒ 逐字节同样的产物（两次生成 `cmp` 相等；产物里没有任何环境指纹）。"""
    root = _temp_repo(tmp_path)
    codegen.write(root)
    first = {rel: (root / rel).read_bytes() for rel in (TS_REL, PY_REL)}
    codegen.write(root)
    second = {rel: (root / rel).read_bytes() for rel in (TS_REL, PY_REL)}
    assert first == second
    assert first == {rel: (REPO_ROOT / rel).read_bytes() for rel in (TS_REL, PY_REL)}


# ── 判据 4：手写面不许再有同名裸字面量 ────────────────────────────────────────


def test_hand_written_faces_have_no_status_literal() -> None:
    assert scan_hand_written(REPO_ROOT) == []
    assert stale_exemptions(REPO_ROOT) == []


def test_hand_written_faces_are_wired_to_the_generated_artifact() -> None:
    """类级元守卫：面还在、接线也在 —— 否则「零字面量」可能只是面被掏空了。"""
    assert len(HAND_WRITTEN_FACES) == 5
    for rel, anchor in WIRING_ANCHORS.items():
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert anchor in text, f"{rel} 里找不到接线锚点 {anchor!r} ⇒ 取值不再来自生成物（判红）"


def test_scan_judgment_has_teeth(tmp_path: Path) -> None:
    """判别力自证（纯内存 / 临时树，不碰工作树）：坏语料必须**具名**、注释不算、台账行放行。"""
    bad_ts = "export const X = {\n  producing: 'producing',\n}\n"
    assert [(bad_ts.count("\n", 0, pos) + 1, v) for pos, v in typescript_literals(bad_ts)] == \
        [(2, "producing")]

    # 注释 / 文档字符串里的同一个词**不算**（这正是引号感知走查存在的理由，`#5323`）。
    commented = "// 'producing'\n/* 'confirmed' */\nconst a = 'packed'\n"
    assert [v for _p, v in typescript_literals(commented)] == ["packed"]

    # Python 侧同口径：`#` 后面 / 字符串里的 `#` 都不影响判定。
    py = "A = 1  # 'producing'\nB = '#cancelled'\nC = 'packed'\n"
    assert [v for _n, v in python_string_literals(py, "fixture.py")] == ["#cancelled", "packed"]

    # 台账行放行：同一条原文在台账里 ⇒ 不报；不在台账里 ⇒ 报。
    rel = "fixture.ts"
    text = "export type InboundOrderStatus = 'draft' | 'posted' | 'cancelled'\n"
    path = tmp_path / rel
    path.write_text(text, encoding="utf-8")
    assert scan_hand_written(tmp_path, faces={rel: "ts"},
                             ledger={rel: ("export type InboundOrderStatus = 'draft' | 'posted' | 'cancelled'",)}) == []
    assert len(scan_hand_written(tmp_path, faces={rel: "ts"}, ledger={})) == 1
    # 台账陈旧 ⇒ 红（某条原文不再出现 ⇒ 要求销账）。
    assert stale_exemptions(tmp_path, ledger={rel: ("已经不存在的一行",)}) != []


def test_scan_names_the_offending_file_and_line(tmp_path: Path) -> None:
    """把一处裸字面量**真写进**判据面的一份副本 ⇒ 必须具名报出文件 + 行 + 值。"""
    rel = "backend/ai-agent-service/app/tools/order_query.py"
    dest = tmp_path / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    original = (REPO_ROOT / rel).read_text(encoding="utf-8")
    poisoned = original.replace(
        '"enum": list(AGENT_ORDER_STATUSES),',
        '"enum": ["pending", "producing"],', 1)
    assert poisoned != original, "注入没生效（锚点漂移）⇒ 本判据无从判红"
    dest.write_text(poisoned, encoding="utf-8")
    problems = scan_hand_written(tmp_path, faces={rel: "py"})
    assert len(problems) == 1
    assert problems[0].startswith(f"{rel} 第 ")
    assert "'producing'" in problems[0]
