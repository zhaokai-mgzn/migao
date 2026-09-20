// case_ids: PG-018
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingOrderSet;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProcessingSetPartToken;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingOrderSetMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProcessingSetPartTokenMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 扫码解析 + 工序推断（切片 ①，issue #4698；设计 {@code docs/design/set-code-and-scan-loop.md} §2.3 / §2.6 / §3）。
 *
 * <p><b>本测试是行为断言，不是桩断言</b>：{@link ProductionService} 用**真实对象**（只 mock Mapper）
 * —— 四形态订单解析 / {@code isDone} / {@code progressOf} 必须走**同一份**实现，
 * mock 掉它们等于把被测口径换成桩（「绿了但没跑」）。</p>
 *
 * <p><b>红证（改前实测，见 PR body）</b>：① 新码解析不出 (套, 部位)；② 旧码不降级 / 默认取第 1 套；
 * ③ 推断找不到下一道 / 套级不回落；④ 工序未确定却放行。每条都由下面某个测试**反向钉住**
 * （删断言或注入缺陷 ⇒ 必红）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("ProductionScanService 扫码解析 + 工序推断（切片 ①）")
class ProductionScanServiceTest {

    private static final Long TENANT = 1L;
    private static final String ORDER_ID = "order-1";
    private static final String PO_ID = "po-1";
    private static final String PO_NO = "CSO260915-02615";
    private static final String SET_ID = "set-14";
    private static final String SET_NO = PO_NO + "-014";
    private static final String FIRST_SET_ID = "set-1";
    private static final String FIRST_SET_NO = PO_NO + "-001";
    private static final String ITEM_CLOTH = "oi-cloth";
    private static final String ITEM_GAUZE = "oi-gauze";
    /**
     * 码夹具值（新码 / 旧码）。
     *
     * <p>⚠️ 刻意用**非密钥形态**的字面量：32 位 hex 会被 CI 的 gitleaks `generic-api-key` 规则
     * 误判为密钥（实测本单首轮 CI 因此判红）。码**格式**（32 位 UUID 去横线）的判据在迁移/打印侧，
     * 不在本测试；这里只需两个互不相等的可辨识值。</p>
     */
    private static final String NEW_CODE = "new-scan-code-4698";
    private static final String OLD_CODE = "legacy-scan-code-4698";

    @Mock
    private ProcessingSetPartTokenMapper setPartTokenMapper;
    @Mock
    private ProcessingOrderSetMapper orderSetMapper;
    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private ProcessingPositionOperationMapper positionOperationMapper;
    @Mock
    private OrderMapper orderMapper;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private ProductionOperationQueryService operationQueryService;
    @Mock
    private ProductionWorkLogMapper workLogMapper;
    @Mock
    private ClientRequestIdService clientRequestIdService;

    private ProductionService productionService;
    private ProductionScanService service;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        productionService = new ProductionService(processingOrderMapper, positionOperationMapper,
                workLogMapper, orderMapper, orderItemMapper, clientRequestIdService);
        service = new ProductionScanService(setPartTokenMapper, orderSetMapper, processingOrderMapper,
                positionOperationMapper, orderItemMapper, operationQueryService, productionService,
                // 卡点判据（切片 ③，issue #4776）：真实对象（只 mock Mapper）——
                // stalled 键的口径必须走**同一份**实现，mock 掉它等于把被测口径换成桩。
                new ProductionStuckPointService(productionService, positionOperationMapper,
                        orderSetMapper, 4.0));
        when(operationQueryService.operationsByName(TENANT)).thenReturn(catalog());
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ============================================================ ① 新码：套 × 部位

