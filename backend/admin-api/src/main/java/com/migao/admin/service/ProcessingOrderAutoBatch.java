package com.migao.admin.service;

import com.migao.admin.dto.BatchStockViews;
import com.migao.admin.dto.ProcessingOrderGenerateRequest.BatchAssignment;
import com.migao.admin.dto.ProductionPoolViews;
import com.migao.admin.exception.BusinessException;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

import static com.migao.admin.service.ProcessingOrderService.*;

/**
 * 加工单**自动批次决策族**单元（issue #8770「自动批次」一档，从 {@link ProcessingOrderService} **纯搬运**）。
 *
 * <p><b>单一职责</b>：回答「现在这批池内订单该不该派、按哪条规则派、派哪几张、失败怎么降级」——
 * 成批条件 ①②③ 的判定、业务兜底的最晚派单日判定、三级 fail-soft 降级、理由文案与
 * {@code generated_by} 持久痕迹的装配。<b>不写库</b>：本类一次 {@code insert} / {@code update} 都没有，
 * 写库仍经门面的 {@code generate(...)} / {@code generatePooled(...)}（{@link Owner#generate}）。</p>
 *
 * <p><b>搬运口径</b>：方法体、注释、理由文案、降级顺序<b>一字未改</b>。改动只有四类，逐条可复算：
 * ① 两段方法体（事件腿 / 定时腿）搬成 {@link #dispatch} / {@link #dispatchDue}，策略归一那一行
 * <b>留在门面</b>；② 4 行外呼换成窄接口 {@link Owner}（{@code pool} / {@code generate} /
 * {@code today} / {@code batchStock}）；③ 类头与两个新入口的 javadoc；④ 门面侧 4 行委托与惰性接线。</p>
 *
 * <p><b>为什么 {@code generate} 不搬</b>：它带 {@code @Transactional} 且是写库路径的入口；
 * 搬出去会改「自调用不走代理」这一既有时序（真实形态见上一档的重启条件：
 * 「生成族先落真库事务判据再搬」）。本类只做**决策**，写库留在门面。</p>
 *
 * <p><b>为什么公开面（{@code AutoBatchPolicy} / {@code AutoBatchOutcome} / {@code AUTO_BATCH_*} 常量 /
 * {@code autoBatchPolicy()} / 两个 {@code latestDispatchDate}·{@code dueReason} 纯函数）不搬</b>：
 * 它们被 {@code AutoBatchDispatchListener} / {@code AutoBatchDueScanService} / 既有判据按
 * {@code ProcessingOrderService.X} 取 —— 搬走 = 删掉被断言的对象（#8681 第十批裁定）。</p>
 */
class ProcessingOrderAutoBatch {

    /**
     * 自动批次对门面的外呼面（**都不是本类的事实**：池读面、写库入口、业务时钟、算料服务仍住门面）。
     *
     * <p>每次调用**即时取值**（{@code Owner} 的实现体在调用点读字段）—— 既有判据用
     * {@code ReflectionTestUtils.setField} 在构造之后换时钟 / 换算料服务，缓存会读到旧值。</p>
     */
    interface Owner {
        ProductionPoolViews.Pool pool(Long tenantId, BigDecimal maxWaitHours);

        List<GenerateResult> generate(List<String> orderIds, List<BatchAssignment> assignments,
                                      Long tenantId, String operator, String rule, Boolean pooled);

        LocalDate today();

        StockBatchConsumptionService batchStock();
    }

    private final Owner owner;

    ProcessingOrderAutoBatch(Owner owner) {
        this.owner = owner;
    }

    private LocalDate today() {
        return owner.today();
    }

    private StockBatchConsumptionService batchStock() {
        return owner.batchStock();
    }

