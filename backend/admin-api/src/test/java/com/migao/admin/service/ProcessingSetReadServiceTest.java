// case_ids: PG-018, PG-058
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.PageResponse;
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
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.lang.reflect.Method;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 套件只读面（issue #5247 的 admin-api 半边）的**服务层**判据。
 *
 * <p><b>本测试的核心不是「三个端点会不会转发」，而是「聚合只有一份」</b>（这一条是硬要求）：
 * ① {@code ProcessingSetReadService.setOverview} 是套 → 部位 → 工序的**唯一**实现
 * （原在 {@code ProductionScanService}，本单原样搬走 ⇒ 本单不得出现第二份）；
 * ② 判据一（等价）：工人扫码面（{@link ProductionScanService#resolve}）的 {@code set_overview}
 * 与套件读面的 {@code set_overview} 对同一份数据**逐值相等**；
 * ③ 判据二（注入式、会红）：用真实子类单点改聚合（{@code set_no} ⇒ {@code MUTATED-5247}）⇒
 * <b>两侧同时变</b>；若哪一侧偷偷写回了自己的聚合，该断言立刻红（它就不再跟着变）；
 * ④ 判据三（结构性）：{@code ProductionScanService} **不得**再声明聚合相关的方法
 * （{@code setOverview} / {@code overviewOperationView} / {@code positionView} / {@code positionEntry}
 * / {@code listSetOperations} / {@code listOrderOperations} / {@code completedAt}）。
 * 真实源码单点变异（改共享实现 ⇒ 本类与 {@code ProductionScanCompleteServiceTest} 同红）的真输出见 PR。</p>
 *
 * <p><b>装配纪律</b>：{@link ProductionService} / {@link ProcessingSetReadService} 用**真实对象**
 * （只 mock Mapper）—— {@code progressOf} / {@code isDone} 是进度与「做完没」的唯一口径，
 * mock 掉它们等于把被测口径换成桩（「绿了但没跑」）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("ProcessingSetReadService 套件只读面（issue #5247）")
class ProcessingSetReadServiceTest {

    private static final Long TENANT = 1L;
    private static final Long OTHER_TENANT = 2L;
    private static final String ORDER_ID = "order-1";
    private static final String ORDER_NO = "SO-20260923-0001";
    private static final String PO_ID = "po-1";
    private static final String PO_NO = "CSO260915-02615";
    private static final String SET_ID = "set-14";
    private static final String SET_NO = PO_NO + "-014";
    private static final String ITEM_CLOTH = "oi-cloth";
    private static final String ITEM_GAUZE = "oi-gauze";
    private static final String TOKEN = "read-api-token-5247";

    /**
     * 聚合的键集（冻结；`position` 类字段缺值给 null 而不是省键）。
     * ⚠️ `cut_plan`（issue #5693）= **精裁输出清单**，**新增键**（只加不改）。
     */
    private static final List<String> OVERVIEW_KEYS =
            List.of("set_no", "set_index", "positions", "cut_plan");
    /** 精裁输出清单的一行（issue #5693）：九键**恒在**，算不出来 ⇒ null + `missing_reason`。 */
    private static final List<String> CUT_PLAN_ROW_KEYS = List.of("order_item_id", "position_kind",
            "position_name", "component", "fabric_meters", "panel_count", "panel_length_m", "remark",
            "missing_reason");
    /** ⚠️ `remark`（issue #5685）为**新增键**（部位级备注，未填 ⇒ null）：键恒在。 */
    private static final List<String> POSITION_KEYS =
            List.of("order_item_id", "position_kind", "position_name", "remark", "operations");
    private static final List<String> OPERATION_KEYS = List.of("operation_id", "logical_name", "position",
            "seq", "qty", "unit", "unit_price", "status", "done_qty");
    private static final List<String> DETAIL_KEYS = List.of("set_id", "set_no", "set_index", "craft_line_id",
            "processing_order_id", "processing_order_no", "order_id", "order_no", "completed", "completed_at",
            "set_overview", "progress");
    private static final List<String> LIST_ROW_KEYS = List.of("set_id", "set_no", "set_index", "craft_line_id",
            "processing_order_id", "processing_order_no", "order_id", "order_no", "total_operations",
            "done_operations", "progress_percent", "completed", "cut_plan");
    private static final List<String> SCAN_PROGRESS_KEYS = List.of("order_id", "order_no",
            "processing_order_id", "processing_order_no", "total_sets", "completed_sets", "total_operations",
            "done_operations", "progress_percent", "sets");
    private static final List<String> SCAN_PROGRESS_SET_KEYS = List.of("set_id", "set_no", "set_index",
            "completed", "completed_at", "total_operations", "done_operations", "progress_percent");

    @Mock
    private ProcessingOrderSetMapper orderSetMapper;
    @Mock
    private ProcessingPositionOperationMapper positionOperationMapper;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private OrderMapper orderMapper;
    @Mock
    private ProductionWorkLogMapper workLogMapper;
    @Mock
    private ProcessingSetPartTokenMapper setPartTokenMapper;
    @Mock
    private ClientRequestIdService clientRequestIdService;
    @Mock
    private ProductionOperationQueryService operationQueryService;

    private ProductionService productionService;
    private ProcessingSetReadService service;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        productionService = new ProductionService(processingOrderMapper, positionOperationMapper,
                workLogMapper, orderMapper, orderItemMapper, clientRequestIdService);
        service = new ProcessingSetReadService(orderSetMapper, positionOperationMapper, orderItemMapper,
                processingOrderMapper, orderMapper, productionService);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ══════════════════ 交付物 2：套件详情（套 → 部位 → 工序明细）

    @Test
    @DisplayName("详情键集冻结（12 键）+ 三层形状（set_overview/positions/operations）键集冻结")
    void detailFreezesKeySets() {
        stubDetail();

        Map<String, Object> detail = service.setDetail(SET_ID, TENANT);

        assertThat(detail.keySet()).as("详情冻结键集：不得删键").containsExactlyInAnyOrderElementsOf(DETAIL_KEYS);
        assertThat(detail).containsEntry("set_id", SET_ID).containsEntry("set_no", SET_NO)
                .containsEntry("set_index", 14).containsEntry("processing_order_no", PO_NO)
                .containsEntry("order_no", ORDER_NO);

        @SuppressWarnings("unchecked")
        Map<String, Object> overview = (Map<String, Object>) detail.get("set_overview");
        assertThat(overview.keySet()).containsExactlyInAnyOrderElementsOf(OVERVIEW_KEYS);
        assertThat(overview).containsEntry("set_no", SET_NO).containsEntry("set_index", 14);

        List<Map<String, Object>> positions = positionsOf(overview);
        assertThat(positions).as("两个部位：布帘 + 纱帘").hasSize(2);
        for (Map<String, Object> position : positions) {
            assertThat(position.keySet()).as("部位键集冻结（缺值给 null 而不是省键）")
                    .containsExactlyInAnyOrderElementsOf(POSITION_KEYS);
        }
        for (Map<String, Object> position : positions) {
            for (Map<String, Object> operation : operationsOf(position)) {
                assertThat(operation.keySet()).as("工序 9 键冻结（应做数量/单位/单价/状态/已报数量）")
                        .containsExactlyInAnyOrderElementsOf(OPERATION_KEYS);
            }
        }
    }

    @Test
    @DisplayName("🔴 部位级备注（issue #5685）：订单行 processing_info.remark 透传到 positions[]；未填 = null（不造值）")
    void itemRemarkFlowsIntoSetOverview() {
        stubDetail();
        when(orderItemMapper.selectById(ITEM_CLOTH))
                .thenReturn(orderItemWithRemark(ITEM_CLOTH, "  公式--48个折  "));
        when(orderItemMapper.selectById(ITEM_GAUZE)).thenReturn(orderItemWithRemark(ITEM_GAUZE, "   "));

        Map<String, Object> detail = service.setDetail(SET_ID, TENANT);
        @SuppressWarnings("unchecked")
        Map<String, Object> overview = (Map<String, Object>) detail.get("set_overview");

        assertThat(positionOf(overview, ITEM_CLOTH))
                .as("填了备注 ⇒ 透传（首尾空白 trim 后逐字）").containsEntry("remark", "公式--48个折");
        Map<String, Object> gauze = positionOf(overview, ITEM_GAUZE);
        assertThat(gauze).as("键恒在（消费方不必写分支）").containsKey("remark");
        assertThat(gauze.get("remark")).as("纯空白 = 未填 ⇒ null（不造空串）").isNull();
    }

    @Test
    @DisplayName("🔴 部位级备注：不越租户 + 非 Map 形态按未填处理（issue #5685）")
    void itemRemarkIsTenantScopedAndTolerant() {
        stubDetail();
        when(orderItemMapper.selectById(ITEM_CLOTH)).thenReturn(OrderItem.builder()
                .id(ITEM_CLOTH).tenantId(OTHER_TENANT).productName("别人的货")
                .processingInfo(Map.of("remark", "别家备注")).build());
        // 字符串形态只在**自定义 @Select 路径**出现（typeHandler 不生效）；本读面走 BaseMapper，
        // 不经过那条路 ⇒ 非 Map 一律按「未填」处理（不解析、不猜）
        when(orderItemMapper.selectById(ITEM_GAUZE)).thenReturn(OrderItem.builder()
                .id(ITEM_GAUZE).tenantId(TENANT).productName("纱")
                .processingInfo("{\"remark\":\"字符串形态\"}").build());

        Map<String, Object> detail = service.setDetail(SET_ID, TENANT);
        @SuppressWarnings("unchecked")
        Map<String, Object> overview = (Map<String, Object>) detail.get("set_overview");

        assertThat(positionOf(overview, ITEM_CLOTH).get("remark"))
                .as("别的租户的行 ⇒ 读不到（不越租户）").isNull();
        assertThat(positionOf(overview, ITEM_GAUZE).get("remark"))
                .as("非 Map 形态 ⇒ 未填（本类不走自定义 @Select 路径）").isNull();
    }

    @Test
    @DisplayName("🔴 未定价 ≠ 0 元（V90 / #4696）：unit_price 为 null 时读面原样 null，不折 0")
    void unpricedOperationKeepsNullUnitPrice() {
        stubDetail();

        Map<String, Object> detail = service.setDetail(SET_ID, TENANT);
        Map<String, Object> unpriced = operationOf(detail, "op-2");

        assertThat(unpriced).as("键必须在场（不得省键）").containsKey("unit_price");
        assertThat(unpriced.get("unit_price")).as("未定价保持 null，绝不折 0").isNull();
        assertThat(unpriced).containsEntry("status", "pending");
        assertThat(unpriced.get("done_qty")).as("已报数量原样（6.00 米）")
                .isEqualTo(new BigDecimal("6.00"));
        assertThat(unpriced.get("qty")).as("应做数量（11.00 米）").isEqualTo(new BigDecimal("11.00"));
    }

    @Test
    @DisplayName("完成口径：全部活跃工序实例报满 ⇒ completed=true + completed_at=最晚 done_at；未报满 ⇒ false")
    void completedFollowsAllOperationsDone() {
        stubDetail();
        assertThat(service.setDetail(SET_ID, TENANT)).as("op-2 待做 ⇒ 未完成")
                .containsEntry("completed", false);

        // 把 op-2 报满 ⇒ 三件全完成
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-1", ITEM_CLOTH, "布帘", 1, "精裁-布", "裁剪", "米", "12.30", "12.30", "3.50", "done",
                        OffsetDateTime.parse("2026-09-23T08:00:00+08:00")),
                op("op-2", ITEM_CLOTH, "布帘", 2, "定型-布", "车位", "米", "11.00", "11.00", null, "done",
                        OffsetDateTime.parse("2026-09-23T09:30:00+08:00")),
                op("op-3", ITEM_GAUZE, "纱帘", 1, "三边-纱", "车位", "米", "8.00", "8.00", "2.00", "done",
                        OffsetDateTime.parse("2026-09-23T07:00:00+08:00"))));

        Map<String, Object> detail = service.setDetail(SET_ID, TENANT);
        assertThat(detail).containsEntry("completed", true);
        assertThat(detail.get("completed_at")).as("= 已完成工序里最晚 done_at")
                .isEqualTo(OffsetDateTime.parse("2026-09-23T09:30:00+08:00"));
    }

    // ══════════════════ 交付物 1：套件列表（分页 + 租户/软删过滤）

    @Test
    @DisplayName("列表行键集冻结（12 键）+ 分页信封 + 进度取自同一份 progressOf")
    void listFreezesRowKeysAndProgress() {
        stubDetail();
        when(orderSetMapper.selectPage(any(), any())).thenReturn(setPage());

        PageResponse<Map<String, Object>> result = service.listSets(null, null, 1, 20, TENANT);

        assertThat(result.getTotal()).isEqualTo(1L);
        assertThat(result.getPage()).isEqualTo(1L);
        assertThat(result.getSize()).isEqualTo(20L);
        Map<String, Object> row = result.getItems().get(0);
        assertThat(row.keySet()).containsExactlyInAnyOrderElementsOf(LIST_ROW_KEYS);
        assertThat(row).containsEntry("set_no", SET_NO).containsEntry("order_no", ORDER_NO)
                .containsEntry("processing_order_no", PO_NO)
                .containsEntry("total_operations", 3).containsEntry("done_operations", 2)
                .containsEntry("progress_percent", 67).containsEntry("completed", false);
    }

    @Test
    @DisplayName("🔴 租户 + 软删是**显式**条件（不依赖多租户拦截器）：套查询与订单查询都带 tenant_id/deleted")
    void queriesCarryTenantAndDeletedExplicitly() {
        stubDetail();
        when(orderSetMapper.selectPage(any(), any())).thenReturn(setPage());
        when(processingOrderMapper.selectList(any())).thenReturn(List.of(po()));
        // 订单号过滤走既有四形态解析（form ② `order_no` 兜底）—— tenant 由它兜住
        when(orderMapper.selectOne(any())).thenReturn(order());

        service.listSets(ORDER_NO, null, 1, 20, TENANT);

        @SuppressWarnings("unchecked")
        ArgumentCaptor<QueryWrapper<ProcessingOrderSet>> setsCaptor =
                ArgumentCaptor.forClass(QueryWrapper.class);
        verify(orderSetMapper).selectPage(any(), setsCaptor.capture());
        QueryWrapper<ProcessingOrderSet> setsWrapper = setsCaptor.getValue();
        // MP 的 wrapper 参数是**惰性**的（要物化 SQL 段才落 paramNameValuePairs）——
        // 字符串列名 ⇒ 物化不需要 TableInfo 缓存，单测里可安全取
        assertThat(setsWrapper.getSqlSegment()).as("套查询条件").contains("tenant_id", "deleted");
        assertThat(setsWrapper.getParamNameValuePairs().values())
                .as("套查询：tenant_id=1 + deleted=0 必须显式在场")
                .contains(TENANT, 0);

        // 加工单按 order_id + tenant + deleted 取（能走到这一步 = resolveOrder 已按租户解析成功）
        @SuppressWarnings("unchecked")
        ArgumentCaptor<QueryWrapper<ProcessingOrder>> poCaptor = ArgumentCaptor.forClass(QueryWrapper.class);
        verify(processingOrderMapper).selectList(poCaptor.capture());
        QueryWrapper<ProcessingOrder> poWrapper = poCaptor.getValue();
        assertThat(poWrapper.getSqlSegment()).contains("order_id", "tenant_id", "deleted");
        assertThat(poWrapper.getParamNameValuePairs().values())
                .as("加工单查询：tenant_id=1 + deleted=0 + order_id 必须显式在场")
                .contains(TENANT, 0, ORDER_ID);
    }

    // ══════════════════ 交付物 3：扫码循环进度

    @Test
    @DisplayName("扫码进度键集冻结（10 键 + 每套 8 键）+ 汇总口径 = 全部活跃工序实例报满率")
    void scanProgressFreezesKeySets() {
        stubDetail();
        when(processingOrderMapper.selectOne(any())).thenReturn(po());
        when(orderSetMapper.selectList(any())).thenReturn(List.of(set()));

        Map<String, Object> progress = service.scanProgress(null, PO_NO, TENANT);

        assertThat(progress.keySet()).containsExactlyInAnyOrderElementsOf(SCAN_PROGRESS_KEYS);
        assertThat(progress).containsEntry("processing_order_no", PO_NO).containsEntry("order_no", ORDER_NO)
                .containsEntry("total_sets", 1).containsEntry("completed_sets", 0)
                .containsEntry("total_operations", 3).containsEntry("done_operations", 2)
                .containsEntry("progress_percent", 67);

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> sets = (List<Map<String, Object>>) progress.get("sets");
        assertThat(sets).hasSize(1);
        assertThat(sets.get(0).keySet()).containsExactlyInAnyOrderElementsOf(SCAN_PROGRESS_SET_KEYS);
        assertThat(sets.get(0)).containsEntry("set_no", SET_NO).containsEntry("completed", false)
                .containsEntry("progress_percent", 67);
    }

    @Test
    @DisplayName("按订单号且该订单还没有加工单 ⇒ 零值行（与既有 progress 的「还没生产就是 0」同口径）")
    void scanProgressZeroFilledWithoutProcessingOrder() {
        when(orderMapper.selectOne(any())).thenReturn(order());
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(null);

        Map<String, Object> progress = service.scanProgress(ORDER_NO, null, TENANT);

        assertThat(progress.keySet()).containsExactlyInAnyOrderElementsOf(SCAN_PROGRESS_KEYS);
        assertThat(progress).containsEntry("order_no", ORDER_NO).containsEntry("processing_order_id", null)
                .containsEntry("processing_order_no", null).containsEntry("total_sets", 0)
                .containsEntry("done_operations", 0).containsEntry("progress_percent", 0);
        assertThat((List<?>) progress.get("sets")).isEmpty();
    }

    @Test
    @DisplayName("两个标识都不给 ⇒ 422 VALIDATION_ERROR（不猜一个全租户的全量进度）")
    void scanProgressNeedsAnIdentifier() {
        assertThatThrownBy(() -> service.scanProgress(null, "  ", TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("至少要给一个")
                .extracting(e -> ((BusinessException) e).getCode())
                .isEqualTo("VALIDATION_ERROR");
    }

    // ══════════════════ 租户 / 软删 fail-closed（PG-011 同族）

    @Test
    @DisplayName("🔴 跨租户 / 已软删 / 不存在的套 ⇒ 404（fail-closed，不返回别人的数据）")
    void crossTenantOrDeletedSetIs404() {
        when(orderSetMapper.selectById(SET_ID)).thenReturn(setWith(TENANT, 1));
        assertThatThrownBy(() -> service.setDetail(SET_ID, TENANT))
                .isInstanceOf(BusinessException.class).hasMessageContaining("不存在");

        when(orderSetMapper.selectById(SET_ID)).thenReturn(setWith(OTHER_TENANT, 0));
        assertThatThrownBy(() -> service.setDetail(SET_ID, TENANT))
                .isInstanceOf(BusinessException.class).hasMessageContaining("不存在");

        when(orderSetMapper.selectById(SET_ID)).thenReturn(null);
        assertThatThrownBy(() -> service.setDetail(SET_ID, TENANT))
                .isInstanceOf(BusinessException.class).hasMessageContaining("不存在");
    }

    @Test
    @DisplayName("🔴 点名的加工单号查不到 ⇒ 404（不静默给空页/零值行）")
    void unknownProcessingOrderNoIs404() {
        when(processingOrderMapper.selectOne(any())).thenReturn(null);
        assertThatThrownBy(() -> service.scanProgress(null, "CSO-NOT-EXIST", TENANT))
                .isInstanceOf(BusinessException.class).hasMessageContaining("加工单");

        assertThatThrownBy(() -> service.listSets(null, "CSO-NOT-EXIST", 1, 20, TENANT))
                .isInstanceOf(BusinessException.class).hasMessageContaining("加工单");
    }

    // ══════════════════ 结构性判据：聚合只有一份

    @Test
    @DisplayName("🔴 工人扫码面与套件读面同源：同一份数据下两侧 set_overview 逐值相等")
    void workerScanAndSetReadShareTheSameOverview() {
        stubScan();

        Map<String, Object> scan = scanService(service).resolve(TOKEN, null, TENANT);
        Map<String, Object> read = service.setDetail(SET_ID, TENANT);

        assertThat(scan.get("set_overview"))
                .as("两消费者必须逐值相等（同一份聚合实现）")
                .isEqualTo(read.get("set_overview"));
    }

    @Test
    @DisplayName("🔴 注入式（会红）：单点改共享聚合 ⇒ 工人扫码面与套件读面**同时**变")
    void mutatingSharedAggregationChangesBothConsumers() {
        stubScan();
        MutatingReadService mutated = new MutatingReadService();

        Map<String, Object> scan = scanService(mutated).resolve(TOKEN, null, TENANT);
        Map<String, Object> read = mutated.setDetail(SET_ID, TENANT);

        @SuppressWarnings("unchecked")
        Map<String, Object> scanOverview = (Map<String, Object>) scan.get("set_overview");
        @SuppressWarnings("unchecked")
        Map<String, Object> readOverview = (Map<String, Object>) read.get("set_overview");
        assertThat(scanOverview).as("扫码面跟着变").containsEntry("set_no", "MUTATED-5247");
        assertThat(readOverview).as("读面跟着变").containsEntry("set_no", "MUTATED-5247");
        assertThat(scanOverview).as("变的是同一处 ⇒ 两侧仍逐值相等").isEqualTo(readOverview);
    }

    @Test
    @DisplayName("🔴 结构性：聚合实现**只**在 ProcessingSetReadService（ProductionScanService 不得再声明一份）")
    void aggregationLivesOnlyInTheSharedReadService() {
        List<String> scanMethods = Arrays.stream(ProductionScanService.class.getDeclaredMethods())
                .map(Method::getName).toList();
        assertThat(scanMethods)
                .as("扫码服务里若再长出第二份聚合（含精裁输出清单），本断言必红")
                .doesNotContain("setOverview", "overviewOperationView", "positionView", "positionEntry",
                        "listSetOperations", "listOrderOperations", "completedAt", "productNameOf",
                        "cutPlan", "cutPlanRow");
        assertThat(Arrays.stream(ProcessingSetReadService.class.getDeclaredMethods()).map(Method::getName))
                .as("聚合本体在共享读面里").contains("setOverview", "cutPlan");
    }

    // ══════════════════ 精裁输出清单（issue #5693：给裁床的「裁多长 × 几片」）

    @Test
    @DisplayName("🔴 清单行键集冻结（九键恒在）+ 定宽买高 = panels 片 × (用料 / panels)")
    void cutPlanFreezesKeySetsAndDecomposesFixedWidth() {
        stubDetail();
        when(orderItemMapper.selectById(ITEM_CLOTH)).thenReturn(orderItemWithCutting(ITEM_CLOTH, "定宽买高", 2));
        when(orderItemMapper.selectById(ITEM_GAUZE)).thenReturn(orderItemWithCutting(ITEM_GAUZE, "定宽买高", 4));

        List<Map<String, Object>> rows = cutPlanOf(service.setDetail(SET_ID, TENANT));

        assertThat(rows).as("两个部位各一行（序 = positions 的同一份分组）").hasSize(2);
        for (Map<String, Object> row : rows) {
            assertThat(row.keySet()).as("清单行键集冻结（缺值给 null 而不是省键）")
                    .containsExactlyInAnyOrderElementsOf(CUT_PLAN_ROW_KEYS);
        }
        // 布帘：精裁-布 应做 12.30 米（qty_source=fabric_meters）⇒ 12.30 / 2 = 6.15 米 × 2 片
        assertThat(cutPlanRowOf(rows, ITEM_CLOTH))
                .containsEntry("position_kind", "布帘")
                .containsEntry("component", "主布")
                .containsEntry("fabric_meters", new BigDecimal("12.30"))
                .containsEntry("panel_count", 2)
                .containsEntry("panel_length_m", new BigDecimal("6.150000"))
                .containsEntry("missing_reason", null);
    }

    @Test
    @DisplayName("🔴 定高买宽 ⇒ 1 片 × 用料米数（引擎口径「一块 = 整窗」；不拿幅数无定义当缺值）")
    void cutPlanFixedHeightIsOneWholeWindowPiece() {
        stubDetail();
        when(orderItemMapper.selectById(ITEM_CLOTH)).thenReturn(orderItemWithCutting(ITEM_CLOTH, "定高买宽", null));
        when(orderItemMapper.selectById(ITEM_GAUZE)).thenReturn(orderItemWithCutting(ITEM_GAUZE, "定高买宽", null));

        List<Map<String, Object>> rows = cutPlanOf(service.setDetail(SET_ID, TENANT));

        assertThat(cutPlanRowOf(rows, ITEM_CLOTH))
                .as("定高买宽：引擎不产 panels（幅数无定义）⇒ 口径 = 一块整窗，长度 = 用料米数")
                .containsEntry("panel_count", 1)
                .containsEntry("panel_length_m", new BigDecimal("12.30"))
                .containsEntry("missing_reason", null);
        assertThat(cutPlanRowOf(rows, ITEM_GAUZE).get("missing_reason"))
                .as("纱帘只有 三边-纱、没有「精裁」实例 ⇒ 用料无从取（留空 + 标原因）").isNotNull();
    }

    @Test
    @DisplayName("🔴 缺值不渲染假数据：qty_source 非 fabric_meters / 缺 panels / 未知加工类型 ⇒ 留空 + 指名原因")
    void cutPlanNeverSubstitutesFakeNumbers() {
        when(orderSetMapper.selectById(SET_ID)).thenReturn(set());
        when(processingOrderMapper.selectById(PO_ID)).thenReturn(po());
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order());
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                // 布帘：有「精裁」实例，但 qty_source=fallback（= 真兜底 1）⇒ 不是用料
                opWithQtySource("op-1", ITEM_CLOTH, "布帘", 1, "精裁-布", "米", "1.00", "fallback"),
                // 纱帘：有「精裁」实例且用料真给了（8.00），但定宽买高缺 panels ⇒ 分不了片
                opWithQtySource("op-3", ITEM_GAUZE, "纱帘", 1, "精裁-纱", "米", "8.00", "fabric_meters")));
        when(orderItemMapper.selectById(ITEM_CLOTH)).thenReturn(orderItemWithCutting(ITEM_CLOTH, "定宽买高", 2));
        when(orderItemMapper.selectById(ITEM_GAUZE)).thenReturn(orderItemWithCutting(ITEM_GAUZE, "定宽买高", null));

        List<Map<String, Object>> rows = cutPlanOf(service.setDetail(SET_ID, TENANT));

        Map<String, Object> cloth = cutPlanRowOf(rows, ITEM_CLOTH);
        assertThat(cloth.get("fabric_meters")).as("兜底 1 不是用料 ⇒ 不得拿 1 冒充").isNull();
        assertThat(cloth.get("panel_count")).as("拿不到用料 ⇒ 不报片数（不放半截数据）").isNull();
        assertThat(cloth.get("panel_length_m")).isNull();
        assertThat((String) cloth.get("missing_reason")).as("要指名缺什么（可行动）")
                .contains("qty_source", "fallback");

        Map<String, Object> gauze = cutPlanRowOf(rows, ITEM_GAUZE);
        assertThat(gauze.get("fabric_meters")).as("引擎直接供数 ⇒ 用料照实给").isEqualTo(new BigDecimal("8.00"));
        assertThat(gauze.get("panel_count")).as("定宽买高缺幅数 ⇒ 不自己 ceil(M/门幅)").isNull();
        assertThat((String) gauze.get("missing_reason")).contains("幅数");

        // 未知加工类型 ⇒ 三项都留空（不猜工艺）
        when(orderItemMapper.selectById(ITEM_CLOTH)).thenReturn(orderItemWithCutting(ITEM_CLOTH, "四开", 2));
        Map<String, Object> unknown = cutPlanRowOf(cutPlanOf(service.setDetail(SET_ID, TENANT)), ITEM_CLOTH);
        assertThat(unknown.get("panel_count")).isNull();
        assertThat((String) unknown.get("missing_reason")).contains("加工类型");
    }

    @Test
    @DisplayName("🔴 存量行 processing_info 为 NULL / 解析失败 ⇒ 清单不 NPE（issue #5550 形态），一律按缺键留空")
    void cutPlanToleratesMissingProcessingInfo() {
        stubDetail();
        // ① 列值就是 null（真库实证：待派明细 15/29 行是 NULL）
        when(orderItemMapper.selectById(ITEM_CLOTH)).thenReturn(OrderItem.builder()
                .id(ITEM_CLOTH).tenantId(TENANT).productName("布艺遮光帘A").build());
        // ② 字符串形态但**解析不了**（自定义 @Select 路径的脏数据）⇒ 归一化返回 null
        when(orderItemMapper.selectById(ITEM_GAUZE)).thenReturn(OrderItem.builder()
                .id(ITEM_GAUZE).tenantId(TENANT).productName("纱帘-白")
                .processingInfo("{不是 JSON").build());

        List<Map<String, Object>> rows = cutPlanOf(service.setDetail(SET_ID, TENANT));

        for (String itemId : List.of(ITEM_CLOTH, ITEM_GAUZE)) {
            Map<String, Object> row = cutPlanRowOf(rows, itemId);
            assertThat(row.get("component")).as("缺 processing_info ⇒ 组件留空（不造值）").isNull();
            assertThat(row.get("panel_count")).as("取不到加工类型 / 幅数 ⇒ 不猜片数").isNull();
            assertThat(row.get("missing_reason")).as("要指名缺什么（可行动）").isNotNull();
        }
        assertThat(cutPlanRowOf(rows, ITEM_CLOTH).get("fabric_meters"))
                .as("用料与 processing_info 无关（来自「精裁」工序实例）⇒ 照实给")
                .isEqualTo(new BigDecimal("12.30"));
    }

    @Test
    @DisplayName("🔴 两处读面 + 列表行：同一份清单**逐值相等**（工人扫码 / 商家套件详情 / 商家列表）")
    void cutPlanIsIdenticalAcrossReadFacesAndListRow() {
        stubScan();
        when(orderItemMapper.selectById(ITEM_CLOTH)).thenReturn(orderItemWithCutting(ITEM_CLOTH, "定宽买高", 2));
        when(orderItemMapper.selectById(ITEM_GAUZE)).thenReturn(orderItemWithCutting(ITEM_GAUZE, "定宽买高", 4));
        when(orderSetMapper.selectPage(any(), any())).thenReturn(setPage());
        when(processingOrderMapper.selectOne(any())).thenReturn(po());

        Map<String, Object> scan = scanService(service).resolve(TOKEN, null, TENANT);
        Map<String, Object> detail = service.setDetail(SET_ID, TENANT);
        Map<String, Object> listRow = service.listSets(null, PO_NO, 1, 20, TENANT).getItems().get(0);

        List<Map<String, Object>> expected = cutPlanOf(detail);
        assertThat(expected).as("两行都得有值（判据不得空跑）").hasSize(2);
        assertThat(cutPlanOf(scan)).as("工人扫码面 = 商家详情面（改一处两处同变）").isEqualTo(expected);
        assertThat(listRow.get("cut_plan")).as("商家列表行 = 商家详情面").isEqualTo(expected);
    }

    @Test
    @DisplayName("🔴 注入式（会红）：单点改 cutPlan ⇒ 工人扫码面与商家读面**同时**变")
    void mutatingCutPlanChangesBothReadFaces() {
        stubScan();
        MutatingCutPlanService mutated = new MutatingCutPlanService();

        Map<String, Object> scan = scanService(mutated).resolve(TOKEN, null, TENANT);
        Map<String, Object> detail = mutated.setDetail(SET_ID, TENANT);

        List<Map<String, Object>> mutatedRows = cutPlanOf(scan);
        assertThat(mutatedRows).as("扫码面跟着变").containsExactly(Map.of("marker", "MUTATED-5693"));
        assertThat(cutPlanOf(detail)).as("商家读面跟着变（哪一侧自己算一份，本断言必红）").isEqualTo(mutatedRows);
    }

    // ══════════════════ 夹具 / 装配 / 工具

    private void stubDetail() {
        when(orderSetMapper.selectById(SET_ID)).thenReturn(set());
        when(processingOrderMapper.selectById(PO_ID)).thenReturn(po());
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order());
        when(positionOperationMapper.selectList(any())).thenReturn(ops());
    }

    /** 工人扫码面的装配（真实对象，只 mock Mapper）：新码 ⇒ 套 × 部位 ⇒ 推断 + set_overview。 */
    private void stubScan() {
        when(setPartTokenMapper.selectOne(any())).thenReturn(ProcessingSetPartToken.builder()
                .id("token-1").tenantId(TENANT).processingOrderId(PO_ID).setId(SET_ID)
                .orderItemId(ITEM_CLOTH).positionKind("布帘").token(TOKEN).deleted(0).build());
        when(operationQueryService.operationsByName(TENANT)).thenReturn(Map.of());
        stubDetail();
    }

    private ProductionScanService scanService(ProcessingSetReadService readService) {
        return new ProductionScanService(setPartTokenMapper, orderSetMapper, processingOrderMapper,
                operationQueryService, productionService,
                new ProductionStuckPointService(productionService, positionOperationMapper, orderSetMapper, 4.0),
                readService);
    }

    /** 单点变异：**只**改共享聚合的一处 ⇒ 所有消费者必须跟着变（注入式判据）。 */
    private final class MutatingReadService extends ProcessingSetReadService {

        private MutatingReadService() {
            super(orderSetMapper, positionOperationMapper, orderItemMapper, processingOrderMapper,
                    orderMapper, productionService);
        }

        @Override
        public Map<String, Object> setOverview(ProcessingOrderSet set,
                                               List<ProcessingPositionOperation> setOperations,
                                               Long tenantId) {
            Map<String, Object> overview = super.setOverview(set, setOperations, tenantId);
            overview.put("set_no", "MUTATED-5247");
            return overview;
        }
    }

    /**
     * 单点变异（issue #5693）：**只**改精裁输出清单 ⇒ 两个读面必须同时变
     * （若哪一侧自己算了一份清单，{@code mutatingCutPlanChangesBothReadFaces} 立刻红）。
     */
    private final class MutatingCutPlanService extends ProcessingSetReadService {

        private MutatingCutPlanService() {
            super(orderSetMapper, positionOperationMapper, orderItemMapper, processingOrderMapper,
                    orderMapper, productionService);
        }

        @Override
        List<Map<String, Object>> cutPlan(List<ProcessingPositionOperation> setOperations, Long tenantId) {
            Map<String, Object> marker = new LinkedHashMap<>();
            marker.put("marker", "MUTATED-5693");
            return List.of(marker);
        }
    }

    private Page<ProcessingOrderSet> setPage() {
        Page<ProcessingOrderSet> page = new Page<>(1, 20);
        page.setRecords(List.of(set()));
        page.setTotal(1L);
        return page;
    }

    private ProcessingOrderSet set() {
        return setWith(TENANT, 0);
    }

    private ProcessingOrderSet setWith(Long tenantId, int deleted) {
        return ProcessingOrderSet.builder().id(SET_ID).tenantId(tenantId).processingOrderId(PO_ID)
                .setIndex(14).setNo(SET_NO).craftLineId(ITEM_CLOTH)
                .positionItemIds(List.of(ITEM_CLOTH, ITEM_GAUZE)).deleted(deleted).build();
    }

    private ProcessingOrder po() {
        return ProcessingOrder.builder().id(PO_ID).tenantId(TENANT).orderId(ORDER_ID)
                .processingOrderNo(PO_NO).status("in_processing").deleted(0).build();
    }

    private Order order() {
        return Order.builder().id(ORDER_ID).tenantId(TENANT).orderNo(ORDER_NO).status("producing")
                .deleted(0).build();
    }

    /**
     * 三件工序实例：布帘 2 道（1 完成 1 待做、**未定价**）+ 纱帘 1 道（完成）⇒
     * 进度 2/3 = 67%，`completed=false`。
     */
    private List<ProcessingPositionOperation> ops() {
        return List.of(
                op("op-1", ITEM_CLOTH, "布帘", 1, "精裁-布", "裁剪", "米", "12.30", "12.30", "3.50", "done"),
                op("op-2", ITEM_CLOTH, "布帘", 2, "定型-布", "车位", "米", "11.00", "6.00", null, "pending"),
                op("op-3", ITEM_GAUZE, "纱帘", 1, "三边-纱", "车位", "米", "8.00", "8.00", "2.00", "done"));
    }

    private ProcessingPositionOperation op(String id, String orderItemId, String positionKind, int seq,
                                           String operationName, String groupName, String unit, String qty,
                                           String doneQty, String unitPrice, String status) {
        return op(id, orderItemId, positionKind, seq, operationName, groupName, unit, qty, doneQty,
                unitPrice, status, null);
    }

    private ProcessingPositionOperation op(String id, String orderItemId, String positionKind, int seq,
                                           String operationName, String groupName, String unit, String qty,
                                           String doneQty, String unitPrice, String status,
                                           OffsetDateTime doneAt) {
        return ProcessingPositionOperation.builder().id(id).tenantId(TENANT).processingOrderId(PO_ID)
                .setId(SET_ID).setNo(SET_NO).orderItemId(orderItemId).positionKind(positionKind)
                .positionName("布帘".equals(positionKind) ? "布艺遮光帘A 米白" : "纱帘-白")
                .seq(seq).operationName(operationName).groupName(groupName).unit(unit)
                .qty(new BigDecimal(qty)).qtySource("fabric_meters").unitPrice(unitPrice == null
                        ? null : new BigDecimal(unitPrice))
                .status(status).doneQty(new BigDecimal(doneQty)).doneAt(doneAt).deleted(0).build();
    }

    @SuppressWarnings("unchecked")
    /** 按 `order_item_id` 取某一个部位（缺失 ⇒ 断言失败，避免「测试自己空跑」）。 */
    private static Map<String, Object> positionOf(Map<String, Object> overview, String orderItemId) {
        for (Map<String, Object> position : positionsOf(overview)) {
            if (orderItemId.equals(position.get("order_item_id"))) {
                return position;
            }
        }
        throw new AssertionError("部位不存在：" + orderItemId + "（判据会空跑）");
    }

    /** 订单行夹具（只带 `processing_info.remark` —— 本判据的唯一输入）。 */
    private static OrderItem orderItemWithRemark(String itemId, String remark) {
        return OrderItem.builder().id(itemId).tenantId(TENANT).productName("布艺遮光帘A")
                .processingInfo(Map.of("remark", remark)).build();
    }

    /**
     * 订单行夹具（精裁输出清单的两个输入）：加工类型（**列** `order_items.cutting_mode`）+
     * 算料输出 `panels`（{@code processing_info.panels}，源头 = 引擎 {@code plan.panels}）。
     * {@code panels == null} = **键缺席**（定高买宽 / 引擎没给）—— 不是「0 幅」。
     */
    private static OrderItem orderItemWithCutting(String itemId, String cuttingMode, Integer panels) {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("componentRole", "主布");
        if (panels != null) {
            info.put("panels", panels);
        }
        return OrderItem.builder().id(itemId).tenantId(TENANT).productName("布艺遮光帘A")
                .cuttingMode(cuttingMode).processingInfo(info).build();
    }

    /** 工序实例夹具（指定 `qty_source`：issue #5693 的用料口径判据要逐态造：direct / fallback）。 */
    private ProcessingPositionOperation opWithQtySource(String id, String orderItemId, String positionKind,
                                                        int seq, String operationName, String unit, String qty,
                                                        String qtySource) {
        return ProcessingPositionOperation.builder().id(id).tenantId(TENANT).processingOrderId(PO_ID)
                .setId(SET_ID).setNo(SET_NO).orderItemId(orderItemId).positionKind(positionKind)
                .positionName("布帘".equals(positionKind) ? "布艺遮光帘A 米白" : "纱帘-白")
                .seq(seq).operationName(operationName).groupName("裁剪").unit(unit)
                .qty(new BigDecimal(qty)).qtySource(qtySource).unitPrice(new BigDecimal("3.50"))
                .status("pending").doneQty(BigDecimal.ZERO).deleted(0).build();
    }

    /**
     * 从响应里取精裁输出清单：{@code set_overview.cut_plan}（扫码面 / 套件详情面）或
     * 列表行顶层的 {@code cut_plan}。取不到 / 空 ⇒ **断言失败**（不允许判据空跑）。
     */
    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> cutPlanOf(Map<String, Object> carrier) {
        Object cutPlan = carrier.get("set_overview") instanceof Map<?, ?> overview
                ? overview.get("cut_plan")
                : carrier.get("cut_plan");
        if (!(cutPlan instanceof List<?> rows) || rows.isEmpty()) {
            throw new AssertionError("精裁输出清单不存在或为空（判据会空跑）：" + carrier.keySet());
        }
        return (List<Map<String, Object>>) cutPlan;
    }

    /** 清单里某一个部位的行（缺失 ⇒ 断言失败，避免「测试自己空跑」）。 */
    private static Map<String, Object> cutPlanRowOf(List<Map<String, Object>> rows, String orderItemId) {
        for (Map<String, Object> row : rows) {
            if (orderItemId.equals(row.get("order_item_id"))) {
                return row;
            }
        }
        throw new AssertionError("清单里没有部位 " + orderItemId + "（判据会空跑）");
    }

    private static List<Map<String, Object>> positionsOf(Map<String, Object> overview) {
        return (List<Map<String, Object>>) overview.get("positions");
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> operationsOf(Map<String, Object> position) {
        return (List<Map<String, Object>>) position.get("operations");
    }

    private static Map<String, Object> operationOf(Map<String, Object> detail, String operationId) {
        @SuppressWarnings("unchecked")
        Map<String, Object> overview = (Map<String, Object>) detail.get("set_overview");
        for (Map<String, Object> position : positionsOf(overview)) {
            for (Map<String, Object> operation : operationsOf(position)) {
                if (operationId.equals(operation.get("operation_id"))) {
                    return operation;
                }
            }
        }
        throw new AssertionError("总览里没有工序 " + operationId);
    }
}