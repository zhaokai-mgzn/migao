package com.migao.admin.service;
// case_ids: PG-001, PG-002, PG-003, PG-004, PG-005, PG-006, PG-007, PG-008, PG-011

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ProcessingOrderResponse;
import com.migao.admin.dto.ProcessingOrderUpdateRequest;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * 加工单服务单元测试（issue #3340）
 * 覆盖：生成（快照五要素 + options + 无销售价）、幂等、状态机、取消联动、租户隔离。
 */
@ExtendWith(MockitoExtension.class)
class ProcessingOrderServiceTest {

    private static final Long TENANT = 1L;

    @InjectMocks
    private ProcessingOrderService processingOrderService;

    @Mock
    private ProcessingOrderMapper processingOrderMapper;

    @Mock
    private OrderMapper orderMapper;

    @Mock
    private OrderItemMapper orderItemMapper;

    @Mock
    private ProcessingItemMapper processingItemMapper;

    @Mock
    private OrderService orderService;

    @Spy
    private ObjectMapper objectMapper = new ObjectMapper();

    private Order confirmedOrder;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, ProcessingOrder.class);

        confirmedOrder = Order.builder()
                .id("order-001")
                .tenantId(TENANT)
                .orderNo("ORD-20260912-0001")
                .status("confirmed")
                .customerName("张三")
                .customerPhone("13800138000")
                .build();
    }

    // ── 快照构建工具 ──────────────────────────────────────────────

    @SuppressWarnings("unchecked")
    private Map<String, Object> processingInfo(String colorName) {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("processingFee", 6.0);
        info.put("colorName", colorName);
        info.put("sellingMethod", "散剪");
        info.put("doorWidth", "2.8米");
        List<Map<String, Object>> procs = new ArrayList<>();
        Map<String, Object> p = new LinkedHashMap<>();
        p.put("id", "p1");
        p.put("name", "打孔");
        p.put("unitPrice", 3.0);
        p.put("quantity", 2);
        p.put("unit", "米");
        procs.add(p);
        info.put("processingItems", procs);
        return info;
    }

    private OrderItem orderItemWithProcessing(String colorName) {
        return OrderItem.builder()
                .id("item-1")
                .tenantId(TENANT)
                .orderId("order-001")
                .productName("布艺遮光帘A")
                .quantity(2)
                .width(new BigDecimal("2.5"))
                .height(new BigDecimal("2.8"))
                .processingInfo(processingInfo(colorName))
                .build();
    }

    private OrderItem orderItemWithoutProcessing() {
        return OrderItem.builder()
                .id("item-2")
                .tenantId(TENANT)
                .orderId("order-001")
                .productName("现货成品")
                .quantity(1)
                .processingInfo(new HashMap<String, Object>())
                .build();
    }

    private ProcessingOrder po(String id, String status) {
        return ProcessingOrder.builder()
                .id(id)
                .tenantId(TENANT)
                .orderId("order-001")
                .processingOrderNo("JG-20260912-0001")
                .status(status)
                .itemsSnapshot(buildSnapshotPayload())
                .build();
    }

    private List<Map<String, Object>> buildSnapshotPayload() {
        List<Map<String, Object>> snapshot = new ArrayList<>();
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("productName", "布艺遮光帘A");
        entry.put("quantity", 2);
        entry.put("colorName", "米白");
        List<Map<String, Object>> procs = new ArrayList<>();
        Map<String, Object> p = new LinkedHashMap<>();
        p.put("id", "p1");
        p.put("name", "打孔");
        procs.add(p);
        entry.put("processingItems", procs);
        snapshot.add(entry);
        return snapshot;
    }

    // ── PG-001 生成成功 ────────────────────────────────────────────

    @Test
    @DisplayName("PG-001 已确认含加工项订单 → 生成加工单 + 订单联动 producing")
    void generateSuccess() {
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectByOrderId("order-001", TENANT))
                .thenReturn(List.of(orderItemWithProcessing("米白")));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);
        ProcessingItem pi = ProcessingItem.builder().id("p1").name("打孔").unit("米").options(List.of("四爪钩")).build();
        when(processingItemMapper.selectById("p1")).thenReturn(pi);
        when(processingOrderMapper.insert(any(ProcessingOrder.class))).thenReturn(1);

        var results = processingOrderService.generate(List.of("order-001"), TENANT, "u1");

        assertThat(results).hasSize(1);
        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(results.get(0).getProcessingOrderNo()).startsWith("JG-");

        ArgumentCaptor<ProcessingOrder> captor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper).insert(captor.capture());
        ProcessingOrder inserted = captor.getValue();
        assertThat(inserted.getStatus()).isEqualTo("generated");
        assertThat(inserted.getTenantId()).isEqualTo(TENANT);
        assertThat(inserted.getOrderId()).isEqualTo("order-001");
        assertThat(inserted.getTemplateVersion()).isEqualTo(1);

        // 快照五要素 + options + 无销售价
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> snapshot = (List<Map<String, Object>>) inserted.getItemsSnapshot();
        assertThat(snapshot).hasSize(1);
        Map<String, Object> entry = snapshot.get(0);
        assertThat(entry.get("productName")).isEqualTo("布艺遮光帘A");
        assertThat(entry.get("colorName")).isEqualTo("米白");
        assertThat(entry.get("sellingMethod")).isEqualTo("散剪");
        assertThat(entry.get("doorWidth")).isEqualTo("2.8米");
        assertThat(entry).doesNotContainKey("price");
        assertThat(entry).doesNotContainKey("salesPrice");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> procs = (List<Map<String, Object>>) entry.get("processingItems");
        assertThat(procs).hasSize(1);
        assertThat(procs.get(0).get("options")).isEqualTo(List.of("四爪钩"));

        // 联动：订单 confirmed → producing
        verify(orderService).updateOrderStatus("order-001", "producing");
    }

    // ── PG-002 幂等 ────────────────────────────────────────────────

    @Test
    @DisplayName("PG-002 已有活跃加工单 → 重复生成拒绝")
    void generateDuplicateRejected() {
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectByOrderId("order-001", TENANT))
                .thenReturn(List.of(orderItemWithProcessing("米白")));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT))
                .thenReturn(po("po-1", "generated"));

        var results = processingOrderService.generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isFalse();
        assertThat(results.get(0).getMessage()).contains("已有加工单");
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
        verify(orderService, never()).updateOrderStatus(anyString(), anyString());
    }

    // ── PG-003 无加工项 ────────────────────────────────────────────

    @Test
    @DisplayName("PG-003 无加工项订单 → 拒绝生成")
    void generateWithoutProcessingRejected() {
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectByOrderId("order-001", TENANT))
                .thenReturn(List.of(orderItemWithoutProcessing()));

        var results = processingOrderService.generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isFalse();
        assertThat(results.get(0).getMessage()).contains("无加工项");
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
    }

    // ── PG-004 未确认订单 ──────────────────────────────────────────

    @Test
    @DisplayName("PG-004 pending 订单 → 拒绝生成")
    void generatePendingOrderRejected() {
        Order pending = Order.builder()
                .id("order-pending").tenantId(TENANT).orderNo("ORD-P")
                .status("pending").build();
        when(orderMapper.selectById("order-pending")).thenReturn(pending);

        var results = processingOrderService.generate(List.of("order-pending"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isFalse();
        assertThat(results.get(0).getMessage()).contains("不允许生成加工单");
    }

    @Test
    @DisplayName("订单号解析：selectById 未命中时按订单号查询")
    void generateResolveByOrderNo() {
        when(orderMapper.selectById("ORD-20260912-0001")).thenReturn(null);
        when(orderMapper.selectOne(any())).thenReturn(confirmedOrder);
        when(orderItemMapper.selectByOrderId("order-001", TENANT))
                .thenReturn(List.of(orderItemWithProcessing("米白")));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);
        when(processingOrderMapper.insert(any(ProcessingOrder.class))).thenReturn(1);

        var results = processingOrderService.generate(List.of("ORD-20260912-0001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        verify(orderService).updateOrderStatus("order-001", "producing");
    }

    // ── PG-005/006 状态机 ──────────────────────────────────────────

    @Test
    @DisplayName("PG-005 issue/start/complete 主链流转")
    void updateStatusMainChain() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "generated"));
        when(processingOrderMapper.updateById(any(ProcessingOrder.class))).thenReturn(1);
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);

        ProcessingOrderUpdateRequest issue = new ProcessingOrderUpdateRequest();
        issue.setAction("issue");
        issue.setProcessor("朝阳加工厂");
        issue.setExpectedDeliveryDate(LocalDate.of(2026, 9, 20));
        processingOrderService.updateStatus("po-1", issue, TENANT, "u1");

        ArgumentCaptor<ProcessingOrder> captor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper).updateById(captor.capture());
        assertThat(captor.getValue().getStatus()).isEqualTo("issued");
        assertThat(captor.getValue().getProcessor()).isEqualTo("朝阳加工厂");
        assertThat(captor.getValue().getExpectedDeliveryDate()).isEqualTo(LocalDate.of(2026, 9, 20));
        assertThat(captor.getValue().getIssuedAt()).isNotNull();

        // start
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "issued"));
        ProcessingOrderUpdateRequest start = new ProcessingOrderUpdateRequest();
        start.setAction("start");
        processingOrderService.updateStatus("po-1", start, TENANT, "u1");
        verify(processingOrderMapper, times(2)).updateById(captor.capture());
        assertThat(captor.getValue().getStatus()).isEqualTo("in_processing");
        assertThat(captor.getValue().getInProcessingAt()).isNotNull();

        // complete：订单保持 producing（不自动 shipped）
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "in_processing"));
        ProcessingOrderUpdateRequest complete = new ProcessingOrderUpdateRequest();
        complete.setAction("complete");
        processingOrderService.updateStatus("po-1", complete, TENANT, "u1");
        verify(processingOrderMapper, times(3)).updateById(captor.capture());
        assertThat(captor.getValue().getStatus()).isEqualTo("completed");
        verify(orderService, never()).updateOrderStatus(eq("order-001"), eq("shipped"));
    }

    @Test
    @DisplayName("PG-006 非法流转拒绝（generated→completed）")
    void updateStatusIllegalTransitionRejected() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "generated"));

        ProcessingOrderUpdateRequest complete = new ProcessingOrderUpdateRequest();
        complete.setAction("complete");

        assertThatThrownBy(() -> processingOrderService.updateStatus("po-1", complete, TENANT, "u1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不允许从");
        verify(processingOrderMapper, never()).updateById(any(ProcessingOrder.class));
    }

    // ── PG-007/008 取消 ────────────────────────────────────────────

    @Test
    @DisplayName("PG-007 取消（generated）→ 加工单 cancelled + 订单 producing→confirmed 回退")
    void cancelGeneratedRevertsOrder() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "generated"));
        when(processingOrderMapper.updateById(any(ProcessingOrder.class))).thenReturn(1);
        Order producing = Order.builder().id("order-001").tenantId(TENANT).status("producing").build();
        when(orderMapper.selectById("order-001")).thenReturn(producing);

        ProcessingOrderUpdateRequest cancel = new ProcessingOrderUpdateRequest();
        cancel.setAction("cancel");
        cancel.setReason("加工方排期冲突");
        processingOrderService.updateStatus("po-1", cancel, TENANT, "u1");

        ArgumentCaptor<ProcessingOrder> captor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper).updateById(captor.capture());
        assertThat(captor.getValue().getStatus()).isEqualTo("cancelled");
        assertThat(captor.getValue().getCancelledReason()).isEqualTo("加工方排期冲突");
        verify(orderService).revertProducingToConfirmed(eq("order-001"), anyString());
    }

    @Test
    @DisplayName("PG-008 取消必填原因")
    void cancelRequiresReason() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "generated"));

        ProcessingOrderUpdateRequest cancel = new ProcessingOrderUpdateRequest();
        cancel.setAction("cancel");

        assertThatThrownBy(() -> processingOrderService.updateStatus("po-1", cancel, TENANT, "u1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("必须填写原因");
    }

    @Test
    @DisplayName("completed 冻结：取消被拒")
    void cancelCompletedFrozen() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "completed"));

        ProcessingOrderUpdateRequest cancel = new ProcessingOrderUpdateRequest();
        cancel.setAction("cancel");
        cancel.setReason("测试");

        assertThatThrownBy(() -> processingOrderService.updateStatus("po-1", cancel, TENANT, "u1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不允许从");
    }

    // ── PG-011 租户隔离 ────────────────────────────────────────────

    @Test
    @DisplayName("PG-011 跨租户加工单解析 → notFound")
    void tenantIsolation() {
        // 其它租户数据：resolve 条件带 tenant_id，selectOne 返回 null → notFound
        when(processingOrderMapper.selectOne(any())).thenReturn(null);

        ProcessingOrderUpdateRequest issue = new ProcessingOrderUpdateRequest();
        issue.setAction("issue");

        assertThatThrownBy(() -> processingOrderService.updateStatus("JG-OTHER-0001", issue, TENANT, "u1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("加工单");
    }

    // ── 查询 ───────────────────────────────────────────────────────

    @Test
    @DisplayName("详情返回：快照解析 + 订单信息回填")
    void detailAssemblesResponse() {
        ProcessingOrder po = po("po-1", "issued");
        po.setProcessor("朝阳加工厂");
        when(processingOrderMapper.selectOne(any())).thenReturn(po);
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);

        ProcessingOrderResponse resp = processingOrderService.getDetail("po-1", TENANT);

        assertThat(resp.getOrderNo()).isEqualTo("ORD-20260912-0001");
        assertThat(resp.getCustomerName()).isEqualTo("张三");
        assertThat(resp.getStatus()).isEqualTo("issued");
        assertThat(resp.getItems()).hasSize(1);
        assertThat(resp.getItems().get(0).getProductName()).isEqualTo("布艺遮光帘A");
        assertThat(resp.getItems().get(0).getColorName()).isEqualTo("米白");
        assertThat(resp.getItems().get(0).getProcessingItems()).hasSize(1);
    }

    // ── 验收复核修复（PR #3345）：生成竞态/并发重复 ──────────────────

    @Test
    @DisplayName("复核修复 P2①：并发重复生成（DuplicateKeyException）→ 订单状态回退 + 幂等失败结果")
    void generateConcurrentDuplicateRollsBackOrder() {
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectByOrderId("order-001", TENANT))
                .thenReturn(List.of(orderItemWithProcessing("米白")));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);
        when(processingOrderMapper.insert(any(ProcessingOrder.class)))
                .thenThrow(new org.springframework.dao.DuplicateKeyException("uk_processing_orders_active"));

        var results = processingOrderService.generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isFalse();
        assertThat(results.get(0).getMessage()).contains("已生成");
        // 联动先发生、落库失败 → 订单回退 confirmed（无孤儿态）
        verify(orderService).updateOrderStatus("order-001", "producing");
        verify(orderService).revertProducingToConfirmed(eq("order-001"), anyString());
    }

    @Test
    @DisplayName("复核修复 P2②：落库失败（非重复）→ 状态回退 + 异常传播（整批回滚）")
    void generateInsertFailureRollsBackAndPropagates() {
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectByOrderId("order-001", TENANT))
                .thenReturn(List.of(orderItemWithProcessing("米白")));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);
        when(processingOrderMapper.insert(any(ProcessingOrder.class)))
                .thenThrow(new RuntimeException("db down"));

        assertThatThrownBy(() -> processingOrderService.generate(List.of("order-001"), TENANT, "u1"))
                .isInstanceOf(RuntimeException.class);
        verify(orderService).revertProducingToConfirmed(eq("order-001"), anyString());
    }
}
