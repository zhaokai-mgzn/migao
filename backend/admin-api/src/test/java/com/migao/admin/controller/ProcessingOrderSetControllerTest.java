// case_ids: PG-011, PG-018, PG-058
package com.migao.admin.controller;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.databind.JsonNode;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingOrderSet;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingOrderSetMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.ClientRequestIdService;
import com.migao.admin.service.ProcessingSetReadService;
import com.migao.admin.service.ProductionService;
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
import org.springframework.test.web.servlet.MockMvc;

import java.lang.reflect.Method;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.nullValue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 加工套件只读端点（issue #5247 的 admin-api 半边）的**契约测试**：
 * {@code GET /api/admin/processing-order-sets}（列表/分页）、{@code /{id}}（详情）、
 * {@code /scan-progress}（扫码循环进度）。
 *
 * <p><b>装配</b>：standalone MockMvc + **真实** {@link ProcessingSetReadService}（只 mock Mapper）
 * ⇒ 断言的是服务端真实的整形/聚合/过滤，而不是桩（同 {@code ProductionRoutingReadControllerTest}
 * 与 {@code AgentProductionControllerTest} 的既有约定）。</p>
 *
 * <p><b>本类钉住四件事</b>：</p>
 * <ol>
 *   <li><b>键集冻结</b>（同既有冻结契约约定，**不得删键**）：列表信封 4 键 + 行 12 键、详情 12 键、
 *       {@code set_overview} 3 键 / 部位 4 键 / 工序 9 键、扫码进度 10 键 + 每套 8 键；</li>
 *   <li><b>null 值键在场</b>：{@code unit_price} 未定价 ⇒ {@code null}（≠ 0 元，V90 / #4696）、
 *       {@code completed_at} 无领活 ⇒ {@code null}，**都不是省键**；</li>
 *   <li><b>租户 + 软删</b>：查询显式带 {@code tenant_id}/{@code deleted}（判据 = captor 看 wrapper 参数），
 *       且跨租户 / 已软删 / 不存在的套 ⇒ 404（fail-closed）；</li>
 *   <li><b>权限锚定</b>：三个端点**方法级** {@code @RequirePermission("processing:view")}，
 *       且该码 = 兄弟只读端点 {@link ProcessingOrderController} 的生效码（加工套件无侧边栏节点 ⇒
 *       按锚定规则退到第二档；注入「换成 processing:manage」或「兄弟端口径变了」⇒ 本断言红）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("ProcessingOrderSetController 只读端点（issue #5247）")
class ProcessingOrderSetControllerTest extends BaseControllerTest {

    private static final String ORDER_ID = "order-1";
    private static final String ORDER_NO = "SO-20260923-0001";
    private static final String PO_ID = "po-1";
    private static final String PO_NO = "CSO260915-02615";
    private static final String SET_ID = "set-14";
    private static final String SET_NO = PO_NO + "-014";
    private static final String ITEM_CLOTH = "oi-cloth";
    private static final String ITEM_GAUZE = "oi-gauze";
    /** 锚定码：加工套件无菜单节点 ⇒ 取兄弟读端点的生效码（{@code ProcessingOrderController} 的 GET）。 */
    // issue #5246：兄弟锚点（`ProcessingOrderController` 的 GET）从 processing:view 收窄为
    // processing:manage（processing:view 在四处菜单源里没有任何节点 ⇒ 持它的岗位能读到页面里
    // 看不到的生产数据，用户裁定禁止）⇒ 本控制器的锚**同步跟随**（方向只收窄）。
    // 本常量仍与两端点断言并用：兄弟再动 ⇒ 必红。
    private static final String ANCHOR_PERMISSION = "processing:manage";

