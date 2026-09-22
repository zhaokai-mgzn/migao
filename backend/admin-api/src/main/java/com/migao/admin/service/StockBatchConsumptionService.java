package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.migao.admin.dto.BatchStockViews;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.SavingMetricViews;
import com.migao.admin.entity.FabricRemnant;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.entity.StockBatch;
import com.migao.admin.entity.StockBatchConsumption;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.StockBatchConsumptionMapper;
import com.migao.admin.mapper.StockBatchMapper;
import com.migao.admin.mapper.StockLedgerMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * 批次消耗台账服务（V116，issue #5145 阶段 1）—— 派工扣批次的**写面**与批次账的**读面**。
 *
 * <h2>两本账（用户裁定「路线 A」，本单不再讨论）</h2>
 * <ul>
 *   <li><b>SKU 账 = 销售账</b>：{@code product_skus.stock}，随支付扣（{@code OrderService.confirmPayment}）
 *       —— 本单<b>一字不动</b>（「不能损失客户」的命门）。</li>
 *   <li><b>批次账 = 实物账</b>：本服务，随**加工单生成**扣、随**加工单作废**回补。</li>
 * </ul>
 * 两账必然有差额（已售未派 / 公式口径 vs 实际 / 存量无批次来源）⇒ 路线 A 的**交换条件**是
 * {@link #reconcile} 这个读面：差额必须**读得出、可解释**，不得静默漂移。
 *
 * <h2>余量是派生值</h2>
 * {@code remaining = stock_batches.quantity + Σ(delta)} —— **不原地改** {@code stock_batches.quantity}
 * （V111 裁定「批次行不可改、冲销走新单据」）。{@code delta} 带符号：负 = 扣减、正 = 回补。
 *
 * <h2>写面分两段（plan → apply）—— 为什么必须分开</h2>
 * {@code ProcessingOrderService.generate} 逐单 {@code catch (BusinessException)} 记账后继续处理其余单，
 * 而**异常不逸出事务边界 ⇒ 不会回滚**。⇒ 若在写库之后再抛业务异常，就会留下「有加工单、扣了半截」
 * 的半成品（同 #4116 对工序实例 payload 的处置）。故本服务的纪律是：
 * <b>{@link #plan} 只读校验（任何业务异常都在这里抛完）；{@link #apply} 只落账、不再抛业务异常。</b>
 *
 * <h2>扣减米数 = 排料口径（V119，issue #5158）—— 「省料」真正产生的地方</h2>
 * 本单之前，扣减米数 = 公式米数（{@code toStockScaleByCeiling(order_items.quantity)}）⇒ 哪怕排料
 * 能省，批次账照旧按公式扣（#5142 的排料器因此只是积木、省不了一米）。本单起：
 * <ol>
 *   <li>按「**批次 × 加工类型**」成组调用 {@link CuttingPlanCalculator}（同批次 = 同一卷布，
 *       跨批次成组是虚报 —— 理由见 {@link #cuttingPlanByItemId}）；</li>
 *   <li>组的应领米数按各行公式米数占比分摊回行，再经
 *       {@link StockQuantity#toStockScaleByCeiling}（**领料量归一的唯一入口**，公式口径与排料口径
 *       共用同一个函数）归一到 0.1 ⇒ 实际扣减 = 排料结果，**省下的米数留在批次余量上**；</li>
 *   <li>两个口径的米数**都落库**（{@code formula_meters} / {@code planned_meters}）+
 *       **当时**该批次均价快照（{@code unit_cost}）⇒ 事后能逐单回答「省了多少米、多少钱」
 *       （#5159 L1），且换价后历史单的 {@code saved_amount} 不变。</li>
 * </ol>
 * <p>排不了料（工艺未知 / 缺窗高或幅数 / 门幅没记 / 取不到上下卷边 / 排料器报错）⇒ 该组
 * **逐值退回公式口径**（saved = 0）：排料是优化，不是加工单生成的正确性前提
 * （「宁可为 0，不许估」，且绝不因为优化失败让加工单生成不了）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class StockBatchConsumptionService {

    /** 变更来源：派加工单扣减 */
    public static final String REASON_PROCESSING_ORDER = StockBatchConsumption.REASON_PROCESSING_ORDER;
    /** 变更来源：加工单作废回补 */
    public static final String REASON_PROCESSING_ORDER_CANCELLED =
            StockBatchConsumption.REASON_PROCESSING_ORDER_CANCELLED;

    /** 批次不存在 / 不属于当前租户（错误码，可被前端与 agent 判读） */
    public static final String ERR_BATCH_NOT_FOUND = "BATCH_NOT_FOUND";
    /** 批次不属于该 SKU（指定错了货） */
    public static final String ERR_BATCH_SKU_MISMATCH = "BATCH_SKU_MISMATCH";
    /** 批次余量不足（fail-closed：**不得静默少扣**） */
    public static final String ERR_BATCH_STOCK_INSUFFICIENT = "BATCH_STOCK_INSUFFICIENT";
    /** 未知的指派规则（fail-closed：**不得静默回落 fifo**，见 {@link #normalizeAssignmentRule}） */
    public static final String ERR_ASSIGNMENT_RULE_UNKNOWN = "ASSIGNMENT_RULE_UNKNOWN";

    /** 阶段 1 的建议值口径（**朴素**，显式回给读的人 —— 阶段 2 才换 best-fit，见 #5144） */
    public static final String SUGGESTION_RULE_FIFO = "FIFO_RECEIVED_DATE";
    /** best-fit 的建议值口径（余量最接近需求者优先，issue #5167）：读面据此判别当前生效的是哪条规则 */
    public static final String SUGGESTION_RULE_BEST_FIT = "BEST_FIT_REMAINING";

    /**
     * 指派规则：**入库日期早者优先**（= 缺省值）。
     *
     * <p>它同时是「阶段 1 行为」的别名：不传规则 ⇒ 建议值与候选顺序与今天**逐值相同**
     * （#5145 记录期的定义特征 ⇒ 基线可比，见 issue #5167「默认必须关」）。</p>
     */
    public static final String ASSIGNMENT_RULE_FIFO = "fifo";

    /**
     * 指派规则：**余量最接近需求者优先**（best-fit，issue #5167）—— 目标 = 让批次被用尽，
     * 治「企业剩余大量 0.5 米左右批次」这个痛点。
     *
     * <p>只在「能满足需求」（{@code remaining ≥ need}）的候选里挑**余量最小**者；
     * 余量相同 ⇒ 先入库者优先（平局裁决 = FIFO 序，故候选列表的既有顺序就是裁决，
     * 不需要第二个排序键）。**无候选满足 ⇒ 无建议**（不退回"挑个最大的"）。</p>
     */
    public static final String ASSIGNMENT_RULE_BEST_FIT = "best_fit";

    private static final BigDecimal LE_0_2 = new BigDecimal("0.2");
    private static final BigDecimal LE_0_5 = new BigDecimal("0.5");
    private static final BigDecimal LE_1 = new BigDecimal("1");

    /**
     * 分摊商的小数位（内部中间值，**不是业务精度**）：分摊的结果紧接着就经
     * {@link StockQuantity#toStockScaleByCeiling} 归一到 0.1 —— 这里多留几位只是为了让
     * 「Σ 分摊 = 组应领米数」在归一之前逐值成立（`BigDecimal.divide` 除不尽必须给 scale，
     * 给 1 位就等于在归一之前先私自舍入了一次）。
     */
    private static final int SHARE_SCALE = 10;

    /** 定宽买高「每幅」的小数位（同上：中间值，落库存前统一由 {@code toStockScaleByCeiling} 归一）。 */
    private static final int PER_PIECE_SCALE = 6;

    private final StockBatchMapper stockBatchMapper;
    private final StockBatchConsumptionMapper consumptionMapper;
    private final ProductSkuMapper productSkuMapper;
    private final StockLedgerMapper stockLedgerMapper;

    /**
     * 算料配置的**单一读面**（issue #5158）：排料定尺要一个「上下卷边」（{@link CraftCalcConfigService#hemMarginOrNull}）。
     *
     * <p>只借它取这**一个**参数 —— 门幅/褶倍/幅数一律不在 Java 侧重算（它们由算料引擎产出、
     * 随订单落 {@code processing_info}，本服务只搬不算）。取不到 ⇒ **不排料**（fail-soft，
     * 见 {@link #hemMarginOrNull}）：排料是优化，不是加工单生成的正确性前提。</p>
     */
    private final CraftCalcConfigService craftCalcConfigService;

    /**
     * 余料台账写面（V122 / issue #5146）：派工扣批次之后**立即**把排料结果里的余料登记进台账。
     *
     * <p>🔴 <b>可为 null</b>（既有 5 个真库判据直接 new 本服务、不装余料腿）—— null ⇒ 跳过登记，
     * 批次账行为与今天**逐字相同**（余料是**附加事实**，不是扣减的正确性前提；
     * 与 #5158 排料的 fail-soft 同一条纪律）。</p>
     */
    private final RemnantService remnantService;

    // ══════════════════════════════════════════════════════════════════════════════════
    // 写面 ① plan —— 只读校验（全部业务异常在此抛完）
    // ══════════════════════════════════════════════════════════════════════════════════

    /**
     * 派工指定批次的一行（由 {@code ProcessingOrderService} 从加工单快照行的**该行米数**算出）。
     *
     * <p>{@code skuId} **不在入参里**：**批次的 SKU 才是权威**（批次由入库产生、SKU 固定不变），
     * 而订单行侧只带得出 {@code skuCode}（{@code processing_info.sku}）。
     * 用「订单行 skuCode vs 批次 skuCode」做一致性判据，比从订单行反解 skuId 少一层猜测
     * （反解要靠 {@code OrderService.matchSkuId} 那套匹配，那是销售腿的口径）。</p>
     *
     * <h2>后面三个字段是**排料定尺**的入参（issue #5158），不是可选的装饰</h2>
     * 排料要回答「这一行在门幅上占多宽、沿卷长要多长」，而这两条边**全部来自算料引擎的产物**
     * （本服务不重算幅数/褶倍/窗宽 —— 重算就是第二份会漂移的算料口径）：
     * <ul>
     *   <li><b>定高买宽</b>：一块 = 整窗 ⇒ {@code 占门幅宽 = height + 上下卷边}（卷边取自算料配置）、
     *       {@code 沿卷长 = meters}（= 引擎给的该行用料米数）；</li>
     *   <li><b>定宽买高</b>：一块 = 每一幅 ⇒ 幅数 {@code panels}（引擎的 {@code panels} 输出）
     *       把该行米数**等分**成 {@code panels} 块（{@code 每幅 = meters / panels} 就是引擎口径下的
     *       「幅宽」与「每幅长」—— 引擎的 {@code M = P × (H + 卷边)} 决定了这两个数恒等，
     *       故等分是**分解**引擎的输出，不是重新推导它）。</li>
     * </ul>
     * <p>任一字段缺席（存量单没有该键 / 加工类型未知）⇒ **该行不参与排料**，按 {@code meters}
     * （公式口径）扣 —— 「宁可为 0，不许估」。</p>
     *
     * @param orderItemId 订单明细行 id（= 快照行的 itemId，唯一标识「哪一行」）
     * @param batchNo     文员指定的批次号（**人工最终选择**，不是建议值）
     * @param meters      **公式口径**米数（= {@code toStockScaleByCeiling(order_items.quantity)}，
     *                    与销售账扣减**同一个函数**）—— 它是「改前的扣减口径」，本单把它原样落
     *                    {@code formula_meters}，与排料口径并列可读
     * @param cuttingMode 加工类型（{@code 定高买宽} / {@code 定宽买高}；其它值 ⇒ 不排料）
     * @param height      窗高（米；定高买宽定尺用）
     * @param panels      分幅数（定宽买高定尺用；引擎的 {@code panels} 输出）
     */
    public record Designation(String orderItemId, String productId, String skuCode,
                              String batchNo, BigDecimal meters,
                              String cuttingMode, BigDecimal height, Integer panels) {
    }

    /**
     * 计划里的一行（已校验「批次存在 / 属于该 SKU / 余量足够」；apply 只负责落账）。
     *
     * <p>{@code formulaMeters} / {@code plannedMeters}（V119，issue #5158）= 两个口径的米数，
     * 随扣减行一起落库并**带符号**（见 {@link StockBatchConsumption}）；
     * {@code unitCost} = **当时**该批次均价快照（源 {@code stock_batches.unit_cost}，
     * {@code null} = 批次未记成本 ⇒ 省钱数读不出，不猜）。</p>
     */
    public record Deduction(Long batchId, String batchNo, String productId, Long skuId, String skuCode,
                            String orderItemId, BigDecimal formulaMeters, BigDecimal plannedMeters,
                            BigDecimal unitCost, BigDecimal remainingBefore,
                            List<RemnantService.Draft> remnantDrafts) {

        /**
         * 旧签名（V119 形态）—— 排料产生的余料为**空**。
         *
         * <p>保留它是为了让「不关心余料」的既有调用点（真库判据、单测）**一个字都不用改**：
         * 余料是附加事实，缺省 = 不登记，批次账行为逐字不变。</p>
         */
        public Deduction(Long batchId, String batchNo, String productId, Long skuId, String skuCode,
                         String orderItemId, BigDecimal formulaMeters, BigDecimal plannedMeters,
                         BigDecimal unitCost, BigDecimal remainingBefore) {
            this(batchId, batchNo, productId, skuId, skuCode, orderItemId, formulaMeters,
                    plannedMeters, unitCost, remainingBefore, List.of());
        }

        /** 实际扣减米数 = **排料口径**（= 改后口径）。保留此访问器：既有调用点读的就是「扣多少」。 */
        public BigDecimal meters() {
            return plannedMeters;
        }
    }

    /**
     * 校验并规划派工扣减（**只读**，不写任何一行）。
     *
     * <p>三条 fail-closed 判据（缺料不静默的全部内容）：批次必须在（同租户）→ 必须属于该 SKU →
     * 余量必须够本行米数。<b>不足 ⇒ 抛 {@link #ERR_BATCH_STOCK_INSUFFICIENT} + 可行动建议</b>
     * （列出同 SKU 的有余量批次），绝不「有多少扣多少」。</p>
     *
     * <p>同一批次被多行指定时按**累积**判余量（不是逐行各自判）——否则两行各 3 米会把只剩 5 米的批次扣成 -1。</p>
     *
     * <p>🔴 <b>扣减米数 = 排料口径</b>（V119，issue #5158）：先按「批次 × 加工类型」成组排料
     * （{@link #cuttingPlanByItemId}），把每组的应领米数按各行公式米数占比分摊回行、
     * 经 {@link StockQuantity#toStockScaleByCeiling} 归一到 0.1，再拿它判余量 ——
     * 「省下的米数留在批次余量上」就是这一步的结果。排不了料的行**逐值退回公式口径**
     * （= 改前行为，节省恒为 0）。</p>
     */
    public List<Deduction> plan(Long tenantId, List<Designation> designations) {
        if (designations == null || designations.isEmpty()) {
            return List.of();
        }
        Set<String> batchNos = new LinkedHashSet<>();
        for (Designation d : designations) {
            if (StringUtils.hasText(d.batchNo())) {
                batchNos.add(d.batchNo().trim());
            }
        }
        Map<String, StockBatch> byNo = new LinkedHashMap<>();
        if (!batchNos.isEmpty()) {
            for (StockBatch b : stockBatchMapper.selectList(new LambdaQueryWrapper<StockBatch>()
                    .eq(StockBatch::getTenantId, tenantId)
                    .eq(StockBatch::getDeleted, 0)
                    .in(StockBatch::getBatchNo, batchNos))) {
                byNo.put(b.getBatchNo(), b);
            }
        }
        List<Long> batchIds = new ArrayList<>();
        for (StockBatch b : byNo.values()) {
            batchIds.add(b.getId());
        }
        // 累积口径：running = 「该批次已消耗净额」（负数为扣减）—— 同一批次被多行指定时逐行递减
        Map<Long, BigDecimal> running = new HashMap<>(consumedByBatchId(tenantId, batchIds));
        // 排料口径（V119 / issue #5158）：缺席的行 = 该行不参与排料 ⇒ 下面逐值退回公式口径。
        // 余料草稿（V122 / issue #5146）：**同一遍排料**顺带算出的空处（门幅余料 + 端部余料）
        // —— 不重排、不重算口径、不额外扫一遍（余料是排料结果的副产品，不是第二次求解）。
        Map<String, List<RemnantService.Draft>> draftsByItemId = new LinkedHashMap<>();
        Map<String, BigDecimal> plannedByItemId =
                cuttingPlanByItemId(tenantId, designations, byNo, draftsByItemId);

        List<Deduction> plan = new ArrayList<>();
        for (Designation d : designations) {
            StockBatch batch = StringUtils.hasText(d.batchNo()) ? byNo.get(d.batchNo().trim()) : null;
            if (batch == null) {
                throw new BusinessException(ERR_BATCH_NOT_FOUND,
                        String.format("批次 %s 不存在或不属于当前租户", d.batchNo()), 400,
                        "请刷新候选批次列表后重新选择；批次只能由入库单过账产生");
            }
            if (!batch.getProductId().equals(d.productId())) {
                throw new BusinessException(ERR_BATCH_SKU_MISMATCH,
                        String.format("批次 %s 属于商品 %s，与订单明细行的商品不一致",
                                batch.getBatchNo(), batch.getProductId()), 400,
                        "请选择与该行商品一致的批次");
            }
            if (StringUtils.hasText(d.skuCode()) && StringUtils.hasText(batch.getSkuCode())
                    && !batch.getSkuCode().equals(d.skuCode())) {
                throw new BusinessException(ERR_BATCH_SKU_MISMATCH,
                        String.format("批次 %s 属于 SKU %s，与订单明细行指定的 SKU %s 不一致",
                                batch.getBatchNo(), batch.getSkuCode(), d.skuCode()), 400,
                        "请选择与该行颜色/门幅一致的批次");
            }
            BigDecimal formula = StockQuantity.orZero(d.meters());
            BigDecimal meters = plannedByItemId.getOrDefault(d.orderItemId(), formula);
            BigDecimal before = StockQuantity.orZero(batch.getQuantity())
                    .add(running.getOrDefault(batch.getId(), BigDecimal.ZERO));
            if (before.compareTo(meters) < 0) {
                throw new BusinessException(ERR_BATCH_STOCK_INSUFFICIENT,
                        String.format("批次 %s 余量不足：可用 %s 米，本行需要 %s 米",
                                batch.getBatchNo(), plain(before), plain(meters)), 409,
                        availableHint(tenantId, d.productId(), batch.getSkuId(), batch.getId(), meters));
            }
            running.put(batch.getId(), before.subtract(meters).subtract(StockQuantity.orZero(batch.getQuantity())));
            plan.add(new Deduction(batch.getId(), batch.getBatchNo(), batch.getProductId(),
                    batch.getSkuId(),
                    StringUtils.hasText(batch.getSkuCode()) ? batch.getSkuCode() : d.skuCode(),
                    d.orderItemId(), formula, meters, batch.getUnitCost(), before,
                    draftsByItemId.getOrDefault(d.orderItemId(), List.of())));
        }
        return plan;
    }

    /**
     * 落账（**只插入**，不抛业务异常 —— 见类注释「写面分两段」）。
     *
     * @return 落账行数（0 = 本单没有指定任何批次 ⇒ 行为与今天逐字相同）
     */
    public int apply(Long tenantId, String processingOrderNo, String orderNo, List<Deduction> plan) {
        if (plan == null || plan.isEmpty()) {
            return 0;
        }
        for (Deduction d : plan) {
            BigDecimal delta = d.meters().negate();
            consumptionMapper.insert(StockBatchConsumption.builder()
                    .tenantId(tenantId)
                    .batchId(d.batchId())
                    .batchNo(d.batchNo())
                    .productId(d.productId())
                    .skuId(d.skuId())
                    .skuCode(d.skuCode())
                    .delta(delta)
                    .beforeQty(d.remainingBefore())
                    .afterQty(d.remainingBefore().add(delta))
                    // 两个米数 + 当时均价随扣减行**同时**落库（V119 / issue #5158；#5159 硬约束一）：
                    // 事后重算会随口径漂移（算料配置可改、排料器会迭代）⇒ 写账这一笔才是唯一真相。
                    .formulaMeters(d.formulaMeters())
                    .plannedMeters(d.plannedMeters())
                    .unitCost(d.unitCost())
                    .reason(REASON_PROCESSING_ORDER)
                    .processingOrderNo(processingOrderNo)
                    .orderNo(orderNo)
                    .orderItemId(d.orderItemId())
                    .operator(StockLedgerService.resolveOperator())
                    .note("生成加工单指定批次扣减")
                    .createdAt(OffsetDateTime.now())
                    .build());
        }
        // 余料登记（V122 / issue #5146）：**排料/派工结果自动产生**，不需要任何人手工登记。
        // 时点 = 扣减落账之后、同一事务内 —— 余料的来源（批次/缸号/商品/颜色）就是刚扣的那一批。
        // fail-soft：余料腿为 null（既有真库判据直接 new 本服务）或登记失败都**不影响**批次账
        //（余料是附加事实，不是扣减的正确性前提；与 #5158 排料的 fail-soft 同一条纪律）。
        if (remnantService != null) {
            for (Deduction d : plan) {
                if (d.remnantDrafts() == null || d.remnantDrafts().isEmpty()) {
                    continue;
                }
                remnantService.accrue(tenantId, processingOrderNo, orderNo,
                        new RemnantService.Source(d.batchId(), d.batchNo(), d.productId(),
                                d.skuId(), d.skuCode()),
                        d.remnantDrafts());
            }
        }
        log.info("派工扣批次库存: po={}, orderNo={}, tenant={}, lines={}, meters={}, formula={}, saved={}",
                processingOrderNo, orderNo, tenantId, plan.size(),
                plain(StockQuantity.sum(plan.stream().map(Deduction::plannedMeters).toList())),
                plain(StockQuantity.sum(plan.stream().map(Deduction::formulaMeters).toList())),
                plain(StockQuantity.sum(plan.stream()
                        .map(d -> d.formulaMeters().subtract(d.plannedMeters())).toList())));
        return plan.size();
    }

    // ══════════════════════════════════════════════════════════════════════════════════
    // 写面 ② reverse —— 作废回补（同事务、幂等、可重跑）
    // ══════════════════════════════════════════════════════════════════════════════════

    /**
     * 加工单作废 ⇒ 回补该单扣过的每一个批次（**逐值对称**：回补量 = 原扣减量的相反数）。
     *
     * <p><b>幂等 / 可重跑</b>：已经回补过的行（按 {@code 批次 × 明细行} 配对）直接跳过 ——
     * 第二遍调用返回 0 而不是撞唯一键报错。DB 侧另有 {@code uk_batch_consumption_line} 兜底。</p>
     *
     * <p><b>fail-closed</b>：原扣减行引用的批次查不到 ⇒ 抛错（批次行不可删，出现即账坏了；
     * 静默跳过会让「回补了」与「没回补」长得一样）。</p>
     *
     * @return 本次真正回补的行数（0 = 该单没有批次扣减 / 已经全部回补过）
     */
    @Transactional(rollbackFor = Exception.class)
    public int reverse(Long tenantId, String processingOrderNo, String orderNo, String note) {
        List<StockBatchConsumption> consumed = consumptionMapper.selectList(
                new LambdaQueryWrapper<StockBatchConsumption>()
                        .eq(StockBatchConsumption::getTenantId, tenantId)
                        .eq(StockBatchConsumption::getProcessingOrderNo, processingOrderNo)
                        .eq(StockBatchConsumption::getReason, REASON_PROCESSING_ORDER)
                        .eq(StockBatchConsumption::getDeleted, 0));
        if (consumed.isEmpty()) {
            return 0;
        }
        List<StockBatchConsumption> already = consumptionMapper.selectList(
                new LambdaQueryWrapper<StockBatchConsumption>()
                        .eq(StockBatchConsumption::getTenantId, tenantId)
                        .eq(StockBatchConsumption::getProcessingOrderNo, processingOrderNo)
                        .eq(StockBatchConsumption::getReason, REASON_PROCESSING_ORDER_CANCELLED)
                        .eq(StockBatchConsumption::getDeleted, 0));
        Set<String> done = new LinkedHashSet<>();
        for (StockBatchConsumption r : already) {
            done.add(lineKey(r.getBatchId(), r.getOrderItemId()));
        }
        List<Long> batchIds = new ArrayList<>();
        for (StockBatchConsumption c : consumed) {
            batchIds.add(c.getBatchId());
        }
        Map<Long, StockBatch> batches = new LinkedHashMap<>();
        for (StockBatch b : stockBatchMapper.selectList(new LambdaQueryWrapper<StockBatch>()
                .eq(StockBatch::getTenantId, tenantId)
                .in(StockBatch::getId, batchIds))) {
            batches.put(b.getId(), b);
        }
        Map<Long, BigDecimal> running = new HashMap<>(consumedByBatchId(tenantId, batchIds));

        int rows = 0;
        for (StockBatchConsumption c : consumed) {
            if (done.contains(lineKey(c.getBatchId(), c.getOrderItemId()))) {
                continue; // 幂等：该行已回补过 ⇒ 跳过（可重跑）
            }
            StockBatch batch = batches.get(c.getBatchId());
            if (batch == null) {
                throw new BusinessException(ERR_BATCH_NOT_FOUND,
                        String.format("回补失败：批次 id=%s（%s）不存在 —— 批次行不可删，出现即账目异常",
                                c.getBatchId(), c.getBatchNo()), 409,
                        "请人工核对 stock_batch_consumptions 与该批次；不要手工删台账行");
            }
            BigDecimal before = StockQuantity.orZero(batch.getQuantity())
                    .add(running.getOrDefault(batch.getId(), BigDecimal.ZERO));
            BigDecimal delta = c.getDelta().negate();
            // 回补行**逐值对称**地回写两个米数与当时均价（取相反数）：
            // ① 两列同带符号 ⇒ 作废后整单两个口径都净额归零（读面不必再写第二套减法）；
            // ② saved_meters 于是得到 −(原省数) ⇒ 与扣减行的省数**相加归零**（作废不冒功）；
            // ③ 均价是**同一笔成本基础**的快照，原样搬运（不是「今天的价」）。
            consumptionMapper.insert(StockBatchConsumption.builder()
                    .tenantId(tenantId)
                    .batchId(c.getBatchId())
                    .batchNo(c.getBatchNo())
                    .productId(c.getProductId())
                    .skuId(c.getSkuId())
                    .skuCode(c.getSkuCode())
                    .delta(delta)
                    .beforeQty(before)
                    .afterQty(before.add(delta))
                    .formulaMeters(negated(c.getFormulaMeters()))
                    .plannedMeters(negated(c.getPlannedMeters()))
                    .unitCost(c.getUnitCost())
                    .reason(REASON_PROCESSING_ORDER_CANCELLED)
                    .processingOrderNo(processingOrderNo)
                    .orderNo(orderNo != null ? orderNo : c.getOrderNo())
                    .orderItemId(c.getOrderItemId())
                    .operator(StockLedgerService.resolveOperator())
                    .note(note)
                    .createdAt(OffsetDateTime.now())
                    .build());
            // running 的口径 = 「Σdelta」（不是余量）⇒ 回补一行就是加一次 delta
            // （余量 = stock_batches.quantity + Σdelta，公式只有这一处）
            running.put(batch.getId(), running.getOrDefault(batch.getId(), BigDecimal.ZERO).add(delta));
            rows++;
        }
        if (rows > 0) {
            log.info("加工单作废回补批次库存: po={}, tenant={}, rows={}", processingOrderNo, tenantId, rows);
        }
        return rows;
    }

    // ══════════════════════════════════════════════════════════════════════════════════
    // 读面
    // ══════════════════════════════════════════════════════════════════════════════════

    /**
     * 批次余量列表（派生 = 入库量 + Σ消耗）。
     *
     * @param onlyAvailable true ⇒ 只回余量 &gt; 0 的批次（派工候选/「还有哪些能用」）
     */
    public List<BatchStockViews.BatchRemaining> remaining(Long tenantId, String productId, Long skuId,
                                                          boolean onlyAvailable) {
        List<StockBatch> batches = listBatches(tenantId, productId, skuId);
        Map<Long, BigDecimal> consumed = consumedByBatchId(tenantId, ids(batches));
        List<BatchStockViews.BatchRemaining> rows = new ArrayList<>();
        for (StockBatch b : batches) {
            BigDecimal used = consumed.getOrDefault(b.getId(), BigDecimal.ZERO);
            BigDecimal inbound = StockQuantity.orZero(b.getQuantity());
            BigDecimal rest = inbound.add(used);
            if (onlyAvailable && rest.compareTo(BigDecimal.ZERO) <= 0) {
                continue;
            }
            rows.add(new BatchStockViews.BatchRemaining(b.getId(), b.getBatchNo(), b.getProductId(),
                    b.getSkuId(), b.getSkuCode(), b.getInboundNo(), b.getDyeLot(), b.getReceivedDate(),
                    b.getUnitCost(), plain(inbound), plain(used.negate()), plain(rest)));
        }
        return rows;
    }

    /**
     * 剩余量分布（四档 `≤0.2m / 0.2~0.5m / 0.5~1m / &gt;1m`，按批次数与占比）。
     *
     * <p>这就是母单 #5144 的效果判据「更多批次剩余量落到 ≤0.2m」的读数面 —— 阶段 1 先把
     * **同口径的基线**记下来（阶段 2 的 best-fit 才有前后可比的东西）。</p>
     */
    public BatchStockViews.Distribution distribution(Long tenantId, String productId) {
        List<BatchStockViews.BatchRemaining> rows = remaining(tenantId, productId, null, false);
        int[] counts = new int[4];
        for (BatchStockViews.BatchRemaining r : rows) {
            counts[bucketIndex(r.remainingMeters())]++;
        }
        int total = rows.size();
        List<BatchStockViews.Bucket> buckets = new ArrayList<>();
        for (int i = 0; i < BUCKET_KEYS.length; i++) {
            buckets.add(bucket(BUCKET_KEYS[i], BUCKET_LABELS[i], counts[i], total));
        }
        return new BatchStockViews.Distribution(total, buckets);
    }

    /**
     * 对账读面（**路线 A 的交换条件**）：{@code Σ批次余量} 与 {@code product_skus.stock} 的差额。
     *
     * <p>恒等式与各腿的含义见 {@link BatchStockViews.ReconcileRow}。{@code reconciled=false}
     * 表示恒等式不成立（有批次/台账落到了读面覆盖不到的地方）——**读得出，不是静默**。</p>
     */
    public BatchStockViews.Reconcile reconcile(Long tenantId, String productId, Long skuId) {
        List<StockBatch> batches = listBatches(tenantId, productId, skuId);
        Map<Long, BigDecimal> consumed = consumedByBatchId(tenantId, ids(batches));
        // 逐 SKU 聚：入库总米数 / 批次余量
        Map<Long, BigDecimal> inboundBySku = new LinkedHashMap<>();
        Map<Long, BigDecimal> remainingBySku = new LinkedHashMap<>();
        Map<Long, String> skuCodes = new LinkedHashMap<>();
        for (StockBatch b : batches) {
            if (b.getSkuId() == null) {
                continue;
            }
            BigDecimal inbound = StockQuantity.orZero(b.getQuantity());
            inboundBySku.merge(b.getSkuId(), inbound, BigDecimal::add);
            remainingBySku.merge(b.getSkuId(), inbound.add(consumed.getOrDefault(b.getId(), BigDecimal.ZERO)),
                    BigDecimal::add);
            if (StringUtils.hasText(b.getSkuCode())) {
                skuCodes.putIfAbsent(b.getSkuId(), b.getSkuCode());
            }
        }
        // 派工扣减净额（逐 SKU）—— 口径 = **排料后**实际扣的米数（V119 起）
        Map<Long, BigDecimal> dispatchedBySku = new LinkedHashMap<>();
        // 公式口径的派工扣减净额（逐 SKU，V119）：与上面同一次扫描 ⇒ 拆分不是两次查询凑出来的
        Map<Long, BigDecimal> formulaBySku = new LinkedHashMap<>();
        for (StockBatchConsumptionMapper.SkuDeltaSum sum : consumptionMapper.sumDeltaBySku(tenantId)) {
            dispatchedBySku.merge(sum.getSkuId(), StockQuantity.orZero(sum.getDeltaSum()).negate(),
                    BigDecimal::add);
            formulaBySku.merge(sum.getSkuId(), StockQuantity.orZero(sum.getFormulaSum()), BigDecimal::add);
        }
        // 销售账分腿（逐 SKU）
        Map<Long, StockLedgerMapper.SkuLedgerSum> ledger = new LinkedHashMap<>();
        for (StockLedgerMapper.SkuLedgerSum sum : stockLedgerMapper.sumBySku(tenantId)) {
            ledger.put(sum.getSkuId(), sum);
        }

        List<ProductSku> skus = productSkuMapper.selectList(new LambdaQueryWrapper<ProductSku>()
                .eq(ProductSku::getTenantId, tenantId)
                .eq(ProductSku::getProductId, productId)
                .eq(skuId != null, ProductSku::getId, skuId));
        List<BatchStockViews.ReconcileRow> rows = new ArrayList<>();
        BigDecimal totalDiff = BigDecimal.ZERO;
        BigDecimal totalFormula = BigDecimal.ZERO;
        BigDecimal totalPlanned = BigDecimal.ZERO;
        BigDecimal totalSaved = BigDecimal.ZERO;
        int unreconciled = 0;
        for (ProductSku sku : skus) {
            BigDecimal inbound = inboundBySku.getOrDefault(sku.getId(), BigDecimal.ZERO);
            BigDecimal dispatched = dispatchedBySku.getOrDefault(sku.getId(), BigDecimal.ZERO);
            BigDecimal formulaDeducted = formulaBySku.getOrDefault(sku.getId(), BigDecimal.ZERO);
            BigDecimal batchRemaining = remainingBySku.getOrDefault(sku.getId(), BigDecimal.ZERO);
            // 只列出「与批次账有关」的 SKU（从未入库过的 SKU 没有批次来源，差额恒为 −stock，读它无意义）
            if (inbound.compareTo(BigDecimal.ZERO) == 0 && dispatched.compareTo(BigDecimal.ZERO) == 0) {
                continue;
            }
            BigDecimal stock = StockQuantity.orZero(sku.getStock());
            StockLedgerMapper.SkuLedgerSum l = ledger.get(sku.getId());
            BigDecimal soldDeducted = l == null ? BigDecimal.ZERO : StockQuantity.orZero(l.getSoldDeducted());
            BigDecimal otherDelta = l == null ? BigDecimal.ZERO : StockQuantity.orZero(l.getOtherDelta());
            BigDecimal totalDelta = l == null ? BigDecimal.ZERO : StockQuantity.orZero(l.getTotalDelta());
            BigDecimal unbatched = stock.subtract(totalDelta);
            BigDecimal diff = batchRemaining.subtract(stock);
            // 差额拆成两项（V119 / issue #5158；两项之和**逐值等于**拆之前的总解释项 —— formulaDeducted 一加一减）
            BigDecimal planSaved = formulaDeducted.subtract(dispatched);
            BigDecimal soldUnbatched = soldDeducted.subtract(formulaDeducted).subtract(otherDelta)
                    .subtract(unbatched);
            BigDecimal explained = soldUnbatched.add(planSaved);
            boolean ok = diff.compareTo(explained) == 0;
            if (!ok) {
                unreconciled++;
                log.warn("批次账对账不平: tenant={}, skuId={}, diff={}, explained={}, 已售未派={}, 排料节省={}",
                        tenantId, sku.getId(), plain(diff), plain(explained),
                        plain(soldUnbatched), plain(planSaved));
            }
            totalDiff = totalDiff.add(diff);
            totalFormula = totalFormula.add(formulaDeducted);
            totalPlanned = totalPlanned.add(dispatched);
            totalSaved = totalSaved.add(planSaved);
            rows.add(new BatchStockViews.ReconcileRow(sku.getId(),
                    StringUtils.hasText(sku.getSkuCode()) ? sku.getSkuCode() : skuCodes.get(sku.getId()),
                    sku.getProductId(), plain(stock), plain(batchRemaining), plain(inbound),
                    plain(dispatched), plain(soldDeducted), plain(otherDelta), plain(unbatched),
                    plain(diff), plain(explained), plain(soldUnbatched), plain(planSaved),
                    plain(formulaDeducted), ok));
        }
        return new BatchStockViews.Reconcile(rows, plain(totalDiff), unreconciled,
                plain(totalFormula), plain(totalPlanned), plain(totalSaved));
    }

    /**
     * 派工候选批次 + 建议值（生成加工单界面用）。
     *
     * <p><b>候选列表顺序恒 = 入库日期序</b>（{@link #listBatches} 的 ORDER BY，即 FIFO 序）——
     * 两种规则只改**建议值**，不改候选集合、不改顺序：文员看到的是同一份"有哪些批次能用"，
     * 差别只在"系统建议哪一个"（{@code suggested} 标记 + {@code suggestionRule} 回口径）。
     * 于是「切换规则不得漏候选」是**结构性**成立的，而不是靠断言兜。</p>
     *
     * <p><b>建议值口径</b>：缺省（{@code assignmentRule} 为 null/空白）= {@link #ASSIGNMENT_RULE_FIFO}
     * —— 与阶段 1 逐值相同（#5167 判据 1）；{@link #ASSIGNMENT_RULE_BEST_FIT} ⇒ 余量最接近需求者。
     * {@code suggestionRule} 显式回口径，免得读的人把朴素值当成 best-fit（或反过来）。</p>
     *
     * @param assignmentRule 指派规则（{@code null}/空白 = 缺省 fifo；未知取值 ⇒ **显式拒绝**）
     */
    public BatchStockViews.Candidates candidates(Long tenantId, String productId, Long skuId,
                                                 BigDecimal requiredMeters, String assignmentRule) {
        return suggest(remaining(tenantId, productId, skuId, true), requiredMeters,
                normalizeAssignmentRule(assignmentRule));
    }

    /**
     * 派工候选批次 + 建议值，**缺省规则**（= {@link #ASSIGNMENT_RULE_FIFO}）。
     *
     * <p>保留这个 4 参重载不是装饰：它是「缺省 = 阶段 1 行为」的**唯一入口**，
     * 调它的人不必知道规则的存在（#5167 判据 1「不传规则时与 fifo 逐值相同」）。</p>
     */
    public BatchStockViews.Candidates candidates(Long tenantId, String productId, Long skuId,
                                                 BigDecimal requiredMeters) {
        return candidates(tenantId, productId, skuId, requiredMeters, null);
    }

    // ══════════════════════════════════════════════════════════════════════════════════
    // 读面 ③ 省料度量 L2/L3 汇总（issue #5159）—— **只读**，无新增迁移
    // ══════════════════════════════════════════════════════════════════════════════════

    /** 未知的时间粒度（fail-closed：**不静默回落 month** —— 静默回落会让看板显示的口径与请求的不是一回事）。 */
    public static final String ERR_GRANULARITY_UNKNOWN = "GRANULARITY_UNKNOWN";

    /** PG {@code to_char} 的月份格式（本地时区下的自然月） */
    private static final String FMT_MONTH = "YYYY-MM";
    /** PG {@code to_char} 的 ISO 周格式（{@code 2026-W39}）；跨年周的年份要用 {@code IYYY}（ISO 年） */
    private static final String FMT_WEEK = "IYYY-\"W\"IW";

    /** 四档的 key / label —— **唯一定义处**（与 {@link #distribution} 同一对常量，见该方法的复用） */
    private static final String[] BUCKET_KEYS = {"le_0_2", "b0_2_0_5", "b0_5_1", "gt_1"};
    private static final String[] BUCKET_LABELS = {"≤0.2 米", "0.2~0.5 米", "0.5~1 米", ">1 米"};

    /** 粒度归一 + 校验（**纯函数**；未知取值 ⇒ 400 显式拒绝，不静默回落） */
    public static String normalizeGranularity(String raw) {
        if (!StringUtils.hasText(raw)) {
            return SavingMetricViews.GRANULARITY_MONTH;
        }
        return switch (raw.trim().toLowerCase(Locale.ROOT)) {
            case SavingMetricViews.GRANULARITY_MONTH -> SavingMetricViews.GRANULARITY_MONTH;
            case SavingMetricViews.GRANULARITY_WEEK -> SavingMetricViews.GRANULARITY_WEEK;
            default -> throw new BusinessException(ERR_GRANULARITY_UNKNOWN,
                    String.format("未知的时间粒度：%s", raw), 400,
                    String.format("可选值：%s（按月，YYYY-MM）/ %s（按 ISO 周，YYYY-Www）",
                            SavingMetricViews.GRANULARITY_MONTH, SavingMetricViews.GRANULARITY_WEEK));
        };
    }

    /**
     * L2 看板 + L1 的分组汇总（issue #5159 判据 1 / 2 / 3）。
     *
     * <h2>口径怎么保证「只有一套」（判据 1）</h2>
     * <ul>
     *   <li><b>批次余量 / 分档</b>：直接复用 {@link #remaining} 的余量派生（{@code 入库量 + Σdelta}）
     *       与 {@link #bucketIndex} 的边界 —— <b>#5145 的分档口径一个字没改</b>，
     *       本读面只是把它**再按（时间 × 来源 × 物料）分组**；</li>
     *   <li><b>省料米数 / 金额</b>：SQL 侧逐行取整再求和
     *       （见 {@code StockBatchConsumptionMapper.sumSavingByPeriodCohortMaterial}），
     *       与逐单读面的 {@code getSavedMeters()} / {@code getSavedAmount()} 求和<b>逐值相等</b>。</li>
     * </ul>
     *
     * <h2>存量单列（判据 2）</h2>
     * 每一个分组键都含来源组，{@code cohorts} <b>恒含</b> {@link SavingMetricViews#COHORT_OPENING}
     * 一行（哪怕今天为空）—— 「没有这一组」与「这一组是空的」必须可区分。
     *
     * @param productId  可选：只统计该商品的批次（{@code null} = 全租户）
     * @param granularity 时间粒度（{@code null} = 缺省按月；未知值 ⇒ 400）
     */
    public SavingMetricViews.Board savingBoard(Long tenantId, String productId, String granularity) {
        String g = normalizeGranularity(granularity);
        String fmt = formatOf(g);

        // ── L2：批次分档（复用既有余量派生 + 分档边界 —— 口径同源，#5145 一字未改）──
        List<StockBatch> batches = listBatches(tenantId, productId, null);
        Map<Long, BigDecimal> consumedByBatch = consumedByBatchId(tenantId, ids(batches));
        Map<Long, String> cohortOfBatch = cohortByBatchId(tenantId);
        Map<String, BatchAcc> byGroup = new LinkedHashMap<>();
        Map<String, BatchAcc> byCohort = new LinkedHashMap<>();
        for (String cohort : SavingMetricViews.COHORTS) {
            byCohort.put(cohort, new BatchAcc());
        }
        for (StockBatch b : batches) {
            String cohort = SavingMetricViews.cohortOf(cohortOfBatch.get(b.getId()));
            BigDecimal rest = StockQuantity.orZero(b.getQuantity())
                    .add(consumedByBatch.getOrDefault(b.getId(), BigDecimal.ZERO));
            String key = groupKey(periodOf(b.getReceivedDate()), cohort, b.getProductId(), b.getSkuCode());
            byGroup.computeIfAbsent(key, k -> new BatchAcc())
                    .put(periodOf(b.getReceivedDate()), cohort, b.getProductId(), b.getSkuCode())
                    .add(rest);
            byCohort.get(cohort).add(rest);
        }
        List<SavingMetricViews.BatchGroup> batchGroups = new ArrayList<>();
        for (BatchAcc acc : byGroup.values()) {
            batchGroups.add(new SavingMetricViews.BatchGroup(acc.period, acc.cohort,
                    SavingMetricViews.cohortLabel(acc.cohort),
                    SavingMetricViews.COHORT_OPENING.equals(acc.cohort),
                    SavingMetricViews.materialKeyOf(acc.productId, acc.skuCode),
                    acc.productId, acc.skuCode,
                    acc.total, acc.counts[0], share(acc.counts[0], acc.total),
                    acc.total == 0 ? null : plain(acc.remaining), bucketsOf(acc)));
        }

        // ── L1 汇总：逐单省料按（时间 × 来源 × 物料）聚合（SQL 一次扫描；与逐单读面同一列族）──
        Map<String, SavedAcc> savedByGroup = new LinkedHashMap<>();
        Map<String, SavedAcc> savedByCohort = new LinkedHashMap<>();
        for (String cohort : SavingMetricViews.COHORTS) {
            savedByCohort.put(cohort, new SavedAcc());
        }
        SavingMetricViews.Total total;
        SavedAcc totalAcc = new SavedAcc();        for (StockBatchConsumptionMapper.SavingSum row
                : consumptionMapper.sumSavingByPeriodCohortMaterial(
                        tenantId, SavingMetricViews.TIMEZONE, fmt)) {
            if (StringUtils.hasText(productId) && !productId.equals(row.getProductId())) {
                continue; // 商品筛选（批次腿已在 listBatches 里筛过；两腿必须同一个筛选面）
            }
            String cohort = SavingMetricViews.cohortOf(row.getSource());
            String key = groupKey(row.getPeriod(), cohort, row.getProductId(), row.getSkuCode());
            savedByGroup.computeIfAbsent(key, k -> new SavedAcc())
                    .put(row.getPeriod(), cohort, row.getProductId(), row.getSkuCode())
                    .add(row);
            savedByCohort.get(cohort).add(row);
            totalAcc.add(row);
        }
        List<SavingMetricViews.SavedGroup> savedGroups = new ArrayList<>();
        for (SavedAcc acc : savedByGroup.values()) {
            savedGroups.add(acc.toGroup());
        }
        total = new SavingMetricViews.Total(plainOrNull(totalAcc.formula), plainOrNull(totalAcc.planned),
                totalAcc.lineCount == 0 ? null : plain(totalAcc.formula.subtract(totalAcc.planned)),
                totalAcc.knownCostLines == 0 ? null : plain(totalAcc.amount),
                totalAcc.lineCount, totalAcc.lineCount - totalAcc.knownCostLines,
                batches.size(), byCohort.isEmpty() ? 0 : totalLe0_2(byCohort),
                share(totalLe0_2(byCohort), batches.size()));

        // ── 两张来源组合计卡（恒含 opening 一行；判据 2 / 4）──
        List<SavingMetricViews.CohortSummary> cohorts = new ArrayList<>();
        for (String cohort : SavingMetricViews.COHORTS) {
            BatchAcc b = byCohort.get(cohort);
            SavedAcc s = savedByCohort.get(cohort);
            int le0 = b.counts[0];
            cohorts.add(new SavingMetricViews.CohortSummary(cohort,
                    SavingMetricViews.cohortLabel(cohort),
                    SavingMetricViews.COHORT_OPENING.equals(cohort),
                    b.total, le0, share(le0, b.total),
                    b.total == 0 ? null : plain(b.remaining),
                    s.lineCount == 0 ? null : plain(s.formula.subtract(s.planned)),
                    s.knownCostLines == 0 ? null : plain(s.amount),
                    s.lineCount, s.lineCount - s.knownCostLines, bucketsOf(b)));
        }
        return new SavingMetricViews.Board(g, SavingMetricViews.TIMEZONE, cohorts, batchGroups,
                savedGroups, total);
    }

    /**
     * L3 趋势（采购/财务口径，issue #5159）：逐周/月的
     * <b>入库/采购总米数（指标②）</b>、<b>消耗米数</b>、<b>产出面积</b>与
     * <b>单位产出的面料消耗（米/㎡）</b>。
     *
     * <h2>🔴 存量导入单列（判据 2）</h2>
     * {@code purchasedMeters} <b>只含</b> {@code source='purchase'} 的入库量；
     * {@code openingMeters} 单列回。期初建账不是「这个月的采购」—— 混进来会让指标②
     * 永远被历史量压着，<b>改善看不出来</b>（这正是本单要治的形态）。
     *
     * <h2>消耗腿为什么不分来源组</h2>
     * 「消耗」是<b>用掉了多少布</b>，用谁的库存都是消耗（存量被用掉也是真消耗）。
     * 分来源的是<b>买</b>（② 与 {@code openingMeters}）与 L2 的<b>批次结构</b>——
     * 这两处才是「历史包袱会污染改善读数」的地方（判据 2 的落点）。分子分母仍<b>同集</b>：
     * 都取自同一批扣减行（分子 = Σ planned_meters，分母 = 这些行的窗户面积）。
     */
    public SavingMetricViews.Trend savingTrend(Long tenantId, String granularity) {
        String g = normalizeGranularity(granularity);
        String fmt = formatOf(g);

        Map<String, BigDecimal> purchased = new LinkedHashMap<>();
        Map<String, BigDecimal> opening = new LinkedHashMap<>();
        for (StockBatchConsumptionMapper.InboundSum row
                : consumptionMapper.sumInboundMetersByPeriodSource(tenantId, fmt)) {
            String cohort = SavingMetricViews.cohortOf(row.getSource());
            if (SavingMetricViews.COHORT_OPENING.equals(cohort)) {
                opening.merge(row.getPeriod(), StockQuantity.orZero(row.getMeters()), BigDecimal::add);
            } else if (SavingMetricViews.COHORT_PURCHASE.equals(cohort)) {
                purchased.merge(row.getPeriod(), StockQuantity.orZero(row.getMeters()), BigDecimal::add);
            }
        }
        Map<String, BigDecimal> consumed = new LinkedHashMap<>();
        for (StockBatchConsumptionMapper.SavingSum row
                : consumptionMapper.sumSavingByPeriodCohortMaterial(
                        tenantId, SavingMetricViews.TIMEZONE, fmt)) {
            consumed.merge(row.getPeriod(), StockQuantity.orZero(row.getPlannedSum()), BigDecimal::add);
        }
        Map<String, StockBatchConsumptionMapper.AreaSum> area = new LinkedHashMap<>();
        for (StockBatchConsumptionMapper.AreaSum row : consumptionMapper.sumOutputAreaByPeriod(
                tenantId, SavingMetricViews.TIMEZONE, fmt)) {
            area.put(row.getPeriod(), row);
        }

        Set<String> periods = new LinkedHashSet<>();
        periods.addAll(purchased.keySet());
        periods.addAll(opening.keySet());
        periods.addAll(consumed.keySet());
        periods.addAll(area.keySet());
        List<String> sorted = new ArrayList<>(periods);
        sorted.sort(Comparator.naturalOrder());

        List<SavingMetricViews.ConsumptionPoint> points = new ArrayList<>();
        for (String period : sorted) {
            BigDecimal buy = purchased.get(period);
            BigDecimal open = opening.get(period);
            BigDecimal use = consumed.get(period);
            StockBatchConsumptionMapper.AreaSum a = area.get(period);
            BigDecimal areaM2 = a == null ? null : a.getAreaM2();
            points.add(new SavingMetricViews.ConsumptionPoint(period,
                    buy == null ? null : plain(buy),
                    open == null ? null : plain(open),
                    use == null ? null : plain(use),
                    areaM2 == null ? null : plain(areaM2),
                    ratio(use, areaM2),
                    a == null || a.getOutputLines() == null ? 0 : a.getOutputLines()));
        }
        return new SavingMetricViews.Trend(g, SavingMetricViews.TIMEZONE, points,
                purchased.isEmpty() ? null : plain(StockQuantity.sum(purchased.values())),
                consumed.isEmpty() ? null : plain(StockQuantity.sum(consumed.values())),
                opening.isEmpty() ? null : plain(StockQuantity.sum(opening.values())));
    }

    /** 时间粒度 → PG {@code to_char} 格式 */
    private static String formatOf(String granularity) {
        return SavingMetricViews.GRANULARITY_WEEK.equals(granularity) ? FMT_WEEK : FMT_MONTH;
    }

    /** 批次收货月（{@code YYYY-MM}）；未记日期 ⇒ {@code null}（**不猜**，页面渲染「未记收货日期」）。 */
    private static String periodOf(LocalDate date) {
        return date == null ? null : String.format("%04d-%02d", date.getYear(), date.getMonthValue());
    }

    /** 分组键（{@code period|cohort|materialKey}）—— 机器可判，且**存量恒是独立键**（判据 2） */
    private static String groupKey(String period, String cohort, String productId, String skuCode) {
        return (period == null ? "" : period) + "#" + cohort + "#"
                + SavingMetricViews.materialKeyOf(productId, skuCode);
    }

    /**
     * 占比（4 位小数，{@code HALF_UP}）。
     *
     * <p>🔴 分母为 0 ⇒ {@code null}（**无数据**，不是 0）：判据 4 —— 0 会被读成
     * 「没有浪费」，而真相是「还没有数据」。</p>
     */
    private static BigDecimal share(int count, int total) {
        return total == 0 ? null
                : BigDecimal.valueOf(count).divide(BigDecimal.valueOf(total), 4, RoundingMode.HALF_UP);
    }

    /** 单位产出消耗（米/㎡，4 位）；分子或分母读不出 / 分母为 0 ⇒ {@code null}（判据 4） */
    private static BigDecimal ratio(BigDecimal meters, BigDecimal areaM2) {
        if (meters == null || areaM2 == null || areaM2.signum() == 0) {
            return null;
        }
        return meters.divide(areaM2, 4, RoundingMode.HALF_UP);
    }

    private static BigDecimal plainOrNull(BigDecimal value) {
        return value == null ? null : plain(value);
    }

    /** 恒四档（key/label 与 {@link #distribution} **同一对常量**；空档回 0 —— 计数为 0 是事实） */
    private static List<SavingMetricViews.Bucket> bucketsOf(BatchAcc acc) {
        List<SavingMetricViews.Bucket> out = new ArrayList<>(4);
        for (int i = 0; i < BUCKET_KEYS.length; i++) {
            out.add(new SavingMetricViews.Bucket(BUCKET_KEYS[i], BUCKET_LABELS[i], acc.counts[i],
                    share(acc.counts[i], acc.total),
                    acc.total == 0 ? null : plain(acc.bucketMeters[i])));
        }
        return out;
    }

    private static int totalLe0_2(Map<String, BatchAcc> byCohort) {
        int n = 0;
        for (BatchAcc acc : byCohort.values()) {
            n += acc.counts[0];
        }
        return n;
    }

    private Map<Long, String> cohortByBatchId(Long tenantId) {
        Map<Long, String> out = new LinkedHashMap<>();
        for (StockBatchMapper.BatchSourceRow row : stockBatchMapper.listBatchSources(tenantId)) {
            out.put(row.getBatchId(), row.getSource());
        }
        return out;
    }

    /** 分档累加器（L2：批次余量四档） */
    private static final class BatchAcc {
        private final int[] counts = new int[4];
        private final BigDecimal[] bucketMeters = {BigDecimal.ZERO, BigDecimal.ZERO,
                BigDecimal.ZERO, BigDecimal.ZERO};
        private BigDecimal remaining = BigDecimal.ZERO;
        private int total;
        private String period;
        private String cohort;
        private String productId;
        private String skuCode;

        private BatchAcc put(String period, String cohort, String productId, String skuCode) {
            this.period = period;
            this.cohort = cohort;
            this.productId = productId;
            this.skuCode = skuCode;
            return this;
        }

        private void add(BigDecimal rest) {
            int i = bucketIndex(rest);
            counts[i]++;
            bucketMeters[i] = bucketMeters[i].add(StockQuantity.orZero(rest));
            remaining = remaining.add(StockQuantity.orZero(rest));
            total++;
        }
    }

    /** 省料累加器（L1 汇总：加总 SQL 已按逐行取整的值，**不再取整** —— 再取整就是第二套口径） */
    private static final class SavedAcc {
        private BigDecimal formula = BigDecimal.ZERO;
        private BigDecimal planned = BigDecimal.ZERO;
        private BigDecimal amount = BigDecimal.ZERO;
        private int lineCount;
        private int knownCostLines;
        private String period;
        private String cohort;
        private String productId;
        private String skuCode;

        private SavedAcc put(String period, String cohort, String productId, String skuCode) {
            this.period = period;
            this.cohort = cohort;
            this.productId = productId;
            this.skuCode = skuCode;
            return this;
        }

        private void add(StockBatchConsumptionMapper.SavingSum row) {
            formula = formula.add(StockQuantity.orZero(row.getFormulaSum()));
            planned = planned.add(StockQuantity.orZero(row.getPlannedSum()));
            int known = row.getKnownCostLines() == null ? 0 : row.getKnownCostLines();
            if (known > 0 && row.getSavedAmountSum() != null) {
                amount = amount.add(row.getSavedAmountSum());
            }
            knownCostLines += known;
            lineCount += row.getLineCount() == null ? 0 : row.getLineCount();
        }

        private SavingMetricViews.SavedGroup toGroup() {
            return new SavingMetricViews.SavedGroup(period, cohort,
                    SavingMetricViews.cohortLabel(cohort),
                    SavingMetricViews.COHORT_OPENING.equals(cohort),
                    SavingMetricViews.materialKeyOf(productId, skuCode), productId, skuCode,
                    plain(formula), plain(planned),
                    lineCount == 0 ? null : plain(formula.subtract(planned)),
                    knownCostLines == 0 ? null : plain(amount),
                    lineCount, lineCount - knownCostLines);
        }
    }

    /**
     * 规则归一 + 校验（**纯函数**：给 {@code ProcessingOrderService} 在任何写库之前判）。
     *
     * <p>🔴 <b>未知取值 ⇒ 显式拒绝</b>（{@link #ERR_ASSIGNMENT_RULE_UNKNOWN}，400 + 可选值清单）：
     * 静默回落 fifo = 「商家以为开了 best-fit 却没开」，而账面上**看不出**没开
     * —— 本仓明令禁止的形态（#5167 判据 4）。</p>
     *
     * @param raw 请求里的原值（{@code null}/空白 = 缺省 fifo；大小写与 {@code best-fit} 连写法都收）
     */
    public static String normalizeAssignmentRule(String raw) {
        if (!StringUtils.hasText(raw)) {
            return ASSIGNMENT_RULE_FIFO;
        }
        return switch (raw.trim().toLowerCase(Locale.ROOT)) {
            case ASSIGNMENT_RULE_FIFO -> ASSIGNMENT_RULE_FIFO;
            case ASSIGNMENT_RULE_BEST_FIT, "best-fit" -> ASSIGNMENT_RULE_BEST_FIT;
            default -> throw new BusinessException(ERR_ASSIGNMENT_RULE_UNKNOWN,
                    String.format("未知的批次指派规则：%s", raw), 400,
                    String.format("可选值：%s（缺省，入库日期早者优先）/ %s（余量最接近需求者优先，让批次被用尽）",
                            ASSIGNMENT_RULE_FIFO, ASSIGNMENT_RULE_BEST_FIT));
        };
    }

    /**
     * 自动指派的建议批次号（生成加工单时该行**没有**指定批次、且调用方主动传了规则）。
     *
     * <p>与 {@link #candidates} 同一个挑法（{@link #suggest}）—— 两处各写一份必然漂移。
     * 行侧只有 {@code skuCode}（没有 skuId），故先按商品取余量批次、再按 {@code skuCode} 过滤：
     * 过滤口径与 {@link #plan} 的一致性判据**同源**（两边都有值才比，缺一不算不一致）。</p>
     *
     * @return 建议批次号；**无候选满足 ⇒ {@code null}**（由调用方 fail-closed 拒绝，不静默跳过）
     */
    public String suggestedBatchNo(Long tenantId, String productId, String skuCode,
                                   BigDecimal requiredMeters, String assignmentRule) {
        String rule = normalizeAssignmentRule(assignmentRule);
        List<BatchStockViews.BatchRemaining> rows = new ArrayList<>();
        for (BatchStockViews.BatchRemaining r : remaining(tenantId, productId, null, true)) {
            if (StringUtils.hasText(skuCode) && StringUtils.hasText(r.skuCode())
                    && !r.skuCode().equals(skuCode)) {
                continue;
            }
            rows.add(r);
        }
        return suggest(rows, requiredMeters, rule).suggestedBatchNo();
    }

    /** 候选 + 建议值的**唯一实现**（读面与自动指派共用）：候选顺序不动，只按规则挑建议值。 */
    private static BatchStockViews.Candidates suggest(List<BatchStockViews.BatchRemaining> rows,
                                                      BigDecimal requiredMeters, String rule) {
        BigDecimal need = StockQuantity.orZero(requiredMeters);
        String suggested = pick(rows, need, rule);
        List<BatchStockViews.Candidate> candidates = new ArrayList<>();
        for (BatchStockViews.BatchRemaining r : rows) {
            boolean enough = r.remainingMeters().compareTo(need) >= 0;
            candidates.add(new BatchStockViews.Candidate(r.batchNo(), r.remainingMeters(),
                    r.receivedDate(), r.dyeLot(), r.inboundNo(), r.unitCost(),
                    r.batchNo().equals(suggested), enough));
        }
        return new BatchStockViews.Candidates(
                ASSIGNMENT_RULE_BEST_FIT.equals(rule) ? SUGGESTION_RULE_BEST_FIT : SUGGESTION_RULE_FIFO,
                suggested, plain(need), candidates);
    }

    /** 挑建议批次：FIFO = 第一个够用的（{@code rows} 已是入库日期序）；best-fit = 够用的里头余量最小者。 */
    private static String pick(List<BatchStockViews.BatchRemaining> rows, BigDecimal need, String rule) {
        BatchStockViews.BatchRemaining best = null;
        for (BatchStockViews.BatchRemaining r : rows) {
            if (r.remainingMeters().compareTo(need) < 0) {
                continue; // 满足不了需求 ⇒ 两个策略都不看它（余量再小也不是「用尽」，是「不够」）
            }
            // FIFO：第一个够用的即结论。best-fit：取余量最小者；**平局保留先遇到的那个**
            // （= 入库日期早者）⇒ 裁决确定、可复算，且不依赖排序稳定性之外的任何东西。
            if (!ASSIGNMENT_RULE_BEST_FIT.equals(rule)) {
                return r.batchNo();
            }
            if (best == null || r.remainingMeters().compareTo(best.remainingMeters()) < 0) {
                best = r;
            }
        }
        return best == null ? null : best.batchNo();
    }

    /** 消耗台账分页（判据：**按批次 / 加工单 / 订单**都能查回来）。 */
    public PageResponse<StockBatchConsumption> consumptionPage(Long tenantId, String batchNo,
                                                              String processingOrderNo, String orderNo,
                                                              long page, long size) {
        Page<StockBatchConsumption> result = consumptionMapper.selectPage(new Page<>(page, size),
                new LambdaQueryWrapper<StockBatchConsumption>()
                        .eq(StockBatchConsumption::getTenantId, tenantId)
                        .eq(StringUtils.hasText(batchNo), StockBatchConsumption::getBatchNo, batchNo)
                        .eq(StringUtils.hasText(processingOrderNo),
                                StockBatchConsumption::getProcessingOrderNo, processingOrderNo)
                        .eq(StringUtils.hasText(orderNo), StockBatchConsumption::getOrderNo, orderNo)
                        .orderByDesc(StockBatchConsumption::getId));
        return PageResponse.of(result);
    }

    /**
     * 某加工单逐明细行的批次指派（工人端读面用：`order_item_id → {batch_no, batch_meters}`）。
     *
     * <p>同一行同一批次可能既有扣减又有回补（作废后重新生成）⇒ 取**净额**；
     * 净额为 0（已完全回补）⇒ 该行**不出现在结果里**（工人不该被告知去裁一个已经不扣账的批次）。</p>
     */
    public Map<String, BatchAssignment> assignmentsOf(Long tenantId, String processingOrderNo) {
        if (!StringUtils.hasText(processingOrderNo)) {
            return Map.of();
        }
        List<StockBatchConsumption> rows = consumptionMapper.selectList(
                new LambdaQueryWrapper<StockBatchConsumption>()
                        .eq(StockBatchConsumption::getTenantId, tenantId)
                        .eq(StockBatchConsumption::getProcessingOrderNo, processingOrderNo)
                        .eq(StockBatchConsumption::getDeleted, 0)
                        .orderByAsc(StockBatchConsumption::getId));
        Map<String, BatchAssignment> out = new LinkedHashMap<>();
        for (StockBatchConsumption c : rows) {
            BatchAssignment current = out.get(c.getOrderItemId());
            BigDecimal meters = StockQuantity.orZero(c.getDelta()).negate();
            if (current == null) {
                out.put(c.getOrderItemId(), new BatchAssignment(c.getBatchNo(), meters));
            } else {
                out.put(c.getOrderItemId(), new BatchAssignment(current.batchNo(),
                        current.meters().add(meters)));
            }
        }
        out.entrySet().removeIf(e -> e.getValue().meters().compareTo(BigDecimal.ZERO) == 0);
        return out;
    }

    /** 工人端一行：批次号 + 该行的裁剪米数（净额） */
    public record BatchAssignment(String batchNo, BigDecimal meters) {
    }

    // ══════════════════════════════════════════════════════════════════════════════════
    // 内部
    // ══════════════════════════════════════════════════════════════════════════════════

    // ══════════════════════════════════════════════════════════════════════════════════
    // 排料（V119 / issue #5158）：A 类完整布并排 —— 「省下的米数留在批次余量上」
    // ══════════════════════════════════════════════════════════════════════════════════

    /**
     * 逐行算出**排料口径**米数（= 该行应领多少米）。排不了料的行**不出现在结果里**
     * ⇒ 调用方逐值退回公式口径（{@link #plan} 里的 {@code getOrDefault}）。
     *
     * <h2>成组键 =（批次 × 加工类型）—— 🔴 为什么必须含<b>批次</b>，不能只按门幅</h2>
     * 并排省料的物理前提是「两块料裁自**同一卷**」。两块料若在不同批次（不同卷）上，
     * 各自都必须单独占一段卷长 ⇒ 跨批次成组会把「两卷各自 3 米」算成「共 3 米」——
     * 那是**虚报**（#5159 硬约束四「不虚报」）。
     * 「同门幅」由批次自身保证：批次由入库产生、{@code sku_id} 固定，而 SKU 组合 = 颜色 × 门幅
     * ⇒ 同批次必然同门幅（跨批次即使门幅相同也**不得**成组）。
     *
     * <h2>应领米数怎么分摊回行</h2>
     * 排料器给的是**组**的应领米数（{@code Σ 行长}），而扣减是**逐行**落账的 ⇒ 按各行公式米数占比分摊：
     * {@code 分摊_i = issued × formula_i / Σformula}。两条性质是判据的基础：
     * <ul>
     *   <li>{@code Σ 分摊 = issued}（逐值）⇒ 组内总扣减 = 排料结果 ⇒ 省下的米数**真的**留在批次上；</li>
     *   <li>{@code issued ≤ Σformula}（行长 = 行内最大沿卷长 ≤ 行内各块之和）⇒ 每一行
     *       {@code 分摊_i ≤ formula_i}；再经 {@code toStockScaleByCeiling} 进位，
     *       {@code 归一后 ≤ formula_i} 仍然成立（公式米数本身已是 0.1 粒度）
     *       ⇒ DB 约束 {@code planned_meters <= formula_meters} **不可能**被触发，节省恒 ≥ 0。</li>
     * </ul>
     * <p>「不可并排 ⇒ 与公式米数逐值相同」也来自这里：每块各占一行时 {@code issued = Σformula}，
     * 分摊恒等于自己那行的公式米数（判据「不倒退」）。</p>
     */
    private Map<String, BigDecimal> cuttingPlanByItemId(Long tenantId, List<Designation> designations,
                                                        Map<String, StockBatch> byNo,
                                                        Map<String, List<RemnantService.Draft>> draftsOut) {
        Map<String, BigDecimal> planned = new LinkedHashMap<>();
        // 余料序号在**整张加工单**范围内递增（幂等闸 uk_fabric_remnants_piece 的键：
        // 同一份排料结果两遍得到同一组序号 ⇒ 重复登记撞唯一键而不是写两遍）
        int[] pieceSeq = {0};
        BigDecimal hemMargin = craftCalcConfigService == null ? null
                : craftCalcConfigService.hemMarginOrNull(tenantId);
        if (hemMargin == null) {
            return planned; // 取不到上下卷边 ⇒ 不排料（宁可为 0，不许估一个余量）
        }
        Map<Long, Double> doorWidthBySkuId = doorWidthsBySkuId(tenantId, byNo.values());
        Map<String, PlanGroup> groups = new LinkedHashMap<>();
        for (Designation d : designations) {
            String mode = cuttingModeOf(d.cuttingMode());
            StockBatch batch = StringUtils.hasText(d.batchNo()) ? byNo.get(d.batchNo().trim()) : null;
            Double doorWidth = mode == null || batch == null ? null : doorWidthBySkuId.get(batch.getSkuId());
            if (doorWidth == null) {
                continue; // 工艺未知 / 批次查不到 / 门幅没记 ⇒ 该行不排料
            }
            List<CuttingPlanCalculator.Piece> pieces = piecesOf(d, mode, doorWidth, hemMargin);
            if (pieces.isEmpty()) {
                continue; // 定尺输入不全（缺窗高 / 缺幅数）⇒ 该行不排料
            }
            groups.computeIfAbsent(batch.getId() + "|" + mode,
                            k -> new PlanGroup(batch.getId(), mode, doorWidth))
                    .add(d.orderItemId(), StockQuantity.orZero(d.meters()), pieces);
        }
        for (PlanGroup group : groups.values()) {
            CuttingPlanCalculator.CuttingPlan cuttingPlan;
            try {
                cuttingPlan = CuttingPlanCalculator.plan(group.pieces(), group.doorWidth(),
                        hemMargin.doubleValue());
            } catch (IllegalArgumentException e) {
                // 排料失败（如窗高 + 卷边 > 门幅 ⇒ 这块料排不下）⇒ **整组退回公式口径**。
                // 这里有意**不** fail-closed：排料是优化，不是加工单生成的正确性前提
                // —— 让一张排不出方案的订单生成不了加工单是更坏的交换（「不能损失客户」）；
                // 退回后行为与本单之前**逐字相同**（saved = 0），且日志里留得下原因。
                log.warn("排料失败 ⇒ 该组退回公式口径（saved=0）: tenant={}, batchId={}, mode={}, reason={}",
                        tenantId, group.batchId(), group.cuttingMode(), e.getMessage());
                continue;
            }
            BigDecimal issued = cuttingPlan.issuedMeters();
            BigDecimal totalFormula = group.totalFormula();
            // 余料（V122 / issue #5146）：排料结果里的空处 = 门幅余料 + 端部余料。
            // 🔴 余料属于**组**（同一卷布上这一段里没被占的地方），不拆到行 ⇒ 挂在组内**第一行**上，
            //    由 apply() 连同该行的批次上下文一起登记（批次的缸号/商品/颜色就在那一行上）。
            List<RemnantService.Draft> groupDrafts = remnantDraftsOf(cuttingPlan, group.doorWidth(), pieceSeq);
            if (!groupDrafts.isEmpty()) {
                draftsOut.put(group.itemIds().get(0), groupDrafts);
            }
            for (String itemId : group.itemIds()) {
                BigDecimal share = totalFormula.signum() == 0 ? BigDecimal.ZERO
                        : issued.multiply(group.formulaOf(itemId))
                                .divide(totalFormula, SHARE_SCALE, RoundingMode.HALF_UP);
                // 🔴 归一的**唯一入口**（公式口径与排料口径共用同一个函数）：
                // 排料结果**不取整**，落库存前按 0.1 向上进位 ⇒ 领料量只多不少
                // （少领 = 切不出货，比不省料严重得多）。关系与理由见 StockQuantity#toStockScaleByCeiling。
                planned.put(itemId, StockQuantity.toStockScaleByCeiling(share));
            }
        }
        return planned;
    }

    /**
     * 排料结果 → 余料草稿（V122 / issue #5146）—— **纯函数**，两种余料都在这里算清。
     *
     * <h2>两种余料的几何</h2>
     * 排料器逐行给出「行长度」（= 该行各块沿卷长的**最大值**）与行内各块的「占门幅宽」：
     * <ul>
     *   <li><b>门幅余料</b>：行内 {@code Σ占门幅宽 < 门幅} ⇒ 剩下一条竖带
     *       （长 = 行长度、宽 = 门幅 − Σ占门幅宽）；</li>
     *   <li><b>端部余料</b>：某块比该行最长块短 ⇒ 它尾部剩一条横带
     *       （长 = 行长度 − 该块沿卷长、宽 = 该块占门幅宽）。</li>
     * </ul>
     * 两者都在「**这一行已按行长度整段领下来**」的那段布里面 ⇒ 它们的米数**确实已被计价**
     * （每幅按整门幅算，门幅余料的钱客户已经付过 = 本单「成本回收」的物理前提）。
     *
     * <h2>取整方向：**向下**（fail-closed）</h2>
     * 排料器给的是 double，余料落库是 {@code NUMERIC(12,2)}。这里一律
     * {@code setScale(2, FLOOR)} —— 向上取整会把「其实装不下」报成装得下，
     * 正是判据 5「不凭空推荐」要防的形态。<b>宁可少报 1 厘米，不可多报。</b>
     *
     * <p>小于 {@link RemnantService#MIN_REMNANT_DIM_M} 的碎边**不登记**：那不是业务阈值而是
     * 「0 面积的矩形不是余料」这条物理事实（本仓宽高按厘米报），登记它只会把台账灌满零面积行。</p>
     */
    private static List<RemnantService.Draft> remnantDraftsOf(
            CuttingPlanCalculator.CuttingPlan cuttingPlan, double doorWidth, int[] pieceSeq) {
        List<RemnantService.Draft> drafts = new ArrayList<>();
        BigDecimal door = BigDecimal.valueOf(doorWidth);
        for (CuttingPlanCalculator.Row row : cuttingPlan.rows()) {
            BigDecimal span = BigDecimal.ZERO;
            for (CuttingPlanCalculator.Piece piece : row.pieces()) {
                span = span.add(BigDecimal.valueOf(piece.doorSpanMeters()));
            }
            BigDecimal widthLeft = door.subtract(span);
            if (widthLeft.compareTo(RemnantService.MIN_REMNANT_DIM_M) >= 0) {
                drafts.add(new RemnantService.Draft(pieceSeq[0]++, FabricRemnant.KIND_WIDTH,
                        floor2(row.length()), floor2(widthLeft)));
            }
            for (CuttingPlanCalculator.Piece piece : row.pieces()) {
                BigDecimal endLeft = row.length().subtract(BigDecimal.valueOf(piece.meters()));
                if (endLeft.compareTo(RemnantService.MIN_REMNANT_DIM_M) >= 0) {
                    drafts.add(new RemnantService.Draft(pieceSeq[0]++, FabricRemnant.KIND_END,
                            floor2(endLeft), floor2(BigDecimal.valueOf(piece.doorSpanMeters()))));
                }
            }
        }
        return drafts;
    }

    /** 余料尺寸取整：**向下**到 2 位（见 {@link #remnantDraftsOf} 的取整方向说明）。 */
    private static BigDecimal floor2(BigDecimal value) {
        return value.setScale(2, RoundingMode.FLOOR);
    }

    /** 一个排料组（同批次 = 同一卷布；同加工类型 = 同一套定尺口径）。 */
    private static final class PlanGroup {

        private final Long batchId;
        private final String cuttingMode;
        private final double doorWidth;
        private final List<String> itemIds = new ArrayList<>();
        private final List<CuttingPlanCalculator.Piece> pieces = new ArrayList<>();
        private final Map<String, BigDecimal> formulaByItemId = new LinkedHashMap<>();

        private PlanGroup(Long batchId, String cuttingMode, double doorWidth) {
            this.batchId = batchId;
            this.cuttingMode = cuttingMode;
            this.doorWidth = doorWidth;
        }

        private void add(String itemId, BigDecimal formulaMeters,
                         List<CuttingPlanCalculator.Piece> linePieces) {
            itemIds.add(itemId);
            formulaByItemId.put(itemId, formulaMeters);
            pieces.addAll(linePieces);
        }

        private Long batchId() {
            return batchId;
        }

        private String cuttingMode() {
            return cuttingMode;
        }

        private double doorWidth() {
            return doorWidth;
        }

        private List<String> itemIds() {
            return itemIds;
        }

        private List<CuttingPlanCalculator.Piece> pieces() {
            return pieces;
        }

        private BigDecimal formulaOf(String itemId) {
            return formulaByItemId.getOrDefault(itemId, BigDecimal.ZERO);
        }

        private BigDecimal totalFormula() {
            return StockQuantity.sum(formulaByItemId.values());
        }
    }

    /**
     * 一行的排料块（**定尺输入，本服务不重算算料口径** —— 两条边全部来自算料引擎的产物）。
     *
     * <ul>
     *   <li><b>定高买宽</b>（一块 = 整窗）：{@code 占门幅宽 = 窗高 + 上下卷边}；
     *       {@code 沿卷长 = 公式米数}（引擎给的 {@code W×N}）。</li>
     *   <li><b>定宽买高</b>（一块 = 每一幅）：幅数 = 引擎的 {@code panels} 输出，
     *       把公式米数**等分**成 {@code panels} 块。等分不是新口径：引擎的
     *       {@code M = P × (H + 卷边)} 使「每幅宽」与「每幅长」恒为 {@code M/P}，
     *       故这里只是**分解**引擎的输出（`panels` 缺席 ⇒ 不排料，绝不自己算 {@code ceil(M/G)}）。</li>
     * </ul>
     */
    private static List<CuttingPlanCalculator.Piece> piecesOf(Designation d, String mode,
                                                              double doorWidth, BigDecimal hemMargin) {
        BigDecimal formula = StockQuantity.orZero(d.meters());
        if (formula.signum() <= 0) {
            return List.of();
        }
        if (CuttingPlanCalculator.MODE_FIXED_HEIGHT.equals(mode)) {
            BigDecimal height = StockQuantity.orZero(d.height());
            if (height.signum() <= 0) {
                return List.of();
            }
            return List.of(new CuttingPlanCalculator.Piece(d.orderItemId() + "#1", mode,
                    height.add(hemMargin).doubleValue(), formula.doubleValue()));
        }
        if (CuttingPlanCalculator.MODE_FIXED_WIDTH.equals(mode)) {
            int panels = d.panels() == null ? 0 : d.panels();
            if (panels <= 0) {
                return List.of();
            }
            BigDecimal per = formula.divide(BigDecimal.valueOf(panels), PER_PIECE_SCALE,
                    RoundingMode.HALF_UP);
            List<CuttingPlanCalculator.Piece> pieces = new ArrayList<>(panels);
            for (int i = 1; i <= panels; i++) {
                pieces.add(new CuttingPlanCalculator.Piece(d.orderItemId() + "#" + i, mode,
                        per.doubleValue(), per.doubleValue()));
            }
            return pieces;
        }
        return List.of();
    }

    /**
     * 订单侧加工类型（{@code processing_info.cuttingMode}，中文串）→
     * {@link CuttingPlanCalculator} 的模式常量。
     *
     * <p>真值源 = 算料引擎的 {@code CUTTING_MODE_FIXED_HEIGHT = "定高买宽"} /
     * {@code CUTTING_MODE_FIXED_WIDTH = "定宽买高"}（订单侧下单时原样透传该中文串）。
     * 映射**只在这里写一次**；未知取值 ⇒ {@code null}（不排料，**不猜工艺** —— 猜错会把整窗
     * 当成多幅拆开，那是少领）。</p>
     */
    private static String cuttingModeOf(String raw) {
        if (raw == null) {
            return null;
        }
        return switch (raw.trim()) {
            case "定高买宽" -> CuttingPlanCalculator.MODE_FIXED_HEIGHT;
            case "定宽买高" -> CuttingPlanCalculator.MODE_FIXED_WIDTH;
            default -> null;
        };
    }

    /** 批次 SKU → 门幅（米）。只有**批次**的 SKU 才作数（扣的是这批布，不是订单行上写的那个）。 */
    private Map<Long, Double> doorWidthsBySkuId(Long tenantId, Collection<StockBatch> batches) {
        Set<Long> skuIds = new LinkedHashSet<>();
        for (StockBatch b : batches) {
            if (b.getSkuId() != null) {
                skuIds.add(b.getSkuId());
            }
        }
        Map<Long, Double> out = new LinkedHashMap<>();
        if (skuIds.isEmpty()) {
            return out;
        }
        for (ProductSku sku : productSkuMapper.selectList(new LambdaQueryWrapper<ProductSku>()
                .eq(ProductSku::getTenantId, tenantId)
                .in(ProductSku::getId, skuIds))) {
            Double meters = parseDoorWidth(sku.getDoorWidth());
            if (meters != null) {
                out.put(sku.getId(), meters);
            }
        }
        return out;
    }

    /**
     * 门幅原串 → 米。存量有两种形态（{@code "2.8米"} / {@code "2.8"}），与
     * {@code ProductService} 的建品解析、前端 {@code craft-display} 同一口径（去掉非数字修饰）。
     *
     * <p>解析不出 / 非正 ⇒ {@code null} ⇒ 该批次**不参与排料**（**不猜门幅**：
     * 猜大了会把两块料并进一行 ⇒ 少领 ⇒ 切不出货）。</p>
     */
    private static Double parseDoorWidth(String raw) {
        if (!StringUtils.hasText(raw)) {
            return null;
        }
        try {
            BigDecimal value = new BigDecimal(raw.replaceAll("[^0-9.]", ""));
            return value.signum() > 0 ? value.doubleValue() : null;
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static BigDecimal negated(BigDecimal value) {
        return value == null ? null : value.negate();
    }

    private List<StockBatch> listBatches(Long tenantId, String productId, Long skuId) {
        return stockBatchMapper.selectList(new LambdaQueryWrapper<StockBatch>()
                .eq(StockBatch::getTenantId, tenantId)
                .eq(StockBatch::getDeleted, 0)
                .eq(StringUtils.hasText(productId), StockBatch::getProductId, productId)
                .eq(skuId != null, StockBatch::getSkuId, skuId)
                // 建议值口径 = 入库日期先进先出（同日按 id）；未记收货日期的排最后（不猜日期）
                .orderByAsc(StockBatch::getReceivedDate)
                .orderByAsc(StockBatch::getId));
    }

    private Map<Long, BigDecimal> consumedByBatchId(Long tenantId, Collection<Long> batchIds) {
        Map<Long, BigDecimal> out = new HashMap<>();
        if (batchIds == null || batchIds.isEmpty()) {
            return out;
        }
        for (StockBatchConsumptionMapper.BatchDeltaSum sum
                : consumptionMapper.sumDeltaByBatchIds(tenantId, batchIds)) {
            out.put(sum.getBatchId(), StockQuantity.orZero(sum.getDeltaSum()));
        }
        return out;
    }

    private static List<Long> ids(List<StockBatch> batches) {
        List<Long> ids = new ArrayList<>();
        for (StockBatch b : batches) {
            ids.add(b.getId());
        }
        return ids;
    }

    private static int bucketIndex(BigDecimal remaining) {
        BigDecimal r = StockQuantity.orZero(remaining);
        if (r.compareTo(LE_0_2) <= 0) {
            return 0;
        }
        if (r.compareTo(LE_0_5) <= 0) {
            return 1;
        }
        if (r.compareTo(LE_1) <= 0) {
            return 2;
        }
        return 3;
    }

    private static BatchStockViews.Bucket bucket(String key, String label, int count, int total) {
        BigDecimal share = total == 0
                ? BigDecimal.ZERO
                : BigDecimal.valueOf(count).divide(BigDecimal.valueOf(total), 4, RoundingMode.HALF_UP);
        return new BatchStockViews.Bucket(key, label, count, plain(share));
    }

    /** 缺料的可行动建议：同 SKU 还有哪些批次、各剩多少（fail-closed 不等于「只说不」） */
    private String availableHint(Long tenantId, String productId, Long skuId, Long excludeBatchId,
                                 BigDecimal needed) {
        List<BatchStockViews.BatchRemaining> rows = remaining(tenantId, productId, skuId, true);
        StringBuilder sb = new StringBuilder("该行需要 ")
                .append(plain(needed))
                .append(" 米。当前可用批次：");
        int shown = 0;
        for (BatchStockViews.BatchRemaining r : rows) {
            if (r.batchId().equals(excludeBatchId)) {
                continue;
            }
            if (shown++ == 3) {
                break;
            }
            sb.append(r.batchNo()).append("（剩 ").append(plain(r.remainingMeters())).append(" 米）");
            sb.append(shown == 1 ? "" : "、");
        }
        if (shown == 0) {
            sb.append("无（该 SKU 没有其它有余量的批次）");
        }
        return sb.append("。可选其它批次，或先入库补料后重新生成加工单（阶段 2 将支持拆多批次）。").toString();
    }

    private static String lineKey(Long batchId, String orderItemId) {
        return batchId + "#" + orderItemId;
    }

    /** 去掉无意义的尾零（`2.70` → `2.7`）：JSON 字面量与断言才好逐值比（同 StockQuantity 的口径）。 */
    private static BigDecimal plain(BigDecimal value) {
        return value == null ? null : StockQuantity.stripTrailingZerosPlain(value);
    }
}
