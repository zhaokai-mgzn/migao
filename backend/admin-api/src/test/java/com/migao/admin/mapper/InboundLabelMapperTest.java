// case_ids: PR-113, PR-114
package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.InboundLabel;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Update;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.time.OffsetDateTime;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * InboundLabelMapper 契约（入库标签，issue #5052 <b>P2</b>，V134）。
 *
 * <p>本类钉**SQL 形态与注解面**（不需要数据库）；<b>真库</b>那一半（并发计数不丢 / 部分唯一索引兜底 /
 * 撤销置 NULL / V134 在真库上可重复执行）见同包外的
 * {@code com.migao.admin.service.InboundLabelPrintCountRealDbTest} —— 两者合起来才是完整判据：
 * 本类证明「写法是原子的」，那边证明「真库里并发跑完计数确实不丢」。</p>
 *
 * <h3>红证（改坏 ⇒ 必红）</h3>
 * <ul>
 *   <li>把 {@code incrementPrintCount} 改成「读出 +1 再写回」（SQL 里出现 {@code print_count = #{...}}）
 *       ⇒ {@code incrementPrintCountIsAnAtomicSqlIncrement} 红；</li>
 *   <li>给 {@code selectByCode} 摘掉 {@code @InterceptorIgnore} ⇒ 公开入口 {@code /i/} 无租户上下文 ⇒
 *       恒 500 ⇒ {@code selectByCodeIgnoresTenantLine} 红；</li>
 *   <li>{@code selectByCode} 的 WHERE 里漏掉 {@code revoked_code} ⇒ 撤销会被读成「没这个码」（404）
 *       而不是 410 ⇒ {@code selectByCodeMatchesBothLiveAndRevokedCodes} 红；</li>
 *   <li>{@code revoke} 里漏掉 {@code short_code IS NOT NULL} ⇒ 重复撤销会把留档码冲掉
 *       ⇒ {@code revokeIsIdempotentAndKeepsTheArchiveCode} 红。</li>
 * </ul>
 */
@DisplayName("InboundLabelMapper 契约（入库标签短码 / 打印计数 / 撤销，V134）")
class InboundLabelMapperTest {

    private static final String V134 =
            "backend/admin-api/src/main/resources/db/migration/V134__create_inbound_labels.sql";

    @Test
    @DisplayName("实体映射 inbound_labels 表，且关键列都在 V134 与建库脚本里")
    void entityMapsToTableAndColumns() {
        TableName tableName = InboundLabel.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("inbound_labels");

        List<String> fields = Arrays.stream(InboundLabel.class.getDeclaredFields()).map(Field::getName).toList();
        assertThat(fields).contains("tenantId", "inboundOrderId", "inboundItemId", "shortCode",
                "revokedCode", "printCount", "createdBy", "revokedAt", "revokedBy", "deleted");

        ProductionMigrationSql.assertTableColumnsIn(V134, "inbound_labels",
                "id", "tenant_id", "inbound_order_id", "inbound_item_id", "short_code", "revoked_code",
                "print_count", "created_by", "revoked_at", "revoked_by", "deleted");
    }

    @Test
    @DisplayName("🔴 selectByCode 必须绕过多租户拦截器（/i/ 是公开入口，无租户上下文 ⇒ 否则恒 500）")
    void selectByCodeIgnoresTenantLine() throws Exception {
        Method lookup = InboundLabelMapper.class.getMethod("selectByCode", String.class);
        InterceptorIgnore ignore = lookup.getAnnotation(InterceptorIgnore.class);
        assertThat(ignore).as("selectByCode 缺 @InterceptorIgnore ⇒ 公开标签入口必 500").isNotNull();
        assertThat(ignore.tenantLine()).isEqualTo("true");
    }

    @Test
    @DisplayName("🔴 selectByCode 同时认**活码与留档码**（漏掉留档码 ⇒ 撤销被读成 404 而不是 410）")
    void selectByCodeMatchesBothLiveAndRevokedCodes() throws Exception {
        Method lookup = InboundLabelMapper.class.getMethod("selectByCode", String.class);
        String sql = String.join(" ", lookup.getAnnotation(org.apache.ibatis.annotations.Select.class).value());
        assertThat(sql).startsWith("SELECT ");
        assertThat(sql).contains("short_code = #{code}").contains("revoked_code = #{code}");
        assertThat(sql).contains("deleted = 0");
        // 公开入口要能分辨「已作废」与「不存在」⇒ 不能带 short_code IS NOT NULL 过滤
        assertThat(sql).doesNotContain("short_code IS NOT NULL");
    }

    @Test
    @DisplayName("🔴 incrementPrintCount 是**一条**原子自增 SQL（不是读出来 +1 再写回）")
    void incrementPrintCountIsAnAtomicSqlIncrement() throws Exception {
        Method method = InboundLabelMapper.class.getMethod("incrementPrintCount", String.class, Long.class);
        Update update = method.getAnnotation(Update.class);
        assertThat(update).as("必须是原子 UPDATE").isNotNull();
        String sql = String.join(" ", update.value());
        assertThat(sql).startsWith("UPDATE inbound_labels SET print_count = COALESCE(print_count, 0) + 1");
        assertThat(sql).as("自增量不得来自参数（来自参数就是「读出来 +1 再写回」= 并发丢计数）")
                .doesNotContain("print_count = #{");
        assertThat(sql).contains("id = #{id}").contains("tenant_id = #{tenantId}").contains("deleted = 0");
    }

    @Test
    @DisplayName("🔴 revoke 置 NULL + 留档 + 幂等（第二次撤销一字不动）；带租户与软删守卫")
    void revokeIsIdempotentAndKeepsTheArchiveCode() throws Exception {
        Method method = InboundLabelMapper.class.getMethod("revoke", String.class, Long.class,
                OffsetDateTime.class, String.class);
        Update update = method.getAnnotation(Update.class);
        assertThat(update).isNotNull();
        String sql = String.join(" ", update.value());
        assertThat(sql).startsWith("UPDATE inbound_labels");
        assertThat(sql).contains("SET short_code = NULL, revoked_code = short_code");
        assertThat(sql).as("留档码必须是**原列**（不是参数：参数化等于调用方可以随便填）")
                .doesNotContain("revoked_code = #{");
        assertThat(sql).contains("tenant_id = #{tenantId}").contains("deleted = 0")
                .contains("AND short_code IS NOT NULL");
        assertThat(sql).as("撤销不得抹掉打印历史").doesNotContain("print_count");
    }

    @Test
    @DisplayName("🔴 insertIgnoreConflict：撞「一行一标签」唯一索引则**不插**（复用同一张纸 / 同一短码）")
    void insertIgnoreConflictIsPartialIndexAware() throws Exception {
        Method method = InboundLabelMapper.class.getMethod("insertIgnoreConflict", InboundLabel.class);
        Insert insert = method.getAnnotation(Insert.class);
        assertThat(insert).isNotNull();
        String sql = String.join(" ", insert.value());
        assertThat(sql).startsWith("INSERT INTO inbound_labels");
        assertThat(sql).as("必须带索引谓词（部分唯一索引的冲突推断要求谓词匹配）")
                .contains("ON CONFLICT (tenant_id, inbound_item_id) WHERE deleted = 0 DO NOTHING");
        assertThat(sql).contains("print_count").contains("created_by");
        assertThat(sql).as("新标签的计数一律从 0 起（不继承任何值）").contains("0, #{l.createdBy}");
    }

    @Test
    @DisplayName("selectPrintCount 也带租户谓词（回读不能跨租户）")
    void selectPrintCountIsTenantScoped() throws Exception {
        Method method = InboundLabelMapper.class.getMethod("selectPrintCount", String.class, Long.class);
        String sql = String.join(" ", method.getAnnotation(org.apache.ibatis.annotations.Select.class).value());
        assertThat(sql).contains("SELECT print_count FROM inbound_labels")
                .contains("id = #{id}").contains("tenant_id = #{tenantId}").contains("deleted = 0");
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(InboundLabelMapper.class)).isTrue();
        // 反向护栏：本 Mapper 只碰 inbound_labels（判据另有源码守卫，这里钉住它没被换成别的表）
        assertThat(InboundLabel.class.getAnnotation(TableName.class).value()).isEqualTo("inbound_labels");
    }
}