    /**
     * 事件腿的决策主体（从门面 {@code autoBatchDispatch(tenantId, trigger, policy)} **纯搬运**：
     * 方法体、注释、理由文案与降级顺序一字未改）。
     *
     * <p>三段（顺序即优先级）：① 加急逐单立即派 → ② 按物料组判条件 ①②③ → ③ 业务兜底（不可取消）。
     * 策略归一（{@code policyRaw == null ? autoBatchPolicy() : policyRaw}）留在门面 ——
     * 它读的是门面自己的 {@code @Value} 字段，不是本类的事实。</p>
     */
    AutoBatchOutcome dispatch(Long tenantId, String trigger, AutoBatchPolicy policy) {
        if (tenantId == null || !policy.enabled()) {
            // 🔴 判据 1（#6588 重写）：**显式关** ⇒ 零读零写（连池都不查）。
            // 缺省已翻成「开」⇒ 本条钉的从「缺省不动数据」变成「关闸真的关得上」。
            return new AutoBatchOutcome(false, trigger, null, List.of(), List.of(), List.of(), List.of());
        }
        String rule = StockBatchConsumptionService.normalizeAssignmentRule(policy.assignmentRule());
        String operator = AUTO_BATCH_OPERATOR_PREFIX + trigger + ":" + rule;
        List<String> reasons = new ArrayList<>();
        List<String> dispatched = new ArrayList<>();
        List<String> failedIds = new ArrayList<>();
        List<String> failures = new ArrayList<>();

        ProductionPoolViews.Pool pool = owner.pool(tenantId, policy.maxWaitHours());
        Map<String, List<ProductionPoolViews.PoolLine>> linesByOrder = linesByOrderOf(pool);

        // ① 加急单永不入池 ⇒ 自动**立即派**（逐单、pooled=false —— 判据 5）
        for (ProductionPoolViews.PoolLine line : pool.urgentLines()) {
            String orderId = line.orderId();
            if (orderId == null || !linesByOrder.containsKey(orderId)) {
                continue;
            }
            reasons.add("order=" + line.orderNo() + ":urgent_never_pooled");
            List<ProductionPoolViews.PoolLine> lines = linesByOrder.remove(orderId);
            collect(dispatchAuto(List.of(orderId), assignmentsOf(lines), tenantId, operator, rule, false),
                    trigger, dispatched, failedIds, failures);
        }

        // ② 成批条件（任一满足即成批）：按**物料组**判、按**订单**派（一单一加工单是既有约束）
        List<String> batchOrderIds = new ArrayList<>();
        for (ProductionPoolViews.PoolGroup group : pool.groups()) {
            String reason = batchConditionReason(group, tenantId, policy);
            if (reason == null) {
                continue;
            }
            reasons.add(reason);
            for (ProductionPoolViews.PoolLine line : group.lines()) {
                if (line.orderId() != null && !batchOrderIds.contains(line.orderId())) {
                    batchOrderIds.add(line.orderId());
                }
            }
        }
        // 一单一加工单：派一张单会带上它的**全部**行（含未命中条件的另一物料组）
        // ⇒ 指派也按「该单的全部池行」装配（否则另一物料组会被静默漏扣）。
        if (!batchOrderIds.isEmpty()) {
            collect(dispatchAuto(batchOrderIds, assignmentsOf(pluck(linesByOrder, batchOrderIds)),
                            tenantId, operator, rule, true),
                    trigger, dispatched, failedIds, failures);
        }

        // ③ 业务兜底（**不可取消**）：最晚派单日已到 ⇒ 必派（判据 4）
        //   ⇒ 与定时腿（issue #5184）**共用同一实现**（dispatchDueOrders）：判定写两遍必然漂移，
        //     而「到日必派」一旦分叉，就会出现「事件腿认为到期、定时腿认为没到期」的静默压单。
        dispatchDueOrders(linesByOrder, tenantId, trigger, operator + ":due", policy, rule,
                reasons, dispatched, failedIds, failures);

        return new AutoBatchOutcome(true, trigger, rule, List.copyOf(reasons),
                List.copyOf(dispatched), List.copyOf(failedIds), List.copyOf(failures));
    }

