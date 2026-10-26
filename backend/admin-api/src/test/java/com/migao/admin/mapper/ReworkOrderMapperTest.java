// case_ids: QC-002
package com.migao.admin.mapper;

import com.migao.admin.entity.ReworkOrder;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;

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

    @Test
    @DisplayName("实体每个字段都有对应列")
    void everyEntityFieldHasAColumn() throws Exception {
        Set<String> columns = MapperColumnAssertions.columnsOf("rework_orders");
        assertThat(columns).isNotEmpty();
        MapperColumnAssertions.assertEveryEntityFieldHasColumn(ReworkOrder.class, "rework_orders");
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
    @DisplayName("售后单关联是真外键（返工单不能挂在不存在的工单上）；车间来源没有售后单 ⇒ 可空")
    void ticketReferenceIsForeignKey() throws Exception {
        assertThat(MapperColumnAssertions.columnsOf("rework_orders")).contains("after_sales_ticket_id");
        // issue #7860（V199）：车间工人报返工没有售后单 ⇒ 该列改**可空**，但**外键仍在**
        // （挂上了就必须是真实存在的售后单）。两个来源由 `source` 区分：
        //   after_sales = 售后开单（有售后单）；worker = 车间报返工（无售后单，挂工序/数量/报工人）
        assertThat(schemaSql()).contains("after_sales_ticket_id VARCHAR(64) REFERENCES after_sales_tickets(id)");
        assertThat(schemaSql()).as("两个来源必须是封闭集合（迁移 V199 的 CHECK）")
                .contains("CONSTRAINT ck_rework_orders_source CHECK (source IN ('after_sales', 'worker'))");
    }

    @Test
    @DisplayName("Mapper 只继承 BaseMapper（唯一性交给索引，状态流转走服务层 CAS）")
    void mapperHasNoCustomSql() {
        long declared = java.util.Arrays.stream(ReworkOrderMapper.class.getDeclaredMethods())
                .filter(m -> !m.isSynthetic()).count();
        assertThat(declared).isZero();
    }
}
