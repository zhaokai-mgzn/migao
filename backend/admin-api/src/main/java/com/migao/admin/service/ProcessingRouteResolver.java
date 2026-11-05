package com.migao.admin.service;

import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.entity.ProductionRouteRule;
import com.migao.admin.entity.ProductionRouteSignal;
import com.migao.admin.entity.ProductionRouteTemplate;
import com.migao.admin.exception.BusinessException;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

import static com.migao.admin.service.ProcessingOrderService.*;
import static com.migao.admin.service.ProcessingOperationWeaver.conditionalRuleTriggers;
import static com.migao.admin.service.ProcessingOperationWeaver.rulePositionMatches;
import static com.migao.admin.service.ProcessingOperationWeaver.processingItemNames;
import static com.migao.admin.service.ProcessingOperationWeaver.specialOptions;

/**
 * 加工单**路线解析**单元（issue #8725 第二档切片，从 {@link ProcessingOrderService} **纯搬运**）。
 *
 * <p><b>单一职责</b>：把「部位 × 工艺 → 工序库路线」这一步算出来 ——
 * 派生路线键（{@link #deriveRouteKey}）、按键取路线模板（{@link #resolveRoute}）、
 * 把模板展开成工序序列（{@link #buildRoute}）、以及展开所需的三件套
 * （条件工序插入的锚点工具留在 {@link ProcessingOperationWeaver}、存量信号兜底
 * {@link #signals} / {@link #firstSignalMatch} 在此）。<b>不写库、不发请求</b>。</p>
 *
 * <p>搬运口径：方法体、注释、异常码、日志文案**一字未改**；只改了「在哪个类里」。</p>
 */
class ProcessingRouteResolver {

    /** 日志类别**必须**仍是 {@code ProcessingOrderService}：既有判据与运维告警按该 logger
     * 取事件（{@code ProcessingOrderRouteSourceTest} 就挂在它上面）—— 换类别 = 可观测面回退。*/
    private static final org.slf4j.Logger log =
            org.slf4j.LoggerFactory.getLogger(ProcessingOrderService.class);

    private final ProductionOperationQueryService productionOperationQueryService;
    /** 条件工序编织（无状态；与门面共享同一个查询服务）。 */
    private final ProcessingOperationWeaver weaver;

    ProcessingRouteResolver(ProductionOperationQueryService productionOperationQueryService) {
        this.productionOperationQueryService = productionOperationQueryService;
        this.weaver = new ProcessingOperationWeaver(productionOperationQueryService);
    }


