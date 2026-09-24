# case_ids: MC-012
"""B7（issue #5245）：本体 `properties[].source` ↔ Java 实体字段 / 建库脚本 DB 列 的**机械对账**。

## 为什么需要（此前的形态 = 「挂载点从未被对账」）

`backend/ai-agent-service/app/ontology/schema.yaml` 的每个属性都声明了 `source`（挂载点），
而**没有任何判据**校验它真的存在 —— 于是本体里长期住着 `ProductSku.status` /
`ProductSku.attributes` / `AfterSalesTicket.type` 这类**从来不存在的字段**（issue #5245 的
B1/B2/B3 逐条改成真实载体）。它们不会让任何东西变红：本体读起来像字段真值，
而真值是「查无此字段」。本判据把「挂载点必须落地」变成机器可判。

## 判据（缺一即红）

`source` 必须形如 `<实体简单名>.<Java 字段名>`，且**四件事同时成立**：

| # | 判据 | 红证（注入） |
|---|---|---|
| ① | 形态正确（`^[A-Z]\\w*\\.\\w+$`） | 写成裸字段名 / 带包路径 ⇒ 红 |
| ② | 实体类 `backend/admin-api/src/main/java/com/migao/admin/entity/<实体>.java` **存在** | 实体名拼错一个字母 ⇒ 红 |
| ③ | 该实体**声明了这个字段**（`private` 声明，`@TableField(exist=false)` 除外） | 凭空字段（如 `ProductSku.status`）⇒ 红 |
| ④ | 该字段映射到的 **DB 列在建库脚本里存在**（`@TableField("col")` 或 camel→snake；表名取 `@TableName`） | 把列从建库脚本里删掉而本体仍引用 ⇒ 红 |

## fail-closed（本仓最忌讳「绿了但没跑」）

schema.yaml 读不到 / 顶层不是映射 / `objects` 为空 / 某对象没有 `properties` / 建库脚本解析出
零张表 ⇒ **直接判红**，并把**读了哪些文件**写进断言消息。**绝不**把「解析不到」当成「通过」。

## 零依赖

只用 `re` / `pathlib` / `yaml`（`pyyaml` 是 `ci workflow helper unit tests` job 已装的依赖）。
**不** import `app.*` / pydantic —— 那会让本文件在该 job 里 import 失败 ⇒ 静默 skip = 没跑。
共享的 DDL / 实体解析件是仓内纯 `re` 模块 `tests/unit_ci_workflows/_sql_schema.py`（同一份实现，
`test_schema_integrity.py` 也用它 —— 不复制第二份解析器）。
"""
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent

# 共享解析件（issue #5245）：`tests/` 上 sys.path 才能按**包名**导入；直接以脚本运行时也补一次。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from unit_ci_workflows._sql_schema import (  # noqa: E402
    ENTITY_DIR,
    SCHEMA,
    SchemaParseError,
    parse_entities,
    parse_schema_columns,
    parse_schema_columns_strict,
)

ONTOLOGY = REPO / "backend" / "ai-agent-service" / "app" / "ontology" / "schema.yaml"

#: `<实体简单名>.<Java 字段名>`（实体名是 Java 类名 ⇒ 首字母大写）
SOURCE_RE = re.compile(r"^([A-Z]\w*)\.(\w+)$")


def read_ontology_sources(path: Path = ONTOLOGY) -> list:
    """schema.yaml → `[(对象, 属性, source)]`；**解析失败 fail-closed**（不是「没得查 ⇒ 通过」）。"""
    import yaml

    assert path.is_file(), f"fail-closed：本体 schema 不存在（读了 {path}）"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:  # pragma: no cover - 只在文件被写坏时命中
        raise AssertionError(f"fail-closed：YAML 解析失败（读了 {path}）：{e}") from e
    assert isinstance(data, dict), f"fail-closed：{path} 顶层不是映射（读了 {path}）"
    objects = data.get("objects")
    assert isinstance(objects, dict) and objects, (
        f"fail-closed：{path} 里读不到 objects 映射 —— 解析失败**不**等于通过（读了 {path}）")
    out = []
    for name, spec in objects.items():
        props = (spec or {}).get("properties")
        assert isinstance(props, dict) and props, (
            f"fail-closed：{path} 的对象 {name} 没有可解析的 properties（读了 {path}）")
        for pname, prop in props.items():
            out.append((name, pname, str((prop or {}).get("source") or "")))
    assert out, f"fail-closed：{path} 的 objects 里一个属性都没解析出来（读了 {path}）"
    return out


