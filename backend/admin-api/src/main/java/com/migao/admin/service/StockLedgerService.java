package com.migao.admin.service;

import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.entity.StockLedger;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.StockLedgerMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import com.migao.admin.security.SecurityUser;

import java.time.OffsetDateTime;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 库存流水/台账服务（issue #4055）。
 *
 * <p>职责：① 记录 SKU 级库存变更（一行 = 一次变更，before/after 首尾相接可对账）；
 * ② 只读查询（按 sku_id / product_id / ref_no 过滤，租户隔离）。</p>
 *
 * <p>写入方挂在**库存变更的既有实现点**（不新造扣减逻辑）：</p>
 * <ul>
 *   <li>{@code ProductService.adjustStockForAgent} —— 手工调整，逐 SKU 直接调 {@link #record}；</li>
 *   <li>{@code AfterSalesTicketService.maybeRestockOnReturn} —— 回补发生在
 *       {@code OrderService.restoreStockForReturn} 内部（本批不动该文件），故用
 *       {@link #snapshotSkus} + {@link #recordChangesAgainstSnapshot} 按「回补前快照 vs 回补后实际值」
 *       比对落账，只记真实变化的 SKU。</li>
 * </ul>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class StockLedgerService extends ServiceImpl<StockLedgerMapper, StockLedger> {

    /** 无认证上下文（定时任务 / 单元测试 / 内部调用）时的操作人占位 */
    static final String OPERATOR_SYSTEM = "system";

    private final StockLedgerMapper stockLedgerMapper;
    private final ProductSkuMapper productSkuMapper;

    /**
     * 记录一次 SKU 库存变更（追加写）。
     *
     * <p>{@code delta} 由本方法按 after-before 计算 —— 不接收调用方传入的 delta，
     * 从根上排除「delta 与 before/after 三者不自洽」的脏行（对账不变式的一半）。</p>
     *
     * @param beforeQty 变更前库存（由调用方在写库前取到）
     * @param afterQty  变更后库存
     * @param reason    变更来源，取值见 {@link StockLedger#REASON_MANUAL} 等
     * @param refNo     业务单据号（订单号/工单号），手工调整传 null
     * @param note      人类可读原因（可空）
     */
    public void record(Long tenantId, String productId, Long skuId, String skuCode,
                       int beforeQty, int afterQty, String reason, String refNo, String note) {
        StockLedger entry = StockLedger.builder()
                .tenantId(tenantId)
                .productId(productId)
                .skuId(skuId)
                .skuCode(skuCode)
                .delta(afterQty - beforeQty)
                .beforeQty(beforeQty)
                .afterQty(afterQty)
                .reason(reason)
                .refNo(refNo)
                .note(note)
                .operator(resolveOperator())
                .createdAt(OffsetDateTime.now())
                .build();
        stockLedgerMapper.insert(entry);
        log.info("库存流水: tenant={}, product={}, skuId={}, skuCode={}, {}->{}(delta={}), reason={}, refNo={}, operator={}",
                tenantId, productId, skuId, skuCode, beforeQty, afterQty, afterQty - beforeQty,
                reason, refNo, entry.getOperator());
    }

    /**
     * 快照一组商品当前各 SKU（skuId → 读取时的实体）。
     *
     * <p>给「库存变更发生在别处、但变更点在本服务可触及范围内」的既有实现点用：
     * 调用方在触发变更**之前**取快照，变更**之后**调 {@link #recordChangesAgainstSnapshot}。</p>
     */
    public Map<Long, ProductSku> snapshotSkus(Collection<String> productIds) {
        if (productIds == null || productIds.isEmpty()) {
            return Map.of();
        }
        List<ProductSku> skus = productSkuMapper.selectList(
                new LambdaQueryWrapper<ProductSku>().in(ProductSku::getProductId, productIds));
        Map<Long, ProductSku> snapshot = new LinkedHashMap<>();
        for (ProductSku sku : skus) {
            snapshot.put(sku.getId(), sku);
        }
        return snapshot;
    }

    /**
     * 与快照比对后落账：只写**实际发生变化**的 SKU（无变化的 SKU 不落行，台账里不出现 0 变更噪声）。
     *
     * @param before {@link #snapshotSkus} 在变更前取到的快照
     * @return 落账行数（0 = 一个 SKU 都没变）
     */
    @Transactional(rollbackFor = Exception.class)
    public int recordChangesAgainstSnapshot(Long tenantId, Map<Long, ProductSku> before,
                                           String reason, String refNo, String note) {
        if (before == null || before.isEmpty()) {
            return 0;
        }
        List<ProductSku> now = productSkuMapper.selectList(
                new LambdaQueryWrapper<ProductSku>().in(ProductSku::getId, before.keySet()));
        int rows = 0;
        for (ProductSku current : now) {
            ProductSku previous = before.get(current.getId());
            if (previous == null) {
                // 快照外的 SKU（不在本次变更范围）不落账 —— 否则会以 before=0 造出假变化
                continue;
            }
            int beforeQty = stockOf(previous);
            int afterQty = stockOf(current);
            if (beforeQty == afterQty) {
                continue;
            }
            record(tenantId, current.getProductId(), current.getId(), current.getSkuCode(),
                    beforeQty, afterQty, reason, refNo, note);
            rows++;
        }
        return rows;
    }

    /**
     * 只读查询：按 sku_id / product_id / ref_no 过滤，按 id 倒序（最新在前）。
     *
     * <p>**全部条件都限定 tenant_id**（跨租户读 = 数据泄漏，不是分页问题）。</p>
     */
    public PageResponse<StockLedger> getLedgerPage(Long tenantId, Long skuId, String productId,
                                                   String refNo, long page, long size) {
        LambdaQueryWrapper<StockLedger> wrapper = new LambdaQueryWrapper<StockLedger>()
                .eq(StockLedger::getTenantId, tenantId)
                .eq(skuId != null, StockLedger::getSkuId, skuId)
                .eq(StringUtils.hasText(productId), StockLedger::getProductId, productId)
                .eq(StringUtils.hasText(refNo), StockLedger::getRefNo, refNo)
                .orderByDesc(StockLedger::getId);
        Page<StockLedger> result = stockLedgerMapper.selectPage(new Page<>(page, size), wrapper);
        return PageResponse.of(result);
    }

    /**
     * 操作人：登录用户名（手机号）→ 内部服务身份（ServiceTokenFilter 的 internal-service）
     * → system（无认证上下文：定时任务 / 单元测试）。
     */
    private static String resolveOperator() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth != null && auth.getPrincipal() instanceof SecurityUser securityUser) {
            return StringUtils.hasText(securityUser.getUsername())
                    ? securityUser.getUsername() : securityUser.getUserId();
        }
        return OPERATOR_SYSTEM;
    }

    private static int stockOf(ProductSku sku) {
        return sku != null && sku.getStock() != null ? sku.getStock() : 0;
    }
}