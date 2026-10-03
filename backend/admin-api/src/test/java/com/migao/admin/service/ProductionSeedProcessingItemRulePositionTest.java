// case_ids: PG-067
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
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
 * 🔴 **issue #6123**（#6114 的同类未固化面）：默认配置下，**纱帘单**只要带了加工项
 * {@code 花边 / 扣环 / 接高} 之一就整张加工单生成失败。报错逐字（本机实跑）：
 *
 * <pre>
 * 工艺路线「窗帘工序路线（默认）」（产品形态「纱帘」）引用的工序 [花边] 在工序库中不存在，无法实例化工序
 * </pre>
 *
 * <h2>归因（与 #6114 同因、另一条触发维）</h2>
 * <p>{@link ProductionSeedTemplateService} 的 {@code planRouteRules} 里，**加工项触发**分支
 * （{@code trigger_kind='processing_item'}）给规则写的 {@code position} 是 {@code null}
 * （= 不限部位），而它引用的三道逻辑工序在工序库里**只有布帘变体**（有 {@code 花边-布}、
 * 没有 {@code 花边-纱}）。触发键 = 订单行 {@code processingInfo.processingItems[].name}（**精确相等**）
 * ⇒ 规则在**纱帘单**上照样命中 ⇒ {@code variantNameOf(逻辑名, '纱帘', catalog)} 返回 {@code null}
 * ⇒ 该逻辑名进 {@code missing_operations} ⇒ {@code buildRoute} fail-closed。</p>
 *
 * <p>#6114 只给**特殊选项**维（{@code option}）补了部位限定 ⇒ 本单是同一事实的另一半。
 * 修法同样**只改种子**：开租播种给这 3 条规则写 {@code position='布帘'}
 * （口径来源 = 用户 2026-09-21 裁定「如果有一些工序只能布帘有或者纱帘有，可以在**适用条件**上设置」）。
 * ⛔ 不发明 {@code -纱} 变体（那是造新工序，会进工人计件口径）。</p>
 *
 * <h2>三条判据（缺一即假绿）</h2>
 * <ol>
 *   <li><b>内容腿</b>（{@link SeedCarriesClothPosition}）：真实跑一次
 *       {@link ProductionSeedTemplateService#applyTemplate}，捕获它落库的每一条加工项规则 ⇒
 *       {@code position} 逐条 = {@code '布帘'}；</li>
 *   <li><b>行为腿·两侧夹住</b>（{@link BothForms}）：把**真实播种产出的规则**喂给
 *       {@link ProcessingOrderService#derivePositionPayload}（真实实例化路径 + 仓内既有工序库夹具）
 *       —— ① 纱帘单 + 这些加工项 ⇒ 能派工、且不出现布帘变体；② 同一配置的布帘单 ⇒ 照旧插布帘变体；</li>
 *   <li><b>类级判据</b>（{@link EverySeedRuleResolvesInItsApplicableForm}）：**种子来源的每条规则**
 *       的 {@code (operation, position)} 在其**适用形态**下必须能解析出变体 —— 同时罩住
 *       {@code option} 与 {@code processing_item} **两条触发维**（#6114 只罩了前者）。</li>
 * </ol>
 *
 * <p><b>红证</b>（把 {@code ProductionSeedTemplateService.PROCESSING_ITEM_POSITION} 改回 {@code null}
 * ⇒ 判据 1/2/3 同时红）：见 PR body 的红证表。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("开租种子：#6123 加工项规则必须带部位限定（纱帘单不再整单 fail-closed）")
class ProductionSeedProcessingItemRulePositionTest {

    private static final Long TENANT = 42L;
    private static final String ORDER_ID = "order-001";

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

    /** 实例化侧真正用的同一个 {@link ProductionOperationQueryService}（与生产同源的一份装配）。 */
    private ProductionOperationQueryService queryForTest() {
        return new ProductionOperationQueryService(
                productionOperationMapper, productionRouteTemplateMapper, productionRouteRuleMapper,
                productionOperationPositionMapper, productionCraftMapper, productionRouteSignalMapper);
    }

    /**
     * 加工项触发的**触发值**（= 规则表里 {@code trigger_kind='processing_item'} 的 {@code trigger_value}
     * 全集，**现取不写死**）—— 播种里少了哪一条都会让下面的行为腿覆盖面缩水。
     */
    private List<String> seededProcessingItemTriggers() {
        return seededRules.stream()
                .filter(r -> "processing_item".equals(r.getTriggerKind()))
                .map(ProductionRouteRule::getTriggerValue).distinct().toList();
    }

    /** 工序变体名 → 逻辑名（`花边-布` → `花边`；无 `-布` / `-纱` 后缀 ⇒ 原名）。 */
    private static String logicalOf(String variant) {
        if (variant.endsWith("-布") || variant.endsWith("-纱")) {
            return variant.substring(0, variant.length() - 2);
        }
        return variant;
    }

    // ══════════════════════════ 内容腿 ══════════════════════════

    @Nested
    @DisplayName("内容腿：新租户会应用的那块种子（开租播种）")
    class SeedCarriesClothPosition {

        @Test
        @DisplayName("3 条加工项规则，播种后 position 逐条 = '布帘'")
        void processingItemRulesCarryClothPosition() {
            List<ProductionRouteRule> rows = seededRules.stream()
                    .filter(r -> "processing_item".equals(r.getTriggerKind()))
                    .toList();
            assertThat(rows).as("""
                    开租播种一条 `processing_item` 规则都没有 ⇒ 判据会空跑
                    （或归因变了：加工项触发这条维已退场，则 issue #4577 的功能也没了）""").isNotEmpty();

            List<String> wrong = rows.stream()
                    .filter(r -> !"布帘".equals(r.getPosition()))
                    .map(r -> r.getTriggerValue() + " → position=" + r.getPosition() + "（期望 布帘）")
                    .toList();
            assertThat(wrong).as("""
                    开租种子的加工项规则没带 `position='布帘'` ⇒ 这批规则会在**纱帘单**上命中，
                    而它们引用的工序只有布帘变体 ⇒ `variantNameOf(逻辑名, '纱帘', catalog)` 返回 null
                    ⇒ 整张加工单 fail-closed（issue #6123 的原始报错）。""").isEmpty();
        }

        @Test
        @DisplayName("部位限定值在闭词表内（不是随手一个字符串）")
        void positionValueIsInsideTheClosedVocabulary() {
            List<String> outside = seededRules.stream()
                    .filter(r -> "processing_item".equals(r.getTriggerKind()))
                    .map(ProductionRouteRule::getPosition).distinct()
                    .filter(p -> p == null
                            || !ProductionOperationQueryService.POSITION_LIMIT_VOCABULARY.contains(p))
                    .map(String::valueOf).toList();
            assertThat(outside).as("规则级部位限定必须是闭词表里的值（`null` = 不限部位**不在**本判据射程内 ——"
                    + "它由上面的内容腿单独钉住），否则这条规则对**任何**实例化部位都不生效"
                    + "（规则已落库但永不生效的黑洞）").isEmpty();
        }
    }

    // ══════════════════════════ 行为腿（两侧夹住）══════════════════════════

    @Nested
    @DisplayName("行为腿：真实播种规则 + 真实实例化路径（两侧夹住）")
    class BothForms {

        @Test
        @DisplayName("① 纱帘单 + 全部加工项 ⇒ 能派工，且不出现布帘变体")
        void sheerOrderWithProcessingItemsInstantiatesWithoutClothVariants() {
            List<String> triggers = seededProcessingItemTriggers();
            assertThat(triggers).as("播种里没有任何 `processing_item` 触发值 ⇒ 判据会空跑").isNotEmpty();

            List<String> operations = derive("纱帘", List.of(), triggers);
            assertThat(operations).as("纱帘单没解析出任何工序 ⇒ 前置不成立，判据会空跑").isNotEmpty();

            List<String> leaked = operations.stream()
                    .map(ProductionSeedProcessingItemRulePositionTest::logicalOf)
                    .filter(triggers::contains).distinct().toList();
            assertThat(leaked).as("""
                    纱帘单里出现了只有布帘变体的加工项工序 %s ⇒ 这批规则在纱帘单上命中了
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
            List<String> triggers = seededProcessingItemTriggers();
            assertThat(triggers).as("播种里没有任何 `processing_item` 触发值 ⇒ 判据会空跑").isNotEmpty();

            List<String> operations = derive("布帘", List.of(), triggers);
            List<String> missing = triggers.stream()
                    .filter(logical -> operations.stream()
                            .filter(name -> logical.equals(ProductionSeedProcessingItemRulePositionTest.logicalOf(name)))
                            .findAny().isEmpty())
                    .toList();
            assertThat(missing).as("""
                    布帘单少了这些加工项逻辑工序 %s ⇒ 部位限定写错（写成别的值 / 把整条规则滤掉）
                    = 车间漏做工序 + 计件漏算（比卡单更坏）""".formatted(missing)).isEmpty();
            assertThat(operations).as("布帘单必须仍插 `花边-布`（#6123 的原始复现加工项）").contains("花边-布");
            assertThat(operations).as("布帘单不得出现纱帘变体").noneMatch(name -> name.endsWith("-纱"));
        }

        /** 用真实派生路径实例化一张订单，返回实例出的**工序名**序列（含变体名）。 */
        private List<String> derive(String curtainType, List<String> specialOptions,
                                    List<String> processingItemNames) {
            Map<String, Object> info = new LinkedHashMap<>();
            info.put("colorName", "米白");
            info.put("sellingMethod", "散剪");
            List<Map<String, Object>> items = new ArrayList<>();
            for (String name : processingItemNames) {
                items.add(Map.of("id", "p-" + name, "name", name,
                        "unitPrice", 3.0, "quantity", 2, "unit", "米"));
            }
            info.put("processingItems", items);
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

    // ══════════════════════════ 类级判据 ══════════════════════════

    /**
     * 🔴 **类级固化（本单重点）**：种子来源的**每一条规则**，其 {@code (operation, position)}
     * 组合必须能在其**适用形态**下解析出变体 —— 同时罩住 {@code option} 与 {@code processing_item}
     * **两条触发维**（#6114 只罩了前者）。
     *
     * <p>适用形态 = {@link ProductionOperationQueryService#BASELINE_POSITIONS 基线三部位}
     * （`布帘` / `纱帘` / `帘头`；{@code 布料}单不套用规则，见 {@code buildRoute} 的
     * {@code isFabricForm} 分支）**∩** 该规则自己的部位限定（{@code position} 非空 ⇒ 只限该部位）。</p>
     *
     * <p><b>为什么这条能罩住本缺陷</b>：{@code position=null} 的加工项规则 = 「在全部三个形态上都适用」
     * ⇒ 它在 {@code 纱帘} 上解析不出变体 ⇒ **当场红**。这正是「把 {@code position} 改回 {@code null}」
     * 的红证形态（缺陷不是「某条规则写错了」，而是「规则对某个**它能命中的**形态不可解析」）。</p>
     */
    @Nested
    @DisplayName("类级判据：种子规则的 (operation, position) 在其适用形态下必须解析出变体")
    class EverySeedRuleResolvesInItsApplicableForm {

        @Test
        @DisplayName("每条种子规则的 (operation, position) 在其适用形态下都解析得出变体（两条触发维一起罩）")
        void everySeedRuleResolvesInEveryApplicableForm() {
            Map<String, Map<String, Object>> catalog = queryForTest().operationsByName(TENANT);
            assertThat(catalog).as("""
                    工序库目录为空 ⇒ `variantNameOf` 对任何名字都返回 null ⇒ 本判据会对**所有**规则判红
                    （那是判据空转，不是缺陷）""").isNotEmpty();

            List<ProductionRouteRule> ruleRows = seededRules.stream()
                    .filter(r -> r.getOperation() != null && !r.getOperation().isEmpty())
                    .toList();
            assertThat(ruleRows).as("播种里没有带工序名的规则 ⇒ 本判据是空断言（会空跑）").isNotEmpty();

            List<String> unresolved = new ArrayList<>();
            for (ProductionRouteRule rule : ruleRows) {
                List<String> forms = ProductionOperationQueryService.BASELINE_POSITIONS.stream()
                        .filter(form -> rule.getPosition() == null || rule.getPosition().isEmpty()
                                || rule.getPosition().equals(form))
                        .toList();
                if (forms.isEmpty()) {
                    unresolved.add(rule.getTriggerKind() + "×" + rule.getTriggerValue()
                            + " → 规则限定的部位 `" + rule.getPosition() + "` 不在任何实例化形态里"
                            + "（规则已落库但永不生效 = 黑洞）");
                    continue;
                }
                for (String form : forms) {
                    if (queryForTest().variantNameOf(rule.getOperation(), form, catalog) == null) {
                        unresolved.add(rule.getTriggerKind() + "×" + rule.getTriggerValue()
                                + " → 工序 `" + rule.getOperation() + "` 在形态「" + form + "」解析不出变体"
                                + "（规则会在该形态命中 ⇒ 整单 fail-closed）");
                    }
                }
            }
            assertThat(unresolved).as("""
                    开租种子里存在「规则会在某个形态命中、却解析不出变体」的规则 ⇒ 该形态的加工单整张
                    fail-closed（issue #6114 / #6123 的同一形态）。修法是给规则补**规则级部位限定**
                    （`production_route_rules.position`），⛔ 不是发明 `-纱` 变体。""").isEmpty();
        }

        @Test
        @DisplayName("两条触发维都被本判据罩住（自证，防「只罩了 option」的假绿）")
        void bothTriggerDimensionsAreInScope() {
            List<String> kinds = seededRules.stream()
                    .filter(r -> r.getOperation() != null)
                    .map(ProductionRouteRule::getTriggerKind).distinct().toList();
            assertThat(kinds).as("""
                    种子里的触发维只有 %s —— 本类级判据必须同时罩住 `option`（#6114）与
                    `processing_item`（#6123）两条触发维；少一条 ⇒ 缺口还在（假绿）""".formatted(kinds))
                    .contains("option", "processing_item");
        }
    }
}