    /**
     * 取路线（**新结构**：主线 + 规则 + 部位适用性）+ 记来源（V60，issue #4308 三层回落语义逐层可观测）。
     *
     * <p><b>P2b 切换（issue #4459）</b>：路线来源从旧 {@code production_routings} 的
     * 「{@code (部位 × 工艺)} 展开快照」切到 {@code production_route_templates.mainline}
     * + {@code production_route_rules} + {@code production_operation_positions}。
     * 规则应用语义与真值源 {@code routing.py::build_route_v2} <b>逐字一致</b>
     * （见 {@link #buildRoute}）。</p>
     *
     * <ul>
     *   <li><b>T1</b> 信号全不命中 ⇒ 取该租户的**默认路线模板**，来源 {@code default}，
     *       记 {@link #INCIDENT_ROUTE_DEFAULTED}（warn 级 —— 迁移前这一层**连 info 都没有**）；</li>
     *   <li><b>T2</b> 派生键的部位**没有**路线模板 ⇒ 回落默认路线模板，来源降级 {@code missing_route}
     *       （**不并入 {@code partial}**：补救动作不同 —— T2 要「建/改路线」、只命中一维要「配信号」），
     *       记 {@link #INCIDENT_ROUTE_FALLBACK}；</li>
     *   <li><b>T3</b> 该租户**连默认路线模板都没有** / 路线引用的工序在库中缺行 ⇒
     *       **fail-closed 中止生成**（#4116 已落码，本单保持不动）。
     *       ⚠️ **绝不**回落到常量 {@code 布帘×韩褶} 或加工项目录。</li>
     * </ul>
     *
     * <p>来源与「实际使用的路线键」必须**同源返回**：分两次算必然漂移（记下来的键与实际实例化的
     * 工序对不上，等于白记）。</p>
     */
    @SuppressWarnings("unchecked")
    RouteResolution resolveRoute(RouteKey key, Long tenantId, Map<String, Object> entry,
                                         List<ProductionRouteRule> rules,
                                         List<ProductionOperationPosition> priceRows,
                                         Map<String, Map<String, Object>> catalog) {
        String requestedKey = "default".equals(key.source()) ? null : key.curtainType() + "×" + key.craft();
        String usedKey = key.curtainType() + "×" + key.craft();
        String source = key.source();
        // 缺 `craft` 且该租户没有默认工艺（production_crafts.is_default）⇒ T3 fail-closed。
        // 绝不静默取常量 `韩褶`：工艺决定「插入哪道工序 + 计件系数」，猜错 = 算错工人工资。
        if (key.craft() == null) {
            log.error("{} 订单缺 `craft` 且该租户没有默认工艺，生成加工单中止（不回退常量 韩褶）: "
                            + "tenantId={}, 部位={}, productName={}",
                    INCIDENT_ROUTING_UNRESOLVED, tenantId, key.curtainType(), entry.get("productName"));
            throw new BusinessException(ERR_ROUTING_NOT_FOUND,
                    String.format("订单未给出工艺（craft），且该租户没有配置默认工艺，无法实例化工序"),
                    422,
                    "该租户没有设过默认工艺（商家面无此维护入口，需服务方配置），"
                            + "或在下单时给出工艺");
        }
        // T1：全无派生信号 ⇒ 直接取默认路线模板（**该租户的**默认，不是常量）
        if ("default".equals(source)) {
            log.warn("{} 订单无任何信号命中（componentRole / craft_hint / 存量信号表的加工项名·options），"
                            + "落默认路线 {}: tenantId={}, productName={}, 信号={}",
                    INCIDENT_ROUTE_DEFAULTED, usedKey, tenantId, entry.get("productName"), signals(entry));
        }
        // T2：派生出部位/工艺但该部位没有路线模板 ⇒ 回落默认路线模板
        ProductionRouteTemplate template =
                productionOperationQueryService.routeTemplateFor(tenantId, key.curtainType());
        // 实例化用的**部位**：命中部位自己的模板 ⇒ 用它；回落默认模板 ⇒ 用模板**自己适用**的部位
        // （否则「罗马帘」这类库里没有价目/工序的部位会让整条路线被适用性矩阵滤空 ⇒ 零工序）。
        String routePosition = key.curtainType();
        String routeCraft = key.craft();
        if (template == null) {
            log.warn("{} 部位「{}」没有可用的工艺路线模板，回落默认路线模板（来源 {} ⇒ missing_route）: "
                            + "tenantId={}, 想走的键={}, productName={}, 库中现有路线模板={}",
                    INCIDENT_ROUTE_FALLBACK, key.curtainType(), source,
                    tenantId, usedKey, entry.get("productName"),
                    productionOperationQueryService.routingKeys(tenantId));
            source = "missing_route";
            template = productionOperationQueryService.defaultRouteTemplate(tenantId);
            if (template != null) {
                routePosition = defaultPositionOf(template);
            }
            // 工艺维**一起回落**：派生出的工艺（如 平幔）属于「该部位没有的那条路线」，
            // 换到默认模板的部位上会插进该部位不做的工序（旧结构 T2 也是整键回落默认）。
            String fallbackCraft = productionOperationQueryService.defaultCraft(tenantId);
            routeCraft = fallbackCraft == null ? routeCraft : fallbackCraft;
        }
        if (template == null) {
            List<String> available = productionOperationQueryService.routingKeys(tenantId);
            log.error("{} 该租户没有默认工艺路线模板，生成加工单中止（不回退加工项目录、不回退常量路线）: "
                            + "tenantId={}, 需要={}, 库中现有路线模板={}, productName={}",
                    INCIDENT_ROUTING_UNRESOLVED, tenantId, usedKey, available, entry.get("productName"));
            throw new BusinessException(ERR_ROUTING_NOT_FOUND,
                    String.format("工序库缺少「%s」的工艺路线模板，且该租户没有默认路线，无法实例化工序"
                                    + "（工序来源为工序库，不回退加工项目录）", usedKey),
                    422,
                    String.format("请在「企业基础设置 → 工艺路线」建一条路线并设为默认（当前库中路线模板 %s）；"
                                    + "若为空库，先确认 V71/V72 种子迁移已执行",
                            available.isEmpty() ? "**为空**" : "有：" + String.join("、", available)));
        }
        Map<String, Object> route = buildRoute(template, routePosition, routeCraft, entry,
                rules, priceRows, catalog, tenantId);
        List<String> missing = (List<String>) route.get("missing_operations");
        if (missing != null && !missing.isEmpty()) {
            log.error("{} 工艺路线引用的工序在工序库无活跃行，生成加工单中止（不回退加工项目录）: "
                            + "tenantId={}, 路线={}, 缺工序={}, productName={}",
                    INCIDENT_ROUTING_UNRESOLVED, tenantId, usedKey, missing, entry.get("productName"));
            throw new BusinessException(ERR_OPERATION_NOT_FOUND,
                    // 🔴 issue #4937 / O1：`applicable` 过滤退场后，**位置维**不再由那道闸给出
                    // ⇒ 可行动性信息（「缺在哪个产品形态上」）必须由本条 message 自己承载
                    // （改前它由「该工序在「X」部位缺库行」那句 hint 顺带给出，而那句随过滤一起退场）。
                    String.format("工艺路线「%s」（产品形态「%s」）引用的工序 %s 在工序库中不存在，"
                                    + "无法实例化工序", template.getName(), routePosition, missing),
                    422,
                    String.format("请在工序库补上 %s（或改这条路线不再引用它们）",
                            String.join("、", missing)));
        }
        // `route_key` = **实际使用的那条路线的身份**。新结构里路线 = 具名模板（工艺已降为规则触发键）
        // ⇒ 用模板名而不是「部位×工艺」：后者在 T2 时描述的不是实际用的路线
        // （验收判据 6：「默认路线改为另一条 ⇒ 无信号订单实际使用键随之变」）。
        return new RouteResolution(route, template.getName(), requestedKey, source);
    }




