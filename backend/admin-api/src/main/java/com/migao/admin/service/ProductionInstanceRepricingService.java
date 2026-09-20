package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProductionInstanceRepricingLog;
import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProductionInstanceRepricingLogMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

/**
 * <b>未定价实例的显式补价路径</b>（issue #4709 C，P1）。
 *
 * <h2>缺陷原形（商家视角的真问题）</h2>
 * V90（issue #4696）把三态做进数据层：<b>未定价</b>（实例 {@code unit_price IS NULL}）/
 * <b>价 0</b> / <b>有价</b>。但**已实例化**的旧单在商家事后补定价时**没有任何补价路径**：
 * <ol>
 *   <li>商家在「工艺配置 → 工艺路线」的部位价目矩阵里给「裁剪 × 布料」「打包」填了价；</li>
 *   <li>旧单的实例快照仍是 {@code NULL}（未定价）⇒ 工人那批活的钱**还是算不出来**
 *       （报工快照按实例价写入 ⇒ {@code price_state='unpriced'} ⇒ 不进计件合计）；</li>
 *   <li>重新实例化**不是**可用路径：{@code OpSpec.signature()} 的 {@code num()} 是
 *       {@code nz(value).stripTrailingZeros()} ⇒ {@code null} 与 {@code 0} **同签名**
 *       ⇒「未定价 ↔ 定价 0」的切换不判「工艺变更」（不软删重插，安全方向）；
 *       而 {@code null → 非 0} 虽会判变更，代价是**软删旧实例 + 重插 + 报工进度清零**
 *       （红线 ④ 禁止）。</li>
 * </ol>
 *
 * <h2>本类做什么（**只做一件事**）</h2>
 * 把该加工单里 {@code unit_price IS NULL} 的实例行补成**当前矩阵价**
 * （{@code production_operation_positions} 的 {@code (部位, 逻辑工序)} 格，与实例化路径**同一份读面**），
 * 并**留痕 + 可回滚**。三个「不」是硬约束（逐条有机械判据，见
 * {@link ProcessingPositionOperationMapper#fillUnpricedUnitPrice}）：
 * <ul>
 *   <li><b>不改写任何已有价的行</b>（{@code > 0} 或 {@code 0} 一律不动）—— SQL 谓词
 *       {@code AND unit_price IS NULL}；</li>
 *   <li><b>不碰报工进度</b>（{@code done_qty} / {@code status}）与计件系数 {@code factor} ——
 *       SET 子句只有 {@code unit_price} + {@code updated_at}；</li>
 *   <li><b>不碰历史报工</b>（{@code production_work_logs.unit_price} / {@code factor}）——
 *       本类根本不注入报工表 Mapper（结构判据）。</li>
 * </ul>
 *
 * <h2>为什么不是「读面实时取价」（issue #4709 的路径 ②，本单不采用）</h2>
 * 实例单价是**下单（实例化）时刻的快照**，改价只影响新报工（真值源 §4「历史报工按当时价，
 * 逐笔可追溯」）。读面按当前矩阵价给 {@code NULL} 实例显示「预计金额」会让**界面数字**与
 * **工人实际拿到的钱**变成两套口径 —— 且这套口径在报工那一刻就分叉（报工快照仍取实例值）。
 * ⇒ 走**显式动作**：商家点一次、看得见改了什么、能回滚。
 *
 * <h2>边界（如实登记，不粉饰）</h2>
 * 补价只改**实例快照**⇒ 只影响**之后的报工**（以及报工时无 {@code price_state} 标记的存量行回查）。
 * **已经报过的**未定价报工（{@code price_state='unpriced'}）**不会**被追溯改价：金额在报工那一刻
 * 固化（#4351 / #4604「不追溯」），红线 ② 也逐字禁止改写 {@code production_work_logs} 的历史值。
 * 那些笔仍由 {@code unpriced} 块显式列出（#4696），商家据实核对。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProductionInstanceRepricingService {

    /** 补价后仍有工序没补上（矩阵格仍是 {@code NULL}）时的可行动提示。 */
    static final String STILL_UNPRICED_HINT =
            "仍有工序未定价（矩阵格为空）：请在「工艺配置 → 工艺路线」的部位价目矩阵里为对应"
                    + "「工序 × 部位」格填入单价（路径 /production/routings），再回来重算一次。";

    /** 全部补上（或本来就没有未定价实例）时的提示。 */
    static final String FILLED_HINT =
            "已按当前矩阵价补齐未定价工序实例；报工将按补上的单价计件。"
                    + "补价只影响之后的报工，已报过的未定价报工不会被追溯改价（金额在报工那一刻固化）。";

    private final OrderMapper orderMapper;
    private final ProcessingOrderMapper processingOrderMapper;
    private final ProcessingPositionOperationMapper positionOperationMapper;
    private final ProductionOperationQueryService productionOperationQueryService;
    private final ProductionInstanceRepricingLogMapper repricingLogMapper;

    /**
     * 「按当前价重算未定价实例」：只补 {@code NULL}，已有价（含 0）一律不动。
     *
     * <p><b>幂等</b>：重复执行 ⇒ 第一次已把能补的补完，第二次 {@code filled=0}
     * （谓词 {@code unit_price IS NULL} 不再命中）⇒ 净效果相同，且**不产生新的账行**。</p>
     *
     * @param orderId 订单 id（与 {@code GET /orders/{orderId}/piecework} 同一寻址口径）
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> repriceUnpricedInstances(String orderId, Long tenantId) {
        Order order = resolveOrder(orderId, tenantId);
        ProcessingOrder po = processingOrderMapper.selectActiveByOrderId(order.getId(), tenantId);
        if (po == null) {
            return emptyResult(order.getId(), "该订单暂无活跃加工单（无工序实例可补价）。");
        }

        Map<String, BigDecimal> priceByCell = currentMatrixPrices(tenantId);
        List<ProcessingPositionOperation> instances = listInstances(po.getId(), tenantId);

        String batchId = UUID.randomUUID().toString().replace("-", "");
        OffsetDateTime now = OffsetDateTime.now();
        List<Map<String, Object>> filled = new ArrayList<>();
        List<Map<String, Object>> stillUnpriced = new ArrayList<>();
        int alreadyPriced = 0;
        for (ProcessingPositionOperation op : instances) {
            // 🔴 红线 ①：已有价的行（> 0 或 0）**一个字段都不碰**（0 是「显式定价 0 元」，不是未定价）
            if (op.getUnitPrice() != null) {
                alreadyPriced++;
                continue;
            }
            BigDecimal price = priceByCell.get(cellKey(op));
            if (price == null) {
                // 矩阵格仍是 NULL（或该 (部位, 工序) 格不存在）⇒ 仍未定价，如实列出来
                stillUnpriced.add(operationRow(op, null));
                continue;
            }
            int updated = positionOperationMapper.fillUnpricedUnitPrice(op.getId(), tenantId, price, now);
            if (updated != 1) {
                // 并发下该行已被别的请求补价 / 已软删 / 跨租户 ⇒ 本行未动，不记账（不谎报已补）
                alreadyPriced++;
                continue;
            }
            repricingLogMapper.insert(ProductionInstanceRepricingLog.builder()
                    .tenantId(tenantId)
                    .batchId(batchId)
                    .processingOrderId(po.getId())
                    .positionOperationId(op.getId())
                    .newUnitPrice(price)
                    .createdAt(now)
                    .deleted(0)
                    .build());
            filled.add(operationRow(op, price));
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("order_id", order.getId());
        result.put("processing_order_id", po.getId());
        result.put("batch_id", filled.isEmpty() ? null : batchId);
        result.put("filled", filled.size());
        result.put("already_priced", alreadyPriced);
        result.put("still_unpriced", stillUnpriced.size());
        result.put("filled_operations", filled);
        result.put("still_unpriced_operations", stillUnpriced);
        result.put("hint", stillUnpriced.isEmpty() ? FILLED_HINT : STILL_UNPRICED_HINT);
        log.info("未定价实例补价: po={}, orderId={}, batch={}, filled={}, stillUnpriced={}, alreadyPriced={}",
                po.getProcessingOrderNo(), order.getId(), batchId, filled.size(), stillUnpriced.size(), alreadyPriced);
        return result;
    }

    /**
     * 回滚**一次补价动作**（按 {@code batchId}）：把本批补上的行还原成未定价（{@code unit_price = NULL}）。
     *
     * <p>判据只来自账本（这正是「留痕」的必要性）：逐行用
     * {@link ProcessingPositionOperationMapper#revertFilledUnitPrice} 的 CAS 谓词
     * （{@code unit_price = 账本记录的那次补价}）⇒ 商家自己定的价（不在账本里）、之后被改过或已重新
     * 实例化（软删）的行**永远**匹配不到。**幂等**：重复回滚 ⇒ 账本里已无「未回滚」行 ⇒
     * {@code reverted=0}，实例行不再变化。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> rollback(String batchId, Long tenantId) {
        if (!StringUtils.hasText(batchId)) {
            throw new BusinessException("INVALID_BATCH_ID", "缺少补价批次号，无法回滚", 422,
                    "请在补价结果里取 batch_id（或直接对未定价实例再执行一次补价）");
        }
        List<ProductionInstanceRepricingLog> rows = repricingLogMapper.selectList(
                new LambdaQueryWrapper<ProductionInstanceRepricingLog>()
                        .eq(ProductionInstanceRepricingLog::getTenantId, tenantId)
                        .eq(ProductionInstanceRepricingLog::getBatchId, batchId)
                        .eq(ProductionInstanceRepricingLog::getDeleted, 0)
                        .isNull(ProductionInstanceRepricingLog::getRolledBackAt));
        OffsetDateTime now = OffsetDateTime.now();
        int reverted = 0;
        int skipped = 0;
        for (ProductionInstanceRepricingLog row : rows) {
            int changed = positionOperationMapper.revertFilledUnitPrice(
                    row.getPositionOperationId(), tenantId, row.getNewUnitPrice(), now);
            if (changed != 1) {
                // 该行当前值已不是本批补的价（被改过 / 已软删）⇒ 不还原、不谎报已回滚
                skipped++;
                continue;
            }
            repricingLogMapper.markRolledBack(row.getId(), tenantId, now);
            reverted++;
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("batch_id", batchId);
        result.put("reverted", reverted);
        result.put("skipped", skipped);
        result.put("hint", skipped == 0
                ? "本批补价已全部回滚（相关工序实例回到「未定价」）。"
                : "有 " + skipped + " 行未回滚：它们的单价已被后续改动覆盖（不覆盖后续改动）。");
        log.info("未定价实例补价回滚: batch={}, reverted={}, skipped={}", batchId, reverted, skipped);
        return result;
    }

    /** 该加工单的活跃工序实例（与报工/读面同一口径：{@code deleted = 0} + 同租户）。 */
    private List<ProcessingPositionOperation> listInstances(String processingOrderId, Long tenantId) {
        List<ProcessingPositionOperation> rows = positionOperationMapper.selectList(
                new LambdaQueryWrapper<ProcessingPositionOperation>()
                        .eq(ProcessingPositionOperation::getTenantId, tenantId)
                        .eq(ProcessingPositionOperation::getProcessingOrderId, processingOrderId)
                        .eq(ProcessingPositionOperation::getDeleted, 0)
                        .orderByAsc(ProcessingPositionOperation::getSeq));
        return rows == null ? List.of() : rows;
    }

    /**
     * 当前**工序一口价**：{@code 逻辑工序} → 单价（**未定价的值为 {@code null}**，
     * 与实例化路径 {@code ProcessingOrderService.buildRoute} 读**同一份**收敛实现
     * {@link ProductionOperationQueryService#collapseToLogical}）。
     *
     * <p>去部位化（issue #4883）：键曾是 {@code (部位, 逻辑工序)}；价不再随部位变化
     * ⇒ 键塌缩为逻辑工序名（部位维退场 ⇒ 不再需要「不许猜部位」的那层保护）。</p>
     */
    private Map<String, BigDecimal> currentMatrixPrices(Long tenantId) {
        Map<String, BigDecimal> prices = new HashMap<>();
        for (ProductionOperationPosition row : ProductionOperationQueryService.collapseToLogical(
                productionOperationQueryService.operationPositions(tenantId))) {
            prices.put(row.getLogicalName(), row.getUnitPrice());
        }
        return prices;
    }

    /**
     * 实例行 → 价目键。{@code position_kind} 的**存在性**仍是前置（**不追溯**：V69 之前没有
     * {@code position_kind} 的存量行维持「仍未定价」，本批不扩大补价射程）；逻辑工序名按
     * **既有唯一映射**派生（{@link ProductionOperationQueryService#logicalOperationName}，
     * 不新造第二份表）。
     *
     * <p>去部位化（issue #4883）：键里**不再拼 {@code position_kind}** —— 价不再随部位变化
     * （{@link ProductionOperationQueryService#collapseToLogical} 收敛成一道工序一个价）
     * ⇒ 保留部位维只会让「同一道工序在两个部位各有一格」这件事继续存在，而那个概念已经退场。</p>
     */
    private static String cellKey(ProcessingPositionOperation op) {
        if (!StringUtils.hasText(op.getPositionKind()) || !StringUtils.hasText(op.getOperationName())) {
            return null;
        }
        return ProductionOperationQueryService.logicalOperationName(op.getOperationName());
    }

    /** 结果里的工序行（与计件报表的 {@code unpriced.operations} 同形：{@code operation} + {@code logical_name}）。 */
    private static Map<String, Object> operationRow(ProcessingPositionOperation op, BigDecimal price) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("operation", op.getOperationName());
        row.put("logical_name", ProductionOperationQueryService.logicalOperationName(op.getOperationName()));
        row.put("position", op.getPositionKind());
        row.put("unit_price", price);
        return row;
    }

    private Map<String, Object> emptyResult(String orderId, String hint) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("order_id", orderId);
        result.put("processing_order_id", null);
        result.put("batch_id", null);
        result.put("filled", 0);
        result.put("already_priced", 0);
        result.put("still_unpriced", 0);
        result.put("filled_operations", List.of());
        result.put("still_unpriced_operations", List.of());
        result.put("hint", hint);
        return result;
    }

    private Order resolveOrder(String key, Long tenantId) {
        Order order = orderMapper.selectById(key);
        if (order == null || !Objects.equals(order.getTenantId(), tenantId)
                || (order.getDeleted() != null && order.getDeleted() != 0)) {
            throw BusinessException.notFound("订单");
        }
        return order;
    }
}