    /** 定时腿的决策主体（从门面 {@code autoBatchDispatchDue(...)} **纯搬运**：只做业务兜底，不判 ①②③）。 */
    AutoBatchOutcome dispatchDue(Long tenantId, String trigger, AutoBatchPolicy policy) {
        if (tenantId == null || !policy.enabled()) {
            // 🔴 判据 4（#6588 重写）：**显式关** ⇒ 零读零写（与 autoBatchDispatch 同一条判断，不另立口径）
            return new AutoBatchOutcome(false, trigger, null, List.of(), List.of(), List.of(),
                    List.of());
        }
        String rule = StockBatchConsumptionService.normalizeAssignmentRule(policy.assignmentRule());
        // 触发原因直接就是痕迹的一部分（**不**再追加 `:due` —— `due_scan` 已经说明了「为什么派」）；
        // 形态与事件腿**逐字同款**：`auto:<触发原因>:<规则>`（判别只看这一段）。
        String operator = AUTO_BATCH_OPERATOR_PREFIX + trigger + ":" + rule;
        List<String> reasons = new ArrayList<>();
        List<String> dispatched = new ArrayList<>();
        List<String> failedIds = new ArrayList<>();
        List<String> failures = new ArrayList<>();
        dispatchDueOrders(linesByOrderOf(owner.pool(tenantId, policy.maxWaitHours())), tenantId, trigger,
                operator, policy, rule, reasons, dispatched, failedIds, failures);
        return new AutoBatchOutcome(true, trigger, rule, List.copyOf(reasons),
                List.copyOf(dispatched), List.copyOf(failedIds), List.copyOf(failures));
    }

    /**
     * 业务兜底段的**唯一实现**（事件腿的 ③ 与定时腿 {@link #autoBatchDispatchDue} 共用）。
     *
     * <p>判据 = {@code 今天 ≥ 最晚派单日}：{@code 有客户要求到货日 ⇒ 到货日 − 标准生产周期}；
     * {@code 无 ⇒ 进池日 + 标准生产周期}（见 {@link #latestDispatchDate}）。到日 ⇒ 必派，**不看条件**。</p>
     *
     * <p>🔴 <b>与等待时长无关</b>：本方法<b>不读</b> {@code PoolLine.waitHours()} / {@code overdue()}
     * —— 池化窗口（{@code maxWaitHours}）是**优化参数**、只决定看板多早告警；把它当派单死线正是
     * issue #5182/#5184 明令排除的形态。红证：把本方法的判据换成 {@code line.overdue()}
     * ⇒ 「超窗但未到期 ⇒ 不派」那条判据当场红（见 {@code scripts/auto-batch-due-scan-red-proof.py}）。</p>
     */
    private void dispatchDueOrders(Map<String, List<ProductionPoolViews.PoolLine>> linesByOrder,
                                   Long tenantId, String trigger, String operator,
                                   AutoBatchPolicy policy, String rule, List<String> reasons,
                                   List<String> dispatched, List<String> failedIds,
                                   List<String> failures) {
        LocalDate today = today();
        List<String> dueOrderIds = new ArrayList<>();
        List<String> dueReasons = new ArrayList<>();
        for (Map.Entry<String, List<ProductionPoolViews.PoolLine>> entry : linesByOrder.entrySet()) {
            ProductionPoolViews.PoolLine first = entry.getValue().get(0);
            LocalDate latest = latestDispatchDate(first, policy.standardCycleDays());
            if (latest == null || today.isBefore(latest)) {
                continue;
            }
            dueOrderIds.add(entry.getKey());
            dueReasons.add(dueReason(first, latest));
        }
        if (dueOrderIds.isEmpty()) {
            return;
        }
        reasons.addAll(dueReasons);
        collect(dispatchAuto(dueOrderIds, assignmentsOf(pluck(linesByOrder, dueOrderIds)),
                        tenantId, operator, rule, true),
                trigger, dispatched, failedIds, failures);
    }

