// case_ids: PG-021
package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProductionPieceworkSettlement;
import com.migao.admin.entity.ProductionPieceworkSettlementLine;
import com.migao.admin.entity.ProductionWorkLog;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductionPieceworkSettlementLineMapper;
import com.migao.admin.mapper.ProductionPieceworkSettlementMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 计件工资**结算**测试（issue #4483 = 母单 #4347 §二.4；真值源 §4）。
 *
 * <p>本类锁四件事（每条都有独立红证）：</p>
 * <ol>
 *   <li><b>结算单是金额快照 + 逐笔明细</b>（真值源 §4「逐笔可追溯」）——
 *       明细合计必须 === 结算单金额；</li>
 *   <li><b>生成幂等</b>：同人同期已存在活跃结算单 ⇒ 跳过（同一笔钱不得结算两次）；</li>
 *   <li><b>确认即锁定</b>：{@code draft → settled} 一步（**不加审批环节**，用户裁定）；
 *       重复确认 ⇒ 422；</li>
 *   <li><b>锁定后报工被拒</b>：该期该人的报工不得再改（补报走调整单，不回改历史）——
 *       与「快照冻结、不回算历史工资」（V61 / #4351）同源。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("PieceworkSettlementService 计件工资结算（#4483）")
class PieceworkSettlementServiceTest {

    private static final Long TENANT = 1L;
    private static final String PERIOD = "2026-09";

    @Mock
    private ProductionPieceworkSettlementMapper settlementMapper;
    @Mock
    private ProductionPieceworkSettlementLineMapper lineMapper;
    @Mock
    private ProductionWorkLogMapper workLogMapper;
    @Mock
    private ProductionService productionService;

    private PieceworkSettlementService service;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        service = new PieceworkSettlementService(settlementMapper, lineMapper, workLogMapper, productionService);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    private ProductionWorkLog log(String id, String workerName, String qty, String unitPrice, String factor) {
        return ProductionWorkLog.builder()
                .id(id).tenantId(TENANT).processingOrderId("po-1").operationId("op-" + id)
                .operationName("精裁-布").workerId("w-1").workerName(workerName)
                .qty(new BigDecimal(qty)).qualifiedQty(new BigDecimal(qty))
                .unitPrice(new BigDecimal(unitPrice)).factor(new BigDecimal(factor))
                .workType("normal").workDate(LocalDate.of(2026, 9, 18)).deleted(0)
                .build();
    }

    private ProcessingPositionOperation op(String id, String unitPrice) {
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId("po-1")
                .positionName("布帘").orderItemId("item-A").operationName("精裁-布").unit("米")
                .qty(new BigDecimal("10")).unitPrice(new BigDecimal(unitPrice)).factor(BigDecimal.ONE)
                .deleted(0).build();
    }

