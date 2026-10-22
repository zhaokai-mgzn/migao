// case_ids: QC-002
package com.migao.admin.mapper;

import com.migao.admin.entity.ReworkOrder;
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
 * 返工单 Mapper / 实体 ↔ 建库脚本（issue #7377 段 2）。
 *
 * <p>额外守一条业务底线：**「同一售后单同时只能有一个未完结返工单」必须是数据库约束**
 * （部分唯一索引）—— 只写在服务层的话，并发开两张单是真实会发生的，而那时「修完没有」就没有唯一答案。</p>
 */
@DisplayName("返工单 Mapper：字段 ⊆ 列 + 四态封闭 + 单售后单未完结唯一是约束")
class ReworkOrderMapperTest {

    private static final Path SCHEMA = Path.of("src/main/resources/db/init/schema.sql");

    private static String schemaSql() throws Exception {
        return Files.readString(SCHEMA);
    }

    private static Set<String> columnsOf(String table) throws Exception {
        Matcher m = Pattern.compile(
                "CREATE TABLE IF NOT EXISTS " + table + " \\(([\\s\\S]*?)\\n\\);").matcher(schemaSql());
        assertThat(m.find()).as("建库脚本里必须有 %s 表", table).isTrue();
        Set<String> cols = new LinkedHashSet<>();
        for (String line : m.group(1).split("\n")) {
            Matcher c = Pattern.compile("^\\s{4}([a-z_]+)\\s+[A-Z]").matcher(line);
            if (c.find()) {
                cols.add(c.group(1));
            }
        }
        return cols;
    }

    @Test
    @DisplayName("实体每个字段都有对应列")
    void everyEntityFieldHasAColumn() throws Exception {
        Set<String> columns = columnsOf("rework_orders");
        assertThat(columns).isNotEmpty();
        Set<String> missing = java.util.Arrays.stream(ReworkOrder.class.getDeclaredFields())
                .filter(f -> !Modifier.isStatic(f.getModifiers()) && !f.isSynthetic())
                .map(Field::getName)
                .map(n -> n.replaceAll("([a-z0-9])([A-Z])", "$1_$2").toLowerCase())
                .collect(Collectors.toCollection(LinkedHashSet::new));
        missing.removeAll(columns);
        assertThat(missing).as("ReworkOrder 实体字段缺列：%s", missing).isEmpty();
    }

    @Test
    @DisplayName("🔴 同一售后单只有一个未完结返工单：写在**部分唯一索引**里")
    void oneOpenPerTicketIsAConstraint() throws Exception {
        String sql = schemaSql();
        assertThat(sql).contains("uk_rework_orders_open_per_ticket");
        assertThat(sql).as("必须是按状态过滤的部分索引").contains("WHERE status IN ('draft', 'in_progress')");
    }

    @Test
    @DisplayName("四态封闭（表 CHECK 与状态机常量一致）")
    void statusIsClosedSet() throws Exception {
        String sql = schemaSql();
        for (String status : new String[]{com.migao.admin.service.ReworkState.DRAFT, com.migao.admin.service.ReworkState.IN_PROGRESS,
                com.migao.admin.service.ReworkState.DONE, com.migao.admin.service.ReworkState.CANCELLED}) {
            assertThat(sql).as("建库脚本 CHECK 必须列出 %s", status).contains("'" + status + "'");
        }
    }

    @Test
    @DisplayName("售后单关联是真外键（返工单不能挂在不存在的工单上）")
    void ticketReferenceIsForeignKey() throws Exception {
        assertThat(columnsOf("rework_orders")).contains("after_sales_ticket_id");
        assertThat(schemaSql()).contains("after_sales_ticket_id VARCHAR(64) NOT NULL REFERENCES after_sales_tickets(id)");
    }

    @Test
    @DisplayName("Mapper 只继承 BaseMapper（唯一性交给索引，状态流转走服务层 CAS）")
    void mapperHasNoCustomSql() {
        long declared = java.util.Arrays.stream(ReworkOrderMapper.class.getDeclaredMethods())
                .filter(m -> !m.isSynthetic()).count();
        assertThat(declared).isZero();
    }
}
