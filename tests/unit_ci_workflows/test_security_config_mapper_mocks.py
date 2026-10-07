# case_ids: DF-007
"""`SecurityConfigTest` 必须能启动上下文：**每个 Mapper 都被 `@MockBean`** + **不得直接注入 `JdbcTemplate`**
（同族坑第 4 次 → 第 5 次的护栏）。

## 病根（本仓已踩 3 次，注释里自己写着「同族坑第 3 次」）

`SecurityConfigTest` 是全仓**唯一**的 `@SpringBootTest` 全上下文测试，它
`@EnableAutoConfiguration(exclude = {DataSourceAutoConfiguration, MybatisPlusAutoConfiguration, RedisAutoConfiguration})`
⇒ 上下文里**没有** `SqlSessionFactory` / `SqlSessionTemplate`，**也没有** `DataSource`
（⇒ `JdbcTemplateAutoConfiguration` 不生效 ⇒ 没有 `JdbcTemplate` bean）。

两个同族坑：

| 坑 | 形态 | 后果 |
|---|---|---|
| ① Mapper 漏 mock | `@MapperScan` 把 `mapper/**` 每个接口注册成 bean，未 mock 的真去创建 | `checkDaoConfig` 抛 `Property 'sqlSessionFactory' … required` ⇒ 该测试类 26 条全 error |
| ② `JdbcTemplate` 直接注入 | `@Service` 声明 `private final JdbcTemplate jdbc;`（`@RequiredArgsConstructor` 构造注入） | 上下文起不来 ⇒ 该测试类 **55 条全 error**（issue #6280 实测，2026-10-07） |

⇒ 结论：**新增一个 Mapper ⇒ 必须同步加一个 `@MockBean`**；
**需要 `JdbcTemplate` 的 bean ⇒ 必须走 `ObjectProvider<JdbcTemplate>` 延迟获取**
（既有先例 = `backend/admin-api/src/main/java/com/migao/admin/service/ClientRequestIdService.java`，
其注释已写明「直接构造注入会让整个应用上下文起不来」）。
漏了不会在「新增那个类」的测试里红，而是在**一个完全无关的 security 测试**里红 ——
这正是它反复被踩的原因（归因错位）。

## 判据

1. `com.migao.admin.mapper` 包下的**每个** `*Mapper` 接口，都必须在 `SecurityConfigTest` 里
   出现 `@MockBean` 声明。**双向**：既查「有 mapper 没被 mock」（坑 ①），也自证「解析确实读到了东西」。
2. `src/main` 里**任何**直接声明 `JdbcTemplate` 字段的类 —— 除非它在 `SecurityConfigTest` 里被
   `@MockBean` 顶替 —— 判红（坑 ②）。走 `ObjectProvider<JdbcTemplate>` 的形态天然不命中
   （`ObjectProvider<JdbcTemplate>` 不是「`JdbcTemplate` 字段」）。

**红证**：① 删掉任一 `@MockBean`（或新增一个 mapper 不加 mock）⇒ 判据 1 红；
② 把 `ClientRequestIdService` / `MaterialShortageService` 的 `ObjectProvider<JdbcTemplate>`
改回 `private final JdbcTemplate jdbc;` ⇒ 判据 2 红（实测读数见 PR body）。
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
MAPPER_DIR = REPO / "backend/admin-api/src/main/java/com/migao/admin/mapper"
MAIN_JAVA = REPO / "backend/admin-api/src/main/java"
SECURITY_TEST = REPO / "backend/admin-api/src/test/java/com/migao/admin/security/SecurityConfigTest.java"


def _mapper_names(mapper_dir: Path = MAPPER_DIR) -> set:
    return {p.stem for p in Path(mapper_dir).glob("*Mapper.java")}


def _mocked_names(text: str) -> set:
    # 形态：private com.migao.admin.mapper.XxxMapper xxxMapper;（@MockBean 在上一行，同块内）
    return set(re.findall(r"private\s+com\.migao\.admin\.mapper\.(\w+Mapper)\s+\w+\s*;", text))


def test_mapper_dir_is_non_trivial():
    """自证：确实解析出了 mapper（否则本文件空转 = 假绿）。"""
    names = _mapper_names()
    assert len(names) > 20, f"mapper 解析结果过少（{len(names)}）—— 解析疑似失效"


def test_security_config_test_mocks_every_mapper():
    """判据：每个 Mapper 都必须在 `SecurityConfigTest` 里 `@MockBean` 顶替。"""
    mappers = _mapper_names()
    mocked = _mocked_names(SECURITY_TEST.read_text(encoding="utf-8"))
    missing = sorted(mappers - mocked)
    assert not missing, (
        f"这些 Mapper 未在 SecurityConfigTest 里 @MockBean：{missing}\n"
        f"⇒ 它们会在上下文启动时**真去创建** ⇒ 因该上下文无 SqlSessionFactory 而抛 "
        f"`Property 'sqlSessionFactory' or 'sqlSessionTemplate' are required` ⇒ "
        f"SecurityConfigTest 26 条**全 error**（同族坑第 4 次）。\n"
        f"修法：在 SecurityConfigTest 里按既有口径补 `@MockBean private com.migao.admin.mapper.XxxMapper xxxMapper;`"
    )


def test_mocked_names_are_parseable_and_directional():
    """反向自证：mock 解析也读到了东西（只查单向会掩盖「正则失效 ⇒ 恒绿」）。"""
    mocked = _mocked_names(SECURITY_TEST.read_text(encoding="utf-8"))
    assert len(mocked) > 20, f"SecurityConfigTest 的 @MockBean mapper 解析过少（{len(mocked)}）—— 疑似失效"


# ── 坑 ②：`JdbcTemplate` 直接注入（issue #6280 实测）────────────────────────────

#: `ObjectProvider<JdbcTemplate>` **不算**命中（它不要求上下文里真有这个 bean）
_DIRECT_JDBC_FIELD = re.compile(r'\bJdbcTemplate\s+(?P<name>[A-Za-z_]\w*)\s*;')
_OBJECT_PROVIDER_JDBC = re.compile(r'ObjectProvider\s*<\s*JdbcTemplate\s*>')


def _direct_jdbc_injecting_classes(main_java: Path = MAIN_JAVA) -> dict:
    """`{仓库相对路径: 字段行}` —— 直接声明 `JdbcTemplate` 字段的类（坑 ② 的形态）。"""
    out = {}
    root = Path(main_java)
    for path in sorted(root.rglob("*.java")):
        text = path.read_text(encoding="utf-8")
        if not _DIRECT_JDBC_FIELD.search(text):
            continue
        out[str(path.relative_to(root.parent.parent.parent.parent))] = text
    return out


def test_jdbc_field_scan_is_non_trivial():
    """自证：解析确实读到了真实代码（否则判据 2 是空断言）。

    真值面 = 仓内确有 **ObjectProvider<JdbcTemplate>** 用法（解析器能读到源码）；
    只断言「扫到 0 个直接注入」会退化成恒绿。
    """
    hits = _direct_jdbc_injecting_classes()
    providers = [
        p for p in MAIN_JAVA.rglob("*.java")
        if _OBJECT_PROVIDER_JDBC.search(p.read_text(encoding="utf-8"))
    ]
    assert providers, "扫不到任何 ObjectProvider<JdbcTemplate> 用法 —— 解析疑似失效（本判据会恒绿）"
    assert isinstance(hits, dict)  # 形态保持：返回逐文件映射，便于具名报错


def test_no_class_requires_jdbc_template_without_mock():
    """判据 2：需要 `JdbcTemplate` 的类必须走 `ObjectProvider`，或在该测试里被 `@MockBean` 顶替。"""
    mocked_text = SECURITY_TEST.read_text(encoding="utf-8")
    offenders = {}
    for rel, text in _direct_jdbc_injecting_classes().items():
        class_name = Path(rel).stem
        # 逃生口：该类已在 SecurityConfigTest 里被 @MockBean 顶替 ⇒ 上下文不会真去创建它
        if re.search(rf"\b{re.escape(class_name)}\s+\w+\s*;", mocked_text):
            continue
        offenders[rel] = _DIRECT_JDBC_FIELD.search(text).group(0).strip()
    assert not offenders, (
        "这些类**直接**声明了 `JdbcTemplate` 字段：\n  "
        + "\n  ".join(f"{rel} → {field}" for rel, field in sorted(offenders.items()))
        + "\n⇒ 无 DataSource 的上下文（SecurityConfigTest / AdminApiApplicationTest exclude 了 "
        "DataSourceAutoConfiguration）里没有这个 bean ⇒ **整个应用上下文起不来** ⇒ "
        "SecurityConfigTest 55 条全 error（issue #6280 实测，同族坑第 5 次）。\n"
        "修法（择一）：① 改成 `private final ObjectProvider<JdbcTemplate> jdbcProvider;` + 调用点 `jdbc()` "
        "（先例 = service/ClientRequestIdService.java）；② 在 SecurityConfigTest 里 `@MockBean` 顶替它。"
    )
