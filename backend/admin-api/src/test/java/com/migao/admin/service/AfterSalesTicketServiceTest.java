// case_ids: AS-001, AS-002, AS-003, AS-004, AS-005

package com.migao.admin.service;

import com.migao.admin.dto.*;
import com.migao.admin.entity.AfterSalesTicket;
import com.migao.admin.entity.Order;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.AfterSalesTicketMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.TicketTimelineMapper;
import com.migao.admin.entity.TicketTimeline;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * AfterSalesTicketService 单元测试
 */
@ExtendWith(MockitoExtension.class)
class AfterSalesTicketServiceTest {

    @InjectMocks
    private AfterSalesTicketService afterSalesTicketService;

    @Mock
    private AfterSalesTicketMapper afterSalesTicketMapper;

    @Mock
    private OrderMapper orderMapper;

    @Mock
    private TicketTimelineMapper ticketTimelineMapper;

    @Mock
    private ObjectMapper objectMapper;

    @Mock
    private FinanceService financeService;

    private AfterSalesTicket testTicket;
    private Order testOrder;

    @BeforeEach
    void setUp() {
        testOrder = Order.builder()
                .id("order-001")
                .tenantId(1L)
                .orderNo("ORD-20250425-001")
                .customerName("张三")
                .customerPhone("13800138000")
                .totalAmount(new BigDecimal("999.00"))
                .actualAmount(new BigDecimal("999.00"))
                .status("shipped")
                .build();

        testTicket = AfterSalesTicket.builder()
                .id("ticket-001")
                .tenantId(1L)
                .ticketNo("AS-20250425-0001")
                .orderId("order-001")
                .customerId("张三")
                .ticketType("return")
                .status("pending")
                .description("商品有质量问题")
                .source("agent")
                .priority("normal")
                .createdAt(OffsetDateTime.now())
                .updatedAt(OffsetDateTime.now())
                .build();
    }

    // ======================== 分页查询测试 ========================

