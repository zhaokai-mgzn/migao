// case_ids: MC-330
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ProcessingOrderResponse;
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
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.IOException;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 加工单**快照构建 + 读面**的 characterization 判据（issue #8770，快照/读面一档，CP-1）。
 *
 * <h2>它补的是哪一格</h2>
 * 上一档（自动批次一档，PR #8807）留下的下一档清单第 3 行原文：
 * <em>「快照 / 读面 / 状态机 / 常量（{@code buildSnapshot} / {@code loadOrderItems} /
 * {@code toResponse} / {@code STATUS_TRANSITIONS} / 常量表）~1,200 行 —— 常量表属公共 API；
 * {@code STATUS_TRANSITIONS} 已被 {@code OrderStatusTransitionsTest} 按单实现核对」</em>。
 * 本档只搬**快照构建**与**读面**两块，故本判据只冻这两块。
 *
 * <h2>为什么必须新写（既有判据全是点状）</h2>
 * 既有 {@code ProcessingOrderServiceTest}（141 条）/ {@code ProcessingOrderReadFaceShortCodeTest}
 * （两键）/ {@code PoolBoardUrgencyTest} 全部断言的是**某几个键**（短码、扫描 URL、某条单在不在池里）。
 * 大面积搬移可以让它们**全绿通过**，却把
 * ① 快照的**键集合 / 键序 / 缺键语义**、② 读面 DTO 的**全部字段**、③ 列表路径的**批量取数形态**、
 * ④ 快照 JSON 字符串解析的**失败退化面**悄悄改掉 —— 每一条都是可观测面：
 * 快照是加工单的**固化真相**（车间按它干活、事后补不回来），读面是商家与 agent 的唯一取数口。
 *
 * <h2>冻的是什么（与 golden 逐字节比对）</h2>
 * <ol>
 *   <li><b>{@code snapshot} 段（12 场景）</b>：{@code buildSnapshot} 的**完整输出**
 *       （每一行是 {@code LinkedHashMap} ⇒ JSON 对象**键序也是行为**），外加每个场景的
 *       {@code keyUnion}（该场景出现过的全部键，按首次出现序）⇒ **不是抽样**；</li>
 *   <li><b>{@code snapshotFullKeys}</b>：场景 {@code 01-all-keys} 的键序与**硬编码字面量**逐字相等
 *       —— 这一条不读 golden，是独立真值（白名单增删必须同时改这里与 golden）；</li>
 *   <li><b>{@code readFace} 段（13 场景）</b>：{@code getDetail} / {@code list} 的**完整 DTO**
 *       （用 {@code ALWAYS} inclusion 序列化 ⇒ **null 键也在场**：新增字段会让 golden 失配，
 *       迫使人显式重录并说明该字段冻的是什么；线上是 {@code NON_NULL}，那是展示层口径，
 *       不是「字段存不存在」的口径）；</li>
 *   <li><b>{@code scanUrl} 段（3 场景）</b>：域名去尾斜杠 / 空短码 / 空域名三条边界。</li>
 * </ol>
 *
 * <h2>墙钟 / 派生量怎么归一</h2>
 * 快照与读面**不读业务时钟**（本档搬的代码里没有 {@code businessClock} 调用）⇒ 不需要
 * {@code Clock.fixed}：所有时间量都是**夹具输入**（{@code Order.requiredDeliveryDate} 等），
 * golden 里落的是输入原值 ⇒ **不随跑测试的时刻漂移**。
 *
 * <p>golden 录制于**切片前**的代码（{@code -Dpos.snapshot.golden.update=true} 生成），
 * 切片后**不带**该开关复跑必须逐字节相同。</p>
 *
 * <h2>红证（注入式，逐条见 PR body）</h2>
 * 把 {@code formula_text} 的源键别名摘掉 / 把卖布行的兜底判据写死 false / 把排序改成单号序 /
 * 把短码为空时的 {@code scan_url} 折成 {@code ""} / 把列表路径退回逐行单查 ⇒ 本判据**具名**报出差异场景。
 */
@DisplayName("加工单快照 + 读面 characterization（issue #8770 快照/读面一档）")
class ProcessingOrderSnapshotReadFaceCharacterizationTest {

    private static final Long TENANT = 1L;

    /** golden 落点（相对 {@code backend/admin-api}）。 */
    private static final Path GOLDEN = Path.of(
            "src/test/resources/processing-order-snapshot-read-face-golden.json");