    /**
     * 成批条件判定（判据 3）：满足**任一** ⇒ 返回命中的那条规则（可读，进 {@code reasons} 痕迹）；
     * 都不满足 ⇒ {@code null}（**不派**）。
     *
     * <h2>三个条件的口径（写在这里一次）</h2>
     * <ul>
     *   <li><b>① 填满某批次 ≥ X%</b>：{@code 该物料组需求米数 ≥ X% × 某批次入库量}
     *       —— 分母是**入库量**（"填满一个整批"的字面口径；批次余量见 ②）。</li>
     *   <li><b>② 余量收敛到 ≤ N 米</b>：{@code 0 ≤ 该批次余量 − 需求米数 ≤ N}
     *       —— 「这批单正好把某一批用到见底」，N 缺省 0.2（与余量分布四档的 `≤0.2m` 同界）。</li>
     *   <li><b>③ 池内同物料需求 ≥ 最小批量</b>：{@code 需求米数 ≥ 阈值}。</li>
     * </ul>
     *
     * <p>⚠️ 这是**触发口径**（用一个可解释的算式回答"值不值得现在凑一批"），
     * 不是排料结果 —— 真正扣多少米由 {@code StockBatchConsumptionService.plan} 在派单时决定
     * （判据 6 的「口径一致」说的是**落账**与**预览**同源，不是触发口径等于排料口径）。
     * 触发口径保守（绝不高估收益）⇒ 不会因为"以为能省"而误派。</p>
     *
     * @return 命中的规则（含材料键与读数）；{@code null} = 三条都不满足 ⇒ 不成批
     */
    String batchConditionReason(ProductionPoolViews.PoolGroup group, Long tenantId,
                                AutoBatchPolicy policy) {
        BigDecimal demand = StockQuantity.orZero(group.requiredMeters());
        if (demand.signum() <= 0) {
            return null;
        }
        if (demand.compareTo(policy.minBatchMeters()) >= 0) {
            return String.format("material=%s:condition=min_batch(demand=%s>=%s)", group.materialKey(),
                    demand.toPlainString(), policy.minBatchMeters().toPlainString());
        }
        List<BatchStockViews.BatchRemaining> batches = batchesOfMaterial(tenantId, group);
        BigDecimal hundred = BigDecimal.valueOf(100);
        BigDecimal ratio = BigDecimal.valueOf(policy.fillRatioPercent());
        for (BatchStockViews.BatchRemaining batch : batches) {
            BigDecimal inbound = StockQuantity.orZero(batch.inboundMeters());
            if (inbound.signum() > 0 && demand.multiply(hundred).compareTo(ratio.multiply(inbound)) >= 0) {
                return String.format("material=%s:condition=fill_ratio(demand=%s>=%s%%×batch[%s]=%s)",
                        group.materialKey(), demand.toPlainString(), ratio.toPlainString(),
                        batch.batchNo(), inbound.toPlainString());
            }
            BigDecimal after = StockQuantity.orZero(batch.remainingMeters()).subtract(demand);
            if (after.signum() >= 0 && after.compareTo(policy.convergeMeters()) <= 0) {
                return String.format("material=%s:condition=converge(demand=%s,batch[%s]余量=%s⇒%s<=%s)",
                        group.materialKey(), demand.toPlainString(), batch.batchNo(),
                        StockQuantity.orZero(batch.remainingMeters()).toPlainString(),
                        after.toPlainString(), policy.convergeMeters().toPlainString());
            }
        }
        return null;
    }

