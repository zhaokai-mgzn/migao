package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.ProcessingOrderGenerateRequest.BatchAssignment;
import com.migao.admin.dto.ProductionPoolViews;
import com.migao.admin.service.ProcessingPositionPayloadBuilder.PositionPayload;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.Supplier;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.SupplierMapper;
import com.migao.admin.time.BusinessClock;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.util.StringUtils;

import static com.migao.admin.service.ProcessingOrderService.*;

/**
 * 加工单**派单生成链**单元（issue #8770「生成族」一档，从 {@link ProcessingOrderService} **纯搬运**）。
 *
 * <p><b>单一职责</b>：一次派单的完整链路 —— 批次指派装配（{@link #assignmentsByOrder}）→ 只读准备
 * （{@link #prepare}：状态闸 / 快照 / 幂等闸 / 工序 payload / 扣减入参）→ 求解（逐单一次
 * {@code plan} 或池级一次，{@link #generatePooled}）→ 落库（{@link #commit}：盖章 → 占号插入 →
 * 扣批次 → 实例化工序）。公开入口（5 个 {@code generate} 重载 / {@code generateDirect} /
 * {@code preview} / {@code processorOptions}）仍住门面 —— 门面留同名委托，
 * **{@code @Transactional} 边界因此仍在门面**（Spring 代理只在门面的公开方法上生效）。</p>
 *
 * <p><b>搬运口径</b>：方法体、注释、异常码与文案**一字未改**。改动只有四类，逐条可复算：
 * ① 可见性 **0 处**（载体类本身 `package-private` ⇒ 原 `public` 成员的有效可见性不变；
 * 原 `private` 成员仍 `private` —— 相对声明不跨界搬家）；
 * ② **9 行**字段引用 → {@link Owner} 回调（业务时钟 2 · 承接方档案 4 · 生命周期服务 2 ·
 * 工序服务 1；初次全文替换后逐行复核，见 PR body 的等价性读数），**每次即时取值**
 * —— 既有判据用 {@code ReflectionTestUtils.setField} 在构造之后换时钟/算料 ⇒ 缓存会读到旧值；
 * ③ **6 处** {@code @Transactional} 注解留在门面（5 个 {@code generate} 重载 + {@code generateDirect}）；
 * ④ 本类**不新增**任何写操作、常量或判据对象 —— 常量表 / {@code STATUS_TRANSITIONS} 状态机 /
 * 四个盖章委托 / {@code snapshotSkuCode} / {@code str} / {@code craftHintOf} 全部仍住门面
 * （它们是被既有判据直接核对的载体）。</p>
 *
 * <p><b>为什么加急/外发闸仍住派单池单元</b>：{@code assertNoUrgentInPooledBatch} /
 * {@code assertNoOutsourcedInPooledBatch} 是池的只读判据，本类经 {@link Owner#dispatchPool()}
 * 回调（同一实例、同一份口径，不复制第二份）。</p>
 */
@Slf4j
@RequiredArgsConstructor
class ProcessingOrderGeneration {

    /** 派单生成链对门面的外呼面（时钟 / 算料 / 工序 / 生命周期 / 读面仍住门面：不复制第二份口径）。 */
    interface Owner {
        LocalDate today();

        BusinessClock businessClock();

        StockBatchConsumptionService batchStock();

        ProcessingPositionPayloadBuilder positionPayloadBuilder();

        ProcessingOrderDispatchPool dispatchPool();

        SupplierMapper supplierMapper();

        ProductionService productionService();

        OrderService orderService();

        Order resolveOrder(String rawId, Long tenantId);

        List<OrderItem> loadOrderItems(String orderId, Long tenantId);

        List<Map<String, Object>> buildSnapshot(List<OrderItem> items, Long tenantId);
    }

    private final ProcessingOrderMapper processingOrderMapper;
    private final ObjectMapper objectMapper;
    private final Owner owner;

    private LocalDate today() {
        return owner.today();
    }

    private BusinessClock businessClock() {
        return owner.businessClock();
    }

    private StockBatchConsumptionService batchStock() {
        return owner.batchStock();
    }

    private ProcessingPositionPayloadBuilder positionPayloadBuilder() {
        return owner.positionPayloadBuilder();
    }

    private ProcessingOrderDispatchPool dispatchPool() {
        return owner.dispatchPool();
    }

    private SupplierMapper supplierMapper() {
        return owner.supplierMapper();
    }

    private ProductionService productionService() {
        return owner.productionService();
    }

    private OrderService orderService() {
        return owner.orderService();
    }

    private Order resolveOrder(String rawId, Long tenantId) {
        return owner.resolveOrder(rawId, tenantId);
    }

    private List<OrderItem> loadOrderItems(String orderId, Long tenantId) {
        return owner.loadOrderItems(orderId, tenantId);
    }

    private List<Map<String, Object>> buildSnapshot(List<OrderItem> items, Long tenantId) {
        return owner.buildSnapshot(items, tenantId);
    }