    /** 录制开关：**只在切片前**用它写 golden；切片后必须不带开关跑。 */
    private static final String UPDATE_FLAG = "pos.snapshot.golden.update";

    /** 门店线上域名（门面 {@code shortLinkBaseUrl} 的缺省值）。 */
    private static final String BASE = "https://app.migaozn.com";

    /** 工艺规格白名单（**逐字**来自摊开的代码事实，不是从被测常量读 —— 否则白名单被清空也照绿）。 */
    private static final List<String> CRAFT_KEYS = List.of(
            "curtainType", "craft", "cuttingMode", "openCount", "isShaped", "pleatSpacing",
            "hasPattern", "patternRepeat", "style", "room", "batchNo",
            "componentRole", "craftLineId", "metersSource", "processingMeters",
            "formula", "craftTier", "saleForm", "remark", "installCommunity", "installRoom");

    /** 算料输出白名单（同上，逐字硬编码）。 */
    private static final List<String> CALC_KEYS = List.of(
            "fabric_meters", "pleat_count", "per_panel_pleats", "panels", "holes",
            "fullness", "fullness_actual", "formula_text");

    /**
     * 场景 {@code 01-all-keys} 的**完整键序**（硬编码真值）。
     *
     * <p>键序不是运气：快照行是 {@code LinkedHashMap}，落库后就是加工单纸面的字段序
     * ⇒ 插入顺序变了也是**行为**变了。</p>
     */
    private static final List<String> FULL_KEY_ORDER = List.of(
            "itemId", "productName", "quantity", "width", "height",
            "sku", "colorName", "sellingMethod", "rollCount", "doorWidth", "unit", "specialOptions",
            "curtainType", "craft", "cuttingMode", "openCount", "isShaped", "pleatSpacing",
            "hasPattern", "patternRepeat", "style", "room", "batchNo",
            "componentRole", "craftLineId", "metersSource", "processingMeters",
            "formula", "craftTier", "saleForm", "remark", "installCommunity", "installRoom",
            "fabric_meters", "pleat_count", "per_panel_pleats", "panels", "holes",
            "fullness", "fullness_actual", "formula_text",
            // 显式字段覆盖（OrderLineCraftFields.toSnapshotKeys）里**白名单外**的那一个键
            "corner",
            "processingItems");