def unresolved_sources(sources, entities, columns, *, schema_path=SCHEMA,
                       entity_dir=ENTITY_DIR) -> list:
    """逐条判 `source` 能否落地 → 违规明细（空列表 = 全部落地）。

    抽成**纯函数**是为了让注入式红证复用同一份判据（不是在测试里另写一套比对）。
    """
    bad = []
    for obj, pname, src in sources:
        m = SOURCE_RE.match(src)
        if not m:
            bad.append(f"{obj}.{pname}: source={src!r} 不是 `<实体>.<字段>` 形态")
            continue
        ent, field = m.groups()
        meta = entities.get(ent)
        if meta is None:
            bad.append(f"{obj}.{pname}: source={src!r} —— 实体类 {ent} 不存在"
                       f"（查了 {entity_dir}/*.java；拼错实体名？）")
            continue
        col = meta["fields"].get(field)
        if col is None:
            bad.append(f"{obj}.{pname}: source={src!r} —— {meta['file']} 没有字段 {field}"
                       f"（凭空字段：本体引用的挂载点在 Java 实体里不存在）")
            continue
        table = meta["table"]
        if table not in columns:
            bad.append(f"{obj}.{pname}: source={src!r} → 表 {table} 不在建库脚本里"
                       f"（查了 {schema_path}）")
        elif col not in columns[table]:
            bad.append(f"{obj}.{pname}: source={src!r} → 列 {table}.{col} 不在建库脚本里"
                       f"（列被删/改名？查了 {schema_path}）")
    return bad


def _real_inputs():
    # 严格入口：建库脚本解析出 0 表 / 0 列 ⇒ 直接抛（不是「没得查 ⇒ 通过」）
    return read_ontology_sources(), parse_entities(), parse_schema_columns_strict()


# ══════════════════════════════════════════════════════════════════════════════════
# 自检：解析真的产出了东西（否则下面那条判据空转 = 假绿）
# ══════════════════════════════════════════════════════════════════════════════════

def test_inputs_are_parsable_and_non_trivial():
    """fail-closed 的**正向**面：两个数据源都必须解析出足够多的东西，且打印读了哪些文件。"""
    sources, entities, columns = _real_inputs()
    evidence = (f"读了：{ONTOLOGY}（属性 {len(sources)} 条） / {ENTITY_DIR}/*.java"
                f"（实体 {len(entities)} 个，字段 "
                f"{sum(len(v['fields']) for v in entities.values())} 个） / {SCHEMA}"
                f"（表 {len(columns)} 张）")
    assert len(sources) >= 30, f"本体属性过少（{len(sources)}）—— 解析疑似失效；{evidence}"
    assert len(entities) >= 20, f"实体过少（{len(entities)}）—— 解析疑似失效；{evidence}"
    assert len(columns) >= 30, f"建库脚本表过少（{len(columns)}）—— 解析疑似失效；{evidence}"


# ══════════════════════════════════════════════════════════════════════════════════
# 主判据
# ══════════════════════════════════════════════════════════════════════════════════

def test_every_ontology_source_resolves_to_a_real_carrier():
    """🔴 本体每个 `properties[].source` 必须落地到真实 Java 字段 + 真实 DB 列。"""
    sources, entities, columns = _real_inputs()
    bad = unresolved_sources(sources, entities, columns)
    assert not bad, (
        "以下本体挂载点（`source`）**落不了地** —— 本体读起来像字段真值，实际查无此字段：\n  "
        + "\n  ".join(bad)
        + f"\n（判据：实体类存在 ∧ 实体声明该字段 ∧ 该字段的 DB 列在 {SCHEMA} 里存在）"
          "\n修法：把 `source` 改成**真实载体**（同 #5245 B1/B2/B3 的口径：清漂移、不扩本体），"
          "或在实体/建库脚本里补齐该字段（后者要先问「它该不该存在」）。"
    )


# ══════════════════════════════════════════════════════════════════════════════════
# 注入式红证：每条判据各自能单独变红（不会红的断言 = 空断言）
# ══════════════════════════════════════════════════════════════════════════════════

def test_phantom_field_is_red():
    """红证 ①/③：本体引用一个**字段不存在的**挂载点（`ProductSku.status`）⇒ 必红。"""
    sources, entities, columns = _real_inputs()
    injected = sources + [("product_sku", "status", "ProductSku.status")]
    bad = unresolved_sources(injected, entities, columns)
    assert any("ProductSku.status" in b and "没有字段 status" in b for b in bad), (
        f"凭空字段必须被判红（实际：{bad}）—— 否则本判据是空断言（#5245 B1 之前 "
        f"`ProductSku.status` 就是这样活下来的）")
    # 负控：同一批里合法条目**不得**被误伤
    assert not unresolved_sources(sources, entities, columns), "合法条目被误判 ⇒ 判据过严"


