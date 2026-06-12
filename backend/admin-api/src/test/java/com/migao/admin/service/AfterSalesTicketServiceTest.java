package com.migao.admin.service;

import com.migao.admin.dto.*;
import com.migao.admin.entity.AfterSalesTicket;
import com.migao.admin.entity.Order;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.AfterSalesTicketMapper;
import com.migao.admin.mapper.OrderMapper;
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
    private ObjectMapper objectMapper;

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
                .status("delivered")
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
        AfterSalesDetailResponse result = afterSalesTicketService.createTicket(request, 1L);

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
        assertThatThrownBy(() -> afterSalesTicketService.createTicket(request, 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessage("关联订单不存在");
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
    @DisplayName("更新工单状态失败 - 非法状态流转 pending -> resolved")
    void updateTicketStatus_InvalidTransition() {
        // given
        AfterSalesStatusUpdateRequest request = new AfterSalesStatusUpdateRequest();
        request.setStatus("resolved");

        when(afterSalesTicketMapper.selectById("ticket-001")).thenReturn(testTicket);

        // when & then
        assertThatThrownBy(() -> afterSalesTicketService.updateTicketStatus("ticket-001", request))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不允许");
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
}
