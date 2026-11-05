package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.BatchStockViews;
import com.migao.admin.dto.MaterialLabels;
import com.migao.admin.dto.ProcessingOrderGenerateRequest;
import com.migao.admin.dto.ProcessingOrderGenerateRequest.BatchAssignment;
import com.migao.admin.dto.ProcessingOrderResponse;
import com.migao.admin.dto.ProcessingOrderUpdateRequest;
import com.migao.admin.dto.ProductionPoolViews;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.entity.ProductionRouteRule;
import com.migao.admin.entity.ProductionRouteSignal;
import com.migao.admin.entity.ProductionRouteTemplate;
import com.migao.admin.entity.Supplier;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.SupplierMapper;
import com.migao.admin.time.BusinessClock;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Duration;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.temporal.ChronoUnit;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.concurrent.ThreadLocalRandom;
import static com.migao.admin.service.ProcessingOrderService.*;

/**
 * 加工单**条件工序编织**单元（issue #8725 第二档切片，从 {@link ProcessingOrderService} **纯搬运**）。
 *
 * <p><b>单一职责</b>：特殊选项 / 加工项名 ⇒ 条件工序规则的触发判定与插序、逻辑锚点定位、seq 重排。
 * 全是**纯函数**（入参进、出参出，无状态、不写库、不发请求）⇒ 本类是静态工具，不需要装配。</p>
 *
 * <p>搬运口径：方法体、注释、异常码、日志文案**一字未改**。</p>
 */
class ProcessingOperationWeaver {

    private final ProductionOperationQueryService productionOperationQueryService;

    ProcessingOperationWeaver(ProductionOperationQueryService productionOperationQueryService) {
        this.productionOperationQueryService = productionOperationQueryService;
    }

    /** 日志类别**必须**仍是 {@code ProcessingOrderService}：既有判据与运维告警按该 logger
     * 取事件（{@code ProcessingOrderRouteSourceTest} 就挂在它上面）—— 换类别 = 可观测面回退。*/
    private static final org.slf4j.Logger log =
            org.slf4j.LoggerFactory.getLogger(ProcessingOrderService.class);


    // ============================================================ 特殊选项（issue #4230）

    /**
     * 本单携带的特殊选项（{@code processingInfo.specialOptions: string[]}，v1a 新增携带）。
     *
     * <p>归一化：只认字符串数组形态（前端/agent 写的就是数组），空白项丢弃、去重保序 ——
     * 重复选项不得把同一道条件工序插两次（插两次会让工人按两遍单价拿钱）。</p>
     */
    static List<String> specialOptions(Map<String, Object> entry) {
        Object raw = entry.get("specialOptions");
        if (!(raw instanceof List<?> list)) {
            return List.of();
        }
        List<String> options = new ArrayList<>(list.size());
        for (Object item : list) {
            String option = str(item);
            if (option != null && !options.contains(option)) {
                options.add(option);
            }
        }
        return options;
    }


    /**
     * 本单该行携带的**加工项名**（{@code processingInfo.processingItems[].name}，去重保序）。
     *
     * <p>`processing_item` 规则的触发键（issue #4577，用户裁定「加工项也触发工序」）。
     * 与 {@link #specialOptions} 同款归一：只认 Map 元素 + 非空名字，缺失/脏形态 ⇒ 不命中（不猜）。
     * 与真值源 {@code routing.py::_rule_triggers} 的 {@code position["processing_items"]} 同口径。</p>
     */
    static List<String> processingItemNames(Map<String, Object> entry) {
        if (!(entry.get("processingItems") instanceof List<?> items)) {
            return List.of();
        }
        List<String> names = new ArrayList<>(items.size());
        for (Object raw : items) {
            if (raw instanceof Map<?, ?> item) {
                String name = str(item.get("name"));
                if (name != null && !names.contains(name)) {
                    names.add(name);
                }
            }
        }
        return names;
    }