    public ProductionPoolViews.Preview preview(Long tenantId, List<String> orderIds,
                                               List<BatchAssignment> batches, String assignmentRule) {
        if (orderIds == null || orderIds.isEmpty()) {
            throw BusinessException.validationError("orderIds 不能为空");
        }
        String normalizedRule = StockBatchConsumptionService.normalizeAssignmentRule(assignmentRule);
        String rule = StringUtils.hasText(assignmentRule) ? normalizedRule : null;
        Map<String, List<BatchAssignment>> byOrder = assignmentsByOrder(orderIds, batches);
        // 🔴 加急单不进池（判据 3）—— 预览是**成批**的预览：让它预览一个**派不出去**的批次
        // 就是「预览说谎」（判据 4）⇒ 与 /dispatch 同一条闸、同一处口径。
        dispatchPool().assertNoUrgentInPooledBatch(orderIds, tenantId);
        dispatchPool().assertNoOutsourcedInPooledBatch(orderIds, tenantId);
        List<Prepared> prepared = new ArrayList<>();
        List<StockBatchConsumptionService.Designation> pooledLines = new ArrayList<>();
        for (String rawId : orderIds) {
            Prepared p = prepare(rawId, byOrder.getOrDefault(rawId, List.of()), tenantId, null, rule);
            prepared.add(p);
            pooledLines.addAll(p.designations());
        }
        List<StockBatchConsumptionService.Deduction> pooledPlan = batchStock().plan(tenantId, pooledLines);
        BigDecimal formula = StockQuantity.sum(
                pooledPlan.stream().map(StockBatchConsumptionService.Deduction::formulaMeters).toList());
        BigDecimal pooledPlanned = StockQuantity.sum(
                pooledPlan.stream().map(StockBatchConsumptionService.Deduction::plannedMeters).toList());
        // 对照读数：**逐单派**的应领合计（池化**新增**的收益 = 两者之差 —— 不把 #5158 已有的
        // 单订单内并排算成池化的功劳）
        BigDecimal perOrderPlanned = BigDecimal.ZERO;
        for (Prepared p : prepared) {
            perOrderPlanned = perOrderPlanned.add(StockQuantity.sum(
                    batchStock().plan(tenantId, p.designations()).stream()
                            .map(StockBatchConsumptionService.Deduction::plannedMeters).toList()));
        }
        return new ProductionPoolViews.Preview(prepared.size(), rule, formula, pooledPlanned,
                formula.subtract(pooledPlanned), perOrderPlanned,
                perOrderPlanned.subtract(pooledPlanned));
    }

    public List<GenerateResult> generate(List<String> orderIds, Long tenantId, String operator) {
        return generate(orderIds, List.of(), tenantId, operator);
    }

    public List<GenerateResult> generate(List<String> orderIds, List<BatchAssignment> batches,
                                         Long tenantId, String operator) {
        return generate(orderIds, batches, tenantId, operator, null);
    }

    public List<GenerateResult> generate(List<String> orderIds, List<BatchAssignment> batches,
                                         Long tenantId, String operator, String assignmentRule) {
        return generate(orderIds, batches, tenantId, operator, assignmentRule, null);
    }

    public List<GenerateResult> generate(List<String> orderIds, List<BatchAssignment> batches,
                                         Long tenantId, String operator, String assignmentRule,
                                         Boolean pooled) {
        return generate(orderIds, batches, tenantId, operator, assignmentRule, pooled, null, null);
    }

    public List<GenerateResult> generate(List<String> orderIds, List<BatchAssignment> batches,
                                         Long tenantId, String operator, String assignmentRule,
                                         Boolean pooled, String processorSupplierId,
                                         LocalDate expectedDeliveryDate) {
        // 承接方 / 回厂日在**任何写库之前**校验完（fail-closed：不存在/停用/非加工厂 ⇒ 整批拒绝）
        Consignee consignee = resolveConsignee(processorSupplierId, expectedDeliveryDate, tenantId);
        if (orderIds == null || orderIds.isEmpty()) {
            throw BusinessException.validationError("orderIds 不能为空");
        }
        // 规则先归一 + 校验（**在任何写库之前**）：未知取值 ⇒ 整批显式拒绝，不留半成品。
        // `rule == null` = 调用方没传 ⇒ 不自动补位（缺省路径逐字不变，见方法注释）。
        String normalizedRule = StockBatchConsumptionService.normalizeAssignmentRule(assignmentRule);
        String rule = StringUtils.hasText(assignmentRule) ? normalizedRule : null;
        Map<String, List<BatchAssignment>> byOrder = assignmentsByOrder(orderIds, batches);
        // 🔴 默认关（判据 1）：不启用池化 ⇒ **逐单派**，与今天逐值相同（顺序、文案都不动）。
        boolean on = pooledEnabled(pooled);
        if (!on) {
            List<GenerateResult> results = new ArrayList<>();
            for (String rawId : orderIds) {
                try {
                    results.add(generateOne(rawId, byOrder.getOrDefault(rawId, List.of()), tenantId,
                            operator, rule, consignee));
                } catch (BusinessException e) {
                    results.add(GenerateResult.fail(rawId, e.getCode(), e.getMessage(), e.getSuggestion()));
                }
            }
            return results;
        }
        return generatePooled(orderIds, byOrder, tenantId, operator, rule, consignee);
    }