    @Test
    @DisplayName("新 token ⇒ 解析出 (套, 部位) + 推断下一道待做工序，部位不选、零额外交互")
    void newTokenResolvesSetPositionAndInfersNextOperation() {
        stubNewTokenScan(ITEM_CLOTH, standardOps());

        Map<String, Object> result = service.resolve(NEW_CODE, null, TENANT);

        assertThat(result.get("granularity")).isEqualTo("set_position");
        assertThat(result.get("set_no")).isEqualTo(SET_NO);
        assertThat(result.get("set_index")).isEqualTo(14);
        assertThat(result.get("processing_order_no")).isEqualTo(PO_NO);
        // 部位**由码给出**：响应里带部位，且不需要任何选择
        assertThat(position(result).get("order_item_id")).isEqualTo(ITEM_CLOTH);
        assertThat(position(result).get("position_kind")).isEqualTo("布帘");
        assertThat(result.get("needs_selection")).isEqualTo(List.of());
        // 推断 = 部位内 seq 最小的**未完成**者（seq1 已做完 ⇒ 不该被选）
        Map<String, Object> operation = operation(result);
        assertThat(operation.get("operation_id")).isEqualTo("op-2");
        assertThat(operation.get("determined_by")).isEqualTo("inferred");
        assertThat(operation.get("rerouted")).isEqualTo(false);
        assertThat(operation.get("qty")).isEqualTo(new BigDecimal("11"));
        assertThat(operation.get("unit")).isEqualTo("米");
        assertThat(operation.get("unit_price")).isEqualTo(new BigDecimal("3.50"));
        assertThat(result.get("completed")).isEqualTo(false);
        // 一键改候选 = 同部位其他待做（seq3 复烫 + seq9 套级打卷——套级工序的承载行就是本部位），
        // 不含已选的 op-2、不含已完成的 op-1
        assertThat(alternatives(result)).extracting(a -> String.valueOf(a.get("operation_id")))
                .containsExactly("op-3", "op-9");
        assertThat(progress(result)).containsEntry("total", 5).containsEntry("done", 2)
                .containsEntry("percent", 40);
    }

    @Test
    @DisplayName("反向护栏：本部位还有待做 ⇒ **不**回落套级（rerouted=false），即使套级工序待做")
    void positionLevelWinsOverSetLevelWhilePositionPending() {
        stubNewTokenScan(ITEM_CLOTH, standardOps());

        Map<String, Object> result = service.resolve(NEW_CODE, null, TENANT);

        // op-9 = 套级「外帘打卷」（挂在主布行 = 本部位上），但本部位还有部位级待做 ⇒ 不回落
        assertThat(operation(result).get("operation_id")).isEqualTo("op-2");
        assertThat(operation(result).get("rerouted")).isEqualTo(false);
        assertThat(operation(result)).doesNotContainKey("carrier");
    }

    @Test
    @DisplayName("套级回落：扫「纱帘」而本部位已干完 ⇒ 返回套级工序 + rerouted=true + 承载部位（D4）")
    void setLevelFallbackReroutesWhenPositionDone() {
        stubNewTokenScan(ITEM_GAUZE, standardOps());

        Map<String, Object> result = service.resolve(NEW_CODE, null, TENANT);

        Map<String, Object> operation = operation(result);
        assertThat(operation.get("operation_id")).isEqualTo("op-9");
        assertThat(operation.get("logical_name")).isEqualTo("外帘打卷");
        assertThat(operation.get("rerouted")).isEqualTo(true);
        assertThat(operation.get("determined_by")).isEqualTo("inferred");
        // 不静默换工序：给出「去哪做」（该套级工序的承载部位 = 主布行）
        assertThat(carrier(operation))
                .containsEntry("order_item_id", ITEM_CLOTH)
                .containsEntry("position_kind", "布帘");
        // 被扫的部位仍是响应里的 position（不是被换成的承载部位）
        assertThat(position(result).get("order_item_id")).isEqualTo(ITEM_GAUZE);
        assertThat(result.get("completed")).isEqualTo(false);
    }