    @Test
    @DisplayName("分页查询售后工单 - 默认分页")
    void getTicketPage_DefaultPagination() {
        // given
        Page<AfterSalesTicket> mockPage = new Page<>(1, 20);
        mockPage.setRecords(List.of(testTicket));
        mockPage.setTotal(1);

        when(afterSalesTicketMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(mockPage);
        when(orderMapper.selectBatchIds(anyCollection())).thenReturn(List.of(testOrder));

        // when
        PageResponse<AfterSalesListResponse> result = afterSalesTicketService.getTicketPage(
                1, 20, null, null, null, 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getTotal()).isEqualTo(1);
        assertThat(result.getItems()).hasSize(1);
        assertThat(result.getItems().get(0).getTicketNo()).isEqualTo("AS-20250425-0001");
        assertThat(result.getItems().get(0).getOrderNo()).isEqualTo("ORD-20250425-001");
        assertThat(result.getItems().get(0).getCustomerName()).isEqualTo("张三");
    }

    @Test
    @DisplayName("分页查询售后工单 - 带状态和类型筛选")
    void getTicketPage_WithFilters() {
        // given
        Page<AfterSalesTicket> mockPage = new Page<>(1, 10);
        mockPage.setRecords(List.of(testTicket));
        mockPage.setTotal(1);

        when(afterSalesTicketMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(mockPage);
        when(orderMapper.selectBatchIds(anyCollection())).thenReturn(List.of(testOrder));

        // when
        PageResponse<AfterSalesListResponse> result = afterSalesTicketService.getTicketPage(
                1, 10, "pending", "return", null, 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getItems()).hasSize(1);
    }

    @Test
    @DisplayName("分页查询售后工单 - 空结果")
    void getTicketPage_EmptyResult() {
        // given
        Page<AfterSalesTicket> emptyPage = new Page<>(1, 20);
        emptyPage.setRecords(List.of());
        emptyPage.setTotal(0);

        when(afterSalesTicketMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(emptyPage);

        // when
        PageResponse<AfterSalesListResponse> result = afterSalesTicketService.getTicketPage(
                1, 20, null, null, null, 1L);

        // then
        assertThat(result.getTotal()).isEqualTo(0);
        assertThat(result.getItems()).isEmpty();
    }

    // ======================== 工单详情测试 ========================

    @Test
    @DisplayName("查询工单详情 - 成功")
    void getTicketById_Success() {
        // given
        when(afterSalesTicketMapper.selectById("ticket-001")).thenReturn(testTicket);
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);

        // when
        AfterSalesDetailResponse result = afterSalesTicketService.getTicketById("ticket-001");

        // then
        assertThat(result).isNotNull();
        assertThat(result.getTicketNo()).isEqualTo("AS-20250425-0001");
        assertThat(result.getOrderNo()).isEqualTo("ORD-20250425-001");
        assertThat(result.getCustomerName()).isEqualTo("张三");
        assertThat(result.getStatus()).isEqualTo("pending");
        assertThat(result.getStatusHistory()).isNotEmpty();
    }

    @Test
    @DisplayName("查询工单详情 - 工单不存在")
    void getTicketById_NotFound() {
        // given
        when(afterSalesTicketMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> afterSalesTicketService.getTicketById("nonexistent"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    // ======================== 创建工单测试 ========================

    @Test
    @DisplayName("创建售后工单成功")
    void createTicket_Success() {
        // given
        AfterSalesCreateRequest request = new AfterSalesCreateRequest();
        request.setOrderId("order-001");
        request.setTicketType("return");
        request.setDescription("商品有质量问题");
        request.setPriority("urgent");
        request.setRefundAmount(new BigDecimal("999.00"));
        request.setImages(List.of("https://example.com/evidence.jpg"));

        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        // 该订单无活跃工单 → 允许创建
        when(afterSalesTicketMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
        when(afterSalesTicketMapper.insert(any(AfterSalesTicket.class))).thenAnswer(invocation -> {
            AfterSalesTicket t = invocation.getArgument(0);
            t.setId("ticket-new");
            return 1;
        });
        // getTicketById 内部调用
        AfterSalesTicket savedTicket = AfterSalesTicket.builder()
                .id("ticket-new")
                .tenantId(1L)
                .ticketNo("AS-20250425-0002")
                .orderId("order-001")
                .customerId("张三")
                .ticketType("return")
                .status("pending")
                .description("商品有质量问题")
                .priority("urgent")
                .source("agent")
                .refundAmount(new BigDecimal("999.00"))
                .images(List.of("https://example.com/evidence.jpg"))
                .createdAt(OffsetDateTime.now())
                .updatedAt(OffsetDateTime.now())
                .build();
        when(afterSalesTicketMapper.selectById("ticket-new")).thenReturn(savedTicket);
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);

        // when
        AfterSalesDetailResponse result = afterSalesTicketService.createTicket(request, 1L, "test-user");

        // then
        assertThat(result).isNotNull();
        assertThat(result.getTicketType()).isEqualTo("return");
        assertThat(result.getStatus()).isEqualTo("pending");
        verify(afterSalesTicketMapper).insert(any(AfterSalesTicket.class));
    }

    @Test
    @DisplayName("创建售后工单失败 - 关联订单不存在")
    void createTicket_OrderNotFound() {
        // given
        AfterSalesCreateRequest request = new AfterSalesCreateRequest();
        request.setOrderId("nonexistent-order");
        request.setTicketType("return");
        request.setDescription("问题描述");

        when(orderMapper.selectById("nonexistent-order")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> afterSalesTicketService.createTicket(request, 1L, "test-user"))
                .isInstanceOf(BusinessException.class)
                .hasMessage("关联订单不存在");
    }

    @Test
    @DisplayName("创建投诉工单成功 - 投诉类型可无关联订单（转人工场景）")
    void createTicket_ComplaintWithoutOrder_Success() {
        // given：complaint 类型无订单（不 mock orderMapper.selectById）
        AfterSalesCreateRequest request = new AfterSalesCreateRequest();
        request.setOrderId(null);
        request.setTicketType("complaint");
        request.setDescription("对服务不满意，要求负责人处理");

        when(afterSalesTicketMapper.insert(any(AfterSalesTicket.class))).thenAnswer(invocation -> {
            AfterSalesTicket t = invocation.getArgument(0);
            t.setId("ticket-complaint");
            return 1;
        });
        AfterSalesTicket savedTicket = AfterSalesTicket.builder()
                .id("ticket-complaint")
                .tenantId(1L)
                .ticketNo("AS-20250425-0003")
                .ticketType("complaint")
                .status("pending")
                .description("对服务不满意，要求负责人处理")
                .source("agent")
                .createdAt(OffsetDateTime.now())
                .updatedAt(OffsetDateTime.now())
                .build();
        when(afterSalesTicketMapper.selectById("ticket-complaint")).thenReturn(savedTicket);

        // when
        AfterSalesDetailResponse result = afterSalesTicketService.createTicket(request, 1L, "test-user");

        // then
        assertThat(result).isNotNull();
        assertThat(result.getTicketType()).isEqualTo("complaint");
        verify(afterSalesTicketMapper).insert(any(AfterSalesTicket.class));
    }

    @Test
    @DisplayName("创建工单被拒 — 同类型活跃工单已存在")
    void createTicket_DuplicateSameType() {
        AfterSalesCreateRequest request = new AfterSalesCreateRequest();
        request.setOrderId("order-001");
        request.setTicketType("return");
        request.setDescription("又一个退货");

        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        // 该订单已有 pending 状态的 return 工单
        when(afterSalesTicketMapper.selectList(any(LambdaQueryWrapper.class)))
            .thenReturn(List.of(testTicket));

        assertThatThrownBy(() -> afterSalesTicketService.createTicket(request, 1L, "test-user"))
            .isInstanceOf(BusinessException.class)
            .hasMessageContaining("已有")
            .hasMessageContaining("退货")
            .hasMessageNotContaining("return");
    }

    @Test
    @DisplayName("创建工单允许 — 不同类型活跃工单（警告不阻止）")
    void createTicket_DifferentTypeAllowed() {
        AfterSalesCreateRequest request = new AfterSalesCreateRequest();
        request.setOrderId("order-001");
        request.setTicketType("repair");
        request.setDescription("维修问题");

        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        // 已有 return 工单，新建 complaint → 允许
        when(afterSalesTicketMapper.selectList(any(LambdaQueryWrapper.class)))
            .thenReturn(List.of(testTicket));
        when(afterSalesTicketMapper.insert(any(AfterSalesTicket.class))).thenAnswer(inv -> {
            AfterSalesTicket t = inv.getArgument(0);
            t.setId("ticket-complaint");
            return 1;
        });
        when(afterSalesTicketMapper.selectById("ticket-complaint"))
            .thenReturn(AfterSalesTicket.builder().id("ticket-complaint").tenantId(1L)
                .ticketNo("AS-test").orderId("order-001").customerId("张三")
                .ticketType("complaint").status("pending").description("投诉问题")
                .priority("normal").source("agent")
                .createdAt(OffsetDateTime.now()).updatedAt(OffsetDateTime.now()).build());

        AfterSalesDetailResponse result = afterSalesTicketService.createTicket(request, 1L, "test-user");
        assertThat(result).isNotNull();
        assertThat(result.getTicketType()).isEqualTo("complaint");
    }

    // ======================== 更新工单状态测试 ========================

    @Test
    @DisplayName("更新工单状态 - pending -> processing")
    void updateTicketStatus_PendingToProcessing() {
        // given
        AfterSalesStatusUpdateRequest request = new AfterSalesStatusUpdateRequest();
        request.setStatus("processing");

        when(afterSalesTicketMapper.selectById("ticket-001")).thenReturn(testTicket);
        when(afterSalesTicketMapper.updateById(any(AfterSalesTicket.class))).thenReturn(1);

        // when
        afterSalesTicketService.updateTicketStatus("ticket-001", request);

        // then
        verify(afterSalesTicketMapper).updateById(argThat(
                (AfterSalesTicket t) -> "processing".equals(t.getStatus())));
    }

    @Test
    @DisplayName("更新工单状态 - pending -> rejected（含关闭原因）")
    void updateTicketStatus_PendingToRejected() {
        // given
        AfterSalesStatusUpdateRequest request = new AfterSalesStatusUpdateRequest();
        request.setStatus("rejected");
        request.setRemark("不符合售后条件");

        when(afterSalesTicketMapper.selectById("ticket-001")).thenReturn(testTicket);
        when(afterSalesTicketMapper.updateById(any(AfterSalesTicket.class))).thenReturn(1);

        // when
        afterSalesTicketService.updateTicketStatus("ticket-001", request);

        // then
        verify(afterSalesTicketMapper).updateById(argThat((AfterSalesTicket t) ->
                "rejected".equals(t.getStatus())
                        && t.getClosedAt() != null
                        && "不符合售后条件".equals(t.getCloseReason())));
    }

    @Test
    @DisplayName("更新工单状态 - processing -> resolved")
    void updateTicketStatus_ProcessingToResolved() {
        // given
        AfterSalesTicket processingTicket = AfterSalesTicket.builder()
                .id("ticket-002")
                .status("processing")
                .build();

        AfterSalesStatusUpdateRequest request = new AfterSalesStatusUpdateRequest();
        request.setStatus("resolved");

        when(afterSalesTicketMapper.selectById("ticket-002")).thenReturn(processingTicket);
        when(afterSalesTicketMapper.updateById(any(AfterSalesTicket.class))).thenReturn(1);

        // when
        afterSalesTicketService.updateTicketStatus("ticket-002", request);

        // then
        verify(afterSalesTicketMapper).updateById(argThat(
                (AfterSalesTicket t) -> "resolved".equals(t.getStatus())));
    }

    @Test
    @DisplayName("更新工单状态 - processing -> closed（含关闭时间）")
    void updateTicketStatus_ProcessingToClosed() {
        // given
        AfterSalesTicket processingTicket = AfterSalesTicket.builder()
                .id("ticket-003")
                .status("processing")
                .build();

        AfterSalesStatusUpdateRequest request = new AfterSalesStatusUpdateRequest();
        request.setStatus("closed");
        request.setRemark("客户撤销申请");

        when(afterSalesTicketMapper.selectById("ticket-003")).thenReturn(processingTicket);
        when(afterSalesTicketMapper.updateById(any(AfterSalesTicket.class))).thenReturn(1);

        // when
        afterSalesTicketService.updateTicketStatus("ticket-003", request);

        // then
        verify(afterSalesTicketMapper).updateById(argThat((AfterSalesTicket t) ->
                "closed".equals(t.getStatus())
                        && t.getClosedAt() != null
                        && "客户撤销申请".equals(t.getCloseReason())));
    }

    @Test
    @DisplayName("更新工单状态失败 - 非法状态流转 pending -> resolved（报错中文术语）")
    void updateTicketStatus_InvalidTransition() {
        // given
        AfterSalesStatusUpdateRequest request = new AfterSalesStatusUpdateRequest();
        request.setStatus("resolved");

        when(afterSalesTicketMapper.selectById("ticket-001")).thenReturn(testTicket);

        // when & then: 报错用中文状态术语，不得暴露英文枚举
        assertThatThrownBy(() -> afterSalesTicketService.updateTicketStatus("ticket-001", request))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("待处理")
                .hasMessageContaining("已解决")
                .hasMessageNotContaining("pending")
                .hasMessageNotContaining("resolved");
    }

    @Test
    @DisplayName("更新工单状态失败 - 终态不允许再变更")
    void updateTicketStatus_TerminalStateNoTransition() {
        // given
        AfterSalesTicket resolvedTicket = AfterSalesTicket.builder()
                .id("ticket-004")
                .status("resolved")
                .build();

        AfterSalesStatusUpdateRequest request = new AfterSalesStatusUpdateRequest();
        request.setStatus("processing");

        when(afterSalesTicketMapper.selectById("ticket-004")).thenReturn(resolvedTicket);

        // when & then
        assertThatThrownBy(() -> afterSalesTicketService.updateTicketStatus("ticket-004", request))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不允许");
    }

    @Test
    @DisplayName("更新工单状态失败 - 工单不存在")
    void updateTicketStatus_TicketNotFound() {
        // given
        AfterSalesStatusUpdateRequest request = new AfterSalesStatusUpdateRequest();
        request.setStatus("processing");

        when(afterSalesTicketMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> afterSalesTicketService.updateTicketStatus("nonexistent", request))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    // ========== Bug修复测试 ==========

    @Test
    @DisplayName("getTicketById — 按ticket_no查询 (兼容米宝用ticket_no调用detail)")
    void getTicketById_ByTicketNo() {
        // given: UUID查询返回null, 但ticket_no查询找到记录
        when(afterSalesTicketMapper.selectById("AS-20260704-0001")).thenReturn(null);
        when(afterSalesTicketMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testTicket);
        when(orderMapper.selectById(anyString())).thenReturn(testOrder);

        // when
        AfterSalesDetailResponse result = afterSalesTicketService.getTicketById("AS-20260704-0001");

        // then: 应通过ticket_no成功找到工单
        assertThat(result).isNotNull();
        assertThat(result.getTicketNo()).isEqualTo("AS-20250425-0001");
        verify(afterSalesTicketMapper).selectById("AS-20260704-0001");
        verify(afterSalesTicketMapper).selectOne(any(LambdaQueryWrapper.class));
    }

    @Test
    @DisplayName("updateTicketStatus — 保存remark到internalNotes")
    void updateTicketStatus_SavesInternalNotes() {
        // given
        when(afterSalesTicketMapper.selectById("ticket-test-001")).thenReturn(testTicket);

        AfterSalesStatusUpdateRequest request = new AfterSalesStatusUpdateRequest();
        request.setStatus("processing");
        request.setRemark("已分配给客服张三处理");

        // when
        afterSalesTicketService.updateTicketStatus("ticket-test-001", request);

        // then: internalNotes应包含 time/status/remark（追加格式），状态用中文业务术语（面向企业客户）
        assertThat(testTicket.getInternalNotes()).contains("已分配给客服张三处理");
        assertThat(testTicket.getInternalNotes()).contains("待处理 → 处理中");
        assertThat(testTicket.getInternalNotes()).doesNotContain("pending → processing");
        assertThat(testTicket.getStatus()).isEqualTo("processing");
        verify(afterSalesTicketMapper).updateById(testTicket);
        // 验证timeline被写入
        verify(ticketTimelineMapper).insert(any(TicketTimeline.class));
    }

    @Test
    @DisplayName("updateTicketStatus — pending→processing时timeline记录from/to")
    void updateTicketStatus_WritesTimelineOnStatusChange() {
        // given
        when(afterSalesTicketMapper.selectById("ticket-test-001")).thenReturn(testTicket);

        AfterSalesStatusUpdateRequest request = new AfterSalesStatusUpdateRequest();
        request.setStatus("processing");
        request.setRemark("开始处理");

        // when
        afterSalesTicketService.updateTicketStatus("ticket-test-001", request);

        // then: timeline应包含 from=pending, to=processing, remark
        verify(ticketTimelineMapper).insert(org.mockito.ArgumentMatchers.<TicketTimeline>any());
    }

    // ======================== 售后完结联动订单 + 财务 ========================

    @Test
    @DisplayName("updateTicketStatus — refund 工单 resolved 联动订单退款 + 财务流水")
    void updateTicketStatus_ResolvedRefundTicket_linksOrderAndFinance() {
        // given: processing → resolved 的 refund 工单，退款金额 300
        AfterSalesTicket processingTicket = AfterSalesTicket.builder()
                .id("ticket-r1")
                .tenantId(1L)
                .ticketNo("AS-REFUND-001")
                .orderId("order-001")
                .ticketType("refund")
                .status("processing")
                .refundAmount(new BigDecimal("300.00"))
                .build();

        AfterSalesStatusUpdateRequest request = new AfterSalesStatusUpdateRequest();
        request.setStatus("resolved");

        when(afterSalesTicketMapper.selectById("ticket-r1")).thenReturn(processingTicket);
        when(afterSalesTicketMapper.updateById(any(AfterSalesTicket.class))).thenReturn(1);
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.updateById(any(Order.class))).thenReturn(1);

        // when
        afterSalesTicketService.updateTicketStatus("ticket-r1", request);

        // then: 订单累加 refundAmount、置 refundAt，并登记退款流水
        verify(orderMapper).updateById(argThat((Order o) ->
                o.getRefundAmount() != null
                        && o.getRefundAmount().compareTo(new BigDecimal("300.00")) == 0
                        && o.getRefundAt() != null));
        verify(financeService).recordRefund(argThat((Order o) -> "order-001".equals(o.getId())),
                argThat(amt -> amt != null && amt.compareTo(new BigDecimal("300.00")) == 0),
                org.mockito.ArgumentMatchers.contains("AS-REFUND-001"));
    }

    @Test
    @DisplayName("updateTicketStatus — return 工单 resolved 同样联动退款")
    void updateTicketStatus_ResolvedReturnTicket_linksOrderAndFinance() {
        // given
        AfterSalesTicket processingTicket = AfterSalesTicket.builder()
                .id("ticket-r2")
                .tenantId(1L)
                .ticketNo("AS-RETURN-001")
                .orderId("order-001")
                .ticketType("return")
                .status("processing")
                .refundAmount(new BigDecimal("200.00"))
                .build();

        AfterSalesStatusUpdateRequest request = new AfterSalesStatusUpdateRequest();
        request.setStatus("resolved");

        when(afterSalesTicketMapper.selectById("ticket-r2")).thenReturn(processingTicket);
        when(afterSalesTicketMapper.updateById(any(AfterSalesTicket.class))).thenReturn(1);
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.updateById(any(Order.class))).thenReturn(1);

        // when
        afterSalesTicketService.updateTicketStatus("ticket-r2", request);

        // then
        verify(orderMapper).updateById(argThat((Order o) ->
                o.getRefundAmount().compareTo(new BigDecimal("200.00")) == 0));
        verify(financeService).recordRefund(any(Order.class),
                argThat(amt -> amt.compareTo(new BigDecimal("200.00")) == 0), anyString());
    }

    @Test
    @DisplayName("updateTicketStatus — 非退款类工单（repair）resolved 不联动")
    void updateTicketStatus_ResolvedNonRefundType_noLinkage() {
        // given
        AfterSalesTicket processingTicket = AfterSalesTicket.builder()
                .id("ticket-r3")
                .tenantId(1L)
                .ticketNo("AS-REPAIR-001")
                .orderId("order-001")
                .ticketType("repair")
                .status("processing")
                .refundAmount(new BigDecimal("200.00"))
                .build();

        AfterSalesStatusUpdateRequest request = new AfterSalesStatusUpdateRequest();
        request.setStatus("resolved");

        when(afterSalesTicketMapper.selectById("ticket-r3")).thenReturn(processingTicket);
        when(afterSalesTicketMapper.updateById(any(AfterSalesTicket.class))).thenReturn(1);

        // when
        afterSalesTicketService.updateTicketStatus("ticket-r3", request);

        // then: 不联动订单、不写退款流水
        verify(orderMapper, never()).updateById(any(Order.class));
        verify(financeService, never()).recordRefund(any(Order.class), any(), anyString());
    }

    @Test
    @DisplayName("updateTicketStatus — refundAmount 为 0 的 refund 工单 resolved 不联动")
    void updateTicketStatus_ResolvedZeroRefundAmount_noLinkage() {
        // given
        AfterSalesTicket processingTicket = AfterSalesTicket.builder()
                .id("ticket-r4")
                .tenantId(1L)
                .ticketNo("AS-ZERO-001")
                .orderId("order-001")
                .ticketType("refund")
                .status("processing")
                .refundAmount(BigDecimal.ZERO)
                .build();

        AfterSalesStatusUpdateRequest request = new AfterSalesStatusUpdateRequest();
        request.setStatus("resolved");

        when(afterSalesTicketMapper.selectById("ticket-r4")).thenReturn(processingTicket);
        when(afterSalesTicketMapper.updateById(any(AfterSalesTicket.class))).thenReturn(1);

        // when
        afterSalesTicketService.updateTicketStatus("ticket-r4", request);

        // then
        verify(orderMapper, never()).updateById(any(Order.class));
        verify(financeService, never()).recordRefund(any(Order.class), any(), anyString());
    }

    @Test
    @DisplayName("updateTicketStatus — 已全额退款的订单，resolved 不再重复累计")
    void updateTicketStatus_Resolved_refundCappedAtActualAmount() {
        // given: 订单已退 950，工单再退 200 → 累计封顶 999
        testOrder.setRefundAmount(new BigDecimal("950.00"));
        AfterSalesTicket processingTicket = AfterSalesTicket.builder()
                .id("ticket-r5")
                .tenantId(1L)
                .ticketNo("AS-CAP-001")
                .orderId("order-001")
                .ticketType("refund")
                .status("processing")
                .refundAmount(new BigDecimal("200.00"))
                .build();

        AfterSalesStatusUpdateRequest request = new AfterSalesStatusUpdateRequest();
        request.setStatus("resolved");

        when(afterSalesTicketMapper.selectById("ticket-r5")).thenReturn(processingTicket);
        when(afterSalesTicketMapper.updateById(any(AfterSalesTicket.class))).thenReturn(1);
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.updateById(any(Order.class))).thenReturn(1);

        // when
        afterSalesTicketService.updateTicketStatus("ticket-r5", request);

        // then: 只补足到实收款 999，流水金额 = 49
        verify(orderMapper).updateById(argThat((Order o) ->
                o.getRefundAmount().compareTo(new BigDecimal("999.00")) == 0));
        verify(financeService).recordRefund(any(Order.class),
                argThat(amt -> amt.compareTo(new BigDecimal("49.00")) == 0), anyString());
    }

    // ======================== 创建工单状态门禁 + 退款金额校验 ========================

    private AfterSalesCreateRequest buildCreateRequest(String ticketType, BigDecimal refundAmount) {
        AfterSalesCreateRequest request = new AfterSalesCreateRequest();
        request.setOrderId("order-001");
        request.setTicketType(ticketType);
        request.setDescription("测试描述");
        request.setRefundAmount(refundAmount);
        return request;
    }

    @Test
    @DisplayName("创建工单 - pending 订单不允许建退款/退货工单")
    void createTicket_rejectsPendingOrderForRefundType() {
        // given
        testOrder.setStatus("pending");
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);

        // when & then
        assertThatThrownBy(() -> afterSalesTicketService.createTicket(
                buildCreateRequest("refund", new BigDecimal("100.00")), 1L, "test-user"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不允许创建退款/退货工单");
    }

    @Test
    @DisplayName("创建工单 - cancelled 订单不允许建退款/退货工单")
    void createTicket_rejectsCancelledOrderForRefundType() {
        // given
        testOrder.setStatus("cancelled");
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);

        // when & then
        assertThatThrownBy(() -> afterSalesTicketService.createTicket(
                buildCreateRequest("return", new BigDecimal("100.00")), 1L, "test-user"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不允许创建退款/退货工单");
    }

    @Test
    @DisplayName("创建工单 - completed 订单允许建退款工单")
    void createTicket_acceptsCompletedOrderForRefundType() {
        // given
        testOrder.setStatus("completed");
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(afterSalesTicketMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
        when(afterSalesTicketMapper.insert(any(AfterSalesTicket.class))).thenAnswer(inv -> {
            AfterSalesTicket t = inv.getArgument(0);
            t.setId("ticket-completed");
            return 1;
        });
        when(afterSalesTicketMapper.selectById("ticket-completed")).thenReturn(
                AfterSalesTicket.builder().id("ticket-completed").tenantId(1L)
                        .ticketNo("AS-TEST").orderId("order-001").customerId("张三")
                        .ticketType("refund").status("pending").description("测试")
                        .priority("normal").source("agent").refundAmount(new BigDecimal("100.00"))
                        .createdAt(OffsetDateTime.now()).updatedAt(OffsetDateTime.now()).build());
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);

        // when & then: 不抛异常
        AfterSalesDetailResponse result = afterSalesTicketService.createTicket(
                buildCreateRequest("refund", new BigDecimal("100.00")), 1L, "test-user");
        assertThat(result).isNotNull();
    }

    @Test
    @DisplayName("创建工单 - 非退款类工单不受状态门禁限制（pending 可建）")
    void createTicket_acceptsNonRefundTypeOnPendingOrder() {
        // given
        testOrder.setStatus("pending");
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(afterSalesTicketMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
        when(afterSalesTicketMapper.insert(any(AfterSalesTicket.class))).thenAnswer(inv -> {
            AfterSalesTicket t = inv.getArgument(0);
            t.setId("ticket-complaint-pending");
            return 1;
        });
        when(afterSalesTicketMapper.selectById("ticket-complaint-pending")).thenReturn(
                AfterSalesTicket.builder().id("ticket-complaint-pending").tenantId(1L)
                        .ticketNo("AS-TEST").orderId("order-001").customerId("张三")
                        .ticketType("repair").status("pending").description("维修")
                        .priority("normal").source("agent")
                        .createdAt(OffsetDateTime.now()).updatedAt(OffsetDateTime.now()).build());

        // when & then: 不抛异常
        AfterSalesDetailResponse result = afterSalesTicketService.createTicket(
                buildCreateRequest("repair", null), 1L, "test-user");
        assertThat(result).isNotNull();
    }

    @Test
    @DisplayName("创建工单 - 负数退款金额被拒绝")
    void createTicket_rejectsNegativeRefundAmount() {
        // given
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);

        // when & then
        assertThatThrownBy(() -> afterSalesTicketService.createTicket(
                buildCreateRequest("refund", new BigDecimal("-10.00")), 1L, "test-user"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("退款金额");
    }

    @Test
    @DisplayName("创建工单 - 退款金额超过订单实收款被拒绝")
    void createTicket_rejectsRefundAmountExceedingActual() {
        // given: 实收 999，工单退款 1000
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);

        // when & then
        assertThatThrownBy(() -> afterSalesTicketService.createTicket(
                buildCreateRequest("refund", new BigDecimal("1000.00")), 1L, "test-user"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("退款金额");
    }
}