    /** 冻结投影：ISO 日期/时刻 + **null 也落键**（理由见类注释）。 */
    private final ObjectMapper mapper = new ObjectMapper()
            .registerModule(new JavaTimeModule())
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS)
            .setSerializationInclusion(JsonInclude.Include.ALWAYS)
            .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);

    private ProcessingOrderMapper processingOrderMapper;
    private OrderMapper orderMapper;
    private OrderItemMapper orderItemMapper;
    private ProcessingItemMapper processingItemMapper;
    private OrderService orderService;
    private ProductionService productionService;
    private ProductionOperationQueryService productionOperationQueryService;
    private ProductionOperationQtyClient productionOperationQtyClient;

    private ProcessingOrderService service;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        processingOrderMapper = mock(ProcessingOrderMapper.class);
        orderMapper = mock(OrderMapper.class);
        orderItemMapper = mock(OrderItemMapper.class);
        processingItemMapper = mock(ProcessingItemMapper.class);
        orderService = mock(OrderService.class);
        productionService = mock(ProductionService.class);
        productionOperationQueryService = mock(ProductionOperationQueryService.class);
        productionOperationQtyClient = mock(ProductionOperationQtyClient.class);

        // LambdaQueryWrapper 构建需 TableInfo（同 ProcessingOrderReadFaceShortCodeTest 的做法）
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, ProcessingOrder.class);

        service = new ProcessingOrderService(
                processingOrderMapper, orderMapper, orderItemMapper, processingItemMapper,
                orderService, mapper, productionService,
                productionOperationQueryService, productionOperationQtyClient);
        ReflectionTestUtils.setField(service, "shortLinkBaseUrl", BASE);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ── ① 快照：12 场景，逐场景冻结完整输出 + 键集合 ────────────────────────

    @Test
    @DisplayName("快照构建 12 场景：键集合 / 键序 / 缺键语义 / 卖布兜底 / 归一化失败面 与切片前逐字节相同")
    void snapshotIsByteIdenticalToThePreSliceGolden() throws IOException {
        Map<String, Object> actual = new LinkedHashMap<>();
        for (String scenario : SNAPSHOT_SCENARIOS) {
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> rows = (List<Map<String, Object>>) ReflectionTestUtils
                    .invokeMethod(service, "buildSnapshot", snapshotItems(scenario), TENANT);

            Map<String, Object> frozen = new LinkedHashMap<>();
            frozen.put("rows", rows);
            frozen.put("keyUnion", keyUnion(rows));
            actual.put(scenario, frozen);
        }
        assertGolden("snapshot", actual);
    }

    @Test
    @DisplayName("🔴 快照键集合是**全量**的：01-all-keys 的键序与硬编码字面量逐字相等（白名单增删 ⇒ 这里先红）")
    void everySnapshotKeyIsFrozenNotSampled() {
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> rows = (List<Map<String, Object>>) ReflectionTestUtils
                .invokeMethod(service, "buildSnapshot", snapshotItems("01-all-keys"), TENANT);

        assertThat(rows).as("01-all-keys 必须产出一行（夹具形态变了 ⇒ 先在这里红）").hasSize(1);
        assertThat(new ArrayList<>(rows.get(0).keySet()))
                .as("快照键序 = 加工单纸面的字段序；与硬编码真值不等 ⇒ 要么删了键（车间少一道活）"
                        + "、要么加了键却没重录 golden")
                .isEqualTo(FULL_KEY_ORDER);
        assertThat(rows.get(0)).containsKeys(CRAFT_KEYS.toArray(String[]::new));
        assertThat(rows.get(0)).containsKeys(CALC_KEYS.toArray(String[]::new));
    }

    // ── ② 读面：13 场景，冻结完整 DTO（null 键也在场）────────────────────────

    @Test
    @DisplayName("读面 13 场景：getDetail / list 的完整 DTO（含 null 键）与切片前逐字节相同")
    void readFaceIsByteIdenticalToThePreSliceGolden() throws IOException {
        Map<String, Object> actual = new LinkedHashMap<>();
        for (String scenario : READ_FACE_SCENARIOS) {
            actual.put(scenario, readFace(scenario));
        }
        assertGolden("readFace", actual);
    }

    @Test
    @DisplayName("🔴 列表路径是**一次批量取数**：selectBatchIds 恰好 1 次、绝不逐行 selectById（#4304 的 N+1 防线）")
    void listBatchesOrdersAndNeverQueriesPerRow() {
        when(processingOrderMapper.selectList(any())).thenReturn(List.of(
                po("po-1", "order-001", "SO-1"), po("po-2", "order-002", "SO-2")));
        when(orderMapper.selectBatchIds(anyCollection())).thenReturn(List.of(order("order-001"), order("order-002")));

        List<ProcessingOrderResponse> rows = service.list(null, null, TENANT);

        assertThat(rows).hasSize(2);
        verify(orderMapper, times(1)).selectBatchIds(anyCollection());
        verify(orderMapper, never()).selectById(anyString());
    }

    @Test
    @DisplayName("列表路径的关键词分支走 selectByKeyword（不是先全量再内存过滤）")
    void listUsesKeywordQueryWhenKeywordPresent() {
        when(processingOrderMapper.selectByKeyword("布帘", TENANT)).thenReturn(List.of(po("po-1", "order-001", "SO-1")));
        when(orderMapper.selectBatchIds(anyCollection())).thenReturn(List.of(order("order-001")));

        assertThat(service.list("布帘", null, TENANT)).hasSize(1);
        verify(processingOrderMapper, times(1)).selectByKeyword("布帘", TENANT);
        verify(processingOrderMapper, never()).selectList(any());
    }

    // ── ③ 扫码 URL：3 条边界 ────────────────────────────────────────────────

    @Test
    @DisplayName("扫码 URL 3 条边界：域名去尾斜杠 / 空短码不造 /o/null / 空域名给相对路径")
    void scanUrlBoundariesAreByteIdenticalToThePreSliceGolden() throws IOException {
        Map<String, Object> actual = new LinkedHashMap<>();
        for (String scenario : SCAN_URL_SCENARIOS) {
            actual.put(scenario, scanUrl(scenario));
        }
        assertGolden("scanUrl", actual);
    }

    // ── 夹具：快照 ─────────────────────────────────────────────────────────

    private static final List<String> SNAPSHOT_SCENARIOS = List.of(
            "01-all-keys",
            "02-columns-override-jsonb",
            "03-json-string-processing-info",
            "04-null-processing-info",
            "05-no-procs-not-fabric",
            "06-fabric-sale-form-no-procs",
            "07-fabric-evidence-from-columns",
            "08-partial-craft-keys",
            "09-processing-item-missing-catalog",
            "10-malformed-json-string",
            "11-multi-rows-order",
            "12-empty-items");

    private static final List<String> READ_FACE_SCENARIOS = List.of(
            "01-detail-all-fields",
            "02-detail-snapshot-json-string",
            "03-detail-malformed-snapshot",
            "04-detail-no-order",
            "05-detail-without-short-code",
            "06-list-basic",
            "07-list-status-filter",
            "08-list-outsourced-filter",
            "09-list-null-order-ids",
            "10-list-empty",
            "11-detail-missing-but-order-exists",
            "12-detail-neither-exists",
            "13-list-mixed-order-presence");

    private static final List<String> SCAN_URL_SCENARIOS = List.of(
            "01-trailing-slash-trimmed",
            "02-blank-short-code",
            "03-empty-base");

    /** 一行明细（无显式字段覆盖）：{@code processing_info} 里放快照键族的来源键。 */
    private static OrderItem item(String id, String name, Object processingInfo) {
        return OrderItem.builder()
                .id(id).tenantId(TENANT).orderId("order-001")
                .productName(name).quantity(new BigDecimal("2"))
                .width(new BigDecimal("1.80")).height(new BigDecimal("2.00"))
                .processingInfo(processingInfo)
                .build();
    }

    /** 全键 {@code processing_info}（工艺白名单 + 算料输出 + 销售信息，逐键都在场）。 */
    private static Map<String, Object> allKeysProcessingInfo() {
        Map<String, Object> pi = new LinkedHashMap<>();
        pi.put("sku", "SKU-LEGACY");
        pi.put("skuCode", "SKU-001");
        pi.put("colorName", "米白");
        pi.put("sellingMethod", "窗帘");
        pi.put("doorWidth", "3.20");
        pi.put("unit", "米");
        pi.put("specialOptions", List.of("高温定型", "遮光衬"));
        pi.put("curtainType", "布帘");
        pi.put("craft", "韩褶");
        pi.put("cuttingMode", "对开");
        pi.put("openCount", 2);
        pi.put("isShaped", false);
        pi.put("pleatSpacing", new BigDecimal("16.0"));
        pi.put("hasPattern", true);
        pi.put("patternRepeat", new BigDecimal("32.0"));
        pi.put("style", "简约");
        pi.put("room", "主卧");
        pi.put("batchNo", "B-01");
        pi.put("componentRole", "主布");
        pi.put("craftLineId", "i-craft-1");
        pi.put("metersSource", "calc");
        pi.put("processingMeters", new BigDecimal("6.40"));
        pi.put("formula", "width*2");
        pi.put("craftTier", "standard");
        pi.put("saleForm", "成品帘");
        pi.put("remark", "公式：48 个折");
        pi.put("installCommunity", "观星台花园");
        pi.put("installRoom", "主卧飘窗");
        pi.put("fabric_meters", new BigDecimal("6.40"));
        pi.put("pleat_count", 48);
        pi.put("per_panel_pleats", 24);
        pi.put("panels", 2);
        pi.put("holes", 96);
        pi.put("fullness", new BigDecimal("2.0"));
        pi.put("fullness_actual", new BigDecimal("2.1"));
        // 🔴 算料公式串的**取值键是 camelCase**（快照键族是 snake_case）⇒ 只在这里验别名映射
        pi.put("formulaText", "1.80 × 2.00 × 2");
        Map<String, Object> proc = new LinkedHashMap<>();
        proc.put("id", "pi-1");
        proc.put("name", "裁剪");
        pi.put("processingItems", List.of(proc));
        return pi;
    }

    /** 一行明细 + 显式字段覆盖（{@code order_items} 的 craft spec 列）。 */
    private static OrderItem itemWithColumns(String id) {
        return OrderItem.builder()
                .id(id).tenantId(TENANT).orderId("order-001")
                .productName("布艺遮光帘").quantity(new BigDecimal("1"))
                .width(new BigDecimal("2.00")).height(new BigDecimal("2.60"))
                .curtainType("水波帘").craft("打孔").openCount(3)
                .cuttingMode("单开").isShaped(true)
                .fullness(new BigDecimal("2.5")).fullnessActual(new BigDecimal("2.6"))
                .pleatSpacing(new BigDecimal("18.0")).pleatCount(36)
                .hasPattern(false).corner("左")
                .sellingMethod("窗帘").rollCount(2)
                .processingInfo(allKeysProcessingInfo())
                .build();
    }

    private List<OrderItem> snapshotItems(String scenario) {
        switch (scenario) {
            case "01-all-keys":
                stubCatalogItem("pi-1", List.of("包边", "定型"), "条", " 韩褶 ");
                // rollCount / corner **只**来自明细列（白名单里没有这两个键）⇒ 全键场景必须带上这两列
                return List.of(OrderItem.builder()
                        .id("i-1").tenantId(TENANT).orderId("order-001")
                        .productName("布艺遮光帘").quantity(new BigDecimal("2"))
                        .width(new BigDecimal("1.80")).height(new BigDecimal("2.00"))
                        .rollCount(2).corner("左")
                        .processingInfo(allKeysProcessingInfo())
                        .build());
            case "02-columns-override-jsonb":
                stubCatalogItem("pi-1", List.of("包边"), "条", "韩褶");
                return List.of(itemWithColumns("i-1"));
            case "03-json-string-processing-info":
                stubCatalogItem("pi-1", null, null, null);
                return List.of(item("i-1", "布艺遮光帘", jsonOf(allKeysProcessingInfo())));
            case "04-null-processing-info":
                return List.of(item("i-1", "布艺遮光帘", null));
            case "05-no-procs-not-fabric":
                return List.of(item("i-1", "配件", Map.of("sku", "SKU-ACC")));
            case "06-fabric-sale-form-no-procs":
                return List.of(item("i-1", "遮光布", Map.of("saleForm", "布料", "sku", "SKU-FABRIC")));
            case "07-fabric-evidence-from-columns":
                return List.of(OrderItem.builder()
                        .id("i-1").tenantId(TENANT).orderId("order-001")
                        .productName("遮光布").quantity(new BigDecimal("7.5"))
                        .width(new BigDecimal("2.80")).height(BigDecimal.ZERO)
                        .sellingMethod("布料").rollCount(1)
                        .processingInfo(Map.of("sku", "SKU-FABRIC"))
                        .build());
            case "08-partial-craft-keys":
                return List.of(item("i-1", "布艺遮光帘",
                        Map.of("curtainType", "布帘", "craft", "韩褶", "processingMeters", new BigDecimal("5.5"))));
            case "09-processing-item-missing-catalog":
                // 目录行不存在 ⇒ options / unit / craftHint 一律不落键（缺键就是缺键）
                when(processingItemMapper.selectById("pi-gone")).thenReturn(null);
                return List.of(item("i-1", "布艺遮光帘", Map.of("processingItems",
                        List.of(new LinkedHashMap<>(Map.of("id", "pi-gone", "name", "裁剪"))))));
            case "10-malformed-json-string":
                return List.of(item("i-1", "布艺遮光帘", "not a json"));
            case "11-multi-rows-order":
                stubCatalogItem("pi-1", List.of("包边"), "条", "韩褶");
                return List.of(
                        item("i-1", "布艺遮光帘", allKeysProcessingInfo()),
                        item("i-2", "配件", Map.of("sku", "SKU-ACC")),
                        OrderItem.builder().id("i-3").tenantId(TENANT).orderId("order-001")
                                .productName("遮光布").quantity(new BigDecimal("3"))
                                .width(new BigDecimal("2.00")).height(BigDecimal.ZERO)
                                .sellingMethod("布料")
                                .processingInfo(Map.of("saleForm", "布料")).build());
            case "12-empty-items":
                return List.of();
            default:
                throw new IllegalArgumentException("未知快照场景: " + scenario);
        }
    }

    private void stubCatalogItem(String id, Object options, String unit, String craftHint) {
        when(processingItemMapper.selectById(id)).thenReturn(ProcessingItem.builder()
                .id(id).tenantId(TENANT).name("裁剪")
                .options(options).unit(unit).craftHint(craftHint)
                .build());
    }

    // ── 夹具：读面 ─────────────────────────────────────────────────────────

    private Object readFace(String scenario) {
        switch (scenario) {
            case "01-detail-all-fields": {
                when(processingOrderMapper.selectOne(any())).thenReturn(fullPo());
                when(orderMapper.selectById("order-001")).thenReturn(order("order-001"));
                return dto(service.getDetail("po-1", TENANT));
            }
            case "02-detail-snapshot-json-string": {
                ProcessingOrder po = fullPo();
                po.setItemsSnapshot(jsonOf(List.of(allKeysRow())));
                when(processingOrderMapper.selectOne(any())).thenReturn(po);
                when(orderMapper.selectById("order-001")).thenReturn(order("order-001"));
                return dto(service.getDetail("po-1", TENANT));
            }
            case "03-detail-malformed-snapshot": {
                ProcessingOrder po = fullPo();
                po.setItemsSnapshot("<<not json>>");
                when(processingOrderMapper.selectOne(any())).thenReturn(po);
                when(orderMapper.selectById("order-001")).thenReturn(order("order-001"));
                return dto(service.getDetail("po-1", TENANT));
            }
            case "04-detail-no-order": {
                when(processingOrderMapper.selectOne(any())).thenReturn(fullPo());
                when(orderMapper.selectById("order-001")).thenReturn(null);
                return dto(service.getDetail("po-1", TENANT));
            }
            case "05-detail-without-short-code": {
                ProcessingOrder po = fullPo();
                po.setShortCode(null);
                when(processingOrderMapper.selectOne(any())).thenReturn(po);
                when(orderMapper.selectById("order-001")).thenReturn(order("order-001"));
                return dto(service.getDetail("po-1", TENANT));
            }
            case "06-list-basic": {
                when(processingOrderMapper.selectList(any())).thenReturn(List.of(
                        po("po-1", "order-001", "SO-1"), po("po-2", "order-002", "SO-2")));
                when(orderMapper.selectBatchIds(anyCollection())).thenReturn(List.of(
                        order("order-001"), order("order-002")));
                return dto(service.list(null, null, TENANT));
            }
            case "07-list-status-filter": {
                when(processingOrderMapper.selectList(any())).thenReturn(List.of(po("po-1", "order-001", "SO-1")));
                when(orderMapper.selectBatchIds(anyCollection())).thenReturn(List.of(order("order-001")));
                return dto(service.list(null, "issued", TENANT));
            }
            case "08-list-outsourced-filter": {
                ProcessingOrder withSupplier = po("po-1", "order-001", "SO-1");
                withSupplier.setProcessorSupplierId("sup-1");
                ProcessingOrder withoutSupplier = po("po-2", "order-002", "SO-2");
                when(processingOrderMapper.selectList(any())).thenReturn(List.of(withSupplier, withoutSupplier));
                when(orderMapper.selectBatchIds(anyCollection())).thenReturn(List.of(
                        order("order-001"), order("order-002")));
                return dto(service.list(null, null, TENANT, true));
            }
            case "09-list-null-order-ids": {
                // #6226：order_id 全为空的行 —— `orders.get(null)` 不得抛（空集分支必须是可变表）
                when(processingOrderMapper.selectList(any())).thenReturn(List.of(
                        po("po-1", null, "SO-1"), po("po-2", null, "SO-2")));
                when(orderMapper.selectBatchIds(anyCollection())).thenReturn(List.of());
                return dto(service.list(null, null, TENANT));
            }
            case "10-list-empty": {
                when(processingOrderMapper.selectList(any())).thenReturn(List.of());
                return dto(service.list(null, null, TENANT));
            }
            case "11-detail-missing-but-order-exists": {
                when(processingOrderMapper.selectOne(any())).thenReturn(null);
                when(orderMapper.selectById("order-001")).thenReturn(order("order-001"));
                return dto(service.getDetail("order-001", TENANT));
            }
            case "12-detail-neither-exists": {
                when(processingOrderMapper.selectOne(any())).thenReturn(null);
                when(orderMapper.selectById("order-missing")).thenReturn(null);
                when(orderMapper.selectOne(any())).thenReturn(null);
                try {
                    service.getDetail("order-missing", TENANT);
                    throw new AssertionError("不存在的订单必须 404");
                } catch (BusinessException e) {
                    Map<String, Object> frozen = new LinkedHashMap<>();
                    frozen.put("code", e.getCode());
                    frozen.put("message", e.getMessage());
                    return frozen;
                }
            }
            case "13-list-mixed-order-presence": {
                // 一行有订单、一行没有 ⇒ 两行都出，缺失订单的字段留空（不因缺订单丢行）
                ProcessingOrder withOrder = po("po-1", "order-001", "SO-1");
                ProcessingOrder withoutOrder = po("po-2", null, "SO-2");
                when(processingOrderMapper.selectList(any())).thenReturn(List.of(withOrder, withoutOrder));
                when(orderMapper.selectBatchIds(anyCollection())).thenReturn(List.of(order("order-001")));
                return dto(service.list(null, null, TENANT));
            }
            default:
                throw new IllegalArgumentException("未知读面场景: " + scenario);
        }
    }

    /** 扫码 URL 三条边界。 */
    private Object scanUrl(String scenario) {
        switch (scenario) {
            case "01-trailing-slash-trimmed": {
                ReflectionTestUtils.setField(service, "shortLinkBaseUrl", "https://staging.example.com///");
                return detailWithoutItems(po("po-1", "order-001", "SO-1")).getScanUrl();
            }
            case "02-blank-short-code": {
                ProcessingOrder po = po("po-1", "order-001", "SO-1");
                po.setShortCode("   ");
                return detailWithoutItems(po).getScanUrl();
            }
            case "03-empty-base": {
                ReflectionTestUtils.setField(service, "shortLinkBaseUrl", "");
                return detailWithoutItems(po("po-1", "order-001", "SO-1")).getScanUrl();
            }
            default:
                throw new IllegalArgumentException("未知扫码场景: " + scenario);
        }
    }

    private ProcessingOrderResponse detailWithoutItems(ProcessingOrder po) {
        when(processingOrderMapper.selectOne(any())).thenReturn(po);
        when(orderMapper.selectById("order-001")).thenReturn(order("order-001"));
        return service.getDetail("po-1", TENANT);
    }

    // ── 夹具：实体 ─────────────────────────────────────────────────────────

    private static ProcessingOrder po(String id, String orderId, String no) {
        return ProcessingOrder.builder()
                .id(id).tenantId(TENANT).orderId(orderId)
                .processingOrderNo("JG-20261106-0001")
                .status("issued")
                .shortCode("SC-0001")
                .build();
    }

    /** 每一个 DTO 字段都有值的一行（读面「全字段」场景的输入）。 */
    private static ProcessingOrder fullPo() {
        ProcessingOrder po = ProcessingOrder.builder()
                .id("po-1").tenantId(TENANT).orderId("order-001")
                .processingOrderNo("JG-20261106-0001")
                .processor("本厂")
                .processorSupplierId("sup-1")
                .expectedDeliveryDate(LocalDate.parse("2026-11-20"))
                .status("issued")
                .remark("加急出")
                .templateVersion(3)
                .generatedAt(at("2026-11-06T01:00:00Z"))
                .issuedAt(at("2026-11-06T02:00:00Z"))
                .inProcessingAt(at("2026-11-06T03:00:00Z"))
                .completedAt(at("2026-11-06T04:00:00Z"))
                .cancelledAt(at("2026-11-06T05:00:00Z"))
                .cancelledReason("客户改期")
                .printCount(7)
                .routeKey("route-1")
                .routeRequestedKey("route-0")
                .routeSource("direct")
                .orderKind("processing")
                .shortCode("SC-0001")
                .build();
        po.setItemsSnapshot(List.of(allKeysRow()));
        return po;
    }

    /** 全键快照行（{@code items_snapshot} 的落库形态；读面会把它映射回 {@code ProcessingOrderItemBrief}）。 */
    private static Map<String, Object> allKeysRow() {
        Map<String, Object> row = new LinkedHashMap<>(allKeysProcessingInfo());
        row.remove("skuCode");
        row.remove("formulaText");
        row.put("formula_text", "1.80 × 2.00 × 2");
        row.put("itemId", "i-1");
        row.put("productName", "布艺遮光帘");
        row.put("quantity", new BigDecimal("2"));
        row.put("width", new BigDecimal("1.80"));
        row.put("height", new BigDecimal("2.00"));
        row.put("processingItems", List.of());
        return row;
    }

    private static Order order(String id) {
        return Order.builder()
                .id(id).tenantId(TENANT)
                .orderNo("ORD-" + id)
                .status("producing")
                .customerName("张三")
                .customerPhone("13800000000")
                .build();
    }

    private static OffsetDateTime at(String iso) {
        return OffsetDateTime.ofInstant(java.time.Instant.parse(iso), ZoneOffset.UTC);
    }

    // ── golden 断言 ────────────────────────────────────────────────────────

    @SuppressWarnings("unchecked")
    private void assertGolden(String section, Map<String, Object> actual) throws IOException {
        if (Boolean.parseBoolean(System.getProperty(UPDATE_FLAG, "false"))) {
            Files.createDirectories(GOLDEN.getParent());
            Map<String, Object> merged = Files.exists(GOLDEN)
                    ? mapper.readValue(Files.readString(GOLDEN, StandardCharsets.UTF_8), Map.class)
                    : new LinkedHashMap<>();
            Map<String, Object> sectionMap = (Map<String, Object>) merged.computeIfAbsent(section,
                    k -> new LinkedHashMap<String, Object>());
            sectionMap.putAll(actual);
            Files.writeString(GOLDEN, mapper.writerWithDefaultPrettyPrinter().writeValueAsString(merged) + "\n",
                    StandardCharsets.UTF_8);
            return;
        }
        assertThat(Files.exists(GOLDEN))
                .as("golden 不存在（%s）⇒ 本判据无从判起。录制：mvnw test -D%s=true", GOLDEN, UPDATE_FLAG)
                .isTrue();
        Map<String, Object> golden = mapper.readValue(Files.readString(GOLDEN, StandardCharsets.UTF_8), Map.class);
        assertThat(golden).as("golden 缺少段 %s —— 新增段必须先重新录制并说明它冻的是什么", section)
                .containsKey(section);
        Map<String, Object> expected = (Map<String, Object>) golden.get(section);
        // 逐场景断言（不是整段一比）：红的时候**具名**是哪个场景变了
        assertThat(actual.keySet())
                .as("段 %s 的场景集与 golden 不一致（新增 / 删除场景都必须重新录制并说明它冻的是什么）", section)
                .isEqualTo(expected.keySet());
        for (String key : actual.keySet()) {
            assertThat(pretty(actual.get(key)))
                    .as("段 %s / 场景 %s：与切片前**不逐字节相同** ⇒ 切片改变了行为"
                            + "（快照键集合/键序/缺键语义、读面全字段、批量取数形态、扫码 URL 边界）", section, key)
                    .isEqualTo(pretty(expected.get(key)));
        }
    }

    /**
     * 两侧**同一次归一化**后比较：先落 JSON 文本、再读回 {@code Object}。
     *
     * <p>为什么不能直接比 {@code BigDecimal} 的字面量：{@code new BigDecimal("1.80")} 与
     * 从 golden 读回的 {@code Double 1.8} 文本形态不同（右侧是「读回来的」，形状由 Jackson 决定）
     * ⇒ 同一行为会假红。归一化对**两侧**一致 ⇒ 比较的是「落库 JSON」而不是 JVM 里的数值类型
     * （后者本来就不是行为：落库后读回来都会变成 {@code Double} / {@code BigDecimal} 之一）。</p>
     */
    private String pretty(Object value) {
        try {
            String json = mapper.writeValueAsString(mapper.convertValue(value, Object.class));
            Object normalized = mapper.readValue(json, Object.class);
            return mapper.writerWithDefaultPrettyPrinter().writeValueAsString(normalized);
        } catch (com.fasterxml.jackson.core.JsonProcessingException e) {
            throw new IllegalStateException("冻结投影序列化失败", e);
        }
    }

    private static List<String> keyUnion(List<Map<String, Object>> rows) {
        Set<String> keys = new LinkedHashSet<>();
        for (Map<String, Object> row : rows) {
            keys.addAll(row.keySet());
        }
        return new ArrayList<>(keys);
    }

    private String jsonOf(Object value) {
        try {
            return mapper.writeValueAsString(value);
        } catch (com.fasterxml.jackson.core.JsonProcessingException e) {
            throw new IllegalStateException("夹具 JSON 序列化失败", e);
        }
    }

    private Object dto(Object value) {
        return mapper.convertValue(value, Object.class);
    }
}
