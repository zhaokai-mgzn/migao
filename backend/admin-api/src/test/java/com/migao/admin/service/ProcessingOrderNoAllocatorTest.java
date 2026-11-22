// case_ids: PG-001, PG-002
package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.time.BusinessClock;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.format.DateTimeFormatter;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 加工单号取号器（集群 P0-5，issue #9021）—— <b>直接</b>判 {@link ProcessingOrderNoAllocator}：
 * 换候选重试、耗尽文案、活跃单分诊、起点来自库内最大号。
 *
 * <p>服务层的接线（订单联动 / 失败回退 / 并发两线程建单）在
 * {@code ProcessingOrderServiceTest}；真库 SQL 形态（{@code ON CONFLICT DO NOTHING} / JSONB /
 * 部分唯一索引）在 {@code ProcessingOrderNoConflictRealDbTest}。本类只钉「取号器自己」的行为，
 * 不依赖 {@code ProcessingOrderService} 的整条装配。</p>
 */
@ExtendWith(MockitoExtension.class)
class ProcessingOrderNoAllocatorTest {

    private static final Long TENANT = 1L;
    private static final String ORDER_ID = "order-001";

    @Mock
    private ProcessingOrderMapper processingOrderMapper;

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final BusinessClock businessClock = new BusinessClock();

    @AfterEach
    void resetProbe() {
        ProcessingOrderNoAllocator.setProbeFirstCandidateForTest(null);
    }

    @Test
    @DisplayName("P0-5 取号器①：首个候选被抢 ⇒ 换候选重试，返回的号**确实**被这次调用占用（快照 JSON 同批落库）")
    void retriesWithFreshNoAndClaimsItAtomically() {
        when(processingOrderMapper.selectMaxProcessingOrderNo(anyString())).thenReturn(null);
        String occupied = "JG-20260101-0001";
        // 「库」= 单号唯一索引语义：putIfAbsent 成功 ⇒ 1 行；号已被占 ⇒ 0 行
        Map<String, String> table = new HashMap<>();
        table.put(occupied, "[]");
        when(processingOrderMapper.insertIgnoreProcessingNoConflict(any(ProcessingOrder.class), anyString()))
                .thenAnswer(inv -> {
                    ProcessingOrder candidate = inv.getArgument(0);
                    String snapshotJson = inv.getArgument(1);
                    return table.putIfAbsent(candidate.getProcessingOrderNo(), snapshotJson) == null ? 1 : 0;
                });
        ProcessingOrderNoAllocator.setProbeFirstCandidateForTest(occupied);
        ProcessingOrder po = po();

        ProcessingOrderNoAllocator.insertWithFresh(
                processingOrderMapper, objectMapper, businessClock, order(), po);

        assertThat(po.getProcessingOrderNo())
                .as("撞号必须换号成功（改前：直接失败并谎报「已生成」）")
                .matches("JG-\\d{8}-\\d{4}").isNotEqualTo(occupied);
        assertThat(po.getId()).as("手写 INSERT 不走 ASSIGN_UUID ⇒ 主键必须由取号器先给")
                .hasSize(32);
        assertThat(table).as("新号必须真的被占用（不是只换了内存里的字符串）")
                .containsKey(po.getProcessingOrderNo());
        verify(processingOrderMapper, times(2))
                .insertIgnoreProcessingNoConflict(any(ProcessingOrder.class), anyString());
        ArgumentCaptor<String> snapshotJson = ArgumentCaptor.forClass(String.class);
        verify(processingOrderMapper, times(2))
                .insertIgnoreProcessingNoConflict(any(ProcessingOrder.class), snapshotJson.capture());
        assertThat(snapshotJson.getAllValues()).as("快照以 JSON 文本传给 mapper 的 CAST(… AS jsonb)")
                .containsOnly("[]");
    }

    @Test
    @DisplayName("P0-5 取号器②：连续撞号到上限 ⇒ 409「加工单号生成冲突」+ requestId，绝不报「已生成」")
    void exhaustionReportsActionableConflictNotAlreadyGenerated() {
        when(processingOrderMapper.selectMaxProcessingOrderNo(anyString())).thenReturn(null);
        when(processingOrderMapper.insertIgnoreProcessingNoConflict(any(ProcessingOrder.class), anyString()))
                .thenReturn(0);
        // 回查活跃单：查不到（默认 null）⇒ 是取号冲突，不是「已有单」
        ProcessingOrder po = po();

        assertThatThrownBy(() -> ProcessingOrderNoAllocator.insertWithFresh(
                processingOrderMapper, objectMapper, businessClock, order(), po))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> {
                    BusinessException ex = (BusinessException) thrown;
                    assertThat(ex.getCode()).isEqualTo("PROCESSING_ORDER_NO_CONFLICT");
                    assertThat(ex.getMessage())
                            .contains("加工单号生成冲突").contains("requestId=").doesNotContain("已生成");
                });
        verify(processingOrderMapper, times(ProcessingOrderNoAllocator.ATTEMPTS))
                .insertIgnoreProcessingNoConflict(any(ProcessingOrder.class), anyString());
    }

    @Test
    @DisplayName("P0-5 取号器③：0 行后回查**确实**有活跃单 ⇒ 才报「已生成」并带真实单号（且不再空转重试）")
    void existingActiveOrderIsReportedOnlyAfterVerified() {
        when(processingOrderMapper.selectMaxProcessingOrderNo(anyString())).thenReturn(null);
        when(processingOrderMapper.insertIgnoreProcessingNoConflict(any(ProcessingOrder.class), anyString()))
                .thenReturn(0);
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(
                ProcessingOrder.builder().id("po-existing").processingOrderNo("JG-20260101-0007").build());

        assertThatThrownBy(() -> ProcessingOrderNoAllocator.insertWithFresh(
                processingOrderMapper, objectMapper, businessClock, order(), po()))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("已生成")
                .hasMessageContaining("JG-20260101-0007");
        verify(processingOrderMapper, times(1))
                .insertIgnoreProcessingNoConflict(any(ProcessingOrder.class), anyString());
    }

    @Test
    @DisplayName("P0-5 取号器④：起点 = 库内当日最大号 + 1（不依赖进程内计数器）")
    void startsFromDbMaxNotProcessState() {
        String prefix = "JG-" + businessClock.today().format(DateTimeFormatter.ofPattern("yyyyMMdd")) + "-";
        when(processingOrderMapper.selectMaxProcessingOrderNo(prefix)).thenReturn(prefix + "0041");
        when(processingOrderMapper.insertIgnoreProcessingNoConflict(any(ProcessingOrder.class), anyString()))
                .thenReturn(1);
        ProcessingOrder po = po();

        ProcessingOrderNoAllocator.insertWithFresh(
                processingOrderMapper, objectMapper, businessClock, order(), po);

        assertThat(po.getProcessingOrderNo()).isEqualTo(prefix + "0042");
    }

    private Order order() {
        return Order.builder().id(ORDER_ID).tenantId(TENANT).orderNo("ORD-20260101-0001").build();
    }

    private ProcessingOrder po() {
        return ProcessingOrder.builder()
                .tenantId(TENANT).orderId(ORDER_ID).status("generated")
                .itemsSnapshot(List.of())
                .build();
    }
}
