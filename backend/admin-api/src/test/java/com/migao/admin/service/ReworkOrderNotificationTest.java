// case_ids: PG-098
package com.migao.admin.service;

import com.migao.admin.dto.NotificationEvent;
import com.migao.admin.entity.ReworkOrder;
import com.migao.admin.mapper.AfterSalesTicketMapper;
import com.migao.admin.mapper.ReworkOrderMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;

import java.math.BigDecimal;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.verify;

/**
 * 新增返工单 ⇒ 站内通知（issue #7860，用户追加要求：「新增返工单需要产生通知消息」）。
 *
 * <p>🔴 三条判据（每条能单独变红）：</p>
 * <ol>
 *   <li><b>两个来源都发</b>：售后开单与车间报返工都触发 `rework_order_created`（同一句模板，靠
 *       `sourceText` 区分来源）—— 漏一条 = 车间报的返工没人被叫醒；</li>
 *   <li><b>可点进单据</b>：事件带 `bizType=rework_order` / `bizId` / `bizNo` / `targetPath=/rework-orders`
 *       —— 只发一句话、点不进单据，等于把「谁去做」变成一个要人肉搜索的问句；</li>
 *   <li><b>fail-soft</b>：通知抛异常**不得**让返工单创建失败（通知是事实之后的追加，不是事实本身）。</li>
 * </ol>
 */
@DisplayName("返工单新增即通知（#7860）：两个来源都发 / 事件可点进单据 / 发送失败不影响单据")
class ReworkOrderNotificationTest {

    private static final Long TENANT = 20L;

    private ReworkOrderMapper reworkOrderMapper;
    private NotificationService notificationService;
    private ReworkOrderService service;

    @BeforeEach
    void setUp() {
        com.baomidou.mybatisplus.core.MybatisConfiguration configuration =
                new com.baomidou.mybatisplus.core.MybatisConfiguration();
        for (Class<?> entity : java.util.List.of(ReworkOrder.class,
                com.migao.admin.entity.ProcessingOrder.class, com.migao.admin.entity.Order.class)) {
            com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(
                    new org.apache.ibatis.builder.MapperBuilderAssistant(configuration, ""), entity);
        }
        reworkOrderMapper = Mockito.mock(ReworkOrderMapper.class);
        notificationService = Mockito.mock(NotificationService.class);
        service = new ReworkOrderService(reworkOrderMapper, Mockito.mock(AfterSalesTicketMapper.class),
                new com.migao.admin.time.BusinessClock());
        service.notificationService = notificationService;
        // MyBatis-Plus 的 ASSIGN_UUID 主键在 **insert 时**由框架回填 ⇒ 桩必须同款回填，
        // 否则事件里 `bizId` 恒为 null（那不是实现缺陷，是夹具没模拟框架行为）。
        Mockito.doAnswer(invocation -> {
            ReworkOrder row = invocation.getArgument(0);
            if (row.getId() == null) {
                row.setId("rw-1");
            }
            return 1;
        }).when(reworkOrderMapper).insert(Mockito.any(ReworkOrder.class));
    }

    @Test
    @DisplayName("① 车间报返工 ⇒ 发 rework_order_created，变量含单号/工序/数量/原因/来源")
    void workerReworkTriggersNotification() {
        service.createWorkerRework(TENANT, "o-1", "po-1", "op-1", "车缝", new BigDecimal("2.000"),
                "布面污渍", "worker-zhang", "张三", "log-1");

        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, String>> vars = ArgumentCaptor.forClass(Map.class);
        ArgumentCaptor<NotificationEvent> event = ArgumentCaptor.forClass(NotificationEvent.class);
        verify(notificationService).triggerForTenantAdmins(eq(TENANT), eq("rework_order_created"),
                vars.capture(), event.capture());

        assertThat(vars.getValue()).containsEntry("operationName", "车缝")
                .containsEntry("qtyText", "返工数量 2")
                .containsEntry("reason", "布面污渍")
                .containsEntry("sourceText", "车间报返工");
        assertThat(vars.getValue().get("reworkNo")).startsWith("RG");
        assertThat(event.getValue().getBizType()).isEqualTo("rework_order");
        assertThat(event.getValue().getTargetPath()).isEqualTo("/rework-orders");
        assertThat(event.getValue().getBizId()).isNotBlank();
        assertThat(event.getValue().getBizNo()).startsWith("RG");
    }

    @Test
    @DisplayName("② 售后开单 ⇒ 同一事件、来源写「售后判定要返工」")
    void afterSalesReworkTriggersNotification() {
        com.migao.admin.entity.AfterSalesTicket ticket = new com.migao.admin.entity.AfterSalesTicket();
        ticket.setId("t-1");
        ticket.setTenantId(TENANT);
        ticket.setOrderId("o-1");
        ticket.setStatus("processing");
        AfterSalesTicketMapper ticketMapper = Mockito.mock(AfterSalesTicketMapper.class);
        Mockito.when(ticketMapper.selectById("t-1")).thenReturn(ticket);
        service = new ReworkOrderService(reworkOrderMapper, ticketMapper,
                new com.migao.admin.time.BusinessClock());
        service.notificationService = notificationService;

        service.create("t-1", "客户反馈褶皱", "po-1", null);

        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, String>> vars = ArgumentCaptor.forClass(Map.class);
        verify(notificationService).triggerForTenantAdmins(eq(TENANT), eq("rework_order_created"),
                vars.capture(), any(NotificationEvent.class));
        assertThat(vars.getValue()).containsEntry("sourceText", "售后判定要返工")
                .containsEntry("reason", "客户反馈褶皱");
    }

    @Test
    @DisplayName("③ 通知发送失败 ⇒ 返工单照样创建（fail-soft，不回滚事实）")
    void notificationFailureDoesNotBreakCreation() {
        doThrow(new RuntimeException("通知通道不可用"))
                .when(notificationService).triggerForTenantAdmins(anyLong(), anyString(), any(), any());

        assertThatCode(() -> service.createWorkerRework(TENANT, "o-1", "po-1", "op-1", "车缝",
                new BigDecimal("1"), "缝线开裂", "worker-zhang", "张三", "log-1"))
                .doesNotThrowAnyException();
        verify(reworkOrderMapper).insert(any(ReworkOrder.class));
    }
}
