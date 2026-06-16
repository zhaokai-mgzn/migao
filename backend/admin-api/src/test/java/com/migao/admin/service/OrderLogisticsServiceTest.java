package com.migao.admin.service;

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
    @DisplayName("createLogistics")
    class Create {

        @Test
        @DisplayName("创建成功 → in_transit 状态")
        void success() {
            OrderLogistics result = orderLogisticsService.createLogistics(
                    "order-1", TEST_TENANT_ID, "顺丰速运", "SF123456");

            assertThat(result.getStatus()).isEqualTo("in_transit");
            assertThat(result.getLogisticsCompany()).isEqualTo("顺丰速运");
            assertThat(result.getTrackingNo()).isEqualTo("SF123456");
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

            orderLogisticsService.deleteLogistics("log-1");

            verify(orderLogisticsMapper).selectById("log-1");
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
