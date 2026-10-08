# case_ids: PG-069
"""类级元守卫（issue #6226）：`Map.of()` / `Map.copyOf()` 族空表 + **未经判空的空键索引**。

## 病（本单两处站点的**共同形态**，逐字复核过）

方法在一个**空集分支**返回 `Map.of()`（= `ImmutableCollections.MapN`，**对 `get(null)` 抛 NPE**），
而调用点用**可能为 null 的键**去索引它 —— 于是「该页/该批所有键都为空」这一条路径必然 500：

| 站点 | 空集分支 | 调用点 |
|---|---|---|
| `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingItemService.java::getCategoryNameMap` | `return Map.of();` | `categoryNameMap.get(item.getCategoryId())`（键**未过**同一道 `hasText` 过滤） |
| `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java::loadOrders` | `return Map.of();` | `orders.get(po.getOrderId())`（未判空） |

**同族不一致的实证**：`backend/admin-api/src/main/java/com/migao/admin/service/ProductService.java::getCategoryNameMap`
**同名、同签名**，空集返回 `new HashMap<>()` ⇒ 空键索引返 null 不抛 ⇒ 安全（本单**不动**它）。

## 射程（**只裁 `Map.of` / `Map.copyOf` 族**，如实登记）

JDK 语义**实跑已证**（issue #6219 的对照表 + 本单红证）：
`Map.of().get(null)` / `Map.of("k","v").get(null)` / `Map.copyOf(...)` ⇒ **NPE**；
`Collections.emptyMap()` / `Collections.unmodifiableMap(new LinkedHashMap<>())` / `new LinkedHashMap<>()`
/ `new HashMap<>()` ⇒ `get(null)` **返 null 不抛**。⇒ 后者**一律不判**（判了就是新的假红）。

## 判据（五条，任一不成立 ⇒ 红；条数**现取**，不写死）

1. **未登记即红**：现取到的「`Map.of`/`Map.copyOf` 族方法的返回值被**同文件、同方法**内的
   `<var>.get(...)` 索引」候选点，必须逐条登记在 `mapof_family_null_key_index_ledger.json`；
2. **台账只许缩短**：台账里的候选点必须是**现取集合**的子集（幽灵条目 ⇒ 红）；
3. **判据不空转 + 裁得动**：两段台账都不许空；每条必须带 `why`；`disposition=safe-literal`
   的声明必须**机械为真**（该候选点的索引实参全是字符串字面量 —— 字面量键恒非 null）；
4. **修复回归锁**：`tolerant_fixes` 里每个「空集分支已改成容忍空键的表」的方法，
   其方法体**不得再出现** `Map.of` / `Map.copyOf`（谁改回去，当场红）；
5. **判别力自证**：六种坏形态（两处真站点各自改回 `Map.of()` / 新增未登记候选点 /
   幽灵条目 / 假 `safe-literal` 声明 / 只改注释）在**内存变异**下各自判红，未变异则**不报**。

## 覆盖边界（照实登记，§19.1）

- **只认「同文件 + 同方法」的局部变量族**（`Map<...> v = M(...)` 后 `v.get(arg)`）——
  本单两处站点都在此族内。**跨方法传参族不在射程内**：把 map 存进字段/当形参传给另一个方法后再
  `get(null)`（形态见 `backend/admin-api/src/main/java/com/migao/admin/service/WorkerCuttingHeightService.java`
  的 `brands(...)` → `positionRow(...)`，即 issue #6219 的站点）本扫描器**看不见**
  ⇒ 与 #6219 的守卫是**互补**关系、不是重复（见 PR body 的「与 #6219 守卫的关系」段）。
- **方法归属靠缩进 4 格以上的「单行签名 + `{` 结尾」近似**：多行签名 / 嵌套类里的方法会被归到
  外层方法名下 ⇒ 同一「同方法」判定变松（可能多报、不会漏报本族）。
- **「实参是否可能为 null」不做数据流分析**：只有字符串字面量被**机械**判为安全；
  其余形态一律要人写下 `why` 登记 —— 这是**有意的**（口径同 §28.2.2：机械锁盖不到的那一半如实登记）。
- 本守卫**不跑** Java 测试（只读源码文本），**不**替代 #6226 的两条实例判据
  （`ProcessingItemServiceTest` / `ProcessingOrderServiceTest`）。
"""

from __future__ import annotations

import json
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
SRC_REL = "backend/admin-api/src/main/java"
LEDGER_REL = "tests/unit_ci_workflows/mapof_family_null_key_index_ledger.json"
MIN_WHY = 20

