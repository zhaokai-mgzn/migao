package com.migao.admin.mapper;

// case_ids: PR-041, PR-046, PR-047

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductSku;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.lang.reflect.Parameter;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * ProductSkuMapper 契约测试（V111 入库扩展，issue #5034）。
 *
 * <p>本单在既有 Mapper 上加了 {@code receiveStock}（入库：加库存 + 写移动加权均价 + 记最近批次号）。
 * 它守三条判据：</p>
 * <ol>
 *   <li><b>只按 id 定位</b>：{@code WHERE id = #{skuId}} —— 库存是 SKU 级权威（issue #4038），
 *       按「颜色+门幅」之类的组合条件更新会在组合漂移时改到**另一行**；</li>
 *   <li><b>均价由调用方传入</b>：SQL 里**不得**出现加权平均公式 —— 公式只有
 *       {@code InboundOrderService.movingAverage} 一处实现，两边各写一份迟早漂移，
 *       而漂移的表现是「台账 avg_cost_after 与 SKU 上的 avg_cost 不一致」（只在事后对账时才看得见）；</li>
 *   <li><b>成本未知不得写成 0</b>：{@code avg_cost = #{newAvgCost}} 直接写（可为 NULL），
 *       {@code cost_amount} 在均价为 NULL 时也必须留 NULL（0 会被读成「成本为零」的真数据）。</li>
 * </ol>
 */
@DisplayName("ProductSkuMapper 契约（入库 receiveStock + 既有库存增减）")
class ProductSkuMapperTest {

    private static String sqlOf(String name, Class<?>... params) throws NoSuchMethodException {
        Method m = ProductSkuMapper.class.getMethod(name, params);
        Update update = m.getAnnotation(Update.class);
        assertThat(update).as("%s 必须标 @Update", name).isNotNull();
        return String.join("\n", update.value());
    }

    @Test
    @DisplayName("receiveStock：按 id 定位（库存权威是 SKU 级，不得用组合条件更新）")
    void receiveStockTargetsSingleSkuById() throws NoSuchMethodException {
        String sql = sqlOf("receiveStock", Long.class, java.math.BigDecimal.class,
                java.math.BigDecimal.class, String.class);
        assertThat(sql).contains("WHERE id = #{skuId}");
        assertThat(sql).doesNotContain("color_id");
        assertThat(sql).doesNotContain("door_width");
    }

    @Test
    @DisplayName("receiveStock：加库存 + 写均价 + 记最近批次号（三件事一条 SQL，无中间态）")
    void receiveStockWritesStockCostAndBatch() throws NoSuchMethodException {
        String sql = sqlOf("receiveStock", Long.class, java.math.BigDecimal.class,
                java.math.BigDecimal.class, String.class);
        assertThat(sql).contains("stock = COALESCE(stock, 0) + #{quantity}");
        assertThat(sql).contains("avg_cost = #{newAvgCost}");
        assertThat(sql).contains("latest_batch_no = #{batchNo}");
        assertThat(sql).contains("cost_amount =");
    }

    @Test
    @DisplayName("receiveStock：SQL 里**不得**出现加权平均公式（公式只有 Java 一处实现）")
    void receiveStockDoesNotReimplementMovingAverage() throws NoSuchMethodException {
        String sql = sqlOf("receiveStock", Long.class, java.math.BigDecimal.class,
                java.math.BigDecimal.class, String.class);
        // 均价由调用方算好传入；SQL 里出现除法/旧均价参与运算 = 第二份公式实现
        assertThat(sql).doesNotContain("avg_cost +");
        assertThat(sql).doesNotContain("avg_cost *");
        assertThat(sql).doesNotContain("old_avg");
    }

    @Test
    @DisplayName("receiveStock：成本未知时 cost_amount 留 NULL（不用 0 冒充「成本为零」）")
    void receiveStockKeepsCostAmountNullWhenCostUnknown() throws NoSuchMethodException {
        String sql = sqlOf("receiveStock", Long.class, java.math.BigDecimal.class,
                java.math.BigDecimal.class, String.class);
        assertThat(sql).contains("CASE WHEN #{newAvgCost} IS NULL THEN NULL");
    }

    @Test
    @DisplayName("receiveStock 的四个参数都标 @Param（不标 ⇒ MyBatis 按 arg0/param1 绑定，改签名即静默错位）")
    void receiveStockParamsAreNamed() throws NoSuchMethodException {
        Method m = ProductSkuMapper.class.getMethod("receiveStock", Long.class, java.math.BigDecimal.class,
                java.math.BigDecimal.class, String.class);
        for (Parameter p : m.getParameters()) {
            assertThat(p.getAnnotation(Param.class)).as("参数 %s 必须标 @Param", p.getName()).isNotNull();
        }
        assertThat(sqlOf("receiveStock", Long.class, java.math.BigDecimal.class,
                java.math.BigDecimal.class, String.class))
                .contains("#{skuId}").contains("#{quantity}")
                .contains("#{newAvgCost}").contains("#{batchNo}");
    }

    @Test
    @DisplayName("既有库存增减（deductStock / restoreStock）仍是按 id 的原子 UPDATE，未被本单改坏")
    void existingStockOpsUnchanged() throws NoSuchMethodException {
        String deduct = sqlOf("deductStock", Long.class, java.math.BigDecimal.class);
        assertThat(deduct).contains("WHERE id = #{skuId}");
        assertThat(deduct).contains("GREATEST(COALESCE(stock, 0) - #{quantity}, 0)");
        String restore = sqlOf("restoreStock", Long.class, java.math.BigDecimal.class);
        assertThat(restore).contains("WHERE id = #{skuId}");
        assertThat(restore).contains("COALESCE(stock, 0) + #{quantity}");
    }

    @Test
    @DisplayName("PR-046/047 数量参数一律 BigDecimal（int 形参会强迫调用方在边界上静默取整）")
    void quantityParamsAreBigDecimalSoCallersCannotTruncate() throws NoSuchMethodException {
        // issue #5063：库存/销量列已是 NUMERIC(12,1) ⇒ 形参是 int 的话，调用方必须在边界上取整，
        // 而那种取整是静默的（买 2.7 米扣 2 米、0.7 米凭空消失）—— 本判据把它钉死在签名上。
        for (String name : new String[]{"deductStock", "restoreStock", "increaseSalesCount",
                "decreaseSalesCount"}) {
            assertThat(ProductSkuMapper.class.getMethod(name, Long.class, java.math.BigDecimal.class))
                    .as("%s 的 quantity 形参必须是 BigDecimal", name).isNotNull();
            assertThatThrownBy(() -> ProductSkuMapper.class.getMethod(name, Long.class, int.class))
                    .as("%s 不得还存在 int 形参的重载（会诱导调用方取整）", name)
                    .isInstanceOf(NoSuchMethodException.class);
        }
        assertThat(ProductSkuMapper.class.getMethod("receiveStock", Long.class,
                java.math.BigDecimal.class, java.math.BigDecimal.class, String.class)).isNotNull();
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(ProductSkuMapper.class)).isTrue();
    }
}
