// case_ids: PG-001, PG-062
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProductionCraft;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.entity.ProductionRouteRule;
import com.migao.admin.entity.ProductionRouteTemplate;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProductionCraftMapper;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOperationPositionMapper;
import com.migao.admin.mapper.ProductionOperationPriceVersionMapper;
import com.migao.admin.mapper.ProductionRouteRuleMapper;
import com.migao.admin.mapper.ProductionRouteSignalMapper;
import com.migao.admin.mapper.ProductionRouteTemplateMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Captor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.io.InputStream;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 🔴 **issue #6114**：默认配置下，**纱帘单**只要勾选下列任一特殊选项就整张加工单生成失败 ——
 * {@code 拼1次 / 拼2次 / 拼3次 / 加花边 / 加铅块 / 接高 / 加logo条 / 加立边 / 扣环 / 防翘扣}
 * （另含同源的 {@code 双眼皮接高}）。报错逐字：
 *
 * <pre>
 * 工艺路线「窗帘工序路线（默认）」（产品形态「纱帘」）引用的工序 [花边] 在工序库中不存在，无法实例化工序
 * </pre>
 *
 * <h2>归因</h2>
 * <p>这批**特殊选项条件工序规则**的 {@code position} 为 {@code NULL}（= 不限部位），而它们引用的
 * 逻辑工序（{@code 拼1次 / 拼2次 / 拼3次 / 花边 / 铅坠 / 接高 / logo条 / 立边 / 扣环 / 防翘扣}）
 * 在工序库里**只有布帘变体**（有 {@code 花边-布}、没有 {@code 花边-纱}）⇒ 规则在**纱帘单**上照样命中
 * ⇒ {@code variantNameOf(逻辑名, '纱帘', catalog)} 返回 {@code null} ⇒ 该逻辑名进
 * {@code missing_operations} ⇒ {@code resolveRoute} fail-closed
 * （fail-closed 本身是对的，缺口在**默认配置**）。</p>
 *
 * <p>修法 = **只改种子**：开租播种时给这 16 条特殊选项规则写上规则级部位限定
 * {@code position='布帘'}（口径来源 = 用户 2026-09-21 裁定「如果有一些工序只能布帘有或者纱帘有，
 * 可以在**适用条件**上设置」）。⛔ 不发明 {@code -纱} 变体（那是造新工序，会进工人计件口径）。</p>
 *
 * <h2>为什么判据的对象是「开租播种」而不是 {@code schema.sql}</h2>
 * <p>{@code backend/admin-api/src/main/resources/db/init/schema.sql} 的逐租户种子块
 * （{@code rr-v72-*}）只在**首次建库**跑一次（{@code MigrationRunner} 按**文件名**记账）⇒
 * 今天新开的租户走不到它。新租户的规则来自 {@code RegistrationService} →
 * {@link ProductionSeedTemplateService#applyTemplate}（本类第 ① 腿的主体）。</p>
 *
 * <h2>两条腿（缺一即假绿）</h2>
 * <ol>
 *   <li><b>内容腿</b>（{@link OptionRulePosition}）：真实跑一次
 *       {@link ProductionSeedTemplateService#applyTemplate}，捕获它落库的每一条规则 ⇒
 *       **模板 JSON 的 16 条特殊选项规则逐条** {@code position='布帘'}；</li>
 *   <li><b>行为腿</b>（{@link SheerOrderStopsFailingClosed}）：把**真实播种产出的规则**喂给
 *       {@link ProcessingOrderService#derivePositionPayload}（真实实例化路径 + 仓内既有工序库夹具）
 *       —— ① 纱帘单能派工（不含布帘变体、不 fail-closed）；② 同一配置的布帘单**照旧**插入布帘变体。</li>
 * </ol>
 *
 * <p><b>红证</b>（把 {@code ProductionSeedTemplateService.OPTION_OPERATION_POSITION} 改回 {@code null}
 * ⇒ 两条腿同时红）：见 PR body 的红证表。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("开租种子：#6114 特殊选项规则必须带部位限定（纱帘单不再整单 fail-closed）")
class ProductionSeedOptionRulePositionTest {

    private static final Long TENANT = 42L;
    private static final String ORDER_ID = "order-001";

    /** 正被播种的模板 = **生产资产**（不是测试副本）⇒ 断言随之自动跟上模板演化。 */
    private static final String TEMPLATE_RESOURCE = "production-templates/curtain/seed.json";

    // ── 开租播种侧（ProductionSeedTemplateService）────────────────────────────────
    @Mock
    private ProductionOperationMapper productionOperationMapper;
    @Mock
    private ProductionOperationPriceVersionMapper priceVersionMapper;
    @Mock
    private ProductionRouteTemplateMapper productionRouteTemplateMapper;
    @Mock
    private ProductionOperationPositionMapper productionOperationPositionMapper;
    @Mock
    private ProductionRouteRuleMapper productionRouteRuleMapper;
    @Mock
    private ProductionCraftMapper productionCraftMapper;

    // ── 实例化侧（ProcessingOrderService）─────────────────────────────────────────
    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private OrderMapper orderMapper;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private ProcessingItemMapper processingItemMapper;
    @Mock
    private OrderService orderService;
    @Mock
    private ProcessingPositionOperationMapper positionOperationMapper;
    @Mock
    private ProductionWorkLogMapper workLogMapper;
    @Mock
    private ClientRequestIdService clientRequestIdService;
    @Mock
    private ProductionOperationQtyClient productionOperationQtyClient;
    @Mock
    private ProductionRouteSignalMapper productionRouteSignalMapper;

    @Captor
    private ArgumentCaptor<ProductionRouteRule> ruleCaptor;

    /** 开租播种产出的**全部**规则（行为腿的输入 = 真实播种产出，不是手抄字面量）。 */
    private List<ProductionRouteRule> seededRules;
    private ProcessingOrderService service;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        MybatisConfiguration conf = new MybatisConfiguration();
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(conf, ""), Order.class);

        // ── ① 跑完整条真实开租播种路径：工序库「insert 后可见」+ 新结构三表空库 ──
        List<ProductionOperation> operationStore = wireSeedOperationLibrary();
        stubEmptyNewStructure();
        ProductionSeedTemplateService seedService = new ProductionSeedTemplateService(
                productionOperationMapper, productionRouteTemplateMapper,
                productionOperationPositionMapper, productionRouteRuleMapper,
                productionCraftMapper, priceVersionMapper);
        Map<String, Object> applied = seedService.applyTemplate(TENANT, "curtain");
        assertThat(applied.get("applied")).as("窗帘行业必须被套用（否则下面的判据会空跑）").isEqualTo(true);
        assertThat(operationStore).as("开租播种没落任何工序 ⇒ 工序库为空，判据会空跑").isNotEmpty();
        verify(productionRouteRuleMapper, atLeastOnce()).insert(ruleCaptor.capture());
        seededRules = List.copyOf(ruleCaptor.getAllValues());
        assertThat(seededRules).as("开租播种一条规则都没落 ⇒ 判据会空跑").isNotEmpty();

        // ── ② 实例化侧：规则 = **刚播种的那批**；模板/价目/工艺/工序库 = 仓内既有夹具 ──
        when(productionOperationMapper.selectList(any())).thenReturn(operationStore);
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                RoutingModelFixture.defaultTemplateAllPositions(TENANT)));
        when(productionRouteRuleMapper.selectList(any())).thenReturn(seededRules);
        when(productionOperationPositionMapper.selectList(any())).thenReturn(
                RoutingModelFixture.canonicalPositions84(TENANT));
        when(productionCraftMapper.selectList(any())).thenReturn(List.of(
                RoutingModelFixture.defaultCraft(TENANT, "韩褶")));

        ProductionOperationQueryService queryService = new ProductionOperationQueryService(
                productionOperationMapper, productionRouteTemplateMapper, productionRouteRuleMapper,
                productionOperationPositionMapper, productionCraftMapper, productionRouteSignalMapper);
        service = new ProcessingOrderService(
                processingOrderMapper, orderMapper, orderItemMapper, processingItemMapper,
                orderService, new ObjectMapper(),
                new ProductionService(processingOrderMapper, positionOperationMapper, workLogMapper,
                        orderMapper, orderItemMapper, clientRequestIdService),
                queryService, productionOperationQtyClient);

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
        when(orderMapper.selectById(ORDER_ID)).thenReturn(Order.builder()
                .id(ORDER_ID).tenantId(TENANT).orderNo("ORD-20261003-0001").status("confirmed")
                .customerName("张三").customerPhone("13800138000").build());
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(null);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ══════════════════════════ 夹具 ══════════════════════════

    /** 让工序库「insert 后可见」（真实路径读的是**刚插入**的工序库，Mockito 桩不会自动回读）。 */
    private List<ProductionOperation> wireSeedOperationLibrary() {
        List<ProductionOperation> store = new ArrayList<>();
        when(productionOperationMapper.selectList(any())).thenAnswer(inv -> store);
        when(productionOperationMapper.insert(any(ProductionOperation.class))).thenAnswer(inv -> {
            ProductionOperation op = inv.getArgument(0);
            if (op.getId() == null) {
                op.setId("op-" + store.size());
            }
            store.add(op);
            return 1;
        });
        return store;
    }

    private void stubEmptyNewStructure() {
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of());
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of());
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of());
        when(productionCraftMapper.selectList(any())).thenReturn(List.of());
        when(productionRouteTemplateMapper.insert(any(ProductionRouteTemplate.class))).thenReturn(1);
        when(productionOperationPositionMapper.insert(any(ProductionOperationPosition.class))).thenReturn(1);
        when(productionRouteRuleMapper.insert(any(ProductionRouteRule.class))).thenReturn(1);
        when(productionCraftMapper.insert(any(ProductionCraft.class))).thenReturn(1);
    }

    /** 生产模板 JSON 的 16 条特殊选项映射（**只读生产资产**，不另抄一份字面量）。 */
    private static List<JsonNode> optionRoutings() {
        try (InputStream in = ProductionSeedOptionRulePositionTest.class
                .getClassLoader().getResourceAsStream(TEMPLATE_RESOURCE)) {
            assertThat(in).as("读不到生产模板 " + TEMPLATE_RESOURCE + " ⇒ 判据会空跑").isNotNull();
            JsonNode options = new ObjectMapper().readTree(in).path("option_routings");
            assertThat(options.isArray()).as("模板缺 option_routings 数组 ⇒ 判据会空跑").isTrue();
            List<JsonNode> out = new ArrayList<>();
            options.forEach(out::add);
            return out;
        } catch (Exception e) {
            throw new IllegalStateException("读生产模板失败：" + TEMPLATE_RESOURCE, e);
        }
    }

    /** 工序变体名 → 逻辑名（`花边-布` → `花边`；无 `-布` / `-纱` 后缀 ⇒ 原名）。 */
    private static String logicalOf(String variant) {
        if (variant.endsWith("-布") || variant.endsWith("-纱")) {
            return variant.substring(0, variant.length() - 2);
        }
        return variant;
    }



    @Nested
    @DisplayName("内容腿：新租户会应用的那块种子（开租播种）")
    class OptionRulePosition {

        @Test
        @DisplayName("模板 JSON 的 16 条特殊选项规则，播种后 position 逐条 = '布帘'")
        void optionRulesCarryClothPosition() {
            List<JsonNode> options = optionRoutings();
            List<ProductionRouteRule> insertRules = seededRules.stream()
                    .filter(r -> "option".equals(r.getTriggerKind()) && "insert".equals(r.getAction()))
                    .toList();
            assertThat(insertRules.size())
                    .as("播种出的特殊选项 insert 规则数 ≠ 模板的 %d 条 ⇒ 判据会空跑（播种=%d）"
                            .formatted(options.size(), insertRules.size()))
                    .isEqualTo(options.size());

            List<String> wrong = new ArrayList<>();
            for (JsonNode node : options) {
                String name = node.path("option_name").asText();
                List<ProductionRouteRule> hit = insertRules.stream()
                        .filter(r -> name.equals(r.getTriggerValue())).toList();
                if (hit.size() != 1) {
                    wrong.add(name + " → 规则行数 " + hit.size() + "（期望恰好 1）");
                } else if (!"布帘".equals(hit.get(0).getPosition())) {
                    wrong.add(name + " → position=" + hit.get(0).getPosition() + "（期望 布帘）");
                }
            }
            assertThat(wrong).as("""
                    开租种子的特殊选项规则没带 `position='布帘'` ⇒ 这批规则会在**纱帘单**上命中，
                    而它们引用的工序只有布帘变体 ⇒ `variantNameOf(逻辑名, '纱帘', catalog)` 返回 null
                    ⇒ 整张加工单 fail-closed（issue #6114 的原始报错）。""").isEmpty();
        }

        @Test
        @DisplayName("部位限定值在闭词表内（不是随手一个字符串）")
        void positionValueIsInsideTheClosedVocabulary() {
            List<String> outside = seededRules.stream()
                    .filter(r -> "option".equals(r.getTriggerKind()) && "insert".equals(r.getAction()))
                    .map(ProductionRouteRule::getPosition).distinct()
                    .filter(p -> p == null
                            || !ProductionOperationQueryService.POSITION_LIMIT_VOCABULARY.contains(p))
                    .map(String::valueOf).toList();
            assertThat(outside).as("规则级部位限定必须是闭词表里的值（`null` = 不限部位**不在**本判据射程内 ——"
                    + "它由上面的内容腿单独钉住），否则这条规则对**任何**实例化部位都不生效"
                    + "（规则已落库但永不生效的黑洞）").isEmpty();
        }

        @Test
        @DisplayName("工艺变体规则不退化为部位限定（反向护栏）")
        void craftRulesKeepTheirPositionSemantics() {
            List<ProductionRouteRule> dakong = seededRules.stream()
                    .filter(r -> "craft".equals(r.getTriggerKind()) && "打孔".equals(r.getTriggerValue()))
                    .toList();
            assertThat(dakong).as("播种里找不到 `打孔` 工艺规则 ⇒ 判据会空跑").hasSize(1);
            assertThat(dakong.get(0).getPosition())
                    .as("`打孔 → insert 打孔` 被限定到某个部位 ⇒ 另一个帘种少一道打孔（本判据的反向护栏）")
                    .isNull();
            List<ProductionRouteRule> hanzheUp = seededRules.stream()
                    .filter(r -> "craft".equals(r.getTriggerKind()) && "上车布".equals(r.getOperation()))
                    .toList();
            assertThat(hanzheUp).as("播种里找不到 `韩褶 → insert 上车布` ⇒ 判据会空跑").hasSize(1);
            assertThat(hanzheUp.get(0).getPosition())
                    .as("`韩褶 → insert 上车布` 是种子里**唯一**带部位限定的工艺规则（#4962 的冻结口径）")
                    .isEqualTo("布帘");
        }
    }

    // ══════════════════════════ 行为腿 ══════════════════════════

    @Nested
    @DisplayName("行为腿：真实播种规则 + 真实实例化路径（两侧夹住）")
    class SheerOrderStopsFailingClosed {

        @Test
        @DisplayName("① 纱帘单 + 全部「只有布帘变体」的特殊选项 ⇒ 能派工，且不出现布帘变体")
        void sheerOrderInstantiatesWithoutClothVariants() {
            Map<String, String> clothOnly = clothOnlyOptions();
            assertThat(clothOnly.keySet()).as("""
                    模板里没有任何「只有布帘变体」的特殊选项 ⇒ 判据会空跑
                    （或归因变了：这批工序在库里已经有纱帘变体）""").isNotEmpty();

            List<String> operations = derive("纱帘", new ArrayList<>(clothOnly.keySet()));
            assertThat(operations).as("纱帘单没解析出任何工序 ⇒ 前置不成立，判据会空跑").isNotEmpty();

            List<String> leaked = operations.stream()
                    .map(ProductionSeedOptionRulePositionTest::logicalOf)
                    .filter(clothOnly::containsValue).distinct().toList();
            assertThat(leaked).as("""
                    纱帘单里出现了只有布帘变体的工序 %s ⇒ 这批规则在纱帘单上命中了
                    （`position` 没起筛选作用）⇒ 生成加工单会 fail-closed：工艺路线「窗帘工序路线（默认）」
                    （产品形态「纱帘」）引用的工序 [...] 在工序库中不存在，无法实例化工序""".formatted(leaked))
                    .isEmpty();
            assertThat(operations).as("纱帘单不得出现任何布帘变体（`*-布` / `布三边` / `布帘车被`）")
                    .noneMatch(name -> name.endsWith("-布") || "布三边".equals(name) || "布帘车被".equals(name));
            assertThat(operations).as("纱帘单必须仍按纱帘变体实例化（`精裁` → `精裁-纱`）")
                    .contains("精裁-纱");
        }

        @Test
        @DisplayName("② 同一配置的布帘单 ⇒ 照旧插入对应布帘变体（修复不误伤布帘单）")
        void clothOrderStillGetsClothVariants() {
            Map<String, String> clothOnly = clothOnlyOptions();
            List<String> operations = derive("布帘", new ArrayList<>(clothOnly.keySet()));
            List<String> missing = clothOnly.values().stream()
                    .filter(logical -> operations.stream()
                            .filter(name -> logical.equals(ProductionSeedOptionRulePositionTest.logicalOf(name)))
                            .findAny().isEmpty())
                    .toList();
            assertThat(missing).as("""
                    布帘单少了这些逻辑工序 %s ⇒ 部位限定写错（写成别的值 / 把整条规则滤掉）
                    = 车间漏做工序 + 计件漏算（比卡单更坏）""".formatted(missing)).isEmpty();
            assertThat(operations).as("布帘单必须仍插 `花边-布`（#6114 的原始复现选项）").contains("花边-布");
            assertThat(operations).as("布帘单不得出现纱帘变体").noneMatch(name -> name.endsWith("-纱"));
        }

        @Test
        @DisplayName("③ 单选项 `接高` 的纱帘单也应可派工（最小复现面，选项名与逻辑名同名）")
        void singleClothOnlyOptionAlsoInstantiatesOnSheer() {
            List<String> operations = derive("纱帘", List.of("接高"));
            assertThat(operations).as("单选项 `接高` 的纱帘单解析不出任何工序 ⇒ 前置不成立").isNotEmpty();
            assertThat(operations).as("`接高` 在纱帘单上仍带出了 `接高-布`（= 原始报错形态）")
                    .noneMatch(name -> name.contains("接高"));
            assertThat(derive("布帘", List.of("接高")))
                    .as("对照：同一选项在布帘单上**照旧**插 `接高-布`").contains("接高-布");
        }

        /** 用真实派生路径实例化一张订单，返回实例出的**工序名**序列（含变体名）。 */
        private List<String> derive(String curtainType, List<String> specialOptions) {
            Map<String, Object> info = new LinkedHashMap<>();
            info.put("colorName", "米白");
            info.put("sellingMethod", "散剪");
            info.put("processingItems", List.of(Map.of("id", "p-1", "name", "工序甲",
                    "unitPrice", 3.0, "quantity", 2, "unit", "米")));
            info.put("specialOptions", specialOptions);
            when(orderItemMapper.selectList(any())).thenReturn(List.of(OrderItem.builder()
                    .id("item-1").tenantId(TENANT).orderId(ORDER_ID)
                    .productName("遮光成品X").quantity(BigDecimal.valueOf(2))
                    .width(new BigDecimal("2.5")).height(new BigDecimal("2.8"))
                    .curtainType(curtainType).craft("韩褶")
                    .processingInfo(info)
                    .build()));

            List<Map<String, Object>> payload = service.derivePositionPayload(ORDER_ID, TENANT);
            assertThat(payload).as("派生出的部位 payload 为空 ⇒ 判据会空跑").isNotEmpty();
            List<String> names = new ArrayList<>();
            for (Map<String, Object> position : payload) {
                for (Object raw : (List<?>) position.get("operations")) {
                    names.add(String.valueOf(((Map<?, ?>) raw).get("operation")));
                }
            }
            return names;
        }
    }

    /**
     * 「**引用的工序只有布帘变体**」的那批特殊选项（现取，不写死选项名）——
     * `{特殊选项名: 该选项引用的逻辑工序}`。
     *
     * <p>⚠️ **触发键是特殊选项名**（`加花边`），不是逻辑工序名（`花边`）——
     * 规则表的 `trigger_value` 是前者（实测：用逻辑名当选项名 ⇒ 规则不命中，判据静默空跑）。</p>
     */
    private Map<String, String> clothOnlyOptions() {
        Map<String, Map<String, Object>> catalog = queryForTest().operationsByName(TENANT);
        Map<String, String> out = new LinkedHashMap<>();
        for (JsonNode node : optionRoutings()) {
            String option = node.path("option_name").asText();
            String logical = logicalOf(node.path("operation_name").asText());
            if (queryForTest().variantNameOf(logical, "纱帘", catalog) == null) {
                out.put(option, logical);
            }
        }
        return out;
    }

    /**
     * 外层 mocks → 实例化侧真正用的同一个 {@link ProductionOperationQueryService}
     * （`@Nested` 内部类的静态方法拿不到外层实例字段，故行为腿自己在内部类里装配）。
     */
    private ProductionOperationQueryService queryForTest() {
        return new ProductionOperationQueryService(
                productionOperationMapper, productionRouteTemplateMapper, productionRouteRuleMapper,
                productionOperationPositionMapper, productionCraftMapper, productionRouteSignalMapper);
    }
}
