# case_ids: MC-064
"""Mapper SQL「裸参出现在 PG 无法推断类型的位置」的类级守卫（issue #5975）。

## 缺陷形态（真库实测，不是推断）

`ProductSkuMapper.receiveStock` 的内联 SQL 里有：

```sql
avg_cost = #{newAvgCost},
cost_amount = CASE WHEN #{newAvgCost} IS NULL THEN NULL ELSE ... END
```

`avg_cost = ?` 这一处 PG 能**从目标列**推出 `numeric`；但 `CASE WHEN ? IS NULL` 里的 `?`
**左边没有列、没有 cast、没有函数签名** —— 实参为 **NULL** 时 PG 拿到的是 *unspecified* 类型的
参数，直接抛 `ERROR: could not determine data type of parameter $3`
⇒ `BadSqlGrammarException` ⇒ 接口 **500**。实参非 NULL 时按字面量类型推断、一切正常
—— 这就是「同一轮里有的能过、有的不能过」的机制。

**为什么这条路径必然被走到**：新 SKU ⇒ `avg_cost` 为 NULL；明细留空单价 ⇒
`InboundOrderService.movingAverage(beforeQty, null, qty, null)` 原样返回 `beforeAvg` = NULL
⇒ `receiveStock(..., newAvgCost = null, ...)`。而入库页注释明示「不记单价请留空」
（`frontend/admin-web/src/app/(dashboard)/inbound-orders/new/page.tsx`）⇒
**商家按页面提示操作时，新 SKU 的第一次过账必然 500**。

同类形态**不止这一处写法**：只要 `#{x}` 出现在「没有类型锚点的位置」且实参可能为 NULL，
就同族。本守卫把一个缺陷的修复升级为**一类**约束。

## 判据形态（静态扫描 + 判别力自证）

守卫跑在 CI 的 `ci-workflow-tests` job（`pr-check.yml`）：零真实 DB、零网络、零 LLM。
它扫 `backend/**/src/main/**` 的 Java（MyBatis `@Select/@Update/@Insert/@Delete` 注解 SQL）
与 XML（`<select>/<update>/<insert>/<delete>` 映射文件），把 `#{}` 绑定分两类：

* **有类型锚点** ⇒ 放行：带 `jdbcType=`、或外面套了 cast（`CAST(#{x} AS numeric)` / `#{x}::numeric`
  —— 后两者 `}` 与 `IS NULL` 之间夹了别的东西，正则天然不命中）；
* **类型盲区**（本守卫判红）：
  1. `#{x}` 紧跟 `IS NULL` / `IS NOT NULL`（空值判定的**主语**）；
  2. `#{x}` 紧跟 `WHEN`（`CASE WHEN #{x}` / `WHEN #{x} = ?` 的**布尔主语**）。

命中且未登记 ⇒ **红**（具名到 `文件:行:绑定`，并直接给出修法）。

## 自证（防「仓库全绿只是空跑」）

1. `test_scan_covers_the_known_defect_site`：扫描面必须**真的覆盖** #5975 的缺陷点文件，
   且全仓 `#{}` 绑定数 > 0（扫了个空集 ⇒ 后面的断言恒绿 = 假绿）；
2. `test_known_defect_site_binding_is_typed`：缺陷点现在必须是**带类型**的形态（对照读数
   —— 证明本守卫认的是「绑定有没有类型」而不是「文件变没变」）；把 `jdbcType=NUMERIC` 去掉 ⇒ 红；
3. 判别力自证（8 种坏/好形态在内存文本上各自判定）：裸 `IS NULL` / `IS NOT NULL` / `CASE WHEN #{x}`
   判红；`jdbcType=` / `CAST(...)` / `#{x}::numeric` / 纯比较位（有列锚点）/ **注释里提一句**
   判**不**红 —— 最后一条尤其要紧：判据不许被自己的文案喂红（§17.3 家族）；
4. `test_xml_mapper_form_is_scanned`：XML 面同样在扫描射程内（仓内现取 0 份 XML mapper ⇒
   用 tmp_path 造的 XML 语料证明它真被读进来，而不是「glob 写了个空集」）。

## 豁免台账

`tests/unit_ci_workflows/mapper_param_type_ledger.json`：命中即红，除非登记；登记必须带
`reason` + `case_ids` **且必须是活的命中**（修好后条目变死 ⇒ 判红 ⇒ 台账**只许缩短**）；
条数上限 `max_exemptions` 另受本文件 `FROZEN_MAX_EXEMPTIONS` 冻结（放一条要同时改两处）。
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests"))

# 剥 Java 注释**复用仓内唯一实现**（引号感知、字符串原样保留 —— 注解 SQL 就在字符串里）：
# 不再自写第二把尺子（`#5323` 收敛纪律；唯一性判据 = test_automerge_bot_safe_path.py 的判据 11）。
from unit_ci_workflows._source_parsing import java_code  # noqa: E402

#: 扫描面：MyBatis 注解 SQL（Java）+ XML 映射文件。**只扫 src/main**（测试里的 SQL 片段不算生产契约）。
MAIN_GLOBS = ("backend/**/src/main/**/*.java", "backend/**/src/main/**/*.xml")

LEDGER = Path(__file__).resolve().parent / "mapper_param_type_ledger.json"

#: #5975 的缺陷点（扫描面覆盖锚 —— 改文件/改方法名 ⇒ 本守卫红，锚点必须同步）。
KNOWN_DEFECT_SITE = (
    "backend/admin-api/src/main/java/com/migao/admin/mapper/ProductSkuMapper.java"
)

#: 豁免条数上限的**冻结值**（只许缩短）。放行一条豁免要同时改本常量与台账的 `max_exemptions`
#: —— 两处都改 = 一次被评审的动作，防「台账自己给自己盖章」。
FROZEN_MAX_EXEMPTIONS = 0

#: 类型盲区形态（判红）：① 空值判定的主语；② CASE WHEN 的布尔主语。
NULL_TEST_RE = re.compile(r"#\{([^}]*)\}\s*IS\s+(?:NOT\s+)?NULL", re.IGNORECASE)
#: `(?!\s*::)` —— `#{x}::numeric` 自带 cast（PG 拿到类型）⇒ 不算盲区，不许误报。
WHEN_SUBJECT_RE = re.compile(r"\bWHEN\s+#\{([^}]*)\}(?!\s*::)", re.IGNORECASE)

#: 绑定里声明了类型 ⇒ 有锚点（MyBatis 会 setNull(i, jdbcType) 让 PG 拿到类型）。
EXPLICIT_TYPE_RE = re.compile(r"jdbcType\s*=", re.IGNORECASE)

#: XML 面只去 `<!-- -->`（另一族；Java 词法器不适用）。
XML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

#: 全仓 `#{}` 绑定计数（覆盖锚：0 ⇒ 扫描面是空的 ⇒ 判红）。
ANY_BINDING_RE = re.compile(r"#\{[^}]*\}")


@dataclass(frozen=True)
class Hit:
    """一处**类型盲区且未显式声明类型**的绑定。"""

    path: str
    line: int
    binding: str
    form: str

    @property
    def key(self) -> str:
        return f"{self.path}::{self.binding}"

    def __str__(self) -> str:
        fix = "jdbcType=NUMERIC" if self.form != "when_subject" else "jdbcType=<类型>"
        return (f"{self.path}:{self.line} 「{self.form}」处的裸参 {self.binding} 没有类型锚点 "
                f"⇒ NULL 实参时 PG 报 `could not determine data type of parameter $N`；"
                f"修法 = 写 {self.binding[:-1]},{fix}}} 或给 SQL 加 cast")


def scan_text(src: str, label: str) -> tuple[list[Hit], int]:
    """单文件扫描 ⇒ (命中清单, 该文件的 `#{}` 绑定总数)。

    Java 侧剥注释走 `unit_ci_workflows._source_parsing.java_code`（唯一实现，字符串原样保留）；
    XML 侧另去 `<!-- -->`。等长替换 ⇒ 行号不变。
    """
    text = XML_COMMENT_RE.sub(" ", src) if label.endswith(".xml") else java_code(src)
    hits: list[Hit] = []
    seen: set[tuple[int, str]] = set()
    for regex, form in ((NULL_TEST_RE, "is_null"), (WHEN_SUBJECT_RE, "when_subject")):
        for match in regex.finditer(text):
            body = match.group(1)
            if EXPLICIT_TYPE_RE.search(body):
                continue
            line = text.count("\n", 0, match.start()) + 1
            if (line, body) in seen:
                continue
            seen.add((line, body))
            hits.append(Hit(path=label, line=line, binding="#{" + body + "}", form=form))
    return hits, len(ANY_BINDING_RE.findall(text))


def scan_tree(root: Path) -> tuple[list[Path], list[Hit], int]:
    """扫 `root` 下的生产面 ⇒ (文件清单, 命中清单, 绑定总数)。"""
    files: list[Path] = []
    for pattern in MAIN_GLOBS:
        files.extend(sorted(root.glob(pattern)))
    files = sorted(set(files))
    hits: list[Hit] = []
    total = 0
    for path in files:
        file_hits, file_total = scan_text(
            path.read_text(encoding="utf-8", errors="ignore"), str(path.relative_to(root)))
        hits.extend(file_hits)
        total += file_total
    return files, hits, total


def ledger() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


# ────────────────────────────────────────────── 判据

def test_scan_covers_the_known_defect_site() -> None:
    """覆盖锚：扫描面必须真的读到 #5975 的缺陷点，且全仓绑定数 > 0（防空跑成假绿）。"""
    files, _hits, total = scan_tree(REPO)
    rel = [str(p.relative_to(REPO)) for p in files]
    assert KNOWN_DEFECT_SITE in rel, (
        f"扫描面没覆盖到 #5975 的缺陷点 {KNOWN_DEFECT_SITE} —— 扫描 glob / 目录布局改了 ⇒ 本守卫失锚，"
        f"必须同步（现取 {len(files)} 份文件）")
    assert total > 0, f"全仓 `#{{}}` 绑定数为 0 ⇒ 扫描面是空的（假绿），现取文件数 {len(files)}"


