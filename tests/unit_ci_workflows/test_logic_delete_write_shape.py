# case_ids: PG-020, PG-032
"""逻辑删除**写形态**守卫：禁止「同一方法体内 `setDeleted(0/1)` 之后调用 `updateById(`」（issue #4608）。

## 缺陷形态（字节码级实证，不是猜测）

`backend/admin-api/src/main/resources/application.yml` 配了 MyBatis-Plus **全局逻辑删除**：

```yaml
mybatis-plus:
  global-config:
    db-config:
      logic-delete-field: deleted
      logic-delete-value: 1
      logic-not-delete-value: 0
```

MyBatis-Plus 3.5.8 在**开了逻辑删除的表**上，`updateById` 会把逻辑删除字段**从 SET 子句里剔除**
（框架认为那一列归自己管）：

- `TableInfo.lambda$getAllSqlSet$6(boolean ignoreLogicDelFiled, TableFieldInfo i)`：
  `ignoreLogicDelFiled && isWithLogicDelete() && i.isLogicDelete()` ⇒ **返回 false（该字段被滤掉）**；
- `UpdateById` 传给 `sqlSet(...)` 的第一个布尔 = `tableInfo.isWithLogicDelete()` ⇒ **true**。

⇒ `entity.setDeleted(1); mapper.updateById(entity);` **只更新了别的列**，`deleted` 那一列从没被写，
而 `updateById` 仍返回成功（它确实匹配到 1 行）⇒ **服务端报成功、数据还在**（用户原话：
「删除后提示成功但是数据仍然在」）。本仓 issue #4608 的三处软删（删条件工序规则 / 删工艺路线 /
删工序）此前**全是这个写法**，即三处删除全是**静默 no-op**。

**为什么单测没拦住**：三处的单测是 mock（`verify(mapper).updateById(captor)` + 断言 captor 里
`deleted=1`）—— 断言的是「我们塞进实体的值」，**不是 DB 实际写了什么**。本守卫补的正是这一层：
静态锁定**调用形态**，与运行期 mock 断言互补（形态错了 ⇒ 无论实体里塞了什么，那一列都不会落库）。

## 判据形态（为什么是静态扫描而不是跑 DB）

本文件跑在 CI 的 `ci workflow helper unit tests` job（`pr-check.yml`）里，**零真实 DB、零网络、
零 LLM**：admin-api 无 testcontainers/H2（见 `ProductionRoutingCommandServiceTest` 的注释），
「真的写进 DB 了吗」在单测里**不可判**。可判的是**写法**：写了 `setDeleted(...)` 又走 `updateById`
⇒ 那一列必然不落库（框架行为已实证）。

## 正确写法（issue #4608 冻结）

```java
mapper.update(null, new LambdaUpdateWrapper<Xxx>()
        .eq(Xxx::getId, id)
        .set(Xxx::getDeleted, 1)
        .set(Xxx::getUpdatedAt, OffsetDateTime.now()));
```

显式 `.set(...)` 绕过字段剔除，同时**保住审计字段 `updated_at`**（三处 javadoc 都写明
「谁在什么时候删的」是排查的唯一证据）—— 故**不**改用 `deleteById(id)`（它能真删但不推进 `updated_at`）。

## 自证（防「仓库绿只是空跑」）

1. `test_scan_covers_the_known_soft_delete_sites`：扫描集必须**真的覆盖**三处已知软删点所在文件
   （扫了个空集 ⇒ 后面那条断言恒绿 = 假绿）；
2. `test_injected_updateById_form_is_detected` / `test_injected_resurrect_form_is_detected`：
   往临时副本塞**禁用形态**（含复活 `setDeleted(0)`）⇒ **仍判红**（并附**内容指纹**自证注入真的落盘了）；
3. `test_legal_explicit_column_form_is_not_flagged`：塞**合法形态**（显式写列）⇒ **不误报**
   （同样附内容指纹自证 —— 否则"不误报"可能只是注入没生效）。
"""
from __future__ import annotations

import hashlib
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: 生产代码里的 Java 源（**不含测试**：测试用 builder 造 `deleted=1` 的实体是合法的）。
JAVA_GLOB = "backend/**/src/main/java/**/*.java"

#: 守卫的「扫描确实覆盖到被测对象」锚点 = issue #4608 的三处软删点。
#: 改方法名 / 挪文件 ⇒ 本守卫会红（锚点要同步，不许静默失锚）。
KNOWN_SITES = (
    ("backend/admin-api/src/main/java/com/migao/admin/service/ProductionRoutingCommandService.java",
     "deleteRouting"),
    ("backend/admin-api/src/main/java/com/migao/admin/service/ProductionRoutingCommandService.java",
     "deleteRouteRule"),
    ("backend/admin-api/src/main/java/com/migao/admin/service/ProductionOperationCommandService.java",
     "delete"),
)