    @Test
    @DisplayName("生成结算单：金额 = Σ逐笔，且**逐笔明细**合计 === 结算单金额（真值源 §4 逐笔可追溯）")
    void generateCreatesSnapshotWithTraceableLines() {
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                log("w1", "蒋雪云", "10", "0.40", "1.00"),
                log("w2", "蒋雪云", "4", "0.40", "1.70")));
        when(productionService.listActiveOperations(TENANT)).thenReturn(new ArrayList<>());
        when(settlementMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> result = service.generate(PERIOD, TENANT);

        assertThat(result.get("period")).isEqualTo(PERIOD);
        assertThat(result.get("generated")).isEqualTo(1);
        // 10×0.40×1.00 + 4×0.40×1.70 = 4.00 + 2.72 = 6.72
        ArgumentCaptor<ProductionPieceworkSettlement> captor =
                ArgumentCaptor.forClass(ProductionPieceworkSettlement.class);
        verify(settlementMapper).insert(captor.capture());
        ProductionPieceworkSettlement saved = captor.getValue();
        assertThat(saved.getAmount()).isEqualByComparingTo("6.72");
        assertThat(saved.getWorkerName()).isEqualTo("蒋雪云");
        assertThat(saved.getStatus()).isEqualTo("draft");
        assertThat(saved.getLineCount()).isEqualTo(2);

        // 逐笔明细：两行，且合计 === 结算单金额
        ArgumentCaptor<ProductionPieceworkSettlementLine> lineCaptor =
                ArgumentCaptor.forClass(ProductionPieceworkSettlementLine.class);
        verify(lineMapper, org.mockito.Mockito.times(2)).insert(lineCaptor.capture());
        BigDecimal lineSum = lineCaptor.getAllValues().stream()
                .map(ProductionPieceworkSettlementLine::getAmount)
                .reduce(BigDecimal.ZERO, BigDecimal::add);
        assertThat(lineSum)
                .as("逐笔明细合计必须 === 结算单金额（否则「逐笔可追溯」不成立）")
                .isEqualByComparingTo(saved.getAmount());
    }

    @Test
    @DisplayName("生成幂等：同人同期已有活跃结算单 ⇒ 跳过（同一笔钱不得结算两次）")
    void generateSkipsExistingSettlement() {
        when(workLogMapper.selectList(any())).thenReturn(List.of(log("w1", "蒋雪云", "10", "0.40", "1.00")));
        when(productionService.listActiveOperations(TENANT)).thenReturn(new ArrayList<>());
        when(settlementMapper.selectList(any())).thenReturn(List.of(
                ProductionPieceworkSettlement.builder()
                        .id("s-1").tenantId(TENANT).period(PERIOD).workerKey("w-1")
                        .workerName("蒋雪云").amount(new BigDecimal("4.00")).status("draft").deleted(0)
                        .build()));

        Map<String, Object> result = service.generate(PERIOD, TENANT);

        assertThat(result.get("generated")).isEqualTo(0);
        assertThat(result.get("skipped")).isEqualTo(1);
        verify(settlementMapper, never()).insert(any(ProductionPieceworkSettlement.class));
    }

    @Test
    @DisplayName("确认结算：draft → settled 一步（不加审批），落 settled_at / settled_by")
    void settleLocksSettlement() {
        when(settlementMapper.selectById("s-1")).thenReturn(
                ProductionPieceworkSettlement.builder()
                        .id("s-1").tenantId(TENANT).period(PERIOD).workerKey("w-1")
                        .workerName("蒋雪云").amount(new BigDecimal("6.72")).status("draft").deleted(0)
                        .build());

        Map<String, Object> result = service.settle("s-1", "财务小王", TENANT);

        assertThat(result.get("status")).isEqualTo("settled");
        ArgumentCaptor<ProductionPieceworkSettlement> captor =
                ArgumentCaptor.forClass(ProductionPieceworkSettlement.class);
        verify(settlementMapper).updateById(captor.capture());
        assertThat(captor.getValue().getStatus()).isEqualTo("settled");
        assertThat(captor.getValue().getSettledAt()).isNotNull();
        assertThat(captor.getValue().getSettledBy()).isEqualTo("财务小王");
    }

    @Test
    @DisplayName("确认红证：已 settled ⇒ 422（不静默重复结算）")
    void settleRejectsAlreadySettled() {
        when(settlementMapper.selectById("s-1")).thenReturn(
                ProductionPieceworkSettlement.builder()
                        .id("s-1").tenantId(TENANT).period(PERIOD).workerKey("w-1")
                        .workerName("蒋雪云").status("settled").deleted(0)
                        .build());

        assertThatThrownBy(() -> service.settle("s-1", "财务小王", TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不能重复结算");
        verify(settlementMapper, never()).updateById(any(ProductionPieceworkSettlement.class));
    }

    @Test
    @DisplayName("🔴 锁定守卫：该期该人已 settled ⇒ 报工被拒，且**指名期次**（工人能行动的信息）")
    void lockedPeriodRejectsReporting() {
        when(settlementMapper.selectList(any())).thenReturn(List.of(
                ProductionPieceworkSettlement.builder()
                        .id("s-1").tenantId(TENANT).period(PERIOD).workerKey("w-1")
                        .workerName("蒋雪云").status("settled").deleted(0)
                        .build()));

        assertThatThrownBy(() -> PieceworkSettlementService.assertPeriodNotLocked(
                settlementMapper, TENANT, LocalDate.of(2026, 9, 18), "w-1", "蒋雪云"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("已结算并锁定")
                .hasMessageContaining(PERIOD)
                .hasMessageContaining("蒋雪云");
    }

    @Test
    @DisplayName("锁定守卫反向：draft（未确认）**不**锁 —— 确认前仍可补报")
    void draftDoesNotLockReporting() {
        when(settlementMapper.selectList(any())).thenReturn(List.of(
                ProductionPieceworkSettlement.builder()
                        .id("s-1").tenantId(TENANT).period(PERIOD).workerKey("w-1")
                        .workerName("蒋雪云").status("draft").deleted(0)
                        .build()));

        // 不抛 = 放行
        PieceworkSettlementService.assertPeriodNotLocked(
                settlementMapper, TENANT, LocalDate.of(2026, 9, 18), "w-1", "蒋雪云");
    }

    @Test
    @DisplayName("锁定守卫：无结算单 / workDate 为空 ⇒ 放行（不误伤）")
    void noSettlementMeansNoLock() {
        when(settlementMapper.selectList(any())).thenReturn(List.of());
        PieceworkSettlementService.assertPeriodNotLocked(
                settlementMapper, TENANT, LocalDate.of(2026, 9, 18), "w-1", "蒋雪云");
        // workDate 为空 ⇒ 直接返回（不查库）
        PieceworkSettlementService.assertPeriodNotLocked(settlementMapper, TENANT, null, "w-1", "蒋雪云");
    }
}
