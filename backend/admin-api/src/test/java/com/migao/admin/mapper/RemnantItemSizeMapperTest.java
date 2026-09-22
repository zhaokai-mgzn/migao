// case_ids: PR-098
package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.RemnantItemSize;
import com.migao.admin.service.RemnantTestDb;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.sql.SQLException;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.catchThrowable;

/**
 * {@link RemnantItemSizeMapper} 的**持久化契约**判据（V122 / issue #5146）—— 真库。
 *
 * <h2>为什么这几条必须落在 DB 上</h2>
 * 小件用料尺寸表是**企业可配参数**（用户裁定「可以整个参数配置，未来让企业自定义」）
 * ⇒ 它的三条不变式只有数据库能保证，写在 Java 里一律是「注释里的承诺」：
 * <ol>
 *   <li><b>一租户一小件一行</b>：部分唯一索引 {@code uk_remnant_spec_item} 必须真的挡住第二行
 *       （否则读面会出现「同一小件两个尺寸」的歧义，而匹配取哪一行取决于扫描顺序）；</li>
 *   <li><b>尺寸为正</b>：{@code ck_remnant_spec_size} 必须挡住 0 / 负数（0 面积的「用料」不是用料）；</li>
 *   <li><b>软删不占唯一键</b>：全量替换是「软删旧行 + 插新行」⇒ 旧行（{@code deleted = 1}）**不得**
 *       让新行撞唯一键（撞了就等于「改过的小件再也改不回来」）。</li>
 * </ol>
 *
 * <p>三条各带**注入了就必须红**的红证（用裸 SQL 越过实体层直插违规行）。</p>
 */
@DisplayName("RemnantItemSizeMapper 持久化契约（一行一小件 / 尺寸为正 / 软删不占唯一键）")
class RemnantItemSizeMapperTest {

    private static RemnantTestDb db;
    private static RemnantItemSizeMapper mapper;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        db = RemnantTestDb.start();
        if (db == null) {
            Assumptions.abort("本机没有 PG 二进制（initdb/pg_ctl）⇒ 真库判据**未跑**（不是通过）");
        }
        mapper = db.mapperOf(RemnantItemSizeMapper.class);
    }

    @AfterAll
    static void stopRealPostgres() {
        if (db != null) {
            db.stop();
        }
    }

    @Test
    @DisplayName("判据1/2：插入即可读回（逐值）；尺寸为 0 / 负数 ⇒ DB 当场拒绝")
    void insertAndSizeGuard() throws Exception {
        clearSpecs();
        mapper.insert(row("绑带-布", "0.50", "0.20"));

        List<RemnantItemSize> rows = list();
        assertThat(rows).hasSize(1);
        assertThat(rows.get(0).getItemKey()).isEqualTo("绑带-布");
        assertThat(rows.get(0).getLengthM()).isEqualByComparingTo(new BigDecimal("0.50"));
        assertThat(rows.get(0).getWidthM()).isEqualByComparingTo(new BigDecimal("0.20"));

        assertThat(sqlStateOf(catchThrowable(() -> db.exec("INSERT INTO remnant_small_item_specs"
                + " (tenant_id, item_key, length_m, width_m, operator) VALUES ("
                + RemnantTestDb.TENANT_ID + ", '零尺寸', 0, 0.2, 'system')"))))
                .as("0 面积的「用料」不是用料 ⇒ 约束必须挡住（23514）").isEqualTo("23514");
        assertThat(sqlStateOf(catchThrowable(() -> db.exec("INSERT INTO remnant_small_item_specs"
                + " (tenant_id, item_key, length_m, width_m, operator) VALUES ("
                + RemnantTestDb.TENANT_ID + ", '负尺寸', -1, 0.2, 'system')"))))
                .as("负尺寸同样当场拒绝").isEqualTo("23514");
    }

    @Test
    @DisplayName("🔴 判据1 唯一键：同一租户同一小件插第二行 ⇒ 23505（红证：换个键 ⇒ 成功）")
    void oneRowPerItemKeyPerTenant() throws Exception {
        clearSpecs();
        mapper.insert(row("帘头制作", "1.20", "0.40"));
        assertThat(sqlStateOf(catchThrowable(() -> db.exec("INSERT INTO remnant_small_item_specs"
                + " (tenant_id, item_key, length_m, width_m, operator) VALUES ("
                + RemnantTestDb.TENANT_ID + ", '帘头制作', 9, 9, 'system')"))))
                .as("🔴 同一小件的第二行必须被 uk_remnant_spec_item 挡下（否则读面有「同一小件两个尺寸」的歧义）")
                .isEqualTo("23505");

        // 红证：换一个键 ⇒ 必须成功（证明上面那条挡的是「重复」而不是别的原因）
        mapper.insert(row("抱枕", "0.45", "0.45"));
        assertThat(list().stream().map(RemnantItemSize::getItemKey).toList())
                .containsExactlyInAnyOrder("帘头制作", "抱枕");
    }

    @Test
    @DisplayName("🔴 判据3 软删不占唯一键：软删旧行 + 插同键新行 ⇒ 必须成功（否则改过的小件再也改不回来）")
    void softDeletedRowDoesNotBlockReinsert() throws Exception {
        clearSpecs();
        RemnantItemSize first = row("绑带-布", "0.50", "0.20");
        mapper.insert(first);
        assertThat(mapper.deleteById(first.getId())).as("逻辑删（@TableLogic ⇒ UPDATE deleted = 1）").isEqualTo(1);
        assertThat(list()).as("软删后读面看不到它").isEmpty();

        mapper.insert(row("绑带-布", "0.60", "0.25"));
        List<RemnantItemSize> after = list();
        assertThat(after).hasSize(1);
        assertThat(after.get(0).getLengthM()).as("新值生效（旧行不占唯一键）")
                .isEqualByComparingTo(new BigDecimal("0.60"));
        assertThat(db.scalar("SELECT COUNT(*) FROM remnant_small_item_specs WHERE tenant_id = "
                + RemnantTestDb.TENANT_ID).longValue())
                .as("旧行仍在表里（软删，不是物理删 —— 变更留痕的载体）").isEqualTo(2);
    }

    // ────────────────────────────────────────────── 工具

    private static RemnantItemSize row(String itemKey, String lengthM, String widthM) {
        return RemnantItemSize.builder().tenantId(RemnantTestDb.TENANT_ID).itemKey(itemKey)
                .lengthM(new BigDecimal(lengthM)).widthM(new BigDecimal(widthM))
                .operator("system").deleted(0).build();
    }

    private static List<RemnantItemSize> list() {
        return mapper.selectList(new LambdaQueryWrapper<RemnantItemSize>()
                .eq(RemnantItemSize::getTenantId, RemnantTestDb.TENANT_ID)
                .orderByAsc(RemnantItemSize::getItemKey));
    }

    private static void clearSpecs() throws Exception {
        // 用例间隔离：共用一个真库 ⇒ 先物理清空（含软删行），不依赖执行顺序
        db.exec("DELETE FROM remnant_small_item_specs WHERE tenant_id = " + RemnantTestDb.TENANT_ID);
    }

    private static String sqlStateOf(Throwable failure) {
        Throwable current = failure;
        for (int i = 0; current != null && i < 20; i++) {
            if (current instanceof SQLException sqlException) {
                return sqlException.getSQLState();
            }
            current = current.getCause();
        }
        return null;
    }
}
