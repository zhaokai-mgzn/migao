// case_ids: OR-045, OR-047
package com.migao.admin.service;

import com.migao.admin.entity.OrderLogistics;
import com.migao.admin.mapper.OrderLogisticsMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 物流写入（issue #3768 的判定本体，issue #5648 抽成单一实现点）。
 *
 * <p>两条踩过坑的规则必须有牙：① 新建时才解析发货人；② 更新时**仅显式传入**才覆盖 ——
 * 否则「别人来改一次运单号」就会把经手人换成那个人（责任凭证被静默改写）。</p>
 *
 * <p>红证方向：把更新分支的 {@code if (hasText(shipperName))} 去掉 ⇒
 * {@link #updateNeverRewritesShipperWithAnImplicitFallback} 红。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("物流写入：新建/更新两条分支 + 发货人规则")
class OrderLogisticsWriterTest {

    private static final Long TENANT = 1L;

    @Mock private OrderLogisticsMapper orderLogisticsMapper;

    private void givenExisting(OrderLogistics... rows) {
        when(orderLogisticsMapper.selectByOrderId("o1", TENANT))
                .thenReturn(new ArrayList<>(List.of(rows)));
    }

    @Test
    @DisplayName("无既有记录 ⇒ 新建（status=in_transit，发货人取显式值）")
    void createsWhenAbsent() {
        givenExisting();
        OrderLogisticsWriter.upsert(orderLogisticsMapper, TENANT, "o1", "顺丰", "SF1", "张三", () -> "兜底人");
        ArgumentCaptor<OrderLogistics> c = ArgumentCaptor.forClass(OrderLogistics.class);
        verify(orderLogisticsMapper).insert(c.capture());
        assertThat(c.getValue().getTrackingNo()).isEqualTo("SF1");
        assertThat(c.getValue().getShipperName()).isEqualTo("张三");
        assertThat(c.getValue().getStatus()).isEqualTo("in_transit");
        assertThat(c.getValue().getTenantId()).isEqualTo(TENANT);
        verify(orderLogisticsMapper, never()).updateById(any(OrderLogistics.class));
    }

    @Test
    @DisplayName("无既有记录且未给发货人 ⇒ 用兜底来源（**延迟求值**：更新路径不调用它）")
    void fallsBackOnlyOnCreate() {
        givenExisting();
        AtomicInteger calls = new AtomicInteger();
        OrderLogisticsWriter.upsert(orderLogisticsMapper, TENANT, "o1", "顺丰", "SF1", null,
                () -> { calls.incrementAndGet(); return "当前登录人"; });
        ArgumentCaptor<OrderLogistics> c = ArgumentCaptor.forClass(OrderLogistics.class);
        verify(orderLogisticsMapper).insert(c.capture());
        assertThat(c.getValue().getShipperName()).isEqualTo("当前登录人");
        assertThat(calls.get()).isEqualTo(1);
    }

    @Test
    @DisplayName("🔴 更新时**仅显式传入**才覆盖发货人（改运单号 ≠ 换经手人）")
    void updateNeverRewritesShipperWithAnImplicitFallback() {
        givenExisting(OrderLogistics.builder().id("l1").tenantId(TENANT).orderId("o1")
                .shipperName("原经手人").trackingNo("OLD").build());
        AtomicInteger calls = new AtomicInteger();
        OrderLogisticsWriter.upsert(orderLogisticsMapper, TENANT, "o1", "顺丰", "SF2", null,
                () -> { calls.incrementAndGet(); return "改单号的人"; });
        ArgumentCaptor<OrderLogistics> c = ArgumentCaptor.forClass(OrderLogistics.class);
        verify(orderLogisticsMapper).updateById(c.capture());
        assertThat(c.getValue().getShipperName())
                .as("经手人属于**新建时的**事实，不能被后来的操作人顶掉")
                .isEqualTo("原经手人");
        assertThat(c.getValue().getTrackingNo()).isEqualTo("SF2");
        assertThat(calls.get()).as("更新路径不得求值兜底来源").isZero();
        verify(orderLogisticsMapper, never()).insert(any(OrderLogistics.class));
    }

    @Test
    @DisplayName("显式传入发货人时才覆盖（工人发货路径：经手人 = 登录工人）")
    void explicitShipperOverwrites() {
        givenExisting(OrderLogistics.builder().id("l1").tenantId(TENANT).orderId("o1")
                .shipperName("原经手人").build());
        OrderLogisticsWriter.upsert(orderLogisticsMapper, TENANT, "o1", "顺丰", "SF3", "李四", () -> null);
        ArgumentCaptor<OrderLogistics> c = ArgumentCaptor.forClass(OrderLogistics.class);
        verify(orderLogisticsMapper).updateById(c.capture());
        assertThat(c.getValue().getShipperName()).isEqualTo("李四");
    }

    @Test
    @DisplayName("既有记录 status 为空 ⇒ 补 in_transit（不把空状态留在库里）")
    void fillsMissingStatusOnUpdate() {
        givenExisting(OrderLogistics.builder().id("l1").tenantId(TENANT).orderId("o1").status(null).build());
        OrderLogisticsWriter.upsert(orderLogisticsMapper, TENANT, "o1", "顺丰", "SF4", "张三", () -> null);
        ArgumentCaptor<OrderLogistics> c = ArgumentCaptor.forClass(OrderLogistics.class);
        verify(orderLogisticsMapper).updateById(c.capture());
        assertThat(c.getValue().getStatus()).isEqualTo("in_transit");
    }

    @Test
    @DisplayName("selectByOrderId 返回 null（自定义 @Select 的老坑）⇒ 按「无记录」新建，不 NPE")
    void nullSelectResultIsTreatedAsAbsent() {
        List<OrderLogistics> nullRows = null;
        when(orderLogisticsMapper.selectByOrderId("o1", TENANT)).thenReturn(nullRows);
        OrderLogisticsWriter.upsert(orderLogisticsMapper, TENANT, "o1", "顺丰", "SF5", "张三", () -> null);
        verify(orderLogisticsMapper).insert(any(OrderLogistics.class));
    }
}