    public List<GenerateResult> generateDirect(List<String> orderIds, List<BatchAssignment> batches,
                                               Long tenantId, String operator, String assignmentRule) {
        if (orderIds == null || orderIds.isEmpty()) {
            throw BusinessException.validationError("orderIds 不能为空");
        }
        // 与 generate() 同一道「未匹配指派」校验（在任何写库之前）—— 语义不得因为多一层闸而漂移。
        Map<String, List<BatchAssignment>> byOrder = assignmentsByOrder(orderIds, batches);
        GenerateResult[] slots = new GenerateResult[orderIds.size()];
        List<String> allowed = new ArrayList<>();
        List<Integer> allowedSlots = new ArrayList<>();
        List<BatchAssignment> allowedBatches = new ArrayList<>();
        for (int i = 0; i < orderIds.size(); i++) {
            String rawId = orderIds.get(i);
            Order order = resolveOrder(rawId, tenantId);
            // 解析不到的订单**不在这里另造文案**：留给 generate() 的既有 ORDER_NOT_FOUND 分支
            // （两处文案必然漂移；「哪一步先失败」也是既有契约的一部分）。
            if (order != null) {
                slots[i] = GenerateResult.fail(rawId, ERR_DIRECT_DISPATCH_POOL_REQUIRED,
                        DIRECT_DISPATCH_POOL_REQUIRED_MESSAGE, DIRECT_DISPATCH_POOL_REQUIRED_SUGGESTION);
                continue;
            }
            allowed.add(rawId);
            allowedSlots.add(i);
            allowedBatches.addAll(byOrder.getOrDefault(rawId, List.of()));
        }
        if (!allowed.isEmpty()) {
            List<GenerateResult> generated = generate(allowed, allowedBatches, tenantId, operator,
                    assignmentRule);
            for (int k = 0; k < allowedSlots.size(); k++) {
                slots[allowedSlots.get(k)] = generated.get(k);
            }
        }
        return new ArrayList<>(java.util.Arrays.asList(slots));
    }

    /**
     * 批次指派 → {@code orderId → 逐行指派}（**任何写库之前**的唯一装配点；
     * 逐单派、池化派、成批预览三条路径共用 ⇒ ① 的 fail-closed 不可能只在一处生效）。
     *
     * <p>① 未匹配的指派（{@code orderId} 不在本次 {@code orderIds} 内）⇒ 显式拒绝
     * （静默丢掉 = 文员以为指定了、账上永远少一笔）。</p>
     */
    private static Map<String, List<BatchAssignment>> assignmentsByOrder(List<String> orderIds,
                                                                        List<BatchAssignment> batches) {
        List<BatchAssignment> assignments = batches == null ? List.of() : batches;
        Set<String> requested = new LinkedHashSet<>(orderIds);
        List<String> unknown = new ArrayList<>();
        for (BatchAssignment a : assignments) {
            String key = a == null ? null : a.getOrderId();
            if (key == null || !requested.contains(key)) {
                unknown.add(key == null ? "(空)" : key);
            }
        }
        if (!unknown.isEmpty()) {
            throw BusinessException.validationError(
                    "批次指派里的订单不在本次生成范围内：" + String.join(", ", unknown));
        }
        Map<String, List<BatchAssignment>> byOrder = new LinkedHashMap<>();
        for (BatchAssignment a : assignments) {
            byOrder.computeIfAbsent(a.getOrderId(), k -> new ArrayList<>()).add(a);
        }
        return byOrder;
    }

    private GenerateResult generateOne(String rawId, List<BatchAssignment> assignments,
                                       Long tenantId, String operator, String rule,
                                       Consignee consignee) {
        Prepared p = prepare(rawId, assignments, tenantId, operator, rule, consignee);
        // 不指派批次（本单没有指定、也没传规则）⇒ **一次都不调** plan：与 #5145 之前逐字相同
        // （「不指派 ⇒ 不扣批次、不产生台账行、不多一个错误分支」—— 连 mock 交互次数都不许多一次）
        List<StockBatchConsumptionService.Deduction> deductions = p.designations().isEmpty()
                ? List.of() : batchStock().plan(tenantId, p.designations());
        return commit(p, deductions, tenantId, operator);
    }

