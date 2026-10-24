// case_ids: QC-002
package com.migao.admin.service;

import com.migao.admin.entity.AfterSalesTicket;
import com.migao.admin.entity.ReworkOrder;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.AfterSalesTicketMapper;
import com.migao.admin.mapper.ReworkOrderMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * 返工单服务（issue #7377 段 2）—— 闭环唯一三道闸 + 回写不覆盖别人的结论。
 *
 * <p>最贵的两个错：① 已闭环的售后单还能再开返工（「闭环了还在做」）；② 完成时把 `pending`
 * 直接改成 `resolved`（替客服下了结论）。两者都不会报错。</p>
 */
@DisplayName("返工单：已闭环拒开 / 同单只一个未完结 / 完成回写仅从 processing / CAS 落空")
class ReworkOrderServiceTest {

    private ReworkOrderMapper reworkOrderMapper;
    private AfterSalesTicketMapper ticketMapper;
    private ReworkOrderService service;

    @BeforeEach
    void setUp() {
        com.baomidou.mybatisplus.core.MybatisConfiguration configuration =
                new com.baomidou.mybatisplus.core.MybatisConfiguration();
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(
                new org.apache.ibatis.builder.MapperBuilderAssistant(configuration, ""), ReworkOrder.class);
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(
                new org.apache.ibatis.builder.MapperBuilderAssistant(configuration, ""),
                AfterSalesTicket.class);
        reworkOrderMapper = Mockito.mock(ReworkOrderMapper.class);
        ticketMapper = Mockito.mock(AfterSalesTicketMapper.class);
        service = new ReworkOrderService(reworkOrderMapper, ticketMapper,
                new com.migao.admin.time.BusinessClock());
    }

    private static AfterSalesTicket ticket(String status) {
        AfterSalesTicket t = new AfterSalesTicket();
        t.setId("t-1");
        t.setTenantId(1L);
        t.setOrderId("o-1");
        t.setStatus(status);
        return t;
    }

    private static ReworkOrder rework(String status) {
        return ReworkOrder.builder().id("r-1").tenantId(1L).reworkNo("RG20261022-0001")
                .afterSalesTicketId("t-1").status(status).build();
    }

    @Test
    @DisplayName("🔴 已闭环的售后单拒开返工（否则就是「闭环了单子还在做」）")
    void closedTicketCannotOpen() {
        when(ticketMapper.selectById("t-1")).thenReturn(ticket("closed"));

        assertThatThrownBy(() -> service.create("t-1", "补做", null, null))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("已闭环");
    }

    @Test
    @DisplayName("同一售后单已有未完结返工单 ⇒ 拒（「修完没有」不能有两个答案）")
    void secondOpenReworkIsRejected() {
        when(ticketMapper.selectById("t-1")).thenReturn(ticket("processing"));
        when(reworkOrderMapper.selectList(any())).thenReturn(List.of(rework("in_progress")));

        assertThatThrownBy(() -> service.create("t-1", "补做", null, null))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("未完结");
    }

    @Test
    @DisplayName("开单：初始 draft，带上售后单与订单关联")
    void createStartsAsDraft() {
        when(ticketMapper.selectById("t-1")).thenReturn(ticket("processing"));
        when(reworkOrderMapper.selectList(any())).thenReturn(List.of());

        var view = service.create("t-1", "客户投诉色差", "po-1", null);

        assertThat(view.getStatus()).isEqualTo("draft");
        assertThat(view.getAfterSalesTicketId()).isEqualTo("t-1");
        assertThat(view.getOrderId()).isEqualTo("o-1");
        Mockito.verify(reworkOrderMapper).insert(any(ReworkOrder.class));
    }

    @Test
    @DisplayName("🔴 完成回写：售后 processing ⇒ resolved")
    void completeWritesBackFromProcessing() {
        when(reworkOrderMapper.selectById("r-1")).thenReturn(rework("in_progress"));
        when(reworkOrderMapper.update(any(), any())).thenReturn(1);
        when(ticketMapper.selectById("t-1")).thenReturn(ticket("processing"));
        when(ticketMapper.update(any(), any())).thenReturn(1);

        service.complete("r-1");

        Mockito.verify(ticketMapper).update(any(), any());
    }

    @Test
    @DisplayName("🔴 完成但售后是 pending ⇒ **不回写**（不替客服下结论）")
    void completeDoesNotOverridePending() {
        when(reworkOrderMapper.selectById("r-1")).thenReturn(rework("in_progress"));
        when(reworkOrderMapper.update(any(), any())).thenReturn(1);
        when(ticketMapper.selectById("t-1")).thenReturn(ticket("pending"));

        service.complete("r-1");

        Mockito.verify(ticketMapper, Mockito.never()).update(any(), any());
    }

    @Test
    @DisplayName("没开工就完成 ⇒ 拒（跳过返工）")
    void cannotCompleteDraft() {
        when(reworkOrderMapper.selectById("r-1")).thenReturn(rework("draft"));

        assertThatThrownBy(() -> service.complete("r-1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("只有进行中的才能完成");
    }

    @Test
    @DisplayName("CAS 落空（别人先改了状态）⇒ 可读报错，不静默覆盖")
    void casLosesOnStatusChange() {
        when(reworkOrderMapper.selectById("r-1")).thenReturn(rework("draft"));
        when(reworkOrderMapper.update(any(), any())).thenReturn(0);

        assertThatThrownBy(() -> service.start("r-1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("被别人改了状态");
    }

    @Test
    @DisplayName("取消不回退售后状态（已取消 ≠ 售后已解决）")
    void cancelDoesNotTouchTicket() {
        when(reworkOrderMapper.selectById("r-1")).thenReturn(rework("in_progress"));
        when(reworkOrderMapper.update(any(), any())).thenReturn(1);

        service.cancel("r-1");

        Mockito.verify(ticketMapper, Mockito.never()).update(any(), any());
    }
}