    @Test
    @DisplayName("本套无活可做 ⇒ completed=true（不报错）+ 完成时刻取已完成工序最晚 done_at")
    void completedWhenNoPendingOperationInSet() {
        OffsetDateTime doneAt = OffsetDateTime.parse("2026-09-20T10:00:00+08:00");
        List<ProcessingPositionOperation> ops = List.of(
                op("op-1", ITEM_CLOTH, "布帘", "布艺遮光帘A", 1, "精裁-布", "11", "11", doneAt),
                op("op-4", ITEM_GAUZE, "纱帘", "纱帘B", 1, "精裁-纱", "8", "8", doneAt.plusHours(2)));
        stubNewTokenScan(ITEM_CLOTH, ops);

        Map<String, Object> result = service.resolve(NEW_CODE, null, TENANT);

        assertThat(result.get("completed")).isEqualTo(true);
        assertThat(result.get("operation")).isNull();
        assertThat(result.get("completed_at")).isEqualTo(doneAt.plusHours(2));
        assertThat(alternatives(result)).isEmpty();
    }

    // ============================================================ ③ 硬约束：工序必须确定

    @Test
    @DisplayName("🔴 硬约束：seq 重复（推断出多道）⇒ 422 OPERATION_AMBIGUOUS，**不静默取第一道**")
    void ambiguousSeqIsRefusedInsteadOfSilentlyPickingFirst() {
        List<ProcessingPositionOperation> ops = List.of(
                op("op-2", ITEM_CLOTH, "布帘", "布艺遮光帘A", 2, "定型-布", "11", "0"),
                op("op-3", ITEM_CLOTH, "布帘", "布艺遮光帘A", 2, "复烫-布", "11", "0"));
        stubNewTokenScan(ITEM_CLOTH, ops);

        assertThatThrownBy(() -> service.resolve(NEW_CODE, null, TENANT))
                .isInstanceOfSatisfying(BusinessException.class, e -> {
                    assertThat(e.getCode()).isEqualTo("OPERATION_AMBIGUOUS");
                    assertThat(e.getHttpStatus()).isEqualTo(422);
                    assertThat(e.getMessage()).contains("seq");
                });
    }

    @Test
    @DisplayName("一键改：显式 operation_id 属于本部位 ⇒ determined_by=picked（默认下一道仍可改）")
    void pickedOperationWins() {
        stubNewTokenScan(ITEM_CLOTH, standardOps());

        Map<String, Object> result = service.resolve(NEW_CODE, "op-3", TENANT);

        assertThat(operation(result).get("operation_id")).isEqualTo("op-3");
        assertThat(operation(result).get("determined_by")).isEqualTo("picked");
        assertThat(alternatives(result)).extracting(a -> String.valueOf(a.get("operation_id")))
                .containsExactly("op-2", "op-9");
    }

    @Test
    @DisplayName("一键改：指定**别的部位**的工序 ⇒ 422（不得跨部位报工，D9 同口径）")
    void pickedOtherPositionOperationIsRefused() {
        stubNewTokenScan(ITEM_CLOTH, standardOps());

        assertThatThrownBy(() -> service.resolve(NEW_CODE, "op-4", TENANT))
                .isInstanceOfSatisfying(BusinessException.class, e -> {
                    assertThat(e.getCode()).isEqualTo("OPERATION_NOT_IN_SCAN_TARGET");
                    assertThat(e.getHttpStatus()).isEqualTo(422);
                });
    }

    @Test
    @DisplayName("新码未命中 ⇒ 回落旧四形态（不是 404）：同一入口兼容存量车间在产的旧码")
    void newTokenMissFallsBackToLegacyForms() {
        stubLegacyQrTokenScan();

        Map<String, Object> result = service.resolve(OLD_CODE, null, TENANT);

        assertThat(result.get("granularity")).isEqualTo("order");
    }

    @Test
    @DisplayName("新码命中但套已软删 ⇒ 404（fail-closed，不静默回落旧路径）")
    void staleTokenFailsClosed() {
        when(setPartTokenMapper.selectOne(any())).thenReturn(partToken(ITEM_CLOTH));
        when(orderSetMapper.selectById(SET_ID)).thenReturn(set(SET_ID, SET_NO, 14, 1));

        assertThatThrownBy(() -> service.resolve(NEW_CODE, null, TENANT))
                .isInstanceOfSatisfying(BusinessException.class,
                        e -> assertThat(e.getCode()).isEqualTo("NOT_FOUND"));
    }

