// case_ids: PG-046, PG-018
package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingOrderSet;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProcessingSetPartToken;
import com.migao.admin.entity.ProductAttribute;
import com.migao.admin.mapper.CuttingHeightConfigMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingOrderSetMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProcessingSetPartTokenMapper;
import com.migao.admin.mapper.ProductAttributeMapper;
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

import java.io.IOException;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * 工人端**三条**读面的「部位明细键」同源守卫（母单 #6901，面①）。
 *
 * <h2>治什么</h2>
 * <p>工人端有三条读面都在下发「这个部位是什么规格」，而它们此前各拼各的键：</p>
 * <ol>
 *   <li>扫码详情面 —— {@code ProductionScanService} 的 {@code set_overview.positions[]} /
 *       旧码 {@code selections[].positions[]}；</li>
 *   <li>工序读面 —— {@code ProductionService#getOperations} 的 {@code positions[]}
 *       （机台/小程序/商家共用的那条）；</li>
 *   <li>机台面 —— {@code WorkerCuttingHeightService#positionRow}
 *       （{@code /api/worker/production/cutting-height}，一体机屏一）。</li>
 * </ol>
 * <p>各写一份 ⇒ 「加了一个字段，某一屏静默缺失」—— 这正是用户 2026-10-14 的原始抱怨
 * （「加工单缺乏订单中的规格尺寸和加工信息，工人需要这些信息+商品信息来决定如何生产」）。
 * ⇒ 键清单只有一份（{@link PositionSpecFields}），三条读面逐键同源；本文件把这条**同源**钉成判据。</p>
 *
 * <h2>判据（每条都能红 —— 红证读数见 PR body）</h2>
 * <ol>
 *   <li><b>① 扫码面 = 全键集</b>：{@code set_overview.positions[]} 与旧码
 *       {@code selections[].positions[]} 的键集**逐字等于** {@code PositionSpecFields.DETAIL_KEYS} + 既有四键；
 *       把 {@code fillDetailKeys} 拆回「只给 9 键」⇒ 红（键集不等，且报出缺哪几个键）；</li>
 *   <li><b>② 工序面 ⊇ 全键集</b>：{@code getOperations.positions[]} 是 {@code putAll(spec)} ⇒ 天然全键；
 *       把 {@code orderSpecByItemId} 的某个键删掉 ⇒ 红；</li>
 *   <li><b>③ 机台面 ⊇ 全键集 − 具名排除项</b>：{@code positionRow} 已有值的键（{@code width} 取自
 *       {@code order_items} 列、{@code fabric_meters} 取自 {@code fabricMeters(scan)}）**值逐字不变**，
 *       新增键补齐；把 {@code fillDetailKeys} 从 {@code positionRow} 摘掉 ⇒ 红；</li>
 *   <li><b>④ 前端标签表 ⊇ 全键集</b>：报工屏 / 机台屏共用 `frontend/worker-h5/src/position-spec.mjs`
 *       的 {@code POSITION_SPEC_KEYS}（**现取**该文件的键，不在本测试里另抄一份键名清单）——
 *       后端加键而前端表没跟上 ⇒ 红（未登记即红）。</li>
 * </ol>
 *
 * <p>🔴 <b>为什么必须现取</b>：若本文件再抄一份键名清单，那份清单就是**第二份会漂的口径**
 * （后端加键、测试照旧绿）。故 ①③④ 的期望值全部来自真源：{@code PositionSpecFields.DETAIL_KEYS}
 * 与前端模块源码。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("工人端三条读面的部位明细键同源守卫（母单 #6901）")
class PositionSpecFieldsTest {

    private static final Long TENANT = 1L;
    private static final String ORDER_ID = "order-6901";
    private static final String PO_ID = "po-6901";
    private static final String PO_NO = "CSO261014-06901";
    private static final String SET_ID = "set-6901";
    private static final String ITEM_ID = "oi-6901";
    private static final String CODE = "scan-detail-6901";
    private static final String OPERATION_ID = "op-6901";

    /** 既有四键（P0-C / issue #5685）—— 明细键的**基线**，本次未动。 */
    private static final List<String> EXISTING_KEYS = List.of(
            "order_item_id", "position_kind", "position_name", "remark");

    /** 工序读面（{@code getOperations}）多出来的键：本就不是「部位规格」。 */
    private static final List<String> OPERATIONS_SURFACE_ONLY_KEYS = List.of(
            "set_no", "operations", "part_token", "part_short_code", "scan_url");

    /** 前端共享标签表的路径（仓根相对）—— 从真源**现取**，不在本文件另抄键名。 */
    private static final Path FRONTEND_SPEC_MODULE =
            Path.of("..", "..", "frontend", "worker-h5", "src", "position-spec.mjs");

    private static final Pattern FRONTEND_SPEC_ARRAY =
            Pattern.compile("POSITION_SPEC_KEYS\\s*=\\s*\\[(.*?)\\n\\]", Pattern.DOTALL);
    private static final Pattern FRONTEND_KEY = Pattern.compile("\\{\\s*key:\\s*'([a-z0-9_]+)'");

    @Mock
    private ProcessingSetPartTokenMapper setPartTokenMapper;
    @Mock
    private ProcessingOrderSetMapper processingOrderSetMapper;
    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private ProcessingPositionOperationMapper positionOperationMapper;
    @Mock
    private OrderMapper orderMapper;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private ProductionWorkLogMapper workLogMapper;
    @Mock
    private ProductionOperationQueryService operationQueryService;
    @Mock
    private ClientRequestIdService clientRequestIdService;
    @Mock
    private CuttingHeightConfigMapper cuttingHeightConfigMapper;
    @Mock
    private ProductAttributeMapper productAttributeMapper;

    private ProductionService productionService;
    private ProductionScanService scanService;
    private WorkerCuttingHeightService cuttingHeightService;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        // 真实现（只 mock Mapper）：三条读面共用的正是这些真实现（`orderSpecByItemId` /
        // `fillDetailKeys` / `positionRow`）—— mock 掉它们等于把被测口径换成桩（「绿了但没跑」）。
        productionService = new ProductionService(processingOrderMapper, positionOperationMapper,
                workLogMapper, orderMapper, orderItemMapper, clientRequestIdService);
        ProductionStuckPointService stuckPointService = new ProductionStuckPointService(
                productionService, positionOperationMapper, processingOrderSetMapper, 4.0);
        scanService = new ProductionScanService(setPartTokenMapper, processingOrderSetMapper, processingOrderMapper,
                operationQueryService, productionService, stuckPointService,
                new ProcessingSetReadService(processingOrderSetMapper, positionOperationMapper, orderItemMapper,
                        processingOrderMapper, orderMapper, productionService),
                orderMapper);
        CuttingHeightConfigService configService = new CuttingHeightConfigService(cuttingHeightConfigMapper,
                new TenantParamAuditService(org.mockito.Mockito.mock(com.migao.admin.mapper.TenantParamAuditMapper.class),
                        new io.micrometer.core.instrument.simple.SimpleMeterRegistry(),
                        new com.fasterxml.jackson.databind.ObjectMapper()));
        cuttingHeightService = new WorkerCuttingHeightService(scanService, configService, orderItemMapper,
                orderMapper, processingOrderMapper, processingOrderSetMapper, productAttributeMapper);
        when(orderItemMapper.selectById(any())).thenReturn(null);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ============================================================ ① 扫码面

    @Test
    @DisplayName("① 扫码面（set_overview + 旧码 selections）的键集 = 全键集，值与订单行逐值一致")
    void scanSurfaceCarriesTheWholeKeySet() {
        stubScan();
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItem()));

        Map<String, Object> cloth = positionOf(overviewPositions(scanService.resolve(CODE, null, TENANT)));

        assertThat(cloth.keySet()).containsExactlyInAnyOrderElementsOf(
                concat(EXISTING_KEYS, PositionSpecFields.DETAIL_KEYS, "operations"));
        // 值逐字来自订单行（同一份 `orderSpecByItemId` 取数）
        assertThat(cloth.get("sku")).isEqualTo("MG-006901");
        assertThat(cloth.get("color_name")).isEqualTo("雾霾蓝");
        assertThat(cloth.get("door_width")).isEqualTo("2.8");
        assertThat(cloth.get("selling_method")).isEqualTo("bulk_cut");
        assertThat(cloth.get("unit")).isEqualTo("米");
        assertThat(cloth.get("fullness_actual")).isEqualTo(new BigDecimal("2.35"));
        assertThat(cloth.get("pleat_count")).isEqualTo(48);
        assertThat(cloth.get("per_panel_pleats")).isEqualTo(24);
        assertThat(cloth.get("panels")).isEqualTo(2);
        assertThat(cloth.get("formula")).isEqualTo("窗宽×褶倍÷门幅");
        assertThat(cloth.get("craft_tier")).isEqualTo("标准");
        assertThat(cloth.get("special_options")).isEqualTo(List.of("加线", "包边"));
        assertThat(cloth.get("style")).isEqualTo("拼色");
        assertThat(cloth.get("has_pattern")).isEqualTo(true);
        assertThat(cloth.get("pattern_repeat")).isEqualTo(new BigDecimal("0.32"));
        assertThat(cloth.get("processing_meters")).isEqualTo(new BigDecimal("8.10"));
        assertThat(cloth.get("formula_text")).isEqualTo("2.8×2÷1.5=3.73→4");
        assertThat(cloth.get("component_role")).isEqualTo("主布");
        // 既有 9 键（P0-C）值一字未变
        assertThat(cloth.get("width")).isEqualTo(new BigDecimal("2.92"));
        assertThat(cloth.get("craft")).isEqualTo("韩褶");
        assertThat(cloth.get("fabric_meters")).isEqualTo(new BigDecimal("12.35"));

        // 旧码降级清单的 selections[].positions[] 同批同键（同一展厅屏不出现两套形状）
        Map<String, Object> legacy = legacyPositionOf();
        assertThat(legacy.keySet()).containsExactlyInAnyOrderElementsOf(
                concat(EXISTING_KEYS, PositionSpecFields.DETAIL_KEYS, "operations"));
    }

    @Test
    @DisplayName("①-b 缺值 ⇒ 键恒在且为 null（不省键、不猜 0 / false / 空串）")
    void scanSurfaceKeepsNullKeysForMissingValues() {
        stubScan();
        // 订单行只有商品名（存量单：processing_info 为 NULL、工艺列全空）
        OrderItem bare = new OrderItem();
        bare.setId(ITEM_ID);
        bare.setTenantId(TENANT);
        bare.setOrderId(ORDER_ID);
        bare.setProductName("裸单商品");
        when(orderItemMapper.selectList(any())).thenReturn(List.of(bare));

        Map<String, Object> cloth = positionOf(overviewPositions(scanService.resolve(CODE, null, TENANT)));

        for (String key : PositionSpecFields.DETAIL_KEYS) {
            assertThat(cloth).containsKey(key);
        }
        for (String key : PositionSpecFields.DETAIL_KEYS) {
            if ("product_name".equals(key)) {
                continue;
            }
            assertThat(cloth.get(key))
                    .as("键 %s 的源缺失 ⇒ 必须是 null（不得折成 0 / false / 空串）", key)
                    .isNull();
        }
        assertThat(cloth.get("product_name")).isEqualTo("裸单商品");
    }

    // ============================================================ ② 工序读面

    @Test
    @DisplayName("② 工序读面（getOperations.positions[]）⊇ 全键集（本条是面③b 包 B 的取数前提）")
    void operationsSurfaceCarriesTheWholeKeySet() {
        stubScan();
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItem()));

        Map<String, Object> result = productionService.getOperations(ORDER_ID, TENANT);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> positions = (List<Map<String, Object>>) result.get("positions");
        Map<String, Object> cloth = positions.stream()
                .filter(p -> ITEM_ID.equals(p.get("order_item_id")))
                .findFirst()
                .orElseThrow(() -> new AssertionError("工序读面里没有 " + ITEM_ID));

        assertThat(cloth.keySet()).containsAll(PositionSpecFields.DETAIL_KEYS);
        assertThat(cloth.keySet()).containsAll(OPERATIONS_SURFACE_ONLY_KEYS);
        // 值与扫码面**逐值同源**（同一份 `orderSpecByItemId`）
        assertThat(cloth.get("sku")).isEqualTo("MG-006901");
        assertThat(cloth.get("color_name")).isEqualTo("雾霾蓝");
        assertThat(cloth.get("craft_tier")).isEqualTo("标准");
        assertThat(cloth.get("component_role")).isEqualTo("主布");
    }

    // ============================================================ ③ 机台面

    @Test
    @DisplayName("③ 机台面（cutting-height positions[]）⊇ 全键集 − 具名排除项，且既有键值/来源一字未变")
    void machineSurfaceCarriesTheWholeKeySetWithoutRemarkAlias() {
        stubScan();
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItem()));
        when(orderMapper.selectOne(any())).thenReturn(order());
        when(processingOrderMapper.selectList(any())).thenReturn(List.of(processingOrder()));
        when(processingOrderSetMapper.selectCount(any())).thenReturn(1L);
        when(productAttributeMapper.selectList(any())).thenReturn(List.of(
                ProductAttribute.builder().tenantId(TENANT).productId("p-1")
                        .attrKey("brand").attrValue("观星台").build()));

        Map<String, Object> out = cuttingHeightService.read(CODE, TENANT);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> positions = (List<Map<String, Object>>) out.get("positions");
        Map<String, Object> cloth = positions.get(0);

        Set<String> expected = new LinkedHashSet<>(PositionSpecFields.DETAIL_KEYS);
        expected.removeAll(WorkerCuttingHeightService.MACHINE_ROW_EXCLUDED_KEYS);
        assertThat(cloth.keySet()).containsAll(expected);
        // 🔴 具名排除项：本面上同一件事实的键名是 `position_remark`，**不得**再多一个 `remark` 别名
        assertThat(WorkerCuttingHeightService.MACHINE_ROW_EXCLUDED_KEYS).containsExactly("remark");
        assertThat(cloth).doesNotContainKey("remark");
        assertThat(cloth.get("position_remark")).isEqualTo("左窗");
        // 🔴 负控：既有键的**值与来源**一字未变（机台屏取值自订单行 `order_items` 列）——
        // `width`/`height`/`craft`/`curtain_type`/`open_count`/`cutting_mode`/`fullness` 不得被快照覆盖
        assertThat(cloth.get("width")).isEqualTo(new BigDecimal("2.92"));
        assertThat(cloth.get("height")).isEqualTo(new BigDecimal("2.60"));
        assertThat(cloth.get("craft")).isEqualTo("韩褶");
        assertThat(cloth.get("curtain_type")).isEqualTo("布帘");
        assertThat(cloth.get("open_count")).isEqualTo(2);
        assertThat(cloth.get("cutting_mode")).isEqualTo("定高买宽");
        assertThat(cloth.get("fullness")).isEqualTo(new BigDecimal("2.0"));
        // 新增键（此前机台屏**没有**的组 1 / 组 3 / 组 5）
        assertThat(cloth.get("sku")).isEqualTo("MG-006901");
        assertThat(cloth.get("color_name")).isEqualTo("雾霾蓝");
        assertThat(cloth.get("door_width")).isEqualTo("2.8");
        assertThat(cloth.get("fullness_actual")).isEqualTo(new BigDecimal("2.35"));
        assertThat(cloth.get("pleat_count")).isEqualTo(48);
        assertThat(cloth.get("panels")).isEqualTo(2);
        assertThat(cloth.get("component_role")).isEqualTo("主布");
    }

    // ============================================================ ②′ 双名共存 ⇒ 不漂移

    /**
     * 同一件事实在工序读面上有**两个键名**（camelCase 兼容支 + snake_case canonical 支）——
     * 这是**有意的例外**（改名 = 打回既有消费方；登记见 {@code docs/wiki/CONTRACT-LEDGER.md} §九）。
     * 例外的代价必须由判据兜住：**只要两侧都有值就必须逐值相等**。
     *
     * <p>孪生对照**现取**：camelCase 一侧从 {@code OrderLineCraftFields.toSnapshotKeys} **实跑**取键
     * （喂一个字段齐全的订单行），snake_case 一侧取 {@code PositionSpecFields.DETAIL_KEYS} 的交集
     * ⇒ 本测试**不手抄**任何键名清单。</p>
     */
    @Test
    @DisplayName("②′ 双名共存不漂移：camelCase 兼容支 与 snake_case canonical 支**逐值相等**")
    void twinKeysNeverDrift() {
        stubScan();
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItem()));

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> positions = (List<Map<String, Object>>)
                productionService.getOperations(ORDER_ID, TENANT).get("positions");
        Map<String, Object> cloth = positions.stream()
                .filter(p -> ITEM_ID.equals(p.get("order_item_id")))
                .findFirst()
                .orElseThrow(() -> new AssertionError("工序读面里没有 " + ITEM_ID));

        Set<String> camelKeys = new LinkedHashSet<>(OrderLineCraftFields.toSnapshotKeys(orderItem()).keySet());
        Set<String> twins = new LinkedHashSet<>(camelKeys);
        twins.retainAll(PositionSpecFields.DETAIL_KEYS);
        // 台账不许空转：一对孪生键都取不到 ⇒ 本判据恒绿（那是"没跑"而不是"通过"）
        assertThat(twins).as("孪生键必须**现取**到（样本里两侧都有值）").isNotEmpty();

        for (String camel : twins) {
            // snake_case 一侧的键名 = camelCase 的 snake_case 化（**生成规则现取**，不手抄键名清单）
            String snake = camel.replaceAll("([a-z0-9])([A-Z])", "$1_$2").toLowerCase(java.util.Locale.ROOT);
            if (!PositionSpecFields.DETAIL_KEYS.contains(snake)) {
                continue; // 该 camelCase 键没有 canonical 孪生（如 `corner`）⇒ 不在本判据射程
            }
            assertThat(cloth).as("孪生键 %s 的两支都必须在该读面上", snake).containsKeys(camel, snake);
            assertThat(cloth.get(snake))
                    .as("孪生键 %s / %s 两支的值必须逐值相等（只改一边 ⇒ 静默漂移）", camel, snake)
                    .isEqualTo(cloth.get(camel));
        }
        // 同名（非孪生）键照旧只一支：`product_name` / `width` / `height` / `remark` / `sku`
        assertThat(cloth).containsKeys("product_name", "width", "height", "remark", "sku");
        assertThat(cloth).doesNotContainKey("productName");
        assertThat(cloth).doesNotContainKey("skuCode");
    }

    // ============================================================ ④ 前端标签表

    @Test
    @DisplayName("④ 前端共享标签表（position-spec.mjs）⊇ 全键集 —— 后端加键而前端没跟上 ⇒ 红")
    void frontendLabelTableCoversTheWholeKeySet() throws IOException {
        Path module = FRONTEND_SPEC_MODULE.toAbsolutePath().normalize();
        assertThat(Files.exists(module))
                .as("前端共享标签表必须存在（母单 #6901 的「标签只许一份」承载面）：%s", module)
                .isTrue();
        Set<String> frontendKeys = readFrontendSpecKeys(Files.readString(module));

        assertThat(frontendKeys)
                .as("后端 DETAIL_KEYS 里的每个键都必须在前端标签表里登记（否则该键在工人屏上永远不显示）")
                .containsAll(PositionSpecFields.DETAIL_KEYS);
        // 反向：前端表里不得登记后端根本不发的键（登记了也会静默空转 —— 那是第二份会漂的口径）
        assertThat(PositionSpecFields.DETAIL_KEYS).containsAll(frontendKeys);
        // 台账不许空转：真取到键才算数（空集会让上面两条恒绿）
        assertThat(frontendKeys.size()).isGreaterThanOrEqualTo(PositionSpecFields.DETAIL_KEYS.size());
        assertThat(frontendKeys).isNotEmpty();
    }

    // ============================================================ 夹具

    /** 从前端模块源码里**现取** `POSITION_SPEC_KEYS` 的键集（不在这里另抄一份键名清单）。 */
    private static Set<String> readFrontendSpecKeys(String source) {
        Matcher array = FRONTEND_SPEC_ARRAY.matcher(source);
        assertThat(array.find()).as("前端模块里必须能定位到 POSITION_SPEC_KEYS 数组字面量").isTrue();
        Set<String> keys = new LinkedHashSet<>();
        Matcher key = FRONTEND_KEY.matcher(array.group(1));
        while (key.find()) {
            keys.add(key.group(1));
        }
        return keys;
    }

    private void stubScan() {
        // ⚠️ **两处**都要给订单行：`orderSpecByItemId` 走 `selectList`（按 order_id 查行），
        // `WorkerCuttingHeightService.itemsOf` 走 `selectByOrderId` —— 两条链各自取数（本仓既有形态）。
        when(orderItemMapper.selectByOrderId(ORDER_ID, TENANT)).thenReturn(List.of(orderItem()));
        when(setPartTokenMapper.selectOne(any())).thenReturn(ProcessingSetPartToken.builder()
                .id("pt-1").tenantId(TENANT).token(CODE)
                .processingOrderId(PO_ID).setId(SET_ID).orderItemId(ITEM_ID)
                .positionKind("布帘").deleted(0).build());
        when(processingOrderSetMapper.selectById(SET_ID)).thenReturn(ProcessingOrderSet.builder()
                .id(SET_ID).tenantId(TENANT).processingOrderId(PO_ID)
                .setIndex(1).setNo(PO_NO + "-001").deleted(0).build());
        when(processingOrderMapper.selectById(PO_ID)).thenReturn(processingOrder());
        when(processingOrderMapper.selectOne(any())).thenReturn(processingOrder());
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder());
        when(processingOrderSetMapper.selectList(any())).thenReturn(List.of(ProcessingOrderSet.builder()
                .id(SET_ID).tenantId(TENANT).processingOrderId(PO_ID)
                .setIndex(1).setNo(PO_NO + "-001").deleted(0).build()));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(operation()));
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order());
    }

    private Map<String, Object> legacyPositionOf() {
        when(setPartTokenMapper.selectOne(any())).thenReturn(null);
        Map<String, Object> result = scanService.resolve("legacy-scan-6901", null, TENANT);
        assertThat(result.get("granularity")).isEqualTo("order");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> selections = (List<Map<String, Object>>) result.get("selections");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> positions = (List<Map<String, Object>>) selections.get(0).get("positions");
        return positions.get(0);
    }

    private ProcessingPositionOperation operation() {
        return ProcessingPositionOperation.builder()
                .id(OPERATION_ID).tenantId(TENANT).processingOrderId(PO_ID).setId(SET_ID)
                .orderItemId(ITEM_ID).positionKind("布帘").positionName("布帘")
                .seq(1).operationName("精裁-布").groupName("车位").unit("米")
                .qty(new BigDecimal("12.35")).doneQty(BigDecimal.ZERO).qtySource("fabric_meters")
                .unitPrice(new BigDecimal("3.50")).isMustFinish(false).isStartMarker(false)
                .status("pending").deleted(0)
                .build();
    }

    /** 订单行：工艺列 + `processing_info`（商品身份 / 加工 / 算料输出 / 派工 / 备注同一载体）。 */
    private OrderItem orderItem() {
        OrderItem item = new OrderItem();
        item.setId(ITEM_ID);
        item.setTenantId(TENANT);
        item.setOrderId(ORDER_ID);
        item.setProductId("p-1");
        item.setProductName("布艺遮光帘A");
        item.setWidth(new BigDecimal("2.92"));
        item.setHeight(new BigDecimal("2.60"));
        item.setCraft("韩褶");
        item.setCurtainType("布帘");
        item.setOpenCount(2);
        item.setCuttingMode("定高买宽");
        item.setIsShaped(true);
        item.setFullness(new BigDecimal("2.0"));
        Map<String, Object> info = new LinkedHashMap<>();
        // 商品身份（与 `ProcessingOrderService#buildSnapshot` 同一批键）
        info.put("skuCode", "MG-006901");
        info.put("colorName", "雾霾蓝");
        info.put("doorWidth", "2.8");
        info.put("sellingMethod", "bulk_cut");
        info.put("unit", "米");
        // 加工信息
        info.put("style", "拼色");
        info.put("hasPattern", true);
        info.put("patternRepeat", "0.32");
        info.put("formula", "窗宽×褶倍÷门幅");
        info.put("craftTier", "标准");
        info.put("specialOptions", List.of("加线", "包边"));
        info.put("processingMeters", "8.10");
        info.put("formulaText", "2.8×2÷1.5=3.73→4");
        info.put("componentRole", "主布");
        // 算料输出（`CALC_OUTPUT_SNAPSHOT_KEYS`，snake_case）
        info.put("fullness_actual", "2.35");
        info.put("pleat_count", 48);
        info.put("per_panel_pleats", 24);
        info.put("panels", 2);
        info.put("fabric_meters", "12.35");
        info.put("remark", "左窗");
        item.setProcessingInfo(info);
        item.setDeleted(0);
        return item;
    }

    private Order order() {
        Order o = new Order();
        o.setId(ORDER_ID);
        o.setTenantId(TENANT);
        o.setOrderNo("ORD-20261014-06901");
        o.setCustomerName("张女士");
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

    // ============================================================ 断言辅助

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> overviewPositions(Map<String, Object> result) {
        Map<String, Object> overview = (Map<String, Object>) result.get("set_overview");
        return (List<Map<String, Object>>) overview.get("positions");
    }

    private static Map<String, Object> positionOf(List<Map<String, Object>> positions) {
        return positions.stream()
                .filter(p -> ITEM_ID.equals(p.get("order_item_id")))
                .findFirst()
                .orElseThrow(() -> new AssertionError("该套的部位清单里没有 " + ITEM_ID));
    }

    private static List<String> concat(List<String> a, List<String> b, String extra) {
        List<String> all = new ArrayList<>(a);
        all.addAll(b);
        all.add(extra);
        return all.stream().distinct().collect(Collectors.toList());
    }
}