    /**
     * 条件工序规则的触发判定（issue #4577）：**精确相等**，与 {@code buildRoute} /
     * {@code routing.py::_rule_triggers} 同口径。
     *
     * <p>{@code option} ⇒ 触发键 = 本单特殊选项名；{@code processing_item} ⇒ 触发键 = 该行
     * {@code processingInfo.processingItems[].name}（**不得**用 {@code contains} —— 错一个字就静默失效；
     * {@code contains} 只存在于存量信号兜底 {@code firstSignalMatch}，不在此处引入第二处）。</p>
     */
    static boolean conditionalRuleTriggers(ProductionRouteRule rule, List<String> options,
                                                   List<String> processingItems) {
        String kind = rule.getTriggerKind();
        if ("craft".equals(kind)) {
            // `craft` 维的 insert/remove **由 `buildRoute` 统一处理**（它先跑，序列已定稿）；
            // 本方法只补「按**订单行**触发」的那两类（特殊选项 / 加工项）⇒ craft 规则在这里
            // 返回 false 是「**不重复插入**」，**不是**「未实现」（别把它挪到下面的显式失败里：
            // 那会让每一张单在实例化时 422）。
            return false;
        }
        if ("option".equals(kind)) {
            return options.contains(rule.getTriggerValue());
        }
        if ("processing_item".equals(kind)) {
            return processingItems.contains(rule.getTriggerValue());
        }
        if (TRIGGER_KIND_SALES_FORM.equals(kind)) {
            // 售卖方式规则由 `buildRoute` 统一处理（与 `craft` 同款：这里返回 false = 不重复插入，
            // **不是**「未实现」—— 挪到下面的显式失败会让每张布料单实例化时 422）。
            return false;
        }
        if (TRIGGER_KIND_POSITION.equals(kind)) {
            // 部位维（issue #4962）：`trigger_value` = 部位名，写面把它**镜像**进 `position` 列
            // ⇒ 「这条规则限哪个部位」只有**一处**判据（{@link #rulePositionMatches}，见两个调用方的
            // 统一筛选）。此处恒 true 只表示「该触发类型已实现」，**不是**「跳过筛选」。
            return true;
        }
        // ⛔ 未知 / 未实现的触发类型 ⇒ **显式失败**，不静默跳过（issue #4962）：
        // 返回 false 会让「规则已落库但永不生效」变成无人可见的黑洞
        // （与真值源 `routing.py::_rule_triggers` 的 `raise ValueError` 同款纪律）。
        throw new BusinessException(ERR_ROUTING_NOT_FOUND,
                String.format("条件工序规则「%s」的触发类型「%s」尚未实现，无法实例化工序", rule.getId(), kind),
                422,
                "请在「企业基础设置 → 工艺路线」停用该规则，或联系研发实现该触发类型");
    }


    /**
     * **规则级部位限定**（issue #4962 加回；此前由 issue #4937 / O2 整块退场）。
     *
     * <p>{@code position} 为空 / {@code NULL} = **不限部位**；否则必须**逐字**匹配当前实例化部位。
     * 与真值源 {@code app/production/routing.py::_rule_position_matches} **同款同序同判据** ——
     * 两侧漂移会让同一张单在 Java 与 Python 上得到不同的工序序列（车间按两套顺序干）。</p>
     *
     * <p>调用点**必须在触发类型分派之后**：未知类型要先显式失败，不能因为部位不匹配就静默跳过。</p>
     */
    static boolean rulePositionMatches(ProductionRouteRule rule, String position) {
        String limit = rule.getPosition();
        return limit == null || limit.isEmpty() || Objects.equals(limit, position);
    }