    /**
     * 自动派单的**三级尝试**（判据 10 的 fail-soft 落点）。
     *
     * <p>① 整批一次（成批 = {@code pooled=true} ⇒ 跨订单成组；加急 = 逐单 {@code pooled=false}）
     * → ② 对失败的**逐单 + 规则**（池级累计余量不足是池化**新出现**的失败面：
     * 两张单各要 3 米而批次只剩 5 米，逐单看各自都够）
     * → ③ 对仍失败的**逐单 + 不带规则**（#5145 之前的缺省形态：不碰批次账）。
     * 三级都失败才记失败 —— 「不能损失客户」不等于「假装成功」，失败照实留痕。</p>
     *
     * <p>重试**不会重复派**：① 里成功的单不在重试集里，而失败的判定依据
     * （{@code selectActiveByOrderId} + {@code uk_processing_orders_active}）是 fail-closed 的
     * —— 已经有加工单的单在②③里同样被拒（判据 7）。</p>
     */
    private List<AutoLine> dispatchAuto(List<String> orderIds, List<BatchAssignment> assignments,
                                        Long tenantId, String operator, String rule, Boolean pooled) {
        List<AutoLine> lines = new ArrayList<>();
        List<String> retry = new ArrayList<>();
        List<GenerateResult> results = generateSafely(orderIds, assignments, tenantId, operator, rule, pooled);
        for (int i = 0; i < orderIds.size(); i++) {
            GenerateResult r = i < results.size() ? results.get(i) : null;
            if (r != null && r.isSuccess()) {
                lines.add(new AutoLine(orderIds.get(i), true, r.getProcessingOrderNo()));
            } else {
                retry.add(orderIds.get(i));
            }
        }
        for (String orderId : retry) {
            GenerateResult one = firstOf(generateSafely(List.of(orderId),
                    assignmentsOfOrder(assignments, orderId), tenantId, operator + ":single", rule, false));
            if (one != null && one.isSuccess()) {
                lines.add(new AutoLine(orderId, true, one.getProcessingOrderNo()));
                continue;
            }
            GenerateResult plain = firstOf(generateSafely(List.of(orderId), List.of(), tenantId,
                    operator + ":plain", null, false));
            if (plain != null && plain.isSuccess()) {
                lines.add(new AutoLine(orderId, true, plain.getProcessingOrderNo()));
                continue;
            }
            lines.add(new AutoLine(orderId, false, messageOf(plain != null ? plain : one)));
        }
        return lines;
    }

    /**
     * {@link #generate} 的**不抛**包装：整批显式拒绝（池级求解失败 / 非法规则 / 累计余量不足）
     * ⇒ 逐单记失败，交给 {@link #dispatchAuto} 的降级重试。
     *
     * <p>{@code generate} 是 {@code @Transactional(rollbackFor = Exception.class)}：
     * 异常逸出 ⇒ 该次调用<b>整体回滚</b>（池级求解发生在任何写库之前，见 {@code generatePooled}）
     * ⇒ 这里的重试**不可能**撞上"写了一半"的中间态。</p>
     */
    private List<GenerateResult> generateSafely(List<String> orderIds, List<BatchAssignment> assignments,
                                                Long tenantId, String operator, String rule, Boolean pooled) {
        try {
            return owner.generate(new ArrayList<>(orderIds), assignments, tenantId, operator, rule, pooled);
        } catch (RuntimeException e) {
            String message = e instanceof BusinessException be ? be.getMessage() : String.valueOf(e);
            String code = e instanceof BusinessException be ? be.getCode() : "AUTO_BATCH_DISPATCH_FAILED";
            String suggestion = e instanceof BusinessException be ? be.getSuggestion() : null;
            List<GenerateResult> out = new ArrayList<>();
            for (String orderId : orderIds) {
                out.add(GenerateResult.fail(orderId, code, message, suggestion));
            }
            return out;
        }
    }

    /** 池行按订单归拢（**包含加急行与每个物料组**；一单一加工单 ⇒ 派一张单要带上它的全部行）。 */
    private static Map<String, List<ProductionPoolViews.PoolLine>> linesByOrderOf(
            ProductionPoolViews.Pool pool) {
        Map<String, List<ProductionPoolViews.PoolLine>> out = new LinkedHashMap<>();
        for (ProductionPoolViews.PoolLine line : pool.urgentLines()) {
            if (line.orderId() != null) {
                out.computeIfAbsent(line.orderId(), k -> new ArrayList<>()).add(line);
            }
        }
        for (ProductionPoolViews.PoolGroup group : pool.groups()) {
            for (ProductionPoolViews.PoolLine line : group.lines()) {
                if (line.orderId() != null) {
                    out.computeIfAbsent(line.orderId(), k -> new ArrayList<>()).add(line);
                }
            }
        }
        return out;
    }

