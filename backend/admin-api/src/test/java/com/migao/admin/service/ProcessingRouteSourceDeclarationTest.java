package com.migao.admin.service;

// case_ids: PG-048, PG-049, PG-050, PG-051, PG-052

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProductionRouteSignal;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * **消灭信号映射这层「名词解释」**（issue #4452，包 C）—— 部位改走受控来源、工艺改走加工项显式声明。
 *
 * <h2>病根（代码事实，改前实测）</h2>
 * {@code ProcessingOrderService.deriveRouteKey} 的派生层按「加工项名 → 加工项 options → 商品名 →
 * 销售方式」顺序做 {@code contains} 中文子串匹配（{@code production_route_signals} +
 * {@code firstSignalMatch}）。判据绑在**研发改的常量表**上，而**加工项目录是商家可自定义的业务数据**
 * ⇒ 每加一个自定义名就多一分静默错配（{@code craft-routing-customization.md} §4 P2 已实证：
 * V58 错配 ⇒ 纱帘订单拿到布帘 11 道工序，**工序与工资全错**）。
 *
 * <h2>本文件钉住的四条口径</h2>
 * <ol>
 *   <li><b>两维都在订单行上 ⇒ 全程不读信号表</b>（连一次 {@code routeSignals} 都不许发生）；</li>
 *   <li><b>部位 = 受控来源</b>：V63 {@code curtain_type} 列 &gt; {@code componentRole} 受控枚举
 *       （{@code 纱} ⇒ 纱帘；{@code 主布}/{@code 配布边} ⇒ 布帘）—— **商品名不再是判据**；</li>
 *   <li><b>工艺 = 加工项显式声明</b>：{@code processing_items.craft_hint} —— 改声明 ⇒ 结果随之变，
 *       改加工项**名**但声明不动 ⇒ 结果不变；</li>
 *   <li><b>存量单（无 V63 列值）仍走信号表兜底</b>，但兜底信号源**只剩加工项名/options**
 *       （商品名 / 销售方式已从判据里摘掉）。</li>
 * </ol>
 *
 * <h2>红证（注入式，改前实测）</h2>
 * 每条用例的 javadoc 写明「把哪一处改回旧形态 ⇒ 本用例红」。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("信号映射退场：部位走 componentRole、工艺走加工项声明（issue #4452）")
class ProcessingRouteSourceDeclarationTest {

    private static final Long TENANT = 1L;

    @Mock
    private com.migao.admin.mapper.ProcessingOrderMapper processingOrderMapper;
    @Mock
    private com.migao.admin.mapper.OrderMapper orderMapper;
    @Mock
    private com.migao.admin.mapper.OrderItemMapper orderItemMapper;
    @Mock
    private com.migao.admin.mapper.ProcessingItemMapper processingItemMapper;
    @Mock
    private OrderService orderService;
    @Mock
    private com.migao.admin.mapper.ProcessingPositionOperationMapper positionOperationMapper;
    @Mock
    private com.migao.admin.mapper.ProductionWorkLogMapper workLogMapper;
    @Mock
    private ClientRequestIdService clientRequestIdService;
    @Mock
    private ProductionOperationQueryService productionOperationQueryService;
    @Mock
    private ProductionOperationQtyClient productionOperationQtyClient;