    /**
     * 池化成批派单（issue #5169 判据 2 的落点）—— 两段式：
     * <b>① 全部只读准备 → ② 池级一次性求解 → ③ 逐张落库</b>。
     *
     * <h2>为什么必须两段（不能边准备边落库）</h2>
     * 排料的成组要看**整个池子**：第 1 张单准备好时还不知道第 2 张单有没有可并排的块。
     * 故「写库」必须等到池级求解完成之后。而只读准备阶段**任何业务异常都还没写库**
     * ⇒ {@link #prepare} 抛错的那张单直接记 {@code fail} 并**不污染**其余单
     * （同 {@link #generateOne} 的既有纪律：异常不逸出事务边界 ⇒ 写库之后再抛就会留半成品）。
     *
     * <h2>结果顺序 = {@code orderIds} 顺序</h2>
     * 用下标槽位回填（不是「先追加成功的、再追加失败的」）—— 顺序也是判据 1 的一部分。
     */
    private List<GenerateResult> generatePooled(List<String> orderIds,
                                                Map<String, List<BatchAssignment>> byOrder,
                                                Long tenantId, String operator, String rule,
                                                Consignee consignee) {
        // 🔴 加急单**不进池**（issue #5177 判据 3）：混进成批批次 ⇒ 整批显式拒绝，**一行都不写**。
        // 放在 prepare 之前 ⇒ 拒绝时连只读准备都还没跑，更没有半成品。
        dispatchPool().assertNoUrgentInPooledBatch(orderIds, tenantId);
        dispatchPool().assertNoOutsourcedInPooledBatch(orderIds, tenantId);
        GenerateResult[] slots = new GenerateResult[orderIds.size()];
        List<Prepared> prepared = new ArrayList<>();
        List<Integer> indexes = new ArrayList<>();
        List<StockBatchConsumptionService.Designation> pooledLines = new ArrayList<>();
        for (int i = 0; i < orderIds.size(); i++) {
            String rawId = orderIds.get(i);
            try {
                Prepared p = prepare(rawId, byOrder.getOrDefault(rawId, List.of()), tenantId, operator,
                        rule, consignee);
                prepared.add(p);
                indexes.add(i);
                pooledLines.addAll(p.designations());
            } catch (BusinessException e) {
                slots[i] = GenerateResult.fail(rawId, e.getCode(), e.getMessage(), e.getSuggestion());
            }
        }
        if (!prepared.isEmpty()) {
            // 🔴 本单的核心：**只调一次** plan，候选块来自池内多张单 ⇒ 跨订单并排成立。
            // 成组键（批次 × 加工类型）在 plan 内部，本方法不碰（#5158 口径）。
            // 没有指派（`pooledLines` 为空）⇒ **一次都不调** plan：与逐单派的缺省路径逐字相同
            // （「不指派 ⇒ 不碰批次账」是 #5145 记录期的定义特征，见 generateOne 的同款守卫）。
            Map<String, List<StockBatchConsumptionService.Deduction>> byItemId = pooledLines.isEmpty()
                    ? Map.of() : deductionsByItemId(batchStock().plan(tenantId, pooledLines));
            for (int k = 0; k < prepared.size(); k++) {
                Prepared p = prepared.get(k);
                int slot = indexes.get(k);
                try {
                    slots[slot] = commit(p, deductionsOf(p, byItemId), tenantId, operator);
                } catch (BusinessException e) {
                    slots[slot] = GenerateResult.fail(orderIds.get(slot), e.getCode(), e.getMessage(),
                            e.getSuggestion());
                }
            }
        }
        List<GenerateResult> results = new ArrayList<>(orderIds.size());
        for (int i = 0; i < orderIds.size(); i++) {
            // 每个下标要么在上面的失败分支写过、要么在 commit 分支写过 ⇒ 恒非 null；
            // 非 BusinessException（如 DB 层错误）照旧逸出本方法（与逐单派同款：不吞异常）
            results.add(slots[i]);
        }
        return results;
    }

    private static Map<String, List<StockBatchConsumptionService.Deduction>> deductionsByItemId(
            List<StockBatchConsumptionService.Deduction> plan) {
        Map<String, List<StockBatchConsumptionService.Deduction>> out = new LinkedHashMap<>();
        for (StockBatchConsumptionService.Deduction d : plan) {
            out.computeIfAbsent(d.orderItemId(), k -> new ArrayList<>()).add(d);
        }
        return out;
    }

    private static List<StockBatchConsumptionService.Deduction> deductionsOf(Prepared p,
            Map<String, List<StockBatchConsumptionService.Deduction>> byItemId) {
        List<StockBatchConsumptionService.Deduction> out = new ArrayList<>();
        for (StockBatchConsumptionService.Designation d : p.designations()) {
            out.addAll(byItemId.getOrDefault(d.orderItemId(), List.of()));
        }
        return out;
    }

    /**
     * 一个订单的**只读准备结果**（池化两段式的第一段）：写库之前的全部校验、快照与工序计划。
     *
     * <p>{@code designations} 是**排料/扣减的入参**（池级求解的输入），
     * 而 {@code po} 已经建好（含加工单号）但**未插入** —— 插入与扣账都在 {@link #commit}。</p>
     */
    private record Prepared(String rawId, Order order, List<Map<String, Object>> snapshot,
                            List<Map<String, Object>> positions, ProcessingOrder po,
                            List<StockBatchConsumptionService.Designation> designations) {
    }

    /**
     * 承接方（外发加工厂）解析 —— 派单写面的**唯一**校验点（issue #7723）。
     *
     * <p>三条 fail-closed：① 档案存在且属本租户；② 在用；③ 类型 = 加工厂
     * （{@code processor}）—— 采购供应商不得被派成外发承接方。回厂日早于今天同样拒绝
     * （沿用 issue #3901 的交期边界）。校验失败 ⇒ 整批拒绝（{@link #generate} 在任何写库之前调用）。</p>
     */
    private Consignee resolveConsignee(String processorSupplierId, LocalDate expectedDeliveryDate,
                                       Long tenantId) {
        if (expectedDeliveryDate != null && expectedDeliveryDate.isBefore(today())) {
            throw BusinessException.validationError("回厂日不能早于今天");
        }
        if (!StringUtils.hasText(processorSupplierId)) {
            return new Consignee(null, null, expectedDeliveryDate);
        }
        if (supplierMapper() == null) {
            throw new IllegalStateException(
                    "SupplierMapper 未装配 —— 外发承接方不能静默当成「本厂自做」（issue #7723）");
        }
        Supplier supplier = supplierMapper().selectById(processorSupplierId);
        if (supplier == null || Boolean.TRUE.equals(supplier.getDeleted())
                || !tenantId.equals(supplier.getTenantId())) {
            throw BusinessException.validationError("承接方（加工厂）不存在：" + processorSupplierId);
        }
        if (!SupplierService.STATUS_ACTIVE.equals(supplier.getStatus())) {
            throw BusinessException.validationError(
                    "承接方「" + supplier.getName() + "」已停用，请先启用或换一家");
        }
        if (!SupplierService.TYPE_PROCESSOR.equals(supplier.getType())) {
            throw BusinessException.validationError(
                    "「" + supplier.getName() + "」不是加工厂（档案类型须为 processor）");
        }
        return new Consignee(supplier.getId(), supplier.getName(), expectedDeliveryDate);
    }

