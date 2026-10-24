// case_ids: PRC-003, PRC-005
package com.migao.admin.service;

import com.migao.admin.dto.PriceBookView;
import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentMatchers;
import org.mockito.Mockito;
import org.springframework.jdbc.core.JdbcTemplate;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

/**
 * 价格本录入（issue #7375 段 3）—— 「价格必须 > 0」「阶梯区间合法」「upsert 靠唯一索引」三条。
 *
 * <p>为什么值得单测：价格本一旦录入 0 或负数，段 2 的下单定价会把它当成「有价」，
 * 结果就是 0 元成交 / 负金额订单 —— 而这两件事在页面上都只是「一个数字」。</p>
 */
@DisplayName("价格本录入：价格必须 > 0 / 阶梯区间合法 / 软删找不到即 404")
class PriceBookServiceTest {

    private JdbcTemplate jdbcTemplate;
    private PriceBookService service;

    @BeforeEach
    void setUp() {
        jdbcTemplate = Mockito.mock(JdbcTemplate.class);
        service = new PriceBookService(jdbcTemplate);
        when(jdbcTemplate.update(anyString(), ArgumentMatchers.<Object[]>any())).thenReturn(1);
    }

    @Test
    @DisplayName("🔴 价格必须 > 0：0 元与负数一律拒（0 元 = 白送；未定价就不该录）")
    void priceMustBePositive() {
        assertThatThrownBy(() -> service.upsertProtocol(1L, "c-1", 10L, BigDecimal.ZERO, null))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("必须大于 0");
        assertThatThrownBy(() -> service.upsertVipLevel(1L, "vip1", 10L, new BigDecimal("-1")))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("必须大于 0");
        assertThatThrownBy(() -> service.upsertTier(1L, 10L, BigDecimal.ONE, null, BigDecimal.ZERO))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("必须大于 0");
    }

    @Test
    @DisplayName("阶梯：起订量必须 > 0，上限不能小于起订量")
    void tierRangeMustBeSane() {
        assertThatThrownBy(() -> service.upsertTier(1L, 10L, BigDecimal.ZERO, null, new BigDecimal("88")))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("起订量");
        assertThatThrownBy(() -> service.upsertTier(1L, 10L, new BigDecimal("50"), new BigDecimal("10"),
                new BigDecimal("88")))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("上限");
    }

    @Test
    @DisplayName("协议价 upsert 走 `ON CONFLICT … DO UPDATE`（同客户同 SKU 只留一条生效价）")
    void protocolUpsertUsesConflictClause() {
        service.upsertProtocol(1L, " c-1 ", 10L, new BigDecimal("88.00"), "老客户");

        // `update(String, Object...)` 是**可变参数** ⇒ 混合匹配器/捕获器在 varargs 上都不可靠。
        // 直接读实际调用列表（第一个参数永远是 SQL 文本），断言文本里带冲突条款。
        java.util.List<String> sqls = Mockito.mockingDetails(jdbcTemplate).getInvocations().stream()
                .filter(i -> "update".equals(i.getMethod().getName()))
                .map(i -> String.valueOf(i.<Object>getArgument(0)))
                .toList();
        org.assertj.core.api.Assertions.assertThat(sqls)
                .anySatisfy(sql -> org.assertj.core.api.Assertions.assertThat(sql)
                        .contains("ON CONFLICT (tenant_id, customer_id, sku_id)")
                        .contains("DO UPDATE SET price = EXCLUDED.price"));
    }

    @Test
    @DisplayName("软删：类型必须是三类之一；找不到 ⇒ 404 语义（不是静默成功）")
    void removeValidatesKindAndExistence() {
        assertThatThrownBy(() -> service.remove(1L, "promo", "1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("protocol");
        when(jdbcTemplate.update(anyString(), ArgumentMatchers.<Object[]>any())).thenReturn(0);
        assertThatThrownBy(() -> service.remove(1L, "protocol", "1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("价格本");
    }

    @Test
    @DisplayName("读面必须指定 SKU（价格本是按 SKU 维护的）")
    void listRequiresSku() {
        assertThatThrownBy(() -> service.list(1L, null, null))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("skuId");
    }

    @Test
    @DisplayName("🔴 协议价的行给的是**客户展示名**（join 客户档案 + 两级兜底；绝不把客户 id 当名字）")
    void protocolRowsCarryCustomerDisplayName() {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("id", "1");
        row.put("customer_id", "c-1");
        row.put("price", new BigDecimal("88"));
        row.put("customer_name", "王芳");
        when(jdbcTemplate.<Map<String, Object>>queryForList(
                ArgumentMatchers.contains("customer_sku_prices"), any(Object.class), any(Object.class)))
                .thenReturn(List.of(row));
        when(jdbcTemplate.<Map<String, Object>>queryForList(
                ArgumentMatchers.contains("vip_level_prices"), any(Object.class), any(Object.class)))
                .thenReturn(List.of());
        when(jdbcTemplate.<Map<String, Object>>queryForList(
                ArgumentMatchers.contains("sku_tier_prices"), any(Object.class), any(Object.class)))
                .thenReturn(List.of());

        PriceBookView view = service.list(1L, 10L, null);

        // ① 展示名随行下发（页面直接渲染名字，不再印内部编号）
        org.assertj.core.api.Assertions.assertThat(view.getProtocol()).hasSize(1);
        org.assertj.core.api.Assertions.assertThat(view.getProtocol().get(0))
                .containsEntry("customer_name", "王芳")
                .containsEntry("customer_id", "c-1");

        // ② 判的是**读面契约**：查询必须 join 客户档案，且兜底写在 SQL 里
        //    （缺名 ⇒ 手机号 / 未命名客户；档案不存在 ⇒ 客户已移除）—— 否则前端只能退回印 id
        String protocolSql = Mockito.mockingDetails(jdbcTemplate).getInvocations().stream()
                .filter(i -> "queryForList".equals(i.getMethod().getName()))
                .map(i -> String.valueOf(i.<Object>getArgument(0)))
                .filter(sql -> sql.contains("customer_sku_prices"))
                .findFirst()
                .orElseThrow(() -> new AssertionError("没有走到协议价查询"));
        org.assertj.core.api.Assertions.assertThat(protocolSql)
                .contains("LEFT JOIN customer_profiles")
                .contains("AS customer_name")
                .contains("客户已移除")
                .contains("未命名客户");
    }
}
