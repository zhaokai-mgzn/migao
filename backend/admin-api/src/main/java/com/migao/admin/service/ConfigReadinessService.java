package com.migao.admin.service;

import com.migao.admin.dto.ProcessingItemQueryRequest;
import com.migao.admin.dto.RemnantViews;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 「配置就绪度」的**服务端聚合器**（issue #6579；上游 = #6573 的配置主线）。
 *
 * <h2>它为什么存在（今天的具体代价）</h2>
 *
 * 画出「还缺什么、下一步去哪」这条配置主线，前端原本要发 **5 个**读请求（工序价目 / 工艺路线 /
 * 加工费组合 / 加工费缺口 / 算料配置）：任一失败只能落到三态的 `unknown`，而
 * **「网络失败」与「没权限」在客户端长得一样** ⇒ 话术给不出可行动出口。
 * 更关键的是主线第 ① 步缺一维：**孤儿工序**（库里有、没有任何价目行）要复刻工艺配置页的
 * 逻辑名去重口径才能算 ⇒ 前端一旦自己算就是**第二份会漂的实现**（#5858「同屏两个矛盾的数」
 * 就是这么来的）⇒ 那天只能传 `null`（不参与判定）。**这份事实本来就住在服务端** ⇒ 由服务端给数。
 *
 * <h2>三条口径（每条都可被判据检查）</h2>
 *
 * 1. 🔴 **本类是聚合器，不是第二份数据源**：每个事实都取自**既有** service 的**既有**方法
 *    （{@code ProductionRoutingReadService#operationPositions}、
 *    {@code ProductionOperationQueryService#catalog/#routings}、
 *    {@code ProcessingFeeQueryService#combinations/#feeGaps}、
 *    {@code ProcessingItemService#getProcessingItems}、
 *    {@code CraftCalcConfigService#get}、{@code RemnantService#specs}）——
 *    **本类不碰持久层、不写任何查询语句、不新造任何一个业务口径**
 *    （守卫 `tests/unit_ci_workflows/test_config_readiness_endpoint.py` 钉住「零持久层 / 零查询语句」）。
 * 2. 🔴 **只给事实，不给三态**：响应里是计数与取值（`total` / `unpriced` / `orphans` …），
 *    `done` / `todo` / `unknown` 的判定**唯一真值源**仍是
 *    `frontend/admin-web/src/lib/config-readiness.ts` 的 `judge*` 系列
 *    （类级守卫 `tests/unit_ci_workflows/test_config_readiness_single_source.py`）。
 *    在这里判三态 = 把「读不到」与「没配」的取舍搬进第二个家，两处必然漂移。
 * 3. 🔴 **跨码步骤按调用方权限整个省略**：`remnant-sizes` 的读面码是 {@value #REMNANT_SIZES_READ_CODE}
 *    （余料尺寸表读端点所属的类级码）。调用方不持该码 ⇒ 该步**整个不出现在 `steps` 里** ——
 *    **不返回 0、不返回 forbidden 占位**（两者都是谎报：前者说「你没配」，后者把「不该你看见」
 *    画成一个可见的缺口）。判定由调用方（Controller）用**同一个**授权实现问一次后传入。
 *
 * <h2>取不到怎么表达（fail-closed）</h2>
 *
 * 任一步的取数抛错 ⇒ 该步仍然**在** `steps` 里，但 `facts` 是**空对象** ⇒ 前端把缺键读成
 * `unknown`（「读不到」），**绝不**降级成 `todo`（「没配」）。这里刻意**不吞成 0**：
 * 0 是一个会被判成「没配置」的真实读数。
 *
 * <h2>孤儿工序的**单一真值源**口径</h2>
 *
 * 与「工艺配置」页（`frontend/admin-web/src/components/production-config/features.ts` 的
 * `orphanOps` / `orphanRows`）**同一份判据**，且两个输入就是那两页用的**同两个读面**
 * （`GET /production/operations-catalog` 与 `GET /production/operation-positions`）：
 * <ol>
 *   <li>**孤儿候选** = 工序库里**没有任何价目行引用它**的工序（价目行的 {@code variant_operation_id}
 *       指向该工序 {@code id}）—— 即「库里有、价目表没有」；</li>
 *   <li>按**逻辑工序名**去重（库里同一道活按部位拆成多行：{@code 精裁-布} / {@code 精裁-纱}）；</li>
 *   <li>价格表里**已经出现过**的逻辑名不算孤儿（该道活有价，只是用了另一个变体行）；</li>
 *   <li>名字为空的库行不计（无法呈现，也无法判定）。</li>
 * </ol>
 * 计数 = 满足上述四条的**逻辑工序数**（= 工艺配置页表里那些「无价目行」行的行数）。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ConfigReadinessService {

    /** 主线第 ① 步（工序与单价）：`facts = {total, unpriced, orphans}`。 */
    public static final String STEP_OPERATIONS = "operations";
    /** 主线第 ② 步（工艺路线）：`facts = {missing_base_routes}`。 */
    public static final String STEP_ROUTINGS = "routings";
    /** 主线第 ③ 步（默认路线）：`facts = {count}`。 */
    public static final String STEP_DEFAULT_ROUTE = "default-route";
    /** 主线（#6579 接上）加工项：`facts = {total, active}`。 */
    public static final String STEP_PROCESSING_ITEMS = "processing-items";
    /** 主线第 ④ 步（加工费组合）：`facts = {combinations, gaps}`。 */
    public static final String STEP_FEE_COMBINATIONS = "fee-combinations";
    /** 主线第 ⑤ 步（算料配置）：`facts = {source}`。 */
    public static final String STEP_CALC = "calc";
    /** 主线（#6579 接上）余料尺寸：**仅持 {@value #REMNANT_SIZES_READ_CODE} 时出现**；`facts = {configured, items}`。 */
    public static final String STEP_REMNANT_SIZES = "remnant-sizes";

    /**
     * 余料尺寸读面的**权限码**（跨码步骤的判据来源）。
     *
     * <p>它是余料尺寸表读端点
     * （{@code RemnantController} 的 {@code GET /api/admin/production/remnants/small-item-specs}）
     * 所属的**类级** {@code @RequirePermission}，也是前端
     * `frontend/admin-web/src/lib/config-center-domains.ts` 里 `remnant-sizes` 域的 `requiredCode`。
     * 三处**逐字同值**由 `tests/unit_ci_workflows/test_config_readiness_endpoint.py` 双向钉住
     * （改一处不改另两处 ⇒ 红）。</p>
     */
    public static final String REMNANT_SIZES_READ_CODE = "processing:manage";

    /**
     * 两条**基础路线**的名字（issue #4677 的口径：判据是「缺哪条」，不是数条数）。
     *
     * <p>🔴 与前端 `frontend/admin-web/src/lib/config-readiness.ts` 的 `BASE_ROUTE_NAMES`、
     * 以及算料引擎 {@code backend/ai-agent-service/app/production/routing.py} 的
     * {@code ROUTE_TEMPLATE_NAME_DEFAULT} / {@code FABRIC_ROUTE_TEMPLATE_NAME_DEFAULT}
     * **逐字同源**（Java 无法 import Python/TS ⇒ 逐字解析三份文本是唯一可失败的同源判据）。
     * 三处任一处漂移 ⇒ `tests/unit_ci_workflows/test_config_readiness_endpoint.py` 判红。</p>
     */
    public static final List<String> BASE_ROUTE_NAMES =
            List.of("窗帘工序路线（默认）", "布料工序路线");

    /**
     * 每步的**可点去处**（`migao-dev-flow` §31.3 / §22 基线①：出处由服务端给，前端只格式化）。
     *
     * <p>🔴 与前端 `MAINLINE_STEPS[].href` **逐值相等**（同一条守卫双向钉住）——
     * 两处各写一份死链就是「一改一漏」（#6825 的病灶：旧深链
     * {@code /production/routings?tab=calc} 落到了一个已退役 tab）。</p>
     */
    private static final Map<String, String> STEP_HREFS = stepHrefs();

    private static Map<String, String> stepHrefs() {
        Map<String, String> hrefs = new LinkedHashMap<>();
        hrefs.put(STEP_OPERATIONS, "/production/routings");
        hrefs.put(STEP_ROUTINGS, "/production/routings");
        hrefs.put(STEP_DEFAULT_ROUTE, "/production/routings");
        hrefs.put(STEP_PROCESSING_ITEMS, "/settings?domain=processing-items");
        hrefs.put(STEP_FEE_COMBINATIONS, "/production/processing-fees");
        hrefs.put(STEP_CALC, "/settings/params");
        hrefs.put(STEP_REMNANT_SIZES, "/settings?domain=remnant-sizes");
        return Map.copyOf(hrefs);
    }

    /** 工序库 / 工序价目（**既有读面**；孤儿工序的两个输入之一）。 */
    private final ProductionRoutingReadService productionRoutingReadService;
    /** 工序库目录 + 工艺路线（**既有读面**）。 */
    private final ProductionOperationQueryService productionOperationQueryService;
    /** 加工费组合 / 缺口（**既有读面**）。 */
    private final ProcessingFeeQueryService processingFeeQueryService;
    /** 加工项目录分页读面（**既有读面**：`total` / 启用数各取一次分页的 `total`）。 */
    private final ProcessingItemService processingItemService;
    /** 算料配置读面（**既有读面**：只要 `source`，不取配置本体）。 */
    private final CraftCalcConfigService craftCalcConfigService;
    /** 余料尺寸表读面（**既有读面**，跨码步骤）。 */
    private final RemnantService remnantService;

    /**
     * 就绪度事实（**只给事实，不给三态**）。
     *
     * @param tenantId            租户
     * @param includeRemnantSizes 调用方是否持 {@value #REMNANT_SIZES_READ_CODE}
     *                            ⇒ 不持则 `remnant-sizes` 那一步**整个不在 `steps` 里**
     * @return {@code {steps: {<stepKey>: {facts: {...}, href: "..."}}}}（键序 = 主线渲染序）
     */
    public Map<String, Object> readiness(Long tenantId, boolean includeRemnantSizes) {
        Map<String, Object> steps = new LinkedHashMap<>();
        steps.put(STEP_OPERATIONS, step(STEP_OPERATIONS, this::operationsFacts, tenantId));
        steps.put(STEP_ROUTINGS, step(STEP_ROUTINGS, this::routingFacts, tenantId));
        steps.put(STEP_DEFAULT_ROUTE, step(STEP_DEFAULT_ROUTE, this::defaultRouteFacts, tenantId));
        steps.put(STEP_PROCESSING_ITEMS, step(STEP_PROCESSING_ITEMS, this::processingItemFacts, tenantId));
        steps.put(STEP_FEE_COMBINATIONS, step(STEP_FEE_COMBINATIONS, this::feeCombinationFacts, tenantId));
        steps.put(STEP_CALC, step(STEP_CALC, this::calcFacts, tenantId));
        if (includeRemnantSizes) {
            steps.put(STEP_REMNANT_SIZES, step(STEP_REMNANT_SIZES, this::remnantSizeFacts, tenantId));
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("steps", steps);
        return result;
    }

    /** 一步的 `{facts, href}`；取数抛错 ⇒ `facts` 为空对象（前端读成 `unknown`，**不降级成 todo**）。 */
    private Map<String, Object> step(String key, StepFacts facts, Long tenantId) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("facts", factsOf(key, facts, tenantId));
        entry.put("href", STEP_HREFS.get(key));
        return entry;
    }

    private Map<String, Object> factsOf(String key, StepFacts facts, Long tenantId) {
        try {
            return facts.facts(tenantId);
        } catch (RuntimeException e) {
            // 读不到 ≠ 没配：**空 facts** 让前端落 unknown；日志点名是哪一步、为什么（不静默）
            log.warn("配置就绪度取数失败: step={}, tenantId={}, reason={}", key, tenantId, e.getMessage());
            return Map.of();
        }
    }

    /** 一步的事实取数器（把 try/catch 收在一处，避免六个步骤各写一遍）。 */
    @FunctionalInterface
    private interface StepFacts {
        Map<String, Object> facts(Long tenantId);
    }

    // ══════════════════════════ ① 工序与单价 ══════════════════════════

    /**
     * `{total, unpriced, orphans}` —— 三项都取**工艺配置页自己用的那几个输入**，不另立口径：
     *
     * <ul>
     *   <li>{@code total} = 工序库目录的 {@code total}（= 板子 {@code operationsReady} 的同一个输入
     *       「有没有工序」；取 {@code null} ⇒ 前端落「读不到」，**不回落 0**）；</li>
     *   <li>{@code unpriced} = 价目行里 {@code unit_price} 为空的条数（与板子 {@code cellState}
     *       的 {@code unit_price == null ⇒ unpriced} 同判据；#4951 之后每个逻辑工序只有一行）；</li>
     *   <li>{@code orphans} = 孤儿逻辑工序数（见 {@link #orphanOperationNames} 的四条口径）。</li>
     * </ul>
     */
    private Map<String, Object> operationsFacts(Long tenantId) {
        List<Map<String, Object>> positions =
                productionRoutingReadService.operationPositions(tenantId);
        Map<String, Object> catalog = productionOperationQueryService.catalog(tenantId);
        Set<String> pricedOperations = new LinkedHashSet<>();
        Set<String> referencedIds = new LinkedHashSet<>();
        int unpriced = 0;
        for (Map<String, Object> row : positions) {
            pricedOperations.add(stringOf(row.get("operation")));
            referencedIds.add(stringOf(row.get("variant_operation_id")));
            if (row.get("unit_price") == null) {
                unpriced++;
            }
        }
        int orphans = orphanOperationNames(catalog, referencedIds, pricedOperations).size();
        Map<String, Object> facts = new LinkedHashMap<>();
        facts.put("total", catalog == null ? null : catalog.get("total"));
        facts.put("unpriced", unpriced);
        facts.put("orphans", orphans);
        return facts;
    }

    /**
     * 孤儿工序的**逻辑名**集合 —— 与 `features.ts` 的 `orphanRows` 同口径：
     * 库里有、没有任何价目行（{@code variant_operation_id}）引用它、且该逻辑名在价目表里也没出现过；
     * 同一逻辑名多行只算一个；空名不计（板子也呈现不了）。
     */
    private Set<String> orphanOperationNames(Map<String, Object> catalog, Set<String> referencedIds,
                                             Set<String> pricedOperations) {
        Set<String> orphanNames = new LinkedHashSet<>();
        for (Map<String, Object> operation : libraryOperations(catalog)) {
            String id = stringOf(operation.get("id"));
            String name = stringOf(operation.get("name"));
            if (referencedIds.contains(id) || pricedOperations.contains(name) || name.isEmpty()) {
                continue;
            }
            orphanNames.add(name);
        }
        return orphanNames;
    }

    /** 工序库目录摊平成工序项清单（`catalog` 的 `groups[].operations[]`；不另取一次库）。 */
    private List<Map<String, Object>> libraryOperations(Map<String, Object> catalog) {
        List<Map<String, Object>> out = new ArrayList<>();
        Object groups = catalog == null ? null : catalog.get("groups");
        if (!(groups instanceof List<?> groupList)) {
            return out;
        }
        for (Object group : groupList) {
            if (!(group instanceof Map<?, ?> groupMap)) {
                continue;
            }
            Object operations = groupMap.get("operations");
            if (!(operations instanceof List<?> operationList)) {
                continue;
            }
            for (Object operation : operationList) {
                if (operation instanceof Map<?, ?> operationMap) {
                    Map<String, Object> view = new LinkedHashMap<>();
                    operationMap.forEach((k, v) -> view.put(String.valueOf(k), v));
                    out.add(view);
                }
            }
        }
        return out;
    }

    // ══════════════════════════ ②③ 工艺路线 / 默认路线 ══════════════════════════

    /** `{missing_base_routes}` —— 缺哪几条**基础路线**（名字取自 {@link #BASE_ROUTE_NAMES}）。 */
    private Map<String, Object> routingFacts(Long tenantId) {
        List<String> names = routeNames(tenantId);
        List<String> missing = new ArrayList<>();
        for (String base : BASE_ROUTE_NAMES) {
            if (!names.contains(base)) {
                missing.add(base);
            }
        }
        Map<String, Object> facts = new LinkedHashMap<>();
        facts.put("missing_base_routes", missing);
        return facts;
    }

    /** `{count}` —— 标记为默认的路线条数（**恰好一条**才算完成，判定在前端）。 */
    private Map<String, Object> defaultRouteFacts(Long tenantId) {
        int count = 0;
        for (Map<String, Object> route : routings(tenantId)) {
            if (Boolean.TRUE.equals(route.get("is_default"))) {
                count++;
            }
        }
        Map<String, Object> facts = new LinkedHashMap<>();
        facts.put("count", count);
        return facts;
    }

    private List<String> routeNames(Long tenantId) {
        List<String> names = new ArrayList<>();
        for (Map<String, Object> route : routings(tenantId)) {
            names.add(stringOf(route.get("name")));
        }
        return names;
    }

    /** 工艺路线读面（`{total, routings:[{id, name, is_default, …}]}`）的列表部分。 */
    private List<Map<String, Object>> routings(Long tenantId) {
        Map<String, Object> payload = productionOperationQueryService.routings(tenantId);
        Object rows = payload == null ? null : payload.get("routings");
        List<Map<String, Object>> out = new ArrayList<>();
        if (!(rows instanceof List<?> list)) {
            return out;
        }
        for (Object row : list) {
            if (row instanceof Map<?, ?> map) {
                Map<String, Object> view = new LinkedHashMap<>();
                map.forEach((k, v) -> view.put(String.valueOf(k), v));
                out.add(view);
            }
        }
        return out;
    }

    // ══════════════════════════ 加工项 ══════════════════════════

    /**
     * `{total, active}` —— 加工项目录的总数与启用数。
     *
     * <p>复用**既有**分页读面（`ProcessingItemService#getProcessingItems`）只取 `total`：
     * 不新写一条 count SQL（那会成为第二套过滤口径 —— 分页读面里已经有租户/关键字/状态条件）。</p>
     */
    private Map<String, Object> processingItemFacts(Long tenantId) {
        long total = processingItemTotal(tenantId, null);
        long active = processingItemTotal(tenantId, "active");
        Map<String, Object> facts = new LinkedHashMap<>();
        facts.put("total", total);
        facts.put("active", active);
        return facts;
    }

    private long processingItemTotal(Long tenantId, String status) {
        ProcessingItemQueryRequest query = new ProcessingItemQueryRequest();
        // 只要 total：取 1 条即可（分页读面的 total 与 size 无关）
        query.setPage(1L);
        query.setSize(1L);
        query.setStatus(status);
        Long total = processingItemService.getProcessingItems(query, tenantId).getTotal();
        return total == null ? 0L : total;
    }

    // ══════════════════════════ ④ 加工费组合 ══════════════════════════

    /** `{combinations, gaps}` —— 组合价条数 + 未定价组合数（缺口口径**在服务端**，前端不重算）。 */
    private Map<String, Object> feeCombinationFacts(Long tenantId) {
        Map<String, Object> combinations = processingFeeQueryService.combinations(tenantId);
        Map<String, Object> gaps = processingFeeQueryService.feeGaps(tenantId);
        Map<String, Object> facts = new LinkedHashMap<>();
        facts.put("combinations", combinations == null ? null : combinations.get("total"));
        facts.put("gaps", gaps == null ? null : gaps.get("unpriced_combination_total"));
        return facts;
    }

    // ══════════════════════════ ⑤ 算料配置 ══════════════════════════

    /** `{source}` —— `stored` / `default`（取值本身是事实；三态判定在前端）。 */
    private Map<String, Object> calcFacts(Long tenantId) {
        Map<String, Object> config = craftCalcConfigService.get(tenantId);
        Map<String, Object> facts = new LinkedHashMap<>();
        facts.put("source", config == null ? null : config.get("source"));
        return facts;
    }

    // ══════════════════════════ 余料尺寸（跨码） ══════════════════════════

    /** `{configured, items}` —— 小件用料尺寸表配没配、配了几条（读面码 {@value #REMNANT_SIZES_READ_CODE}）。 */
    private Map<String, Object> remnantSizeFacts(Long tenantId) {
        RemnantViews.SpecsView specs = remnantService.specs(tenantId);
        Map<String, Object> facts = new LinkedHashMap<>();
        facts.put("configured", specs.configured());
        facts.put("items", specs.items() == null ? 0 : specs.items().size());
        return facts;
    }

    /** `null` 安全的字符串归一（读面里 `id` 可能是数字或字符串，两种都收敛成字符串）。 */
    private static String stringOf(Object value) {
        return value == null ? "" : String.valueOf(value);
    }
}