    /**
     * 插入条件工序（issue #4230 验收判据 1；P2b 改读 {@code production_route_rules}）。
     *
     * <p>规则行的 {@code action='insert'} + {@code trigger_kind ∈ {option, processing_item}} ⇒ 把
     * {@code operation} 插到 {@code after_operation} 之后（issue #4577 起加工项也是触发键）。
     * 与真值源
     * {@code routing.py::build_route_v2} + {@code _insert_after} 同口径：
     * 锚点不在该部位路线中 ⇒ **追加到末尾**；同一锚点上的多个插入按 {@code (priority, id)}
     * 依次插在锚点之后 ⇒ 后插的在前（与 Python 的 {@code insert(idx+1, …)} 逐字同款）。</p>
     *
     * <p>工序元数据（分组/单位/单价/必完/开始标记）**逐字取库**（经
     * {@code variantNameOf} 把逻辑名换成该租户库里的变体名）；条件工序在工序库无活跃行 ⇒
     * fail-closed（{@link #ERR_OPERATION_NOT_FOUND}）—— 静默跳过会让「勾了却没加工序」
     * 在数据上消失，那正是本单要治的「设计过但从未接线」形态。</p>
     *
     * <p><b>唯一性 = 取代（issue #4577）</b>：目标逻辑工序**已在序列里** ⇒ <b>先移除旧位置、再按本条
     * 规则的锚点插入</b>（<b>取代</b>，不是"跳过"—— 跳过会让位置停留在先应用那条规则，而商家选特殊
     * 选项的意图是「按这个选项的工序来」；口径来源 = 用户 2026-09-19 原话「工序需要保证唯一…用特殊
     * 选项中的余料做绑带替代绑带这个工序…需要有这个前提」，前提 = **目标工序名相同**）。
     * 结果 = 该工序在序列里**恰好一行**（盲插会让工人按两遍/三遍单价拿钱，同族事故 #4523）。
     * 规则应用顺序仍由 {@code priority} 决定（特殊选项 110~260 > 工艺 10~100 ⇒ 特殊选项自然覆盖工艺）。</p>
     */
    void insertConditionalOperations(List<Map<String, Object>> operations, List<String> options,
                                             List<String> processingItems, List<ProductionRouteRule> rules,
                                             Long tenantId, Map<String, Object> entry,
                                             Map<String, Map<String, Object>> catalog,
                                             String position) {
        List<ProductionRouteRule> applicable = new ArrayList<>();
        for (ProductionRouteRule rule : rules) {
            if (!"insert".equals(rule.getAction())
                    || !conditionalRuleTriggers(rule, options, processingItems)) {
                continue;
            }
            // 🔴 **规则级部位限定**（issue #4962 加回；#4937 / O2 曾整块退场）：`position` 为空 /
            // NULL = **不限部位**；否则必须逐字匹配当前实例化部位。与真值源
            // `routing.py::build_route_v2` 的 `_rule_position_matches` 同款同序同判据。
            // ⚠️ 位置**必须在触发判定之后**（上面那行已经先跑）：未知触发类型要显式失败，
            // 不能因为部位不匹配就静默跳过（「规则落库但永不生效」的黑洞）。
            if (!rulePositionMatches(rule, position)) {
                continue;
            }
            applicable.add(rule);
        }
        if (applicable.isEmpty()) {
            return; // 选项未登记条件工序（纯系数选项 / 显式不计件选项）⇒ 路线不变，不是错误
        }
        // 读取侧已按 (priority, id) 排好；此处再显式排一次，不依赖调用方（确定性的承重点）
        applicable.sort(Comparator.comparing(
                        (ProductionRouteRule r) -> r.getPriority() == null ? 0 : r.getPriority())
                .thenComparing(r -> r.getId() == null ? "" : r.getId()));
        List<String> missing = new ArrayList<>();
        for (ProductionRouteRule rule : applicable) {
            String logicalName = rule.getOperation();
            String operationName = productionOperationQueryService.variantNameOf(logicalName, position, catalog);
            Map<String, Object> meta = operationName == null ? null : catalog.get(operationName);
            if (meta == null) {
                // ⚠️ 只报**逻辑名**，**不得**拼期望的库内变体名（issue #4647 / D3(b)）：该 hint 经
                // `message` / `suggestion` 进 422 响应体（接口响应可见），而变体名（`拼1次-布`）是
                // 工人端快照名 —— 拼进去就是同一处泄漏换了个出口（改前实测日志：
                // `缺工序=[拼1次（库中缺变体 拼1次-布 / 布拼1次 / 布帘拼1次 / 拼1次）]`）。
                // 可行动性靠**说清缺什么 + 去哪儿补**（部位在 `position` 里，已由外层日志/提示给出）。
                missing.add(logicalName + "（该工序在「" + position + "」部位缺库行 / 未建矩阵行）");
                continue;
            }
            Map<String, Object> operation = new LinkedHashMap<>();
            // ⚠️ `operation` = **工人端快照名**（变体名）：**web 界面不得渲染该键**（issue #4621）
            operation.put("operation", operationName);
            // 显示名派生键：规则里的 `operation` **就是逻辑名**（`production_route_rules.operation`
            // 与 OPERATION_LOGICAL_NAMES 的值域一致）⇒ 逐字带出，不再归一一次
            operation.put("logical_name", logicalName);
            operation.put("position", ProductionOperationQueryService.displayPosition(operationName, position));
            operation.putAll(meta);
            // 唯一性 = 取代（issue #4577）：目标工序已在序列里 ⇒ 先移除旧位置、再按本条规则的锚点插入
            operations.removeIf(existing -> Objects.equals(str(existing.get("operation")), operationName));
            int anchor = indexOfLogicalOperation(operations, rule.getAfterOperation());
            if (anchor < 0) {
                log.info("特殊选项「{}」的锚点工序「{}」不在该部位路线中，条件工序「{}」追加到末尾: productName={}",
                        rule.getTriggerValue(), rule.getAfterOperation(), operationName, entry.get("productName"));
                operations.add(operation);
            } else {
                operations.add(anchor + 1, operation);
            }
        }
        if (!missing.isEmpty()) {
            log.error("{} 特殊选项引用的条件工序在工序库无活跃行，生成加工单中止: tenantId={}, 缺工序={}, productName={}",
                    INCIDENT_ROUTING_UNRESOLVED, tenantId, missing, entry.get("productName"));
            throw new BusinessException(ERR_OPERATION_NOT_FOUND,
                    String.format("特殊选项引用的条件工序 %s 在工序库中不存在，无法实例化工序", missing),
                    422,
                    String.format("请在工序库补上 %s（或停用引用它的特殊选项映射）",
                            String.join("、", missing)));
        }
    }


