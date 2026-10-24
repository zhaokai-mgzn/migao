// case_ids: SP-001
package com.migao.admin.mapper;

import com.migao.admin.entity.Supplier;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

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

    private static final Path SCHEMA = Path.of("src/main/resources/db/init/schema.sql");

    private static Set<String> columnsOf(String table) throws Exception {
        String sql = Files.readString(SCHEMA);
        Matcher m = Pattern.compile(
                "CREATE TABLE IF NOT EXISTS " + table + " \\(([\\s\\S]*?)\\n\\);").matcher(sql);
        assertThat(m.find()).as("建库脚本里必须有 %s 表（缺 ⇒ 新建库缺表，#3270 形态）", table).isTrue();
        Set<String> cols = new LinkedHashSet<>();
        for (String line : m.group(1).split("\n")) {
            Matcher c = Pattern.compile("^\\s{4}([a-z_]+)\\s+[A-Z]").matcher(line);
            if (c.find()) {
                cols.add(c.group(1));
            }
        }
        return cols;
    }

    /** Java 字段名 → 列名（camelCase → snake_case；本仓无自定义 @TableField 映射）。 */
    private static String toColumn(String field) {
        return field.replaceAll("([a-z0-9])([A-Z])", "$1_$2").toLowerCase();
    }

    private static Set<String> entityColumns() {
        return java.util.Arrays.stream(Supplier.class.getDeclaredFields())
                .filter(f -> !Modifier.isStatic(f.getModifiers()))
                .filter(f -> !f.isSynthetic())
                .map(Field::getName)
                .map(SupplierMapperTest::toColumn)
                .collect(Collectors.toCollection(LinkedHashSet::new));
    }

    @Test
    @DisplayName("实体每个字段都在建库脚本里有对应列（加字段不加列 ⇒ 每次 SQL 都炸）")
    void everyEntityFieldHasAColumn() throws Exception {
        Set<String> columns = columnsOf("suppliers");
        assertThat(columns).as("解析自证：suppliers 列面非空").isNotEmpty();

        Set<String> missing = new LinkedHashSet<>(entityColumns());
        missing.removeAll(columns);
        assertThat(missing)
                .as("实体字段在建库脚本里没有对应列：%s（列面 = %s）", missing, columns)
                .isEmpty();
    }

    @Test
    @DisplayName("租户列 `tenant_id` 必须在场（缺列 = 租户插件注入的谓词每次都报错）")
    void tenantColumnIsPresent() throws Exception {
        assertThat(columnsOf("suppliers")).contains("tenant_id");
    }

    @Test
    @DisplayName("契约列逐值核对：本段声明的 11 列一列不差（PR body 的冻结契约）")
    void declaredContractColumnsExist() throws Exception {
        assertThat(columnsOf("suppliers")).containsExactlyInAnyOrder(
                "id", "tenant_id", "name", "contact_name", "contact_phone",
                "payment_terms_days", "status", "remark",
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