    /**
     * **主线 + 规则 + 部位适用性** → 工序实例的基准序列（P2b，issue #4459）。
     *
     * <p>⚠️ <b>本方法是「怎么展开路线」的**唯一** Java 实现</b>，且必须与真值源
     * {@code routing.py::build_route_v2} <b>逐字一致</b>（顺序敏感）：</p>
     * <ol>
     *   <li>取主线（{@code template.mainline}，逻辑工序名）；</li>
     *   <li>按 {@code priority} <b>升序</b>应用规则（同 priority 按 id，读取侧已排好）：
     *       触发命中（工艺精确匹配 / 选项 ∈ 本单选项）⇒
     *       {@code insert} 用 {@code after_operation} 定位（锚点不在序列中 ⇒ <b>追加末尾</b>，
     *       与 {@code _insert_after} 同款）；{@code remove} 直接删除该逻辑工序名。
     *       ⚠️ <b>{@code remove} 不先于 {@code insert}</b>：顺序完全由 {@code priority} 决定。
     *       ⚠️ <b>规则级</b>的 {@code position}（部位限定）**照旧筛选** —— 它与「路线层的帘种适用性」
     *       （{@code production_route_templates.positions}）**不是**同一件事：实测去掉它会让规范
     *       9 条老路线的逐字重建判据变红（`ProductionRouteParityTest`），并让 `韩褶 × 布帘` 那条
     *       插入 {@code 上车布} 的规则对帘头单生效 ⇒ 帘头主线多一道不该做的工序（错发计件工资）；</li>
     *   <li>🔴 <b>「部位适用性」已退场</b>（issue #4937，用户裁定 2026-09-21「不计成本的改」）：
     *       主线里的名字**不再被 {@code production_operation_positions.applicable} 过滤**。
     *       唯一保留的判据是<b>名字形态</b>（issue #4609）：名字归一后**不等于自己** ⇒
     *       它是变体名 / 别名（{@code 精裁-布}），实例化按逻辑名建键永远查不到
     *       ⇒ <b>必须可见</b>（进 {@code missing_operations}，调用方 fail-closed 并指名报缺）；
     *       名字本身就是逻辑工序名 ⇒ 正常建键。⛔ 原来那条「键不存在 ⇒ 静默 {@code continue}」
     *       与「{@code applicable=false} ⇒ 静默滤掉」两条闸**一并删除** —— 它们是「部位」最后一次
     *       参与取路，而用户已裁定部位不再参与任何取价、取路、筛选、配置。</li>
     * </ol>
     *
     * <p>工序元数据（分组/单位/单价/必完/开始标记/作用域）逐字取该租户的工序库行
     * （经 {@link ProductionOperationQueryService#variantNameOf} 换回变体名）；
     * 库中缺该变体、或主线里出现**不认识的名字** ⇒ 登记进 {@code missing_operations}
     * （由调用方 fail-closed，**不猜默认值**，也**不静默丢**）。</p>
     *
     * <p><b>单价 = 该逻辑工序的「一口价」</b>（去部位化，issue #4883：矩阵按逻辑工序收敛为一行，
     * 收敛规则见 {@link ProductionOperationQueryService#collapseToLogical}；用户裁定取布帘价），
     * <b>逐字带出、绝不回落</b>（issue #4696，P1）：该价 {@code NULL} = <b>未定价</b> ⇒
     * 实例快照落 {@code NULL}（不是 0）。</p>
     *
     * <p>⚠️ 改前这里回落「工序库行价」（{@code production_operations.unit_price}，V49 DDL 是
     * {@code NOT NULL DEFAULT 0}）⇒ 布料单的 `配料`/`打包`（矩阵格 NULL）落库 <b>0 元</b> ⇒
     * 报工即按 0 计件（<b>工人白干且无人知道</b>），而 V88 的读面
     * （{@code GET /operation-layers}）**不回落**、判 {@code unpriced}、界面显示「未定价」
     * ⇒ 两处口径不一致，且「没定价」与「价本来就是 0」不可区分。
     * 现在两侧**同口径**：格价 NULL ⇒ 未定价（落 {@code NULL}）；格价 0 ⇒ <b>有价 0 元</b>。</p>
     */
    Map<String, Object> buildRoute(ProductionRouteTemplate template, String position, String craft,
                                           Map<String, Object> entry,
                                           List<ProductionRouteRule> rules,
                                           List<ProductionOperationPosition> priceRows,
                                           Map<String, Map<String, Object>> catalog,
                                           Long tenantId) {
        // 价目**一口价**（去部位化，issue #4883）：部位不再参与取价 ⇒ 把矩阵按逻辑工序收敛成
        // 「一道逻辑工序 → 一个价」（收敛规则 = ProductionOperationQueryService#collapseToLogical：
        // 适用行优先、其中**布帘列**优先 —— 用户裁定「取布帘价」）。
        // 🔴 未定价（收敛行的 unit_price IS NULL）**不得**回落工序库行价（issue #4696）：
        // 工序库是 `NOT NULL DEFAULT 0` ⇒ 回落把「未定价」变成「真 0 元」（工人白干且无人知道）。
        Map<String, BigDecimal> priceByLogical = new LinkedHashMap<>();
        for (ProductionOperationPosition row
                : ProductionOperationQueryService.collapseToLogical(priceRows)) {
            priceByLogical.put(row.getLogicalName(), row.getUnitPrice());
        }
        // ⛔ **「部位适用性」退场（issue #4937）**：此处原有 `applicableByLogical` 的构造 +
        // 下面两道 `continue` 闸（「键不存在」与「applicable=false」），本包按用户裁定
        // （2026-09-21「这个必须要改，我们移除了部位的设计，不计成本的改」，母单 #4936）
        // **整块删除** —— 部位不再参与取路。原来维护这条筛选的三条守卫已按同一次裁定退休/换基线：
        //  · `ProductionRouteParityTest#skippingApplicabilityFilterWouldLeakClothOnlyOperationsIntoSheerRoute`
        //    ⇒ 退休，原位换成「纱帘单与布帘单**工序集完全一致**」的新判据；
        //  · 9 条老路线**逐字重建** / `instantiationSequenceIsUnchangedForTheCanonicalRuleConfig`
        //    ⇒ 换成**去部位后的新模型冻结快照**基线（`RoutingModelFixture.DEPOSITIONED_ROUTINGS`）。
        // ⚠️ 唯一**保留**的判据是「名字形态」（见循环体：变体名/别名 ⇒ 进 missing_operations）。
        List<String> sequence = new ArrayList<>();
        for (String step : stringList(template.getMainline())) {
            sequence.add(step);
        }
        // 🔴 **工艺规则只对「窗帘类产品形态」生效**（issue #4937 / P2）。
        // 判据 = 与主线选择**同一个键**（`saleForm == 布料` ⇒ 布料主线，见 `routeTemplateFor`）：
        // 布料单是**另一个产品形态**（主线只有 `配料 → 打包`），在它上面套用窗帘工艺规则会把
        // `韩褶`/`上车布` 插进布料单 —— 而**旧口径下这件事被 `applicable` 过滤挡住了**
        // （`韩褶 × 布料` 当时不存在/不适用）。部位过滤退场后，「哪些工序不属于这个产品形态」
        // 必须由**产品形态**表达，否则布料单的工序数会当场从 2 变 4（真值源
        // `routing.py::build_route_v2` 的 `if is_fabric: continue` 是同一份口径）。
        boolean isFabricForm = FABRIC_POSITION.equals(position);
        List<String> options = specialOptions(entry);
        List<String> processingItems = processingItemNames(entry);
        // 顺序**必须**显式排一次（不依赖调用方）：与 routing.py::build_route_v2 的
        // `sorted(ROUTE_RULES, key=priority)` 逐字同口径 —— 规则应用顺序敏感
        // （`remove` 不先于 `insert`；锚点可用性由 priority 决定）。
        List<ProductionRouteRule> ordered = new ArrayList<>(rules);
        ordered.sort(Comparator.comparing(
                        (ProductionRouteRule r) -> r.getPriority() == null ? 0 : r.getPriority())
                .thenComparing(r -> r.getId() == null ? "" : r.getId()));
        for (ProductionRouteRule rule : ordered) {
            String kind = rule.getTriggerKind();
            // 产品形态分派（issue #7523）：布料单**只**吃 `sales_form`（售卖方式）规则；
            // 窗帘单**不**吃 sales_form（售卖方式只属于卖布行）。其余规则维持原口径 ——
            // 布料单不套用窗帘工艺规则（与真值源 `routing.py::build_route_v2` 同款）。
            boolean salesFormRule = TRIGGER_KIND_SALES_FORM.equals(kind);
            if (isFabricForm != salesFormRule) {
                continue;
            }
            if ("craft".equals(kind)) {
                if (!Objects.equals(rule.getTriggerValue(), craft)) {
                    continue;
                }
            } else if ("option".equals(kind)) {
                if (!options.contains(rule.getTriggerValue())) {
                    continue;
                }
            } else if (TRIGGER_KIND_SALES_FORM.equals(kind)) {
                // 售卖方式（issue #7523）：整卷 full_roll / 散剪 bulk_cut，与订单行**精确相等**
                // （快照键 sellingMethod；缺键 ⇒ 不命中，存量单行为不变）
                if (!Objects.equals(rule.getTriggerValue(), str(entry.get("sellingMethod")))) {
                    continue;
                }
            } else if ("processing_item".equals(kind)) {
                // 加工项触发（issue #4577，用户裁定「加工项也触发工序」）：触发键 = 该行
                // `processingInfo.processingItems[].name`，**精确相等**（与 craft/option 同款）。
                if (!processingItems.contains(rule.getTriggerValue())) {
                    continue;
                }
            } else if (TRIGGER_KIND_POSITION.equals(kind)) {
                // 部位维（issue #4962）：`trigger_value` = 部位名，写面把它**镜像**进 `position` 列
                // ⇒ 真正的筛选是下面那一处 {@link #rulePositionMatches}（**只有一处判据**）。
                // 列缺值 ⇒ 这条规则对**任何**部位都不生效 = 「规则已落库但永不生效」的黑洞
                // ⇒ 显式失败（不允许静默）。
                if (rule.getPosition() == null || rule.getPosition().isEmpty()) {
                    throw new BusinessException(ERR_ROUTING_NOT_FOUND,
                            String.format("工艺路线规则「%s」的部位维触发没有落 `position` 值，"
                                    + "无法判定它限哪个部位（规则永不生效）", rule.getId()),
                            422,
                            "请停用该规则后重建（部位维规则必须带 `position` / `trigger_value` 部位名）");
                }
            } else {
                // `shaped` 是表结构预留的触发类型（V71/V72 无种子行、无消费路径）。
                // 静默跳过会让「规则已落库但永不生效」变成无人可见的黑洞 ⇒ 与真值源
                // routing.py::_rule_triggers 同款**显式失败**。
                throw new BusinessException(ERR_ROUTING_NOT_FOUND,
                        String.format("工艺路线规则「%s」的触发类型「%s」尚未实现，无法实例化工序",
                                rule.getId(), kind),
                        422,
                        "请在「企业基础设置 → 工艺路线」停用该规则，或联系研发实现该触发类型");
            }
            // 🔴 **规则级部位限定**（issue #4962 加回；#4937 / O2 曾整块退场）：`position` 为空 /
            // NULL = **不限部位**；否则必须逐字匹配当前实例化部位。与真值源
            // `routing.py::build_route_v2` 的 `_rule_position_matches` 同款同序同判据。
            // ⚠️ 位置**必须在触发类型分派之后**：未知类型先显式失败，不因部位不匹配就静默跳过。
            if (!rulePositionMatches(rule, position)) {
                continue;
            }
            if ("insert".equals(rule.getAction())) {
                sequence = insertAfterLogical(sequence, rule.getOperation(), rule.getAfterOperation());
            } else if ("remove".equals(rule.getAction())) {
                String removed = rule.getOperation();
                sequence.removeIf(op -> Objects.equals(op, removed));
            }
            // action='factor' 不参与序列构造（#4589 起它也不再覆盖计件系数 —— 该档已无消费者，
            // 新迁移已把活跃行软删；此处保留分支语义：非 insert/remove 的动作不改序列）
        }

        List<Map<String, Object>> steps = new ArrayList<>();
        List<String> missing = new ArrayList<>();
        int seq = 1;
        for (String logicalName : sequence) {
            // 🔴 **唯一保留的判据 = 名字形态**（issue #4609，P0 静默丢工序）：
            // 主线里存着**变体名 / 别名**（`精裁-布`，老 bundle / 界面加过工序的存量路线）时，
            // 实例化按逻辑名建键永远查不到 ⇒ **必须可见**：进 `missing_operations`
            // （调用方据此 fail-closed 并指名报缺），**不得**静默滤掉。
            // 判据复用**同一份**归一表（`normalizeOperationName`，不新造第二份）。
            // ⛔ 原「键不存在 ⇒ 静默 continue」与「applicable=false ⇒ 静默 continue」两道闸
            // 已随「部位适用性」退场（issue #4937）—— 名字本身就是逻辑工序名 ⇔ 归一后等于自己
            // ⇒ 直接按逻辑名建键（不再是「没登记适用性就不猜」）。
            if (!logicalName.equals(productionOperationQueryService.normalizeOperationName(logicalName))) {
                missing.add(logicalName);
                continue;
            }
            String variant = productionOperationQueryService.variantNameOf(logicalName, position, catalog);
            Map<String, Object> meta = variant == null ? null : catalog.get(variant);
            if (meta == null) {
                missing.add(logicalName);
                continue;
            }
            Map<String, Object> step = new LinkedHashMap<>();
            step.put("seq", seq++);
            step.put("operation", variant);
            // 工序显示名的读时派生（issue #4621）：`logical_name` + `position` 供 **web 界面**渲染
            // 「逻辑名 · 部位」；`operation` 是**工人端快照名**（变体名），**web 界面不得渲染该键**。
            step.put("logical_name", logicalName);
            step.put("position", ProductionOperationQueryService.displayPosition(variant, position));
            step.put("group", meta.get("group"));
            step.put("unit", meta.get("unit"));
            // 🔴 未定价（格价 NULL）**不得**回落工序库行价（issue #4696，P1）：工序库行价是
            // `NOT NULL DEFAULT 0` ⇒ 回落就把「未定价」变成「真 0 元」（工人白干且无人知道），
            // 且与「显式定价 0 元」不可区分。读面（V88 `GET /operation-layers`）不回落 ⇒
            // 实例化侧必须同口径：格价 NULL ⇒ 落 NULL（未定价），格价 0 ⇒ 有价 0 元。
            step.put("unit_price", priceByLogical.get(logicalName));
            // 🔴 `is_must_finish` **不再带出**（#4961）：路线步骤里去掉该键 ⇒ 实例化 payload 也没有它
            // （`buildPositionPayload` 逐字从中带出；列保留为历史载体）。
            step.put("is_start_marker", meta.get("is_start_marker"));
            step.put("scope", meta.get("scope"));
            steps.add(step);
        }

        Map<String, Object> route = new LinkedHashMap<>();
        route.put("route_template_id", template.getId());
        route.put("route_template_name", template.getName());
        route.put("curtain_type", position);
        route.put("craft", craft);
        route.put("operation_count", steps.size());
        route.put("missing_operations", missing);
        route.put("operations", steps);
        return route;
    }


