// case_ids: MC-241
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.dto.FollowStatusResponse;
import com.migao.admin.entity.Order;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.OffsetDateTime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.when;

/**
 * 订单**实体写面**的跟进读取三态直测判据（issue #8681，P2-1e 第七批）。
 *
 * <p><b>这组判据为什么搬到这里</b>：第五批把 {@code getFollowStatus}（读）搬进
 * {@link OrderStatsService}，而写面 {@code updateFollowStatus} 留在门面 ⇒ 同一语义分处两个文件
 * （当批登记为返工点）。本批把写面搬进 {@link OrderEntityWriteService}，读面**同批并回**
 * —— 判据跟着实现点走，<b>断言本身一个字都没改</b>（只是接收者从 {@code orderStatsService}
 * 换成 {@code orderEntityWriteService}），所以「读得到 / 未设置回落 {@code pending} / 不存在 ⇒ 404」
 * 这三条口径的看管强度不变。</p>
 *
 * <p><b>红证方向</b>：把回落值从 {@code "pending"} 改成 {@code null} 或空串 ⇒ 第二条红；
 * 把 404 改成返回空壳 ⇒ 第三条红；让 {@code updatedAt} 另取时钟 ⇒ 第一条红。</p>
 *
 * <p><b>复算</b>：{@code cd backend/admin-api && ./mvnw -Dtest=OrderEntityWriteServiceTest test}。</p>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("实体写面 · 跟进读取三态（#8681 P2-1e 第七批）：读写同址后仍不另造口径")
class OrderEntityWriteServiceTest {

    @Mock
    private OrderMapper orderMapper;

    @InjectMocks
    private OrderEntityWriteService orderEntityWriteService;

    @BeforeEach
    void initEntityMapping() {
        // 让 LambdaUpdateWrapper / LambdaQueryWrapper 能把 Order::getId 解析成列名
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
    }

    @Test
    @DisplayName("跟进读取：读得到 ⇒ 返回该单的跟进状态与更新时间（不另造口径）")
    void followStatusReturnsStoredValue() {
        OffsetDateTime updatedAt = OffsetDateTime.parse("2026-11-05T10:00:00+08:00");
        when(orderMapper.selectById("order-1")).thenReturn(Order.builder()
                .id("order-1").tenantId(7L).followStatus("completed").updatedAt(updatedAt).build());

        FollowStatusResponse response = orderEntityWriteService.getFollowStatus("order-1");

        assertThat(response.getOrderId()).isEqualTo("order-1");
        assertThat(response.getFollowStatus()).isEqualTo("completed");
        assertThat(response.getUpdatedAt()).isEqualTo(updatedAt);
    }

    @Test
    @DisplayName("跟进读取：未设置跟进状态 ⇒ 回落 pending（不是 null、也不是空串）")
    void followStatusFallsBackToPending() {
        when(orderMapper.selectById("order-2")).thenReturn(Order.builder()
                .id("order-2").tenantId(7L).followStatus(null).build());

        FollowStatusResponse response = orderEntityWriteService.getFollowStatus("order-2");

        assertThat(response.getFollowStatus()).isEqualTo("pending");
    }

    @Test
    @DisplayName("跟进读取：订单不存在 ⇒ 404（fail-closed，不是返回空壳）")
    void followStatusMissingOrderIsNotFound() {
        when(orderMapper.selectById("order-missing")).thenReturn(null);

        assertThatThrownBy(() -> orderEntityWriteService.getFollowStatus("order-missing"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("订单");
    }
}
