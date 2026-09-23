package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.RemnantViews;
import com.migao.admin.entity.FabricRemnant;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionOptionRouting;
import com.migao.admin.entity.RemnantItemSize;
import com.migao.admin.entity.StockBatch;
import com.migao.admin.entity.StockBatchConsumption;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.FabricRemnantMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOptionRoutingMapper;
import com.migao.admin.mapper.RemnantItemSizeMapper;
import com.migao.admin.mapper.StockBatchConsumptionMapper;
import com.migao.admin.mapper.StockBatchMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 余料成本回收（V122，issue #5146）—— **非资产**台账 + 小件优先匹配 + 回收记账 + 报废留痕。
 *
 * <h2>本单的四条口径（决定实现形态，先讲清）</h2>
 * <ol>
 *   <li><b>余料零价值</b>（用户裁定逐字「这个废布不算在企业资产了」）⇒ 台账只记**实物可用性**
 *       （尺寸 / 来源 / 缸号 / 状态），<b>不计价、不进库存金额</b>。本服务**不写**
 *       {@code product_skus} / {@code stock_ledger_entries} / {@code stock_batches} 任何一行。</li>
 *   <li><b>小件尺寸是可配参数</b>（用户裁定逐字「小件用料尺寸表，可以整个参数配置，未来让企业自定义」）
 *       ⇒ 尺寸在 {@code remnant_small_item_specs}（本服务读写），**缺行 = 未配置 = 未启用**，
 *       不编业务数值。</li>
 *   <li><b>回收不是向客户再要一次钱</b>：计价口径 {@code M = P × 每幅长} 本身就包含门幅余料
 *       ⇒ 这块布的钱客户已经付过；「回收额」是把**已经计过价的东西**从「丢掉」改成「用起来」的
 *       <b>内部成本冲减量</b>，归属是**用它的那张单**（{@code used_by_order_no}）。
 *       ⇒ 对客售价 / 加工费 / 成品尺寸<b>一字不动</b>（判据 2「不损失客户」）。</li>
 *   <li><b>不静默</b>：未配置小件尺寸 ⇒ 匹配**不产生任何推荐**且 {@code notice} 非空；
 *       尺寸不足 ⇒ 不推荐；取不到缸号 ⇒ 不推荐（不猜颜色）。「没配」与「没匹配上」必须能分开读。</li>
 * </ol>
 *
 * <h2>余料从哪来（时点 = 排料/派工结果**自动产生**）</h2>
 * 排料器（{@link CuttingPlanCalculator}）逐行给出「行长度」与行内各块的「占门幅宽」，
 * 两种余料都是矩形、都能直接算出（推导见
 * {@code backend/admin-api/src/main/resources/db/migration-archive/V122__create_fabric_remnants.sql} 文件头）：
 * <ul>
 *   <li>{@link FabricRemnant#KIND_WIDTH} 门幅余料：行内 {@code Σ占门幅宽 < 门幅} 剩下的竖带；</li>
 *   <li>{@link FabricRemnant#KIND_END} 端部余料：行内短块尾部剩下的横带。</li>
 * </ul>
 * 入口是 {@link #accrue}，由 {@link StockBatchConsumptionService#apply} 在**派工扣批次之后立即**调用
 * （同一事务）⇒ 余料不需要任何人手工登记。排不出料的行不产生余料（那些行的布没有排料结果可依据）。
 *
 * <h2>尺寸取整方向：**向下**（fail-closed）</h2>
 * 排料器给的是 double，落库是 {@code NUMERIC(12,2)}。这里一律
 * {@code setScale(2, RoundingMode.FLOOR)}（<b>向下</b>）—— 向上取整会把「其实装不下」报成装得下，
 * 正是判据 5「不凭空推荐」要防的形态。宁可少报 1 厘米，不可多报。
 *
 * <h2>匹配的降级策略（照实登记）</h2>
 * 排序 = ①同缸号 → ②同色（同 skuCode）→ ③长度升序（先用小块，大块留给大件）→ ④id 升序（确定性）。
 * **硬底线** = 候选必须「同缸号 **或** 同色」，两者都不满足 ⇒ 淘汰（防色差的底线，不得放宽）。
 * ⇒ 「同缸号找不到、但有同色余料」时会推荐**不同缸号**的那一块，并在读面用
 * {@code sameDyeLot=false} 标出来（色差风险可见）；有同缸号时**一定**优先取同缸号。
 * <b>本服务不跨商品匹配</b>（不同商品的布不可能互相替代）。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class RemnantService {

    /** 余料不存在 / 不属于当前租户 */
    public static final String ERR_REMNANT_NOT_FOUND = "REMNANT_NOT_FOUND";
    /** 余料不处于可操作状态（已用 / 已报废 / 客户带走 —— 都不允许再回收或报废） */
    public static final String ERR_REMNANT_NOT_AVAILABLE = "REMNANT_NOT_AVAILABLE";
    /** 该小件**未配置**用料尺寸（fail-closed：不猜尺寸、不按 0 处理） */
    public static final String ERR_REMNANT_SPEC_REQUIRED = "REMNANT_SPEC_REQUIRED";
    /** 余料装不下该小件（判据 5 的写面守卫：读面不推荐，写面也拒绝） */
    public static final String ERR_REMNANT_TOO_SMALL = "REMNANT_TOO_SMALL";
    /** 来源批次没记均价 ⇒ 回收额算不出来（**宁可为失败，不许估**） */
    public static final String ERR_REMNANT_BATCH_COST_UNKNOWN = "REMNANT_BATCH_COST_UNKNOWN";
    /** 该明细行取不到批次 ⇒ 取不到缸号与颜色 ⇒ 无法按同缸号 / 同色匹配 */
    public static final String ERR_REMNANT_NO_BATCH_CONTEXT = "REMNANT_NO_BATCH_CONTEXT";

    /** 状态=客户带走（特殊选项「余料带回」）—— 行业做法 1，企业零损失、不入可用池 */
    public static final String OPTION_TAKE_AWAY_FABRIC = "余料带回-布";
    public static final String OPTION_TAKE_AWAY_SHEER = "余料带回-纱";

    /** 未配置小件尺寸时的**显式**说明（判据 4：不得静默） */
    public static final String NOTICE_SPECS_UNCONFIGURED =
            "未配置小件用料尺寸 ⇒ 不产生匹配建议。本参数默认值为空（未启用），"
                    + "请在「参数总览 → 余料回收」里为需要的小件填上「用料长 × 用料宽」后再看匹配。";

    /** 取不到批次上下文时的**显式**说明 */
    public static final String NOTICE_NO_BATCH_CONTEXT =
            "该明细行取不到来源批次 ⇒ 取不到缸号与颜色，无法按「同缸号、同色」匹配 ⇒ 不产生建议（不猜颜色）。";

    /** 配了尺寸但没有装得下的余料时的**显式**说明 */
    public static final String REASON_NO_SUITABLE_REMNANT =
            "余料台账里没有装得下该小件的可用余料（尺寸不足 ⇒ 不推荐，不凭空推荐）";

    /** 未配置该小件尺寸时的**逐项**说明 */
    public static final String REASON_SPEC_NOT_CONFIGURED = "该小件未配置用料尺寸（默认值为空 = 未启用）";

    /** 尺寸取整方向 = 向下（见类注释） */
    private static final int SIZE_SCALE = 2;

    /**
     * 余料的**物理分辨率下限**（米）。
     *
     * <p>它不是业务阈值（<b>不编业务数值</b>），是「0 面积的矩形不是余料」这条物理事实：
     * 本仓宽高按厘米报（见 {@link CuttingPlanCalculator} 的容差注释），1 厘米以下的碎边
     * 既切不出任何东西、也会把台账灌满零面积行。列为常量并显式说明，而不是散在判断里。</p>
     */
    public static final BigDecimal MIN_REMNANT_DIM_M = new BigDecimal("0.01");

    private final FabricRemnantMapper remnantMapper;
    private final RemnantItemSizeMapper specMapper;
    private final StockBatchMapper stockBatchMapper;
    private final StockBatchConsumptionMapper consumptionMapper;
    private final ProductionOperationMapper operationMapper;
    private final ProductionOptionRoutingMapper optionRoutingMapper;
    private final OrderMapper orderMapper;
    private final OrderItemMapper orderItemMapper;

    // ══════════════════════════════════════════════════════════════════════════════════
    // ① 余料登记（时点 = 排料/派工结果自动产生）
    // ══════════════════════════════════════════════════════════════════════════════════

    /**
     * 一块待登记的余料（由 {@link StockBatchConsumptionService} 从排料清单算出）。
     *
     * <p>{@code pieceSeq} = 该块在这一份排料结果里的**确定序号**（同一份排料结果两遍得到同一组序号）
     * ⇒ 它是幂等闸 {@code uk_fabric_remnants_piece} 的键之一（重复登记撞唯一键而不是写两遍）。</p>
     */
    public record Draft(int pieceSeq, String pieceKind, BigDecimal lengthM, BigDecimal widthM) {
    }

    /**
     * 余料的**来源上下文**（= 这一组料裁自哪一卷）—— 由派工扣减行原样带过来。
     *
     * <p>缸号**不在**这里：它由本服务在登记那一刻从 {@code stock_batches} 读出并**快照**到余料行
     * （同 V119 的 {@code unit_cost} 快照纪律 —— 批次行的缸号事后可能被订正，历史余料不该跟着变）。</p>
     */
    public record Source(Long batchId, String batchNo, String productId, Long skuId, String skuCode) {
    }

    /**
     * 登记一份排料结果产生的余料（**自动产生**的唯一入口；由派工写面在同一事务内调用）。
     *
     * <p>「客户带走」（特殊选项 {@code 余料带回-布} / {@code 余料带回-纱}）在**订单级**判定
     * —— 客户把余料带走是整张单的安排，不是逐块的决定 ⇒ 整单的余料统一落
     * {@link FabricRemnant#STATUS_CUSTOMER_TAKEN}（仍然登记：账要平；但不进可用池、不参与匹配、不计回收）。</p>
     *
     * <p><b>幂等</b>：同一 {@code (tenant, 加工单, pieceSeq)} 已存在 ⇒ 跳过（重跑不重复登记）。
     * 服务层先查一次是为了让重跑**不报错**（唯一索引是第二道网，不是第一道）。</p>
     *
     * @return 实际登记的行数（0 = 没有余料 / 已登记过 ⇒ 主流程行为不变）
     */
    @Transactional
    public int accrue(Long tenantId, String processingOrderNo, String orderNo,
                      Source source, List<Draft> drafts) {
        if (drafts == null || drafts.isEmpty() || source == null
                || !StringUtils.hasText(processingOrderNo)) {
            return 0;
        }
        StockBatch batch = source.batchId() == null ? null
                : stockBatchMapper.selectById(source.batchId());
        String status = orderTakesRemnantsAway(tenantId, orderNo)
                ? FabricRemnant.STATUS_CUSTOMER_TAKEN : FabricRemnant.STATUS_AVAILABLE;
        OffsetDateTime now = OffsetDateTime.now();
        int inserted = 0;
        for (Draft draft : drafts) {
            if (draft == null || alreadyAccrued(tenantId, processingOrderNo, draft.pieceSeq())) {
                continue;
            }
            remnantMapper.insert(FabricRemnant.builder()
                    .tenantId(tenantId)
                    .pieceSeq(draft.pieceSeq())
                    .sourceOrderNo(orderNo)
                    .sourceProcessingOrderNo(processingOrderNo)
                    .sourceBatchId(source.batchId())
                    .sourceBatchNo(source.batchNo())
                    .dyeLot(batch == null ? null : batch.getDyeLot())
                    .productId(source.productId())
                    .skuId(source.skuId() != null ? source.skuId()
                            : (batch == null ? null : batch.getSkuId()))
                    .skuCode(StringUtils.hasText(source.skuCode()) ? source.skuCode()
                            : (batch == null ? null : batch.getSkuCode()))
                    .pieceKind(draft.pieceKind())
                    .lengthM(draft.lengthM())
                    .widthM(draft.widthM())
                    .status(status)
                    .createdAt(now)
                    .deleted(0)
                    .build());
            inserted++;
        }
        if (inserted > 0) {
            log.info("余料登记: tenant={}, po={}, order={}, batch={}, lines={}, status={}",
                    tenantId, processingOrderNo, orderNo, source.batchNo(), inserted, status);
        }
        return inserted;
    }

    private boolean alreadyAccrued(Long tenantId, String processingOrderNo, int pieceSeq) {
        return remnantMapper.selectCount(new LambdaQueryWrapper<FabricRemnant>()
                .eq(FabricRemnant::getTenantId, tenantId)
                .eq(FabricRemnant::getSourceProcessingOrderNo, processingOrderNo)
                .eq(FabricRemnant::getPieceSeq, pieceSeq)) > 0;
    }

    /**
     * 本订单是否「客户带走余料」（{@code processing_info.specialOptions} 含
     * {@link #OPTION_TAKE_AWAY_FABRIC} 或 {@link #OPTION_TAKE_AWAY_SHEER}）。
     *
     * <p>行业做法 1（回收率 100% —— 本来就是客户的）：企业零损失、不入库、不回收。
     * 本方法只回答「整单有没有勾」这一个问题；系统**不推算**客户会带走哪一块（不猜）。</p>
     */
    private boolean orderTakesRemnantsAway(Long tenantId, String orderNo) {
        if (!StringUtils.hasText(orderNo)) {
            return false;
        }
        Order order = orderMapper.selectOne(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId).eq(Order::getOrderNo, orderNo).last("LIMIT 1"));
        if (order == null) {
            return false;
        }
        for (OrderItem item : orderItemMapper.selectList(new LambdaQueryWrapper<OrderItem>()
                .eq(OrderItem::getTenantId, tenantId).eq(OrderItem::getOrderId, order.getId()))) {
            List<String> options = specialOptionsOf(item);
            if (options.contains(OPTION_TAKE_AWAY_FABRIC) || options.contains(OPTION_TAKE_AWAY_SHEER)) {
                return true;
            }
        }
        return false;
    }

    // ══════════════════════════════════════════════════════════════════════════════════
    // ② 小件用料尺寸表（可配参数：读 / 全量替换写）
    // ══════════════════════════════════════════════════════════════════════════════════

    /** 小件用料尺寸表读面（{@code configured=false} ⇒ {@code notice} 非空说明「未启用」） */
    public RemnantViews.SpecsView specs(Long tenantId) {
        List<RemnantItemSize> rows = specRows(tenantId);
        List<RemnantViews.SpecLine> items = new ArrayList<>(rows.size());
        for (RemnantItemSize row : rows) {
            items.add(new RemnantViews.SpecLine(row.getItemKey(), row.getLengthM(), row.getWidthM(),
                    row.getNote(), row.getOperator(), row.getUpdatedAt()));
        }
        boolean configured = !items.isEmpty();
        return new RemnantViews.SpecsView(configured, items,
                configured ? null : NOTICE_SPECS_UNCONFIGURED);
    }

    /**
     * 全量替换本租户的小件用料尺寸表（**空列表 = 清空 = 回到未配置**）。
     *
     * <p>为什么是全量替换而不是逐项 upsert：这张表**就是**商家的参数（一屏几条），
     * 全量替换让「删掉一个不再做的小件」与「改一个尺寸」用同一个动作表达，
     * 不会留下「以为删了其实还在」的行。逐项语义由页面负责（它提交的是编辑后的完整表）。</p>
     *
     * @param items 每项形如 {@code {item_key, length_m, width_m, note?}}；非法值 ⇒ 422 逐条理由
     */
    @Transactional
    public RemnantViews.SpecsView putSpecs(Long tenantId, List<Map<String, Object>> items) {
        String operator = StockLedgerService.resolveOperator();
        OffsetDateTime now = OffsetDateTime.now();
        List<RemnantItemSize> rows = new ArrayList<>();
        Set<String> seen = new LinkedHashSet<>();
        for (Map<String, Object> raw : items == null ? List.<Map<String, Object>>of() : items) {
            String key = str(raw.get("item_key"));
            if (key == null) {
                key = str(raw.get("itemKey"));
            }
            if (key == null) {
                throw BusinessException.validationError("小件配置缺少 item_key（= 该小件对应的工序名）");
            }
            if (!seen.add(key)) {
                throw BusinessException.validationError("小件配置重复：item_key = " + key);
            }
            BigDecimal length = dec(raw.get("length_m"));
            BigDecimal width = dec(raw.get("width_m"));
            if (length == null || length.signum() <= 0 || width == null || width.signum() <= 0) {
                throw BusinessException.validationError(
                        "小件 " + key + " 的用料尺寸必须为正数（length_m / width_m 都要填）");
            }
            // 🔴 键必须是**本租户工序库里真有的工序名**：匹配的触发链是
            // 「特殊选项 → 条件工序（production_option_routings）→ 按工序名查尺寸表」，
            // 打错一个字 ⇒ 这张尺寸行**永远不会被命中**（静默失效 —— 配了却像没配）。
            // 在这里当场拒绝，是把「配了不生效」变成「配的时候就告诉你」的唯一便宜办法。
            String operationName = operationNameOf(tenantId, key);
            if (operationName == null) {
                throw BusinessException.validationError(
                        "工序库里没有「" + key + "」这道工序 ⇒ 该小件永远不会被匹配到（键必须与工序名逐字一致）");
            }
            key = operationName;
            rows.add(RemnantItemSize.builder()
                    .tenantId(tenantId).itemKey(key).lengthM(length).widthM(width)
                    .note(str(raw.get("note"))).operator(operator)
                    .createdAt(now).updatedAt(now).deleted(0).build());
        }
        // 清空 + 重写：本表是**参数**（一屏几条），全量替换的语义比逐行 diff 少一整类「半更新」失效形态。
        for (RemnantItemSize old : specRows(tenantId)) {
            specMapper.deleteById(old.getId());
        }
        for (RemnantItemSize row : rows) {
            specMapper.insert(row);
        }
        log.info("小件用料尺寸表已替换: tenant={}, operator={}, lines={}", tenantId, operator, rows.size());
        return specs(tenantId);
    }

    /** 工序名（本租户工序库里**逐字**存在才回值，否则 {@code null}）—— 见 {@link #putSpecs} 的键校验。 */
    private String operationNameOf(Long tenantId, String itemKey) {
        ProductionOperation operation = operationMapper.selectOne(
                new LambdaQueryWrapper<ProductionOperation>()
                        .eq(ProductionOperation::getTenantId, tenantId)
                        .eq(ProductionOperation::getName, itemKey).last("LIMIT 1"));
        return operation == null ? null : operation.getName();
    }

    private List<RemnantItemSize> specRows(Long tenantId) {
        return specMapper.selectList(new LambdaQueryWrapper<RemnantItemSize>()
                .eq(RemnantItemSize::getTenantId, tenantId)
                .orderByAsc(RemnantItemSize::getItemKey));
    }

    // ══════════════════════════════════════════════════════════════════════════════════
    // ③ 小件优先匹配（先从余料台账找；找得到 ⇒ 不新领料）
    // ══════════════════════════════════════════════════════════════════════════════════

    /**
     * 为一张订单明细行里的**小件需求**匹配可用余料。
     *
     * <p>小件需求**不另造口径**：来自该行勾选的特殊选项，经
     * {@code production_option_routings}（特殊选项 → 条件工序的**既有唯一真值源**，
     * 与工序实例化读的是同一张表）解析成工序名集合；再用工序名去查小件尺寸表
     * （「配置即启用」：有尺寸行 ⇒ 该小件启用余料匹配）。</p>
     *
     * @param batchNo 该行实际领料的批次号（决定缸号与颜色）；为空 ⇒ 从**批次消耗台账**里按
     *                {@code order_item_id} 反查最近一次扣减（台账本来就记着「这一行从哪一批裁」）
     *                ⇒ 仍然取不到 ⇒ **不产生任何建议** + 显式说明（{@link #NOTICE_NO_BATCH_CONTEXT}）
     */
    public RemnantViews.MatchView match(Long tenantId, String orderItemId, String batchNo) {
        if (!StringUtils.hasText(orderItemId)) {
            throw BusinessException.validationError("orderItemId 不能为空（匹配是逐明细行的事）");
        }
        OrderItem item = orderItemMapper.selectOne(new LambdaQueryWrapper<OrderItem>()
                .eq(OrderItem::getTenantId, tenantId).eq(OrderItem::getId, orderItemId).last("LIMIT 1"));
        if (item == null) {
            throw new BusinessException(ERR_REMNANT_NOT_FOUND, "订单明细行不存在：" + orderItemId, 404);
        }
        List<String> options = specialOptionsOf(item);
        Map<String, List<String>> optionsByItemKey = requiredItems(tenantId, options);
        List<String> required = List.copyOf(optionsByItemKey.keySet());

        Map<String, RemnantItemSize> specs = new LinkedHashMap<>();
        for (RemnantItemSize row : specRows(tenantId)) {
            specs.put(row.getItemKey(), row);
        }
        if (specs.isEmpty()) {
            // 🔴 判据 4「未配置不静默」：不产生任何推荐 + **显式**说明（不是静默空列表）
            return new RemnantViews.MatchView(false, NOTICE_SPECS_UNCONFIGURED, required,
                    List.of(), List.of(), required);
        }
        if (required.isEmpty()) {
            return new RemnantViews.MatchView(true, null, List.of(), List.of(), List.of(), List.of());
        }

        StockBatch batch = resolveBatch(tenantId, orderItemId, batchNo);
        List<RemnantViews.Recommendation> recommendations = new ArrayList<>();
        List<RemnantViews.Unmatched> unmatched = new ArrayList<>();
        List<String> unconfigured = new ArrayList<>();
        Set<Long> takenRemnantIds = new LinkedHashSet<>();
        boolean batchContextMissing = batch == null;
        for (Map.Entry<String, List<String>> entry : optionsByItemKey.entrySet()) {
            String itemKey = entry.getKey();
            RemnantItemSize spec = specs.get(itemKey);
            if (spec == null) {
                unconfigured.add(itemKey);
                unmatched.add(new RemnantViews.Unmatched(itemKey, entry.getValue(),
                        REASON_SPEC_NOT_CONFIGURED));
                continue;
            }
            RemnantViews.Recommendation hit = batchContextMissing ? null
                    : findCandidate(tenantId, batch, spec, itemKey, entry.getValue(), takenRemnantIds);
            if (hit == null) {
                unmatched.add(new RemnantViews.Unmatched(itemKey, entry.getValue(),
                        batchContextMissing ? NOTICE_NO_BATCH_CONTEXT : REASON_NO_SUITABLE_REMNANT));
                continue;
            }
            takenRemnantIds.add(hit.remnantId());
            recommendations.add(hit);
        }
        return new RemnantViews.MatchView(true,
                batchContextMissing ? NOTICE_NO_BATCH_CONTEXT : null,
                required, recommendations, unmatched, unconfigured);
    }

    /**
     * 从**该行实际领料的批次**出发找一块装得下的可用余料。
     *
     * <p>排序由 SQL 给出（同缸号 → 同色 → 长度升序 → id，见 {@link FabricRemnantMapper}），
     * 这里只做**硬底线**判定：候选必须「同缸号 **或** 同色」——两者都不满足就是另一匹布
     * （色差是窗帘行业最不能接受的质量事故），直接淘汰而不是「聊胜于无」。</p>
     *
     * <p>被同一张单的另一个小件先拿走的余料不再参与（{@code taken}），
     * 且用 {@link RemnantItemSize#fits} 复核 SQL 的尺寸谓词（两处判据一致 ⇒ 查询写宽了也拦得住）。</p>
     */
    private RemnantViews.Recommendation findCandidate(
            Long tenantId, StockBatch batch, RemnantItemSize spec, String itemKey,
            List<String> optionNames, Set<Long> taken) {
        List<FabricRemnant> candidates = remnantMapper.findMatchCandidates(tenantId,
                batch.getProductId(), batch.getDyeLot(), batch.getSkuCode(),
                spec.getLengthM(), spec.getWidthM());
        for (FabricRemnant candidate : candidates) {
            if (taken.contains(candidate.getId()) || !spec.fits(candidate.getLengthM(), candidate.getWidthM())) {
                continue;
            }
            boolean sameDyeLot = StringUtils.hasText(batch.getDyeLot())
                    && batch.getDyeLot().equals(candidate.getDyeLot());
            boolean sameSku = StringUtils.hasText(batch.getSkuCode())
                    && batch.getSkuCode().equals(candidate.getSkuCode());
            if (!sameDyeLot && !sameSku) {
                continue; // 防色差底线：不同缸号且不同色 ⇒ 淘汰
            }
            // 回收额 = 用掉米数 × **该余料来源批次**的均价（元/米）；均价随行快照，事后改价不影响
            BigDecimal unitCost = unitCostOf(tenantId, candidate.getSourceBatchId());
            BigDecimal meters = candidate.getLengthM();
            BigDecimal amount = unitCost == null ? null : meters.multiply(unitCost);
            return new RemnantViews.Recommendation(itemKey, optionNames, candidate.getId(),
                    candidate.getLengthM(), candidate.getWidthM(), candidate.getSourceBatchNo(),
                    candidate.getDyeLot(), sameDyeLot, sameSku, unitCost, meters, amount,
                    sameDyeLot ? "MATCHED_SAME_DYE_LOT" : "MATCHED_SAME_COLOR_OTHER_DYE_LOT");
        }
        return null;
    }

    /**
     * 该明细行实际领料的批次：入参优先；为空则从**批次消耗台账**反查最近一次扣减行的批次号
     * （台账本来就记着「这一行从哪一批裁」，不另造查找路径）。
     */
    private StockBatch resolveBatch(Long tenantId, String orderItemId, String batchNo) {
        String resolved = StringUtils.hasText(batchNo) ? batchNo.trim() : null;
        if (resolved == null) {
            StockBatchConsumption last = consumptionMapper.selectOne(
                    new LambdaQueryWrapper<StockBatchConsumption>()
                            .eq(StockBatchConsumption::getTenantId, tenantId)
                            .eq(StockBatchConsumption::getOrderItemId, orderItemId)
                            .eq(StockBatchConsumption::getReason,
                                    StockBatchConsumption.REASON_PROCESSING_ORDER)
                            .orderByDesc(StockBatchConsumption::getId).last("LIMIT 1"));
            resolved = last == null ? null : last.getBatchNo();
        }
        if (resolved == null) {
            return null;
        }
        return stockBatchMapper.selectOne(new LambdaQueryWrapper<StockBatch>()
                .eq(StockBatch::getTenantId, tenantId).eq(StockBatch::getBatchNo, resolved)
                .last("LIMIT 1"));
    }

    /** 该行的小件需求：特殊选项 → 工序名（既有唯一真值源 {@code production_option_routings}），保序去重。 */
    private Map<String, List<String>> requiredItems(Long tenantId, List<String> options) {
        Map<String, List<String>> byItemKey = new LinkedHashMap<>();
        if (options.isEmpty()) {
            return byItemKey;
        }
        for (ProductionOptionRouting routing : optionRoutingMapper.selectList(
                new LambdaQueryWrapper<ProductionOptionRouting>()
                        .eq(ProductionOptionRouting::getTenantId, tenantId)
                        .eq(ProductionOptionRouting::getStatus, "active")
                        .in(ProductionOptionRouting::getOptionName, options))) {
            byItemKey.computeIfAbsent(routing.getOperationName(), k -> new ArrayList<>())
                    .add(routing.getOptionName());
        }
        return byItemKey;
    }

    // ══════════════════════════════════════════════════════════════════════════════════
    // ④ 回收记账 + 报废留痕
    // ══════════════════════════════════════════════════════════════════════════════════

    /**
     * 余料被用掉 ⇒ 记回收（**冲减使用它的那张单的面料成本**）。
     *
     * <p>🔴 <b>本方法不写任何 {@code stock_batch_consumptions} 行</b> —— 这正是判据 3
     * 「该小件不产生新的批次消耗（批次数不变）」的落点：小件的料来自**已经领下来**的余料，
     * 不新领料、不新增批次扣减。红证 = 改成「先扣一批新料再记回收」⇒ 批次数变了 ⇒ 判红。</p>
     *
     * <p>三条 fail-closed 判据（都不许静默放过）：</p>
     * <ol>
     *   <li>余料必须在且处于 {@code available}（已用 / 已报废 / **客户带走**都不能再回收）；</li>
     *   <li>该小件必须**配了尺寸**且余料**装得下**（读面不推荐，写面也不放行 —— 两层同一判据）；</li>
     *   <li>来源批次必须**记了均价** ⇒ 否则算不出回收额：显式拒绝（<b>宁可为失败，不许估</b>）；
     *       均价在**回收这一刻**从 {@code stock_batches.unit_cost} 取一次并**快照**到余料行
     *       ⇒ 之后改批次均价**不会**改掉历史读数。</li>
     * </ol>
     */
    @Transactional
    public RemnantViews.RemnantLine recover(Long tenantId, Long remnantId,
                                            String orderItemId, String orderNo, String itemKey) {
        if (!StringUtils.hasText(itemKey)) {
            throw BusinessException.validationError("itemKey 不能为空（要记清这块余料用在了哪个小件上）");
        }
        FabricRemnant remnant = require(tenantId, remnantId);
        if (!FabricRemnant.STATUS_AVAILABLE.equals(remnant.getStatus())) {
            throw new BusinessException(ERR_REMNANT_NOT_AVAILABLE,
                    String.format("余料 %s 当前状态 [%s]，只有「可用」的余料才能回收（客户带走的余料归客户）",
                            remnantId, remnant.getStatus()), 409,
                    "请刷新余料台账后重试");
        }
        Map<String, RemnantItemSize> specs = new LinkedHashMap<>();
        for (RemnantItemSize row : specRows(tenantId)) {
            specs.put(row.getItemKey(), row);
        }
        RemnantItemSize spec = specs.get(itemKey);
        if (spec == null) {
            throw new BusinessException(ERR_REMNANT_SPEC_REQUIRED,
                    String.format("小件 %s 未配置用料尺寸 ⇒ 无法判定这块余料装不装得下", itemKey), 422,
                    "请先在「参数总览 → 余料回收」里为它填上用料尺寸（长 × 宽）");
        }
        if (!spec.fits(remnant.getLengthM(), remnant.getWidthM())) {
            throw new BusinessException(ERR_REMNANT_TOO_SMALL,
                    String.format("余料 %s 的尺寸 %s × %s 装不下小件 %s 需要的 %s × %s",
                            remnantId, plain(remnant.getLengthM()), plain(remnant.getWidthM()),
                            itemKey, plain(spec.getLengthM()), plain(spec.getWidthM())), 422,
                    "请从匹配建议里选一块装得下的余料（尺寸不足不推荐、也不放行）");
        }
        BigDecimal unitCost = unitCostOf(tenantId, remnant.getSourceBatchId());
        if (unitCost == null) {
            throw new BusinessException(ERR_REMNANT_BATCH_COST_UNKNOWN,
                    String.format("来源批次 %s 没有记录均价 ⇒ 回收额算不出来（不许估一个价）",
                            remnant.getSourceBatchNo()), 422,
                    "请先在批次台账里补该批次的入库均价，再回收这块余料");
        }
        BigDecimal meters = remnant.getLengthM();
        // 金额**不在这里舍入**：DB 约束是「逐值相等 recovered_amount = meters × unit_cost」，
        // 先舍入就会让约束失败（列精度 6 位正好容得下 2 位 × 4 位的精确积）。
        BigDecimal amount = meters.multiply(unitCost);
        FabricRemnant patch = FabricRemnant.builder()
                .id(remnant.getId())
                .status(FabricRemnant.STATUS_USED)
                .usedByOrderNo(orderNo)
                .usedByOrderItemId(orderItemId)
                .usedByItemKey(itemKey)
                .recoveredMeters(meters)
                .recoveredUnitCost(unitCost)
                .recoveredAmount(amount)
                .recoveredAt(OffsetDateTime.now())
                .recoveredBy(StockLedgerService.resolveOperator())
                .build();
        remnantMapper.updateById(patch);
        log.info("余料回收: tenant={}, remnant={}, item={}, order={}, meters={}, unitCost={}, amount={}",
                tenantId, remnantId, itemKey, orderNo, meters, unitCost, amount);
        return line(require(tenantId, remnantId));
    }

    /**
     * 报废留痕（超期 / 尺寸不足 ⇒ 报废；**谁、何时、为什么**都要留下）。
     *
     * <p>只有「可用」的余料能报废：客户带走的余料**不是企业的**（无权处置），
     * 已用 / 已报废的不能再报废一次（重复报废 = 报废率失真）。</p>
     */
    @Transactional
    public RemnantViews.RemnantLine scrap(Long tenantId, Long remnantId, String reason) {
        if (!StringUtils.hasText(reason)) {
            throw BusinessException.validationError("报废必须写原因（报废留痕要答得出「为什么」）");
        }
        FabricRemnant remnant = require(tenantId, remnantId);
        if (!FabricRemnant.STATUS_AVAILABLE.equals(remnant.getStatus())) {
            throw new BusinessException(ERR_REMNANT_NOT_AVAILABLE,
                    String.format("余料 %s 当前状态 [%s]，只有「可用」的余料才能报废"
                                    + "（客户带走的余料归客户，企业无权处置）",
                            remnantId, remnant.getStatus()), 409,
                    "请刷新余料台账后重试");
        }
        remnantMapper.updateById(FabricRemnant.builder()
                .id(remnant.getId())
                .status(FabricRemnant.STATUS_SCRAPPED)
                .scrapReason(reason.trim())
                .scrappedAt(OffsetDateTime.now())
                .scrappedBy(StockLedgerService.resolveOperator())
                .build());
        log.info("余料报废: tenant={}, remnant={}, reason={}", tenantId, remnantId, reason);
        return line(require(tenantId, remnantId));
    }

    // ══════════════════════════════════════════════════════════════════════════════════
    // ⑤ 读面（台账 + 度量）
    // ══════════════════════════════════════════════════════════════════════════════════

    /** 台账读面（列表 + 汇总）；{@code status} 为空 ⇒ 全部状态。 */
    public RemnantViews.LedgerView ledger(Long tenantId, String status, String batchNo,
                                          String orderNo, long page, long size) {
        LambdaQueryWrapper<FabricRemnant> wrapper = new LambdaQueryWrapper<FabricRemnant>()
                .eq(FabricRemnant::getTenantId, tenantId)
                .eq(StringUtils.hasText(status), FabricRemnant::getStatus, status)
                .eq(StringUtils.hasText(batchNo), FabricRemnant::getSourceBatchNo, batchNo)
                .eq(StringUtils.hasText(orderNo), FabricRemnant::getSourceOrderNo, orderNo)
                .orderByDesc(FabricRemnant::getId);
        Page<FabricRemnant> result = remnantMapper.selectPage(
                new Page<>(page < 1 ? 1 : page, size < 1 ? 20 : Math.min(size, 200)), wrapper);
        List<RemnantViews.RemnantLine> lines = new ArrayList<>(result.getRecords().size());
        for (FabricRemnant row : result.getRecords()) {
            lines.add(line(row));
        }
        return new RemnantViews.LedgerView(
                PageResponse.of(result.getTotal(), result.getCurrent(), result.getSize(), lines),
                summary(tenantId));
    }

    /**
     * 度量（issue #5146「度量可算」）：{@code 余料回收率 = Σ回收额 / Σ领料成本}、{@code 报废率 = Σ报废米数 / Σ余料米数}。
     *
     * <p>分母的来源与口径都写在字段名里，页面不再自算（本仓纪律：钱与米数的判定只在服务端）。
     * 分母为零 ⇒ 比率回 {@code null}（**不是 0** —— 「算不出来」与「是零」必须能分开）。</p>
     */
    public RemnantViews.Summary summary(Long tenantId) {
        List<FabricRemnant> all = remnantMapper.selectList(new LambdaQueryWrapper<FabricRemnant>()
                .eq(FabricRemnant::getTenantId, tenantId));
        int available = 0;
        int used = 0;
        int scrapped = 0;
        int customerTaken = 0;
        BigDecimal availableMeters = BigDecimal.ZERO;
        BigDecimal recoveredMeters = BigDecimal.ZERO;
        BigDecimal scrappedMeters = BigDecimal.ZERO;
        BigDecimal recoveredAmount = BigDecimal.ZERO;
        for (FabricRemnant row : all) {
            BigDecimal meters = row.getLengthM() == null ? BigDecimal.ZERO : row.getLengthM();
            switch (row.getStatus() == null ? "" : row.getStatus()) {
                case FabricRemnant.STATUS_AVAILABLE -> {
                    available++;
                    availableMeters = availableMeters.add(meters);
                }
                case FabricRemnant.STATUS_USED -> {
                    used++;
                    recoveredMeters = recoveredMeters.add(meters);
                    recoveredAmount = recoveredAmount.add(
                            row.getRecoveredAmount() == null ? BigDecimal.ZERO : row.getRecoveredAmount());
                }
                case FabricRemnant.STATUS_SCRAPPED -> {
                    scrapped++;
                    scrappedMeters = scrappedMeters.add(meters);
                }
                case FabricRemnant.STATUS_CUSTOMER_TAKEN -> customerTaken++;
                default -> { /* 未知状态由 DB 约束挡在写面；读面不猜 */ }
            }
        }
        BigDecimal issuedCost = issuedCostTotal(tenantId);
        BigDecimal totalMeters = availableMeters.add(recoveredMeters).add(scrappedMeters);
        return new RemnantViews.Summary(available, used, scrapped, customerTaken,
                availableMeters, recoveredMeters, scrappedMeters, recoveredAmount, issuedCost,
                rate(recoveredAmount, issuedCost), rate(scrappedMeters, totalMeters));
    }

    /**
     * Σ领料成本 = Σ(|{@code planned_meters}| × 当时均价)（源 {@code stock_batch_consumptions}，V119 随行快照）。
     *
     * <p>均价未知的行**不参与**（拿今天的批次价折算历史领料成本，正是 V119 要防的那件事）
     * ⇒ 分母是「**已知均价**那部分领料成本」，照实登记在字段名 {@code issuedCostTotal} 上。</p>
     */
    private BigDecimal issuedCostTotal(Long tenantId) {
        BigDecimal total = BigDecimal.ZERO;
        for (StockBatchConsumption row : consumptionMapper.selectList(
                new LambdaQueryWrapper<StockBatchConsumption>()
                        .eq(StockBatchConsumption::getTenantId, tenantId)
                        .isNotNull(StockBatchConsumption::getUnitCost)
                        .isNotNull(StockBatchConsumption::getPlannedMeters))) {
            total = total.add(row.getPlannedMeters().abs().multiply(row.getUnitCost()));
        }
        return total;
    }

    /** 比率（分母 ≤ 0 ⇒ {@code null}：算不出来 ≠ 是零）；保留 4 位。 */
    private static BigDecimal rate(BigDecimal numerator, BigDecimal denominator) {
        if (numerator == null || denominator == null || denominator.signum() <= 0) {
            return null;
        }
        return numerator.divide(denominator, 4, RoundingMode.HALF_UP);
    }

    private FabricRemnant require(Long tenantId, Long remnantId) {
        FabricRemnant remnant = remnantId == null ? null : remnantMapper.selectOne(
                new LambdaQueryWrapper<FabricRemnant>()
                        .eq(FabricRemnant::getTenantId, tenantId)
                        .eq(FabricRemnant::getId, remnantId).last("LIMIT 1"));
        if (remnant == null) {
            throw new BusinessException(ERR_REMNANT_NOT_FOUND, "余料不存在：" + remnantId, 404);
        }
        return remnant;
    }

    /** 该余料来源批次的**当前**均价（回收/建议那一刻读一次 ⇒ 快照落库）。 */
    private BigDecimal unitCostOf(Long tenantId, Long batchId) {
        if (batchId == null) {
            return null;
        }
        StockBatch batch = stockBatchMapper.selectOne(new LambdaQueryWrapper<StockBatch>()
                .eq(StockBatch::getTenantId, tenantId).eq(StockBatch::getId, batchId).last("LIMIT 1"));
        return batch == null ? null : batch.getUnitCost();
    }

    private static RemnantViews.RemnantLine line(FabricRemnant row) {
        return new RemnantViews.RemnantLine(row.getId(), row.getPieceSeq(), row.getPieceKind(),
                row.getLengthM(), row.getWidthM(), row.getAreaM2(),
                row.getSourceOrderNo(), row.getSourceProcessingOrderNo(), row.getSourceBatchNo(),
                row.getDyeLot(), row.getProductId(), row.getSkuCode(), row.getStatus(),
                row.getUsedByOrderNo(), row.getUsedByOrderItemId(), row.getUsedByItemKey(),
                row.getRecoveredMeters(), row.getRecoveredUnitCost(), row.getRecoveredAmount(),
                row.getRecoveredAt(), row.getRecoveredBy(),
                row.getScrapReason(), row.getScrappedAt(), row.getScrappedBy(), row.getCreatedAt());
    }

    // ══════════════════════════════════════════════════════════════════════════════════
    // 小工具（与 ProcessingOrderService#specialOptions 同口径：只认字符串数组，缺失/脏形态 ⇒ 不猜）
    // ══════════════════════════════════════════════════════════════════════════════════

    /** 本行携带的特殊选项（{@code processing_info.specialOptions: string[]}），保序去重。 */
    static List<String> specialOptionsOf(OrderItem item) {
        Object raw = OrderLineCraftFields.normalize(item == null ? null : item.getProcessingInfo())
                .get("specialOptions");
        if (!(raw instanceof List<?> list)) {
            return List.of();
        }
        List<String> options = new ArrayList<>(list.size());
        for (Object element : list) {
            String option = str(element);
            if (option != null && !options.contains(option)) {
                options.add(option);
            }
        }
        return options;
    }

    private static String str(Object value) {
        if (value == null) {
            return null;
        }
        String text = String.valueOf(value).trim();
        return text.isEmpty() ? null : text;
    }

    private static BigDecimal dec(Object value) {
        if (value instanceof BigDecimal decimal) {
            return decimal;
        }
        if (value instanceof Number number) {
            return new BigDecimal(number.toString());
        }
        String text = str(value);
        if (text == null) {
            return null;
        }
        try {
            return new BigDecimal(text).setScale(SIZE_SCALE, RoundingMode.FLOOR);
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static String plain(BigDecimal value) {
        return value == null ? "—" : value.stripTrailingZeros().toPlainString();
    }
}