    /**
     * 回落默认模板时用来实例化的**部位**：优先 {@link #DEFAULT_CURTAIN_TYPE}（V54 起的事实默认、
     * 也是旧结构回落目标的部位维），否则取模板声明的第一个部位。
     *
     * <p>为什么不直接用订单派生的部位：库里可能根本没有那个部位的价目/工序行（如商家自建信号
     * 「罗马帘」）⇒ 适用性矩阵会把整条主线滤空 ⇒ **零工序的加工单**（工人扫不了码、也不报错）。</p>
     */
    static String defaultPositionOf(ProductionRouteTemplate template) {
        List<String> positions = stringList(template.getPositions());
        if (positions.contains(DEFAULT_CURTAIN_TYPE)) {
            return DEFAULT_CURTAIN_TYPE;
        }
        return positions.isEmpty() ? DEFAULT_CURTAIN_TYPE : positions.get(0);
    }


    /** 把 {@code operation} 插到 {@code after} 之后（锚点不在序列中 ⇒ 追加末尾，同 {@code _insert_after}）。
     *
     * <p><b>唯一性 = 取代（issue #4577）</b>：用户裁定 2026-09-19 原话「**工序需要保证唯一**，比如工艺
     * 带了绑带，特殊选项又选择余料做绑带，得用**特殊选项中的余料做绑带替代绑带这个工序**，余料做绑带的
     * 目标工序也是绑带就能替换，**需要有这个前提**」。⇒ 判据 = <b>目标工序名相同</b>（前提）；
     * 语义 = <b>先移除序列里已有的该工序，再按本条规则的锚点插入</b>（<b>取代</b>，不是"跳过"）——
     * 跳过会让位置停留在<b>先应用</b>那条规则（可能是工艺的锚点），而商家选特殊选项的意图是
     * 「按这个选项的工序来」。结果 = 该工序在序列里<b>恰好出现一次</b>（盲插会让工人按两遍单价拿钱，
     * 同族事故 #4523）。规则应用顺序仍由 {@code priority} 决定（顺序语义未动）。</p> */
    static List<String> insertAfterLogical(List<String> route, String operation, String after) {
        route.removeIf(op -> Objects.equals(op, operation));
        int idx = after == null ? -1 : route.indexOf(after);
        if (idx < 0) {
            route.add(operation);
            return route;
        }
        route.add(idx + 1, operation);
        return route;
    }