    private static final List<String> PAGE_KEYS = List.of("total", "page", "size", "items");
    private static final List<String> LIST_ROW_KEYS = List.of("set_id", "set_no", "set_index", "craft_line_id",
            "processing_order_id", "processing_order_no", "order_id", "order_no", "total_operations",
            "done_operations", "progress_percent", "completed");
    private static final List<String> DETAIL_KEYS = List.of("set_id", "set_no", "set_index", "craft_line_id",
            "processing_order_id", "processing_order_no", "order_id", "order_no", "completed", "completed_at",
            "set_overview", "progress");
    private static final List<String> OVERVIEW_KEYS = List.of("set_no", "set_index", "positions");
    private static final List<String> POSITION_KEYS =
            List.of("order_item_id", "position_kind", "position_name", "operations");
    private static final List<String> OPERATION_KEYS = List.of("operation_id", "logical_name", "position",
            "seq", "qty", "unit", "unit_price", "status", "done_qty");
    private static final List<String> PROGRESS_KEYS = List.of("total", "done", "percent");
    private static final List<String> SCAN_PROGRESS_KEYS = List.of("order_id", "order_no",
            "processing_order_id", "processing_order_no", "total_sets", "completed_sets", "total_operations",
            "done_operations", "progress_percent", "sets");
    private static final List<String> SCAN_PROGRESS_SET_KEYS = List.of("set_id", "set_no", "set_index",
            "completed", "completed_at", "total_operations", "done_operations", "progress_percent");