    /**
     * 锚点工序在**实例序列**中的下标；不在 ⇒ -1（调用方按真值源口径追加到末尾）。
     *
     * <p>锚点是**逻辑名**（规则表的 {@code after_operation}），而实例里的工序名是**变体名**
     * （{@code 精裁-布}）⇒ 比较前先把实例名归一为逻辑名（{@code normalizeOperationName}）。
     * 直接比变体名 ⇒ 锚点永远找不到 ⇒ 条件工序**静默全部追加到末尾**（顺序错 = 车间按错顺序干）。</p>
     */
    int indexOfLogicalOperation(List<Map<String, Object>> operations, String logicalAnchor) {
        if (logicalAnchor == null) {
            return -1;
        }
        for (int i = 0; i < operations.size(); i++) {
            String name = operations.get(i).get("operation") == null
                    ? null : String.valueOf(operations.get(i).get("operation"));
            if (Objects.equals(productionOperationQueryService.normalizeOperationName(name), logicalAnchor)) {
                return i;
            }
        }
        return -1;
    }


    /**
     * 重排部位内序号（1..N）。
     *
     * <p>为什么必须重排：库路线的 seq 只覆盖**基准**工序，条件工序插进来后原序号会重复/断档；
     * 而 {@code seq} 是页面排序与「默认给下一道待做」派生的**唯一**顺序依据 ⇒ 序号重复/断档 =
     * 顺序显示/派生错。真值源同款：
     * {@code routing.py::instance_operations} 在插完条件工序后 `enumerate(route, start=1)`。</p>
     *
     * <p>⚠️ 改判（issue #4694，2026-09-20）：seq **不再是**报工顺序闸门的判据 —— 用户裁定
     * 「系统无需管理生产顺序」，原 {@code ProductionService.assertPredecessorsDone} 已删除
     * （报工不再按 seq 校验前道是否完成）。</p>
     *
     * <p>无特殊选项时结果与库路线逐值相同（路线 seq 本来就是 1..N）⇒ 不回归。</p>
     */
    static void renumberSeq(List<Map<String, Object>> operations) {
        for (int i = 0; i < operations.size(); i++) {
            operations.get(i).put("seq", i + 1);
        }
    }
}
