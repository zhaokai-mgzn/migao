// case_ids: PG-018
package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import com.baomidou.mybatisplus.annotation.TableName;
import com.migao.admin.entity.ProcessingOrder;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.time.OffsetDateTime;
import java.util.Arrays;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 加工单级短码的 mapper 契约（V155，issue #6867 / B1）。
 *
 * <p>本类钉**SQL 形态与实体收敛**（不需要数据库）；真库那一半（真索引兜底 / 并发只补一次）不在
 * 本包射程（注意：判据**不报**「真库上跑过」—— 如实登记）。</p>
 *
 * <h3>红证（改坏 ⇒ 必红）</h3>
 * <ul>
 *   <li>{@code fillMissingShortCode} 摘掉 {@code AND short_code IS NULL} ⇒
 *       {@code fillMissingShortCodeOnlyFillsNullRows} 红 —— 那正是「并发下后写者覆盖前者、
 *       把别人已经印出去的码改掉」的形态；</li>
 *   <li>{@code fillMissingShortCode} 里顺手写 {@code qr_token} ⇒ 同一条判据红
 *       （撤销状态会从一处变成两处）；</li>
 *   <li>{@code revokeQrToken} 里顺手把 {@code short_code} 清掉 ⇒
 *       {@code revokeQrTokenNeverTouchesShortCode} 红（已打印的纸**永久作废**）；</li>
 *   <li>{@code selectByShortCode} 漏 {@code tenant_id = #{tenantId}} ⇒
 *       {@code selectByShortCodeStaysInsideTheTenant} 红（分配期跨租户读 = 越权面）；</li>
 *   <li>实体漏 {@code shortCode} 字段 ⇒ {@code entityMapsShortCodeColumn} 红
 *       （运行期报 unknown property ⇒ 分配直接崩）。</li>
 * </ul>
 */
@DisplayName("ProcessingOrderMapper 契约（加工单级短码，V155 / issue #6867）")
class ProcessingOrderShortCodeMapperTest {

    private static final String V155 = "backend/admin-api/src/main/resources/db/migration/"
            + "V155__add_short_code_to_processing_orders.sql";

    @Test
    @DisplayName("实体映射 processing_orders + shortCode 列在迁移与建库脚本里都有（三源收敛）")
    void entityMapsShortCodeColumn() {
        TableName tableName = ProcessingOrder.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("processing_orders");
        assertThat(Arrays.stream(ProcessingOrder.class.getDeclaredFields()).map(Field::getName))
                .as("短码必须真是实体字段 —— 否则运行期 unknown property，实例化当场崩")
                .contains("qrToken", "shortCode");

        // V155 是 ALTER TABLE（不是 CREATE TABLE）⇒ 逐条断言形态（同 ProcessingSetPartTokenMapperTest 的 V99 段）
        String v155 = ProductionMigrationSql.read(V155);
        assertThat(v155)
                .as("V155 必须给 processing_orders 加 short_code CHAR(8)")
                .containsPattern("(?is)ALTER TABLE\\s+processing_orders\\b[\\s\\S]*?"
                        + "ADD COLUMN IF NOT EXISTS\\s+short_code\\s+CHAR\\(8\\)");
        assertThat(ProductionMigrationSql.read(ProductionMigrationSql.SCHEMA))
                .as("建库脚本必须体现同一终态")
                .containsPattern("(?m)^\\s*short_code\\s+CHAR\\(8\\),");
    }

    @Test
    @DisplayName("🔴 selectByShortCode — 显式租户谓词 + 软删过滤（分配期**不**跨租户读）")
    void selectByShortCodeStaysInsideTheTenant() throws Exception {
        Method method = ProcessingOrderMapper.class.getMethod("selectByShortCode", String.class, Long.class);
        Select select = method.getAnnotation(Select.class);
        assertThat(select).as("必须是 @Select").isNotNull();
        String sql = String.join(" ", select.value());
        assertThat(sql).startsWith("SELECT ");
        assertThat(sql).contains("short_code = #{shortCode}");
        // 🔴 显式租户列（不依赖拦截器是否挂上）：分配与「同一张纸」判定都发生在已认证请求内
        assertThat(sql).contains("tenant_id = #{tenantId}");
        assertThat(sql).contains("deleted = 0");
        assertThat(sql).contains("LIMIT 1");
    }

    @Test
    @DisplayName("🔴 fillMissingShortCode — 只补 short_code IS NULL 的行；不碰 qr_token；租户/软删守卫")
    void fillMissingShortCodeOnlyFillsNullRows() throws Exception {
        Method method = ProcessingOrderMapper.class.getMethod("fillMissingShortCode",
                String.class, Long.class, String.class, OffsetDateTime.class);
        Update update = method.getAnnotation(Update.class);
        assertThat(update).as("必须是条件 UPDATE（不是 updateById 的整行覆盖）").isNotNull();
        String sql = String.join(" ", update.value());
        assertThat(sql).startsWith("UPDATE processing_orders");
        assertThat(sql).contains("SET short_code = #{shortCode}");
        // ① 幂等的**唯一**保证：已有短码的行一字不动（已打印的纸不作废）
        assertThat(sql).contains("AND short_code IS NULL");
        // ② 不碰撤销状态（短码与 qr_token 的职责分离：一处状态，不是两处）
        assertThat(sql).doesNotContain("qr_token");
        // ③ 租户 + 软删守卫
        assertThat(sql).contains("id = #{id}");
        assertThat(sql).contains("tenant_id = #{tenantId}");
        assertThat(sql).contains("deleted = 0");
    }

    @Test
    @DisplayName("🔴 revokeQrToken 绝不碰 short_code（已打印的纸不作废；/o/ 的 410 由 token 为空判定）")
    void revokeQrTokenNeverTouchesShortCode() throws Exception {
        Method method = ProcessingOrderMapper.class.getMethod(
                "revokeQrToken", String.class, Long.class, OffsetDateTime.class);
        Update update = method.getAnnotation(Update.class);
        assertThat(update).isNotNull();
        String sql = String.join(" ", update.value());
        assertThat(sql).startsWith("UPDATE processing_orders");
        assertThat(sql).contains("SET qr_token = NULL");
        assertThat(sql)
                .as("撤销只作废这张纸的当前 token；一并清短码 ⇒ 已打印的纸永久成为废纸")
                .doesNotContain("short_code");
        assertThat(sql).contains("tenant_id = #{tenantId}");
        assertThat(sql).contains("deleted = 0");
    }

    @Test
    @DisplayName("🔴 selectByShortCodeGlobal — 公开入口 /o/{短码} 的**跨租户**读：显式关掉租户拦截器、不带 tenant_id")
    void selectByShortCodeGlobalIsCrossTenantOnPurpose() throws Exception {
        Method method = ProcessingOrderMapper.class.getMethod("selectByShortCodeGlobal", String.class);
        Select select = method.getAnnotation(Select.class);
        assertThat(select).as("必须是 @Select").isNotNull();
        String sql = String.join(" ", select.value());
        assertThat(sql).contains("short_code = #{shortCode}");
        assertThat(sql).contains("deleted = 0");
        assertThat(sql).contains("LIMIT 1");
        // 公开入口没有租户上下文（TenantContext 为空）⇒ **不得**出现 tenant_id 谓词（没有上下文可绑；
        // 短码的跨租户唯一性由部分唯一索引 uk_processing_orders_short_code 兜底，最多命中一行）
        assertThat(sql)
                .as("公开入口无租户上下文 ⇒ 不能绑 tenant_id（那会让纸上的码恒 404）")
                .doesNotContain("tenant_id");
        assertThat(Optional.ofNullable(method.getAnnotation(InterceptorIgnore.class))
                .map(InterceptorIgnore::tenantLine).orElse("<注解缺失>"))
                .as("@InterceptorIgnore(tenantLine = \"true\") 是必须的（不是优化）：漏了 ⇒ 多租户拦截器抛"
                        + " Tenant context not initialized ⇒ 纸上的码恒 500")
                .isEqualTo("true");
    }
}