def test_known_defect_site_binding_is_typed() -> None:
    """对照读数：缺陷点现在是**带类型**的绑定（去掉 jdbcType ⇒ 本守卫与真库判据同时红）。"""
    src = (REPO / KNOWN_DEFECT_SITE).read_text(encoding="utf-8")
    hits, total = scan_text(src, KNOWN_DEFECT_SITE)
    assert total > 0, "缺陷点文件里没有 `#{}` 绑定 ⇒ 判据失锚"
    assert hits == [], "缺陷点又出现了无类型锚点的裸参：" + "；".join(str(h) for h in hits)
    assert "jdbcType=NUMERIC" in src, (
        "缺陷点少了显式 jdbcType ⇒ 新 SKU 首次入库「不记单价」时 PG 推断不出参数类型 ⇒ 500（#5975）")


def test_no_unregistered_bare_param_in_type_blind_context() -> None:
    """主判据：生产面里**没有未登记**的类型盲区裸参。命中 ⇒ 具名报出（文件:行:绑定 + 修法）。"""
    _files, hits, _total = scan_tree(REPO)
    registered = {e["key"] for e in ledger()["exemptions"]}
    unregistered = [h for h in hits if h.key not in registered]
    assert unregistered == [], (
        "Mapper SQL 里出现「PG 无法推断参数类型」的裸参（NULL 实参会 500，issue #5975）：\n  "
        + "\n  ".join(str(h) for h in unregistered)
        + "\n修法 = 给绑定写 jdbcType=<类型>，或给 SQL 加 cast（CAST(#{x} AS numeric) / #{x}::numeric）。"
        + "确有正当理由 ⇒ 登记进 mapper_param_type_ledger.json（须带 reason + case_ids）。")