#: 单行方法签名（≥4 格缩进、以 `{` 结尾）—— 方法归属的**近似**实现（边界见模块 docstring）。
_DECL = re.compile(
    r"^\s{4,}(?:(?:public|private|protected|static|final|synchronized|abstract|default)\s+)*"
    r"(?:[\w$<>\[\],.?\s]+?)\s+(\w+)\s*\([^;{]*\)\s*(?:throws [\w,.\s]+)?\{\s*$"
)
#: 控制流关键字（长得像方法签名，必须排除）
_CTRL = {"if", "for", "while", "switch", "catch", "try", "return", "new", "do", "else",
         "synchronized", "record", "class", "static"}
#: `Map.of` / `Map.copyOf` 族的**返回**（本守卫的裁切面：只有这两个族对 null 键抛）
_RET_FAMILY = re.compile(r"\breturn\s+Map\.(of|copyOf)\s*\(")
#: `Map<...> v = callee(` —— 候选点（返回值落进一个局部 Map 变量）
_MAP_CALL = re.compile(r"\bMap\s*<[^;=]*?>\s*(\w+)\s*=\s*(\w+)\s*\(")
#: `<var>.get(<实参>)`
_GET = re.compile(r"\b(\w+)\.get\s*\(([^()]*(?:\([^()]*\))?[^()]*)\)")
_LITERAL_ARG = re.compile(r'^\s*"[^"]*"\s*$')


def _methods_by_line(lines: list[str]) -> dict[int, str]:
    cur, out = "<class-body>", {}
    for i, ln in enumerate(lines, 1):
        m = _DECL.match(ln)
        if m and m.group(1) not in _CTRL:
            cur = m.group(1)
        out[i] = cur
    return out


def scan(root: pathlib.Path) -> dict:
    """现取扫描（零 LLM、只读）：返回 occurrence 与候选点（键 = `<仓库相对路径>::<方法名>`）。"""
    src = pathlib.Path(root) / SRC_REL
    occurrences: list[dict] = []
    candidates: dict[str, dict] = {}
    for f in sorted(src.rglob("*.java")):
        rel = f.relative_to(root).as_posix()
        lines = f.read_text(encoding="utf-8").splitlines()
        methods = _methods_by_line(lines)
        family_methods: dict[str, int] = {}
        for i, ln in enumerate(lines, 1):
            if _RET_FAMILY.search(ln):
                occurrences.append({"file": rel, "method": methods[i], "line": i})
                family_methods.setdefault(methods[i], i)
        for i, ln in enumerate(lines, 1):
            m = _MAP_CALL.search(ln)
            if not m:
                continue
            var, callee = m.group(1), m.group(2)
            if callee not in family_methods:
                continue
            caller = methods[i]                  # 索引点必须落在**同一个方法**里（跨方法不算本族）
            args = []
            for j in range(i, min(i + 30, len(lines) + 1)):
                if methods.get(j) != caller:      # 越过方法尾即停
                    break
                for gm in _GET.finditer(lines[j - 1]):
                    if gm.group(1) == var:
                        arg = gm.group(2).strip()
                        args.append({"line": j, "arg": arg,
                                     "literal": bool(_LITERAL_ARG.match(arg))})
            if args:
                key = f"{rel}::{callee}"
                candidates.setdefault(key, {"key": key, "file": rel, "callee": callee,
                                            "args": [], "declared_at": family_methods[callee]})
                candidates[key]["args"].extend(args)
    return {"occurrences": occurrences, "candidates": candidates}


def _method_body_has_family(root: pathlib.Path, rel: str, method: str) -> bool | None:
    """`rel` 里名为 `method` 的方法体中是否还有 `Map.of`/`Map.copyOf` 族返回；方法不存在 ⇒ None。"""
    f = pathlib.Path(root) / rel
    if not f.is_file():
        return None
    lines = f.read_text(encoding="utf-8").splitlines()
    methods = _methods_by_line(lines)
    if method not in set(methods.values()):
        return None
    return any(_RET_FAMILY.search(ln) and methods[i] == method
               for i, ln in enumerate(lines, 1))


