package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.ProcessingOrderGenerateRequest;
import com.migao.admin.dto.ProcessingOrderResponse;
import com.migao.admin.dto.ProcessingOrderUpdateRequest;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProductionOptionFactor;
import com.migao.admin.entity.ProductionOptionRouting;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.concurrent.ThreadLocalRandom;

/**
 * 加工单服务（issue #3340，设计文档 docs/design/processing-order-design.md）
 *
 * 核心职责：
 * 1. 生成加工单（快照固化五要素 + options，不含销售价）+ 订单 confirmed→producing 联动；
 * 2. 加工单状态机（generated→issued→in_processing→completed | cancelled），非法迁移拒绝；
 * 3. 取消联动（generated 取消 → 订单 producing→confirmed 回退）；
 * 4. 订单侧联动（shipped 守卫 / 订单取消自动作废）由 OrderService 完成。
 *
 * <h2>工序来源（issue #4116，用户裁定「现在就切」，2026-09-18）</h2>
 * 生成加工单时的工序实例化读**工序库**：{@code production_routings}（部位×工艺 → 基准工序序列）
 * + {@code production_operations}（分组/单位/单价/is_must_finish/is_start_marker），
 * 经 {@link ProductionOperationQueryService#findRouting} 读出。
 * 加工项目录（快照的 {@code processingItems}）**不再是**工序真值源。
 * 取不到路线/工序 ⇒ fail-closed 中止生成（{@link #ERR_ROUTING_NOT_FOUND} /
 * {@link #ERR_OPERATION_NOT_FOUND} + {@link #INCIDENT_ROUTING_UNRESOLVED} 日志），**不回退**旧路径。
 *
 * <h2>部位语义（如实登记，尚未对齐）</h2>
 * {@code processing_position_operations.position_name} 取「加工产物名[+色号]」（如「布艺遮光帘A 米白」），
 * 因为**订单侧没有部位/帘种字段** —— 而工序库的路线是**按部位**索引的（布帘/纱帘/帘头）。
 * ⇒ 本包只能在实例化时**派生**部位（见 {@link #deriveRouteKey}），派生不中就落默认路线 布帘×韩褶。
 * **待订单侧补「部位/帘种」字段后再对齐**（届时改为直读 + 删掉关键字派生表）——
 * 在此之前，部位名与路线键**不是**同一个语义层，不得把前者当成后者的真值。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProcessingOrderService {

    private final ProcessingOrderMapper processingOrderMapper;
    private final OrderMapper orderMapper;
    private final OrderItemMapper orderItemMapper;
    private final ProcessingItemMapper processingItemMapper;
    private final OrderService orderService;
    private final ObjectMapper objectMapper;
    private final ProductionService productionService;
    /** 工序来源（issue #4116 切库）：工序实例的工序/单位/单价/必完标记全部读它。 */
    private final ProductionOperationQueryService productionOperationQueryService;
    /** 应做数量来源（issue #4208 接线）：算料引擎在 ai-agent，Java 侧只问不猜。 */
    private final ProductionOperationQtyClient productionOperationQtyClient;

    /**
     * 工序库查不到「部位×工艺」路线时的错误码（fail-closed）。
     * 可见位置：① 生成加工单的响应 `GenerateResult.message`（`success=false` 的原文）；
     * ② 服务层日志 `INCIDENT_PRODUCTION_ROUTING_UNRESOLVED`（incident 级，按此串检索）。
     */
    public static final String ERR_ROUTING_NOT_FOUND = "PRODUCTION_ROUTING_NOT_FOUND";

    /**
     * 路线引用的工序在工序库无活跃行时的错误码（fail-closed）。
     * 可见位置同 {@link #ERR_ROUTING_NOT_FOUND}。
     */
    public static final String ERR_OPERATION_NOT_FOUND = "PRODUCTION_OPERATION_NOT_FOUND";

    /** 切库失败的 incident 日志标记：`grep INCIDENT_PRODUCTION_ROUTING_UNRESOLVED` 即可捞全部中止事件。 */
    public static final String INCIDENT_ROUTING_UNRESOLVED = "INCIDENT_PRODUCTION_ROUTING_UNRESOLVED";

    /**
     * 默认路线键（派生不出 部位/工艺 时的兜底，issue #4116 用户裁定）。
     * ⚠️ 这是**路线键**的兜底，不是**数据源**的兜底：默认路线同样必须来自工序库，
     * 库里连它都没有 ⇒ fail-closed 中止生成（绝不回退加工项目录）。
     */
    private static final String DEFAULT_CURTAIN_TYPE = "布帘";
    private static final String DEFAULT_CRAFT = "韩褶";

    /**
     * 部位（帘种）派生表：`信号文本含关键字 → production_routings.curtain_type`。
     * 顺序即优先级（"帘头"先于"纱"，避免「帘头纱」被判成纱帘）。
     */
    private static final String[][] CURTAIN_TYPE_KEYWORDS = {
            {"帘头", "帘头"}, {"纱", "纱帘"}, {"布", "布帘"}};

    /**
     * 工艺派生表：`信号文本含关键字 → production_routings.craft`。
     * 末项"帘头"映射到"平幔"：帘头部位在 V54 路线库里只有「帘头×平幔」一条（routing.py ROUTINGS 同口径）。
     */
    private static final String[][] CRAFT_KEYWORDS = {
            {"韩褶", "韩褶"}, {"打孔", "打孔"}, {"四爪钩", "四爪钩"}, {"四叉钩", "四爪钩"},
            {"穿杆", "穿杆"}, {"平幔", "平幔"}, {"帘头", "平幔"}};

    /**
     * 算料输入的透传白名单（键名与 ai-agent {@code routing.py} 的
     * {@code METER_KEYS/FOLD_KEYS/HOLE_KEYS/PANEL_KEYS/SET_KEYS} 同口径）：
     * 订单侧若已存算料输出就原样送过去，Java 侧**不发明数字**（见 {@link #calcInfo}）。
     */
    private static final List<String> CALC_INFO_KEYS = List.of(
            "fabric_meters", "meters", "pleat_count", "holes", "panels", "set_count", "source");

    /**
     * 「订单行数量 = 面料米数」的计价方式（{@code OrderItem.quantity} javadoc：per_meter=米数）。
     * 兼容前端展示标签「按米」（部分历史数据把标签写进了 processing_info）。
     */
    private static final Set<String> PER_METER_METHODS = Set.of("per_meter", "按米");

    /** 加工单状态机（与 OrderService.STATUS_TRANSITIONS 同模式） */    private static final Map<String, Set<String>> STATUS_TRANSITIONS = Map.of(
            "generated", Set.of("issued", "cancelled"),
            "issued", Set.of("in_processing", "cancelled"),
            "in_processing", Set.of("completed", "cancelled"),
            "completed", Set.of(),
            "cancelled", Set.of()
    );

    private static final Map<String, String> STATUS_LABELS = Map.of(
            "generated", "已生成",
            "issued", "已发加工",
            "in_processing", "加工中",
            "completed", "加工完成",
            "cancelled", "已取消"
    );

    /** 加工单号序号（JG-YYYYMMDD-XXXX） */
    private static final java.util.concurrent.atomic.AtomicInteger PO_SEQ =
            new java.util.concurrent.atomic.AtomicInteger(ThreadLocalRandom.current().nextInt(1000, 9999));

    private static final DateTimeFormatter PO_DATE_FMT = DateTimeFormatter.ofPattern("yyyyMMdd");

    // ============================================================ 生成

    /**
     * 批量生成加工单（全事务；单个失败不影响已成功项结果返回，但整体回滚）。
     * 返回逐单结果（success/processingOrderNo/message）。
     */
    @Transactional(rollbackFor = Exception.class)
    public List<GenerateResult> generate(List<String> orderIds, Long tenantId, String operator) {
        if (orderIds == null || orderIds.isEmpty()) {
            throw BusinessException.validationError("orderIds 不能为空");
        }
        List<GenerateResult> results = new ArrayList<>();
        for (String rawId : orderIds) {
            try {
                results.add(generateOne(rawId, tenantId, operator));
            } catch (BusinessException e) {
                results.add(GenerateResult.fail(rawId, e.getCode(), e.getMessage(), e.getSuggestion()));
            }
        }
        return results;
    }

    private GenerateResult generateOne(String rawId, Long tenantId, String operator) {
        Order order = resolveOrder(rawId, tenantId);
        if (order == null) {
            throw new BusinessException("ORDER_NOT_FOUND", "无法找到订单：" + rawId, 404);
        }
        // 仅已确认订单可生成加工单（pending 未付款 / 已取消不允许）
        if (!"confirmed".equals(order.getStatus())) {
            throw BusinessException.validationError(
                    String.format("订单 %s 当前状态 [%s] 不允许生成加工单，须为已确认", order.getOrderNo(), order.getStatus()));
        }
        List<OrderItem> items = loadOrderItems(order.getId(), tenantId);
        List<Map<String, Object>> snapshot = buildSnapshot(items, tenantId);
        if (snapshot.isEmpty()) {
            throw BusinessException.validationError("订单 " + order.getOrderNo() + " 无加工项，无需生成加工单");
        }
        // 幂等：同一订单最多一个非取消态加工单（DB 层另有 partial unique index 兜底）
        ProcessingOrder existing = processingOrderMapper.selectActiveByOrderId(order.getId(), tenantId);
        if (existing != null) {
            throw BusinessException.validationError(
                    "订单 " + order.getOrderNo() + " 已有加工单 " + existing.getProcessingOrderNo() + "，请勿重复生成");
        }

        // 工序实例 payload **在任何写库之前**解析（issue #4116 切库）：工序来源 = 工序库
        // （production_routings 的基准路线 + production_operations 的单位/单价/必完标记）。
        // 放在这里而不是插入之后，是因为 fail-closed 必须同时满足两件事：
        // ① 报出可行动的失败（错误码 + suggestion）；② **不落半成品** ——
        // generate() 逐单 catch BusinessException 后继续处理其余订单（异常不逸出事务边界 ⇒
        // 不会回滚），若先插加工单再解析，库为空时就会留下「有加工单、无工序、无 qr_token」
        // 的孤儿态：工人扫不了码、加工单列表看着正常，没人会发现工序库是空的。
        List<Map<String, Object>> positions = buildPositionPayload(snapshot, tenantId);

        ProcessingOrder po = ProcessingOrder.builder()
                .tenantId(tenantId)
                .orderId(order.getId())
                .processingOrderNo(generateOrderNo())
                .status("generated")
                .itemsSnapshot(snapshot)
                .templateVersion(1)
                .generatedBy(operator)
                .generatedAt(OffsetDateTime.now())
                .printCount(0)
                .deleted(0)
                .build();

        // 联动先行（验收复核 #3345 P2②）：先推进订单 confirmed→producing，再落加工单。
        // 落库失败时回退订单状态，杜绝「producing 无加工单」孤儿态；
        // 并发重复生成由 partial unique index 兜底 → 转幂等错误（P2①）。
        orderService.updateOrderStatus(order.getId(), "producing");
        try {
            processingOrderMapper.insert(po);
        } catch (org.springframework.dao.DuplicateKeyException e) {
            orderService.revertProducingToConfirmed(order.getId(), "加工单并发重复生成，订单状态回退");
            throw BusinessException.validationError(
                    "订单 " + order.getOrderNo() + " 加工单已生成（并发操作），请刷新后重试");
        } catch (Exception e) {
            try {
                orderService.revertProducingToConfirmed(order.getId(), "加工单生成失败，订单状态回退");
            } catch (Exception revertErr) {
                log.warn("加工单生成失败且状态回退失败: orderId={}, err={}", order.getId(), revertErr.getMessage());
            }
            throw e;
        }
        log.info("生成加工单: no={}, orderId={}, tenantId={}, operator={}",
                po.getProcessingOrderNo(), order.getId(), tenantId, operator);
        // 工序实例化（issue #4116，P0 断链第一环）：加工单落行后**立即**实例化工序。
        // 此前 instantiate 端点全仓零调用者 ⇒ 工序列表恒空 ⇒ qr_token 恒 null ⇒
        // 任务卡只出「二维码待生成」占位、工人扫码报工不可达。
        // 工序序列已在插入前解析完毕（见上方 positions）：库取不到 ⇒ 根本走不到这里，
        // 所以本行的失败只可能是 DB 层错误 —— 那种情况异常逸出 generateOne 并由外层逐单
        // catch 记账，同样不留「有加工单、无工序」的静默半成品（工序另可由
        // POST .../instantiate 手工补做）。
        instantiateOperations(order, po, positions, tenantId);
        return GenerateResult.ok(rawId, po.getProcessingOrderNo());
    }

    /**
     * 实例化工序（issue #4116 切库后：工序来源 = **工序库**，不再是加工项目录）。
     *
     * <p><b>工序来源（本包的核心变更）</b>：`production_routings`（部位×工艺 → 基准工序序列）
     * + `production_operations`（每道工序的分组/单位/单价/必完标记），两者都是**库里的行**，
     * 由 {@link ProductionOperationQueryService#findRouting} 读出。加工项目录（快照里的
     * `processingItems`）自此刻起**只**用于①派生路线键的信号、②加工单快照本身的展示，
     * **不再**提供工序 —— 旧的「工序 = 加工项名」路径已删除，取不到库数据时**显式失败**，
     * 不回退（回退会让「切库」变成装饰性的：旧路径还在 ⇒ 库为空也没人发现）。</p>
     *
     * <p><b>取路线判据</b>（订单侧**没有**部位/帘种字段，故必须显式定义取法）：按可派生信号
     * 匹配 `curtain_type`/`craft`，优先级 = 加工项名 &gt; 加工项 options &gt; 商品名 &gt; 销售方式，
     * 命中即止；两类信号全不命中 ⇒ 默认路线 `布帘×韩褶`（见 {@link #deriveRouteKey}）。</p>
     *
     * <p><b>`is_must_finish` / `is_start_marker` 读库</b>：取 `production_operations` 的同名列
     * （V54 种子只把「外帘装袋」标为必完）。此前实例化用「每部位**末道**工序必完」的临时口径
     * （#4131）—— 那是"库里没有种子"时代的占位，与新口径是两套语义，已删除（末道「外帘发货」
     * 在库里 `is_must_finish=false`）。</p>
     */
    private void instantiateOperations(Order order, ProcessingOrder po,
                                       List<Map<String, Object>> positions, Long tenantId) {
        if (positions.isEmpty()) {
            log.warn("加工单无可用部位派生工序，跳过自动实例化（可用手工端点补做）: no={}, orderId={}",
                    po.getProcessingOrderNo(), order.getId());
            return;
        }
        productionService.instantiate(order.getId(), Map.of("positions", positions), tenantId);
    }

    /**
     * 实例化 payload：快照行 → 部位 → **工序库**里的基准工序序列 → **算料引擎**给出的应做数量。
     *
     * <p>部位名 = 加工产物名[+色号]（同行多套据此区分）—— 见类注释「部位语义」节：
     * 订单侧尚无部位/帘种字段 ⇒ 部位**只能**落到产品名，**待订单侧补字段后再对齐**（本包不假装已对齐）。</p>
     *
     * <p><b>应做数量（qty，issue #4208）</b>：库路线只给单位/单价，不给数量；数量的唯一真值源是
     * 算料引擎（{@code routing.py::_qty_for}），由 {@link ProductionOperationQtyClient} 逐部位问取。
     * 此前退化为**该部位的订单数量**（走查实测：一张数量=3 的加工单，11 道工序全显示 3.00 ⇒
     * 「韩褶-布」显示 **3 折**）—— 那是本单要治的缺陷，**已删除该回退**：算料服务不可用 ⇒
     * {@link ProductionOperationQtyClient#ERR_OPERATION_QTY_UNAVAILABLE} fail-closed 中止生成，
     * 绝不静默用订单数量顶替。</p>
     *
     * <p><b>不落 0</b>：缺键兜底 1 由端点负责（应做 0 ⇒ 报工的 {@code done_qty ≥ qty} 恒真 ⇒ 假完工）。</p>
     *
     * <p><b>{@code qty_source}</b>（实例表新增列）：逐工序记录口径来源（键名 = 算料输出 /
     * {@code <键名>_x6} = 有依据的估算 / {@code fallback} = 真兜底），供页面与排查区分
     * 「算料输出」与「兜底」—— 兜底不再静默。</p>
     */
    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> buildPositionPayload(List<Map<String, Object>> snapshot, Long tenantId) {
        List<Map<String, Object>> positions = new ArrayList<>();
        // 与 positions **同序**：回填 qty/qty_source 时按位取，不靠部位名（同商品同色号的两行会重名）
        List<List<Map<String, Object>>> operationRows = new ArrayList<>();
        List<Map<String, Object>> request = new ArrayList<>();
        // 特殊选项映射（issue #4230）：两张表都极小，**一次取回**本租户的全部活跃行，
        // 逐部位在内存里按本单的 specialOptions 过滤 —— 避免「每个选项一次查询」的 N+1。
        List<ProductionOptionRouting> optionRoutings = productionOperationQueryService.optionRoutings(tenantId);
        List<ProductionOptionFactor> optionFactors = productionOperationQueryService.optionFactors(tenantId);
        for (Map<String, Object> entry : snapshot) {
            if (!(entry.get("processingItems") instanceof List<?>)) {
                continue;
            }
            RouteKey key = deriveRouteKey(entry);
            Map<String, Object> route = resolveRoute(key, tenantId, entry);
            List<Map<String, Object>> operations = new ArrayList<>();
            for (Map<String, Object> step : (List<Map<String, Object>>) route.get("operations")) {
                Map<String, Object> operation = new LinkedHashMap<>();
                operation.put("operation", step.get("operation"));
                // 分组/单位/单价/必完/开始标记**逐字取库**（不猜、不补默认值）
                operation.put("group", step.get("group"));
                operation.put("unit", step.get("unit"));
                operation.put("unit_price", step.get("unit_price"));
                operation.put("is_must_finish", step.get("is_must_finish"));
                operation.put("is_start_marker", step.get("is_start_marker"));
                operations.add(operation);
            }
            // 特殊选项（issue #4230）：插条件工序 → 重排 seq → 落计件系数
            List<String> options = specialOptions(entry);
            if (!options.isEmpty()) {
                insertConditionalOperations(operations, options, optionRoutings, tenantId, entry);
            }
            renumberSeq(operations);
            applyFactors(operations, options, optionFactors);
            String productName = str(entry.get("productName"));
            String colorName = str(entry.get("colorName"));
            String positionName = productName == null ? "未命名部位"
                    : (colorName == null ? productName : productName + " " + colorName);
            Map<String, Object> position = new LinkedHashMap<>();
            position.put("position_name", positionName);
            position.put("operations", operations);
            positions.add(position);
            operationRows.add(operations);
            request.add(qtyRequest(entry, positionName, operations));
        }
        if (positions.isEmpty()) {
            return positions;
        }
        fillQty(positions, operationRows, request);
        return positions;
    }

    // ============================================================ 特殊选项（issue #4230）

    /**
     * 本单携带的特殊选项（{@code processingInfo.specialOptions: string[]}，v1a 新增携带）。
     *
     * <p>归一化：只认字符串数组形态（前端/agent 写的就是数组），空白项丢弃、去重保序 ——
     * 重复选项不得把同一道条件工序插两次（插两次会让工人按两遍单价拿钱）。</p>
     */
    private static List<String> specialOptions(Map<String, Object> entry) {
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
     * 插入条件工序（issue #4230 验收判据 1）：选项 → {@code production_option_routings} →
     * 把 {@code operation_name} 插到 {@code after_operation} 之后。
     *
     * <p>与真值源 {@code routing.py::build_routing} + {@code _insert_after} 同口径：
     * 锚点不在该部位路线中 ⇒ **追加到末尾**（例：纱帘路线没有「布帘车被」，
     * 「余料做绑带/布绑带/纱绑带」就落到末尾）；同一锚点上的多个插入按 {@code sort_order}
     * 依次插在锚点之后 ⇒ 后插的在前（与 Python 的 `insert(idx+1, …)` 逐字同款）。</p>
     *
     * <p>工序元数据（分组/单位/单价/必完/开始标记）**逐字取库**；条件工序在工序库无活跃行 ⇒
     * fail-closed（{@link #ERR_OPERATION_NOT_FOUND}）—— 静默跳过会让「勾了却没加工序」
     * 在数据上消失，那正是本单要治的「设计过但从未接线」形态。</p>
     */
    private void insertConditionalOperations(List<Map<String, Object>> operations, List<String> options,
                                             List<ProductionOptionRouting> optionRoutings,
                                             Long tenantId, Map<String, Object> entry) {
        List<ProductionOptionRouting> applicable = new ArrayList<>();
        for (ProductionOptionRouting routing : optionRoutings) {
            if (options.contains(routing.getOptionName())) {
                applicable.add(routing);
            }
        }
        if (applicable.isEmpty()) {
            return; // 选项未登记条件工序（纯系数选项 / 显式不计件选项）⇒ 路线不变，不是错误
        }
        applicable.sort(Comparator.comparing(
                (ProductionOptionRouting r) -> r.getSortOrder() == null ? 0 : r.getSortOrder())
                .thenComparing(r -> r.getOptionName() == null ? "" : r.getOptionName()));
        Map<String, Map<String, Object>> catalog = productionOperationQueryService.operationsByName(tenantId);
        List<String> missing = new ArrayList<>();
        for (ProductionOptionRouting routing : applicable) {
            String operationName = routing.getOperationName();
            Map<String, Object> meta = catalog.get(operationName);
            if (meta == null) {
                missing.add(operationName);
                continue;
            }
            Map<String, Object> operation = new LinkedHashMap<>();
            operation.put("operation", operationName);
            operation.putAll(meta);
            int anchor = indexOfOperation(operations, routing.getAfterOperation());
            if (anchor < 0) {
                log.info("特殊选项「{}」的锚点工序「{}」不在该部位路线中，条件工序「{}」追加到末尾: productName={}",
                        routing.getOptionName(), routing.getAfterOperation(), operationName, entry.get("productName"));
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
                    String.format("请在工序库补上 %s（或停用引用它的特殊选项映射）；"
                                    + "工序库目录查看入口 GET /api/admin/production/operations-catalog",
                            String.join("、", missing)));
        }
    }

    /** 锚点工序在路线中的下标；不在 ⇒ -1（调用方按真值源口径追加到末尾）。 */
    private static int indexOfOperation(List<Map<String, Object>> operations, String operationName) {
        for (int i = 0; i < operations.size(); i++) {
            if (Objects.equals(operations.get(i).get("operation"), operationName)) {
                return i;
            }
        }
        return -1;
    }

    /**
     * 重排部位内序号（1..N）。
     *
     * <p>为什么必须重排：库路线的 seq 只覆盖**基准**工序，条件工序插进来后原序号会重复/断档；
     * 而 {@code seq} 是报工「越站」防呆（{@code assertPredecessorsDone} 取「seq 最大的前道」）
     * 与页面排序的**唯一**顺序依据 ⇒ 序号错 = 越站校验错。真值源同款：
     * {@code routing.py::instance_operations} 在插完条件工序后 `enumerate(route, start=1)`。</p>
     *
     * <p>无特殊选项时结果与库路线逐值相同（路线 seq 本来就是 1..N）⇒ 不回归。</p>
     */
    private static void renumberSeq(List<Map<String, Object>> operations) {
        for (int i = 0; i < operations.size(); i++) {
            operations.get(i).put("seq", i + 1);
        }
    }

    /**
     * 落计件系数（issue #4230 验收判据 2）：选项 → {@code production_option_factors} →
     * 该部位每道工序的 {@code factor}。
     *
     * <p>取用口径与真值源 {@code routing.py::factor_for} 逐字同口径：
     * ① 单个选项内**例外档盖住平摊档**（{@code operation_name} 命中的档优先，否则取 NULL 档）
     * —— 不是相乘（相乘会把「平摊 ×1.7 + 逐工序 ×2.0」算成 ×3.4，纯属重复计费）；
     * ② 多个加系数选项之间**相乘**（独立倍率的合成口径）；
     * ③ 未登记的选项**不得**悄悄改系数（查不到档 ⇒ 保持 1）。</p>
     *
     * <p>落进 {@code factor} 后由计件公式（{@code Σ 合格数 × 单价 × 系数}）真的乘进钱 ——
     * 该列自 V49 就存在、公式也真的读它，但**此前零写方** ⇒ 恒 1.00。</p>
     */
    private static void applyFactors(List<Map<String, Object>> operations, List<String> options,
                                     List<ProductionOptionFactor> optionFactors) {
        if (options.isEmpty()) {
            for (Map<String, Object> operation : operations) {
                operation.put("factor", BigDecimal.ONE);
            }
            return;
        }
        for (Map<String, Object> operation : operations) {
            String operationName = String.valueOf(operation.get("operation"));
            BigDecimal factor = BigDecimal.ONE;
            for (String option : options) {
                ProductionOptionFactor scoped = null;
                ProductionOptionFactor flat = null;
                for (ProductionOptionFactor row : optionFactors) {
                    if (!option.equals(row.getOptionName())) {
                        continue;
                    }
                    if (operationName.equals(row.getOperationName())) {
                        scoped = row;          // 例外档
                    } else if (row.getOperationName() == null) {
                        flat = row;            // 平摊档
                    }
                }
                ProductionOptionFactor hit = scoped != null ? scoped : flat;
                if (hit != null && hit.getFactor() != null) {
                    factor = factor.multiply(hit.getFactor());
                }
            }
            operation.put("factor", factor);
        }
    }

    /** 算料请求体里的单个部位（与 ai-agent 端点冻结契约同构）。 */
    private Map<String, Object> qtyRequest(Map<String, Object> entry, String positionName,
                                           List<Map<String, Object>> operations) {
        List<String> names = new ArrayList<>(operations.size());
        for (Map<String, Object> operation : operations) {
            names.add(String.valueOf(operation.get("operation")));
        }
        Map<String, Object> position = new LinkedHashMap<>();
        position.put("position_name", positionName);
        position.put("operations", names);
        position.put("calc_info", calcInfo(entry));
        return position;
    }

    /**
     * 算料输入（issue #4208 Java 接线）。
     *
     * <p><b>口径依据</b>：订单行 {@code quantity} 的语义由**计价方式**决定
     * （{@code OrderItem.quantity} javadoc：「per_meter=米数、per_set=1、per_area=宽×高」；
     * 前端 {@code deriveProcessingQty} 同口径）⇒ {@code per_meter} 时它**就是**面料米数，
     * 映射到算料引擎的 {@code fabric_meters} 键（**键名映射，不是第二份算料逻辑**）。</p>
     *
     * <p><b>已知缺口（#4118，不是本方法缺陷）</b>：订单侧**从不落库算料输出** ⇒
     * {@code pleat_count}（折数）/ {@code panels}（幅）/ {@code set_count}（套）/ {@code holes}（孔）
     * 一律取不到 ⇒ 端点在缺键时兜底 1 并在 {@code qty_source} 标 {@code fallback}。
     * 真正修法是**下单时把算料输出落库**（#4118「实际褶倍算了就丢」），届时本方法只需把透传白名单
     * 扩到那几个键即可 —— 请勿把它当 bug 反复排查。</p>
     */
    private Map<String, Object> calcInfo(Map<String, Object> entry) {
        Map<String, Object> calc = new LinkedHashMap<>();
        // ① 订单侧若已存算料输出（键名与 routing.py 的 METER_KEYS/FOLD_KEYS/… 同口径）⇒ 原样透传
        for (String key : CALC_INFO_KEYS) {
            Object value = entry.get(key);
            if (value != null) {
                calc.put(key, value);
            }
        }
        // ② per_meter 计价：订单行数量即米数（键名映射；其它计价方式**不**冒充米数）
        String sellingMethod = str(entry.get("sellingMethod"));
        if (!calc.containsKey("fabric_meters") && sellingMethod != null
                && PER_METER_METHODS.contains(sellingMethod)) {
            Object quantity = entry.get("quantity");
            if (quantity != null) {
                calc.put("fabric_meters", quantity);
            }
        }
        return calc;
    }

    /**
     * 用算料引擎的返回回填 {@code qty} 与 {@code qty_source}。
     *
     * <p>fail-closed 的两个细节：① 端点返回条数与请求不符 ⇒ 客户端已抛错（不在此处补位）；
     * ② 端点漏答某道工序（契约外形态）⇒ 同样抛错，**不**替它兜底 1 ——
     * 静默补值会让「算料服务没答」与「算料服务答了兜底 1」长得一模一样。</p>
     */
    private void fillQty(List<Map<String, Object>> positions,
                         List<List<Map<String, Object>>> operationRows,
                         List<Map<String, Object>> request) {
        List<ProductionOperationQtyClient.PositionQty> resolved = productionOperationQtyClient.resolve(request);
        if (resolved.size() != positions.size()) {
            throw new BusinessException(ProductionOperationQtyClient.ERR_OPERATION_QTY_UNAVAILABLE,
                    "算料服务返回的部位数（" + resolved.size() + "）与请求（" + positions.size() + "）不符，已中止生成加工单",
                    422,
                    "请确认 ai-agent-service 版本与 admin-api 契约一致后重新生成加工单");
        }
        for (int i = 0; i < positions.size(); i++) {
            ProductionOperationQtyClient.PositionQty answered = resolved.get(i);
            for (Map<String, Object> operation : operationRows.get(i)) {
                String name = String.valueOf(operation.get("operation"));
                BigDecimal qty = answered.qtyByOperation().get(name);
                if (qty == null) {
                    throw new BusinessException(ProductionOperationQtyClient.ERR_OPERATION_QTY_UNAVAILABLE,
                            "算料服务未返回工序「" + name + "」的应做数量，已中止生成加工单（不静默兜底）",
                            422,
                            "请确认 ai-agent-service 的算料端点已登记该工序的单位后重新生成加工单");
                }
                operation.put("qty", qty);
                operation.put("qty_source", answered.qtySourceByOperation().get(name));
            }
        }
    }

    /**
     * 取路线（工序库）：派生键命中就取它；未命中 ⇒ 记日志并取默认路线 `布帘×韩褶`。
     * **两次都没命中、或命中的路线引用了库里不存在的工序 ⇒ fail-closed 中止生成**
     * （错误码 + 可行动 suggestion + incident 日志，绝不回退加工项目录）。
     */
    @SuppressWarnings("unchecked")
    private Map<String, Object> resolveRoute(RouteKey key, Long tenantId, Map<String, Object> entry) {
        Map<String, Object> route = productionOperationQueryService.findRouting(
                tenantId, key.curtainType(), key.craft());
        String usedKey = key.curtainType() + "×" + key.craft();
        if (route == null) {
            log.info("工序库无「{}」路线（派生来源={}），回落默认路线 {}×{}: productName={}",
                    usedKey, key.source(), DEFAULT_CURTAIN_TYPE, DEFAULT_CRAFT, entry.get("productName"));
            usedKey = DEFAULT_CURTAIN_TYPE + "×" + DEFAULT_CRAFT;
            route = productionOperationQueryService.findRouting(tenantId, DEFAULT_CURTAIN_TYPE, DEFAULT_CRAFT);
        }
        if (route == null) {
            List<String> available = productionOperationQueryService.routingKeys(tenantId);
            log.error("{} 工序库无可用工艺路线，生成加工单中止（不回退加工项目录）: tenantId={}, 需要={}, "
                            + "默认={}×{}, 库中现有路线={}, productName={}",
                    INCIDENT_ROUTING_UNRESOLVED, tenantId, usedKey, DEFAULT_CURTAIN_TYPE, DEFAULT_CRAFT,
                    available, entry.get("productName"));
            throw new BusinessException(ERR_ROUTING_NOT_FOUND,
                    String.format("工序库缺少「%s×%s」的工艺路线，无法实例化工序（工序来源为工序库，不回退加工项目录）",
                            DEFAULT_CURTAIN_TYPE, DEFAULT_CRAFT),
                    422,
                    String.format("请在工序库补齐工艺路线；当前库中路线 %s。"
                                    + "若为空库，先确认 V54 种子迁移（V54__seed_production_operations.sql）已执行；"
                                    + "查看入口 GET /api/admin/production/routings",
                            available.isEmpty() ? "**为空**" : "有：" + String.join("、", available)));
        }
        List<String> missing = (List<String>) route.get("missing_operations");
        if (missing != null && !missing.isEmpty()) {
            log.error("{} 工艺路线引用的工序在工序库无活跃行，生成加工单中止（不回退加工项目录）: "
                            + "tenantId={}, 路线={}, 缺工序={}, productName={}",
                    INCIDENT_ROUTING_UNRESOLVED, tenantId, usedKey, missing, entry.get("productName"));
            throw new BusinessException(ERR_OPERATION_NOT_FOUND,
                    String.format("工艺路线「%s」引用的工序 %s 在工序库中不存在，无法实例化工序", usedKey, missing),
                    422,
                    String.format("请在工序库补上 %s（或改这条路线不再引用它们）；"
                                    + "工序库目录查看入口 GET /api/admin/production/operations-catalog",
                            String.join("、", missing)));
        }
        return route;
    }

    /**
     * 从订单侧**可派生信号**推出路线键（`curtain_type` + `craft`）。
     *
     * <p>信号优先级（命中即止，先信号后关键字 —— 更权威的信号先说话）：
     * ① 加工项名（加工项目录里工序名自带部位/工艺，如「韩褶-布」「打孔-纱」「帘头制作」）
     * ② 加工项 options（如「四爪钩」）③ 商品名 ④ 销售方式。两类信号各自独立扫描，
     * 只会派生出一半时另一半取默认值。</p>
     *
     * <p>⚠️ 这是**当前的**取法：订单侧没有部位/帘种字段（见类注释「部位语义」节），
     * 待订单侧补字段后应改为直读，届时本方法连同关键字表一起删除。</p>
     */
    @SuppressWarnings("unchecked")
    private RouteKey deriveRouteKey(Map<String, Object> entry) {
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
        String productName = str(entry.get("productName"));
        if (productName != null) {
            signals.add(productName);
        }
        String sellingMethod = str(entry.get("sellingMethod"));
        if (sellingMethod != null) {
            signals.add(sellingMethod);
        }

        String curtainType = firstKeywordMatch(signals, CURTAIN_TYPE_KEYWORDS);
        String craft = firstKeywordMatch(signals, CRAFT_KEYWORDS);
        boolean derived = curtainType != null || craft != null;
        return new RouteKey(curtainType == null ? DEFAULT_CURTAIN_TYPE : curtainType,
                craft == null ? DEFAULT_CRAFT : craft,
                derived ? "derived" : "default");
    }

    private static String firstKeywordMatch(List<String> signals, String[][] table) {
        for (String signal : signals) {
            for (String[] pair : table) {
                if (signal.contains(pair[0])) {
                    return pair[1];
                }
            }
        }
        return null;
    }

    /** 派生出的路线键 + 来源（"derived" 命中信号 / "default" 全不命中）。 */
    private record RouteKey(String curtainType, String craft, String source) {
    }

    // ============================================================ 存量单恢复 / 打印计数

    /**
     * 按订单派生工序实例 payload（issue #4202）——{@code POST /api/admin/production/orders/{orderId}/instantiate}
     * 的 {@code positions} 缺省路径复用**生成加工单时的同一份**解析：
     * {@link #buildSnapshot}（订单明细 → 部位/工艺信号）+ {@link #buildPositionPayload}（工序库路线）。
     *
     * <p>为什么必须复用而不是另写一份：存量单（生成于 #4116「生成即实例化」之前，工序实例与
     * {@code qr_token} 双空）补工序时，派生的路线/单价/必完标记必须与**新建单**逐字同源 ——
     * 第二份路线解析必然与 {@link #generateOne} 漂移（关键字表/默认路线/fail-closed 三处口径）。</p>
     *
     * <p>取不到路线、或路线引用的工序在库中缺行时**同样 fail-closed**
     * （{@link #ERR_ROUTING_NOT_FOUND} / {@link #ERR_OPERATION_NOT_FOUND} + suggestion），
     * 绝不静默返回空 payload（那会让调用方落一个「有加工单、零工序」的空壳）。</p>
     *
     * @return 与 {@code instantiate} 请求体里 {@code positions} 同构的列表
     */
    public List<Map<String, Object>> derivePositionPayload(String rawOrderId, Long tenantId) {
        Order order = resolveOrder(rawOrderId, tenantId);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }
        return buildPositionPayload(buildSnapshot(loadOrderItems(order.getId(), tenantId), tenantId), tenantId);
    }

    /**
     * 记录一次任务卡打印（issue #4202 边角修复）——{@code processing_orders.print_count} 此前
     * **零写方**（全仓只有建单时的 {@code printCount(0)} 与响应映射）⇒ 真值源 §1「记录打印次数」
     * 在数据层不可观测。SQL 内原子自增（并发多标签页打印不丢计数），返回递增后的计数。
     *
     * @param rawId 加工单 id / 加工单号 / 订单 id（与 {@link #getDetail} 同一解析口径）
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> recordPrint(String rawId, Long tenantId) {
        ProcessingOrder po = resolveProcessingOrder(rawId, tenantId);
        if (po == null) {
            throw BusinessException.notFound("加工单");
        }
        processingOrderMapper.incrementPrintCount(po.getId(), tenantId, OffsetDateTime.now());
        ProcessingOrder after = processingOrderMapper.selectById(po.getId());
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("order_id", po.getOrderId());
        result.put("processing_order_no", po.getProcessingOrderNo());
        result.put("print_count", after == null ? null : after.getPrintCount());
        return result;
    }

    private static String str(Object value) {
        if (value == null) {
            return null;
        }
        String text = String.valueOf(value).trim();
        return text.isEmpty() ? null : text;
    }

    /**
     * 快照构建（五要素 + options；不含销售价——决策 2）。
     * 加工项 options 下单时未落库，此处从加工项目录补齐（设计文档查漏点 1）。
     */
    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> buildSnapshot(List<OrderItem> items, Long tenantId) {
        List<Map<String, Object>> snapshot = new ArrayList<>();
        for (OrderItem item : items) {
            // 归一化：processingInfo 可能是 Map（BaseMapper 路径）或 JSON 字符串（自定义 @Select 路径）
            Map<String, Object> pi = normalizeProcessingInfo(item.getProcessingInfo());
            List<Map<String, Object>> procs = extractProcessingItems(pi);
            if (procs.isEmpty()) {
                continue;
            }
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("productName", item.getProductName());
            entry.put("quantity", item.getQuantity());
            entry.put("width", item.getWidth());
            entry.put("height", item.getHeight());
            // 销售信息（与加工项同存 processing_info，前端写入）
            copyIfPresent(pi, entry, "sku");
            copyIfPresent(pi, entry, "skuCode", "sku");
            copyIfPresent(pi, entry, "colorName");
            copyIfPresent(pi, entry, "sellingMethod");
            copyIfPresent(pi, entry, "doorWidth");
            copyIfPresent(pi, entry, "unit");
            // 特殊选项（issue #4230 v1a）：订单侧**新携带** specialOptions: string[]，
            // 落在既有 processingInfo JSONB 内（**无需迁移**）；加工单快照透传一份，
            // 生成时的条件工序/计件系数都从快照读（快照是加工单的固化真相）。
            copyIfPresent(pi, entry, "specialOptions");
            // 加工项明细 + options 补齐
            List<Map<String, Object>> itemsWithOptions = new ArrayList<>();
            for (Map<String, Object> p : procs) {
                Map<String, Object> enriched = new LinkedHashMap<>(p);
                Object id = p.get("id");
                if (id != null) {
                    ProcessingItem piEntity = processingItemMapper.selectById(String.valueOf(id));
                    if (piEntity != null) {
                        enriched.put("options", piEntity.getOptions());
                        if (!enriched.containsKey("unit")) {
                            enriched.put("unit", piEntity.getUnit());
                        }
                    }
                }
                itemsWithOptions.add(enriched);
            }
            entry.put("processingItems", itemsWithOptions);
            snapshot.add(entry);
        }
        return snapshot;
    }

    private void copyIfPresent(Map<String, Object> from, Map<String, Object> to, String key) {
        copyIfPresent(from, to, key, key);
    }

    /**
     * processing_info 归一化：Map 直接用；JSON 字符串（自定义 @Select 路径，不经过
     * JacksonTypeHandler）解析为 Map；其它形态返回 null。
     */
    @SuppressWarnings("unchecked")
    private Map<String, Object> normalizeProcessingInfo(Object processingInfo) {
        if (processingInfo instanceof Map) {
            return (Map<String, Object>) processingInfo;
        }
        if (processingInfo instanceof String s && !s.isBlank()) {
            try {
                return objectMapper.readValue(s, Map.class);
            } catch (Exception e) {
                log.warn("processingInfo JSON 字符串解析失败: {}", e.getMessage());
            }
        }
        return null;
    }

    private void copyIfPresent(Map<String, Object> from, Map<String, Object> to, String fromKey, String toKey) {
        Object v = from.get(fromKey);
        if (v != null) {
            to.put(toKey, v);
        }
    }

    /**
     * 加载订单明细（走 BaseMapper，确保 processing_info 经 JacksonTypeHandler 反序列化为 Map）。
     * issue #3340 验收实战：自定义 @Select（selectByOrderId）不应用 typeHandler，
     * processing_info 以 JSON 字符串返回 → buildSnapshot 恒空 → 误判「无加工项」。
     */
    private List<OrderItem> loadOrderItems(String orderId, Long tenantId) {
        List<OrderItem> items = orderItemMapper.selectList(new LambdaQueryWrapper<OrderItem>()
                .eq(OrderItem::getOrderId, orderId)
                .eq(OrderItem::getTenantId, tenantId)
                .eq(OrderItem::getDeleted, 0));
        return items != null ? items : java.util.Collections.emptyList();
    }

    /** 解析 processing_info 的加工项列表（与 OrderService.extractProcessingItems 同语义，兼容 JSON 字符串） */
    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> extractProcessingItems(Object processingInfo) {
        Map<String, Object> normalized = normalizeProcessingInfo(processingInfo);
        if (normalized == null) {
            return java.util.Collections.emptyList();
        }
        try {
            Object raw = normalized.get("processingItems");
            if (!(raw instanceof List)) {
                return java.util.Collections.emptyList();
            }
            List<Map<String, Object>> result = new ArrayList<>();
            for (Object element : (List<Object>) raw) {
                if (element instanceof Map) {
                    result.add(new LinkedHashMap<>((Map<String, Object>) element));
                }
            }
            return result;
        } catch (Exception e) {
            log.warn("解析 processingInfo 失败: {}", e.getMessage());
            return java.util.Collections.emptyList();
        }
    }

    private Order resolveOrder(String rawId, Long tenantId) {
        Order byId = orderMapper.selectById(rawId);
        if (byId != null && tenantId.equals(byId.getTenantId())) {
            return byId;
        }
        return orderMapper.selectOne(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId)
                .eq(Order::getOrderNo, rawId)
                .eq(Order::getDeleted, 0)
                .last("LIMIT 1"));
    }

    private String generateOrderNo() {
        String base = "JG-" + LocalDate.now().format(PO_DATE_FMT) + "-";
        // DB 唯一约束兜底；此处随机化降低同秒碰撞概率
        return base + String.format("%04d", PO_SEQ.incrementAndGet());
    }

    // ============================================================ 状态更新

    /**
     * 加工单状态更新（action: issue/start/complete/cancel）。
     * 状态机校验 + 订单联动（cancel → producing→confirmed 回退）。
     */
    @Transactional(rollbackFor = Exception.class)
    public ProcessingOrderResponse updateStatus(String rawId, ProcessingOrderUpdateRequest req,
                                                Long tenantId, String operator) {
        if (req == null || !StringUtils.hasText(req.getAction())) {
            throw BusinessException.validationError("action 不能为空");
        }
        ProcessingOrder po = resolveProcessingOrder(rawId, tenantId);
        if (po == null) {
            throw BusinessException.notFound("加工单");
        }
        String action = req.getAction();
        String target;
        switch (action) {
            case "issue": target = "issued"; break;
            case "start": target = "in_processing"; break;
            case "complete": target = "completed"; break;
            case "cancel": target = "cancelled"; break;
            default: throw BusinessException.validationError("无效的加工单操作: " + action);
        }
        String current = po.getStatus();
        if (!STATUS_TRANSITIONS.getOrDefault(current, Set.of()).contains(target)) {
            throw BusinessException.validationError(String.format(
                    "加工单状态不允许从 [%s] 变更为 [%s]", label(current), label(target)));
        }
        if ("cancel".equals(action) && !StringUtils.hasText(req.getReason())) {
            throw BusinessException.validationError("取消加工单必须填写原因");
        }

        ProcessingOrder upd = ProcessingOrder.builder().id(po.getId()).status(target).build();
        OffsetDateTime now = OffsetDateTime.now();
        switch (action) {
            case "issue":
                // issue #3901：交期不允许早于今天（前端 date 控件之外的兜底，同时覆盖 agent processing_order_update 路径）
                if (req.getExpectedDeliveryDate() != null
                        && req.getExpectedDeliveryDate().isBefore(LocalDate.now())) {
                    throw BusinessException.validationError("交付日期不能早于今天");
                }
                upd.setIssuedAt(now);
                upd.setProcessor(req.getProcessor());
                upd.setExpectedDeliveryDate(req.getExpectedDeliveryDate());
                break;
            case "start":
                upd.setInProcessingAt(now);
                break;
            case "complete":
                upd.setCompletedAt(now);
                break;
            case "cancel":
                upd.setCancelledAt(now);
                upd.setCancelledReason(req.getReason());
                break;
            default:
                break;
        }
        processingOrderMapper.updateById(upd);

        // 联动：加工单取消（未发货）→ 订单 producing→confirmed 回退（重新可生成加工单）
        if ("cancel".equals(action)) {
            Order order = orderMapper.selectById(po.getOrderId());
            if (order != null && "producing".equals(order.getStatus())) {
                orderService.revertProducingToConfirmed(order.getId(),
                        "加工单 " + po.getProcessingOrderNo() + " 取消，订单回退已确认");
                log.info("加工单取消联动回退订单: po={}, orderId={}", po.getProcessingOrderNo(), order.getId());
            }
        }
        log.info("加工单状态变更: no={}, {} -> {}, operator={}", po.getProcessingOrderNo(), current, target, operator);
        return getDetail(po.getId(), tenantId);
    }

    private String label(String status) {
        return STATUS_LABELS.getOrDefault(status, status);
    }

    private ProcessingOrder resolveProcessingOrder(String rawId, Long tenantId) {
        return processingOrderMapper.selectOne(new LambdaQueryWrapper<ProcessingOrder>()
                .eq(ProcessingOrder::getTenantId, tenantId)
                .eq(ProcessingOrder::getDeleted, 0)
                .and(w -> w.eq(ProcessingOrder::getId, rawId)
                        .or().eq(ProcessingOrder::getProcessingOrderNo, rawId)
                        .or().eq(ProcessingOrder::getOrderId, rawId))
                .last("LIMIT 1"));
    }

    // ============================================================ 查询

    public List<ProcessingOrderResponse> list(String keyword, String status, Long tenantId) {
        List<ProcessingOrder> list;
        if (StringUtils.hasText(keyword)) {
            list = processingOrderMapper.selectByKeyword(keyword.trim(), tenantId);
        } else {
            LambdaQueryWrapper<ProcessingOrder> wrapper = new LambdaQueryWrapper<ProcessingOrder>()
                    .eq(ProcessingOrder::getTenantId, tenantId)
                    .eq(ProcessingOrder::getDeleted, 0)
                    .orderByDesc(ProcessingOrder::getCreatedAt)
                    .last("LIMIT 100");
            if (StringUtils.hasText(status)) {
                wrapper.eq(ProcessingOrder::getStatus, status);
            }
            list = processingOrderMapper.selectList(wrapper);
        }
        List<ProcessingOrderResponse> result = new ArrayList<>();
        for (ProcessingOrder po : list) {
            result.add(toResponse(po, tenantId));
        }
        return result;
    }

    public ProcessingOrderResponse getDetail(String rawId, Long tenantId) {
        ProcessingOrder po = resolveProcessingOrder(rawId, tenantId);
        if (po == null) {
            // 订单还没有加工单是正常状态（issue #3887）：rawId 若能解析为有效订单（tenant 隔离），
            // 返回 null → ApiResponse.success(null) → 前端 ProcessingOrderBlock 走
            // res.data?.data ?? null / setNotFound(!data) 展示「生成加工单」态；
            // 订单也不存在（真无效 ID）才保持 404。
            if (resolveOrder(rawId, tenantId) == null) {
                throw BusinessException.notFound("加工单");
            }
            return null;
        }
        return toResponse(po, tenantId);
    }

    @SuppressWarnings("unchecked")
    private ProcessingOrderResponse toResponse(ProcessingOrder po, Long tenantId) {
        ProcessingOrderResponse resp = new ProcessingOrderResponse();
        resp.setId(po.getId());
        resp.setTenantId(String.valueOf(po.getTenantId()));
        resp.setOrderId(po.getOrderId());
        resp.setProcessingOrderNo(po.getProcessingOrderNo());
        resp.setProcessor(po.getProcessor());
        resp.setExpectedDeliveryDate(po.getExpectedDeliveryDate());
        resp.setStatus(po.getStatus());
        resp.setRemark(po.getRemark());
        resp.setTemplateVersion(po.getTemplateVersion());
        resp.setGeneratedAt(po.getGeneratedAt());
        resp.setIssuedAt(po.getIssuedAt());
        resp.setInProcessingAt(po.getInProcessingAt());
        resp.setCompletedAt(po.getCompletedAt());
        resp.setCancelledAt(po.getCancelledAt());
        resp.setCancelledReason(po.getCancelledReason());
        resp.setPrintCount(po.getPrintCount());
        // 订单信息
        Order order = orderMapper.selectById(po.getOrderId());
        if (order != null) {
            resp.setOrderNo(order.getOrderNo());
            resp.setCustomerName(order.getCustomerName());
            resp.setCustomerPhone(order.getCustomerPhone());
        }
        // 快照解析（兼容 JSON 字符串：自定义 @Select 查询路径不经过 typeHandler）
        Object snapshot = po.getItemsSnapshot();
        if (snapshot instanceof String s && !s.isBlank()) {
            try {
                snapshot = objectMapper.readValue(s, Object.class);
            } catch (Exception e) {
                log.warn("加工单快照 JSON 字符串解析失败: po={}, err={}", po.getProcessingOrderNo(), e.getMessage());
                snapshot = null;
            }
        }
        if (snapshot != null) {
            try {
                resp.setItems(objectMapper.convertValue(snapshot,
                        objectMapper.getTypeFactory().constructCollectionType(List.class,
                                ProcessingOrderResponse.ProcessingOrderItemBrief.class)));
            } catch (Exception e) {
                log.warn("加工单快照解析失败: po={}, err={}", po.getProcessingOrderNo(), e.getMessage());
            }
        }
        return resp;
    }

    // ============================================================ 生成结果

    @lombok.Data
    public static class GenerateResult {
        private final String orderRef;
        private final boolean success;
        private final String message;
        private final String processingOrderNo;
        /**
         * 失败时的业务错误码（issue #4116 切库：库取不到工序 ⇒ {@link #ERR_ROUTING_NOT_FOUND} /
         * {@link #ERR_OPERATION_NOT_FOUND}）。此前逐单 catch 只留 message ⇒ 错误码在接口层不可见，
         * 调用方只能靠中文文案分辨失败原因。成功时为 null（不进 JSON，Jackson 默认排除 null）。
         */
        private final String code;
        /** 失败时的可行动建议（同 {@code BusinessException.suggestion} 的口径）；成功时为 null。 */
        private final String suggestion;

        public static GenerateResult ok(String orderRef, String no) {
            return new GenerateResult(orderRef, true, null, no, null, null);
        }

        public static GenerateResult fail(String orderRef, String message) {
            return new GenerateResult(orderRef, false, message, null, null, null);
        }

        /** 带错误码与建议的失败结果（fail-closed 场景：调用方要能机器分辨原因并照着建议修库）。 */
        public static GenerateResult fail(String orderRef, String code, String message, String suggestion) {
            return new GenerateResult(orderRef, false, message, null, code, suggestion);
        }
    }
}
