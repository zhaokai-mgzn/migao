// case_ids: SP-001
package com.migao.admin.mapper;

import com.migao.admin.entity.Supplier;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 供应商 Mapper / 实体 ↔ 建库脚本（issue #7369，P0-1 段 1）。
 *
 * <p>为什么这是判据而不是「MyBatis 会自己报错」：Mapper 在单测里几乎总被 mock（`SecurityConfigTest`
 * 就是 `@MockBean`），列名/字段对不上要等**生产上第一次真跑这条 SQL** 才炸 —— 那时是 500，
 * 不是红单测（本仓 §17.3「mock 掉的依赖，其真实行为在生产才第一次执行」的同族）。
 *
 * <p>守两条：
 * <ol>
 *   <li><b>实体字段 ⊆ 建库脚本列</b>：给实体加字段却没加列 ⇒ 每次 insert/select 都炸；</li>
 *   <li><b>租户列必须在场</b>：`TenantLineInnerInterceptor` 会给每张非忽略表注入 `tenant_id` 谓词 ——
 *       缺列 = 每次查询/插入 SQL 报错（不是「查不到」）���</li>
 * </ol>
 * 红证方向：把 {@code Supplier} 的 {@code contactPhone} 改名成 {@code phone}（脚本未加列）⇒ 本类红。
 */
@DisplayName("供应商 Mapper：实体字段 ⊆ 建库脚本列 + 租户列在场")
class SupplierMapperTest {

    @Test
    @DisplayName("实体每个字段都在建库脚本里有对应列（加字段不加列 ⇒ 每次 SQL 都炸）")
    void everyEntityFieldHasAColumn() throws Exception {
        Set<String> columns = MapperColumnAssertions.columnsOf("suppliers");
        assertThat(columns).as("解析自证：suppliers 列面非空").isNotEmpty();

        MapperColumnAssertions.assertEveryEntityFieldHasColumn(Supplier.class, "suppliers");
    }

    @Test
    @DisplayName("租户列 `tenant_id` 必须在场（缺列 = 租户插件注入的谓词每次都报错）")
    void tenantColumnIsPresent() throws Exception {
        assertThat(MapperColumnAssertions.columnsOf("suppliers")).contains("tenant_id");
    }

    @Test
    @DisplayName("契约列逐值核对：本段声明的 12 列一列不差（PR body 的冻结契约；#7723 加 type）")
    void declaredContractColumnsExist() throws Exception {
        assertThat(MapperColumnAssertions.columnsOf("suppliers")).containsExactlyInAnyOrder(
                "id", "tenant_id", "name", "contact_name", "contact_phone",
                "payment_terms_days", "status", "type", "remark",
                "created_at", "updated_at", "deleted");
    }

    @Test
    @DisplayName("Mapper 只继承 BaseMapper（没有自写 SQL ⇒ 租户/软删口径不会被第二套实现绕过）")
    void mapperHasNoCustomSql() {
        long declaredMethods = java.util.Arrays.stream(SupplierMapper.class.getDeclaredMethods())
                .filter(m -> !m.isSynthetic())
                .count();
        assertThat(declaredMethods)
                .as("SupplierMapper 出现自写方法 ⇒ 需要为它单独补判据（租户插件不会作用于手写 SQL）")
                .isZero();
    }
}
