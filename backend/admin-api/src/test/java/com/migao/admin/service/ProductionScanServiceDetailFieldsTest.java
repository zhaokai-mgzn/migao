// case_ids: PG-046, PG-058
package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingOrderSet;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProcessingSetPartToken;
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
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * 扫码详情面「部位明细键」（母单 #5161，P0-C；切片① = issue #4698 的扫码响应）。
 *
 * <p><b>治什么</b>：一体机（车间屏 + 扫码枪）扫观星台自己的水洗唛 ⇒ 一屏显示订单详情。工人端
 * {@code GET /api/worker/production/scan} 的 {@code set_overview.positions[]}（= 该屏的部位行）
 * 原来只有「行标识 + 部位名 + 备注 + 工序明细」—— 详情面缺宽高 / 工艺 / 加工类型 / 开数 / 褶倍 /
 * 用料 / 部位备注。母单 #6901 再扩到**全量生产信息**（商品身份 / 加工 / 算料 / 派工）。
 * 本测试钉住这批键**只加不改**（键集真值 = {@link PositionDetailFields#DETAIL_KEYS}）。</p>
 *
 * <h2>取数口径（🔴 逐字取库/取快照，Java 侧不重算）</h2>
 * <p>与同族先例 {@code ProductionService#getOperations} 的 {@code positions[]} <b>同一份</b>订单行规格
 * 快照（同一实现 {@code ProductionService#orderSpecByItemId}）—— 在扫码侧再写一份取数就是第二份口径
 * （漂移的那一份不会变红，本仓库反复复发的形态）。每个键的**来源**逐条登记在
 * {@code ProductionScanService#positionDetailKeys} 的注释里。</p>
 *
 * <h2>红证（改前实测：本文件在实现前 3 条全红）</h2>
 * <ol>
 *   <li>① 逐字一致：明细键不出现 ⇒ 断言「键集相等」直接红（不是「键更多了」这种弱断言）；</li>
 *   <li>② 既有键一字未变：把这 3+1 个既有键的任一个改名 / 改值 ⇒ 红；</li>
 *   <li>③ 缺失不猜：`open_count` 的源值为 0 时若被读成「缺失」⇒ 红；源缺失时若被折成 0 / false ⇒ 红。</li>
 * </ol>
 *
 * <h2>与 PG-045 的关系（照实登记，不粉饰）</h2>
 * <p>PG-045 的用例正文登记的是「裁高配置」的引擎层（{@code traces.tests} 亦指向
 * {@code CuttingHeightConfigServiceTest}）。本文件挂同一个 ID 是**派单侧的口径**
 * （母单 #5161 的 P0-C 与 P0-A/B 同属一个用例条目）；若集成侧认为该 ID 面应收窄，
 * 需要改的是 {@code .github/cases/processing.yml}（**本包不碰该面**）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("ProductionScanService 扫码详情面 · 部位明细键（母单 #5161 / P0-C）")
class ProductionScanServiceDetailFieldsTest {

    private static final Long TENANT = 1L;
    private static final String ORDER_ID = "order-5161";
    private static final String PO_ID = "po-5161";
    private static final String PO_NO = "CSO260929-05161";
    private static final String SET_ID = "set-1";
    private static final String SET_NO = PO_NO + "-001";
    private static final String ITEM_CLOTH = "oi-cloth";
    private static final String ITEM_GAUZE = "oi-gauze";
    /**
     * 码夹具值（刻意用**非密钥形态**的字面量：32 位 hex 会被 CI 的 gitleaks `generic-api-key`
     * 误判为密钥 —— 同 {@code ProductionScanServiceTest} 的既有口径）。
     */
    private static final String CODE_CLOTH = "scan-detail-cloth-5161";
    private static final String CODE_GAUZE = "scan-detail-gauze-5161";

    /** 既有四键（`remark` 见 issue #5685）—— 本单**一字不动**；新增的明细键是**追加**。 */
    private static final List<String> EXISTING_KEYS = List.of(
            "order_item_id", "position_kind", "position_name", "remark");

    /**
     * 扫码面下发的明细键 —— **单一真值**（母单 #6901 起是 {@link PositionDetailFields} 的
     * {@code DETAIL_KEYS}，不是本文件再抄一份清单）。
     *
     * <p>P0-C（issue #5161）的 9 键（`width` / `height` / `craft` / `curtain_type` / `open_count` /
     * `cutting_mode` / `fullness` / `is_shaped` / `fabric_meters`）是它的**真子集** ——
     * ⚠️ **用料键 = `fabric_meters`**（不是 `material_meters`）：它是**引擎输出的算料快照键**
     * （与 {@code getOperations} 同源同名），改名 = 同一份引擎数据两个名字。</p>
     */
    private static final List<String> DETAIL_KEYS = PositionDetailFields.DETAIL_KEYS;

    /** 母单 #6901 在 P0-C 的 9 键之外**新增**的键（本文件不再维护第二份清单：由真值集推出来）。 */
    private static final List<String> ADDED_IN_6901 = List.of(
            "product_name", "sku", "color_name", "door_width", "selling_method", "unit",
            "style", "fullness_actual", "pleat_count", "per_panel_pleats", "panels",
            "has_pattern", "pattern_repeat", "formula", "craft_tier", "special_options",
            "processing_meters", "formula_text",
            "batch_no", "batch_meters", "component_role");

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
    private ProductionWorkLogMapper workLogMapper;
    @Mock
    private ProductionOperationQueryService operationQueryService;
    @Mock
    private ClientRequestIdService clientRequestIdService;

    private ProductionScanService service;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        // 真实对象（只 mock Mapper）：规格快照必须走**同一份**实现（`orderSpecByItemId`），
        // mock 掉它等于把被测口径换成桩（"绿了但没跑"）。
        ProductionService productionService = new ProductionService(processingOrderMapper,
                positionOperationMapper, workLogMapper, orderMapper, orderItemMapper, clientRequestIdService);
        ProductionStuckPointService stuckPointService = new ProductionStuckPointService(
                productionService, positionOperationMapper, orderSetMapper, 4.0);
        service = new ProductionScanService(setPartTokenMapper, orderSetMapper, processingOrderMapper,
                operationQueryService, productionService, stuckPointService,
                new ProcessingSetReadService(orderSetMapper, positionOperationMapper, orderItemMapper,
                        processingOrderMapper, orderMapper, productionService),
                orderMapper);
        // 本类测的是**规格快照键**（订单行规格列 + 算料输出），不是 `remark`（issue #5685 已由
        // 既有判据覆盖）⇒ 默认让 `remarkOf` 的 `selectById` 拿不到行（`remark` = null，键恒在）。
        // 订单行本体的替身一律用 `selectList` 提供（规格快照走的正是它）。
        when(orderItemMapper.selectById(any())).thenReturn(null);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ============================================================ ① 新键在且逐字一致

    @Test
    @DisplayName("① 新码扫码 ⇒ 部位行带全量明细键，值与订单行快照**逐字一致**")
    void detailKeysCarrySnapshotValuesVerbatim() {
        stubScan(CODE_CLOTH, ITEM_CLOTH, standardOps());
        when(orderItemMapper.selectList(any())).thenReturn(List.of(
                orderItem(ITEM_CLOTH, "布艺遮光帘A", "2.92", "2.60", "韩褶", "布帘", 2, "定高买宽", true, "2.0")));

        Map<String, Object> cloth = positionOf(overviewPositions(service.resolve(CODE_CLOTH, null, TENANT)),
                ITEM_CLOTH);

        // 宽 / 高 = `order_items.width` / `height`（V63 列）逐字
        assertThat(cloth.get("width")).isEqualTo(new BigDecimal("2.92"));
        assertThat(cloth.get("height")).isEqualTo(new BigDecimal("2.60"));
        // 工艺键 = `OrderLineCraftFields.toSnapshotKeys`（工艺列的**唯一映射点**，本单不另写键名翻译）
        assertThat(cloth.get("craft")).isEqualTo("韩褶");
        assertThat(cloth.get("curtain_type")).isEqualTo("布帘");
        assertThat(cloth.get("open_count")).isEqualTo(2);
        assertThat(cloth.get("cutting_mode")).isEqualTo("定高买宽");
        assertThat(cloth.get("is_shaped")).isEqualTo(true);
        // 褶倍 = 算料快照键（列 > 引擎输出：本夹具只给列，快照里就没有 `fullness` 覆盖 ⇒ 取列值）
        assertThat(cloth.get("fullness")).isEqualTo(new BigDecimal("2.0"));
        // 用料 = 算料快照键（单一真值 = ai-agent 引擎，Java 侧不重算）
        assertThat(cloth.get("fabric_meters")).isEqualTo(new BigDecimal("12.35"));
    }

    @Test
    @DisplayName("①-b 引擎输出 > 工艺列：`processing_info` 里的算料值覆盖同名列（与 `getOperations` 同一优先级）")
    void engineCalcOutputWinsOverColumn() {
        stubScan(CODE_CLOTH, ITEM_CLOTH, standardOps());
        OrderItem item = orderItem(ITEM_CLOTH, "布艺遮光帘A", "2.92", "2.60", "韩褶", "布帘",
                2, "定高买宽", true, "2.0");
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("fullness", "2.5");
        info.put("fabric_meters", "13.80");
        item.setProcessingInfo(info);
        when(orderItemMapper.selectList(any())).thenReturn(List.of(item));

        Map<String, Object> cloth = positionOf(overviewPositions(service.resolve(CODE_CLOTH, null, TENANT)),
                ITEM_CLOTH);

        assertThat(cloth.get("fullness")).isEqualTo(new BigDecimal("2.5"));
        assertThat(cloth.get("fabric_meters")).isEqualTo(new BigDecimal("13.80"));
    }

    // ============================================================ ①′ 母单 #6901：新增的 21 键

    @Test
    @DisplayName("①-c 母单 #6901：商品身份 / 加工 / 派工键**恒在**，值与订单行快照**逐值一致**")
    void added6901KeysCarrySnapshotValuesVerbatim() {
        stubScan(CODE_CLOTH, ITEM_CLOTH, standardOps());
        OrderItem item = orderItem(ITEM_CLOTH, "布艺遮光帘A", "2.92", "2.60", "韩褶", "布帘",
                2, "定高买宽", true, "2.0", identityInfo());
        when(orderItemMapper.selectList(any())).thenReturn(List.of(item));

        Map<String, Object> cloth = positionOf(overviewPositions(service.resolve(CODE_CLOTH, null, TENANT)),
                ITEM_CLOTH);

        // 组 1 商品身份（与加工单快照 `ProcessingOrderItemBrief` 逐字同名）
        assertThat(cloth.get("product_name")).isEqualTo("布艺遮光帘A");
        assertThat(cloth.get("sku")).isEqualTo("MG-006901");
        assertThat(cloth.get("color_name")).isEqualTo("雾霾蓝");
        assertThat(cloth.get("door_width")).isEqualTo("2.8");
        assertThat(cloth.get("selling_method")).isEqualTo("bulk_cut");
        assertThat(cloth.get("unit")).isEqualTo("米");
        // 组 3 加工信息
        assertThat(cloth.get("style")).isEqualTo("拼色");
        assertThat(cloth.get("fullness_actual")).isEqualTo(new BigDecimal("2.35"));
        assertThat(cloth.get("pleat_count")).isEqualTo(48);
        assertThat(cloth.get("per_panel_pleats")).isEqualTo(24);
        assertThat(cloth.get("panels")).isEqualTo(2);
        assertThat(cloth.get("has_pattern")).isEqualTo(true);
        assertThat(cloth.get("pattern_repeat")).isEqualTo(new BigDecimal("0.32"));
        assertThat(cloth.get("formula")).isEqualTo("窗宽×褶倍÷门幅");
        assertThat(cloth.get("craft_tier")).isEqualTo("标准");
        assertThat(cloth.get("special_options")).isEqualTo(List.of("加线", "包边"));
        assertThat(cloth.get("processing_meters")).isEqualTo(new BigDecimal("8.10"));
        assertThat(cloth.get("formula_text")).isEqualTo("2.8×2÷1.5=3.73→4");
        // 组 5 派工（组件来自快照；`batch_no` / `batch_meters` 由派工盖章，本夹具未指派 ⇒ null）
        assertThat(cloth.get("component_role")).isEqualTo("主布");
        assertThat(cloth).containsKey("batch_no");
        assertThat(cloth.get("batch_no")).isNull();
        assertThat(cloth.get("batch_meters")).isNull();
        // 键集 = 既有 4 键 + 全量明细键 + operations（**不省键**）
        assertThat(cloth.keySet()).containsExactlyInAnyOrderElementsOf(
                concat(EXISTING_KEYS, DETAIL_KEYS, "operations"));
        assertThat(DETAIL_KEYS).containsAll(ADDED_IN_6901);
    }

    @Test
    @DisplayName("①-d 母单 #6901：新增键在缺数据时**一个都不折默认**（键恒在 = null）")
    void added6901KeysStayNullWhenSourceIsMissing() {
        stubScan(CODE_GAUZE, ITEM_GAUZE, gauzeOps());
        when(orderItemMapper.selectList(any())).thenReturn(List.of(
                orderItem(ITEM_GAUZE, "纱帘B", null, null, null, null, 0, null, null, null)));

        Map<String, Object> position = positionOf(overviewPositions(service.resolve(CODE_GAUZE, null, TENANT)),
                ITEM_GAUZE);

        for (String key : ADDED_IN_6901) {
            assertThat(position).containsKey(key);
            if ("product_name".equals(key)) {
                continue; // 它取自 `order_items.product_name` **列**（不是快照键族）⇒ 有值是正确形态
            }
            assertThat(position.get(key))
                    .as("键 %s 的源缺失 ⇒ 必须是 null，不得折成 0 / false / 空串", key)
                    .isNull();
        }
        // `product_name` 取自列 ⇒ 有值（逐字）
        assertThat(position.get("product_name")).isEqualTo("纱帘B");
    }

    // ============================================================ ② 既有键一字未变

    @Test
    @DisplayName("② 既有键（order_item_id / position_kind / position_name / remark）值**一字未变**")
    void existingKeysAreUntouched() {
        stubScan(CODE_CLOTH, ITEM_CLOTH, standardOps());
        when(orderItemMapper.selectList(any())).thenReturn(List.of(
                orderItem(ITEM_CLOTH, "布艺遮光帘A", "2.92", "2.60", "韩褶", "布帘", 2, "定高买宽", true, "2.0")));

        Map<String, Object> cloth = positionOf(overviewPositions(service.resolve(CODE_CLOTH, null, TENANT)),
                ITEM_CLOTH);

        assertThat(cloth.get("order_item_id")).isEqualTo(ITEM_CLOTH);
        assertThat(cloth.get("position_kind")).isEqualTo("布帘");
        assertThat(cloth.get("position_name")).isEqualTo("布艺遮光帘A");
        // 部位级备注（issue #5685）：键**恒在**、未填 ⇒ null（既有语义，本单不改）
        assertThat(cloth).containsKey("remark");
        assertThat(cloth.get("remark")).isNull();
        // 🔴 同一件事实不得两个键名（本单**刻意不**落地 `position_remark` 别名）
        assertThat(cloth).doesNotContainKey("position_remark");
    }

    @Test
    @DisplayName("②-b 键集 = 既有 4 键 + 全量明细键（不删键、不多造键）")
    void keySetIsExistingPlusDetails() {
        stubScan(CODE_CLOTH, ITEM_CLOTH, standardOps());
        when(orderItemMapper.selectList(any())).thenReturn(List.of(
                orderItem(ITEM_CLOTH, "布艺遮光帘A", "2.92", "2.60", "韩褶", "布帘", 2, "定高买宽", true, "2.0")));

        Map<String, Object> cloth = positionOf(overviewPositions(service.resolve(CODE_CLOTH, null, TENANT)),
                ITEM_CLOTH);

        assertThat(cloth.keySet()).containsExactlyInAnyOrderElementsOf(
                concat(EXISTING_KEYS, DETAIL_KEYS, "operations"));
    }

    @Test
    @DisplayName("②-c 旧码降级清单 selections[].positions[] 同批补同一套键（同一展厅屏，不两套形状）")
    void degradedSelectionPositionsCarrySameDetailKeys() {
        stubLegacyScan();
        when(orderItemMapper.selectList(any())).thenReturn(List.of(
                orderItem(ITEM_CLOTH, "布艺遮光帘A", "2.92", "2.60", "韩褶", "布帘", 2, "定高买宽", true, "2.0")));

        Map<String, Object> result = service.resolve("legacy-scan-code-5161", null, TENANT);

        assertThat(result.get("granularity")).isEqualTo("order");
        List<Map<String, Object>> firstSet = selections(result).get(0).get("positions") instanceof List<?> list
                ? castPositions(list) : List.of();
        Map<String, Object> cloth = positionOf(firstSet, ITEM_CLOTH);
        assertThat(cloth.get("width")).isEqualTo(new BigDecimal("2.92"));
        assertThat(cloth.get("craft")).isEqualTo("韩褶");
        assertThat(cloth.get("fabric_meters")).isEqualTo(new BigDecimal("12.35"));
    }

    // ============================================================ ③ 缺失不猜

    @Test
    @DisplayName("③ 缺失 ⇒ 键恒在且为 null（不省键、不猜 0 / false）；源为 0 ⇒ 读成 0（不当缺失）")
    void missingSourceYieldsNullButRealZeroStaysZero() {
        stubScan(CODE_GAUZE, ITEM_GAUZE, gauzeOps());
        // 纱帘行：开数**真的为 0**（源值在场）但其余工艺列与算料输出全空 ⇒ 两者必须区分
        OrderItem gauze = orderItem(ITEM_GAUZE, "纱帘B", null, null, null, null, 0, null, null, null,
                Map.of());
        when(orderItemMapper.selectList(any())).thenReturn(List.of(gauze));

        Map<String, Object> position = positionOf(overviewPositions(service.resolve(CODE_GAUZE, null, TENANT)),
                ITEM_GAUZE);

        // 源在场且为 0 ⇒ `open_count` = 0（**不折成 null**：0 开与「没填」是两回事）
        assertThat(position.get("open_count")).isEqualTo(0);
        // 源缺失 ⇒ 键**恒在**、值为 null（不省键 ⇒ 消费方不必写分支；不猜 0 / false）
        for (String key : List.of("width", "height", "craft", "curtain_type", "cutting_mode",
                "fullness", "is_shaped", "fabric_meters")) {
            assertThat(position).containsKey(key);
            assertThat(position.get(key))
                    .as("键 %s 的源缺失 ⇒ 必须是 null，不得折成 0 / false", key)
                    .isNull();
        }
        assertThat(position.keySet()).containsExactlyInAnyOrderElementsOf(
                concat(EXISTING_KEYS, DETAIL_KEYS, "operations"));
    }

    @Test
    @DisplayName("③-b 订单行查不到（脏数据）⇒ 仍给全键（全 null），不冒充已知、也不崩")
    void missingOrderLineStillYieldsNullKeys() {
        stubScan(CODE_CLOTH, ITEM_CLOTH, standardOps());
        when(orderItemMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> cloth = positionOf(overviewPositions(service.resolve(CODE_CLOTH, null, TENANT)),
                ITEM_CLOTH);

        for (String key : DETAIL_KEYS) {
            assertThat(cloth).containsKey(key);
            assertThat(cloth.get(key)).as("键 %s 无订单行 ⇒ null", key).isNull();
        }
    }

    // ============================================================ 夹具

    private void stubScan(String code, String itemId, List<ProcessingPositionOperation> ops) {
        when(setPartTokenMapper.selectOne(any())).thenReturn(partToken(code, itemId));
        when(orderSetMapper.selectById(SET_ID)).thenReturn(set());
        when(processingOrderMapper.selectById(PO_ID)).thenReturn(processingOrder());
        when(positionOperationMapper.selectList(any())).thenReturn(ops);
        // 规格快照按 `po.order_id` 取订单本体（`specByItemIdOf`），再按它查订单行
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order());
    }

    private void stubLegacyScan() {
        when(setPartTokenMapper.selectOne(any())).thenReturn(null);
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order());
        when(processingOrderMapper.selectOne(any())).thenReturn(processingOrder());
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder());
        when(orderSetMapper.selectList(any())).thenReturn(List.of(set()));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-1", ITEM_CLOTH, "布帘", "布艺遮光帘A", 1, "精裁-布", "12.35", "0"),
                op("op-2", ITEM_GAUZE, "纱帘", "纱帘B", 1, "精裁-纱", "8", "0")));
    }

    private List<ProcessingPositionOperation> standardOps() {
        return List.of(op("op-1", ITEM_CLOTH, "布帘", "布艺遮光帘A", 1, "精裁-布", "12.35", "0"));
    }

    private List<ProcessingPositionOperation> gauzeOps() {
        return List.of(op("op-2", ITEM_GAUZE, "纱帘", "纱帘B", 1, "精裁-纱", "8", "0"));
    }

    private ProcessingSetPartToken partToken(String code, String itemId) {
        return ProcessingSetPartToken.builder()
                .id("pt-" + itemId).tenantId(TENANT).token(code)
                .processingOrderId(PO_ID).setId(SET_ID).orderItemId(itemId)
                .positionKind(itemId.equals(ITEM_GAUZE) ? "纱帘" : "布帘")
                .deleted(0)
                .build();
    }

    private ProcessingOrderSet set() {
        return ProcessingOrderSet.builder()
                .id(SET_ID).tenantId(TENANT).processingOrderId(PO_ID)
                .setIndex(1).setNo(SET_NO).deleted(0)
                .build();
    }

    private ProcessingPositionOperation op(String id, String itemId, String positionKind,
                                           String positionName, int seq, String operationName,
                                           String qty, String doneQty) {
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId(PO_ID).setId(SET_ID)
                .orderItemId(itemId).positionKind(positionKind).positionName(positionName)
                .seq(seq).operationName(operationName).groupName("车位").unit("米")
                .qty(new BigDecimal(qty)).doneQty(new BigDecimal(doneQty)).qtySource("fabric_meters")
                .unitPrice(new BigDecimal("3.50")).isMustFinish(false).isStartMarker(false)
                .status("pending").deleted(0)
                .build();
    }

    /** 订单行夹具：只填「部位明细键」用到的列（宽高 / 工艺 / 加工类型 / 开数 / 褶倍 / 定型）。 */
    private OrderItem orderItem(String id, String productName, String width, String height,
                                String craft, String curtainType, Integer openCount,
                                String cuttingMode, Boolean isShaped, String fullness) {
        return orderItem(id, productName, width, height, craft, curtainType, openCount,
                cuttingMode, isShaped, fullness, Map.of("fabric_meters", "12.35"));
    }

    private OrderItem orderItem(String id, String productName, String width, String height,
                                String craft, String curtainType, Integer openCount,
                                String cuttingMode, Boolean isShaped, String fullness,
                                Map<String, Object> processingInfo) {
        OrderItem item = new OrderItem();
        item.setId(id);
        item.setTenantId(TENANT);
        item.setOrderId(ORDER_ID);
        item.setProductName(productName);
        item.setWidth(width == null ? null : new BigDecimal(width));
        item.setHeight(height == null ? null : new BigDecimal(height));
        item.setCraft(craft);
        item.setCurtainType(curtainType);
        item.setOpenCount(openCount);
        item.setCuttingMode(cuttingMode);
        item.setIsShaped(isShaped);
        item.setFullness(fullness == null ? null : new BigDecimal(fullness));
        // 算料输出（含 `fabric_meters`）的来源：`order_items.processing_info` 顶层（引擎落库）
        item.setProcessingInfo(new LinkedHashMap<>(processingInfo));
        item.setDeleted(0);
        return item;
    }

    /**
     * 母单 #6901 的商品身份 / 加工 / 派工夹具（`order_items.processing_info` 顶层扁平键，
     * **与 {@code ProcessingOrderService#buildSnapshot} 读的是同一批键名**）。
     */
    private static Map<String, Object> identityInfo() {
        Map<String, Object> info = new LinkedHashMap<>();
        // 商品身份（`copyIfPresent(pi, entry, "skuCode", "sku")` / "colorName" / "doorWidth" /
        // "sellingMethod" / "unit" 同一批）
        info.put("skuCode", "MG-006901");
        info.put("colorName", "雾霾蓝");
        info.put("doorWidth", "2.8");
        info.put("sellingMethod", "bulk_cut");
        info.put("unit", "米");
        // 加工信息（`CRAFT_SPEC_SNAPSHOT_KEYS` 同族）
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
        return info;
    }

    private Order order() {
        Order o = new Order();
        o.setId(ORDER_ID);
        o.setTenantId(TENANT);
        o.setOrderNo("ORD-20260929-05161");
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

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> selections(Map<String, Object> result) {
        return (List<Map<String, Object>>) result.get("selections");
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> castPositions(List<?> raw) {
        return (List<Map<String, Object>>) raw;
    }

    private static Map<String, Object> positionOf(List<Map<String, Object>> positions, String orderItemId) {
        return positions.stream()
                .filter(p -> orderItemId.equals(p.get("order_item_id")))
                .findFirst()
                .orElseThrow(() -> new AssertionError("该套的部位清单里没有 " + orderItemId));
    }

    private static List<String> concat(List<String> a, List<String> b, String extra) {
        List<String> all = new java.util.ArrayList<>(a);
        all.addAll(b);
        all.add(extra);
        // `remark` 同时是既有键与明细键（同一件事实一个键）⇒ 去重后比较（键集判据钉的是**集合**）
        return all.stream().distinct().toList();
    }
}
