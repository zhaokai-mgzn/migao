// case_ids: OR-045, OR-047
package com.migao.admin.service;

import com.migao.admin.entity.OrderLogistics;
import com.migao.admin.mapper.OrderLogisticsMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InOrder;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.dao.DuplicateKeyException;

import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 物流写入（issue #3768 判定本体；issue #5648 抽成单一实现点；issue #7174 改成**条件更新优先**）。
 *
 * <h2>issue #7174 的病与修法</h2>
 * 原实现是「先 {@code selectByOrderId} 看有没有行，再 insert / 整实体 {@code updateById}」的**读改写** ——
 * 并发两次发货时两边都读到空 ⇒ **都 insert** ⇒ 同一订单出现两条物流记录（列表重复、后续取到哪条不确定）。
 * 现在：先 {@link OrderLogisticsMapper#updateShippingDetails}（带 {@code (tenant_id, order_id, deleted=0)}
 * 谓词的条件 UPDATE），**影响行数 = 0 才建行**；建行撞唯一索引（并发对手先建）⇒ 捕获
 * {@link DuplicateKeyException} 后**收敛为更新那一行**，不把冲突抛给调用方，最终仍恰好 1 行。
 *
 * <h2>为什么判据分两层</h2>
 * 本文件用 mock 守**调用契约**（谁被调、传了什么、什么顺序、兜底来源求值几次）——
 * 它看不见 SQL 谓词是否真的"保留原值"，那件事由真库判据
 * {@code OrderLogisticsUpsertConcurrencyRealDbTest} 守（并发两次 upsert ⇒ 恰 1 行）。
 * 两层缺一：mock 层证明「不再读改写」，真库层证明「并发下真的只有一行」。
 *
 * <p>红证方向：把 {@code upsert} 改回 {@code selectByOrderId + insert}（修法前的形态）⇒
 * {@link #updateFirst_neverInsertsWhenRowExists} 与 {@link #createFirstOrderUpdateThenInsert} 红。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("物流写入：条件更新优先 + 显式才覆盖 + 并发建行收敛")
class OrderLogisticsWriterTest {

    private static final Long TENANT = 1L;
    private static final String ORDER = "o1";

    @Mock private OrderLogisticsMapper orderLogisticsMapper;

    private void givenUpdateMatches(int rows) {
        when(orderLogisticsMapper.updateShippingDetails(any(), anyString(), any(), any(), any(), any(), any()))
                .thenReturn(rows);
    }

    @Test
    @DisplayName("🔴 有既有行（条件更新命中 1 行）⇒ **不建行**，且兜底来源零调用")
    void updateFirst_neverInsertsWhenRowExists() {
        givenUpdateMatches(1);
        AtomicInteger fallbackCalls = new AtomicInteger();

        OrderLogisticsWriter.upsert(orderLogisticsMapper, TENANT, ORDER, "顺丰", "SF2",
                (OrderLogisticsWriter.ShippingDetails) null,
                () -> { fallbackCalls.incrementAndGet(); return "改单号的人"; });

        verify(orderLogisticsMapper, never()).insert(any(OrderLogistics.class));
        assertThat(fallbackCalls.get())
                .as("更新路径不得求值兜底来源（经手人属于**新建时的**事实）")
                .isZero();
        // 「显式才覆盖」的下沉点：没显式给的三列一律传 null，交给 SQL 的 COALESCE 保留原值
        verify(orderLogisticsMapper).updateShippingDetails(TENANT, ORDER, "顺丰", "SF2", null, null, null);
    }

    @Test
    @DisplayName("🔴 无既有行（条件更新 0 行）⇒ 建行；先 update 后 insert（顺序即安全顺序）")
    void createFirstOrderUpdateThenInsert() {
        givenUpdateMatches(0);

        OrderLogisticsWriter.upsert(orderLogisticsMapper, TENANT, ORDER, "顺丰", "SF1",
                new OrderLogisticsWriter.ShippingDetails("张三", "express", "logistics"), () -> "兜底人");

        InOrder order = inOrder(orderLogisticsMapper);
        order.verify(orderLogisticsMapper)
                .updateShippingDetails(TENANT, ORDER, "顺丰", "SF1", "张三", "express", "logistics");
        ArgumentCaptor<OrderLogistics> captured = ArgumentCaptor.forClass(OrderLogistics.class);
        order.verify(orderLogisticsMapper).insert(captured.capture());

        OrderLogistics row = captured.getValue();
        assertThat(row.getTenantId()).isEqualTo(TENANT);
        assertThat(row.getOrderId()).isEqualTo(ORDER);
        assertThat(row.getTrackingNo()).isEqualTo("SF1");
        assertThat(row.getShipperName()).isEqualTo("张三");
        assertThat(row.getStatus()).isEqualTo("in_transit");
        assertThat(row.getShippedAt()).as("新建即首次发货时刻").isNotNull();
    }

    @Test
    @DisplayName("建行且未显式给发货人 ⇒ 用兜底来源（延迟求值，只发生一次）")
    void fallsBackOnlyOnCreate() {
        givenUpdateMatches(0);
        AtomicInteger calls = new AtomicInteger();

        OrderLogisticsWriter.upsert(orderLogisticsMapper, TENANT, ORDER, "顺丰", "SF1",
                (OrderLogisticsWriter.ShippingDetails) null,
                () -> { calls.incrementAndGet(); return "当前登录人"; });

        ArgumentCaptor<OrderLogistics> captured = ArgumentCaptor.forClass(OrderLogistics.class);
        verify(orderLogisticsMapper).insert(captured.capture());
        assertThat(captured.getValue().getShipperName()).isEqualTo("当前登录人");
        assertThat(calls.get()).isEqualTo(1);
    }

    @Test
    @DisplayName("显式发货人 ⇒ 传给 SQL 的是 trim 后的显式值（工人发货路径：经手人 = 登录工人）")
    void explicitShipperIsPassedThrough() {
        givenUpdateMatches(1);

        OrderLogisticsWriter.upsert(orderLogisticsMapper, TENANT, ORDER, "顺丰", "SF3",
                new OrderLogisticsWriter.ShippingDetails("  李四  ", null, null), () -> null);

        verify(orderLogisticsMapper).updateShippingDetails(TENANT, ORDER, "顺丰", "SF3", "李四", null, null);
    }

    @Test
    @DisplayName("空串 = 「本次请求没说这件事」⇒ 传 null（SQL 侧 COALESCE 保留原值），不传空串")
    void blankExplicitValuesArePassedAsNull() {
        givenUpdateMatches(1);

        OrderLogisticsWriter.upsert(orderLogisticsMapper, TENANT, ORDER, "顺丰", "SF4",
                new OrderLogisticsWriter.ShippingDetails(" ", "", "  "), () -> null);

        verify(orderLogisticsMapper)
                .updateShippingDetails(eq(TENANT), eq(ORDER), eq("顺丰"), eq("SF4"),
                        isNull(), isNull(), isNull());
    }

    @Test
    @DisplayName("🔴 建行撞并发（唯一索引冲突）⇒ 收敛为更新那一行，**不抛**给调用方")
    void duplicateInsertConvergesToUpdate() {
        when(orderLogisticsMapper.updateShippingDetails(any(), anyString(), any(), any(), any(), any(), any()))
                .thenReturn(0, 1);   // 第一次 0 行 ⇒ 建行；建行撞冲突 ⇒ 再更新一次（命中 1 行）
        when(orderLogisticsMapper.insert(any(OrderLogistics.class)))
                .thenThrow(new DuplicateKeyException(
                        "duplicate key value violates unique constraint \"uk_order_logistics_tenant_order\""));

        OrderLogisticsWriter.upsert(orderLogisticsMapper, TENANT, ORDER, "顺丰", "SF1",
                new OrderLogisticsWriter.ShippingDetails("张三", null, null), () -> null);

        verify(orderLogisticsMapper, times(2))
                .updateShippingDetails(any(), anyString(), any(), any(), any(), any(), any());
        verify(orderLogisticsMapper).insert(any(OrderLogistics.class));
    }

    @Test
    @DisplayName("🔴 建行抛出**非**唯一约束异常 ⇒ 必须原样抛出（不许把真实故障当并发冲突吞掉）")
    void nonUniqueInsertFailureIsRethrown() {
        givenUpdateMatches(0);
        org.springframework.dao.DataAccessResourceFailureException outage =
                new org.springframework.dao.DataAccessResourceFailureException("connection reset");
        when(orderLogisticsMapper.insert(any(OrderLogistics.class))).thenThrow(outage);

        org.assertj.core.api.Assertions.assertThatThrownBy(() ->
                        OrderLogisticsWriter.upsert(orderLogisticsMapper, TENANT, ORDER, "顺丰", "SF1",
                                (OrderLogisticsWriter.ShippingDetails) null, () -> null))
                .as("别的写库异常必须冒出来（只吞唯一约束冲突）")
                .isSameAs(outage);
        verify(orderLogisticsMapper, times(1))
                .updateShippingDetails(any(), anyString(), any(), any(), any(), any(), any());
    }

    @Test
    @DisplayName("从不再读改写：整个 upsert 期间**不得**调用 selectByOrderId / updateById")
    void neverUsesReadModifyWrite() {
        givenUpdateMatches(0);
        OrderLogisticsWriter.upsert(orderLogisticsMapper, TENANT, ORDER, "顺丰", "SF1",
                (OrderLogisticsWriter.ShippingDetails) null, () -> "x");
        verify(orderLogisticsMapper, never()).selectByOrderId(anyString(), anyLong());
        verify(orderLogisticsMapper, never()).updateById(any(OrderLogistics.class));
    }
}
