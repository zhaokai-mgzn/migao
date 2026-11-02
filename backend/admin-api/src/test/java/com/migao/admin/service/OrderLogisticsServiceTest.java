package com.migao.admin.service;
// case_ids: MC-117

import com.migao.admin.entity.OrderLogistics;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderLogisticsMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.time.OffsetDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("OrderLogisticsService 物流服务测试")
class OrderLogisticsServiceTest extends BaseServiceTest {

    @Mock private OrderLogisticsMapper orderLogisticsMapper;
    @InjectMocks private OrderLogisticsService orderLogisticsService;

    @Nested
    @DisplayName("getByOrderId")
    class GetByOrderId {

        @Test
        @DisplayName("返回物流列表")
        void returnsList() {
            OrderLogistics log = OrderLogistics.builder().id("log-1").orderId("order-1").build();
            when(orderLogisticsMapper.selectByOrderId("order-1", TEST_TENANT_ID))
                    .thenReturn(List.of(log));

            List<OrderLogistics> result = orderLogisticsService.getByOrderId("order-1");

            assertThat(result).hasSize(1);
            assertThat(result.get(0).getId()).isEqualTo("log-1");
        }

        @Test
        @DisplayName("无物流返回空列表")
        void emptyList() {
            when(orderLogisticsMapper.selectByOrderId("order-1", TEST_TENANT_ID))
                    .thenReturn(List.of());

            assertThat(orderLogisticsService.getByOrderId("order-1")).isEmpty();
        }
    }

    @Nested
    @DisplayName("getById")
    class GetById {

        @Test
        @DisplayName("返回物流详情")
        void returnsDetail() {
            OrderLogistics log = OrderLogistics.builder().id("log-1").trackingNo("SF123").build();
            when(orderLogisticsMapper.selectById("log-1")).thenReturn(log);

            assertThat(orderLogisticsService.getById("log-1").getTrackingNo()).isEqualTo("SF123");
        }

        @Test
        @DisplayName("不存在 → NOT_FOUND")
        void notFound() {
            when(orderLogisticsMapper.selectById("nonexistent")).thenReturn(null);

            assertThatThrownBy(() -> orderLogisticsService.getById("nonexistent"))
                    .isInstanceOf(BusinessException.class)
                    .satisfies(ex -> assertThat(((BusinessException) ex).getCode()).isEqualTo("NOT_FOUND"));
        }
    }

    @Nested
    @DisplayName("createLogistics（issue #7398：写面收敛到 OrderLogisticsWriter）")
    class Create {

        @Test
        @DisplayName("创建成功 → 先条件更新 0 行、再建行，返回表里的那一行")
        void success() {
            java.util.concurrent.atomic.AtomicReference<OrderLogistics> inserted = new java.util.concurrent.atomic.AtomicReference<>();
            when(orderLogisticsMapper.updateShippingDetails(TEST_TENANT_ID, "order-1", "顺丰速运", "SF123456",
                    null, null, null)).thenReturn(0);
            when(orderLogisticsMapper.insert(any(OrderLogistics.class))).thenAnswer(invocation -> {
                inserted.set(invocation.getArgument(0));
                return 1;
            });
            when(orderLogisticsMapper.selectByOrderId("order-1", TEST_TENANT_ID))
                    .thenAnswer(invocation -> List.of(inserted.get()));

            OrderLogistics result = orderLogisticsService.createLogistics(
                    "order-1", TEST_TENANT_ID, "顺丰速运", "SF123456", null);

            assertThat(result.getStatus()).isEqualTo("in_transit");
            assertThat(result.getLogisticsCompany()).isEqualTo("顺丰速运");
            assertThat(result.getTrackingNo()).isEqualTo("SF123456");
            assertThat(result.getShippedAt()).as("新建即首次发货时刻（#6276 口径，由 writer 的 insert 分支写）")
                    .isNotNull();
        }

        @Test
        @DisplayName("已有该单物流行 ⇒ 只更新、不建行（同一订单最终恰好 1 行）")
        void existingRowIsUpdatedNotDuplicated() {
            OrderLogistics existing = OrderLogistics.builder()
                    .id("log-1").tenantId(TEST_TENANT_ID).orderId("order-1")
                    .logisticsCompany("顺丰速运").trackingNo("SF-FIRST").status("in_transit").build();
            when(orderLogisticsMapper.updateShippingDetails(TEST_TENANT_ID, "order-1", "中通快递", "ZT-SECOND",
                    null, null, null)).thenReturn(1);
            when(orderLogisticsMapper.selectByOrderId("order-1", TEST_TENANT_ID)).thenReturn(List.of(existing));

            OrderLogistics result = orderLogisticsService.createLogistics(
                    "order-1", TEST_TENANT_ID, "中通快递", "ZT-SECOND", null);

            assertThat(result).isSameAs(existing);
            verify(orderLogisticsMapper, never()).insert(any(OrderLogistics.class));
        }