def problems(result: dict, ledger: dict, root: pathlib.Path = REPO) -> list[str]:
    """五条判据的**单一实现**（纯函数，供判别力自证复用；不在测试里写第二份规则）。"""
    bad: list[str] = []
    live: dict[str, dict] = result["candidates"]
    book = ledger.get("candidates") or []
    fixes = ledger.get("tolerant_fixes") or []

    # ③ 台账不许空转
    if not book:
        bad.append("`candidates` 为空 ⇒ 台账空转（清空台账不能消红）")
    if not fixes:
        bad.append("`tolerant_fixes` 为空 ⇒ 已修站点没被钉住（改回去不会有东西变红）")

    registered = {e.get("key") for e in book}
    # ① 未登记即红
    for key in sorted(set(live) - registered):
        c = live[key]
        args = ", ".join(f"`.get({a['arg']})`@L{a['line']}" for a in c["args"])
        bad.append(
            f"未登记的空键索引候选点：{key} —— {args} ⇒ "
            f"`Map.of`/`Map.copyOf` 族的 `get(null)` 抛 NPE；"
            f"要么把该方法的空集分支改成容忍空键的表，要么登记并写下 why"
        )
    # ② 台账只许缩短（幽灵即红）
    for key in sorted(registered - set(live)):
        bad.append(f"幽灵条目（候选点已消失，台账只许缩短）：{key}")

    # ③ 每条必须有 why；`safe-literal` 声明必须机械为真
    for e in book:
        key = e.get("key") or ""
        why = (e.get("why") or "").strip()
        if len(why) < MIN_WHY:
            bad.append(f"缺 why（<{MIN_WHY} 字）：{key!r}")
        if e.get("disposition") == "safe-literal":
            args = live.get(key, {}).get("args") or []
            not_literal = [a["arg"] for a in args if not a["literal"]]
            if not_literal:
                bad.append(
                    f"`safe-literal` 声明与现取事实不符（实参不是字符串字面量）："
                    f"{key} ⇒ {not_literal}"
                )
        elif e.get("disposition") not in ("accepted",):
            bad.append(f"`disposition` 非法（只认 `safe-literal` / `accepted`）：{key!r}")

    # ④ 修复回归锁
    for e in fixes:
        key = e.get("key") or ""
        why = (e.get("why") or "").strip()
        if len(why) < MIN_WHY:
            bad.append(f"`tolerant_fixes` 缺 why（<{MIN_WHY} 字）：{key!r}")
        rel, _, method = key.partition("::")
        has = _method_body_has_family(root, rel, method) if (rel and method) else None
        if has is None:
            bad.append(f"`tolerant_fixes` 指向不存在的方法（文件或方法没了）：{key}")
        elif has:
            bad.append(
                f"已修站点退回去了：{key} 的方法体里又出现 `Map.of`/`Map.copyOf` 族返回 ⇒ "
                f"空键索引会重新抛 NPE（issue #6226）"
            )
    return bad


def load_ledger(path: pathlib.Path | None = None) -> dict:
    return json.loads((path or (REPO / LEDGER_REL)).read_text(encoding="utf-8"))


# ══════════════════════ 判据 ══════════════════════

def test_repo_tree_has_no_unregistered_null_key_index():
    """①~④ 在本仓真源码上必须全绿（红的时候报出**具名**的站点）。"""
    result = scan(REPO)
    bad = problems(result, load_ledger())
    assert not bad, "空键索引元守卫判红：\n" + "\n".join(f"  - {b}" for b in bad)
    # 条数**现取**（不写死仓库规模；读数供人复算）
    print(f"[6226] 现取：Map.of/Map.copyOf 族返回 {len(result['occurrences'])} 处 / "
          f"候选点 {len(result['candidates'])} 个；台账候选 "
          f"{len(load_ledger()['candidates'])} 条 + 已修 {len(load_ledger()['tolerant_fixes'])} 条")


def test_self_check_catches_both_real_sites_reverted_in_memory(tmp_path):
    """⑤ 判别力自证：把两处真站点的修复**在内存里**退回 `Map.of()` ⇒ 必须各自判红并**具名**。"""
    for rel, method, tolerant in (
        ("backend/admin-api/src/main/java/com/migao/admin/service/ProcessingItemService.java",
         "getCategoryNameMap", "return new HashMap<>();"),
        ("backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java",
         "loadOrders", "return new HashMap<>();"),
    ):
        text = (REPO / rel).read_text(encoding="utf-8")
        assert tolerant in text, f"变异注入点不存在（自证坐标失败）：{rel} 里没有 {tolerant!r}"
        mutated = text.replace(tolerant, "return Map.of();", 1)
        assert mutated != text, "变异未生效"
        root = _fake_root(tmp_path / pathlib.Path(rel).stem, {rel: mutated})
        bad = problems(scan(root), load_ledger(), root)
        key = f"{rel}::{method}"
        assert any(key in b for b in bad), f"退回 `Map.of()` 没被判红或没具名：{key}\n{bad}"
        # 反向对照：不注入 ⇒ 同一个 root 上不报这一条
        clean_root = _fake_root(tmp_path / (pathlib.Path(rel).stem + "-clean"), {rel: text})
        assert not any(key in b for b in problems(scan(clean_root), load_ledger(), clean_root))


