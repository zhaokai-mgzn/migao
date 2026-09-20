// case_ids: PG-018
package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.ProcessingOrderSet;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingOrderSetMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
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
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * 「卡在哪」的判据与报表（切片 ③，issue #4776；设计
 * {@code docs/design/set-code-and-scan-loop.md} §6）。
 *
 * <p><b>本测试是行为断言，不是桩断言</b>：{@link ProductionService} 用**真实对象**（只 mock Mapper）
 * —— 三态的「已完成」必须走**既有唯一一份** {@code isDone}（{@code done_qty ≥ qty}），
 * mock 掉它等于把被测口径换成桩（「绿了但没跑」）。</p>
 *
 * <p><b>红证（改前实测，逐条输出见 PR body）</b>：</p>
 * <ol>
 *   <li><b>「没开工」判据改前不成立</b>：切片 ① 的 {@code ProductionScanService} javadoc 逐字登记
 *       「{@code stalled}（§3.1）属切片 ③（卡点报表），本切片不落」⇒ 改前该键**不存在**、
 *       也没有任何卡点报表 ⇒ 注入「把 {@code stalled} 键整条去掉」= 改前真实状态，
 *       {@link #stalledViewShapeCarriesThresholdSource} 必红；</li>
 *   <li><b>三态混淆</b>：注入「把做了一半（{@code 0 < done_qty < qty}）算成没开工」⇒
 *       {@link #halfDoneIsNotNotStarted} 与 {@link #stalledHoursUsePredecessorDoneAtNotUpdatedAt}
 *       必红（催料催到正在干的活上）；</li>
 *   <li><b>用 {@code updated_at} 当卡住时长</b>：注入「{@code stalled_hours} 取
 *       {@code op.updatedAt} 而不是前道 {@code done_at}」⇒ ②③ 两条必红
 *       （{@link #stalledHoursUsePredecessorDoneAtNotUpdatedAt} 静默少报、
 *       {@link #notStuckWhenDoneAtRecentEvenIfUpdatedAtOld} 静默误报）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("ProductionStuckPointService 「卡在哪」判据与报表（切片 ③）")
class ProductionStuckPointServiceTest {

    private static final Long TENANT = 1L;
    private static final String PO_ID = "po-1";
    private static final String OTHER_PO_ID = "po-2";
    private static final String SET_ID = "set-14";
    private static final String SET_NO = "CSO260915-02615-014";
    private static final String OTHER_SET_ID = "set-15";
    private static final String ITEM_CLOTH = "oi-cloth";
    private static final String ITEM_GAUZE = "oi-gauze";

    /** 挂钟固定：判据是「等了多久 > 阈值」，测试必须能确定复现（不依赖真实时间）。 */
    private static final OffsetDateTime NOW = OffsetDateTime.parse("2026-09-20T18:00:00+08:00");

    /** S3 兜底阈值（设计 §6.4「如 T_wait = 4h」）。 */
    private static final double THRESHOLD = 4.0;

    @Mock
    private ProcessingPositionOperationMapper positionOperationMapper;
    @Mock
    private ProcessingOrderSetMapper orderSetMapper;
    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private ProductionWorkLogMapper workLogMapper;
    @Mock
    private OrderMapper orderMapper;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private ClientRequestIdService clientRequestIdService;

    private ProductionService productionService;
    private ProductionStuckPointService service;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        productionService = new ProductionService(processingOrderMapper, positionOperationMapper,
                workLogMapper, orderMapper, orderItemMapper, clientRequestIdService);
        service = new ProductionStuckPointService(productionService, positionOperationMapper,
                orderSetMapper, THRESHOLD);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ============================================================ ① 三态（必须可区分，不许混）

    @Test
    @DisplayName("三态可区分：没开工(done_qty=0)/做了一半(0<done_qty<qty)/已完成(done_qty≥qty) 互斥且完备")
    void threeStatesAreDistinguishable() {
        assertThat(service.stateOf(op("op-1", ITEM_CLOTH, 1, "精裁-布", "11", "0", null)))
                .isEqualTo(ProductionStuckPointService.STATE_NOT_STARTED);
        assertThat(service.stateOf(op("op-2", ITEM_CLOTH, 2, "三边", "11", "6", null)))
                .isEqualTo(ProductionStuckPointService.STATE_IN_PROGRESS);
        assertThat(service.stateOf(op("op-3", ITEM_CLOTH, 3, "定型", "11", "11", NOW.minusHours(9))))
                .isEqualTo(ProductionStuckPointService.STATE_COMPLETED);
        // done_qty 为 NULL 与 0 同读（既有 nz 口径）⇒ 仍是没开工
        assertThat(service.stateOf(op("op-4", ITEM_CLOTH, 4, "复烫", "11", null, null)))
                .isEqualTo(ProductionStuckPointService.STATE_NOT_STARTED);
        // 超额完成仍是已完成（不因 > 而落进「做了一半」）
        assertThat(service.stateOf(op("op-5", ITEM_CLOTH, 5, "包装", "11", "12", NOW.minusHours(2))))
                .isEqualTo(ProductionStuckPointService.STATE_COMPLETED);
    }

    @Test
    @DisplayName("🔴 反向护栏（红证②）：做了一半**不**算没开工 —— 不许把『有人扫过』混成『没人扫』")
    void halfDoneIsNotNotStarted() {
        ProcessingPositionOperation half = op("op-2", ITEM_CLOTH, 2, "三边", "11", "6", null);

        assertThat(service.isNotStarted(half)).isFalse();
        assertThat(service.stateOf(half)).isEqualTo(ProductionStuckPointService.STATE_IN_PROGRESS);
        // 即使上道早就完成（等了 6 小时），「做了一半」也**不是** A 模式要催的对象
        List<ProcessingPositionOperation> ops = List.of(
                op("op-1", ITEM_CLOTH, 1, "精裁-布", "11", "11", NOW.minusHours(6)),
                half);
        Map<String, Object> stalled = service.stalledView(ops, half, NOW);
        assertThat(stalled.get("kind")).isNull();
        assertThat(stalled.get("stalled_hours")).isNull();
    }

    @Test
    @DisplayName("反向护栏（判据不放宽）：done_qty=0 但 done_at 非空（矛盾态）⇒ 不判没开工")
    void zeroDoneQtyWithDoneAtIsNotNotStarted() {
        ProcessingPositionOperation contradictory =
                op("op-6", ITEM_CLOTH, 6, "打孔", "11", "0", NOW.minusHours(1));

        assertThat(service.stateOf(contradictory))
                .isEqualTo(ProductionStuckPointService.STATE_IN_PROGRESS);
        assertThat(service.isNotStarted(contradictory)).isFalse();
    }

    // ============================================================ ② A 模式卡点（设计 §6.1 行①/§6.3）

    @Test
    @DisplayName("卡点成立：没开工 + 立即前道已完成 + 等待超阈值 ⇒ kind=not_started，且「上道几点完成」可答（D8）")
    void stuckWhenNotStartedAndPredecessorDoneBeyondThreshold() {
        OffsetDateTime predecessorDoneAt = NOW.minusHours(6);
        List<ProcessingPositionOperation> ops = List.of(
                op("op-1", ITEM_CLOTH, 1, "精裁-布", "11", "11", predecessorDoneAt),
                op("op-2", ITEM_CLOTH, 2, "三边", "11", "0", null));

        Map<String, Object> stalled = service.stalledView(ops, ops.get(1), NOW);

        assertThat(stalled.get("kind")).isEqualTo(ProductionStuckPointService.KIND_NOT_STARTED);
        assertThat(stalled.get("state")).isEqualTo(ProductionStuckPointService.STATE_NOT_STARTED);
        assertThat(stalled.get("predecessor_operation_id")).isEqualTo("op-1");
        assertThat(stalled.get("predecessor_done")).isEqualTo(true);
        assertThat(stalled.get("predecessor_done_at")).isEqualTo(predecessorDoneAt);
        assertThat((Double) stalled.get("stalled_hours")).isCloseTo(6.0, within(0.001));
        assertThat(stalled.get("threshold_hours")).isEqualTo(THRESHOLD);
        assertThat(stalled.get("threshold_source")).isEqualTo(ProductionStuckPointService.THRESHOLD_SOURCE_DEFAULT);
    }

    @Test
    @DisplayName("反向护栏：前道**没做完** ⇒ 不卡（判据的合取项，§6.1 行①）")
    void notStuckWhenPredecessorNotDone() {
        List<ProcessingPositionOperation> ops = List.of(
                op("op-1", ITEM_CLOTH, 1, "精裁-布", "11", "6", null),
                op("op-2", ITEM_CLOTH, 2, "三边", "11", "0", null));

        assertThat(service.stalledView(ops, ops.get(1), NOW).get("kind")).isNull();
    }

    @Test
    @DisplayName("反向护栏：前道已完成但 **done_at 不可知**（切片②之前的存量行）⇒ 不卡（§6.3 p.done_at IS NOT NULL）")
    void notStuckWhenPredecessorDoneAtUnknown() {
        List<ProcessingPositionOperation> ops = List.of(
                op("op-1", ITEM_CLOTH, 1, "精裁-布", "11", "11", null),
                op("op-2", ITEM_CLOTH, 2, "三边", "11", "0", null));

        Map<String, Object> stalled = service.stalledView(ops, ops.get(1), NOW);

        assertThat(stalled.get("predecessor_done")).isEqualTo(true);
        assertThat(stalled.get("predecessor_done_at")).isNull();
        assertThat(stalled.get("stalled_hours")).isNull();
        assertThat(stalled.get("kind")).isNull();
    }

    @Test
    @DisplayName("反向护栏（判据不放宽）：未超阈值 ⇒ 不卡；**恰好等于**阈值也不卡（`>` 不是 `>=`）")
    void notStuckAtOrWithinThreshold() {
        for (double hours : new double[]{0.5, 3.99, THRESHOLD}) {
            List<ProcessingPositionOperation> ops = List.of(
                    op("op-1", ITEM_CLOTH, 1, "精裁-布", "11", "11", NOW.minusSeconds((long) (hours * 3600))),
                    op("op-2", ITEM_CLOTH, 2, "三边", "11", "0", null));
            assertThat(service.stalledView(ops, ops.get(1), NOW).get("kind"))
                    .as("等了 %s 小时（阈值 %s）", hours, THRESHOLD).isNull();
        }
        // 刚过阈值 ⇒ 卡（边界另一侧，证明上面不是「恒 null」的空断言）
        List<ProcessingPositionOperation> ops = List.of(
                op("op-1", ITEM_CLOTH, 1, "精裁-布", "11", "11", NOW.minusSeconds((long) ((THRESHOLD + 0.01) * 3600))),
                op("op-2", ITEM_CLOTH, 2, "三边", "11", "0", null));
        assertThat(service.stalledView(ops, ops.get(1), NOW).get("kind"))
                .isEqualTo(ProductionStuckPointService.KIND_NOT_STARTED);
    }

    @Test
    @DisplayName("反向护栏：首道工序没有前道 ⇒ 永不进卡点表（§6.3 ⚠️：首道的『等』是等派工，另立判据）")
    void firstOperationNeverStuck() {
        List<ProcessingPositionOperation> ops = List.of(
                op("op-1", ITEM_CLOTH, 1, "精裁-布", "11", "0", null));
        // 即使该实例行很旧（updated_at / created_at 很久以前）也不得据此判卡
        Map<String, Object> stalled = service.stalledView(ops, ops.get(0), NOW);

        assertThat(stalled.get("predecessor_operation_id")).isNull();
        assertThat(stalled.get("stalled_hours")).isNull();
        assertThat(stalled.get("kind")).isNull();
    }

    @Test
    @DisplayName("前道 = **立即**前道（同部位 seq 最大的更小 seq），不是任何更早的一道")
    void predecessorIsImmediateNotAnyEarlier() {
        OffsetDateTime recent = NOW.minusHours(1);
        OffsetDateTime ancient = NOW.minusHours(20);
        List<ProcessingPositionOperation> ops = List.of(
                op("op-1", ITEM_CLOTH, 1, "精裁-布", "11", "11", ancient),
                op("op-2", ITEM_CLOTH, 2, "三边", "11", "11", recent),
                op("op-3", ITEM_CLOTH, 3, "定型", "11", "0", null));

        Map<String, Object> stalled = service.stalledView(ops, ops.get(2), NOW);

        assertThat(stalled.get("predecessor_operation_id")).isEqualTo("op-2");
        assertThat((Double) stalled.get("stalled_hours")).isCloseTo(1.0, within(0.001));
        // 立即前道只等了 1 小时（< 4h）⇒ 不卡；若误取 seq=1（等了 20h）会**误报**卡点
        assertThat(stalled.get("kind")).isNull();
    }

    @Test
    @DisplayName("前道匹配是 null-safe（= §6.3 的 IS NOT DISTINCT FROM）：order_item_id 为 NULL 的存量行也能匹配")
    void predecessorMatchedNullSafeByOrderItemId() {
        List<ProcessingPositionOperation> ops = List.of(
                op("op-1", null, 1, "精裁-布", "11", "11", NOW.minusHours(6)),
                op("op-2", null, 2, "三边", "11", "0", null));

        Map<String, Object> stalled = service.stalledView(ops, ops.get(1), NOW);

        assertThat(stalled.get("predecessor_operation_id")).isEqualTo("op-1");
        assertThat(stalled.get("kind")).isEqualTo(ProductionStuckPointService.KIND_NOT_STARTED);
    }

    @Test
    @DisplayName("🔴 红证③（正向）：「等了多久」只取前道 done_at —— updated_at 被污染成 1 分钟前也必须仍报 6 小时")
    void stalledHoursUsePredecessorDoneAtNotUpdatedAt() {
        OffsetDateTime predecessorDoneAt = NOW.minusHours(6);
        // 前道完成 6 小时后**任何**一次更新（改名 / 改单价 / 重新实例化）都会刷新 updated_at
        ProcessingPositionOperation predecessor =
                op("op-1", ITEM_CLOTH, 1, "精裁-布", "11", "11", predecessorDoneAt);
        predecessor.setUpdatedAt(NOW.minusMinutes(1));
        ProcessingPositionOperation current = op("op-2", ITEM_CLOTH, 2, "三边", "11", "0", null);
        current.setCreatedAt(NOW.minusMinutes(1));
        current.setUpdatedAt(NOW.minusMinutes(1));

        Map<String, Object> stalled = service.stalledView(List.of(predecessor, current), current, NOW);

        assertThat((Double) stalled.get("stalled_hours"))
                .as("用 updated_at 会得到 ~0.017 小时 ⇒ 静默少报（该报的卡点不报）")
                .isCloseTo(6.0, within(0.001));
        assertThat(stalled.get("kind")).isEqualTo(ProductionStuckPointService.KIND_NOT_STARTED);
    }

    @Test
    @DisplayName("🔴 红证③（反向）：updated_at 很旧但前道 **done_at 是 1 小时前** ⇒ 不卡（用 updated_at 会误报）")
    void notStuckWhenDoneAtRecentEvenIfUpdatedAtOld() {
        ProcessingPositionOperation predecessor =
                op("op-1", ITEM_CLOTH, 1, "精裁-布", "11", "11", NOW.minusHours(1));
        predecessor.setUpdatedAt(NOW.minusHours(10));
        ProcessingPositionOperation current = op("op-2", ITEM_CLOTH, 2, "三边", "11", "0", null);
        current.setUpdatedAt(NOW.minusHours(10));

        Map<String, Object> stalled = service.stalledView(List.of(predecessor, current), current, NOW);

        assertThat((Double) stalled.get("stalled_hours")).isCloseTo(1.0, within(0.001));
        assertThat(stalled.get("kind"))
                .as("用 updated_at（10 小时前）会误报卡点 ⇒ 催料催到刚交的活上")
                .isNull();
    }

    // ============================================================ ③ §3.1 的 stalled 键形状

    @Test
    @DisplayName("🔴 红证①：§3.1 的 stalled 键必须存在且带判据与阈值来源（改前该键整条不存在）")
    void stalledViewShapeCarriesThresholdSource() {
        List<ProcessingPositionOperation> ops = List.of(
                op("op-1", ITEM_CLOTH, 1, "精裁-布", "11", "11", NOW.minusHours(6)),
                op("op-2", ITEM_CLOTH, 2, "三边", "11", "0", null));

        Map<String, Object> stalled = service.stalledView(ops, ops.get(1), NOW);

        assertThat(stalled).containsKeys("kind", "state", "predecessor_operation_id", "predecessor_seq",
                "predecessor_done", "predecessor_done_at", "stalled_hours", "threshold_hours",
                "threshold_source");
        assertThat(stalled.get("predecessor_seq")).isEqualTo(1);
        assertThat(stalled.get("threshold_hours")).isEqualTo(THRESHOLD);
        assertThat(stalled.get("threshold_source"))
                .as("§6.4：「阈值从哪来」必须可解释（S3 兜底 = default）")
                .isEqualTo("default");
    }

    @Test
    @DisplayName("无待做工序（operation=null）⇒ stalled 键仍在、值全 null（不给假信号），阈值照样可见")
    void stalledViewWithoutChosenOperation() {
        Map<String, Object> stalled = service.stalledView(List.of(), null, NOW);

        assertThat(stalled.get("kind")).isNull();
        assertThat(stalled.get("state")).isNull();
        assertThat(stalled.get("stalled_hours")).isNull();
        assertThat(stalled.get("threshold_source")).isEqualTo("default");
    }

    // ============================================================ ④ 报表（§6.3）

    @Test
    @DisplayName("报表：按套 × 工序列出「没开工」，按 stalled_hours 降序，并给出三态计数与阈值来源（§6.3）")
    void reportListsStuckBySetAndOperationOrderedByHours() {
        stubReport(List.of(set(SET_ID, PO_ID, 14, SET_NO)), List.of(
                op("op-1", ITEM_CLOTH, 1, "精裁-布", "11", "11", NOW.minusHours(6)),
                op("op-2", ITEM_CLOTH, 2, "三边", "11", "0", null),          // 上道 6h 前完成 ⇒ 卡
                op("op-3", ITEM_CLOTH, 3, "定型", "11", "0", null),          // 立即前道 op-2 未完成 ⇒ 不卡
                op("op-4", ITEM_GAUZE, 1, "精裁-纱", "8", "8", NOW.minusHours(9)),
                op("op-5", ITEM_GAUZE, 2, "三边-纱", "8", "0", null),        // 上道 9h 前完成 ⇒ 卡
                op("op-6", ITEM_CLOTH, 4, "复烫", "11", "6", null),           // 做了一半 ⇒ 绝不进卡点表
                op("op-7", ITEM_CLOTH, 5, "包装", "11", "11", NOW.minusHours(1))));

        Map<String, Object> report = service.report(PO_ID, TENANT, NOW);

        assertThat(report.get("mode")).isEqualTo("A");
        assertThat(report.get("threshold_hours")).isEqualTo(THRESHOLD);
        assertThat(report.get("threshold_source")).isEqualTo("default");
        assertThat(scopeOf(report)).containsEntry("processing_order_id", PO_ID);
        assertThat(statesOf(report)).containsEntry("not_started", 3)
                .containsEntry("in_progress", 1).containsEntry("completed", 3);
        assertThat(report.get("stuck_total")).isEqualTo(2);
        List<Map<String, Object>> stuck = stuckOf(report);
        assertThat(stuck).extracting(r -> r.get("set_no")).containsExactly(SET_NO, SET_NO);
        assertThat(stuck).extracting(r -> operationOf(r).get("operation_id"))
                .as("§6.3：ORDER BY stalled_hours DESC（9h 的纱帘排前面）")
                .containsExactly("op-5", "op-2");
        assertThat(stuck.get(1)).containsEntry("stalled_hours", 6.0);
        assertThat(stuck).extracting(r -> r.get("kind"))
                .as("A 模式只判「没开工」那一种（裁定②-3）")
                .containsExactly(ProductionStuckPointService.KIND_NOT_STARTED,
                        ProductionStuckPointService.KIND_NOT_STARTED);
        assertThat((Double) stuck.get(0).get("stalled_hours")).isCloseTo(9.0, within(0.001));
        assertThat(predecessorOf(stuck.get(0))).containsEntry("done_at", NOW.minusHours(9));
        assertThat(positionOf(stuck.get(0))).containsEntry("order_item_id", ITEM_GAUZE);
        assertThat(operationOf(stuck.get(0)))
                .containsEntry("state", ProductionStuckPointService.STATE_NOT_STARTED)
                .containsEntry("seq", 2);
    }

    @Test
    @DisplayName("反向护栏（INNER JOIN 语义）：无套归属 / 套已软删的实例行**不进**报表（§6.3 的 JOIN 判据）")
    void reportExcludesRowsWithoutLiveSet() {
        ProcessingPositionOperation noSet = op("op-9", ITEM_CLOTH, 1, "精裁-布", "11", "0", null);
        noSet.setSetId(null);
        ProcessingPositionOperation deadSet = op("op-10", ITEM_CLOTH, 1, "精裁-布", "11", "0", null);
        deadSet.setSetId("set-deleted");
        // 有前道、等超阈值的行也已排除 ⇒ 报表必须为空（不是「恰好没有」）
        stubReport(List.of(set(SET_ID, PO_ID, 14, SET_NO)), List.of(
                op("op-1", ITEM_CLOTH, 1, "精裁-布", "11", "11", NOW.minusHours(6)),
                op("op-2", ITEM_CLOTH, 2, "三边", "11", "0", null),
                noSet, deadSet));

        Map<String, Object> report = service.report(null, TENANT, NOW);

        assertThat(report.get("stuck_total")).isEqualTo(1);
        assertThat(stuckOf(report)).extracting(r -> operationOf(r).get("operation_id"))
                .containsExactly("op-2");
        assertThat(statesOf(report)).containsEntry("not_started", 1)
                .as("无套归属 / 软删套的行**连计数都不进**（与报表同范围）");
        assertThat(scopeOf(report)).containsEntry("processing_order_id", null);
    }

    @Test
    @DisplayName("A 模式边界（裁定②-3）：只判「没开工」那一种 —— C 模式预留列**不参与**判据（连实体都没映射）")
    void reportJudgesOnlyNotStartedKind() {
        // op-1 = status 已是 in_progress 却从未报工（done_qty = 0）。按 issue #4776 逐字的「没开工」定义
        // （done_qty = 0 且 done_at IS NULL）它**仍是**没开工；而「开了没完」那一种卡点（§6.1 行②）
        // 是**仅 C**（§4.4 / §8 A3「C 只作预留」）⇒ A 模式判据**不读** C 模式列（设计 §4.3 D15；
        // 那三列连实体都没映射），本片不落 B/C 卡点。
        stubReport(List.of(set(SET_ID, PO_ID, 14, SET_NO)), List.of(
                startedOp("op-1", ITEM_CLOTH, 1),
                op("op-2", ITEM_CLOTH, 2, "三边", "11", "6", null)));

        Map<String, Object> report = service.report(PO_ID, TENANT, NOW);

        assertThat(report.get("mode")).isEqualTo("A");
        assertThat(statesOf(report)).containsEntry("not_started", 1).containsEntry("in_progress", 1);
        // 首道工序（seq=1）没有前道 ⇒ 不进卡点表（§6.3 ⚠️：首道的「等」是等派工，判据另立）
        assertThat(report.get("stuck_total")).isEqualTo(0);
        // 做了一半（op-2）**绝不**进卡点表（红证②的报表侧）
        assertThat(stuckOf(report)).isEmpty();
    }

    // ============================================================ 夹具

    private static ProcessingPositionOperation op(String id, String orderItemId, int seq,
                                                  String operationName, String qty, String doneQty,
                                                  OffsetDateTime doneAt) {
        return ProcessingPositionOperation.builder()
                .id(id)
                .tenantId(TENANT)
                .processingOrderId(PO_ID)
                .setId(SET_ID)
                .orderItemId(orderItemId)
                .positionKind(ITEM_CLOTH.equals(orderItemId) ? "布帘" : "纱帘")
                .positionName(ITEM_CLOTH.equals(orderItemId) ? "布艺遮光帘A" : "纱帘B")
                .seq(seq)
                .operationName(operationName)
                .unit("米")
                .qty(new BigDecimal(qty))
                .doneQty(doneQty == null ? null : new BigDecimal(doneQty))
                .doneAt(doneAt)
                .status(doneAt == null ? "pending" : "done")
                .createdAt(NOW.minusDays(3))
                .updatedAt(NOW.minusDays(3))
                .deleted(0)
                .build();
    }

    /**
     * C 模式预留态的实例行（{@code status='in_progress'}）。
     *
     * <p>🔴 {@code started_at} / {@code worker_id} / {@code worker_name} 这三列（V92 已建）
     * <b>连实体都没映射</b>（{@code ProcessingPositionOperation} 只有 {@code doneAt} 一个新增时序列）
     * ⇒ A 模式的卡点判据**在类型层就不可能读到它们** —— 这正是设计 §4.3 D15
     * 「C 模式默认关 ⇒ A 模式默认路径不读不写」的机械形态。</p>
     */
    private static ProcessingPositionOperation startedOp(String id, String orderItemId, int seq) {
        ProcessingPositionOperation op = op(id, orderItemId, seq, "定型", "11", "0", null);
        op.setStatus("in_progress");
        return op;
    }

    private static ProcessingOrderSet set(String id, String poId, int index, String setNo) {
        return ProcessingOrderSet.builder()
                .id(id).tenantId(TENANT).processingOrderId(poId).setIndex(index).setNo(setNo)
                .deleted(0).build();
    }

    private void stubReport(List<ProcessingOrderSet> sets, List<ProcessingPositionOperation> ops) {
        when(orderSetMapper.selectList(any())).thenReturn(sets);
        when(positionOperationMapper.selectList(any())).thenReturn(ops);
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> stuckOf(Map<String, Object> report) {
        return (List<Map<String, Object>>) report.get("stuck");
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> statesOf(Map<String, Object> report) {
        return (Map<String, Object>) report.get("states");
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> scopeOf(Map<String, Object> report) {
        return (Map<String, Object>) report.get("scope");
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> operationOf(Map<String, Object> row) {
        return (Map<String, Object>) row.get("operation");
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> predecessorOf(Map<String, Object> row) {
        return (Map<String, Object>) row.get("predecessor");
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> positionOf(Map<String, Object> row) {
        return (Map<String, Object>) row.get("position");
    }
}