    public List<ProcessorOption> processorOptions(Long tenantId) {
        if (supplierMapper() == null) {
            return List.of();
        }
        List<Supplier> suppliers = supplierMapper().selectList(new LambdaQueryWrapper<Supplier>()
                .eq(Supplier::getTenantId, tenantId)
                .eq(Supplier::getStatus, SupplierService.STATUS_ACTIVE)
                .eq(Supplier::getType, SupplierService.TYPE_PROCESSOR)
                .orderByAsc(Supplier::getName));
        List<ProcessorOption> out = new ArrayList<>();
        for (Supplier supplier : suppliers) {
            out.add(new ProcessorOption(supplier.getId(), supplier.getName()));
        }
        return out;
    }

    private record Consignee(String supplierId, String name, LocalDate deliveryDate) {
    }

    private Prepared prepare(String rawId, List<BatchAssignment> assignments,
                             Long tenantId, String operator, String rule) {
        return prepare(rawId, assignments, tenantId, operator, rule, null);
    }

    private Prepared prepare(String rawId, List<BatchAssignment> assignments,
                             Long tenantId, String operator, String rule, Consignee consignee) {
        Order order = resolveOrder(rawId, tenantId);
        if (order == null) {
            throw new BusinessException("ORDER_NOT_FOUND", "无法找到订单：" + rawId, 404);
        }
        // 作业单可在**待付款 / 已确认**生成（issue #7626）—— 作业单是生产计划，
        // 不扣库存、不记资金；收款与扣减仍只在 `OrderService.confirmPayment`。
        if (!GENERATABLE_ORDER_STATUSES.contains(order.getStatus())) {
            throw BusinessException.validationError(
                    String.format("订单 %s 当前状态 [%s] 不允许生成加工单（须为待付款 / 已确认）",
                            order.getOrderNo(), order.getStatus()));
        }
        // 外发单**必须**指定承接方（issue #7746 后续）：外发标记的含义就是「交给外部加工厂做」，
        // 派单时却选「本厂自做」= 自相矛盾 ⇒ 显式拒绝（不静默按本厂派，也不静默忽略标记）。
        if (Boolean.TRUE.equals(order.getIsOutsourced())
                && (consignee == null || !StringUtils.hasText(consignee.supplierId()))) {
            throw BusinessException.validationError(
                    "订单 " + order.getOrderNo() + " 已标记为外发加工，派单时必须选择承接方（加工厂）",
                    List.of(),
                    "在「智能派单」页顶部选「承接方」（加工厂）后再派；若这单其实本厂自己做，"
                            + "先到订单详情把「外发加工」关掉");
        }
        List<OrderItem> items = loadOrderItems(order.getId(), tenantId);
        List<Map<String, Object>> snapshot = buildSnapshot(items, tenantId);
        if (snapshot.isEmpty()) {
            throw BusinessException.validationError("订单 " + order.getOrderNo() + " 无加工项，无需生成加工单");
        }
        // 订单级加急 / 客户要求到货日进快照（V120，issue #5177 范围 5）：**在加工单 insert 之前**写
        // `items_snapshot` —— 快照是加工单的**固化真相**，事后补不回来（与 commit() 里的
        // stampCuttingPlan / stampAssignedBatches 同一时机纪律）。
        stampOrderUrgency(snapshot, order);
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
        PositionPayload payload = positionPayloadBuilder().buildPositionPayload(snapshot, tenantId);
        List<Map<String, Object>> positions = payload.positions();

        // 派工指定批次（V116 / issue #5145 阶段 1）：**只读校验 + 计划在任何写库之前跑完** ——
        // 与上面工序 payload 同一条纪律（generate() 逐单 catch BusinessException 后事务不回滚 ⇒
        // 写库之后再抛业务异常会留下「有加工单、扣了半截」的半成品，见
        // StockBatchConsumptionService 类注释「写面分两段」）。
        List<StockBatchConsumptionService.Designation> designations =
                buildDesignations(items, snapshot, assignments, tenantId, rule);

        // 单据类型（V159，issue #7079）：与快照**同一时机**冻结 —— 卖布单（每一行 saleForm=布料）
        // 落 `outbound`（出库作业单），其余（含混合单）落 `processing`。事后改订单行不回改。
        String orderKind = deriveOrderKind(snapshot);
        // 出库作业单**没有加工环节**（#7079：不设加工方 / 交期）⇒ 外发承接方对它无意义。
        // 显式拒绝而不是静默忽略：静默忽略 = 商家以为这批卖布单已经发给加工厂了。
        if (orderKind.equals(ORDER_KIND_OUTBOUND) && consignee != null && consignee.supplierId() != null) {
            throw BusinessException.validationError(
                    "订单 " + order.getOrderNo() + " 是卖布单（出库作业单），只做出库作业，不支持外发加工厂");
        }

        ProcessingOrder po = ProcessingOrder.builder()
                .tenantId(tenantId)
                .orderId(order.getId())
                // 单号**不在这里生成**（P0-5）：取号必须与「占用它」同一条语句，见 commit() →
                // ProcessingOrderNoAllocator.insertWithFresh（撞号 ⇒ 换候选重试；不依赖进程内计数器）。
                .status("generated")
                .itemsSnapshot(snapshot)
                // 承接方 / 回厂日（V193，issue #7723）：**派单即写**（不再是作业单页上的「发加工」）。
                // 名称快照 + 档案引用同批落库；null = 本厂自做。
                .processor(consignee == null ? null : consignee.name())
                .processorSupplierId(consignee == null ? null : consignee.supplierId())
                .expectedDeliveryDate(consignee == null ? null : consignee.deliveryDate())
                .orderKind(orderKind)
                .templateVersion(1)
                .generatedBy(operator)
                .generatedAt(OffsetDateTime.now())
                .printCount(0)
                // 路线可观测（V60，issue #4308 P1）：这张单**实际走了哪条路线**、**想走哪条**、
                // **怎么来的**，三列一起落库 —— 此前 RouteKey.source 只在「路线缺失」的 error
                // 日志里被读一次，成功路径零痕迹 ⇒ 错配无数据可查。
                .routeKey(payload.routeKey())
                .routeRequestedKey(payload.routeRequestedKey())
                .routeSource(payload.routeSource())
                .deleted(0)
                .build();
        return new Prepared(rawId, order, snapshot, positions, po, designations);
    }