        @Test
        @DisplayName("🔴 同一 (tenant_id, order_id) 重复写入撞唯一索引 ⇒ 收敛为更新、不抛错（#7398）")
        void duplicateWriteConvergesToUpdate() {
            OrderLogistics winner = OrderLogistics.builder()
                    .id("log-winner").tenantId(TEST_TENANT_ID).orderId("order-1")
                    .logisticsCompany("顺丰速运").trackingNo("SF-FIRST").status("in_transit").build();
            // ① 条件更新 0 行（当时没有行）⇒ 建行；② 建行撞上并发对手已提交的行（唯一索引兜底）
            //    ⇒ writer 捕获冲突后**再**更新一次（第二次影响 1 行）—— 调用方不感知冲突、也不报错。
            when(orderLogisticsMapper.updateShippingDetails(TEST_TENANT_ID, "order-1", "中通快递", "ZT-SECOND",
                    null, null, null)).thenReturn(0, 1);
            when(orderLogisticsMapper.insert(any(OrderLogistics.class)))
                    .thenThrow(new org.springframework.dao.DuplicateKeyException("uk_order_logistics_tenant_order"));
            when(orderLogisticsMapper.selectByOrderId("order-1", TEST_TENANT_ID)).thenReturn(List.of(winner));

            OrderLogistics result = orderLogisticsService.createLogistics(
                    "order-1", TEST_TENANT_ID, "中通快递", "ZT-SECOND", null);

            assertThat(result).as("返回值以表里的行为准（不是本次入参的假实体）").isSameAs(winner);
            verify(orderLogisticsMapper, times(2)).updateShippingDetails(TEST_TENANT_ID, "order-1",
                    "中通快递", "ZT-SECOND", null, null, null);
        }
    }

    @Nested
    @DisplayName("updateLogistics")
    class Update {

        @Test
        @DisplayName("更新为 delivered → 自动设签收时间")
        void toDelivered() {
            OrderLogistics log = OrderLogistics.builder().id("log-1").status("in_transit").build();
            when(orderLogisticsMapper.selectById("log-1")).thenReturn(log);

            OrderLogistics result = orderLogisticsService.updateLogistics(
                    "log-1", null, null, "delivered");

            assertThat(result.getStatus()).isEqualTo("delivered");
            assertThat(result.getDeliveredAt()).isNotNull();
        }

        @Test
        @DisplayName("部分更新 → 只改传入字段")
        void partialUpdate() {
            OrderLogistics log = OrderLogistics.builder().id("log-1")
                    .logisticsCompany("圆通").trackingNo("YT111").status("in_transit").build();
            when(orderLogisticsMapper.selectById("log-1")).thenReturn(log);

            OrderLogistics result = orderLogisticsService.updateLogistics(
                    "log-1", null, "YT222", null);

            assertThat(result.getLogisticsCompany()).isEqualTo("圆通");
            assertThat(result.getTrackingNo()).isEqualTo("YT222");
        }

        @Test
        @DisplayName("非法状态 → VALIDATION_ERROR")
        void invalidStatus() {
            OrderLogistics log = OrderLogistics.builder().id("log-1").status("in_transit").build();
            when(orderLogisticsMapper.selectById("log-1")).thenReturn(log);

            assertThatThrownBy(() -> orderLogisticsService.updateLogistics("log-1", null, null, "unknown"))
                    .isInstanceOf(BusinessException.class)
                    .satisfies(ex -> assertThat(((BusinessException) ex).getCode()).isEqualTo("VALIDATION_ERROR"));
        }

        @Test
        @DisplayName("记录不存在 → NOT_FOUND")
        void notFound() {
            when(orderLogisticsMapper.selectById("nonexistent")).thenReturn(null);

            assertThatThrownBy(() -> orderLogisticsService.updateLogistics("nonexistent", null, null, "delivered"))
                    .isInstanceOf(BusinessException.class)
                    .satisfies(ex -> assertThat(((BusinessException) ex).getCode()).isEqualTo("NOT_FOUND"));
        }
    }

    @Nested
    @DisplayName("deleteLogistics")
    class Delete {

        @Test
        @DisplayName("删除成功")
        void success() {
            OrderLogistics log = OrderLogistics.builder().id("log-1").build();
            when(orderLogisticsMapper.selectById("log-1")).thenReturn(log);
            when(orderLogisticsMapper.deleteById("log-1")).thenReturn(1);

            orderLogisticsService.deleteLogistics("log-1");

            verify(orderLogisticsMapper).deleteById("log-1");
        }

        @Test
        @DisplayName("🔴 并发已被删（0 行）⇒ 404，不许回「删除成功」（issue #6956 · 现象 C）")
        void zeroRows_conflict() {
            OrderLogistics log = OrderLogistics.builder().id("log-1").build();
            when(orderLogisticsMapper.selectById("log-1")).thenReturn(log);
            when(orderLogisticsMapper.deleteById("log-1")).thenReturn(0);

            assertThatThrownBy(() -> orderLogisticsService.deleteLogistics("log-1"))
                    .isInstanceOf(BusinessException.class)
                    .satisfies(ex -> assertThat(((BusinessException) ex).getCode()).isEqualTo("NOT_FOUND"));
        }

        @Test
        @DisplayName("记录不存在 → NOT_FOUND")
        void notFound() {
            when(orderLogisticsMapper.selectById("nonexistent")).thenReturn(null);

            assertThatThrownBy(() -> orderLogisticsService.deleteLogistics("nonexistent"))
                    .isInstanceOf(BusinessException.class);
        }
    }
}
