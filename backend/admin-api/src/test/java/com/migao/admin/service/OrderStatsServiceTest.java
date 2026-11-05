// case_ids: MC-233
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.dto.FollowStatusStatsResponse;
import com.migao.admin.dto.OrderStatisticsResponse;
import com.migao.admin.entity.Order;
import com.migao.admin.mapper.OrderMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 统计与跟进**读取**族的直测判据（issue #8681，P2-1e 第五批）：实现点搬到 {@link OrderStatsService} 之后，
 * 把「COUNT 口径与字段映射」钉在<b>实现点自己</b>身上 —— 原来这一族只被控制器测试以 mock 方式「验调用」，
 * 换句话说，<b>方法体算得对不对</b>此前没有任何判据在看。
 *
 * <p><b>它判什么</b>：① 七个 COUNT 的落位（含 {@code unpaidCount = 待付款}、{@code paidCount = 四态之和}、
 * {@code refundedCount = 已取消}这三个<b>派生字段</b>）；② {@code pending = total - following - completed}
 * 的派生口径（含 followStatus 为 null 的那部分）；③ 每条 COUNT 都带租户条件（不是「不限租户」）。</p>
 *
 * <p><b>跟进读取的三态判据不在本类</b>（issue #8681，P2-1e 第七批）：{@code getFollowStatus} 已随写面
 * {@code updateFollowStatus} 合并到 {@link OrderEntityWriteService}，三条断言<b>逐字搬到</b>
 * {@code OrderEntityWriteServiceTest}（断言零改动，只有接收者变了）。</p>
 *
 * <p><b>红证方向</b>：把任一派生字段改成直取某个计数、或把 {@code pending} 改成直取一列 ⇒ 对应的
 * {@code isEqualTo} 当场红（读数互不相同，不会互相掩盖）；把租户条件删掉 ⇒ ② 的 sqlSegment 断言红。</p>
 *
 * <p><b>复算</b>：{@code cd backend/admin-api && ./mvnw -Dtest=OrderStatsServiceTest test}。</p>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("统计与跟进读取族（#8681 P2-1e 第五批）：COUNT 口径与派生字段")
class OrderStatsServiceTest {

    @Mock
    private OrderMapper orderMapper;

    @InjectMocks
    private OrderStatsService orderStatsService;

    @BeforeEach
    void initEntityMapping() {
        // 让 LambdaQueryWrapper 能把 Order::getTenantId 解析成列名（否则取 sqlSegment 会抛 
        // "can not find lambda cache for this entity"）—— 与 OrderQuantityDecimalTest 同一套做法。
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
    }

    // ──────────────────────── 订单统计（七态 + 三个派生字段）

    @Test
    @DisplayName("订单统计：七个 COUNT 各就各位；未付款=待付款、已付款=四态之和、退款=已取消")
    void statisticsMapsCountsToFields() {
        // 依次对应：total / pending / confirmed / producing / shipped / completed / cancelled
        when(orderMapper.selectCount(any())).thenReturn(10L, 1L, 2L, 3L, 4L, 5L, 6L);

        OrderStatisticsResponse stats = orderStatsService.getOrderStatistics(7L);

        assertThat(stats.getTotalCount()).isEqualTo(10L);
        assertThat(stats.getPendingCount()).isEqualTo(1L);
        assertThat(stats.getConfirmedCount()).isEqualTo(2L);
        assertThat(stats.getProducingCount()).isEqualTo(3L);
        assertThat(stats.getShippedCount()).isEqualTo(4L);
        assertThat(stats.getCompletedCount()).isEqualTo(5L);
        assertThat(stats.getCancelledCount()).isEqualTo(6L);
        // 派生字段：口径不是「再数一遍」，而是复用已数出来的那一格（读数为互不相同的数 ⇒ 混淆必红）
        assertThat(stats.getUnpaidCount()).isEqualTo(1L);
        assertThat(stats.getPaidCount()).isEqualTo(14L);
        assertThat(stats.getRefundedCount()).isEqualTo(6L);
        verify(orderMapper, times(7)).selectCount(any());
    }

    @Test
    @DisplayName("订单统计：七条 COUNT 每一条都带租户条件（不是「不限租户」）")
    void statisticsScopesEveryCountByTenant() {
        when(orderMapper.selectCount(any())).thenReturn(0L);

        orderStatsService.getOrderStatistics(42L);

        ArgumentCaptor<LambdaQueryWrapper<Order>> captor = ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        verify(orderMapper, times(7)).selectCount(captor.capture());
        List<LambdaQueryWrapper<Order>> wrappers = captor.getAllValues();
        assertThat(wrappers).hasSize(7);
        assertThat(wrappers).allSatisfy(wrapper ->
                assertThat(wrapper.getSqlSegment()).contains("tenant_id"));
        // 反向对照：状态细分不是七条都一样的「全表数」——至少有三条带 status 条件
        assertThat(wrappers.stream().filter(w -> w.getSqlSegment().contains("status")).count())
                .isEqualTo(6L);
    }

    // ──────────────────────── 跟进统计（派生 pending）

    @Test
    @DisplayName("跟进统计：pending = total − following − completed（含未设置的 null 那部分）")
    void followStatusStatsDerivesPending() {
        when(orderMapper.selectCount(any())).thenReturn(10L, 3L, 2L);

        FollowStatusStatsResponse stats = orderStatsService.getFollowStatusStats(7L);

        assertThat(stats.getTotal()).isEqualTo(10L);
        assertThat(stats.getFollowing()).isEqualTo(3L);
        assertThat(stats.getCompleted()).isEqualTo(2L);
        assertThat(stats.getPending()).isEqualTo(5L);
        verify(orderMapper, times(3)).selectCount(any());
    }
}