    @Spy
    private ObjectMapper objectMapper = new ObjectMapper();

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, ProcessingOrder.class);
        stubQty();
        // 目录查询：默认**无该加工项**（= craft_hint 缺省）。逐用例再按需覆盖。
        lenient().when(processingItemMapper.selectById(anyString())).thenReturn(null);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ══════════════════════════════ 判据 1 / 2：部位走受控来源 ══════════════════════════════

    /**
     * 判据 1 + 2（issue #4452 验收判据 2）：{@code componentRole=纱} + 加工项声明 {@code craft_hint=打孔}
     * ⇒ 路线键 = {@code 纱帘×打孔}。
     *
     * <p><b>红证</b>：把 {@code componentRole} 这一层摘掉（部位只从 {@code curtain_type} 列取）
     * ⇒ 部位退化成默认 {@code 布帘} ⇒ 本用例红（请求键 {@code 布帘×打孔}）。
     * 若把判据改回「商品名 {@code contains 纱}」，商品名是「打孔帘」⇒ 也红。</p>
     */
    @Test
    @DisplayName("#4452 判据 2：componentRole=纱 + craft_hint=打孔 ⇒ 纱帘×打孔")
    void componentRoleSheerWithDeclaredCraftHint() {
        stubRoutings();
        stubSignals();
        when(processingItemMapper.selectById("p-sheer")).thenReturn(
                processingItem("打孔", "打孔"));

        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(
                orderItem("item-1", "打孔帘", "主布行", "p-sheer", "打孔", "纱", null, null)));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(po.get().getRouteRequestedKey())
                .as("部位 = componentRole=纱 ⇒ 纱帘；工艺 = 加工项声明的 craft_hint=打孔 ⇒ 纱帘×打孔")
                .isEqualTo("纱帘×打孔");
    }

    /**
     * 判据 1（issue #4452 验收判据 1）：商品名含「纱」但 {@code componentRole=主布} ⇒ 部位 = **布帘**。
     *
     * <p>这正是病根的可复现形态：旧实现去**营销文案**里 {@code contains '纱'} ⇒ 纱帘订单拿到布帘路线
     * 的反向错配（这里反过来：布帘订单被商品名里的「纱」拖去纱帘）。</p>
     *
     * <p><b>红证</b>：把部位来源改回「商品名 {@code contains}」（或把 {@code componentRole} 层摘掉
     * 只剩商品名）⇒ 部位 = 纱帘 ⇒ 本用例红。</p>
     */
    @Test
    @DisplayName("#4452 判据 1：商品名含「纱」但 componentRole=主布 ⇒ 布帘（商品名不再是判据）")
    void productNameIsNotAPositionSignal() {
        stubRoutings();
        stubSignals();
        when(processingItemMapper.selectById("p-main")).thenReturn(processingItem("韩褶-布", "韩褶"));

        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(
                orderItem("item-1", "遮光纱A", "主布行", "p-main", "韩褶-布", "主布", null, null)));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(po.get().getRouteRequestedKey())
                .as("商品名里的「纱」不是判据 ⇒ 部位 = 主布 ⇒ 布帘×韩褶")
                .isEqualTo("布帘×韩褶");
    }

    // ══════════════════════════════ 判据 3 / 4：工艺走加工项显式声明 ══════════════════════════════

    /**
     * 判据 3（issue #4452 验收判据 3 前半）：加工项「打孔」声明 {@code craft_hint=打孔}
     * ⇒ 工艺 = 打孔；**改声明**（→ 韩褶）⇒ 结果随之变。
     *
     * <p><b>红证</b>：读侧仍 {@code contains} 加工项**名**（「打孔」含「打孔」）⇒ 改声明后结果
     * 不变（仍 打孔）⇒ 本用例红。</p>
     */
    @Test
    @DisplayName("#4452 判据 3：工艺 = 加工项声明的 craft_hint；改声明 ⇒ 结果随之变")
    void craftComesFromDeclaredHintNotFromName() {
        stubRoutings();
        stubSignals();
        // 加工项**名**里含「打孔」，但声明是「韩褶」⇒ 结果必须听声明
        when(processingItemMapper.selectById("p-hole")).thenReturn(
                processingItem("打孔", "韩褶"));

        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(
                orderItem("item-1", "遮光成品X", "主布行", "p-hole", "打孔", "主布", null, null)));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(po.get().getRouteRequestedKey())
                .as("声明 = 韩褶 ⇒ 必须听声明，不得从名字里猜出「打孔」")
                .isEqualTo("布帘×韩褶");
    }

    /**
     * 判据 4（issue #4452 验收判据 4）：加工项**名**改了但声明没改 ⇒ 结果不变。
     *
     * <p>两条明细的加工项名不同（「A 款」「B 款」）、声明都是 {@code 打孔} ⇒ 两单的请求键**逐字相同**。</p>
     *
     * <p><b>红证</b>：读侧仍 {@code contains} 加工项名 ⇒ 名里没有「打孔」两个字的那条派不出工艺
     * ⇒ 两条的请求键不同 ⇒ 本用例红。</p>
     */
    @Test
    @DisplayName("#4452 判据 4：加工项名改了但声明没改 ⇒ 结果不变")
    void renamingProcessingItemDoesNotChangeRoute() {
        stubRoutings();
        stubSignals();
        when(processingItemMapper.selectById("p-a")).thenReturn(processingItem("A 款加工", "打孔"));
        when(processingItemMapper.selectById("p-b")).thenReturn(processingItem("B 款加工", "打孔"));

        AtomicReference<ProcessingOrder> poA = stubGenerate(List.of(
                orderItem("item-1", "遮光成品X", "主布行", "p-a", "A 款加工", "主布", null, null)));
        assertThat(service().generate(List.of("order-001"), TENANT, "u1").get(0).isSuccess()).isTrue();

        AtomicReference<ProcessingOrder> poB = stubGenerate(List.of(
                orderItem("item-1", "遮光成品X", "主布行", "p-b", "B 款加工", "主布", null, null)));
        assertThat(service().generate(List.of("order-001"), TENANT, "u1").get(0).isSuccess()).isTrue();

        assertThat(poA.get().getRouteRequestedKey())
                .as("加工项名里没有「打孔」两字，但声明有 ⇒ 仍派生 打孔")
                .isEqualTo("布帘×打孔");
        assertThat(poB.get().getRouteRequestedKey())
                .as("换了个名字、声明不变 ⇒ 结果逐字不变（证明判据不是名字）")
                .isEqualTo(poA.get().getRouteRequestedKey());
    }

    // ══════════════════════════════ 判据：零读取信号表 ══════════════════════════════

    /**
     * 判据（issue #4452 交付判据 1）：订单行带 {@code curtain_type=纱帘} + {@code craft=打孔}
     * ⇒ 路线 = 纱帘×打孔，**且全程不读** {@code production_route_signals}。
     *
     * <p><b>注入法（本用例即红证）</b>：把信号表**删空**（{@code routeSignals → List.of()}）——
     * 若派生链仍在两维齐全时读信号表（旧实现 {@code deriveRouteKey} 无条件先算 {@code signals(entry)}
     * 并查表），则「删空信号表」会改变可观测行为。本用例另外把**商品名**写成「打孔帘」：
     * 旧实现里商品名是信号源，删空表后派生不出任何一维 ⇒ 本用例红。</p>
     */
    @Test
    @DisplayName("#4452 交付判据 1：两维都在订单行上 ⇒ 路线正确且全程不读信号表")
    void explicitLineFieldsNeverReadTheSignalTable() {
        stubRoutings();
        // 信号表**删空** —— 两维都由订单行给出时它不该被读，更不该影响结果
        lenient().when(productionOperationQueryService.routeSignals(TENANT)).thenReturn(List.of());

        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(
                orderItem("item-1", "打孔帘", "主布行", "p-none", "工序甲", null, "纱帘", "打孔")));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(po.get().getRouteRequestedKey())
                .as("两维直读 ⇒ 纱帘×打孔（信号表删空也拿得到）")
                .isEqualTo("纱帘×打孔");
        verify(productionOperationQueryService, never()).routeSignals(TENANT);
    }

    // ══════════════════════════════ 存量单兜底（回归，不许打破）══════════════════════════════

    /**
     * 存量单（**无 V63 列值**）仍能派生成功 —— 信号表降级为「存量单兜底」，表**不删**。
     *
     * <p><b>红证</b>：把兜底层一并删掉（存量单直接落默认）⇒ 本用例红
     * （请求键退化成 {@code 布帘×韩褶} 或 null）。</p>
     */
    @Test
    @DisplayName("#4452 回归：存量单（无 V63 列值）仍能派生成功")
    void legacyOrderWithoutV63ColumnsStillDerives() {
        stubRoutings();
        stubSignals();

        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(
                orderItem("item-1", "布艺遮光帘A", "主布行", "p-none", "韩褶-布", null, null, null)));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(po.get().getRouteRequestedKey())
                .as("存量单：加工项名「韩褶-布」仍经信号表兜底派生出 布帘×韩褶")
                .isEqualTo("布帘×韩褶");
        verify(productionOperationQueryService, org.mockito.Mockito.atLeastOnce()).routeSignals(TENANT);
    }

    /**
     * 判据（issue #4452 交付判据 4 的前半）：商品名 / 销售方式**不再是**路线键的判据来源。
     *
     * <p>存量单（无 V63 列值）+ 加工项名不含任何信号关键字，而商品名含「纱帘」、销售方式含「打孔」
     * ⇒ 两维都派生不出来 ⇒ 落默认（{@code route_requested_key = null}）。</p>
     *
     * <p><b>红证</b>：把商品名 / 销售方式放回信号源 ⇒ 请求键会变成 {@code 纱帘×打孔}（或半命中
     * {@code 纱帘×韩褶}）⇒ 本用例红。</p>
     */
    @Test
    @DisplayName("#4452 交付判据 4：商品名 / 销售方式零命中（不再是判据来源）")
    void productNameAndSellingMethodAreNotSignalSources() {
        stubRoutings();
        stubSignals();

        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(
                orderItem("item-1", "纱帘成品打孔款", "散剪打孔", "p-none", "工序甲", null, null, null)));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(po.get().getRouteRequestedKey())
                .as("商品名含「纱帘」、销售方式含「打孔」都不算信号 ⇒ 两维全不命中 ⇒ 没有「想走的键」")
                .isNull();
        assertThat(po.get().getRouteSource()).as("两维全不命中 ⇒ default").isEqualTo("default");
    }

    /**
     * **结构性判据**：{@code ProcessingOrderService} 里不得再出现
     * 「把商品名 / 销售方式喂进信号列表」的残留命中点。
     *
     * <p>前一条用例是**行为**判据（红在运行期），这一条是**残留**判据（红在源码文本）——
     * 两者互补：行为判据挡不住「代码里还留着那两行、只是当前恰好不命中」的形态。</p>
     *
     * <p><b>红证</b>：把 {@code signals()} 里 {@code productName} / {@code sellingMethod} 两段
     * 加回去 ⇒ 本用例红。</p>
     */
    @Test
    @DisplayName("#4452 交付判据 4：signals() 里零残留（商品名 / 销售方式不得再进信号列表）")
    void signalsMethodHasNoProductNameOrSellingMethodRemnants() throws Exception {
        String source = Files.readString(
                Path.of("src/main/java/com/migao/admin/service/ProcessingOrderService.java"),
                StandardCharsets.UTF_8);
        int start = source.indexOf("private static List<String> signals(");
        assertThat(start).as("signals() 必须仍存在（存量单兜底的信号源）").isGreaterThan(0);
        int end = source.indexOf("\n    /**", start);
        assertThat(end).as("signals() 的方法体必须能定位").isGreaterThan(start);
        String body = source.substring(start, end);

        assertThat(body)
                .as("signals() 里不得再有 productName（商品名是营销文案，不是结构化输入）")
                .doesNotContain("productName");
        assertThat(body)
                .as("signals() 里不得再有 sellingMethod（销售方式不是部位/工艺判据）")
                .doesNotContain("sellingMethod");
    }

    // ══════════════════════════════ 迁移：存量加工项不猜 ══════════════════════════════

    /**
     * 判据 5（issue #4452 验收判据 5）：存量加工项的 {@code craft_hint} **不硬猜**。
     *
     * <p>本单的迁移只加列（{@code ALTER TABLE … ADD COLUMN IF NOT EXISTS}），**不做**任何
     * {@code UPDATE … SET craft_hint = <猜出来的值>}：加工项目录是商家业务数据，从名字里回填
     * 「能唯一确定的才填」这件事本身就是猜（「韩褶-布」既含「韩褶」也可能是别的工艺名的一部分）。
     * 存量单的兜底交给信号表（长期存在），缺口由 {@code GET /routing-gaps} 与异常订单清单可见。</p>
     *
     * <p><b>红证</b>：迁移里加一条 {@code UPDATE processing_items SET craft_hint = …}
     * ⇒ 本用例红。（该写法同时会被 {@code test_migration_references_exist_in_schema} 判红。）</p>
     */
    @Test
    @DisplayName("#4452 判据 5：craft_hint 迁移只加列、不猜值（无 UPDATE 回填）")
    void craftHintMigrationAddsColumnWithoutGuessing() throws Exception {
        // 迁移文件的两个载体（issue #5243）：历史链整链归档到 `db/migration-archive/`，
        // 活目录只放切点之后的增量 ⇒ **两个都要扫**（只看活目录 ⇒ 找不到 V78 ⇒ 本判据空转/假红）。
        // 判据意图一字未改：仍是「**恰好一条**专门加 craft_hint 的迁移，且它不猜值」。
        List<Path> hit = new ArrayList<>();
        for (String sub : List.of("src/main/resources/db/migration",
                                  "src/main/resources/db/migration-archive")) {
            Path dir = Path.of(sub);
            if (!Files.isDirectory(dir)) {
                continue;   // 两个目录都缺席时 hasSize(1) 会判红（fail-loud，不静默）
            }
            try (var stream = Files.list(dir)) {
                stream.filter(p -> p.getFileName().toString().contains("craft_hint"))
                        .forEach(hit::add);
            }
        }
        assertThat(hit).as("必须有一条专门加 craft_hint 的迁移").hasSize(1);
        String sql = Files.readString(hit.get(0), StandardCharsets.UTF_8);

        assertThat(sql).as("加列必须幂等（MigrationRunner 会重跑）")
                .contains("ADD COLUMN IF NOT EXISTS craft_hint");
        assertThat(sql.toUpperCase())
                .as("不得按加工项名硬猜回填（能唯一确定的也不猜 —— 存量单由信号表兜底）")
                .doesNotContain("UPDATE PROCESSING_ITEMS");
    }

    // ══════════════════════════════ 装配 / 夹具 ══════════════════════════════

    private ProcessingOrderService service() {
        return new ProcessingOrderService(
                processingOrderMapper, orderMapper, orderItemMapper, processingItemMapper,
                orderService, objectMapper,
                new ProductionService(processingOrderMapper, positionOperationMapper, workLogMapper, orderMapper,
                        orderItemMapper, clientRequestIdService),
                productionOperationQueryService, productionOperationQtyClient);
    }

    /** 算料桩：每道工序统一给「1 / fallback」—— 本文件不关心数量口径。 */
    private void stubQty() {
        lenient().when(productionOperationQtyClient.resolve(any())).thenAnswer(inv -> {
            List<Map<String, Object>> request = inv.getArgument(0);
            List<ProductionOperationQtyClient.PositionQty> resolved = new ArrayList<>();
            for (Map<String, Object> position : request) {
                Map<String, BigDecimal> qty = new LinkedHashMap<>();
                Map<String, String> source = new LinkedHashMap<>();
                for (Object raw : (List<?>) position.get("operations")) {
                    qty.put(String.valueOf(raw), BigDecimal.ONE);
                    source.put(String.valueOf(raw), "fallback");
                }
                resolved.add(new ProductionOperationQtyClient.PositionQty(
                        (String) position.get("position_name"), qty, source));
            }
            return resolved;
        });
    }

    /** 信号映射表（V60 种子终态 + V63 修正）—— 只服务**存量单兜底**用例。 */
    private void stubSignals() {
        lenient().when(productionOperationQueryService.routeSignals(TENANT)).thenReturn(List.of(
                signal("sig-v60-01", "帘头", "帘头", null, 1),
                signal("sig-v60-02", "纱", "纱帘", null, 2),
                signal("sig-v60-03", "布", "布帘", null, 3),
                signal("sig-v60-04", "韩褶", null, "韩褶", 1),
                signal("sig-v60-05", "打孔", null, "打孔", 2)));
    }

    private static ProductionRouteSignal signal(String id, String keyword, String curtainType,
                                                String craft, int priority) {
        return ProductionRouteSignal.builder().id(id).tenantId(TENANT).signal(keyword)
                .curtainType(curtainType).craft(craft).priority(priority)
                .status("active").deleted(0).build();
    }

    /** 路线库桩：布帘/纱帘有模板，其余部位 ⇒ T2 回落默认模板。 */
    private void stubRoutings() {
        lenient().when(productionOperationQueryService.routeTemplateFor(eq(TENANT), anyString()))
                .thenAnswer(inv -> {
                    String position = inv.getArgument(1);
                    return "布帘".equals(position) || "纱帘".equals(position)
                            ? RoutingModelFixture.defaultTemplate(TENANT) : null;
                });
        lenient().when(productionOperationQueryService.defaultRouteTemplate(TENANT))
                .thenReturn(RoutingModelFixture.defaultTemplate(TENANT));
        lenient().when(productionOperationQueryService.routeRules(TENANT))
                .thenReturn(RoutingModelFixture.rulesWithFactors(TENANT));
        lenient().when(productionOperationQueryService.operationPositions(TENANT))
                .thenReturn(RoutingModelFixture.canonicalPositions(TENANT));
        lenient().when(productionOperationQueryService.operationsByName(TENANT))
                .thenReturn(RoutingModelFixture.catalog());
        lenient().when(productionOperationQueryService.defaultCraft(TENANT)).thenReturn("韩褶");
        lenient().when(productionOperationQueryService.normalizeOperationName(anyString()))
                .thenAnswer(inv -> RoutingModelFixture.logicalName(inv.getArgument(0)));
        lenient().when(productionOperationQueryService.variantNameOf(anyString(), any(), any()))
                .thenAnswer(inv -> RoutingModelFixture.variantNameOf(
                        inv.getArgument(0), inv.getArgument(1), inv.getArgument(2)));
    }

    /**
     * 一条订单明细。{@code curtainType}/{@code craft} 为 {@code null} ⇒ **不写列**（= 存量单形态）。
     *
     * @param componentRole {@code processing_info} 顶层的部件角色（受控枚举：主布/配布边/纱）
     */
    private static OrderItem orderItem(String itemId, String productName, String sellingMethod,
                                       String processingItemId, String processingItemName,
                                       String componentRole, String curtainType, String craft) {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("colorName", "米白");
        info.put("sellingMethod", sellingMethod);
        if (componentRole != null) {
            info.put("componentRole", componentRole);
        }
        info.put("processingItems", List.of(Map.of(
                "id", processingItemId, "name", processingItemName,
                "unitPrice", 3.0, "quantity", 2, "unit", "米")));
        return OrderItem.builder()
                .id(itemId).tenantId(TENANT).orderId("order-001")
                .productName(productName).quantity(BigDecimal.valueOf(2))
                .width(new BigDecimal("2.5")).height(new BigDecimal("2.8"))
                .curtainType(curtainType).craft(craft)
                .processingInfo(info)
                .build();
    }

    private static ProcessingItem processingItem(String name, String craftHint) {
        return ProcessingItem.builder().id("pi-1").tenantId(TENANT).name(name)
                .craftHint(craftHint).options(List.of()).status("active").deleted(0).build();
    }

    /** 订单/明细/主键回填的公共桩；返回捕获**落库行**的容器。 */
    private AtomicReference<ProcessingOrder> stubGenerate(List<OrderItem> items) {
        Order order = Order.builder().id("order-001").tenantId(TENANT)
                .orderNo("ORD-20260919-0001").status("confirmed")
                .customerName("张三").customerPhone("13800138000").build();
        when(orderMapper.selectById("order-001")).thenReturn(order);
        when(orderItemMapper.selectList(any())).thenReturn(items);
        AtomicReference<ProcessingOrder> poRef = new AtomicReference<>();
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenAnswer(inv -> poRef.get());
        when(processingOrderMapper.insert(any(ProcessingOrder.class))).thenAnswer(inv -> {
            ProcessingOrder inserted = inv.getArgument(0);
            inserted.setId("po-001");
            poRef.set(inserted);
            return 1;
        });
        return poRef;
    }
}