#: 禁用形态 = 逻辑删除字段走**实体 setter**（会被 MP 从 SET 里剔除）。
SET_DELETED_RE = re.compile(r"\.setDeleted\s*\(\s*([01])\s*\)")
UPDATE_BY_ID_RE = re.compile(r"\.updateById\s*\(")

#: 合法形态的必需片段（压缩空白后比对，容忍排版差异）。
LEGAL_NEEDLES = ("update(null,newLambdaUpdateWrapper", "::getDeleted,1)", "::getUpdatedAt,")

#: 方法声明。两条分支都要有：① **修饰符打头**（本仓三处软删点都是这种）；
#: ② 无修饰符的包级私有方法（`Map<String, Object> softDelete(String id) {`）——
#: 漏掉第 ② 类会让「把方法改成无修饰符」成为绕过守卫的路径。
METHOD_START_RE = re.compile(
    r"(?:\b(?:public|private|protected|static|final|synchronized|abstract|native|default)\b[^;{}()]*"
    r"|(?:^|[;{}])\s*[\w<>\[\],.?\s]*)"
    r"\b([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:throws\s+[\w.,\s]+?)?\{"
)

#: 第 ② 条分支会命中 `if (` / `catch (` 这类块 ⇒ 按名排除（它们不是方法体）。
NON_METHOD_NAMES = frozenset({
    "if", "for", "while", "switch", "catch", "try", "do", "else", "synchronized", "new", "return",
})


@dataclass(frozen=True)
class Hit:
    """一处禁用形态：`path#method` 里第 `set_line` 行 `setDeleted(...)`，其后第 `update_line` 行 `updateById(`。"""

    path: str
    method: str
    set_line: int
    update_line: int

    def __str__(self) -> str:
        return (f"{self.path}#{self.method}: 第 {self.set_line} 行 setDeleted(...) "
                f"⇒ 第 {self.update_line} 行 updateById(...)")


def strip_comments_and_strings(src: str) -> str:
    """把注释 / 字符串字面量**替换成等长空白**（保留换行 ⇒ 行号不变）。

    必须做这一步：javadoc 里满是 `{@code ...}` 大括号，直接数括号会把方法边界算错；
    字符串里的 `updateById(` 也不该算命中。
    """
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            end = src.find("\n", i)
            end = n if end < 0 else end
            for k in range(i, end):
                out[k] = " "
            i = end
        elif ch == "/" and i + 1 < n and src[i + 1] == "*":
            end = src.find("*/", i + 2)
            end = n if end < 0 else end + 2
            for k in range(i, end):
                if out[k] != "\n":
                    out[k] = " "
            i = end
        elif ch == '"':
            if src.startswith('"""', i):
                end = src.find('"""', i + 3)
                end = n if end < 0 else end + 3
            else:
                end = i + 1
                while end < n:
                    if src[end] == "\\":
                        end += 2
                        continue
                    if src[end] == '"':
                        end += 1
                        break
                    end += 1
            for k in range(i, min(end, n)):
                if out[k] != "\n":
                    out[k] = " "
            i = end
        elif ch == "'":
            end = i + 1
            while end < n:
                if src[end] == "\\":
                    end += 2
                    continue
                if src[end] == "'":
                    end += 1
                    break
                end += 1
            for k in range(i, min(end, n)):
                if out[k] != "\n":
                    out[k] = " "
            i = end
        else:
            i += 1
    return "".join(out)


def method_ranges(stripped: str) -> list[tuple[int, int, str]]:
    """`(start, end, name)` 列表：方法声明起点 → 配对右括号之后（大括号计数法）。"""
    ranges: list[tuple[int, int, str]] = []
    for match in METHOD_START_RE.finditer(stripped):
        if match.group(1) in NON_METHOD_NAMES:
            continue
        open_brace = match.end() - 1
        depth = 0
        for j in range(open_brace, len(stripped)):
            if stripped[j] == "{":
                depth += 1
            elif stripped[j] == "}":
                depth -= 1
                if depth == 0:
                    ranges.append((match.start(), j + 1, match.group(1)))
                    break
    return ranges


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def scan_text(src: str, label: str) -> list[Hit]:
    """单文件扫描：`setDeleted(0/1)` 之后（同一方法体内）出现 `updateById(` ⇒ 一处命中。"""
    stripped = strip_comments_and_strings(src)
    ranges = method_ranges(stripped)
    hits: list[Hit] = []
    for set_match in SET_DELETED_RE.finditer(stripped):
        pos = set_match.start()
        # 取**最内层**包含该调用的方法体（setDeleted 可能写在方法里的 if 块 / lambda 内）。
        enclosing = [r for r in ranges if r[0] <= pos < r[1]]
        if not enclosing:
            continue
        start, end, name = min(enclosing, key=lambda r: r[1] - r[0])
        after = UPDATE_BY_ID_RE.search(stripped, pos, end)
        if after is None:
            continue
        hits.append(Hit(path=label, method=name,
                        set_line=line_of(src, pos), update_line=line_of(src, after.start())))
    return hits


