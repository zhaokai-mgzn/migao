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
     * 🔴 **新判据**（取代退休的 {@code skippingApplicabilityFilterWouldLeakClothOnlyOperationsIntoSheerRoute}）。
     *
     * <p><b>旧判据</b>：注入「全部格 applicable=true」⇒ 纱帘单会带上布帘专属工序 ⇒
     * 「别去掉 applicable 过滤」。用户已裁定去掉它 ⇒ 该判据的前提消失，**退休**。</p>
     *
     * <p><b>新判据</b>：纱帘单与布帘单的**工序集完全一致**（只因变体名不同：
     * {@code 熨烫-布} ↔ {@code 熨烫-纱}）—— 这正是「部位不再参与取路」的可执行定义。
     * <b>守卫强度只升不降</b>：旧判据只覆盖 1 个组合（纱帘×韩褶），新判据覆盖 **4 个工艺 × 2 帘种**。</p>
     */
    @Test
    @DisplayName("新判据（#4937）：纱帘单与布帘单的工序集完全一致（只因变体名不同）")
    void sheerAndClothOrdersHaveTheSameOperationSet() {
        for (String craft : List.of("韩褶", "打孔", "四爪钩", "穿杆")) {
            List<String> cloth = instantiate("布帘", craft);
            List<String> sheer = instantiate("纱帘", craft);

            assertThat(sheer)
                    .as("纱帘×" + craft + " 与 布帘×" + craft + " 的**道数**必须相同"
                            + "（部位不再参与取路 ⇒ 工序集一致）")
                    .hasSameSizeAs(cloth);
            // 把变体名归一到逻辑名后必须**逐字相同**（顺序也相同）
            List<String> clothLogical = cloth.stream().map(RoutingModelFixture::logicalName).toList();
            List<String> sheerLogical = sheer.stream().map(RoutingModelFixture::logicalName).toList();
            assertThat(sheerLogical)
                    .as("纱帘×" + craft + " 与 布帘×" + craft + " 的**逻辑工序序列**必须逐字相同：\n"
                            + "  布帘 = " + clothLogical + "\n  纱帘 = " + sheerLogical)
                    .isEqualTo(clothLogical);
            // 变体名必须**真的不同**（否则本判据退化成「同一条路线比两次」，是空断言）
            assertThat(sheer).as("纱帘与布帘的变体名不应完全相同（否则判据空跑）")
                    .isNotEqualTo(cloth);
        }
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
     * 🔴 **O2 红证**（issue #4937）：给规则注入一个 `position` 限定 ⇒ **不得**再影响序列。
     *
     * <p>规则级 `position` 已退场（`buildRoute` / `insertConditionalOperations` 的两处筛选
     * 整块删除）⇒ 给它任何值都不改变结果。这是「部位不再参与取路」在**规则维**上的可执行判据
     * （旧基线恰好相反：那时 `position` 是承重的筛选器）。</p>
     */
    @Test
    @DisplayName("O2 红证（#4937）：规则的 position 限定不再影响序列（筛选已退场）")
    void rulePositionNoLongerFiltersAnything() {
        List<ProductionRouteRule> withPosition = new ArrayList<>();
        for (ProductionRouteRule rule : RoutingModelFixture.rulesWithFactors(TENANT)) {
            withPosition.add(ProductionRouteRule.builder()
                    .id(rule.getId()).tenantId(rule.getTenantId())
                    .triggerKind(rule.getTriggerKind()).triggerValue(rule.getTriggerValue())
                    // 注入：把原本 position=null 的规则全改成 `帘头`（旧口径下这会让它们对布帘失效）
                    .position("帘头").action(rule.getAction())
                    .operation(rule.getOperation()).afterOperation(rule.getAfterOperation())
                    .priority(rule.getPriority()).factor(rule.getFactor())
                    .status(rule.getStatus()).deleted(rule.getDeleted())
                    .build());
        }
        when(productionRouteRuleMapper.selectList(any())).thenReturn(withPosition);

        List<String> actual = instantiate("布帘", "韩褶");
        List<String> frozen = List.of(RoutingModelFixture.DEPOSITIONED_ROUTINGS[0][2].split(","));
        assertThat(actual)
                .as("规则的 `position` 仍在筛选（改了它序列就变）⇒ O2 未完成："
                        + "部位还在参与取路\n  实测 = " + actual)
                .isEqualTo(frozen);
    }
}
