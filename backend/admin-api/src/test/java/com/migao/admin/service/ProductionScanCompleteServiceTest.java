// case_ids: PG-018, PG-039, PG-086, PG-093
package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingOrderSet;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProcessingSetPartToken;
import com.migao.admin.entity.ProductionWorkLog;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingOrderSetMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProcessingSetPartTokenMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import com.migao.admin.worker.WorkerIdentity;
import org.apache.ibatis.annotations.Update;
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
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.annotation.Transactional;

import java.lang.reflect.Method;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.api.Assertions.catchThrowable;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 扫码报工主闭环（切片 ②，issue #4698；设计 {@code docs/design/set-code-and-scan-loop.md} §4 / §5）。
 *
 * <p><b>本测试是行为断言，不是桩断言</b>：{@link ProductionService} 与 {@link ProductionScanService}
 * 用**真实对象**（只 mock Mapper）—— 解析 / 推断 / 上限校验 / 价态固化 / CAS 推进 / 幂等接线
 * 必须走**同一份**实现（mock 掉它们等于把被测口径换成桩：绿了但没跑）。</p>
 *
 * <p><b>红证（改前 / 注入实测，逐条输出见 PR body）</b>：</p>
 * <ol>
 *   <li><b>未确定工序却记账</b>：{@code OPERATION_AMBIGUOUS}（seq 重复）/ {@code SET_ALREADY_COMPLETED}
 *       / {@code SCAN_NEEDS_SELECTION}（旧码）/ {@code SET_HAS_NO_OPERATIONS}（存量单零关联工序行，
 *       issue #4871）四条路径**零写入** —— 删掉守卫 ⇒ 本文件红；</li>
 *   <li><b>中途失败留残留</b>：CAS 冲突（{@code rows=0}）⇒ 抛 + 释放幂等占位 + 不落结果快照，
 *       三处写入靠 {@code @Transactional}（下面用反射钉住注解与其 {@code rollbackFor}）—— 摘掉注解 ⇒ 红；</li>
 *   <li><b>同键重复计件</b>：占位失败 ⇒ 回放首次结果、{@code insert} 一次都不发生 —— 跳过占位 ⇒ 红；</li>
 *   <li><b>未定价按 0 计入</b>：实例单价 NULL ⇒ 报工行 {@code price_state=unpriced} 且
 *       {@code unit_price=null}（**不是** 0）—— 写死 {@code priced}/折 0 ⇒ 红；</li>
 *   <li><b>计件归属取 body</b>：body 里塞 {@code worker_id=冒领} ⇒ 落库仍是 session 解出的工人
 *       （issue #4733 的复核，本切片**不**新开第二条身份来源）—— 改成读 body ⇒ 红。</li>
 *   <li><b>「改前真写了 {@code work_logs}」</b>（#4792 的**承重证据**）：旧写入口
 *       {@link ProductionService#report}（= 工人页改前走的
 *       {@code /orders/{orderId}/operations/{operationId}/report}）**不接收码**、
 *       只按 {@code (orderId, operationId)} 定位 ⇒ 拿布帘的码去报纱帘的工序**照样落库**
 *       —— 这就是「防呆④ 在工人页不生效」的实测形态；改成
 *       {@link ProductionScanCompleteService#complete}（按 token 定位部位）后才 422。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("ProductionScanCompleteService 扫码完成主闭环（切片 ②）")
class ProductionScanCompleteServiceTest {

    private static final Long TENANT = 1L;
    private static final String ORDER_ID = "order-1";
    private static final String PO_ID = "po-1";
    private static final String PO_NO = "CSO260915-02615";
    private static final String SET_ID = "set-14";
    private static final String SET_NO = PO_NO + "-014";
    private static final String ITEM_CLOTH = "oi-cloth";
    private static final String ITEM_GAUZE = "oi-gauze";
    private static final String OP_CLOTH = "op-cloth-1";
    private static final String OP_GAUZE = "op-gauze-1";
    /** 新码（套 × 部位）的码值；刻意用非密钥形态字面量（32 位 hex 会被 gitleaks 误判为密钥）。 */
    private static final String TOKEN = "scan-token-4698b";
    private static final String OLD_CODE = "legacy-scan-code-4698b";
    private static final WorkerIdentity WORKER =
            new WorkerIdentity("w-1", "张三", WorkerIdentity.SOURCE_SERVER_SESSION, "sess-1");

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
    /** 批次账（issue #7647）：裁剪报工的「核对 + 纠偏」腿；其余工序不该碰它（never 断言钉住）。 */
    @Mock
    private StockBatchConsumptionService stockBatchConsumptionService;
    /** 工人档案（issue #7749）：写面按它读「绑定的工序」；默认 null = 未绑定（旧行为逐字不变）。 */
    @Mock
    private WorkerAdminService workerAdminService;
    /** 成品入库（issue #7845）：打包工序报工 ⇒ 这一件进成品仓；其它工序不得触达。 */
    @Mock
    private FinishedGoodsService finishedGoodsService;

    private ProductionService productionService;
    private ProductionScanService scanService;
    private ProductionScanCompleteService service;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        productionService = new ProductionService(processingOrderMapper, positionOperationMapper,
                workLogMapper, orderMapper, orderItemMapper, clientRequestIdService);
        // 卡点判据（切片 ③，issue #4776）：真实对象（只 mock Mapper），与生产装配同源
        ProductionStuckPointService stuckPointService = new ProductionStuckPointService(
                productionService, positionOperationMapper, orderSetMapper, 4.0);
        // 套件读面（issue #5247）：与生产装配同源（真实对象，只 mock Mapper）——
        // `set_overview` 的聚合已搬进它，与商家/agent 读面共用同一份。
        scanService = new ProductionScanService(setPartTokenMapper, orderSetMapper,
                processingOrderMapper, operationQueryService, productionService, stuckPointService,
                new ProcessingSetReadService(orderSetMapper, positionOperationMapper, orderItemMapper,
                        processingOrderMapper, orderMapper, productionService),
                orderMapper);
        service = new ProductionScanCompleteService(scanService, productionService, clientRequestIdService,
                workerAdminService);
        // 批次账是**字段注入**（构造签名被 27 处既有测试直接装配，不能加参数）⇒ 测试里同样按字段装。
        // 默认 mock 的 `tracksBatches` 返回 false ⇒ 非「裁剪」工序与存量商品行为逐字不变。
        ReflectionTestUtils.setField(productionService, "stockBatchConsumptionService", stockBatchConsumptionService);
        // 成品入库是**字段注入**（构造签名被既有测试直接装配）⇒ 测试里同样按字段装（issue #7845）
        ReflectionTestUtils.setField(service, "finishedGoodsService", finishedGoodsService);

        // 幂等占位：默认「首次」（claim=true）。重复提交的用例单独把它改成 false。
        when(clientRequestIdService.claim(any(), any(), any())).thenReturn(true);
        when(operationQueryService.operationsByName(TENANT)).thenReturn(Map.of());
        when(setPartTokenMapper.selectOne(any())).thenReturn(partToken(TOKEN));
        when(orderSetMapper.selectById(SET_ID)).thenReturn(orderSet());
        when(processingOrderMapper.selectById(PO_ID)).thenReturn(processingOrder());
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder());
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order());
        when(workLogMapper.insert(any(ProductionWorkLog.class))).thenReturn(1);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ============================================================ ① A 模式闭环：一次扫码 = 完工

    @Test
    @DisplayName("新码 + 推断出唯一工序 ⇒ 一次事务落「明细 + CAS + done_at」，回执带套号/部位/下一道")
    void completesInOneTransaction() {
        stubPending(Set_OP_CLOTH_DONE_0);

        Map<String, Object> result = service.complete(body(TOKEN), TENANT, "key-1", WORKER);

        ProductionWorkLog log = capturedWorkLog();
        assertThat(log.getOperationId()).isEqualTo(OP_CLOTH);
        // 数量默认 = 剩余应做（首次报工 = 应做数量 11）
        assertThat(log.getQty()).isEqualByComparingTo("11");
        assertThat(log.getQualifiedQty()).isEqualByComparingTo("11");
        assertThat(result.get("done_qty")).isEqualTo(new BigDecimal("11"));
        assertThat(result.get("status")).isEqualTo("done");
        assertThat(result.get("set_no")).isEqualTo(SET_NO);
        assertThat(result.get("rerouted")).isEqualTo(false);
        // 一次事务的三处写入：明细 → CAS → done_at
        verify(positionOperationMapper).advanceDoneQtyIfUnchanged(
                eq(OP_CLOTH), eq(TENANT), eq(BigDecimal.ZERO), eq("pending"),
                eq(new BigDecimal("11")), any(OffsetDateTime.class));
        verify(positionOperationMapper).recordCompletionIfDone(
                eq(OP_CLOTH), eq(TENANT), any(OffsetDateTime.class));
        // 占位成功 ⇒ 落结果快照（同键可回放）
        verify(clientRequestIdService).complete(eq(TENANT), eq("key-1"), any());
    }

    @Test
    @DisplayName("部分报工（6/11 米）仍可继续：不落 done_at、status 置 done、进度按实际累加")
    void partialReportStillWorksWithoutDoneAt() {
        stubPending(Set_OP_CLOTH_DONE_0);
        Map<String, Object> payload = body(TOKEN);
        payload.put("qty", new BigDecimal("6"));

        Map<String, Object> result = service.complete(payload, TENANT, "key-1", WORKER);

        assertThat(capturedWorkLog().getQty()).isEqualByComparingTo("6");
        assertThat(result.get("done_qty")).isEqualTo(new BigDecimal("6"));
        // 🔴 没做完 ⇒ 不是完工时刻（done_at 只记「真正做完」那一刻；切片 ① 登记的偏离：
        // 部分报工也把 status 置 done，但 isDone 判据是 done_qty ≥ qty）
        verify(positionOperationMapper, never()).recordCompletionIfDone(any(), any(), any());
    }

    @Test
    @DisplayName("续报默认 = 剩余应做（已报 6/11 ⇒ 默认 5），不是设计字面的「应做 11」")
    void defaultQtyIsRemainingNotPlanned() {
        stubPending(op(OP_CLOTH, ITEM_CLOTH, 1, "精裁-布", "11", "6", new BigDecimal("3.50")));

        Map<String, Object> result = service.complete(body(TOKEN), TENANT, "key-1", WORKER);

        assertThat(capturedWorkLog().getQty()).isEqualByComparingTo("5");
        assertThat(result.get("done_qty")).isEqualTo(new BigDecimal("11"));
        verify(positionOperationMapper).recordCompletionIfDone(eq(OP_CLOTH), eq(TENANT), any());
    }

    @Test
    @DisplayName("越站**不拦**（issue #4694）：前道未完成时，扫同一部位更靠后的工序照常记账")
    void laterOperationIsNotBlockedByPendingPredecessor() {
        // seq 1（前道）未完成 + seq 2（一键改指到它）—— 越站闸门已删 ⇒ 必须成功
        stubPending(List.of(
                op(OP_CLOTH, ITEM_CLOTH, 1, "精裁-布", "11", "0", new BigDecimal("3.50")),
                op(OP_GAUZE, ITEM_CLOTH, 2, "定型-布", "11", "0", new BigDecimal("2.00"))));

        Map<String, Object> result = service.complete(picked(TOKEN, OP_GAUZE), TENANT, "key-1", WORKER);

        assertThat(result.get("operation_id")).isEqualTo(OP_GAUZE);
        assertThat(capturedWorkLog().getOperationId()).isEqualTo(OP_GAUZE);
        verify(positionOperationMapper).advanceDoneQtyIfUnchanged(eq(OP_GAUZE), eq(TENANT),
                eq(BigDecimal.ZERO), eq("pending"), eq(new BigDecimal("11")), any(OffsetDateTime.class));
    }

    @Test
    @DisplayName("套级回落（设计 §3.2 ②）：本部位干完 ⇒ 落到套级工序（打卷），回执 rerouted=true")
    void setLevelFallbackIsReportedAsRerouted() {
        String setOpId = "op-set-roll";
        ProcessingPositionOperation setOp = op(setOpId, ITEM_CLOTH, 9, "打卷", "1", "0",
                new BigDecimal("1.00"));
        stubPending(List.of(
                op(OP_CLOTH, ITEM_CLOTH, 1, "精裁-布", "11", "11", new BigDecimal("3.50")),
                setOp));
        when(positionOperationMapper.selectById(setOpId)).thenReturn(setOp);
        // 套级判据 = 工序库的 scope（逐字取库，不硬编码工序名）
        when(operationQueryService.operationsByName(TENANT)).thenReturn(Map.of("打卷", Map.of("scope", "set")));
        // 扫的是**纱帘**的码（该部位无待做）⇒ 套级回落
        when(setPartTokenMapper.selectOne(any())).thenReturn(partTokenOf(TOKEN, ITEM_GAUZE));

        Map<String, Object> result = service.complete(body(TOKEN), TENANT, "key-1", WORKER);

        assertThat(result.get("operation_id")).isEqualTo(setOpId);
        assertThat(result.get("rerouted")).isEqualTo(true);
        assertThat(capturedWorkLog().getOperationId()).isEqualTo(setOpId);
    }

    // ============================================================ ② 未确定工序 ⇒ 拒绝记账

    @Test
    @DisplayName("🔴 未确定①：seq 重复（脏数据）⇒ 422 OPERATION_AMBIGUOUS，且零写入")
    void ambiguousOperationIsRejectedWithoutWriting() {
        stubPending(List.of(
                op(OP_CLOTH, ITEM_CLOTH, 6, "定型-布", "11", "0", new BigDecimal("3.50")),
                op(OP_GAUZE, ITEM_CLOTH, 6, "打卷-布", "11", "0", new BigDecimal("1.00"))));

        assertThatThrownBy(() -> service.complete(body(TOKEN), TENANT, "key-1", WORKER))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("无法确定本次报哪一道");

        assertNothingWritten();
    }

    @Test
    @DisplayName("🔴 未确定②：本套工序都已完成（推断零道）⇒ 409 SET_ALREADY_COMPLETED，且零写入")
    void alreadyCompletedSetIsRejectedWithoutWriting() {
        stubPending(op(OP_CLOTH, ITEM_CLOTH, 1, "精裁-布", "11", "11", new BigDecimal("3.50")));

        assertThatThrownBy(() -> service.complete(body(TOKEN), TENANT, "key-1", WORKER))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("没有可报的工序")
                // 🔴 契约面（issue #4810）：`@DisplayName` 只是**文案**，不是断言 —— 码与状态码在这里钉死
                // （设计 §5.3.1「拒绝码 = 契约面」）。红证：把源码里的 409 改成别的值 ⇒ 本断言红。
                .hasFieldOrPropertyWithValue("code", "SET_ALREADY_COMPLETED")
                .hasFieldOrPropertyWithValue("httpStatus", 409);

        assertNothingWritten();
    }

    /**
     * 🔴 <b>质检工序没有报工动作（issue #7186）</b>：用户 2026-10-18 逐字「质检员不需要报工这个动作，
     * 只需要有一个质检动作，完成判定后自动报工，然后自动生成质检流水」。
     *
     * <p>判据与逐道报工入口<b>同一份</b>（{@code DocumentOperationLinkage#rejectManualReport}）——
     * 本测试只钉「扫码闭环这条写入口也拦得住」：只留一道 pending 的「质检」⇒ 推断会选中它 ⇒
     * 记账前必须 422，且<b>零写入</b>（不落报工明细 / 不推进做工数量 / 释放幂等占位）。</p>
     *
     * <p>红证：摘掉 {@code doComplete} 里那行 {@code DocumentOperationLinkage.rejectManualReport(op)}
     * ⇒ 本测试变成「报工成功」⇒ 断言红（同一次注入在 {@code ProductionReportQualityGuardTest}
     * 的另一条入口上同样会红）。</p>
     */
    @Test
    @DisplayName("🔴 质检工序没有报工动作（issue #7186）：扫码完成 ⇒ 422 指向质检判定，且零写入")
    void qualityOperationIsNotReportable() {
        stubPending(op(OP_CLOTH, ITEM_CLOTH, 3, "质检", "1", "0", new BigDecimal("1.50")));

        assertThatThrownBy(() -> service.complete(body(TOKEN), TENANT, "key-1", WORKER))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("质检")
                .hasMessageContaining("返工")
                .hasFieldOrPropertyWithValue("code", "VALIDATION_ERROR")
                .hasFieldOrPropertyWithValue("httpStatus", 422);

        assertNothingWritten();
    }

    /**
     * 🔴 <b>存量加工单的实测形态（issue #4871）</b>：部位码能印、短链能跳（302 + 工人端落地页），
     * 但该套<b>一行工序实例都没关联</b>（存量工序行的 {@code set_id} / {@code set_no} 全 NULL ——
     * V92 按「套的部位清单」{@code order_item_id} 回填，而存量行多为 NULL ⇒ 挂不上）
     * ⇒ 解析面 {@code set_progress = {total: 0, done: 0}} 且 {@code completed = true}。
     *
     * <p>🔴 病根：{@code completed} 键 = {@code chosen == null} —— <b>「本套零关联工序行」与
     * 「本套真做完了」共用这一个值</b>（{@code ProductionScanService#setPositionView}）⇒ 记账侧
     * 只读 {@code completed} 就<b>分不出</b>这两态，回执于是说出<b>假陈述</b>
     * 「本套（…）的工序都已完成」，而真相是「一行都没关联上」。判据（issue #4871 验收标准逐字）：
     * <b>{@code total == 0} 与 {@code done == total} 必须是两个分支，不能共用同一句</b>。</p>
     *
     * <p>夹具与真实读面<b>同源</b>（不另造 {@code set_progress} 桩字段）：{@code set_progress} 由
     * {@code ProductionService#progressOf} 按 {@code ProcessingSetReadService#listSetOperations}
     * 的结果算出（本类只 mock Mapper）⇒ <b>空列表</b>就是「零关联工序行」本身。</p>
     */
    @Test
    @DisplayName("🔴 存量单（本套零关联工序行，total=0）⇒ 409 SET_HAS_NO_OPERATIONS，措辞不得说「工序都已完成」，且零写入")
    void setWithoutOperationRowsIsRejectedWithHonestMessage() {
        stubSetWithoutOperations();

        Throwable thrown = catchThrowable(() -> service.complete(body(TOKEN), TENANT, "key-1", WORKER));

        // 🔴 契约面（issue #4810 的口径：`@DisplayName` 只是文案，码与状态码才是断言）：
        // 与真「已完成」**不是同一个码** —— 两个分支共用同一句/同一个码 ⇒ 本断言红。
        assertThat(thrown)
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", "SET_HAS_NO_OPERATIONS")
                .hasFieldOrPropertyWithValue("httpStatus", 409);
        // 文案面（本单的靶心）：说**真实**的原因（零关联工序行），绝不出现真「已完成」那句假陈述。
        // 改前这句逐字是「本套（…）的工序都已完成，没有可报的工序（本次未记账）」⇒ 本断言红。
        assertThat(thrown.getMessage())
                .contains("没有关联工序行")
                .doesNotContain("都已完成");
        // 诚实措辞的第二半 = 可行动：说清「按部位逐道报工 / 重新实例化本单」两条出路。
        assertThat(((BusinessException) thrown).getSuggestion())
                .contains("逐道报工")
                .contains("重新实例化");

        assertNothingWritten();
    }

    @Test
    @DisplayName("🔴 推断之后被报满（并发窗口）⇒ 409 OPERATION_ALREADY_ADVANCED，且零写入")
    void operationFilledBetweenResolveAndChargeIsRejected() {
        // 并发窗口的可执行形态（issue #4810 补，对应设计 §5.3.1 的落点 (b)）：
        // **推断读**（`selectList`，走 `ProductionScanService#listSetOperations`）看到「未完成 6/11 米」
        // ⇒ 工序确定；而**记账前重读**（`selectById`，走 `ProductionService#requireActiveOperation`）
        // 同一行已被别人报满 11/11 ⇒ `plannedRemaining(op) ≤ 0` ⇒ 必须拒绝，绝不记一笔 0 米的账。
        stubPending(op(OP_CLOTH, ITEM_CLOTH, 1, "精裁-布", "11", "6", new BigDecimal("3.50")));
        when(positionOperationMapper.selectById(OP_CLOTH))
                .thenReturn(op(OP_CLOTH, ITEM_CLOTH, 1, "精裁-布", "11", "11", new BigDecimal("3.50")));

        assertThatThrownBy(() -> service.complete(body(TOKEN), TENANT, "key-1", WORKER))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("已报满")
                .hasFieldOrPropertyWithValue("code", "OPERATION_ALREADY_ADVANCED")
                .hasFieldOrPropertyWithValue("httpStatus", 409);

        assertNothingWritten();
    }

    @Test
    @DisplayName("🔴 旧码降级（加工单级）⇒ 422 SCAN_NEEDS_SELECTION：绝不默认取第 1 套，且零写入")
    void legacyCodeIsRejectedWithoutPickingFirstSet() {
        when(setPartTokenMapper.selectOne(any())).thenReturn(null); // 新码未命中 ⇒ 回落四形态
        when(orderMapper.selectById(OLD_CODE)).thenReturn(order()); // 旧码命中既有四形态
        stubPending(Set_OP_CLOTH_DONE_0);

        assertThatThrownBy(() -> service.complete(body(OLD_CODE), TENANT, "key-1", WORKER))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("旧码")
                // 🔴 契约面（issue #4810）：码 + 状态码逐字钉住（设计 §5.3.1）；账本逐字同款
                .hasFieldOrPropertyWithValue("code", "SCAN_NEEDS_SELECTION")
                .hasFieldOrPropertyWithValue("httpStatus", 422);

        assertNothingWritten();
    }

    // ============================================================ ③ 领活语义（issue #4967）

    /**
     * 🔴 <b>领活三列（issue #4967）</b>：扫码 = 开工 / 领活 ⇒ {@code started_at} /
     * {@code worker_id} / {@code worker_name} 在**默认路径**被写入（改前这三列是「C 模式预留，
     * A 模式默认路径不读不写」⇒ 本断言改前必红）。
     *
     * <p>「谁在什么时候领走了这道活」是用户逐字诉求的落点；真库侧另有
     * {@code ProductionScanClaimRealDbTest} 钉住列真的落进了 PG（本类只钉调用面）。</p>
     */
    @Test
    @DisplayName("🔴 扫码 = 开工/领活：默认路径写 started_at + worker_id + worker_name（改前为 NULL ⇒ 必红）")
    void claimWritesStartedAtAndWorkerOnDefaultPath() {
        stubPending(Set_OP_CLOTH_DONE_0);

        service.complete(body(TOKEN), TENANT, "key-1", WORKER);

        // 领活时刻与领活人（与报工明细**同源**：都来自服务端解出的 identity）
        verify(positionOperationMapper).recordReporter(
                eq(OP_CLOTH), eq(TENANT), eq("w-1"), eq("张三"),
                any(OffsetDateTime.class), any(OffsetDateTime.class));
    }

    @Test
    @DisplayName("领活时刻与完工时刻**同一次**落笔（同一事务，不是两次独立写）")
    void claimAndCompletionAreWrittenInTheSameTransaction() {
        stubPending(Set_OP_CLOTH_DONE_0);

        service.complete(body(TOKEN), TENANT, "key-1", WORKER);

        // 同一次 complete ⇒ 身份/开工（recordReporter）与完工（recordCompletionIfDone）**各恰好一次**
        // —— 判据是「不重复写」（两条路径共用 applyReport 的**同一份**记账核，
        // 若在 applyScanComplete 里再加一次就会写两遍）。
        verify(positionOperationMapper, times(1)).recordReporter(
                any(), any(), any(), any(), any(), any());
        verify(positionOperationMapper, times(1)).recordCompletionIfDone(
                eq(OP_CLOTH), eq(TENANT), any(OffsetDateTime.class));
    }

    // ============================================================ ④ 按套展示工序细节（issue #4967 交付物 2）

    /**
     * 🔴 <b>解析响应必须带 {@code set_overview}</b>（issue #4967 交付物 2）：
     * 本套 → 部位 → 工序明细（逻辑名 / 应做数量+单位 / 单价 / 状态 / 已报数量）。
     *
     * <p>判据是**形状 + 值**，不是「有个键」：改前解析响应里没有这个键 ⇒ 本测试必红
     * （读 {@code result.get("set_overview")} 得 null）。</p>
     */
    @Test
    @DisplayName("🔴 解析响应含 set_overview：本套各部位工序明细（逻辑名/应做+单位/单价/状态/已报）")
    @SuppressWarnings("unchecked")
    void resolveCarriesSetOverviewWithOperationDetails() {
        stubPending(List.of(
                op(OP_CLOTH, ITEM_CLOTH, 1, "精裁-布", "11", "0", new BigDecimal("3.50")),
                op(OP_GAUZE, ITEM_GAUZE, 2, "定型-纱", "4", "4", new BigDecimal("2.00"))));

        Map<String, Object> result = service.complete(body(TOKEN), TENANT, "key-1", WORKER);

        Map<String, Object> overview = (Map<String, Object>) result.get("set_overview");
        assertThat(overview).as("解析响应必须带本套工序总览（改前没有这个键 ⇒ 必红）").isNotNull();
        assertThat(overview.get("set_no")).isEqualTo(SET_NO);
        assertThat(overview.get("set_index")).isEqualTo(14);

        List<Map<String, Object>> positions = (List<Map<String, Object>>) overview.get("positions");
        assertThat(positions).as("本套两个部位（布帘 / 纱帘）各一组").hasSize(2);

        Map<String, Object> cloth = positions.get(0);
        assertThat(cloth.get("order_item_id")).isEqualTo(ITEM_CLOTH);
        assertThat(cloth.get("position_name")).isEqualTo("布艺遮光帘A");
        List<Map<String, Object>> clothOps = (List<Map<String, Object>>) cloth.get("operations");
        assertThat(clothOps).as("该部位的工序明细").hasSize(1);
        Map<String, Object> first = clothOps.get(0);
        // 逐键钉住「工人一眼看到的那几列」
        assertThat(first.get("operation_id")).isEqualTo(OP_CLOTH);
        assertThat(first.get("logical_name")).isEqualTo("精裁");   // 逻辑名（去掉 -布 后缀）
        assertThat(first.get("position")).isEqualTo("布帘");
        assertThat(first.get("qty")).isEqualTo(new BigDecimal("11"));
        assertThat(first.get("unit")).isEqualTo("米");
        assertThat(first.get("unit_price")).isEqualTo(new BigDecimal("3.50"));
        assertThat(first.get("status")).isEqualTo("pending");
        assertThat(first.get("done_qty")).isEqualTo(BigDecimal.ZERO);

        // 已完成的那道**也在**（工人要看到「这一套还有哪几道没做」⇒ 不能只列待做）
        Map<String, Object> gauze = positions.get(1);
        Map<String, Object> done = ((List<Map<String, Object>>) gauze.get("operations")).get(0);
        assertThat(done.get("operation_id")).isEqualTo(OP_GAUZE);
        assertThat(done.get("done_qty")).isEqualTo(new BigDecimal("4"));
    }

    @Test
    @DisplayName("set_overview 的 unit_price 为 null ⇒ 原样 null（未定价 ≠ 0 元，V90/#4696，读面不折 0）")
    @SuppressWarnings("unchecked")
    void setOverviewKeepsUnpricedAsNull() {
        stubPending(op(OP_CLOTH, ITEM_CLOTH, 1, "精裁-布", "11", "0", null));

        Map<String, Object> result = service.complete(body(TOKEN), TENANT, "key-1", WORKER);

        Map<String, Object> overview = (Map<String, Object>) result.get("set_overview");
        Map<String, Object> position = ((List<Map<String, Object>>) overview.get("positions")).get(0);
        Map<String, Object> operation = ((List<Map<String, Object>>) position.get("operations")).get(0);
        assertThat(operation).containsEntry("unit_price", null);
    }

    @Test
    @DisplayName("旧码降级形态不含 set_overview（判不出是哪一套 ⇒ 不知道就是不知道，不猜）")
    void degradedViewHasNoSetOverview() {
        when(setPartTokenMapper.selectOne(any())).thenReturn(null);
        when(orderMapper.selectById(OLD_CODE)).thenReturn(order());

        Map<String, Object> scan = scanService.resolve(OLD_CODE, null, null, null, TENANT);

        assertThat(scan.get("granularity")).isEqualTo("order");
        assertThat(scan).as("旧码降级判不出套 ⇒ 不得凭空造一份总览")
                .doesNotContainKey("set_overview");
    }

    @Test
    @DisplayName("🔴 旧码收口（issue #4794）：选完套 + 部位（body 带 set_id + order_item_id）⇒ **能报工**，一次事务记账")
    void legacyCodeWithSelectionCompletesInOneTransaction() {
        stubLegacyScan();

        Map<String, Object> payload = body(OLD_CODE);
        payload.put("set_id", SET_ID);
        payload.put("order_item_id", ITEM_CLOTH);

        Map<String, Object> result = service.complete(payload, TENANT, "key-1", WORKER);

        // 改前：set_id/order_item_id 不被读 ⇒ 降级形态 ⇒ 422 SCAN_NEEDS_SELECTION（本测试必红）
        ProductionWorkLog log = capturedWorkLog();
        assertThat(log.getOperationId()).isEqualTo(OP_CLOTH);
        assertThat(log.getWorkerId()).isEqualTo("w-1");
        assertThat(result.get("set_no")).isEqualTo(SET_NO);
        assertThat(result.get("position")).isNotNull();
        // 一次事务的三处写入：明细 → CAS → done_at（与**新码**主路径**同一份**实现）
        verify(positionOperationMapper).advanceDoneQtyIfUnchanged(
                eq(OP_CLOTH), eq(TENANT), eq(BigDecimal.ZERO), eq("pending"),
                eq(new BigDecimal("11")), any(OffsetDateTime.class));
        verify(positionOperationMapper).recordCompletionIfDone(
                eq(OP_CLOTH), eq(TENANT), any(OffsetDateTime.class));
        verify(clientRequestIdService).complete(eq(TENANT), eq("key-1"), any());
    }

    @Test
    @DisplayName("🔴 旧码收口：只选一半（缺 order_item_id）⇒ 仍 422 SCAN_NEEDS_SELECTION，且零写入")
    void legacyCodeWithPartialSelectionIsStillRejected() {
        stubLegacyScan();
        Map<String, Object> payload = body(OLD_CODE);
        payload.put("set_id", SET_ID);

        assertThatThrownBy(() -> service.complete(payload, TENANT, "key-1", WORKER))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("旧码")
                // 🔴 只选一半 ⇒ **仍**是 422 `SCAN_NEEDS_SELECTION`（不是另一条码）：两个键都非空才走选择路径
                .hasFieldOrPropertyWithValue("code", "SCAN_NEEDS_SELECTION")
                .hasFieldOrPropertyWithValue("httpStatus", 422);

        assertNothingWritten();
    }

    @Test
    @DisplayName("🔴 旧码收口（越权面）：所选套不属于本次扫码的加工单 ⇒ 422，且零写入")
    void legacySelectionOutsideScannedOrderIsRejected() {
        stubLegacyScan();
        when(orderSetMapper.selectById("set-other")).thenReturn(ProcessingOrderSet.builder()
                .id("set-other").tenantId(TENANT).processingOrderId("po-other").setIndex(1)
                .setNo("CSO-OTHER-001").deleted(0).build());
        Map<String, Object> payload = body(OLD_CODE);
        payload.put("set_id", "set-other");
        payload.put("order_item_id", ITEM_CLOTH);

        assertThatThrownBy(() -> service.complete(payload, TENANT, "key-1", WORKER))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不属于本次扫码的加工单");

        assertNothingWritten();
    }

    @Test
    @DisplayName("🔴 反向护栏：**新码**主路径即使被硬塞 set_id / order_item_id 也**不读**（零影响）")
    void newCodePathIgnoresStuffedSelection() {
        // 新码指向「布帘」；body 里硬塞一个**别的**套 + 别的部位 ⇒ 仍按码给的部位推断
        stubPending(List.of(
                op(OP_CLOTH, ITEM_CLOTH, 1, "精裁-布", "11", "0", new BigDecimal("3.50")),
                op(OP_GAUZE, ITEM_GAUZE, 1, "精裁-纱", "8", "0", new BigDecimal("2.00"))));
        Map<String, Object> payload = body(TOKEN);
        payload.put("set_id", "set-hacked");
        payload.put("order_item_id", ITEM_GAUZE);

        Map<String, Object> result = service.complete(payload, TENANT, "key-1", WORKER);

        assertThat(result.get("operation_id")).isEqualTo(OP_CLOTH);
        assertThat(capturedWorkLog().getOperationId()).isEqualTo(OP_CLOTH);
    }

    @Test
    @DisplayName("🔴 旧码收口 + 防呆④：所选部位之外的工序（一键改）⇒ 422 OPERATION_NOT_IN_SCAN_TARGET，零写入")
    void legacySelectionCrossPositionPickIsRejected() {
        stubLegacyScan();
        Map<String, Object> payload = body(OLD_CODE);
        payload.put("set_id", SET_ID);
        payload.put("order_item_id", ITEM_CLOTH);
        payload.put("operation_id", OP_GAUZE); // 属**另一个**部位

        assertThatThrownBy(() -> service.complete(payload, TENANT, "key-1", WORKER))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不属于本次扫码的部位");

        assertNothingWritten();
    }

    @Test
    @DisplayName("跨部位报工被拒（防呆④）：扫布帘的码却指定纱帘的工序 ⇒ 422，且零写入")
    void crossPositionPickIsRejected() {
        stubPending(List.of(
                op(OP_CLOTH, ITEM_CLOTH, 1, "精裁-布", "11", "0", new BigDecimal("3.50")),
                op(OP_GAUZE, ITEM_GAUZE, 1, "精裁-纱", "8", "0", new BigDecimal("2.00"))));

        assertThatThrownBy(() -> service.complete(picked(TOKEN, OP_GAUZE), TENANT, "key-1", WORKER))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不属于本次扫码的部位");

        assertNothingWritten();
    }

    @Test
    @DisplayName("🔴 承重证据（改前真写了 work_logs）：旧写入口 `/report` 无部位判据 —— 拿布帘的码报纱帘的工序照样落库")
    void legacyReportPathAcceptsCrossPositionAndWritesWorkLog() {
        // 同一组夹具：布帘（扫到的码指向它）+ 纱帘（另**一道**工序，属**另一个**部位）
        stubPending(List.of(
                op(OP_CLOTH, ITEM_CLOTH, 1, "精裁-布", "11", "0", new BigDecimal("3.50")),
                op(OP_GAUZE, ITEM_GAUZE, 1, "精裁-纱", "8", "0", new BigDecimal("2.00"))));

        // 旧入口（工人页改前走的那条）：URL 里显式给 orderId + operationId（**纱帘**那道），
        // 🔴 **不带任何码** ⇒ 服务端无从判定「这次扫的是哪个部位」，防呆④ 在这条路径上**不存在**。
        Map<String, Object> legacyBody = body(TOKEN);
        legacyBody.put("qty", new BigDecimal("8"));
        legacyBody.put("qualified_qty", new BigDecimal("8"));
        legacyBody.put("work_type", "normal");

        Map<String, Object> result = productionService.report(
                ORDER_ID, OP_GAUZE, legacyBody, TENANT, "key-legacy", WORKER);

        // 真的写进去了：明细落的是**纱帘**那道（不是扫到的布帘），计件归属 = session 解的工人
        ProductionWorkLog log = capturedWorkLog();
        assertThat(log.getOperationId()).isEqualTo(OP_GAUZE);
        assertThat(log.getQualifiedQty()).isEqualByComparingTo("8");
        assertThat(log.getUnitPrice()).isEqualByComparingTo("2.00");
        assertThat(log.getWorkerId()).isEqualTo("w-1");
        assertThat(result.get("done_qty")).isEqualTo(new BigDecimal("8"));

        // 对照（同一个文件里紧邻的 crossPositionPickIsRejected）：改走 scan/complete ⇒ 422 + 零写入
        // ⇒ 两条合起来才是「工人页改走 scan/complete 才让防呆④ 生效」的完整证据链。
    }

    // ============================================================ ③ 幂等：同键不重复计件

    @Test
    @DisplayName("🔴 同键重复提交 ⇒ 不重复计件：回放首次结果（replayed=true），insert 一次都不发生")
    void sameIdempotencyKeyReplaysWithoutSecondWrite() {
        Map<String, Object> first = new LinkedHashMap<>();
        first.put("operation_id", OP_CLOTH);
        first.put("done_qty", new BigDecimal("11"));
        when(clientRequestIdService.claim(any(), any(), any())).thenReturn(false);
        when(clientRequestIdService.replay(eq(TENANT), eq("key-1"), any()))
                .thenReturn(Optional.of(first));

        Map<String, Object> replayed = service.complete(body(TOKEN), TENANT, "key-1", WORKER);

        assertThat(replayed.get("replayed")).isEqualTo(Boolean.TRUE);
        assertThat(replayed.get("done_qty")).isEqualTo(new BigDecimal("11"));
        // 同键重复 = **回放**，不是失败：三处写入一个都不发生，且**不释放**占位（占位要留给回放）
        assertNoWrites();
        verify(clientRequestIdService, never()).complete(any(), any(), any());
        verify(clientRequestIdService, never()).discard(any(), any());
    }

    // ============================================================ ④ 计件：未定价 ≠ 0 + 身份来自 session

    @Test
    @DisplayName("🔴 未定价（实例单价 NULL）⇒ price_state=unpriced 且 unit_price=null（不是 0）")
    void unpricedOperationIsMarkedNotZeroed() {
        stubPending(op(OP_CLOTH, ITEM_CLOTH, 1, "精裁-布", "11", "0", null));

        service.complete(body(TOKEN), TENANT, "key-1", WORKER);

        ProductionWorkLog log = capturedWorkLog();
        assertThat(log.getPriceState()).isEqualTo(ProductionService.PRICE_STATE_UNPRICED);
        assertThat(log.getUnitPrice()).isNull();
    }

    @Test
    @DisplayName("🔴 计件归属由服务端解（#4733 复核）：body 里塞 worker_id=冒领 也改不了落库的人")
    void identityComesFromSessionNotFromBody() {
        stubPending(Set_OP_CLOTH_DONE_0);
        Map<String, Object> payload = body(TOKEN);
        payload.put("worker_id", "attacker-9");
        payload.put("worker_name", "冒领");

        Map<String, Object> result = service.complete(payload, TENANT, "key-1", WORKER);

        assertThat(capturedWorkLog().getWorkerId()).isEqualTo("w-1");
        assertThat(capturedWorkLog().getWorkerName()).isEqualTo("张三");
        assertThat(result.get("identity_source")).isEqualTo(WorkerIdentity.SOURCE_SERVER_SESSION);
        assertThat(result.get("worker_id")).isEqualTo("w-1");
    }

    // ============================================================ ⑤ 事务边界 / 回滚（红证②的机械判据）

    @Test
    @DisplayName("🔴 一次事务：applyScanComplete 带 @Transactional(rollbackFor=Exception)，三处写入同生共死")
    void writeEntryIsTransactional() throws Exception {
        Method method = ProductionService.class.getMethod("applyScanComplete", Order.class,
                ProcessingOrder.class, ProcessingPositionOperation.class, BigDecimal.class,
                BigDecimal.class, String.class, WorkerIdentity.class, Long.class);
        Transactional tx = method.getAnnotation(Transactional.class);
        assertThat(tx).as("扫码完成入口必须带 @Transactional（否则三处写入各自提交 ⇒ 中途失败留残留）")
                .isNotNull();
        assertThat(tx.rollbackFor()).contains(Exception.class);
    }

    @Test
    @DisplayName("🔴 中途失败（CAS 冲突）⇒ 抛 409 + 释放幂等占位 + 不落结果快照（事务回滚由注解保证）")
    void midFailureReleasesPlaceholderAndDoesNotSnapshot() {
        stubPending(Set_OP_CLOTH_DONE_0);
        when(positionOperationMapper.advanceDoneQtyIfUnchanged(any(), any(), any(), any(), any(), any()))
                .thenReturn(0);

        assertThatThrownBy(() -> service.complete(body(TOKEN), TENANT, "key-1", WORKER))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("刚被另一次报工推进")
                // 🔴 契约面（issue #4810）：CAS 影响行数 0 ⇒ 409 `OPERATION_ALREADY_ADVANCED`
                // （设计 §5.3.1 的落点 (a)）。红证：把源码里的 409 改成别的值 ⇒ 本断言红。
                .hasFieldOrPropertyWithValue("code", "OPERATION_ALREADY_ADVANCED")
                .hasFieldOrPropertyWithValue("httpStatus", 409);

        // 失败 ⇒ 释放占位（否则一次失败把键永久占死）；且**不得**落结果快照（否则同键重试被回放成「成功」）
        verify(clientRequestIdService).discard(TENANT, "key-1");
        verify(clientRequestIdService, never()).complete(any(), any(), any());
    }

    @Test
    @DisplayName("done_at 幂等在 SQL 里：COALESCE(done_at, …) 只第一次落笔 + 谓词只认「真正做完」")
    void doneAtSqlIsIdempotentAndGatedOnCompletion() throws Exception {
        Method method = ProcessingPositionOperationMapper.class.getMethod("recordCompletionIfDone",
                String.class, Long.class, OffsetDateTime.class);
        String sql = String.join(" ", method.getAnnotation(Update.class).value());

        assertThat(sql).contains("COALESCE(done_at");
        assertThat(sql).contains("COALESCE(done_qty, 0) >= COALESCE(qty, 0)");
        // 红线：只写 done_at 一列（进度/单价/系数由别处独占）
        assertThat(sql).doesNotContain("done_qty =").doesNotContain("status =")
                .doesNotContain("unit_price").doesNotContain("factor");
    }

    @Test
    @DisplayName("「下一道」是尽力而为：报工已提交后解析抛错 ⇒ 仍返回成功回执（next_operation=null）")
    void nextOperationFailureDoesNotFailCommittedReport() {
        stubPending(Set_OP_CLOTH_DONE_0);
        // 第 1 次 selectList = 解析；第 2 次 = 事务内的「必完工序全绿」判定（必须成功）；
        // 第 3 次 = 回执里推「下一道」—— 抛脏数据歧义：已提交的报工不得因此变失败
        List<ProcessingPositionOperation> ops = Set_OP_CLOTH_DONE_0;
        when(positionOperationMapper.selectList(any()))
                .thenReturn(ops).thenReturn(ops)
                .thenThrow(new BusinessException("OPERATION_AMBIGUOUS", "脏数据", 422));

        Map<String, Object> result = service.complete(body(TOKEN), TENANT, "key-1", WORKER);

        assertThat(result.get("done_qty")).isEqualTo(new BigDecimal("11"));
        assertThat(result).containsKey("next_operation");
        assertThat(result.get("next_operation")).isNull();
        verify(clientRequestIdService).complete(eq(TENANT), eq("key-1"), any());
    }

    // ============================================================ ⑥ 幂等键的**边界**（issue #4814 核清）

    /**
     * 键**不同**（= 工人刷新/换屏后重扫）时，服务端**不会**把**同一道工序**再记一次。
     *
     * <p>挡住它的**不是**幂等键（键换了，`claim` 会放行）而是业务判据：{@code ProductionScanService.pending()}
     * 滤掉 {@code done_qty ≥ qty} 的工序（{@code ProductionService.isDone}）⇒ 本套已无待做工序 ⇒
     * 409 {@code SET_ALREADY_COMPLETED}，一个字节都不写（<b>零写入</b>由断言钉死）。</p>
     */
    @Test
    @DisplayName("🔴 换键重扫（刷新后）同一道工序**不会**二次记账：推断已无待做工序 ⇒ 409 + 零写入")
    void differentKeyAfterFullReportDoesNotWriteSecondRowForSameOperation() {
        ProcessingPositionOperation cloth =
                op(OP_CLOTH, ITEM_CLOTH, 1, "精裁-布", "11", "0", new BigDecimal("3.50"));
        stubPending(cloth);

        service.complete(body(TOKEN), TENANT, "key-first", WORKER);
        // 这一次报工已提交 ⇒ 下一请求读到的是库里的值（桩按真实提交结果同步，不是"假装没发生"）
        cloth.setDoneQty(new BigDecimal("11"));
        cloth.setStatus("done");

        assertThatThrownBy(() -> service.complete(body(TOKEN), TENANT, "key-second", WORKER))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("工序都已完成");

        // 🔴 判据：换键**不会**换来第二行报工明细（计件凭证与进度都只有一个字节的写入）
        verify(workLogMapper, times(1)).insert(any(ProductionWorkLog.class));
        verify(positionOperationMapper, times(1))
                .advanceDoneQtyIfUnchanged(any(), any(), any(), any(), any(), any());
        verify(clientRequestIdService).discard(TENANT, "key-second");
    }

    /**
     * 键**不同**时**会**多记一笔 —— 但落在**下一道待做工序**上且**满额**（默认数量 = 剩余应做）。
     *
     * <p>这是「换键重扫 ⇒ 多给一笔钱」的**确切形态**（issue #4814 的读数）：不是同一道工序被记两遍，
     * 而是重扫时「待做工序」已推进到下一道 ⇒ 工人再点一次【完成】，系统的下一道就被整笔记上。
     * 服务端无法分辨「工人真做了下一道」与「上一次答复丢了、他在重试」（A 模式零额外交互的代价）
     * ⇒ 这一半必须由**客户端复用同一个幂等键**来关闭（见 worker-h5 的 ⑧ 与 app.mjs 的未确认提交落盘）。</p>
     */
    @Test
    @DisplayName("🔴 换键重扫 ⇒ 第二行 work_log 落在**下一道**工序且满额（#4814 的「多记一笔」读数）")
    void differentKeyAfterFullReportRecordsNextOperationInFull() {
        ProcessingPositionOperation op1 =
                op(OP_CLOTH, ITEM_CLOTH, 1, "精裁-布", "11", "0", new BigDecimal("3.50"));
        ProcessingPositionOperation op2 =
                op("op-cloth-2", ITEM_CLOTH, 2, "打卷", "11", "0", new BigDecimal("2.00"));
        stubPending(List.of(op1, op2));
        when(positionOperationMapper.selectById("op-cloth-2")).thenReturn(op2);

        service.complete(body(TOKEN), TENANT, "key-first", WORKER);
        op1.setDoneQty(new BigDecimal("11"));
        op1.setStatus("done");

        // 换键（= 刷新后重扫）：服务端**没有**把它当成重复请求，而是推进到下一道并满额记账
        service.complete(body(TOKEN), TENANT, "key-second", WORKER);

        ArgumentCaptor<ProductionWorkLog> captor = ArgumentCaptor.forClass(ProductionWorkLog.class);
        verify(workLogMapper, times(2)).insert(captor.capture());
        List<ProductionWorkLog> logs = captor.getAllValues();
        assertThat(logs.get(0).getOperationId()).isEqualTo(OP_CLOTH);
        assertThat(logs.get(1).getOperationId()).isEqualTo("op-cloth-2");
        assertThat(logs.get(1).getQualifiedQty()).isEqualByComparingTo("11");
        assertThat(logs.get(1).getUnitPrice()).isEqualByComparingTo("2.00");
    }

    /**
     * 结果快照写失败时**不得**释放占位（占位被释放 ⇒ 同键重试被当成**首次** ⇒ 再记一笔）。
     *
     * <p>此时报工**已经提交**（明细 + CAS 都已发生，事务已结束），只是「回放用的快照」没落下
     * ⇒ 释放占位等于把一条已生效的报工重新开放执行。<b>fail-closed 才对</b>：让同键请求报错，
     * 由 {@code ClientRequestIdService} 的 30 分钟陈旧占位回收自愈。</p>
     */
    @Test
    @DisplayName("🔴 快照写失败（报工已提交）⇒ **不得**释放幂等占位（释放 = 同键重试被当首次 ⇒ 再记一笔）")
    void snapshotFailureKeepsPlaceholder() {
        stubPending(Set_OP_CLOTH_DONE_0);
        doThrow(BusinessException.validationError("快照序列化失败"))
                .when(clientRequestIdService).complete(any(), any(), any());

        assertThatThrownBy(() -> service.complete(body(TOKEN), TENANT, "key-1", WORKER))
                .isInstanceOf(BusinessException.class);

        // 报工已落库（不是「没执行」）⇒ 占位必须留着
        verify(workLogMapper, times(1)).insert(any(ProductionWorkLog.class));
        verify(clientRequestIdService, never()).discard(eq(TENANT), eq("key-1"));
    }

    // ============================================================ 夹具

    /** 单工序（布帘，seq 1，应做 11，未报）—— 最常见的闭环输入。 */
    private static final List<ProcessingPositionOperation> Set_OP_CLOTH_DONE_0 =
            List.of(op(OP_CLOTH, ITEM_CLOTH, 1, "精裁-布", "11", "0", new BigDecimal("3.50")));

    private void stubPending(ProcessingPositionOperation operation) {
        stubPending(List.of(operation));
    }

    /**
     * 存量单（issue #4871）：部位码命中该套，但该套的工序实例<b>一行都没有</b>
     * （= 解析面 {@code set_progress {total: 0, done: 0}}、{@code completed = true}）。
     *
     * <p>与真实读面<b>同源</b>：{@code set_progress} 由 {@code ProductionService#progressOf} 按
     * {@code ProcessingSetReadService#listSetOperations} 的结果算出 ⇒ 这里只把 Mapper 读面桩成
     * <b>空列表</b>，<b>不另造 {@code set_progress} 桩字段</b>（另造桩 = 测的是桩，不是被测实现）。</p>
     */
    private void stubSetWithoutOperations() {
        when(positionOperationMapper.selectList(any())).thenReturn(List.of());
    }

    private void stubPending(List<ProcessingPositionOperation> operations) {
        when(positionOperationMapper.selectList(any())).thenReturn(operations);
        when(positionOperationMapper.selectById(OP_CLOTH)).thenReturn(operations.get(0));
        when(positionOperationMapper.selectById(OP_GAUZE))
                .thenReturn(operations.size() > 1 ? operations.get(1) : operations.get(0));
        when(positionOperationMapper.advanceDoneQtyIfUnchanged(any(), any(), any(), any(), any(), any()))
                .thenReturn(1);
    }

    /**
     * 旧码（加工单级 {@code qr_token}）路径：新码未命中 ⇒ 走**真实**的四形态解析；
     * 该单的**套 × 部位**清单与工序实例就位（工人从清单里选套 + 选部位）。
     */
    private void stubLegacyScan() {
        when(setPartTokenMapper.selectOne(any())).thenReturn(null);
        when(orderMapper.selectById(OLD_CODE)).thenReturn(order());
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder());
        when(orderSetMapper.selectById(SET_ID)).thenReturn(orderSet());
        stubPending(Set_OP_CLOTH_DONE_0);
    }

    private ProductionWorkLog capturedWorkLog() {
        ArgumentCaptor<ProductionWorkLog> captor = ArgumentCaptor.forClass(ProductionWorkLog.class);
        verify(workLogMapper).insert(captor.capture());
        return captor.getValue();
    }

    /** 「三处写入一个字节都没发生」的判据（拒绝路径与同键回放共用）。 */
    // ============================================================ ⑨ 裁剪报工确认批次（issue #7647）

    @Test
    @DisplayName("🔴 裁剪缺批次 ⇒ 422 BATCH_REQUIRED，且零写入（不落明细、不推进进度、不记账）")
    void cuttingWithoutBatchIsRejectedBeforeAnyWrite() {
        stubPending(op(OP_CLOTH, ITEM_CLOTH, 1, "裁剪", "11", "0", new BigDecimal("3.50")));
        stubCuttingBatch(true);

        assertThatThrownBy(() -> service.complete(body(TOKEN), TENANT, "key-1", WORKER))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", "BATCH_REQUIRED");
        assertNothingWritten();
        verify(stockBatchConsumptionService, never())
                .applyCuttingReport(any(), any(), any(), any(), any(), any(), any(), any(), any());
    }

    @Test
    @DisplayName("裁剪 + 填了批次 ⇒ 同事务核对批次（拿到工人填的值与本次米数），回执带批次/余量/缺口")
    void cuttingWithBatchReconcilesAndReturnsReceipt() {
        stubPending(op(OP_CLOTH, ITEM_CLOTH, 1, "裁剪", "11", "0", new BigDecimal("3.50")));
        stubCuttingBatch(true);
        when(stockBatchConsumptionService.applyCuttingReport(any(), any(), any(), any(), any(), any(), any(),
                any(), any())).thenReturn(new StockBatchConsumptionService.CuttingReportResult(
                        "PC-20261020-0007", new BigDecimal("32.5"), new BigDecimal("3.5")));
        Map<String, Object> payload = body(TOKEN);
        payload.put("batch_no", "  PC-20261020-0007  "); // 前后空白由服务端 text 归一

        Map<String, Object> result = service.complete(payload, TENANT, "key-1", WORKER);

        ArgumentCaptor<String> batchNo = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<BigDecimal> meters = ArgumentCaptor.forClass(BigDecimal.class);
        verify(stockBatchConsumptionService).applyCuttingReport(eq(TENANT), eq(PO_NO), eq("SO-1"),
                eq(ITEM_CLOTH), eq("prod-1"), eq(12L), eq("SKU-A"), batchNo.capture(), meters.capture());
        assertThat(batchNo.getValue()).isEqualTo("PC-20261020-0007");
        assertThat(meters.getValue()).isEqualByComparingTo("11");
        assertThat(result.get("batch_no")).isEqualTo("PC-20261020-0007");
        assertThat((BigDecimal) result.get("batch_remaining")).isEqualByComparingTo("32.5");
        assertThat((BigDecimal) result.get("batch_shortage_meters")).isEqualByComparingTo("3.5");
        // 下一屏的批次判据由**同一次重解析**给出（issue #7647）：这里重解析仍是「裁剪」⇒ true；
        // 键恒在（值可 null / []），页面据此渲染下一屏而不是沿用上一屏。
        assertThat(result).containsEntry("next_batch_required", true);
        assertThat(result).containsKey("next_batch_no");
        assertThat(result.get("next_batch_candidates")).isInstanceOf(List.class);
        // 报工照常落库（批次核对不改变记账判据）
        assertThat(capturedWorkLog().getOperationId()).isEqualTo(OP_CLOTH);
    }

    @Test
    @DisplayName("零批次入库的存量商品 ⇒ 不强制批次（否则存量商品永远报不上工），也不落批次账")
    void cuttingWithoutAnyBatchRowsIsExempt() {
        stubPending(op(OP_CLOTH, ITEM_CLOTH, 1, "裁剪", "11", "0", new BigDecimal("3.50")));
        stubCuttingBatch(false);

        Map<String, Object> result = service.complete(body(TOKEN), TENANT, "key-1", WORKER);

        assertThat(result).doesNotContainKeys("batch_no", "batch_remaining", "batch_shortage_meters");
        assertThat(capturedWorkLog().getOperationId()).isEqualTo(OP_CLOTH);
        verify(stockBatchConsumptionService, never())
                .applyCuttingReport(any(), any(), any(), any(), any(), any(), any(), any(), any());
    }

    @Test
    @DisplayName("非「裁剪」工序（精裁-布）⇒ 传了 batch_no 也不读、不落账（与改前逐字相同）")
    void nonCuttingOperationIgnoresBatchNo() {
        stubPending(op(OP_CLOTH, ITEM_CLOTH, 1, "精裁-布", "11", "0", new BigDecimal("3.50")));
        stubCuttingBatch(true);
        Map<String, Object> payload = body(TOKEN);
        payload.put("batch_no", "PC-20261020-0007");

        Map<String, Object> result = service.complete(payload, TENANT, "key-1", WORKER);

        assertThat(result).doesNotContainKeys("batch_no", "batch_remaining", "batch_shortage_meters");
        // 非裁剪工序 ⇒ 下一屏的批次判据恒 false（不摆输入框）
        assertThat(result).containsEntry("next_batch_required", false);
        verify(stockBatchConsumptionService, never())
                .applyCuttingReport(any(), any(), any(), any(), any(), any(), any(), any(), any());
    }

    /** 裁剪批次判据的夹具：明细行（商品 × SKU）+ 该 SKU 是否有批次行（`tracksBatches`）。 */
    private void stubCuttingBatch(boolean tracks) {
        when(orderItemMapper.selectById(ITEM_CLOTH)).thenReturn(OrderItem.builder()
                .id(ITEM_CLOTH).tenantId(TENANT).productId("prod-1").skuId(12L).skuCode("SKU-A")
                .deleted(0).build());
        when(stockBatchConsumptionService.tracksBatches(eq(TENANT), eq("prod-1"), eq(12L)))
                .thenReturn(tracks);
    }

    private void assertNoWrites() {
        verify(workLogMapper, never()).insert(any(ProductionWorkLog.class));
        verify(positionOperationMapper, never())
                .advanceDoneQtyIfUnchanged(any(), any(), any(), any(), any(), any());
        verify(positionOperationMapper, never()).recordCompletionIfDone(any(), any(), any());
        verify(processingOrderMapper, never()).markCompletedIfActive(any(), any(), any());
    }

    /**
     * 「一个字节都不写」+ **释放幂等占位**（未确定工序 / 旧码 / 跨部位三条**拒绝**路径共用）：
     * 拒绝必须释放占位，否则一次失败把该键永久占死（工人重试会被误判成「重复」）。
     */
    private void assertNothingWritten() {
        assertNoWrites();
        verify(clientRequestIdService).discard(TENANT, "key-1");
    }

    private static Map<String, Object> body(String token) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("token", token);
        return body;
    }

    private static Map<String, Object> picked(String token, String operationId) {
        Map<String, Object> body = body(token);
        body.put("operation_id", operationId);
        return body;
    }

    private static ProcessingSetPartToken partToken(String token) {
        return partTokenOf(token, ITEM_CLOTH);
    }

    private static ProcessingSetPartToken partTokenOf(String token, String orderItemId) {
        return ProcessingSetPartToken.builder()
                .id("token-1").tenantId(TENANT).processingOrderId(PO_ID).setId(SET_ID)
                .orderItemId(orderItemId).positionKind("布帘").token(token).deleted(0)
                .build();
    }

    private static ProcessingOrderSet orderSet() {
        return ProcessingOrderSet.builder()
                .id(SET_ID).tenantId(TENANT).processingOrderId(PO_ID).setIndex(14).setNo(SET_NO)
                .deleted(0).build();
    }

    private static ProcessingOrder processingOrder() {
        return ProcessingOrder.builder()
                .id(PO_ID).tenantId(TENANT).orderId(ORDER_ID).processingOrderNo(PO_NO)
                .status("issued").deleted(0).build();
    }

    private static Order order() {
        return Order.builder().id(ORDER_ID).tenantId(TENANT).orderNo("SO-1").deleted(0).build();
    }

    private static ProcessingPositionOperation op(String id, String orderItemId, int seq,
                                                  String operationName, String qty, String doneQty,
                                                  BigDecimal unitPrice) {
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId(PO_ID).setId(SET_ID)
                .orderItemId(orderItemId).positionKind("布帘").positionName("布艺遮光帘A")
                .operationName(operationName).seq(seq).unit("米").qty(new BigDecimal(qty))
                .doneQty(new BigDecimal(doneQty)).unitPrice(unitPrice).status("pending")
                .isMustFinish(Boolean.TRUE).deleted(0).build();
    }

    // ============================================================ ④ 打包工序 ⇒ 成品入库（issue #7845）

    @Test
    @DisplayName("🔴 打包工序报工 ⇒ 回执带 finished_inbound（入库单/仓位/标签），报工结论一字未动")
    void packReportAttachesFinishedInbound() {
        ProcessingPositionOperation packOp = op("op-pack", ITEM_CLOTH, 3, "打包", "1", "0", new BigDecimal("1.00"));
        stubPending(packOp);
        // 写面按 operation_id 取回实例（`stubPending` 只桩了两个常量 id）
        when(positionOperationMapper.selectById("op-pack")).thenReturn(packOp);
        Map<String, Object> inbound = new java.util.LinkedHashMap<>();
        inbound.put("inbound_no", "RK-20261026-0001");
        inbound.put("bin_code", "A-01");
        when(finishedGoodsService.receiveByScanReport(eq(TENANT), any(Order.class), eq(TOKEN), eq("张三")))
                .thenReturn(inbound);

        Map<String, Object> result = service.complete(body(TOKEN), TENANT, "key-1", WORKER);

        assertThat(result.get("finished_inbound")).isEqualTo(inbound);
        assertThat(result.get("status")).isEqualTo("done");
        verify(finishedGoodsService).receiveByScanReport(eq(TENANT), any(Order.class), eq(TOKEN), eq("张三"));
    }

    @Test
    @DisplayName("非打包工序 ⇒ 不触达成品入库（finished_inbound 为 null、零调用）")
    void nonPackReportDoesNotTouchFinishedGoods() {
        stubPending(Set_OP_CLOTH_DONE_0);

        Map<String, Object> result = service.complete(body(TOKEN), TENANT, "key-1", WORKER);

        assertThat(result).containsEntry("finished_inbound", null);
        verify(finishedGoodsService, never()).receiveByScanReport(any(), any(), any(), any());
    }

    @Test
    @DisplayName("🔴 入库失败不改变报工结论：报工照常成功 + 回执带 finished_inbound_error（不诱发重试重复计件）")
    void inboundFailureDoesNotFailTheReport() {
        ProcessingPositionOperation packOp = op("op-pack", ITEM_CLOTH, 3, "打包", "1", "0", new BigDecimal("1.00"));
        stubPending(packOp);
        // 写面按 operation_id 取回实例（`stubPending` 只桩了两个常量 id）
        when(positionOperationMapper.selectById("op-pack")).thenReturn(packOp);
        when(finishedGoodsService.receiveByScanReport(any(), any(), any(), any()))
                .thenThrow(new IllegalStateException("成品仓没仓位了"));

        Map<String, Object> result = service.complete(body(TOKEN), TENANT, "key-1", WORKER);

        assertThat(result.get("status")).isEqualTo("done");
        assertThat(result.get("finished_inbound")).isNull();
        assertThat((String) result.get("finished_inbound_error")).contains("入库");
        verify(clientRequestIdService).complete(eq(TENANT), eq("key-1"), any());
    }
}