def scan_tree(root: Path, pattern: str = JAVA_GLOB) -> tuple[list[Path], list[Hit]]:
    """扫描 `root` 下 `pattern` 命中的全部 Java 文件 → (文件清单, 命中清单)。"""
    files = sorted(root.glob(pattern))
    hits: list[Hit] = []
    for path in files:
        hits.extend(scan_text(path.read_text(encoding="utf-8"), str(path.relative_to(root))))
    return files, hits


def method_body(src: str, name: str) -> str | None:
    """取名为 `name` 的方法体原文（同名取第一个；找不到返回 None）。"""
    stripped = strip_comments_and_strings(src)
    for start, end, found in method_ranges(stripped):
        if found == name:
            return src[start:end]
    return None


def fingerprint(path: Path) -> str:
    """内容 sha256（**只用内容**：mtime / size 不参与，见 issue #4260）。"""
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _format(hits: list[Hit]) -> str:
    return "\n".join(f"  · {h}" for h in hits)


# ══════════════════ ① 反空跑：扫描集必须覆盖三处已知软删点 ══════════════════

def test_scan_covers_the_known_soft_delete_sites():
    files, _ = scan_tree(REPO)
    assert files, "扫描集为空（glob 写错了？）—— 守卫空跑 = 假绿"
    rels = {str(p.relative_to(REPO)) for p in files}
    missing = sorted({rel for rel, _ in KNOWN_SITES} - rels)
    assert not missing, (
        "守卫没扫到 issue #4608 的已知软删点所在文件（锚点失锚 ⇒ 下面的判据可能恒绿）：\n"
        + "\n".join(f"  · {m}" for m in missing)
    )


# ══════════════════ ② L0 不变式：禁用形态零容忍 ══════════════════

def test_no_updateById_after_setDeleted_in_same_method():
    _, hits = scan_tree(REPO)
    assert not hits, (
        f"发现「同一方法体内 setDeleted(0/1) 之后调用 updateById(」形态（{len(hits)} 处）：\n"
        + _format(hits)
        + "\n\nMyBatis-Plus 全局逻辑删除（application.yml 的 "
          "mybatis-plus.global-config.db-config.logic-delete-field=deleted）\n"
          "会把逻辑删除字段从 updateById 的 SET 子句里剔除 ⇒ `deleted` 那一列**根本不会被写**，\n"
          "而调用仍返回成功 = 删除静默 no-op（issue #4608：用户「删除后提示成功但是数据仍然在」）。\n\n"
          "正确写法 = 显式写列（绕过字段剔除，且保住审计字段 updated_at）：\n"
          "  mapper.update(null, new LambdaUpdateWrapper<Xxx>()\n"
          "          .eq(Xxx::getId, id)\n"
          "          .set(Xxx::getDeleted, 1)\n"
          "          .set(Xxx::getUpdatedAt, OffsetDateTime.now()));"
    )


def test_three_soft_delete_sites_write_deleted_explicitly():
    """正向判据：三处软删**确实**在显式写 `deleted`（否则"删掉功能"也能让上面那条恒绿）。"""
    problems: list[str] = []
    for rel, name in KNOWN_SITES:
        body = method_body((REPO / rel).read_text(encoding="utf-8"), name)
        if body is None:
            problems.append(f"{rel}#{name}: 找不到该方法（改名/挪走了？守卫锚点要同步）")
            continue
        compact = re.sub(r"\s+", "", body)
        absent = [needle for needle in LEGAL_NEEDLES if needle not in compact]
        if absent:
            problems.append(f"{rel}#{name}: 缺显式写列片段 {absent}")
    assert not problems, (
        "三处软删必须用 `update(null, LambdaUpdateWrapper … .set(::getDeleted, 1).set(::getUpdatedAt, …))` "
        "显式写列：\n" + "\n".join(f"  · {p}" for p in problems)
    )