    /** JSONB 列归一化为 {@code List<String>}（{@code JacksonTypeHandler} 反序列化后可能是 {@code List<?>}）。 */
    static List<String> stringList(Object raw) {
        List<String> names = new ArrayList<>();
        if (raw instanceof List<?> list) {
            for (Object item : list) {
                if (item != null) {
                    names.add(String.valueOf(item));
                }
            }
        }
        return names;
    }


    /**
     * 路线键（`curtain_type` + `craft`）+ 来源：**显式字段 &gt; 受控来源 &gt; 存量单信号兜底**
     * （issue #4354 落码「直读优先」，issue #4362 把「显式字段」升级为 {@code order_items} 的
     * craft spec 列，issue #4452 把第 2 层从「`contains` 猜文本」换成**受控来源**）。
     *
     * <p><b>取法优先级（三层，issue #4452 冻结口径）</b>：</p>
     * <ol>
     *   <li><b>显式字段</b>（最高）—— 订单行写下的部位/工艺。载体有两者、**同源**：
     *       {@code order_items.curtain_type} / {@code craft} <b>列</b>（V63 / issue #4362，结构化落库）
     *       与 {@code processing_info} 顶层的同键（issue #4354 起的旧载体，存量单）；
     *       列非空时在 {@link #buildSnapshot} 里覆盖同键 ⇒ 两维都在 ⇒ 来源 {@code direct}
     *       （**此时全程不读** {@code production_route_signals}）；</li>
     *   <li><b>受控来源</b>（第 2 层，issue #4452 新增）—— 显式字段缺的那一维由**结构化字段**补齐：
     *       部位 ← {@code componentRole} 受控枚举（{@link #COMPONENT_ROLE_POSITIONS}：{@code 纱} ⇒ 纱帘，
     *       {@code 主布}/{@code 配布边} ⇒ 布帘）；工艺 ← 加工项的**显式声明**
     *       {@code processing_items.craft_hint}（{@link #craftHintOf}）。
     *       ⚠️ **不再** `contains` 加工项名 / 加工项 options —— 那些是**商家可自定义的自由文本**，
     *       把判据绑在研发改的关键词表上就是「名词解释」（{@code craft-routing-customization.md} §4 P2）；</li>
     *   <li><b>存量单信号兜底</b>（第 3 层，**两维都缺**时才轮到）—— 存量的**订单行**上没有 V63 列值
     *       也没有 {@code componentRole} / {@code craft_hint}（老数据形态），此时才读
     *       {@code production_route_signals} 兜底；信号源**只剩加工项名 / 加工项 options**
     *       （商品名与销售方式已从判据里摘掉 —— 营销文案不是结构化输入）。
     *       三层都不命中 ⇒ 两维取**该租户的默认**（部位常量 / 默认工艺，来源 {@code default}，T1）。</li>
     * </ol>
     * <p>只补齐一维 ⇒ 来源 {@code partial}（补救动作 = 把另一维填进订单，或让加工项声明它）。</p>
     *
     * <p><b>信号表是「存量单兜底」，不是长期判据</b>（issue #4452）：表**不删**（存量单仍需派生），
     * 但新单两维都缺时按既有四/五态 {@code route_source} **显式标注**（{@code default}/{@code partial}）
     * 并由 {@code GET /production/orders/routing-anomalies} 列出可行动清单，**不静默落默认**。</p>
     *
     * <p><b>⚠️ P2b：缺 {@code craft} 取「商户级默认工艺」，不再写死常量（issue #4459 §1②）</b>：
     * {@code production_crafts} 的 {@code is_default} 行是**商家可配**的（改默认工艺 ⇒ 后续订单
     * 插入的工序与计件系数随之变）；该租户**没有**默认工艺 ⇒ 返回 {@code null}，
     * 由 {@link #resolveRoute} 走 T3 fail-closed（错误码 + suggestion 说清「商家面无默认工艺维护入口」），
     * **绝不**静默取常量 {@code 韩褶}（商户只做打孔时会插错工序 + 算错计件系数 = 错发工资）。</p>
     *
     * <p><b>⚠️ 派生路径**不退场**（用户裁定 2026-09-19「部位不是必填的」）</b>：S1 的字段全部可空
     * ⇒「没填部位/工艺的单」永远存在 ⇒ 第 2/3 层与信号映射表是**长期**兜底，**不是**临时桥。
     * 代码注释里旧表述「待订单侧补字段后本方法连同信号表一起退场」**已作废**，不得再按它写回。
     * 第 3 层同样**不是**可删项：它是「商家自定义加工项」的兜底面（issue #4308 已做成商家可配）。</p>
     *
     * <p><b>⚠️ 信号表已降级为「存量单兜底」（issue #4452）</b>：它**只在两维都缺**时才被读
     * ⇒ 新单（带 V63 列值 / {@code componentRole} / {@code craft_hint} 任一）**全程不读**它。
     * 表**不删**（存量单仍需派生），但不再是「长期判据」。</p>
     *
     * <p><b>为什么不校验显式字段的值</b>：它是订单侧已落库的真值，Java 只读不猜、不归一
     * （错值/库里无该部位模板 ⇒ 由 {@link #resolveRoute} 的 T2 显式落 {@code missing_route}
     * 并记 incident 日志，绝不静默）。空白键（{@code " "}）视为**缺键**（{@code str} 会 trim）——
     * 否则会造出「{@code  ×韩褶}」这种不存在的键。</p>
     *
     * <p><b>来源四态（V60，issue #4308 冻结口径；落 {@code processing_orders.route_source}）</b>：
     * {@code derived} = 两维都由库中信号映射命中（**只剩存量单**会走到这里）；
     * {@code partial} = 只补齐一维；{@code default} = 两维全不命中（T1）。
     * **本方法只产出这三态 + issue #4354 新增的 {@code direct}**；
     * 第五态 {@code missing_route}（T2 = 部位无模板而回落默认模板）由 {@link #resolveRoute}
     * 在回落时引入 —— 否则「回落过」与「本来就没派生」在数据上长得一模一样，
     * 而前者是错配高发形态。</p>
     */
    RouteKey deriveRouteKey(Map<String, Object> entry, Long tenantId) {
        // ① 两维都直读 ⇒ direct（**不查**信号映射表：订单侧的真值优先于任何派生）
        String directCurtainType = str(entry.get("curtainType"));
        String directCraft = str(entry.get("craft"));
        // ⓪ 售卖形态 = **布料** ⇒ 部位维直读为 `布料`（第 4 个部位），**不走**部位派生链
        //    （issue #4529）：`componentRole` 受控枚举与存量信号表都是「窗帘部位」的口径
        //    （主布/配布边/纱、布/纱/帘头…），用在布料单上必然错配成窗帘路线。
        //    工艺维对布料单无意义（布料主线只有 配料/打包）⇒ 仍取该租户默认工艺，仅为满足
        //    T3 的既有护栏（缺 `craft` 且无默认工艺 ⇒ fail-closed，本单不放宽该护栏）。
        if (isFabricSaleLine(entry)) {
            String fabricCraft = directCraft != null
                    ? directCraft : productionOperationQueryService.defaultCraft(tenantId);
            return new RouteKey(FABRIC_POSITION, fabricCraft, "direct");
        }
        if (directCurtainType != null && directCraft != null) {
            return new RouteKey(directCurtainType, directCraft, "direct");
        }
        // ② 受控来源补齐缺的那一维（issue #4452）：部位 ← componentRole 枚举；工艺 ← 加工项声明列。
        String curtainType = directCurtainType != null ? directCurtainType : positionOfComponentRole(entry);
        // 加工项的工艺声明**无条件校验**（用户裁定 2026-09-19「工艺单值护栏」）：不能等
        // 「显式 craft 为空」才读它 —— 下单页会把派生出的 craft 显式写回（route_source=direct），
        // 那时本行会短路 ⇒ 护栏失效、两个不同声明被静默取第一个。
        String declaredCraft = craftHintOf(entry);
        String craft = directCraft != null ? directCraft : declaredCraft;
        // ③ 两维都缺 ⇒ **存量单**（老数据没有 V63 列 / componentRole / craft_hint）才读信号表兜底。
        //    信号源只剩加工项名/options（商品名与销售方式已摘掉，见 signals()）。
        //    ⚠️ 本分支的**条件**就是「不读信号表」的判据：新单只要给出一维，本行不执行。
        if (curtainType == null && craft == null) {
            List<ProductionRouteSignal> mappings = productionOperationQueryService.routeSignals(tenantId);
            if (!mappings.isEmpty()) {
                List<String> signals = signals(entry);
                curtainType = firstSignalMatch(signals, mappings, true);
                craft = firstSignalMatch(signals, mappings, false);
            }
        }
        // ⚠️ 来源必须在**默认值补齐之前**算：补齐后 `craft != null` 恒真 ⇒ T1 会被误判成 partial
        // （「没人派生过」与「只补齐一维」是两种不同的补救动作）。
        String source;
        if (curtainType != null && craft != null) {
            // 有一维来自订单行显式字段/受控来源 ⇒ 补救动作 = 把另一维填进订单
            // （与「两维都由信号表派生」的 derived 区分开）
            source = directCurtainType != null || directCraft != null ? "partial" : "derived";
        } else if (curtainType != null || craft != null) {
            source = "partial";
        } else {
            source = "default";
        }
        // 缺 `craft` 的兜底 = **该租户的默认工艺**（商家可配，issue #4459 §1②）。
        // 该租户没有默认工艺 ⇒ 保持 null，由 resolveRoute 走 T3 fail-closed（**不写死常量 韩褶**）。
        if (craft == null) {
            craft = productionOperationQueryService.defaultCraft(tenantId);
        }
        return new RouteKey(curtainType == null ? DEFAULT_CURTAIN_TYPE : curtainType, craft, source);
    }