def test_misspelled_entity_name_is_red():
    """红证 ②：实体名拼错一个字母 ⇒ 必红（且消息里点名**查了哪个目录**）。"""
    sources, entities, columns = _real_inputs()
    injected = sources + [("order", "status", "Ordr.status")]
    bad = unresolved_sources(injected, entities, columns)
    assert any("Ordr.status" in b and "实体类 Ordr 不存在" in b for b in bad), (
        f"拼错的实体名必须被判红（实际：{bad}）")


def test_column_removed_from_build_script_is_red():
    """红证 ④：把**建库脚本里的一列**删掉而本体仍引用它 ⇒ 必红（真文件手术，不是模拟）。"""
    sources, entities, columns = _real_inputs()
    # 挑一个本体真的引用、且其列由 `ALTER TABLE ... ADD COLUMN` 提供的源（`orders.discount_amount`）
    target = [s for s in sources if s[2] == "Order.discountAmount"]
    assert target, "本体里没有 `Order.discountAmount` ⇒ 本红证的前提变了，请同步（别删这条判据）"
    assert "discount_amount" in columns["orders"], "前提：该列此刻确实在建库脚本里"

    sql = SCHEMA.read_text(encoding="utf-8")
    line = "ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_amount DECIMAL(12,2) DEFAULT 0;"
    assert line in sql, "建库脚本里找不到该列的 ALTER 行 ⇒ 本红证的注入点变了，请同步"
    doctored = parse_schema_columns(sql.replace(line, ""))
    assert "discount_amount" not in doctored["orders"], "注入没生效（假红证）"

    bad = unresolved_sources(sources, doctored, columns={})  # 用注入后的解析结果
    assert any("Order.discountAmount" in b for b in bad), (
        f"列被删而本体仍引用 ⇒ 必须判红（实际：{bad}）")
    # 负控：注入前的真实解析结果必须**无**该违规（证明红来自那次手术，不是本来就红）
    assert not any("Order.discountAmount" in b
                   for b in unresolved_sources(sources, entities, doctored | {"orders": columns["orders"]})), \
        "注入前的对照面也报红 ⇒ 上一条不是「因注入而红」"


def test_parse_failure_fails_closed_not_green():
    """红证 ⑤（fail-closed）：本体读不到 / 建库脚本解析出零张表 ⇒ **判红**，不是「没得查 ⇒ 绿」。"""
    tmp = Path(pytest.importorskip("tempfile").mkdtemp()) / "schema.yaml"
    tmp.write_text("version: '1.0'\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="fail-closed"):
        read_ontology_sources(tmp)

    tmp2 = Path(pytest.importorskip("tempfile").mkdtemp()) / "schema.yaml"
    tmp2.write_text("version: '1.0'\nobjects:\n  order:\n    display_name: 订单\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="fail-closed"):
        read_ontology_sources(tmp2)

    # 建库脚本解析出零张表 ⇒ 严格入口直接抛（**机制**，不靠调用方记得判空）
    with pytest.raises(SchemaParseError, match="fail-closed"):
        parse_schema_columns_strict("-- 什么都没有\n")
    # 兜底反向断言：即便有人绕过严格入口用宽松版，判据也不会因此变绿
    sources, entities, _ = _real_inputs()
    empty_columns = parse_schema_columns("-- 什么都没有\n")
    assert empty_columns == {}, "空脚本必须解析出零张表（前提）"
    assert unresolved_sources(sources, entities, empty_columns), (
        "建库脚本解析出零张表却没有任何违规 ⇒ 解析失败被当成了通过（本仓最忌讳的形态）")


def test_comment_mention_does_not_satisfy_resolution():
    """**负控**：把列名只写进**注释**⇒ 不算落地（防「判据被自己的文案喂绿」）。"""
    sources, entities, columns = _real_inputs()
    injected = sources + [("order", "ghost", "Order.ghostColumn")]
    doctored = parse_schema_columns(
        SCHEMA.read_text(encoding="utf-8") + "\n-- ORDER.ghost_column 是注释里提到的列\n")
    bad = unresolved_sources(injected, entities, doctored)
    assert any("Order.ghostColumn" in b for b in bad), (
        "注释里提到列名就算落地 ⇒ 判据会被文案喂绿（实际：注释不该改变结论）")