    /**
     * 落库（两段式的第二段）：快照盖章 → 插加工单 → 扣批次 → 实例化工序。
     *
     * <p>{@code deductions} 由调用方给出（逐单派 = 本单求解；池化派 = 池级求解里属于本单的那几行）
     * —— 本方法因此对「池化开了没有」无感，判据 3「不可成组 ⇒ 与逐单派逐值相同」是
     * **结构性**成立的，而不是靠分支对齐。</p>
     */
    private GenerateResult commit(Prepared p, List<StockBatchConsumptionService.Deduction> deductions,
                                  Long tenantId, String operator) {
        // 把**文员最终指定**的批次写进加工单快照的 batchNo（V63 白名单早有该键、此前全仓零写入方
        // = 现成的空插座）；在插入**之前**写，故不多一次 UPDATE。
        stampAssignedBatches(p.snapshot(), deductions);
        // 排料结果（V119 / issue #5158）同样在插入之前写进快照：应领米数 / 公式米数 / 省下的米数
        // —— 快照是固化真相，前端与车间都读它（批次侧另有逐行台账，两条路都可审计）。
        stampCuttingPlan(p.snapshot(), deductions);

        // 🔴 派单即生产（issue #7723，用户 2026-10-25 裁定 A）：订单 confirmed→producing 的
        // **唯一时点** 从「发加工」（#4305）挪到「派单」。为什么必须挪：发加工已不再是必经动作
        // （状态机放开 generated→in_processing）⇒ 仍留在那里的话，派单后没有任何人点它，
        // 订单就永远不会进 producing（作业单照做、订单永远「已确认」）。
        //
        // **联动先行 + 失败回退**（与 updateStatus 的 issue 分支同款 fail-closed）：先推进订单、
        // 再落作业单；随后任何写库失败都把订单回退 ⇒ 杜绝「订单生产中、作业单没生成」的孤儿态。
        // 待付款单**不动**（订单状态机没有 pending→producing；付款转 confirmed 后不会补推，
        // 这是存量缺口，本单不放大也不修 —— 见 issue #7723 的边界）。
        Order order = p.order();
        boolean orderLinked = OrderStatusTransitions.CONFIRMED.equals(order.getStatus());
        if (orderLinked) {
            orderService().lifecycleService().updateOrderStatus(order.getId(), OrderStatusTransitions.PRODUCING, orderService().sharedParts());
        }
        try {
            // 🔴 P0-5：单号在**落库那一刻**取（一条 INSERT … ON CONFLICT DO NOTHING 占号），
            // 撞号就换候选重试。改前是「进程内随机起点计数器先给号、之后再 insert」⇒ 并发/重启撞号时
            // 一律报「已生成」，而单子其实**没落库**（静默漏单）。实现见 ProcessingOrderNoAllocator。
            ProcessingOrderNoAllocator.insertWithFresh(
                    processingOrderMapper, objectMapper, businessClock(), order, p.po());
            log.info("生成加工单: no={}, orderId={}, tenantId={}, operator={}",
                    p.po().getProcessingOrderNo(), order.getId(), tenantId, operator);
        // 派工扣批次库存（issue #5145 判据 1）：与加工单生成**同一事务** ——
        // 加工单插入成功之后才扣（重复生成在更上游就被 selectActiveByOrderId +
        // uk_processing_orders_active 拒掉 ⇒ 不可能二次扣减）；计划已在插入前校验完，
        // 这里只落账、不再抛业务异常。不指定批次 ⇒ 计划为空 ⇒ 本段零动作（行为与今天逐字相同）。
            if (!deductions.isEmpty()) {
                batchStock().apply(tenantId, p.po().getProcessingOrderNo(), order.getOrderNo(), deductions);
            }
        // 工序实例化（issue #4116，P0 断链第一环）：加工单落行后**立即**实例化工序。
        // 此前 instantiate 端点全仓零调用者 ⇒ 工序列表恒空 ⇒ qr_token 恒 null ⇒
        // 任务卡只出「二维码待生成」占位、工人扫码报工不可达。
        // 工序序列已在插入前解析完毕（见 prepare 的 positions）：库取不到 ⇒ 根本走不到这里，
        // 所以本行的失败只可能是 DB 层错误 —— 那种情况异常逸出并由外层逐单
        // catch 记账，同样不留「有加工单、无工序」的静默半成品（工序另可由
        // POST .../instantiate 手工补做）。
            instantiateOperations(order, p.po(), p.positions(), tenantId);
            return GenerateResult.ok(p.rawId(), p.po().getProcessingOrderNo());
        } catch (RuntimeException e) {
            // 联动回退（issue #7723）：与 updateStatus 的 issue 分支同款 —— 落库失败 ⇒ 订单退回已确认，
            // 让商家刷新后能原样重派。回退自身失败只记 WARN（不掩盖主异常，也不能把主异常吞掉）。
            if (orderLinked) {
                try {
                    orderService().lifecycleService().revertProducingToConfirmed(order.getId(), "派单落库失败，订单状态回退");
                } catch (Exception revertErr) {
                    log.warn("派单落库失败且订单状态回退失败: orderId={}, err={}",
                            order.getId(), revertErr.getMessage());
                }
            }
            throw e;
        }
    }