    @Test
    @DisplayName("空白扫码内容 ⇒ 422（不查库）")
    void blankTokenRejected() {
        assertThatThrownBy(() -> service.resolve("   ", null, TENANT))
                .isInstanceOfSatisfying(BusinessException.class,
                        e -> assertThat(e.getCode()).isEqualTo("VALIDATION_ERROR"));
        verify(setPartTokenMapper, never()).selectOne(any());
    }

    // ============================================================ ② 旧码：降级形态

    @Test
    @DisplayName("🔴 旧码降级：granularity=order + 强制选套选部位，**绝不默认取第 1 套**（D10）")
    void legacyTokenDegradesAndNeverDefaultsToFirstSet() {
        stubLegacyQrTokenScan();

        Map<String, Object> result = service.resolve(OLD_CODE, null, TENANT);

        assertThat(result.get("granularity")).isEqualTo("order");
        assertThat(result.get("processing_order_no")).isEqualTo(PO_NO);
        // 🔴 系统明确知道它不知道是哪一套 ⇒ 一律 null（默认 = 静默把进度记到错的套上）
        assertThat(result.get("set_no")).isNull();
        assertThat(result.get("set_index")).isNull();
        assertThat(result.get("position")).isNull();
        assertThat(result.get("operation")).isNull();
        assertThat(result.get("set_progress")).isNull();
        // null = 未知（降级形态判不出哪一套 ⇒ 判不出完没完），不是 false
        assertThat(result.get("completed")).isNull();
        assertThat(result.get("needs_selection")).isEqualTo(List.of("set", "position"));
        // 可选清单里**有**第 1 套（工人可一键选它）—— 但它是候选，不是默认值
        List<Map<String, Object>> selections = selections(result);
        assertThat(selections).extracting(s -> String.valueOf(s.get("set_no")))
                .containsExactly(FIRST_SET_NO, SET_NO);
        assertThat(positionsOf(selections.get(0)))
                .extracting(p -> String.valueOf(p.get("order_item_id")))
                .containsExactly(ITEM_CLOTH);
        assertThat(positionsOf(selections.get(1)))
                .extracting(p -> String.valueOf(p.get("order_item_id")))
                .containsExactly(ITEM_GAUZE);
    }

    @Test
    @DisplayName("旧码四形态**一字不动**：order_id / order_no / qr_token / processing_order_no 全部解析成功")
    void legacyFourFormsAllStillResolve() {
        // ① 内部 order_id
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order());
        assertThat(service.resolve(ORDER_ID, null, TENANT).get("granularity")).isEqualTo("order");

        // ② 订单号 order_no（手输纸质单号）
        when(orderMapper.selectById("ORD-20260917-001")).thenReturn(null);
        when(orderMapper.selectOne(any())).thenReturn(order());
        assertThat(service.resolve("ORD-20260917-001", null, TENANT).get("granularity"))
                .isEqualTo("order");