    /** 取出这几个订单的池行并**从索引里移除**（已处理过的单不参与后续段/不重复装配指派）。 */
    private static List<ProductionPoolViews.PoolLine> pluck(
            Map<String, List<ProductionPoolViews.PoolLine>> linesByOrder, List<String> orderIds) {
        List<ProductionPoolViews.PoolLine> out = new ArrayList<>();
        for (String orderId : orderIds) {
            List<ProductionPoolViews.PoolLine> lines = linesByOrder.remove(orderId);
            if (lines != null) {
                out.addAll(lines);
            }
        }
        return out;
    }

    /**
     * 池行 → 批次指派（{@code batchNo} **留空** ⇒ 由 {@code assignmentRule} 按 #5167 的规则补位）。
     *
     * <p>自动路径没有文员来指定批次，故逐行「有这一行、批次待定」；规则无效/无候选批次
     * ⇒ {@code buildDesignations} 抛业务异常 ⇒ 该单在①失败、由②③降级兜住（fail-soft）。</p>
     */
    private static List<BatchAssignment> assignmentsOf(List<ProductionPoolViews.PoolLine> lines) {
        List<BatchAssignment> out = new ArrayList<>();
        for (ProductionPoolViews.PoolLine line : lines) {
            if (line.orderId() == null || line.itemId() == null) {
                continue;
            }
            BatchAssignment a = new BatchAssignment();
            a.setOrderId(line.orderId());
            a.setItemId(line.itemId());
            out.add(a);
        }
        return out;
    }

    private static List<BatchAssignment> assignmentsOfOrder(List<BatchAssignment> assignments,
                                                            String orderId) {
        List<BatchAssignment> out = new ArrayList<>();
        for (BatchAssignment a : assignments) {
            if (Objects.equals(a.getOrderId(), orderId)) {
                out.add(a);
            }
        }
        return out;
    }

    /** 某物料的批次读数（余量口径 = 入库量 + Σ消耗，与余量分布/对账**同一函数**）。 */
    private List<BatchStockViews.BatchRemaining> batchesOfMaterial(Long tenantId,
                                                                   ProductionPoolViews.PoolGroup group) {
        List<BatchStockViews.BatchRemaining> out = new ArrayList<>();
        for (BatchStockViews.BatchRemaining batch
                : batchStock().remaining(tenantId, group.productId(), null, false)) {
            // SKU 一致性口径与 plan / suggestedBatchNo **同源**（有一侧没记 ⇒ 不作不一致判定）
            if (!StringUtils.hasText(group.skuCode()) || !StringUtils.hasText(batch.skuCode())
                    || group.skuCode().equals(batch.skuCode())) {
                out.add(batch);
            }
        }
        return out;
    }

    private void collect(List<AutoLine> lines, String trigger, List<String> dispatched,
                         List<String> failedIds, List<String> failures) {
        for (AutoLine line : lines) {
            if (line.success()) {
                dispatched.add(line.detail());
            } else {
                failedIds.add(line.orderId());
                failures.add(String.format("trigger=%s, orderId=%s: %s", trigger, line.orderId(),
                        line.detail()));
            }
        }
    }

    private static GenerateResult firstOf(List<GenerateResult> results) {
        return results == null || results.isEmpty() ? null : results.get(0);
    }

    private static String messageOf(GenerateResult r) {
        return r == null ? "自动派单未返回结果" : r.getMessage();
    }

    /** 自动派单里**一张单的最终结局**（三级尝试之后；{@code detail} = 加工单号或失败文案）。 */
    private record AutoLine(String orderId, boolean success, String detail) {
    }
}