    /**
     * 部位维的**受控来源**（issue #4452）：{@code componentRole} 受控枚举 → 部位名。
     *
     * <p>受控枚举值见 {@link #COMPONENT_ROLE_POSITIONS}（写侧 {@code order_create.py} 的 enum：
     * 主布 / 配布边 / 纱）。**未知取值返回 null**（不猜、不默认成布帘）—— 该维按缺维处理，
     * 由 {@code route_source} 显式标注并在异常订单清单里可见。</p>
     */
    static String positionOfComponentRole(Map<String, Object> entry) {
        String role = str(entry.get("componentRole"));
        // 缺键（存量单）/ 未知取值 ⇒ null（**不猜**）：Map.of 也不接受 null 键
        return role == null ? null : COMPONENT_ROLE_POSITIONS.get(role);
    }


    /**
     * 订单侧可派生信号，**顺序即推导链的第 2/3 层**（命中即止，外层先说话）：
     * <ol>
     *   <li><b>加工项推导</b>（issue #4362 冻结的第 2 层）：加工项**名**（加工项目录里工序名自带
     * **存量单兜底**信号（issue #4452 起**只剩加工项名 / 加工项 options**，命中即止）：
     * <ol>
     *   <li>加工项**名**（老订单行上工序名自带部位/工艺，如「韩褶-布」「打孔-纱」「帘头制作」）；</li>
     *   <li>加工项 **options**（如「四爪钩」）。</li>
     * </ol>
     *
     * <p>⚠️ <b>商品名与销售方式**已摘掉**</b>（issue #4452 交付判据 4）：它们是**营销文案**，
     * 不是结构化输入 —— 旧实现去商品名里 {@code contains '纱'} 判部位，正是本单要消灭的
     * 「名词解释」。同时「加工项比商品名权威」这个相对次序判据随之作废（商品名不再参与）。</p>
     *
     * <p>本方法**只在两维都缺时**被调用（见 {@link #deriveRouteKey}）⇒ 它不再参与新单的路线键。</p>
     */
    @SuppressWarnings("unchecked")
    static List<String> signals(Map<String, Object> entry) {
        List<String> signals = new ArrayList<>();
        if (entry.get("processingItems") instanceof List<?> items) {
            for (Object raw : items) {
                if (raw instanceof Map<?, ?> item) {
                    String name = str(((Map<String, Object>) item).get("name"));
                    if (name != null) {
                        signals.add(name);
                    }
                }
            }
            for (Object raw : items) {
                if (raw instanceof Map<?, ?> item && item.get("options") instanceof List<?> options) {
                    for (Object option : options) {
                        if (option != null) {
                            signals.add(String.valueOf(option));
                        }
                    }
                }
            }
        }
        return signals;
    }