def test_self_check_catches_new_unregistered_candidate(tmp_path):
    """⑤ 新增一个「`Map.of()` 空表 + 未判空空键索引」的候选点 ⇒ 未登记即红。"""
    rel = "backend/admin-api/src/main/java/com/migao/admin/service/Probe.java"
    root = _fake_root(tmp_path / "new", {rel: _probe(with_defect=True)})
    bad = problems(scan(root), _probe_ledger(rel), root)
    assert any(f"{rel}::nameMap" in b and "未登记" in b for b in bad), bad


def test_self_check_catches_ghost_entry(tmp_path):
    """⑤ 幽灵条目（台账里有、现取没有）⇒ 台账只许缩短 ⇒ 红。"""
    rel = "backend/admin-api/src/main/java/com/migao/admin/service/Probe.java"
    root = _fake_root(tmp_path / "ghost", {rel: _probe(with_defect=False)})
    ledger = _probe_ledger(rel)
    ledger["candidates"] = [{"key": f"{rel}::nameMap", "disposition": "accepted",
                             "why": "幽灵条目红证用（该候选点在现取集合里不存在）"}]
    assert any(f"{rel}::nameMap" in b and "幽灵" in b for b in problems(scan(root), ledger, root))


def test_self_check_catches_false_safe_literal_claim(tmp_path):
    """⑤ 声明 `safe-literal` 但实参不是字面量 ⇒ 声明必须机械为真 ⇒ 红。"""
    rel = "backend/admin-api/src/main/java/com/migao/admin/service/Probe.java"
    root = _fake_root(tmp_path / "false-literal", {rel: _probe(with_defect=True)})
    ledger = _probe_ledger(rel)
    ledger["candidates"] = [{"key": f"{rel}::nameMap", "disposition": "safe-literal",
                             "why": "这条声明是假的（本判据的红证）"}]
    bad = problems(scan(root), ledger, root)
    assert any(f"{rel}::nameMap" in b and "safe-literal" in b for b in bad), bad


def test_self_check_comment_only_change_stays_green(tmp_path):
    """⑤ 对照读数：只改注释 ⇒ **不**红（守卫不被自己的文案喂红）。

    断言口径 = 「这个候选点上没有任何一条判据被喂红」（自证用的作用域台账里
    `candidates` 是空的 ⇒ 「台账空转」那条会照常报，那是台账判据自己的读数、与本条无关）。
    """
    rel = "backend/admin-api/src/main/java/com/migao/admin/service/Probe.java"
    root = _fake_root(tmp_path / "comment", {rel: _probe(with_defect=False) + "\n// 只是加一行注释\n"})
    bad = problems(scan(root), _probe_ledger(rel), root)
    assert not any(f"{rel}::nameMap" in b for b in bad), bad


def _probe_ledger(rel: str) -> dict:
    """自证用的**作用域内**台账（只认这个假根里的那一个方法）——
    与真台账同构，避免「假根里自然产生的幽灵条目」把自证读数搅浑。"""
    return {
        "candidates": [],
        "tolerant_fixes": [{"key": f"{rel}::nameMap",
                            "why": "自证用：该方法的空集分支已改成容忍空键的表（new HashMap<>()）"}],
    }


def _probe(with_defect: bool) -> str:
    body = "        if (ids.isEmpty()) {\n            return Map.of();\n        }\n" if with_defect \
        else "        if (ids.isEmpty()) {\n            return new HashMap<>();\n        }\n"
    return (
        "package com.migao.admin.service;\n\n"
        "import java.util.HashMap;\nimport java.util.List;\nimport java.util.Map;\n\n"
        "class Probe {\n"
        "    Map<String, String> nameMap(List<Row> rows) {\n"
        "        List<String> ids = List.of();\n"
        + body +
        "        return new HashMap<>();\n"
        "    }\n"
        "    void use(List<Row> rows) {\n"
        "        Map<String, String> m = nameMap(rows);\n"
        "        for (Row r : rows) {\n"
        "            System.out.println(m.get(r.getId()));\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


def _fake_root(base: pathlib.Path, files: dict[str, str]) -> pathlib.Path:
    for rel, text in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return base


if __name__ == "__main__":      # 取台账用（只读；打印现取候选点，供人复算）
    res = scan(REPO)
    print(f"occurrences={len(res['occurrences'])} candidates={len(res['candidates'])}")
    for k, v in sorted(res["candidates"].items()):
        print(f"  {k}  args={[a['arg'] for a in v['args']]}")
    print("problems:", problems(res, load_ledger()))