def test_exemptions_are_live_and_justified() -> None:
    """台账只许缩短：每条登记必须是**活的**命中，且带 reason + case_ids（死条目/空口登记 ⇒ 红）。"""
    _files, hits, _total = scan_tree(REPO)
    live = {h.key for h in hits}
    problems: list[str] = []
    for entry in ledger()["exemptions"]:
        if entry.get("key") not in live:
            problems.append(f"死条目（已修好却还挂在台账里，应删除）：{entry.get('key')}")
        for field in ("reason", "case_ids"):
            if not entry.get(field):
                problems.append(f"{entry.get('key')} 缺 {field}")
    assert problems == [], "豁免台账不合规：\n  " + "\n  ".join(problems)


def test_exemption_budget_does_not_grow() -> None:
    """条数上限冻结（只许缩短）：台账自报的上限不得超过守卫里的冻结值，实存条数不得超过上限。"""
    data = ledger()
    assert isinstance(data["max_exemptions"], int), "max_exemptions 必须是整数"
    assert data["max_exemptions"] <= FROZEN_MAX_EXEMPTIONS, (
        f"台账把豁免上限抬到 {data['max_exemptions']}（冻结值 {FROZEN_MAX_EXEMPTIONS}）—— "
        "豁免只许缩短；确需放行请连同 FROZEN_MAX_EXEMPTIONS 一起改（一次被评审的动作）")
    assert len(data["exemptions"]) <= data["max_exemptions"], (
        f"实存豁免 {len(data['exemptions'])} 条 > 上限 {data['max_exemptions']}")


# ────────────────────────────────────────────── 判别力自证（内存/临时语料，双向量）