# ══════════════════ ③ 注入式自证（红 / 不误报，双向） ══════════════════

FIXTURE_LEGAL = '''package demo;

import java.time.OffsetDateTime;
import java.util.Map;

class DemoHolder {
    private DemoMapper mapper;

    Map<String, Object> softDelete(String id) {
        mapper.update(null, new LambdaUpdateWrapper<Demo>()
                .eq(Demo::getId, id)
                .set(Demo::getDeleted, 1)
                .set(Demo::getUpdatedAt, OffsetDateTime.now()));
        return Map.of("id", id, "deleted", true);
    }
}
'''

FIXTURE_INJECTED = FIXTURE_LEGAL.replace(
    """        mapper.update(null, new LambdaUpdateWrapper<Demo>()
                .eq(Demo::getId, id)
                .set(Demo::getDeleted, 1)
                .set(Demo::getUpdatedAt, OffsetDateTime.now()));""",
    """        Demo entity = mapper.selectById(id);
        entity.setDeleted(1);
        entity.setUpdatedAt(OffsetDateTime.now());
        mapper.updateById(entity);""",
)

FIXTURE_RESURRECT = FIXTURE_INJECTED.replace("entity.setDeleted(1);", "entity.setDeleted(0);")

#: 合法形态的**另一种排版**（证明"不误报"不是因为注入没生效）。
FIXTURE_LEGAL_VARIANT = FIXTURE_LEGAL.replace(
    "        return Map.of(\"id\", id, \"deleted\", true);",
    "        mapper.update(null, new LambdaUpdateWrapper<Demo>().eq(Demo::getId, id)\n"
    "                .set(Demo::getDeleted, 1).set(Demo::getUpdatedAt, OffsetDateTime.now()));\n"
    "        return Map.of(\"id\", id, \"deleted\", true);",
)


def _fixture(tmp: Path, body: str) -> Path:
    path = Path(tempfile.mkdtemp(dir=tmp)) / "Demo.java"
    path.write_text(body, encoding="utf-8")
    return path


def _scan_fixture(java_file: Path) -> list[Hit]:
    """扫临时夹具目录（**注意换 glob**：默认 glob 是仓内 `backend/**`，在 tmp 下会扫出空集 ⇒ 假绿）。"""
    files, hits = scan_tree(java_file.parent, pattern="**/*.java")
    assert files == [java_file], f"夹具没被扫到（扫到的是 {files}）⇒ 本自证是空跑"
    return hits


def test_injected_updateById_form_is_detected(tmp_path):
    """往临时副本塞**禁用形态** ⇒ 仍判红（附内容指纹自证注入真的落盘）。"""
    base = _fixture(tmp_path, FIXTURE_LEGAL)
    assert not _scan_fixture(base), "合法夹具不该命中"
    before = fingerprint(base)

    injected = _fixture(tmp_path, FIXTURE_INJECTED)
    after = fingerprint(injected)
    assert before != after, "注入前后内容指纹相同 ⇒ 注入没生效，本自证是空跑"

    hits = _scan_fixture(injected)
    assert hits, "注入 `setDeleted(1)` + `updateById(` 之后守卫**没判红** ⇒ 守卫判据失效"
    assert [h.method for h in hits] == ["softDelete"], _format(hits)
    assert hits[0].set_line < hits[0].update_line, _format(hits)


def test_injected_resurrect_form_is_detected(tmp_path):
    """`setDeleted(0)`（复活/取消删除）同款禁用 —— MP 一样会把它从 SET 剔除。"""
    injected = _fixture(tmp_path, FIXTURE_RESURRECT)
    assert "setDeleted(0)" in injected.read_text(encoding="utf-8"), "夹具里没有 setDeleted(0) ⇒ 自证空跑"
    hits = _scan_fixture(injected)
    assert hits, "`setDeleted(0)` + `updateById(` 没被判红 ⇒ 复活形态漏判"
    assert [h.method for h in hits] == ["softDelete"], _format(hits)


def test_legal_explicit_column_form_is_not_flagged(tmp_path):
    """塞**合法形态**（显式写列）⇒ 不误报；指纹自证"不误报"不是因为注入没生效。"""
    base = _fixture(tmp_path, FIXTURE_LEGAL)
    assert not _scan_fixture(base), "显式写列形态被误报"

    variant = _fixture(tmp_path, FIXTURE_LEGAL_VARIANT)
    assert fingerprint(base) != fingerprint(variant), "变体与基准逐字节相同 ⇒ 本自证是空跑"
    assert not _scan_fixture(variant), "显式写列的另一种排版被误报"
