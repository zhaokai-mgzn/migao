// case_ids: PG-018, PG-035
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
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
import com.migao.admin.mapper.ProductionRouteRuleMapper;
import com.migao.admin.mapper.ProductionRouteSignalMapper;
import com.migao.admin.mapper.ProductionRouteTemplateMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
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
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.when;

/**
 * **实例化逐字一致**（P2b 的承重判据，issue #4459 验收判据 1）—— **去部位化后的新基线**。
 *
 * <h2>🔴 本类在 issue #4937 换过基线（照实登记）</h2>
 * <p><b>旧基线随用户 2026-09-21 裁定退休</b>：母单 #4936 用户原话「这个必须要改，我们移除了
 * 部位的设计，<b>不计成本的改</b>」⇒ issue #4937 把「部位」从取价、取路、筛选、配置里全部移除。
 * 三条旧判据因此退休并换基线：</p>
 * <table border="1">
 *   <caption>退休 → 换基线</caption>
 *   <tr><th>旧</th><th>新</th></tr>
 *   <tr>
 *     <td>{@code allNineCombinationsRebuildTheLegacyRoutesVerbatim} + {@code
 *         instantiationSequenceIsUnchangedForTheCanonicalRuleConfig}：与**旧 9 条展开路线**
 *         （{@code routing.py::ROUTINGS}）逐字相等</td>
 *     <td>{@link #allNineCombinationsMatchTheDepositionedSnapshot()}：与<b>去部位化后重新冻结</b>
 *         的 9 条组合序列（{@link RoutingModelFixture#DEPOSITIONED_ROUTINGS}）逐字相等</td>
 *   </tr>
 *   <tr>
 *     <td>{@code skippingApplicabilityFilterWouldLeakClothOnlyOperationsIntoSheerRoute}：
 *         「别去掉 applicable 过滤」的注入式守卫</td>
 *     <td>{@link #sheerAndClothOrdersHaveTheSameOperationSet()}：纱帘单与布帘单的
 *         <b>工序集完全一致</b>（只因变体名不同）—— 这正是去掉过滤后的新语义</td>
 *   </tr>
 * </table>
 *
 * <h2>为什么「逐字冻结」仍然是必须的</h2>
 * 拿生产代码的输出与生产代码自己比是自证（永远绿）。本类喂的是**规范种子**
 * （价目矩阵 + 26 条规则 + 主线 + 工序库行，全部与 V71/V72/V79 迁移同源），
 * 断言的是**冻结序列** ⇒ 任一环节漂移（规则 priority 错序 / 锚点归一漏了 / 变体名解析错 /
 * 规则里又冒出 `position` 筛选）都变红。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("P2b 实例化逐字一致（去部位化新基线）：9 个 (帘种,工艺) 组合 = 冻结快照")
class ProductionRouteParityTest {

    private static final Long TENANT = 1L;

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
    private ProductionOperationMapper productionOperationMapper;
    @Mock
    private ProductionRouteTemplateMapper productionRouteTemplateMapper;
    @Mock
    private ProductionRouteRuleMapper productionRouteRuleMapper;
    @Mock
    private ProductionOperationPositionMapper productionOperationPositionMapper;
    @Mock
    private ProductionCraftMapper productionCraftMapper;
    @Mock
    private ProductionRouteSignalMapper productionRouteSignalMapper;

    private ProcessingOrderService service;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);

        // ── 规范种子（与 V71/V72/V79 迁移逐行同值）──
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                RoutingModelFixture.defaultTemplateAllPositions(TENANT)));
        when(productionRouteRuleMapper.selectList(any())).thenReturn(
                RoutingModelFixture.rulesWithFactors(TENANT));
        when(productionOperationPositionMapper.selectList(any())).thenReturn(
                RoutingModelFixture.canonicalPositions84(TENANT));
        when(productionCraftMapper.selectList(any())).thenReturn(List.of(
                RoutingModelFixture.defaultCraft(TENANT, "韩褶")));
        when(productionOperationMapper.selectList(any())).thenReturn(
                RoutingModelFixture.operationEntities(TENANT));

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
        Order order = Order.builder().id("order-001").tenantId(TENANT)
                .orderNo("ORD-20260919-0001").status("confirmed")
                .customerName("张三").customerPhone("13800138000").build();
        when(orderMapper.selectById("order-001")).thenReturn(order);
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    /**
     * 🔴 **新基线**（issue #4937）：9 个 `(帘种, 工艺)` 组合的实例序列 = **去部位化后的冻结快照**。
     *
     * <p>⚠️ **旧基线退休**：本测试原为
     * {@code allNineCombinationsRebuildTheLegacyRoutesVerbatim}，断言的是「与**旧 9 条展开路线**
     * （{@code routing.py::ROUTINGS}）逐字相等」。用户 2026-09-21 裁定（母单 #4936）
     * 「我们移除了部位的设计，不计成本的改」⇒ 该判据的**前提**（旧结构是正确性的标尺）
     * 不再成立 ⇒ 换成去部位化后的新模型冻结快照。</p>
     */
    @Test
    @DisplayName("新基线（#4937）：9/9 逐字一致 = 去部位化后的冻结快照")
    void allNineCombinationsMatchTheDepositionedSnapshot() {
        assertThat(RoutingModelFixture.DEPOSITIONED_ROUTINGS.length)
                .as("新基线有 9 个 (帘种, 工艺) 组合").isEqualTo(9);

        List<String> failures = new ArrayList<>();
        for (String[] expected : RoutingModelFixture.DEPOSITIONED_ROUTINGS) {
            String position = expected[0];
            String craft = expected[1];
            List<String> frozen = List.of(expected[2].split(","));

            List<String> actual = instantiate(position, craft);
            if (!frozen.equals(actual)) {
                failures.add(position + "×" + craft + "\n  期望: " + frozen + "\n  实际: " + actual);
            }
        }
        assertThat(failures)
                .as("实例化必须与新基线**逐字一致**（任一漂移 = 车间按错顺序干 + 计件按错工序算）")
                .isEmpty();
    }

    /** 用显式 (帘种, 工艺) 的订单跑一次派生，返回实例的工序名序列。 */
    private List<String> instantiate(String position, String craft) {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("colorName", "米白");
        info.put("sellingMethod", "散剪");
        info.put("processingItems", List.of(Map.of("id", "p-1", "name", "工序甲",
                "unitPrice", 3.0, "quantity", 2, "unit", "米")));
        OrderItem item = OrderItem.builder()
                .id("item-1").tenantId(TENANT).orderId("order-001")
                .productName("遮光成品X").quantity(BigDecimal.valueOf(2))
                .width(new BigDecimal("2.5")).height(new BigDecimal("2.8"))
                .curtainType(position).craft(craft)
                .processingInfo(info)
                .build();
        when(orderItemMapper.selectList(any())).thenReturn(List.of(item));

        List<Map<String, Object>> payload = service.derivePositionPayload("order-001", TENANT);
        List<String> names = new ArrayList<>();
        for (Map<String, Object> p : payload) {
            for (Object raw : (List<?>) p.get("operations")) {
                names.add(String.valueOf(((Map<?, ?>) raw).get("operation")));
            }
        }
        return names;
    }

    /**
     * 🔴 **本单的核心判据**（issue #4962，取代 {@code sheerAndClothOrdersHaveTheSameOperationSet}）。
     *
     * <p><b>旧判据</b>（#4937 基线）：「纱帘单与布帘单的工序集**完全一致**」—— 它成立的**唯一理由**是
     * 「规则级 `position` 也被退场了」。用户 2026-09-21 追问后的裁定
     * 「**如果有一些工序只能布帘有或者纱帘有，可以在适用条件上设置**」把该维**加回**
     * ⇒ 旧判据的前提消失，**改判**（不是删除、不是放宽）。</p>
     *
     * <p><b>新判据</b>：分叉面**只有**带 `position` 的规则 —— 26 条种子行里恰好一条
     * （`韩褶 → insert 上车布`，`position='布帘'`）：
     * <ul>
     *   <li>布帘×韩褶 ⇒ <b>有</b> `上车布-布`（限定的部位 = 当前部位）；</li>
     *   <li>纱帘×韩褶 ⇒ <b>没有</b> `上车布-纱`（限定的部位 ≠ 当前部位）；</li>
     *   <li>反向护栏：`四爪钩 → insert 上车布`（`position` 为空 = **不限部位**）⇒ 两个帘种**都**有
     *       —— 判据不得把「空值」也一起筛掉（那会静默少工序）。</li>
     * </ul>
     * <b>守卫强度只升不降</b>：旧判据只覆盖 `韩褶/打孔/四爪钩/穿杆` 四个工艺的「相等」，
     * 新判据额外覆盖「**必须不等**的那一格」（部位限定真的在筛）与「空值不筛」的反向护栏。</p>
     */
    @Test
    @DisplayName("新判据（#4962）：带 position 的规则只在**逐字匹配**的部位生效；空 position = 不限")
    void positionLimitedRuleFiresOnlyOnItsOwnPosition() {
        // ① 限定的部位 = 布帘 ⇒ 布帘×韩褶 必须有「上车布」
        assertThat(instantiate("布帘", "韩褶"))
                .as("布帘×韩褶 少了部位限定规则插入的 `上车布-布` ⇒ 规则对**该生效的部位**没生效")
                .contains("上车布-布");
        // ② 部位限定 ≠ 纱帘 ⇒ 纱帘×韩褶 **不得**有「上车布」
        //    （改前实测就是这一形态：筛选不存在 ⇒ 规则对所有部位都生效）
        assertThat(instantiate("纱帘", "韩褶"))
                .as("纱帘×韩褶 带上了 `上车布-纱` ⇒ 部位限定没生效（筛选不存在 ⇒ 规则对所有部位都生效）")
                .doesNotContain("上车布-纱");
        // ③ 反向护栏：`position` 为空 = 不限部位 ⇒ 那条同名规则（四爪钩 → 上车布）仍然两处都生效
        for (String curtainType : List.of("布帘", "纱帘")) {
            assertThat(instantiate(curtainType, "四爪钩"))
                    .as(curtainType + "×四爪钩 少了 `上车布`（那条规则的 position 为空 = 不限部位）"
                            + " ⇒ 判据把空值也一起筛掉了")
                    .anyMatch(name -> name.startsWith("上车布"));
        }
        // ④ 分叉面**只有**部位限定那一条：其余工艺在两个帘种上逻辑序列逐字相同（#4937 不回退）
        for (String craft : List.of("打孔", "穿杆")) {
            List<String> clothLogical = instantiate("布帘", craft).stream()
                    .map(RoutingModelFixture::logicalName).toList();
            List<String> sheerLogical = instantiate("纱帘", craft).stream()
                    .map(RoutingModelFixture::logicalName).toList();
            assertThat(sheerLogical)
                    .as("工艺 `" + craft + "` 在不同帘种上分叉 ⇒ 部位在**别处**也参与了取路：\n"
                            + "  布帘 = " + clothLogical + "\n  纱帘 = " + sheerLogical)
                    .isEqualTo(clothLogical);
        }
    }

    /**
     * **注入法自证**（本判据的红证）：把那条规则的 `position` 抹成 `null`（= 不限部位）
     * ⇒ 纱帘×韩褶 **立刻**多出 `上车布-纱`（证明上面那条断言真的在测「部位限定」，不是恒真）。
     */
    @Test
    @DisplayName("注入法自证（#4962）：抹掉 position ⇒ 纱帘×韩褶 多出 上车布（判据有判别力）")
    void droppingThePositionLimitLeaksClothOnlyOperationsIntoSheerRoute() {
        List<ProductionRouteRule> dropped = new ArrayList<>();
        for (ProductionRouteRule rule : RoutingModelFixture.rulesWithFactors(TENANT)) {
            dropped.add(ProductionRouteRule.builder()
                    .id(rule.getId()).tenantId(rule.getTenantId())
                    .triggerKind(rule.getTriggerKind()).triggerValue(rule.getTriggerValue())
                    .position(null)   // 注入：部位限定全体退场（= #4937 之后的形态）
                    .action(rule.getAction())
                    .operation(rule.getOperation()).afterOperation(rule.getAfterOperation())
                    .priority(rule.getPriority()).factor(rule.getFactor())
                    .status(rule.getStatus()).deleted(rule.getDeleted())
                    .build());
        }
        when(productionRouteRuleMapper.selectList(any())).thenReturn(dropped);

        List<String> leaked = instantiate("纱帘", "韩褶");
        assertThat(leaked)
                .as("抹掉 `position` 后纱帘×韩褶 仍没有 `上车布-纱` ⇒ 注入没生效，"
                        + "`positionLimitedRuleFiresOnlyOnItsOwnPosition` 可能是空断言")
                .contains("上车布-纱");
        assertThat(leaked)
                .as("注入后与冻结快照相同 ⇒ 冻结快照本身没把「少一道」判出来")
                .isNotEqualTo(List.of(RoutingModelFixture.DEPOSITIONED_ROUTINGS[4][2].split(",")));
    }

    /**
     * **注入法自证**：把一条规则的 priority 调到最后 ⇒ 序列漂移（判据不是空断言）。
     */
    @Test
    @DisplayName("注入法自证：priority 提前 ⇒ 锚点尚不存在 ⇒ 上车布追加末尾（判据有判别力）")
    void reorderingRulesByPriorityIsWhatKeepsTheSequenceStable() {
        List<ProductionRouteRule> rules = new ArrayList<>();
        for (ProductionRouteRule rule : RoutingModelFixture.rulesWithFactors(TENANT)) {
            ProductionRouteRule copy = ProductionRouteRule.builder()
                    .id(rule.getId()).tenantId(rule.getTenantId())
                    .triggerKind(rule.getTriggerKind()).triggerValue(rule.getTriggerValue())
                    .position(rule.getPosition()).action(rule.getAction())
                    .operation(rule.getOperation()).afterOperation(rule.getAfterOperation())
                    .priority("上车布".equals(rule.getOperation()) ? 5 : rule.getPriority())
                    .factor(rule.getFactor()).status(rule.getStatus()).deleted(rule.getDeleted())
                    .build();
            rules.add(copy);
        }
        when(productionRouteRuleMapper.selectList(any())).thenReturn(rules);

        List<String> actual = instantiate("布帘", "韩褶");
        List<String> frozen = List.of(RoutingModelFixture.DEPOSITIONED_ROUTINGS[0][2].split(","));

        assertThat(actual)
                .as("priority 提前 ⇒ 锚点「韩褶」尚未插入 ⇒ 上车布追加末尾 ⇒ 与冻结期望不同（判据有判别力）")
                .isNotEqualTo(frozen);
        assertThat(actual.get(actual.size() - 1)).as("上车布被追加到末尾").isEqualTo("上车布-布");
    }

    /**
     * **回归锁（issue #4650 阶段 1）**：同一套规则配置下，实例化产出的工序序列**逐项不变**。
     *
     * <p>这里喂的是**更全**的规范种子（26 条 craft/option + 系数档 + 3 条加工项触发规则），
     * 而 {@link #allNineCombinationsMatchTheDepositionedSnapshot()} 喂的是 {@code rulesWithFactors}。</p>
     */
    @Test
    @DisplayName("回归锁（#4650 阶段 1）：更全的规则配置下，序列仍等于冻结快照")
    void instantiationSequenceIsUnchangedForTheCanonicalRuleConfig() {
        when(productionRouteRuleMapper.selectList(any())).thenReturn(
                RoutingModelFixture.rulesWithProcessingItems(TENANT));

        List<String> failures = new ArrayList<>();
        for (String[] expected : RoutingModelFixture.DEPOSITIONED_ROUTINGS) {
            List<String> frozen = List.of(expected[2].split(","));
            List<String> actual = instantiate(expected[0], expected[1]);
            if (!frozen.equals(actual)) {
                failures.add(expected[0] + "×" + expected[1] + "\n  期望: " + frozen + "\n  实际: " + actual);
            }
        }
        assertThat(failures)
                .as("规则载体的扩增**不得**改动实例化语义（界面搬了、工序序列漂了 = 车间按错顺序干）")
                .isEmpty();

        // ② 注入式自证：同一条规则挪一下 priority（锚点「韩褶」尚未插入）⇒ 序列必须变
        List<ProductionRouteRule> reordered = new ArrayList<>();
        for (ProductionRouteRule rule : RoutingModelFixture.rulesWithProcessingItems(TENANT)) {
            reordered.add(ProductionRouteRule.builder()
                    .id(rule.getId()).tenantId(rule.getTenantId())
                    .triggerKind(rule.getTriggerKind()).triggerValue(rule.getTriggerValue())
                    .position(rule.getPosition()).action(rule.getAction())
                    .operation(rule.getOperation()).afterOperation(rule.getAfterOperation())
                    .priority("上车布".equals(rule.getOperation()) ? 5 : rule.getPriority())
                    .factor(rule.getFactor()).status(rule.getStatus()).deleted(rule.getDeleted())
                    .build());
        }
        when(productionRouteRuleMapper.selectList(any())).thenReturn(reordered);
        assertThat(instantiate("布帘", "韩褶"))
                .as("priority 注入 ⇒ 序列漂移（判据有判别力）")
                .isNotEqualTo(List.of(RoutingModelFixture.DEPOSITIONED_ROUTINGS[0][2].split(",")));
    }

    /**
     * 🔴 **本单的核心判据之二**（issue #4962，取代 {@code rulePositionNoLongerFiltersAnything}）。
     *
     * <p><b>旧判据</b>（#4937 基线）：给每条规则注入 `position='帘头'` ⇒ 序列**一字不变**
     * （「筛选已退场」）。用户 2026-09-21 追问后的裁定把该维**加回** ⇒ 旧判据的前提消失，**改判**。</p>
     *
     * <p><b>新判据</b>：注入 `position='帘头'` ⇒ 布帘×韩褶 的序列**当场变**（`上车布` 被筛掉）
     * —— 这正是「规则级 `position` 重新承重」的可执行定义；且与**该部位自己**的序列一致
     * （帘头×韩褶 也带 `position='帘头'` 的规则）。</p>
     */
    @Test
    @DisplayName("新判据（#4962）：规则的 position 重新承重（注入 '帘头' ⇒ 布帘序列当场变）")
    void rulePositionFiltersAgain() {
        List<ProductionRouteRule> withPosition = new ArrayList<>();
        for (ProductionRouteRule rule : RoutingModelFixture.rulesWithFactors(TENANT)) {
            withPosition.add(ProductionRouteRule.builder()
                    .id(rule.getId()).tenantId(rule.getTenantId())
                    .triggerKind(rule.getTriggerKind()).triggerValue(rule.getTriggerValue())
                    // 注入：把**所有**规则的 position 改成 `帘头`（含原本 null 的与原本 布帘 的那条）
                    .position("帘头").action(rule.getAction())
                    .operation(rule.getOperation()).afterOperation(rule.getAfterOperation())
                    .priority(rule.getPriority()).factor(rule.getFactor())
                    .status(rule.getStatus()).deleted(rule.getDeleted())
                    .build());
        }
        when(productionRouteRuleMapper.selectList(any())).thenReturn(withPosition);

        List<String> cloth = instantiate("布帘", "韩褶");
        List<String> frozen = List.of(RoutingModelFixture.DEPOSITIONED_ROUTINGS[0][2].split(","));
        assertThat(cloth)
                .as("全部改成 `position='帘头'` 后布帘序列没变 ⇒ 规则的 `position` **没有**在筛选"
                        + "（#4962 未落地）\n  实测 = " + cloth)
                .isNotEqualTo(frozen);
        assertThat(cloth)
                .as("布帘序列仍带 `上车布-布` ⇒ 部位限定没生效")
                .doesNotContain("上车布-布");
        assertThat(cloth.stream().map(RoutingModelFixture::logicalName).toList())
                .as("注入后布帘×韩褶 的序列应等于「无 上车布」的 10 道（部位不匹配 ⇒ 规则被筛掉）")
                .doesNotContain("上车布");
    }
}