    private MockMvc mockMvc;

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
    private ClientRequestIdService clientRequestIdService;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        // 真实服务（只 mock Mapper）：端点的响应形状 = 生产装配的那一份
        ProductionService productionService = new ProductionService(processingOrderMapper,
                positionOperationMapper, workLogMapper, orderMapper, orderItemMapper, clientRequestIdService);
        ProcessingSetReadService readService = new ProcessingSetReadService(orderSetMapper,
                positionOperationMapper, orderItemMapper, processingOrderMapper, orderMapper, productionService);
        mockMvc = buildMockMvc(new ProcessingOrderSetController(readService));
    }

    @AfterEach
    void tearDown() {
        super.baseTearDown();
    }

    // ══════════════════ 交付物 1：GET /api/admin/processing-order-sets

    @Test
    @DisplayName("GET / → 200 + 分页信封键集冻结（4 键）+ 行键集冻结（12 键）")
    void listFreezesKeySets() throws Exception {
        stubList();

        String body = mockMvc.perform(get("/api/admin/processing-order-sets")
                        .param("page", "1").param("size", "20"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.total").value(1))
                .andExpect(jsonPath("$.data.page").value(1))
                .andExpect(jsonPath("$.data.size").value(20))
                .andExpect(jsonPath("$.data.items[0].set_no").value(SET_NO))
                .andExpect(jsonPath("$.data.items[0].set_index").value(14))
                .andExpect(jsonPath("$.data.items[0].processing_order_no").value(PO_NO))
                .andExpect(jsonPath("$.data.items[0].order_no").value(ORDER_NO))
                .andExpect(jsonPath("$.data.items[0].total_operations").value(3))
                .andExpect(jsonPath("$.data.items[0].done_operations").value(2))
                .andExpect(jsonPath("$.data.items[0].progress_percent").value(67))
                .andExpect(jsonPath("$.data.items[0].completed").value(false))
                .andReturn().getResponse().getContentAsString();

        JsonNode data = objectMapper.readTree(body).path("data");
        assertThat(keysOf(data)).containsExactlyInAnyOrderElementsOf(PAGE_KEYS);
        assertThat(keysOf(data.path("items").get(0))).as("列表行键集冻结：不得删键")
                .containsExactlyInAnyOrderElementsOf(LIST_ROW_KEYS);
    }

    @Test
    @DisplayName("🔴 列表查询显式带 tenant_id + deleted=0（不靠多租户拦截器）")
    void listQueryCarriesTenantAndDeleted() throws Exception {
        stubList();

        mockMvc.perform(get("/api/admin/processing-order-sets")).andExpect(status().isOk());

        @SuppressWarnings("unchecked")
        ArgumentCaptor<QueryWrapper<ProcessingOrderSet>> captor = ArgumentCaptor.forClass(QueryWrapper.class);
        verify(orderSetMapper).selectPage(any(), captor.capture());
        QueryWrapper<ProcessingOrderSet> wrapper = captor.getValue();
        // MP 的 wrapper 参数是**惰性**的（物化 SQL 段才落 paramNameValuePairs）；
        // 字符串列名 ⇒ 物化不需要 TableInfo 缓存，standalone 单测里可安全取
        assertThat(wrapper.getSqlSegment()).as("查询条件里必须有这两列").contains("tenant_id", "deleted");
        assertThat(wrapper.getParamNameValuePairs().values())
                .as("tenant_id=1（TEST_TENANT_ID）+ deleted=0 必须显式在场")
                .contains(TEST_TENANT_ID, 0);
    }

    @Test
    @DisplayName("按加工单号过滤 + 每页条数收敛（size 超上限按 100，不报错）")
    void listFiltersByProcessingOrderNoAndClampsSize() throws Exception {
        stubList();
        when(processingOrderMapper.selectOne(any())).thenReturn(po());

        mockMvc.perform(get("/api/admin/processing-order-sets")
                        .param("processingOrderNo", PO_NO).param("size", "999"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.size").value(100))
                .andExpect(jsonPath("$.data.items[0].processing_order_no").value(PO_NO));

        verify(processingOrderMapper).selectOne(any());
    }

    // ══════════════════ 交付物 2：GET /api/admin/processing-order-sets/{id}

    @Test
    @DisplayName("GET /{id} → 200 + 详情键集冻结（12 键）+ set_overview 三层键集冻结")
    void detailFreezesKeySets() throws Exception {
        stubDetail();

        String body = mockMvc.perform(get("/api/admin/processing-order-sets/" + SET_ID))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.set_id").value(SET_ID))
                .andExpect(jsonPath("$.data.set_no").value(SET_NO))
                .andExpect(jsonPath("$.data.processing_order_no").value(PO_NO))
                .andExpect(jsonPath("$.data.order_no").value(ORDER_NO))
                .andExpect(jsonPath("$.data.completed").value(false))
                .andExpect(jsonPath("$.data.set_overview.set_no").value(SET_NO))
                .andExpect(jsonPath("$.data.progress.total").value(3))
                .andExpect(jsonPath("$.data.progress.done").value(2))
                .andExpect(jsonPath("$.data.progress.percent").value(67))
                .andReturn().getResponse().getContentAsString();

        JsonNode data = objectMapper.readTree(body).path("data");
        assertThat(keysOf(data)).as("详情键集冻结：不得删键")
                .containsExactlyInAnyOrderElementsOf(DETAIL_KEYS);
        assertThat(keysOf(data.path("progress"))).containsExactlyInAnyOrderElementsOf(PROGRESS_KEYS);

        JsonNode overview = data.path("set_overview");
        assertThat(keysOf(overview)).containsExactlyInAnyOrderElementsOf(OVERVIEW_KEYS);
        JsonNode position = overview.path("positions").get(0);
        assertThat(keysOf(position)).as("部位键集冻结（缺值给 null 而不是省键）")
                .containsExactlyInAnyOrderElementsOf(POSITION_KEYS);
        for (JsonNode operation : position.path("operations")) {
            assertThat(keysOf(operation)).as("工序 9 键冻结（对应设计 §4.1 的应做/单位/单价/状态/已报）")
                    .containsExactlyInAnyOrderElementsOf(OPERATION_KEYS);
        }
    }

    @Test
    @DisplayName("🔴 未定价不折 0 + 无领活给 null：unit_price / completed_at 键在场且值为 null")
    void detailKeepsNullValuedKeysPresent() throws Exception {
        stubDetail();

        mockMvc.perform(get("/api/admin/processing-order-sets/" + SET_ID))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.completed_at").value(nullValue()))
                .andExpect(jsonPath("$.data.set_overview.positions[0].operations[1].operation_id").value("op-2"))
                .andExpect(jsonPath("$.data.set_overview.positions[0].operations[1].unit_price")
                        .value(nullValue()))
                .andExpect(jsonPath("$.data.set_overview.positions[0].operations[1].done_qty").value(6.00));
    }

    @Test
    @DisplayName("🔴 跨租户 / 已软删 / 不存在的套 ⇒ 404（fail-closed）")
    void detailIs404ForCrossTenantOrDeleted() throws Exception {
        when(orderSetMapper.selectById(SET_ID)).thenReturn(setWith(99L, 0));
        mockMvc.perform(get("/api/admin/processing-order-sets/" + SET_ID))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.success").value(false));

        when(orderSetMapper.selectById(SET_ID)).thenReturn(setWith(TEST_TENANT_ID, 1));
        mockMvc.perform(get("/api/admin/processing-order-sets/" + SET_ID))
                .andExpect(status().isNotFound());

        when(orderSetMapper.selectById(SET_ID)).thenReturn(null);
        mockMvc.perform(get("/api/admin/processing-order-sets/" + SET_ID))
                .andExpect(status().isNotFound());
    }

    // ══════════════════ 交付物 3：GET /api/admin/processing-order-sets/scan-progress

    @Test
    @DisplayName("GET /scan-progress → 200 + 键集冻结（10 键 + 每套 8 键）+ 汇总口径")
    void scanProgressFreezesKeySets() throws Exception {
        stubList();
        when(processingOrderMapper.selectOne(any())).thenReturn(po());

        String body = mockMvc.perform(get("/api/admin/processing-order-sets/scan-progress")
                        .param("processingOrderNo", PO_NO))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.processing_order_no").value(PO_NO))
                .andExpect(jsonPath("$.data.order_no").value(ORDER_NO))
                .andExpect(jsonPath("$.data.total_sets").value(1))
                .andExpect(jsonPath("$.data.completed_sets").value(0))
                .andExpect(jsonPath("$.data.total_operations").value(3))
                .andExpect(jsonPath("$.data.done_operations").value(2))
                .andExpect(jsonPath("$.data.progress_percent").value(67))
                .andExpect(jsonPath("$.data.sets[0].set_no").value(SET_NO))
                .andExpect(jsonPath("$.data.sets[0].completed").value(false))
                .andReturn().getResponse().getContentAsString();

        JsonNode data = objectMapper.readTree(body).path("data");
        assertThat(keysOf(data)).containsExactlyInAnyOrderElementsOf(SCAN_PROGRESS_KEYS);
        assertThat(keysOf(data.path("sets").get(0))).containsExactlyInAnyOrderElementsOf(SCAN_PROGRESS_SET_KEYS);
    }

    @Test
    @DisplayName("GET /scan-progress 缺标识 ⇒ 422；加工单号查不到 ⇒ 404")
    void scanProgressRejectsMissingAndUnknownIdentifiers() throws Exception {
        mockMvc.perform(get("/api/admin/processing-order-sets/scan-progress"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.success").value(false));

        when(processingOrderMapper.selectOne(any())).thenReturn(null);
        mockMvc.perform(get("/api/admin/processing-order-sets/scan-progress")
                        .param("processingOrderNo", "CSO-NOT-EXIST"))
                .andExpect(status().isNotFound());
    }

    // ══════════════════ 权限锚定（#5246 / #5247 的判据）

    @Test
    @DisplayName("🔴 三个端点都有**方法级** @RequirePermission，且锚 = 兄弟读端点的生效码 processing:view")
    void everyEndpointDeclaresMethodLevelPermission() throws Exception {
        for (String name : List.of("list", "detail", "scanProgress")) {
            Method method = Arrays.stream(ProcessingOrderSetController.class.getDeclaredMethods())
                    .filter(m -> m.getName().equals(name)).findFirst()
                    .orElseThrow(() -> new AssertionError("端点方法不存在：" + name));
            RequirePermission annotation = method.getAnnotation(RequirePermission.class);
            assertThat(annotation).as("%s 必须声明方法级 @RequirePermission（#5246 权限一致性判据）", name)
                    .isNotNull();
            assertThat(annotation.value()).as("%s 的锚定码（加工套件无菜单节点 ⇒ 兄弟读端点的生效码）", name)
                    .isEqualTo(ANCHOR_PERMISSION);
        }
        assertThat(ProcessingOrderSetController.class.getAnnotation(RequirePermission.class))
                .as("逐端点方法级声明（不靠类级一把抓）").isNull();

        // 锚定判据的**另一半**：兄弟只读端点（同实体族）的生效码必须仍是 processing:view
        // ⇒ 它若改码，本断言红，逼一次锚定复核（不静默漂移）。
        Method sibling = ProcessingOrderController.class.getDeclaredMethod("list", String.class, String.class);
        assertThat(sibling.getAnnotation(RequirePermission.class).value())
                .as("锚定来源：ProcessingOrderController 的 GET 生效码").isEqualTo(ANCHOR_PERMISSION);
    }

    // ══════════════════ 夹具 / 工具

    private void stubList() {
        Page<ProcessingOrderSet> page = new Page<>(1, 20);
        page.setRecords(List.of(set()));
        page.setTotal(1L);
        when(orderSetMapper.selectPage(any(), any())).thenReturn(page);
        when(orderSetMapper.selectList(any())).thenReturn(List.of(set()));
        when(positionOperationMapper.selectList(any())).thenReturn(ops());
        when(processingOrderMapper.selectById(PO_ID)).thenReturn(po());
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order());
    }

    private void stubDetail() {
        when(orderSetMapper.selectById(SET_ID)).thenReturn(set());
        when(processingOrderMapper.selectById(PO_ID)).thenReturn(po());
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order());
        when(positionOperationMapper.selectList(any())).thenReturn(ops());
    }

    private ProcessingOrderSet set() {
        return setWith(TEST_TENANT_ID, 0);
    }

    private ProcessingOrderSet setWith(Long tenantId, int deleted) {
        return ProcessingOrderSet.builder().id(SET_ID).tenantId(tenantId).processingOrderId(PO_ID)
                .setIndex(14).setNo(SET_NO).craftLineId(ITEM_CLOTH)
                .positionItemIds(List.of(ITEM_CLOTH, ITEM_GAUZE)).deleted(deleted).build();
    }

    private ProcessingOrder po() {
        return ProcessingOrder.builder().id(PO_ID).tenantId(TEST_TENANT_ID).orderId(ORDER_ID)
                .processingOrderNo(PO_NO).status("in_processing").deleted(0).build();
    }

    private Order order() {
        return Order.builder().id(ORDER_ID).tenantId(TEST_TENANT_ID).orderNo(ORDER_NO)
                .status("producing").deleted(0).build();
    }

    /** 布帘 2 道（1 完成 + 1 待做且**未定价**）+ 纱帘 1 道（完成）⇒ 2/3 = 67%。 */
    private List<ProcessingPositionOperation> ops() {
        return List.of(
                op("op-1", ITEM_CLOTH, "布帘", 1, "精裁-布", "3.50", "12.30", "12.30", "done"),
                op("op-2", ITEM_CLOTH, "布帘", 2, "定型-布", null, "11.00", "6.00", "pending"),
                op("op-3", ITEM_GAUZE, "纱帘", 1, "三边-纱", "2.00", "8.00", "8.00", "done"));
    }

    private ProcessingPositionOperation op(String id, String orderItemId, String positionKind, int seq,
                                           String operationName, String unitPrice, String qty, String doneQty,
                                           String status) {
        return ProcessingPositionOperation.builder().id(id).tenantId(TEST_TENANT_ID)
                .processingOrderId(PO_ID).setId(SET_ID).setNo(SET_NO).orderItemId(orderItemId)
                .positionKind(positionKind)
                .positionName("布帘".equals(positionKind) ? "布艺遮光帘A 米白" : "纱帘-白")
                .seq(seq).operationName(operationName).groupName("车位").unit("米")
                .qty(new BigDecimal(qty)).qtySource("fabric_meters")
                .unitPrice(unitPrice == null ? null : new BigDecimal(unitPrice))
                .status(status).doneQty(new BigDecimal(doneQty)).deleted(0).build();
    }

    private static List<String> keysOf(JsonNode node) {
        List<String> keys = new ArrayList<>();
        node.fieldNames().forEachRemaining(keys::add);
        return keys;
    }
}