def test_blind_context_forms_are_flagged() -> None:
    """三种坏形态必须各自判红（否则守卫对同类没有牙）。"""
    cases = {
        "is_null": '@Update("UPDATE t SET a = CASE WHEN #{cost} IS NULL THEN NULL ELSE 1 END")',
        "is_not_null": '@Select("SELECT 1 FROM t WHERE #{flag} IS NOT NULL")',
        "when_subject": '@Select("SELECT CASE WHEN #{flag} THEN 1 ELSE 0 END FROM t")',
    }
    for form, src in cases.items():
        hits, total = scan_text(src, f"fixture-{form}.java")
        assert total > 0, f"{form}: fixture 里没有绑定 ⇒ 注入没生效"
        assert len(hits) == 1, f"{form}: 裸参未被判红（hits={hits}）"


def test_anchored_forms_are_not_flagged() -> None:
    """有类型锚点 / 不是类型盲区的位置**一律不误报**（含注释里的提及）。"""
    clean = {
        "jdbc_type": '@Update("UPDATE t SET a = CASE WHEN #{cost,jdbcType=NUMERIC} IS NULL THEN NULL ELSE 1 END")',
        "cast_as": '@Update("UPDATE t SET a = CASE WHEN CAST(#{cost} AS numeric) IS NULL THEN NULL ELSE 1 END")',
        "pg_cast": '@Update("UPDATE t SET a = CASE WHEN #{cost}::numeric IS NULL THEN NULL ELSE 1 END")',
        "column_anchor": '@Update("UPDATE t SET avg_cost = #{cost} WHERE id = #{id}")',
        "when_on_column": '@Select("SELECT CASE WHEN avg_cost IS NULL THEN 1 ELSE 0 END FROM t")',
        "comment_only": "// 注意：CASE WHEN #{cost} IS NULL 这种写法在实参为 null 时会 500（#5975）\n"
                        '@Update("UPDATE t SET a = #{cost}")',
    }
    for name, src in clean.items():
        hits, _total = scan_text(src, f"fixture-{name}.java")
        assert hits == [], f"{name}: 误报（hits={[str(h) for h in hits]}）"


def test_xml_mapper_form_is_scanned(tmp_path: Path) -> None:
    """XML 面同样在射程内：仓内现取 0 份 XML mapper ⇒ 用 tmp_path 真造一份证明它被读进来。"""
    java_dir = tmp_path / "backend" / "admin-api" / "src" / "main" / "java" / "com" / "m" / "mapper"
    res_dir = tmp_path / "backend" / "admin-api" / "src" / "main" / "resources" / "mapper"
    java_dir.mkdir(parents=True)
    res_dir.mkdir(parents=True)
    (java_dir / "Kept.java").write_text('@Select("SELECT 1 FROM t WHERE id = #{id}")', encoding="utf-8")
    (res_dir / "Broken.xml").write_text(
        '<mapper><update id="u">UPDATE t SET a = CASE WHEN #{cost} IS NULL THEN NULL ELSE 1 END</update>'
        "</mapper>", encoding="utf-8")

    files, hits, total = scan_tree(tmp_path)
    rel = [str(p.relative_to(tmp_path)) for p in files]
    assert any(p.endswith("Broken.xml") for p in rel), f"XML 映射文件不在扫描面内：{rel}"
    assert total >= 2, f"绑定没被数到（total={total}）"
    assert len(hits) == 1 and hits[0].path.endswith("Broken.xml"), \
        f"XML 里的裸参未被判红（hits={[str(h) for h in hits]}）"


def test_temp_java_tree_injection_red_and_clean(tmp_path: Path) -> None:
    """真语料的双向量：同一份 Java 语料，注入裸参 ⇒ 红；换成带类型 ⇒ 不红（证明判别力来自形态）。"""
    java_dir = tmp_path / "backend" / "admin-api" / "src" / "main" / "java" / "com" / "m"
    java_dir.mkdir(parents=True)
    fixture = java_dir / "M.java"

    fixture.write_text('@Update("UPDATE t SET a = CASE WHEN #{cost} IS NULL THEN NULL ELSE 1 END")',
                       encoding="utf-8")
    _files, hits, _total = scan_tree(tmp_path)
    assert len(hits) == 1, "注入的裸参未被判红"

    fixture.write_text(
        '@Update("UPDATE t SET a = CASE WHEN #{cost,jdbcType=NUMERIC} IS NULL THEN NULL ELSE 1 END")',
        encoding="utf-8")
    _files, hits, _total = scan_tree(tmp_path)
    assert hits == [], f"带类型后仍误报：{[str(h) for h in hits]}"