    /**
     * 派工指定批次 → **只读校验 + 扣减入参**（必须在任何写库之前调用完）；**不**做池级求解
     * —— 求解在调用方（逐单派 = 本单一次 {@code plan}；池化派 = 池内多单一次 {@code plan}，
     * issue #5169 判据 2）。
     *
     * <p>逐行两件事：① 指派的行必须在该订单的加工单快照里（不在 ⇒ 显式拒绝 —— 配件/赠品行
     * 不成部位、不进快照，静默忽略会让文员以为指定了）；② 扣减米数 = 该行米数。</p>
     *
     * <p><b>两个米数（V119 / issue #5158）</b>：入参给 {@code StockBatchConsumptionService}
     * 的是**公式口径**（{@link StockQuantity#toStockScaleByCeiling} 后的订单行数量，与销售账扣减
     * **同一个函数**）+ 排料定尺要的三项（加工类型 / 窗高 / 分幅数，全部来自**快照**，即订单侧
     * 下单时落库的算料输出 —— Java 不重算幅数/褶倍/卷边）。扣多少米由
     * {@code StockBatchConsumptionService} 成组排料后决定（= 排料口径），本方法**不**替它算。</p>
     *
     * <p>两边同源是对账读面成立的前提：公式口径腿与销售账的扣减腿同函数 ⇒
     * 「{@code Σ批次余量} − {@code product_skus.stock}」的差额可以被拆成「已售未派」与
     * 「排料节省」两项而**不留口径差**（口径差会让差额读得出来却解释不清，正是路线 A 要防的漂移）。</p>
     *
     * <p><b>指派规则（issue #5167）</b>：{@code assignmentRule == null} = 调用方没传 ⇒ 未指定批次的行
     * **逐字**走原来的显式拒绝（缺省路径一字不改）；传了 ⇒ 只对未指定批次的行按规则补位
     * （{@link StockBatchConsumptionService#suggestedBatchNo}，与读面同一挑法），
     * 没有可满足批次 ⇒ 显式拒绝该行（不静默跳过 = 不静默少扣）。补位用的需求 = **公式口径**米数
     * （该行的领料上限），而实际扣减仍由 {@code plan} 按排料结果定（#5158 口径，本方法不碰）。</p>
     *
     * <p><b>SKU 码的取值键（issue #5174）</b>：逐行取快照**实际写入的键**（{@link #snapshotSkuCode}）。
     * 改前只有池化路径（#5169）这么取，既有路径读的是快照里**不存在**的 {@code skuCode} 键 ⇒ 恒 null
     * ⇒ 「批次 SKU 必须与订单行一致」这条判据与建议值的 SKU 过滤在**生产路径上从未生效**。
     * 取值键统一后两条路径在这一格上**同源**（其余口径本来就逐字相同：缺省拒绝、规则补位、
     * 米数、定尺入参）。</p>
     */
    private List<StockBatchConsumptionService.Designation> buildDesignations(
            List<OrderItem> items, List<Map<String, Object>> snapshot,
            List<BatchAssignment> assignments, Long tenantId, String assignmentRule) {
        if (assignments == null || assignments.isEmpty()) {
            return List.of();
        }
        Map<String, Map<String, Object>> rowByItemId = new LinkedHashMap<>();
        for (Map<String, Object> row : snapshot) {
            Object itemId = row.get("itemId");
            if (itemId != null) {
                rowByItemId.put(String.valueOf(itemId), row);
            }
        }
        Map<String, String> productIdByItemId = new LinkedHashMap<>();
        for (OrderItem item : items) {
            if (item.getId() != null) {
                productIdByItemId.put(item.getId(), item.getProductId());
            }
        }
        List<StockBatchConsumptionService.Designation> designations = new ArrayList<>();
        for (BatchAssignment a : assignments) {
            String itemId = a.getItemId() == null ? null : a.getItemId().trim();
            Map<String, Object> row = itemId == null ? null : rowByItemId.get(itemId);
            if (row == null) {
                throw BusinessException.validationError(String.format(
                        "批次指派的行 %s 不在本订单的加工单快照里（配件/赠品行不成部位，不参与派工指定）",
                        a.getItemId()));
            }
            // 缺省路径（没传规则）逐字不变：未指定批次 ⇒ 原样拒绝（错误码 / 文案 / 顺序都不动）
            if (!StringUtils.hasText(a.getBatchNo()) && assignmentRule == null) {
                throw BusinessException.validationError("批次指派缺少 batchNo（行 " + itemId + "）");
            }
            BigDecimal meters = StockQuantity.toStockScaleByCeiling(
                    row.get("quantity") instanceof BigDecimal q ? q : null);
            if (meters.compareTo(BigDecimal.ZERO) <= 0) {
                throw BusinessException.validationError(String.format(
                        "明细行 %s 的米数为 %s，无法指定批次扣减", itemId, meters.toPlainString()));
            }
            String batchNo = a.getBatchNo() == null ? null : a.getBatchNo().trim();
            // SKU 码（= 颜色 × 门幅）：**所有路径**都取快照实际写入的键（issue #5174；唯一入口见
            // {@link #snapshotSkuCode} —— 读错键会让整条 SKU 护栏 no-op）
            String skuCode = snapshotSkuCode(row);
            if (!StringUtils.hasText(batchNo)) {
                // 显式传了规则且该行没指定批次 ⇒ 按规则补位（建议值 = 直接采用）
                batchNo = batchStock().suggestedBatchNo(tenantId, productIdByItemId.get(itemId),
                        skuCode, meters, assignmentRule);
                if (!StringUtils.hasText(batchNo)) {
                    // 🔴 2026-10-17（issue #7077，用户逐字「得把报错原因用业务文案写清楚，而不是技术语言」）：
                    // 旧文案把**内部规则码**（`fifo` / `best_fit`）与**明细行 id**（UUID）端给商家
                    // —— 两句都是他照着做不了的读数。现在说清四件事：哪一行（商品名）/ 要多少米 /
                    // 为什么补不上（按「先到先用」也找不到能整行裁出的批次）/ 下一步做什么（入库或核对余量）。
                    // ⚠️ 判据 `ProcessingOrderServiceTest#noCandidateUnderTheRuleFailsClosed` 同时钉
                    // 「新文案在」与「内部标识符不在」两条（把任一句写回去 ⇒ 红）。
                    String productName = str(row.get("productName"));
                    String lineLabel = StringUtils.hasText(productName) ? productName : "这一行";
                    throw BusinessException.validationError(String.format(
                            "「%s」这行需要 %s 米，库存里没有能裁出它的批次（按「先到先用」也补不上）"
                                    + "—— 请先把这批布入库，或核对库存里对应门幅与颜色的余量后重试",
                            lineLabel, meters.toPlainString()));
                }
            }
            designations.add(new StockBatchConsumptionService.Designation(
                    itemId, productIdByItemId.get(itemId), skuCode,
                    batchNo, meters,
                    // 排料定尺入参（V119 / issue #5158）：**逐字来自快照**（下单时落库的算料输出）
                    str(row.get("cuttingMode")),
                    OrderLineCraftFields.decimalOrNull(row.get("height"), "快照行 " + itemId + " 的窗高"),
                    OrderLineCraftFields.integerOrNull(row.get("panels"), "快照行 " + itemId + " 的分幅数")));
        }
        return designations;
    }

