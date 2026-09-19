# case_ids: DF-007
"""`SecurityConfigTest` 必须 `@MockBean` 掉**每一个** Mapper（同族坑第 4 次的护栏）。

## 病根（本仓已踩 3 次，注释里自己写着「同族坑第 3 次」）

`SecurityConfigTest` 是全仓**唯一**的 `@SpringBootTest` 全上下文测试，它
`@EnableAutoConfiguration(exclude = {DataSourceAutoConfiguration, MybatisPlusAutoConfiguration, RedisAutoConfiguration})`
⇒ 上下文里**没有** `SqlSessionFactory` / `SqlSessionTemplate`。

而 `AdminApiApplication` 上有 `@MapperScan("com.migao.admin.mapper")` ⇒ **该包下每个 Mapper 都会被注册成 bean**。
未被 `@MockBean` 顶替的那个会**真去创建** ⇒ `MapperFactoryBean.checkDaoConfig` 抛
`Property 'sqlSessionFactory' or 'sqlSessionTemplate' are required` ⇒ **该测试类 26 条全 error**。

⇒ 结论：**新增一个 Mapper ⇒ 必须同步在 `SecurityConfigTest` 里加一个 `@MockBean`**。
漏了不会在「新增 mapper 的那个测试」里红，而是在**一个完全无关的 security 测试**里红 ——
这正是它反复被踩的原因（归因错位）。

## 判据

`com.migao.admin.mapper` 包下的**每个** `*Mapper` 接口，都必须在 `SecurityConfigTest` 里
出现 `@MockBean` 声明。**双向**：既查「有 mapper 没被 mock」（本坑），也自证「解析确实读到了东西」
（否则正则失效 = 空断言）。

**红证**：删掉任一 `@MockBean`（或新增一个 mapper 不加 mock）⇒ 本判据红。
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
MAPPER_DIR = REPO / "backend/admin-api/src/main/java/com/migao/admin/mapper"
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
