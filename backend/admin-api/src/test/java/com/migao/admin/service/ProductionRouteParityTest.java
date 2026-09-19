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
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.when;

/**
 * **实例化逐字一致**（P2b 的承重判据，issue #4459 验收判据 1）。
 *
 * <h2>判据</h2>
 * 9 个 {@code (部位, 工艺)} 组合的工序实例序列，与**旧结构**（9 条展开快照，
 * 真值源 {@code routing.py::ROUTINGS}）**逐字相同** —— 名称、顺序。
 *
 * <h2>为什么必须有它（形态 = 「切了消费路径，但展开语义漂了」）</h2>
 * P2b 把「怎么展开路线」从「读展开快照」换成「主线 + 规则 + 部位适用性」——
 * 这是**第二份实现**（Python 真值源是第一份）。判据 2 要求它与
 * {@code routing.py::build_route_v2} 逐字一致，而「逐字」只能靠**冻结期望**判：
 * 拿生产代码的输出与生产代码自己比是自证（永远绿）。
 *
 * <p>本文件喂的是**规范种子**（84 行部位价目 + 26 条规则 + 9 道主线 + 35 道工序库行，
 * 全部与 V71/V72 迁移逐行同值），断言的是**旧结构 9 条路线的冻结序列** ——
 * 任一环节漂移（规则 priority 错序 / 锚点归一漏了 / 适用性过滤错 / 变体名解析错）都变红。</p>
 *
 * <h2>红证（注入式，逐条见 PR body）</h2>
 * ① 把规则按声明序而非 {@code priority} 升序应用 ⇒ 布帘×韩褶 的「上车布」落到末尾 ⇒ 红；
 * ② 去掉「帘头回落 {@code -布} 变体」⇒ 帘头×平幔 的 精裁/三边/定型 解析不到 ⇒ 红；
 * ③ 漏掉部位适用性过滤 ⇒ 纱帘×韩褶 多出「熨烫/定型/复烫/车被」⇒ 红。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("P2b 实例化逐字一致：9 个 (部位,工艺) 组合 = 旧结构 9 条展开路线")
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

        // ── 规范种子（与 V71/V72 迁移逐行同值）──
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

    @Test
    @DisplayName("9/9 逐字一致：每个 (部位,工艺) 的实例序列 = 旧结构展开快照（名称 + 顺序）")
    void allNineCombinationsRebuildTheLegacyRoutesVerbatim() {
        assertThat(RoutingModelFixture.LEGACY_ROUTINGS.length)
                .as("真值源有 9 个 (部位,工艺) 组合").isEqualTo(9);

        List<String> failures = new ArrayList<>();
        for (String[] expected : RoutingModelFixture.LEGACY_ROUTINGS) {
            String position = expected[0];
            String craft = expected[1];
            List<String> frozen = List.of(expected[2].split(","));

            List<String> actual = instantiate(position, craft);
            if (!frozen.equals(actual)) {
                failures.add(position + "×" + craft + "\n  期望: " + frozen + "\n  实际: " + actual);
            }
        }
        assertThat(failures)
                .as("实例化必须与旧结构**逐字一致**（任一漂移 = 车间按错顺序干 + 计件按错工序算）")
                .isEmpty();
    }

    /** 用显式 (部位, 工艺) 的订单跑一次派生，返回实例的工序名序列。 */
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

    @Test
    @DisplayName("注入法自证：把一条规则的 priority 调到最后 ⇒ 序列漂移（判据不是空断言）")
    void reorderingRulesByPriorityIsWhatKeepsTheSequenceStable() {
        // 「韩褶 insert 上车布 after 韩褶」的 priority 从 20 提到 999 ⇒ 锚点「韩褶」此时已存在
        // ⇒ 结果**相同**（说明 priority 的语义是「锚点可用性」，不是「随便排」）；
        // 反过来把「韩褶 insert 韩褶 after 三边」（10）提到 20 之后 ⇒ 锚点「三边」仍存在 ⇒ 也相同。
        // ⇒ 真正可判的是**锚点不存在时**：把 20 号规则降到 10 之前，「韩褶」还不存在 ⇒ 上车布追加末尾。
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
        List<String> frozen = List.of(RoutingModelFixture.LEGACY_ROUTINGS[0][2].split(","));

        assertThat(actual)
                .as("priority 提前 ⇒ 锚点「韩褶」尚未插入 ⇒ 上车布追加末尾 ⇒ 与冻结期望不同（判据有判别力）")
                .isNotEqualTo(frozen);
        assertThat(actual.get(actual.size() - 1)).as("上车布被追加到末尾").isEqualTo("上车布-布");
    }

    @Test
    @DisplayName("注入法自证：漏掉部位适用性过滤 ⇒ 纱帘路线多出布帘专属工序（判据有判别力）")
    void skippingApplicabilityFilterWouldLeakClothOnlyOperationsIntoSheerRoute() {
        List<ProductionOperationPosition> allApplicable = new ArrayList<>();
        for (ProductionOperationPosition row : RoutingModelFixture.canonicalPositions84(TENANT)) {
            allApplicable.add(ProductionOperationPosition.builder()
                    .id(row.getId()).tenantId(row.getTenantId())
                    .logicalName(row.getLogicalName()).position(row.getPosition())
                    .unitPrice(row.getUnitPrice())
                    .applicable(true)          // 注入：全部「适用」
                    .status(row.getStatus()).deleted(row.getDeleted())
                    .build());
        }
        when(productionOperationPositionMapper.selectList(any())).thenReturn(allApplicable);

        // 不过滤适用性 ⇒ 纱帘路线带上布帘专属的 熨烫/定型/复烫/车被；而这些工序在纱帘**没有变体**
        // ⇒ 解析不到 ⇒ fail-closed（实例化直接中止）。两条路径都说明「适用性过滤是承重的」：
        // 少了它，要么多出别人的工序、要么整条单生成不了 —— 都不是旧结构的行为。
        assertThatThrownBy(() -> instantiate("纱帘", "韩褶"))
                .isInstanceOf(com.migao.admin.exception.BusinessException.class)
                .hasMessageContaining("无法实例化工序");
    }

    /**
     * **回归锁（issue #4650 阶段 1）**：「条件工序规则」独立表从商家界面移除，条件改为挂在**工序**上。
     *
     * <h2>判据</h2>
     * 同一套规则配置下，订单实例化产出的工序序列**逐项不变** —— 与
     * {@link RoutingModelFixture#LEGACY_ROUTINGS}（真值源 {@code routing.py::ROUTINGS} 的冻结快照）
     * 逐字相同；且**换了配置载体也不许漂**：这里喂的是**更全**的规范种子
     * （{@code rulesWithProcessingItems} = 26 条 craft/option + 系数档 + 3 条加工项触发规则），
     * 而 {@link #allNineCombinationsRebuildTheLegacyRoutesVerbatim()} 喂的是 {@code rulesWithFactors}。
     *
     * <h2>为什么阶段 1 必须有它</h2>
     * 阶段 1 改的只是**呈现与编辑落点**（独立规则表 ⇒ 工序抽屉的「适用条件」），
     * 写面（{@code POST/DELETE /route-rules}）、读面、实例化**一律不动**。
     * 这条锁把「界面搬了、实例化语义却跟着漂了」钉死：规则 priority 序 / 锚点归一 /
     * 部位适用性过滤 / 加工项触发——任一处被动过，序列就变红。
     *
     * <h2>红证（注入式自证，判据不是空断言）</h2>
     * 把「上车布」那条规则的 priority 提到锚点「韩褶」之前 ⇒ 锚点尚未存在 ⇒ 上车布追加末尾
     * ⇒ 与冻结期望不同（同 {@link #reorderingRulesByPriorityIsWhatKeepsTheSequenceStable()} 的注入形态）。
     */
    @Test
    @DisplayName("回归锁（#4650 阶段 1）：同一套规则配置下，实例化产出的工序序列逐项不变")
    void instantiationSequenceIsUnchangedForTheCanonicalRuleConfig() {
        // ① 更全的规范种子（含加工项触发规则；订单没带那些加工项 ⇒ 它们不命中）
        when(productionRouteRuleMapper.selectList(any())).thenReturn(
                RoutingModelFixture.rulesWithProcessingItems(TENANT));

        List<String> failures = new ArrayList<>();
        for (String[] expected : RoutingModelFixture.LEGACY_ROUTINGS) {
            List<String> frozen = List.of(expected[2].split(","));
            List<String> actual = instantiate(expected[0], expected[1]);
            if (!frozen.equals(actual)) {
                failures.add(expected[0] + "×" + expected[1] + "\n  期望: " + frozen + "\n  实际: " + actual);
            }
        }
        assertThat(failures)
                .as("移除独立规则表**不得**改动实例化语义（界面搬了、工序序列漂了 = 车间按错顺序干）")
                .isEmpty();

        // ② 注入式自证：同一条规则挪一下 priority（锚点「韩褶」尚未插入）⇒ 序列必须变
        //    （不变 ⇒ 上面那条是空断言：拿生产代码的输出与生产代码自己比）
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
                .isNotEqualTo(List.of(RoutingModelFixture.LEGACY_ROUTINGS[0][2].split(",")));
    }
}