    /**
     * 第一个命中的映射值（信号**外层**、映射行**内层** —— 与迁移前的常量表扫描逐字同序：
     * 更权威的信号先说话；同一信号内按 {@code priority} 取位次最靠前的那条）。
     *
     * @param curtain true = 只扫帘种行（{@code curtain_type} 非空），false = 只扫工艺行
     */
    static String firstSignalMatch(List<String> signals, List<ProductionRouteSignal> mappings, boolean curtain) {
        for (String signal : signals) {
            for (ProductionRouteSignal mapping : mappings) {
                String target = curtain ? mapping.getCurtainType() : mapping.getCraft();
                String keyword = mapping.getSignal();
                if (target != null && keyword != null && signal.contains(keyword)) {
                    return target;
                }
            }
        }
        return null;
    }


    /**
     * 路线键 + 来源（{@code direct} 两维直读订单工艺规格 / {@code derived} 两维都由信号映射命中 /
     * {@code partial} 只命中或只直读一维 / {@code default} 全不命中 —— **本 record 只产出这四态**，
     * 第五态 {@code missing_route} 由 {@link #resolveRoute} 在「键在库中无路线而回落」时引入）。
     */
    record RouteKey(String curtainType, String craft, String source) {
    }


    /**
     * 一次路线解析的结果：**实际使用**的路线 + **派生出来想用**的键 + 来源（V60，issue #4308）。
     * 三者必须同源返回 —— 分两次算必然漂移（「用的路线」与「记下来的键」对不上就白记了）。
     *
     * @param routeKey          实际使用的路线键（= 派生出来的那个；T1 时 = 布帘×该租户默认工艺）
     * @param routeRequestedKey 想用的路线键（派生/直读出来的那个）；两维全不命中（source=default）时 null
     * @param routeSource       direct / derived / partial / missing_route / default
     */
    record RouteResolution(Map<String, Object> route, String routeKey,
                                   String routeRequestedKey, String routeSource) {
    }
}
