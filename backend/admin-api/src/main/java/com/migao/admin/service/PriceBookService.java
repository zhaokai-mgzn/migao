package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.PriceBookView;
import com.migao.admin.exception.BusinessException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 价格本录入与读面（issue #7375，P1-3 段 3）—— 让「协议价 / 等级价 / 阶梯价」**可被运营维护**。
 *
 * <h3>为什么需要它</h3>
 * <p>段 1 立了三张价格本 + 解析链，段 2 让下单按它定价，但**没有任何录入入口** —— 只能直接写库。
 * 一个只有工程师能维护的价格体系，等于没有。</p>
 *
 * <h3>三条纪律</h3>
 * <ol>
 *   <li><b>价格必须是正数</b>：0 或负数一律拒（0 元成交 = 白送；这是段 1 就定下的口径）；</li>
 *   <li><b>upsert 靠唯一索引</b>：同一客户同 SKU / 同等级同 SKU / 同 SKU 同门槛只留一条生效价
 *       （部分唯一索引兜住，冲突映射成可读 409，不靠服务层查一遍）；</li>
 *   <li><b>金额精度过闸</b>：落库前过 {@code MoneyScale}（两位小数，超精度直接拒）。</li>
 * </ol>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PriceBookService {

    private final JdbcTemplate jdbcTemplate;

    /**
     * 改价闸门（issue #7375 段 4）：低于成本必须先有已通过的 `price_change` 审批。
     * 可空注入 ⇒ 切片上下文/老单测退回「无闸门」= 改前行为，不静默放宽（那需要显式给 bean）。
     */
    @org.springframework.beans.factory.annotation.Autowired(required = false)
    private com.migao.admin.mapper.ProductSkuMapper productSkuMapper;

    @org.springframework.beans.factory.annotation.Autowired(required = false)
    private ApprovalService approvalService;

    /** 价格本读面：按 SKU（可选客户）一次性给出三层价格，供页面渲染「这个 SKU 现在有几档价」。 */
    public PriceBookView list(Long tenantId, Long skuId, String customerId) {
        PriceBookView view = new PriceBookView();
        view.setSkuId(skuId);
        view.setCustomerId(customerId);
        if (skuId == null) {
            throw BusinessException.validationError("必须指定 skuId（价格本是按 SKU 维护的）");
        }
        // 🔴 展示名与标识分离（issue #7623 / 研发模式 §31 P3）：协议价的行要能读出「这是给谁定的价」，
        // 而客户 id 是内部编号（雪花号 / 64 位串）—— 必须由**服务端**给展示名，前端不拿 id 切字符串、
        // 也不回查第二份口径。兜底两级：档案里的微信昵称 → 手机号 → 「未命名客户」；
        // 客户档案已不存在（join 不到）⇒「客户已移除」，绝不把 id 当名字印上屏。
        view.setProtocol(jdbcTemplate.queryForList(
                "SELECT p.id::text AS id, p.customer_id, p.price,"
                        + " CASE WHEN c.id IS NULL THEN '客户已移除'"
                        + " ELSE COALESCE(NULLIF(c.wechat_nickname, ''), NULLIF(c.phone, ''), '未命名客户')"
                        + " END AS customer_name"
                        + " FROM customer_sku_prices p"
                        + " LEFT JOIN customer_profiles c ON c.id = p.customer_id AND c.tenant_id = p.tenant_id"
                        + " WHERE p.tenant_id = ? AND p.sku_id = ? AND p.deleted = 0"
                        + (customerId == null ? "" : " AND p.customer_id = ?")
                        + " ORDER BY customer_name, p.customer_id",
                customerId == null
                        ? new Object[]{tenantId, skuId}
                        : new Object[]{tenantId, skuId, customerId}).stream()
                .map(PriceBookService::normalize).toList());
        view.setVipLevels(jdbcTemplate.queryForList(
                "SELECT id::text AS id, vip_level, price FROM vip_level_prices"
                        + " WHERE tenant_id = ? AND sku_id = ? AND deleted = 0 ORDER BY vip_level",
                tenantId, skuId).stream().map(PriceBookService::normalize).toList());
        view.setTiers(jdbcTemplate.queryForList(
                "SELECT id::text AS id, min_qty, max_qty, price FROM sku_tier_prices"
                        + " WHERE tenant_id = ? AND sku_id = ? AND deleted = 0 ORDER BY min_qty",
                tenantId, skuId).stream().map(PriceBookService::normalize).toList());
        return view;
    }

    /** 协议价 upsert（客户 × SKU）。 */
    @Transactional
    public void upsertProtocol(Long tenantId, String customerId, Long skuId, BigDecimal price, String note) {
        requirePrice(price);
        requireText(customerId, "客户");
        requireSku(skuId);
        assertPriceFloorAllows(skuId, price, "协议价");
        jdbcTemplate.update(
                "INSERT INTO customer_sku_prices (tenant_id, customer_id, sku_id, price, note)"
                        + " VALUES (?, ?, ?, ?, ?)"
                        + " ON CONFLICT (tenant_id, customer_id, sku_id) WHERE deleted = 0"
                        + " DO UPDATE SET price = EXCLUDED.price, note = EXCLUDED.note,"
                        + " updated_at = NOW()",
                tenantId, customerId.trim(), skuId, money(price), note);
        log.info("[price-book] 协议价 | tenant={} customer={} sku={} price={}", tenantId, customerId, skuId, price);
    }

    /** 等级价 upsert（VIP 等级 × SKU）。 */
    @Transactional
    public void upsertVipLevel(Long tenantId, String vipLevel, Long skuId, BigDecimal price) {
        requirePrice(price);
        requireText(vipLevel, "客户等级");
        requireSku(skuId);
        assertPriceFloorAllows(skuId, price, "等级价");
        jdbcTemplate.update(
                "INSERT INTO vip_level_prices (tenant_id, vip_level, sku_id, price) VALUES (?, ?, ?, ?)"
                        + " ON CONFLICT (tenant_id, vip_level, sku_id) WHERE deleted = 0"
                        + " DO UPDATE SET price = EXCLUDED.price, updated_at = NOW()",
                tenantId, vipLevel.trim(), skuId, money(price));
        log.info("[price-book] 等级价 | tenant={} level={} sku={} price={}", tenantId, vipLevel, skuId, price);
    }

    /** 阶梯价 upsert（SKU + 门槛）。 */
    @Transactional
    public void upsertTier(Long tenantId, Long skuId, BigDecimal minQty, BigDecimal maxQty, BigDecimal price) {
        requirePrice(price);
        requireSku(skuId);
        if (minQty == null || minQty.signum() <= 0) {
            throw BusinessException.validationError("阶梯的起订量必须大于 0");
        }
        if (maxQty != null && maxQty.compareTo(minQty) < 0) {
            throw BusinessException.validationError("阶梯的上限不能小于起订量");
        }
        assertPriceFloorAllows(skuId, price, "阶梯价");
        jdbcTemplate.update(
                "INSERT INTO sku_tier_prices (tenant_id, sku_id, min_qty, max_qty, price) VALUES (?, ?, ?, ?, ?)"
                        + " ON CONFLICT (tenant_id, sku_id, min_qty) WHERE deleted = 0"
                        + " DO UPDATE SET max_qty = EXCLUDED.max_qty, price = EXCLUDED.price, updated_at = NOW()",
                tenantId, skuId, minQty, maxQty, money(price));
        log.info("[price-book] 阶梯价 | tenant={} sku={} min={} max={} price={}",
                tenantId, skuId, minQty, maxQty, price);
    }

    /** 软删一条价格本记录（`kind` 决定表；各表的 id 类型不同 ⇒ 分别处理）。 */
    @Transactional
    public void remove(Long tenantId, String kind, String id) {
        String table = switch (kind == null ? "" : kind) {
            case "protocol" -> "customer_sku_prices";
            case "vip-level" -> "vip_level_prices";
            case "tier" -> "sku_tier_prices";
            default -> throw BusinessException.validationError(
                    "价格本类型必须是 protocol / vip-level / tier 之一");
        };
        int updated = jdbcTemplate.update(
                "UPDATE " + table + " SET deleted = 1, updated_at = NOW()"
                        + " WHERE tenant_id = ? AND id = ? AND deleted = 0", tenantId, id);
        if (updated == 0) {
            throw BusinessException.notFound("价格本记录");
        }
    }

    /**
     * 改价闸门（issue #7375 段 4）：价低于该 SKU 成本 ⇒ 必须有一条**已通过且未用掉**的
     * `price_change` 审批（对象 = SKU id，金额 = 成本价），否则写面直接拒。
     *
     * <p>成本未知 ⇒ 放行（见 {@link PriceFloorPolicy} 的取舍），但日志里标明「这次无底价可依」。</p>
     */
    private void assertPriceFloorAllows(Long skuId, BigDecimal price, String label) {
        if (productSkuMapper == null) {
            return;   // 无成本读数 ⇒ 退回改前行为（不静默造一道假闸门）
        }
        com.migao.admin.entity.ProductSku sku = productSkuMapper.selectById(skuId);
        PriceFloorPolicy.Decision decision = PriceFloorPolicy.evaluate(price,
                sku == null ? null : sku.getAvgCost());
        if (!decision.needsApproval()) {
            if (decision.costUnknown()) {
                log.info("[price-book] {} 成本未知 ⇒ 不阻断，但也无底价可依 | sku={} price={}", label, skuId, price);
            }
            return;
        }
        String consumed = approvalService == null ? null
                : approvalService.consume(com.migao.admin.entity.Approval.TYPE_PRICE_CHANGE,
                        String.valueOf(skuId), sku.getAvgCost(), "sku:" + skuId);
        if (consumed == null) {
            throw BusinessException.validationError(String.format(
                    "%s ¥%s 低于该 SKU 成本 ¥%s（差 ¥%s），必须先有已通过的「改价」审批："
                            + "objectType=price_change，objectRef=%s，金额 ≥ 成本价",
                    label, price.toPlainString(), sku.getAvgCost().toPlainString(),
                    decision.shortfall().toPlainString(), skuId));
        }
        log.info("[price-book] {} 低于成本经审批放行 | sku={} price={} cost={} approval={}",
                label, skuId, price, sku.getAvgCost(), consumed);
    }

    private static Map<String, Object> normalize(Map<String, Object> row) {
        Map<String, Object> out = new LinkedHashMap<>();
        row.forEach((k, v) -> out.put(k, v instanceof BigDecimal decimal ? decimal.stripTrailingZeros() : v));
        return out;
    }

    private static void requirePrice(BigDecimal price) {
        if (price == null) {
            throw BusinessException.validationError("价格不能为空");
        }
        if (price.signum() <= 0) {
            throw BusinessException.validationError("价格必须大于 0（0 元 = 白送；未定价就不录）");
        }
    }

    private static void requireText(String value, String label) {
        if (value == null || value.isBlank()) {
            throw BusinessException.validationError(label + "不能为空");
        }
    }

    private static void requireSku(Long skuId) {
        if (skuId == null) {
            throw BusinessException.validationError("必须指定 SKU");
        }
    }

    /** 金额精度准入（#6228）：两位小数，超精度直接拒（不静默四舍五入）。 */
    private static BigDecimal money(BigDecimal price) {
        return MoneyScale.requireTwoDecimalsOrNull(price, "价格");
    }

    /** 读面里的三层价格（页面按需渲染，缺层就是没有该层价）。 */
    public record Snapshot(List<Map<String, Object>> protocol,
                           List<Map<String, Object>> vipLevels,
                           List<Map<String, Object>> tiers) {
    }

    /** 供测试/读面复用的空值包装（避免调用方各自判 null）。 */
    static List<Map<String, Object>> emptyIfNull(List<Map<String, Object>> rows) {
        return rows == null ? new ArrayList<>() : rows;
    }
}