    /**
     * 实例化工序（issue #4116 切库后：工序来源 = **工序库**，不再是加工项目录）。
     *
     * <p><b>工序来源（本包的核心变更；P2b 起为新结构）</b>：`production_route_templates`（主线）
     * + `production_route_rules`（规则）+ `production_operation_positions`（部位价目/适用性）
     * + `production_operations`（每道工序的分组/单位/必完标记/作用域），全部是**库里的行**，
     * 由 {@link ProductionOperationQueryService} 的新读面读出（见 {@link ProcessingRouteResolver#buildRoute}）。加工项目录（快照里的
     * `processingItems`）自此刻起**只**用于①派生路线键的信号、②加工单快照本身的展示，
     * **不再**提供工序 —— 旧的「工序 = 加工项名」路径已删除，取不到库数据时**显式失败**，
     * 不回退（回退会让「切库」变成装饰性的：旧路径还在 ⇒ 库为空也没人发现）。</p>
     *
     * <p><b>取路线判据</b>（订单侧**没有**部位/帘种字段，故必须显式定义取法）：按可派生信号
     * 匹配 `curtain_type`/`craft`，优先级 = 加工项名 &gt; 加工项 options &gt; 商品名 &gt; 销售方式，
     * 命中即止；两类信号全不命中 ⇒ 该租户的**默认路线模板**（见 {@link ProcessingRouteResolver#deriveRouteKey}
     * 与 {@link ProcessingRouteResolver#resolveRoute}）。</p>
     *
     * <p><b>`is_start_marker` 读库</b>：取 `production_operations` 的同名列。
     * 🔴 `is_must_finish`（必完）**已退场**（#4961，用户裁定 2026-09-21「完工 = 全部工序全绿」）：
     * 实例化 payload **不再带该键**（列保留为历史载体），完工判据改看「全部实例完成」。</p>
     */
    private void instantiateOperations(Order order, ProcessingOrder po,
                                       List<Map<String, Object>> positions, Long tenantId) {
        if (positions.isEmpty()) {
            log.warn("加工单无可用部位派生工序，跳过自动实例化（可用手工端点补做）: no={}, orderId={}",
                    po.getProcessingOrderNo(), order.getId());
            return;
        }
        productionService().instantiate(order.getId(), Map.of("positions", positions), tenantId);
    }
}
