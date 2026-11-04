// case_ids: MC-189
package com.migao.admin.service;

import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.ProcessingItemQueryRequest;
import com.migao.admin.dto.ProcessingItemResponse;
import com.migao.admin.dto.RemnantViews;
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
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;

/**
 * {@link ConfigReadinessService} 的**事实口径**判据（issue #6579）。
 *
 * <p>每条判据都**会红**（红证写在用例注释里）：</p>
 * <ol>
 *   <li><b>工序与单价三个数</b>：{@code total} = 价目行（逻辑工序）+ 孤儿行；{@code unpriced} = 收敛行
 *       里 {@code unit_price} 为空的个数；{@code orphans} 按**工艺配置页**的四条口径算
 *       （无价目行引用 / 按逻辑名去重 / 价目表已出现的名字不算 / 空名不计）。
 *       红证：把 {@code orphans} 直接写 0、或改成「库里所有工序数」⇒ 断言当场红。</li>
 *   <li><b>跨码步骤整个省略</b>：不持 {@code processing:manage} ⇒ {@code remnant-sizes}
 *       **整个不在 {@code steps} 里**（既不是 0 也不是 forbidden 占位）。红证：改成返回
 *       {@code facts={configured:false}} ⇒ 断言红（那是「你没配」的谎报）。</li>
 *   <li><b>取不到 ≠ 0</b>：某一步取数抛错 ⇒ 该步仍在，但 {@code facts} 是**空对象**（前端落 unknown）。
 *       红证：把异常吞成 0 ⇒ 断言红（0 会被判成「没配置」）。</li>
 *   <li><b>每步给 {@code href}</b>：七步的 href 与前端主线逐值一致（此处钉住服务端侧的那一半）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("ConfigReadinessService 配置就绪度事实（issue #6579）")
class ConfigReadinessServiceTest {

    private static final Long TENANT = 1L;

    @Mock
    private ProductionRoutingReadService productionRoutingReadService;
    @Mock
    private ProductionOperationQueryService productionOperationQueryService;
    @Mock
    private ProcessingFeeQueryService processingFeeQueryService;
    @Mock
    private ProcessingItemService processingItemService;
    @Mock
    private CraftCalcConfigService craftCalcConfigService;
    @Mock
    private RemnantService remnantService;

    private ConfigReadinessService service;

    @BeforeEach
    void setUp() {
        service = new ConfigReadinessService(productionRoutingReadService, productionOperationQueryService,
                processingFeeQueryService, processingItemService, craftCalcConfigService, remnantService);
        // 默认：全部读面可用且取值确定（各用例按需覆写其中一面）
        when(productionRoutingReadService.operationPositions(TENANT)).thenReturn(positions());
        when(productionOperationQueryService.catalog(TENANT)).thenReturn(catalog());
        when(productionOperationQueryService.routings(TENANT)).thenReturn(routings());
        when(processingFeeQueryService.combinations(TENANT)).thenReturn(Map.of("total", 3));
        when(processingFeeQueryService.feeGaps(TENANT)).thenReturn(Map.of("unpriced_combination_total", 1));
        when(processingItemService.getProcessingItems(any(ProcessingItemQueryRequest.class), eq(TENANT)))
                .thenAnswer(invocation -> {
                    ProcessingItemQueryRequest query = invocation.getArgument(0);
                    long total = query.getStatus() == null ? 8L : 7L;
                    return PageResponse.of(total, 1L, 1L, List.<ProcessingItemResponse>of());
                });
        when(craftCalcConfigService.get(TENANT)).thenReturn(Map.of("source", "stored"));
        when(remnantService.specs(TENANT)).thenReturn(new RemnantViews.SpecsView(true,
                List.of(new RemnantViews.SpecLine("抱枕", new BigDecimal("0.60"), new BigDecimal("0.40"),
                        null, null, null)),
                null));
    }

    // ── 夹具：价目行 2 条（精裁 未定价 / 三边 已定价）+ 工序库 6 行（其中「花边」两行、一行空名）──

    private static List<Map<String, Object>> positions() {
        List<Map<String, Object>> rows = new ArrayList<>();
        rows.add(position("精裁", null, "10"));
        rows.add(position("三边", new BigDecimal("2.00"), "11"));
        return rows;
    }

    private static Map<String, Object> position(String operation, BigDecimal unitPrice, String variantId) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("operation", operation);
        row.put("unit_price", unitPrice);
        row.put("variant_operation_id", variantId);
        return row;
    }

    private static Map<String, Object> libraryOperation(Object id, String name) {
        Map<String, Object> op = new LinkedHashMap<>();
        op.put("id", id);
        op.put("name", name);
        return op;
    }

    private static Map<String, Object> catalog() {
        List<Map<String, Object>> operations = new ArrayList<>();
        // 被价目行引用 ⇒ 不是孤儿
        operations.add(libraryOperation("10", "精裁"));
        operations.add(libraryOperation("11", "三边"));
        // 未被引用，但它的逻辑名在价目表里已出现（三边由另一变体行定价）⇒ **不是**孤儿
        operations.add(libraryOperation("12", "三边"));
        // 未被引用、名字也没在价目表出现 ⇒ **孤儿**（两行同一逻辑名 ⇒ 只算 1 个）
        operations.add(libraryOperation("13", "花边"));
        operations.add(libraryOperation("14", "花边"));
        // 空名 ⇒ 无法呈现也无法判定 ⇒ **不计**
        operations.add(libraryOperation("15", ""));
        Map<String, Object> group = new LinkedHashMap<>();
        group.put("group", "车位");
        group.put("operations", operations);
        Map<String, Object> catalog = new LinkedHashMap<>();
        catalog.put("total", operations.size());
        catalog.put("groups", List.of(group));
        return catalog;
    }

    private static Map<String, Object> routings() {
        List<Map<String, Object>> rows = new ArrayList<>();
        rows.add(route(ConfigReadinessService.BASE_ROUTE_NAMES.get(0), true));
        rows.add(route("商家自建路线", false));
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("total", rows.size());
        payload.put("routings", rows);
        return payload;
    }

    private static Map<String, Object> route(String name, boolean isDefault) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("name", name);
        row.put("is_default", isDefault);
        return row;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> steps(Map<String, Object> payload) {
        return (Map<String, Object>) payload.get("steps");
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> facts(Map<String, Object> steps, String key) {
        Map<String, Object> step = (Map<String, Object>) steps.get(key);
        assertThat(step).as("步骤 %s 必须存在", key).isNotNull();
        return (Map<String, Object>) step.get("facts");
    }

    @SuppressWarnings("unchecked")
    private String href(Map<String, Object> steps, String key) {
        Map<String, Object> step = (Map<String, Object>) steps.get(key);
        assertThat(step).as("步骤 %s 必须存在", key).isNotNull();
        return String.valueOf(step.get("href"));
    }

    @Test
    @DisplayName("① 工序与单价：total = 价目行 + 孤儿行；unpriced 只数空价；orphans 按工艺配置页口径")
    void operationsFactsFollowTheConfigPageRule() {
        Map<String, Object> steps = steps(service.readiness(TENANT, false));
        Map<String, Object> facts = facts(steps, ConfigReadinessService.STEP_OPERATIONS);

        // 价目行 2 条（已收敛到逻辑工序）+ 孤儿 1 个（花边：两行同逻辑名去重、空名不计、
        // 三边的另一变体行虽然没被引用但逻辑名已定价 ⇒ 不算）
        assertThat(facts.get("total")).isEqualTo(3);
        assertThat(facts.get("unpriced")).isEqualTo(1);
        assertThat(facts.get("orphans")).isEqualTo(1);
    }

    @Test
    @DisplayName("② 工艺路线 / 默认路线：missing_base_routes 点名缺哪条；默认路线数只数 is_default")
    void routingFactsNameTheMissingBaseRoute() {
        Map<String, Object> steps = steps(service.readiness(TENANT, false));

        assertThat(facts(steps, ConfigReadinessService.STEP_ROUTINGS).get("missing_base_routes"))
                .isEqualTo(List.of(ConfigReadinessService.BASE_ROUTE_NAMES.get(1)));
        assertThat(facts(steps, ConfigReadinessService.STEP_DEFAULT_ROUTE).get("count")).isEqualTo(1);
    }

    @Test
    @DisplayName("③ 加工项 / 加工费组合 / 算料：计数与取值逐值来自既有 service")
    void processingItemsFeeCombinationsAndCalcFacts() {
        Map<String, Object> steps = steps(service.readiness(TENANT, false));

        assertThat(facts(steps, ConfigReadinessService.STEP_PROCESSING_ITEMS).get("total")).isEqualTo(8L);
        assertThat(facts(steps, ConfigReadinessService.STEP_PROCESSING_ITEMS).get("active")).isEqualTo(7L);
        assertThat(facts(steps, ConfigReadinessService.STEP_FEE_COMBINATIONS).get("combinations")).isEqualTo(3);
        assertThat(facts(steps, ConfigReadinessService.STEP_FEE_COMBINATIONS).get("gaps")).isEqualTo(1);
        assertThat(facts(steps, ConfigReadinessService.STEP_CALC).get("source")).isEqualTo("stored");
    }

    @Test
    @DisplayName("④ 缺 processing:manage ⇒ remnant-sizes 整个不在 steps 里（不返回 0、不返回占位）")
    void remnantSizesStepIsOmittedWithoutTheCode() {
        Map<String, Object> steps = steps(service.readiness(TENANT, false));

        assertThat(steps).doesNotContainKey(ConfigReadinessService.STEP_REMNANT_SIZES);
        // 其余六步一个不少（省略只针对跨码那一步，不是把整份响应缩掉）
        assertThat(steps.keySet()).containsExactly(
                ConfigReadinessService.STEP_OPERATIONS,
                ConfigReadinessService.STEP_ROUTINGS,
                ConfigReadinessService.STEP_DEFAULT_ROUTE,
                ConfigReadinessService.STEP_PROCESSING_ITEMS,
                ConfigReadinessService.STEP_FEE_COMBINATIONS,
                ConfigReadinessService.STEP_CALC);
    }

    @Test
    @DisplayName("⑤ 持 processing:manage ⇒ remnant-sizes 在，facts 给 configured/items")
    void remnantSizesStepPresentForHolders() {
        Map<String, Object> steps = steps(service.readiness(TENANT, true));

        Map<String, Object> facts = facts(steps, ConfigReadinessService.STEP_REMNANT_SIZES);
        assertThat(facts.get("configured")).isEqualTo(true);
        assertThat(facts.get("items")).isEqualTo(1);
    }

    @Test
    @DisplayName("⑥ 某一步取数抛错 ⇒ 该步仍在但 facts 为空（读不到 ≠ 没配，不吞成 0）")
    void failingReadYieldsEmptyFactsNotZero() {
        when(productionRoutingReadService.operationPositions(TENANT))
                .thenThrow(new IllegalStateException("boom"));

        Map<String, Object> steps = steps(service.readiness(TENANT, false));

        assertThat(steps).containsKey(ConfigReadinessService.STEP_OPERATIONS);
        assertThat(facts(steps, ConfigReadinessService.STEP_OPERATIONS)).isEmpty();
    }

    @Test
    @DisplayName("⑦ 每步都给 href（七步逐条；缺一个 ⇒ 前端「去配置」成死链）")
    void everyStepCarriesAnHref() {
        Map<String, Object> steps = steps(service.readiness(TENANT, true));

        assertThat(href(steps, ConfigReadinessService.STEP_OPERATIONS)).isEqualTo("/production/routings");
        assertThat(href(steps, ConfigReadinessService.STEP_ROUTINGS)).isEqualTo("/production/routings");
        assertThat(href(steps, ConfigReadinessService.STEP_DEFAULT_ROUTE)).isEqualTo("/production/routings");
        assertThat(href(steps, ConfigReadinessService.STEP_PROCESSING_ITEMS))
                .isEqualTo("/settings?domain=processing-items");
        assertThat(href(steps, ConfigReadinessService.STEP_FEE_COMBINATIONS))
                .isEqualTo("/production/processing-fees");
        assertThat(href(steps, ConfigReadinessService.STEP_CALC)).isEqualTo("/settings/params");
        assertThat(href(steps, ConfigReadinessService.STEP_REMNANT_SIZES))
                .isEqualTo("/settings?domain=remnant-sizes");
    }
}
