// case_ids: PRC-003
package com.migao.admin.service;

import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentMatchers;
import org.mockito.Mockito;
import org.springframework.jdbc.core.JdbcTemplate;

import java.math.BigDecimal;
import java.util.List;

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
}