        // ③ 加工单 qr_token（打印二维码内容）
        when(orderMapper.selectById(anyString())).thenReturn(null);
        when(orderMapper.selectOne(any())).thenReturn(null);
        when(processingOrderMapper.selectOne(argThatWrapper("qr_token"))).thenReturn(processingOrder());
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order());
        assertThat(service.resolve(OLD_CODE, null, TENANT).get("granularity")).isEqualTo("order");

        // ④ 加工单号 processing_order_no（工人端「手输加工单号」兜底）
        when(processingOrderMapper.selectOne(argThatWrapper("qr_token"))).thenReturn(null);
        when(processingOrderMapper.selectOne(argThatWrapper("processing_order_no")))
                .thenReturn(processingOrder());
        assertThat(service.resolve(PO_NO, null, TENANT).get("granularity")).isEqualTo("order");
    }

    // ============================================================ ②′ 旧码收口（issue #4794）

    @Test
    @DisplayName("🔴 旧码收口：选完套 + 部位 ⇒ 部位级视图（与**新码**同一份推断），needs_selection 清空")
    void legacySelectionResolvesToSetPositionView() {
        stubLegacySelectionScan();

        Map<String, Object> result = service.resolve(OLD_CODE, null, SET_ID, ITEM_GAUZE, TENANT);

        // 改前：set_id/order_item_id 无入参可给 ⇒ 恒 `granularity="order"`（D1：无路可走）
        assertThat(result.get("granularity")).isEqualTo("set_position");
        assertThat(result.get("set_no")).isEqualTo(SET_NO);
        assertThat(result.get("processing_order_no")).isEqualTo(PO_NO);
        assertThat(position(result).get("order_item_id")).isEqualTo(ITEM_GAUZE);
        assertThat(result.get("needs_selection")).isEqualTo(List.of());
        // 工序仍由**系统**推断（防呆⑤）：该部位 seq 最小的未完成者
        assertThat(operation(result).get("operation_id")).isEqualTo("op-4");
        assertThat(operation(result).get("determined_by")).isEqualTo("inferred");
        assertThat(result.get("completed")).isEqualTo(false);
    }

    @Test
    @DisplayName("🔴 旧码收口 + 防呆④：所选部位之外的工序（一键改）⇒ 422 OPERATION_NOT_IN_SCAN_TARGET")
    void legacySelectionCrossPositionPickIsRefused() {
        stubLegacySelectionScan();

        assertThatThrownBy(() -> service.resolve(OLD_CODE, "op-1", SET_ID, ITEM_GAUZE, TENANT))
                .isInstanceOfSatisfying(BusinessException.class, e -> {
                    assertThat(e.getCode()).isEqualTo("OPERATION_NOT_IN_SCAN_TARGET");
                    assertThat(e.getHttpStatus()).isEqualTo(422);
                });
    }

    @Test
    @DisplayName("🔴 反向护栏：**新码**不读 setId/orderItemId（码已给出套 × 部位 ⇒ 对已有新码零影响）")
    void newCodeIgnoresSelectionArguments() {
        stubNewTokenScan(ITEM_CLOTH, standardOps());

        // 硬塞一个**别的**套 + 别的部位 ⇒ 仍按码给的部位解析
        Map<String, Object> result = service.resolve(NEW_CODE, null, "set-hacked", ITEM_GAUZE, TENANT);

        assertThat(result.get("granularity")).isEqualTo("set_position");
        assertThat(position(result).get("order_item_id")).isEqualTo(ITEM_CLOTH);
        assertThat(result.get("set_no")).isEqualTo(SET_NO);
        assertThat(operation(result).get("operation_id")).isEqualTo("op-2");
    }

    @Test
    @DisplayName("🔴 旧码收口（越权面）：所选套不属于本次扫码的加工单 ⇒ 422，不按别人的单记账")
    void selectionOutsideScannedOrderIsRefused() {
        stubLegacySelectionScan();
        when(orderSetMapper.selectById("set-other")).thenReturn(ProcessingOrderSet.builder()
                .id("set-other").tenantId(TENANT).processingOrderId("po-other")
                .setIndex(1).setNo("CSO-OTHER-001").deleted(0).build());

        assertThatThrownBy(() -> service.resolve(OLD_CODE, null, "set-other", ITEM_CLOTH, TENANT))
                .isInstanceOfSatisfying(BusinessException.class, e -> {
                    assertThat(e.getCode()).isEqualTo("SCAN_SELECTION_NOT_IN_ORDER");
                    assertThat(e.getHttpStatus()).isEqualTo(422);
                });
    }

    @Test
    @DisplayName("🔴 旧码收口（越权面）：所选部位不在该套 ⇒ 422（不静默说「本套已完成」）")
    void selectionPositionOutsideSetIsRefused() {
        stubLegacySelectionScan();

        assertThatThrownBy(() -> service.resolve(OLD_CODE, null, SET_ID, "oi-nope", TENANT))
                .isInstanceOfSatisfying(BusinessException.class,
                        e -> assertThat(e.getCode()).isEqualTo("SCAN_SELECTION_NOT_IN_ORDER"));
    }

    @Test
    @DisplayName("🔴 旧码收口：只给一半（缺部位）⇒ 仍是降级形态 needs_selection（不静默解析）")
    void halfSelectionStillDegrades() {
        stubLegacySelectionScan();

        Map<String, Object> result = service.resolve(OLD_CODE, null, SET_ID, null, TENANT);

        assertThat(result.get("granularity")).isEqualTo("order");
        assertThat(result.get("needs_selection")).isEqualTo(List.of("set", "position"));
        assertThat(result.get("set_no")).isNull();
    }

    @Test
    @DisplayName("🔴 旧码收口：解析仍是**只读**（选完套/部位也不写库）")
    void legacySelectionResolveIsReadOnly() {
        stubLegacySelectionScan();

        service.resolve(OLD_CODE, null, SET_ID, ITEM_GAUZE, TENANT);

        verify(orderSetMapper, never()).insert(any(ProcessingOrderSet.class));
        verify(orderSetMapper, never()).updateById(any(ProcessingOrderSet.class));
        verify(positionOperationMapper, never()).insert(any(ProcessingPositionOperation.class));
        verify(positionOperationMapper, never()).updateById(any(ProcessingPositionOperation.class));
        verify(processingOrderMapper, never()).updateById(any(ProcessingOrder.class));
        verify(orderMapper, never()).updateById(any(Order.class));
    }

    @Test
    @DisplayName("五形态全不命中 ⇒ 404（既有行为保留）")
    void unknownCodeIsNotFound() {
        when(orderMapper.selectById(anyString())).thenReturn(null);
        when(orderMapper.selectOne(any())).thenReturn(null);
        when(processingOrderMapper.selectOne(any())).thenReturn(null);

        assertThatThrownBy(() -> service.resolve("NOPE-404", null, TENANT))
                .isInstanceOfSatisfying(BusinessException.class,
                        e -> assertThat(e.getCode()).isEqualTo("NOT_FOUND"));
    }

    // ============================================================ 只读（幂等）

    @Test
    @DisplayName("解析与推断**不写库**（本切片是只读面；报工主闭环 = 切片 ②）")
    void resolveIsReadOnly() {
        stubNewTokenScan(ITEM_CLOTH, standardOps());

        service.resolve(NEW_CODE, null, TENANT);

        verify(setPartTokenMapper, never()).insert(any(ProcessingSetPartToken.class));
        verify(setPartTokenMapper, never()).updateById(any(ProcessingSetPartToken.class));
        verify(setPartTokenMapper, never()).deleteById(anyString());
        verify(orderSetMapper, never()).insert(any(ProcessingOrderSet.class));
        verify(orderSetMapper, never()).updateById(any(ProcessingOrderSet.class));
        verify(positionOperationMapper, never()).insert(any(ProcessingPositionOperation.class));
        verify(positionOperationMapper, never()).updateById(any(ProcessingPositionOperation.class));
        verify(orderItemMapper, never()).insert(any(OrderItem.class));
        verify(orderItemMapper, never()).updateById(any(OrderItem.class));
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
        verify(processingOrderMapper, never()).updateById(any(ProcessingOrder.class));
        verify(orderMapper, never()).insert(any(Order.class));
        verify(orderMapper, never()).updateById(any(Order.class));
    }

    // ============================================================ 夹具

    @Test
    @DisplayName("§3.1 的 stalled 键（切片 ③，issue #4776）：上道完成时刻可知且等超阈值 ⇒ kind=not_started")
    void stalledKeyIsEmittedWithCriterion() {
        OffsetDateTime predecessorDoneAt = OffsetDateTime.now().minusHours(6);
        stubNewTokenScan(ITEM_CLOTH, List.of(
                op("op-1", ITEM_CLOTH, "布帘", "布艺遮光帘A", 1, "精裁-布", "11", "11", predecessorDoneAt),
                op("op-2", ITEM_CLOTH, "布帘", "布艺遮光帘A", 2, "定型-布", "11", "0")));

        Map<String, Object> result = service.resolve(NEW_CODE, null, TENANT);

        Map<String, Object> stalled = stalled(result);
        assertThat(stalled.get("kind")).isEqualTo(ProductionStuckPointService.KIND_NOT_STARTED);
        assertThat(stalled.get("state")).isEqualTo(ProductionStuckPointService.STATE_NOT_STARTED);
        assertThat(stalled.get("predecessor_operation_id")).isEqualTo("op-1");
        assertThat(stalled.get("predecessor_done_at")).isEqualTo(predecessorDoneAt);
        // 「卡了多久」= now - 前道 done_at（**不是** updated_at）
        assertThat((Double) stalled.get("stalled_hours")).isGreaterThan(5.9);
        assertThat(stalled.get("threshold_source")).isEqualTo("default");
    }

    /** 标准一套：布帘 3 道（1 已完成 / 2 待做）+ 纱帘 1 道（已完成）+ 套级「外帘打卷」待做。 */
    private List<ProcessingPositionOperation> standardOps() {
        return List.of(
                op("op-1", ITEM_CLOTH, "布帘", "布艺遮光帘A", 1, "精裁-布", "11", "11"),
                op("op-2", ITEM_CLOTH, "布帘", "布艺遮光帘A", 2, "定型-布", "11", "0"),
                op("op-3", ITEM_CLOTH, "布帘", "布艺遮光帘A", 3, "复烫-布", "11", "0"),
                op("op-4", ITEM_GAUZE, "纱帘", "纱帘B", 1, "精裁-纱", "8", "8"),
                op("op-9", ITEM_CLOTH, "布帘", "布艺遮光帘A", 9, "外帘打卷", "1", "0"));
    }

    private void stubNewTokenScan(String scannedItemId, List<ProcessingPositionOperation> ops) {
        when(setPartTokenMapper.selectOne(any())).thenReturn(partToken(scannedItemId));
        when(orderSetMapper.selectById(SET_ID)).thenReturn(set(SET_ID, SET_NO, 14, 0));
        when(processingOrderMapper.selectById(PO_ID)).thenReturn(processingOrder());
        when(positionOperationMapper.selectList(any())).thenReturn(ops);
    }

    /** 旧码（加工单级 qr_token）路径：新码未命中 ⇒ 走**真实**的四形态解析。 */
    private void stubLegacyQrTokenScan() {        when(setPartTokenMapper.selectOne(any())).thenReturn(null);
        when(orderMapper.selectById(OLD_CODE)).thenReturn(null);
        when(orderMapper.selectOne(any())).thenReturn(null);
        when(processingOrderMapper.selectOne(any())).thenReturn(processingOrder());
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order());
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder());
        when(orderSetMapper.selectList(any())).thenReturn(List.of(
                set(FIRST_SET_ID, FIRST_SET_NO, 1, 0),
                set(SET_ID, SET_NO, 14, 0)));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-1", ITEM_CLOTH, "布帘", "布艺遮光帘A", 1, "精裁-布", "11", "0", FIRST_SET_ID),
                op("op-4", ITEM_GAUZE, "纱帘", "纱帘B", 1, "精裁-纱", "8", "0", SET_ID)));
    }

    /** 旧码 + 工人选了（套, 部位）：该套的实例行就位（与 `selections` 清单**同一份**来源）。 */
    private void stubLegacySelectionScan() {
        stubLegacyQrTokenScan();
        when(orderSetMapper.selectById(SET_ID)).thenReturn(set(SET_ID, SET_NO, 14, 0));
    }

    private ProcessingSetPartToken partToken(String orderItemId) {
        return ProcessingSetPartToken.builder()
                .id("tok-1").tenantId(TENANT).processingOrderId(PO_ID).setId(SET_ID)
                .orderItemId(orderItemId)
                .positionKind(ITEM_CLOTH.equals(orderItemId) ? "布帘" : "纱帘")
                .token(NEW_CODE).deleted(0)
                .build();
    }

    private ProcessingOrderSet set(String id, String setNo, int index, Integer deleted) {
        return ProcessingOrderSet.builder()
                .id(id).tenantId(TENANT).processingOrderId(PO_ID)
                .setIndex(index).setNo(setNo).deleted(deleted)
                .build();
    }

    private ProcessingPositionOperation op(String id, String itemId, String positionKind,
                                           String positionName, int seq, String operationName,
                                           String qty, String doneQty) {
        return op(id, itemId, positionKind, positionName, seq, operationName, qty, doneQty, null, SET_ID);
    }

    private ProcessingPositionOperation op(String id, String itemId, String positionKind,
                                           String positionName, int seq, String operationName,
                                           String qty, String doneQty, OffsetDateTime doneAt) {
        return op(id, itemId, positionKind, positionName, seq, operationName, qty, doneQty, doneAt, SET_ID);
    }

    private ProcessingPositionOperation op(String id, String itemId, String positionKind,
                                           String positionName, int seq, String operationName,
                                           String qty, String doneQty, String setId) {
        return op(id, itemId, positionKind, positionName, seq, operationName, qty, doneQty, null, setId);
    }

    private ProcessingPositionOperation op(String id, String itemId, String positionKind,
                                           String positionName, int seq, String operationName,
                                           String qty, String doneQty, OffsetDateTime doneAt,
                                           String setId) {
        BigDecimal planned = new BigDecimal(qty);
        BigDecimal done = new BigDecimal(doneQty);
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId(PO_ID).setId(setId)
                .orderItemId(itemId).positionKind(positionKind).positionName(positionName)
                .seq(seq).operationName(operationName).groupName("车位").unit("米")
                .qty(planned).doneQty(done).qtySource("fabric_meters")
                .unitPrice(new BigDecimal("3.50"))
                .isMustFinish(false).isStartMarker(false)
                .status(done.compareTo(planned) >= 0 ? "done" : "pending")
                .doneAt(doneAt).deleted(0)
                .build();
    }

    /** 工序库（判部位级 / 套级的唯一来源）：`scope='set'` = 套级。 */
    private Map<String, Map<String, Object>> catalog() {
        Map<String, Map<String, Object>> catalog = new LinkedHashMap<>();
        for (String name : List.of("精裁-布", "定型-布", "复烫-布", "精裁-纱")) {
            catalog.put(name, Map.of("scope", "position"));
        }
        catalog.put("外帘打卷", Map.of("scope", "set"));
        return catalog;
    }

    private Order order() {
        Order o = new Order();
        o.setId(ORDER_ID);
        o.setTenantId(TENANT);
        o.setOrderNo("ORD-20260917-001");
        o.setStatus("producing");
        o.setDeleted(0);
        return o;
    }

    private ProcessingOrder processingOrder() {
        ProcessingOrder po = new ProcessingOrder();
        po.setId(PO_ID);
        po.setTenantId(TENANT);
        po.setOrderId(ORDER_ID);
        po.setProcessingOrderNo(PO_NO);
        po.setStatus("in_processing");
        po.setDeleted(0);
        return po;
    }

    /** 按 WHERE 片段里的列名匹配 QueryWrapper（区分 ③ qr_token 与 ④ processing_order_no）。 */
    private static Wrapper<ProcessingOrder> argThatWrapper(String column) {
        return org.mockito.ArgumentMatchers.argThat(
                w -> w != null && w.getSqlSegment() != null && w.getSqlSegment().contains(column));
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> operation(Map<String, Object> result) {
        return (Map<String, Object>) result.get("operation");
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> carrier(Map<String, Object> operation) {
        return (Map<String, Object>) operation.get("carrier");
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> positionsOf(Map<String, Object> selection) {
        return (List<Map<String, Object>>) selection.get("positions");
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> position(Map<String, Object> result) {
        return (Map<String, Object>) result.get("position");
    }

    /** 一屏输出里的卡点键（切片 ③，issue #4776；设计 §3.1）。 */
    @SuppressWarnings("unchecked")
    private static Map<String, Object> stalled(Map<String, Object> result) {
        return (Map<String, Object>) result.get("stalled");
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> progress(Map<String, Object> result) {
        return (Map<String, Object>) result.get("set_progress");
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> alternatives(Map<String, Object> result) {
        return (List<Map<String, Object>>) result.get("alternatives");
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> selections(Map<String, Object> result) {
        return (List<Map<String, Object>>) result.get("selections");
    }
}
