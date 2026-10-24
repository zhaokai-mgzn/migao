package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.mapper.CustomerProfileMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 价格解析服务（issue #7375，P1-3 段 1）：把三张价格本 + SKU 标准价喂给纯函数
 * {@link PriceResolution}，并**自述命中层级**（改价争议的第一份证据）。
 *
 * <p>⚠️ 本服务**只读**：不改订单、不落价格快照 —— 下单侧「服务端为准 + 差异留痕」是段 2（见 issue 判据 2），
 * 本段先把「该按哪个价」这件事变成可判定的服务端事实。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PriceService {

    private final ProductSkuMapper productSkuMapper;
    private final CustomerProfileMapper customerProfileMapper;
    private final JdbcTemplate jdbcTemplate;

    /**
     * 解析该客户买该 SKU、数量为 {@code quantity} 时的单价。
     *
     * @param customerId 客户（null ⇒ 没有协议价/等级价，走阶梯价或标准价）
     * @param skuId      SKU
     * @param quantity   数量（null ⇒ 阶梯价不参与）
     */
    public PriceResolution.Result resolvePrice(String customerId, Long skuId, BigDecimal quantity) {
        ProductSku sku = productSkuMapper.selectById(skuId);
        if (sku == null) {
            throw com.migao.admin.exception.BusinessException.notFound("SKU");
        }
        Long tenantId = sku.getTenantId();

        String vipLevel = null;
        if (customerId != null) {
            CustomerProfile customer = customerProfileMapper.selectById(customerId);
            if (customer != null) {
                vipLevel = customer.getVipLevel();
            }
        }

        BigDecimal protocolPrice = customerId == null ? null : queryDecimal(
                "SELECT price FROM customer_sku_prices WHERE tenant_id = ? AND customer_id = ?"
                        + " AND sku_id = ? AND deleted = 0",
                tenantId, customerId, skuId);
        BigDecimal vipLevelPrice = vipLevel == null ? null : queryDecimal(
                "SELECT price FROM vip_level_prices WHERE tenant_id = ? AND vip_level = ?"
                        + " AND sku_id = ? AND deleted = 0",
                tenantId, vipLevel, skuId);
        List<PriceResolution.Tier> tiers = queryTiers(tenantId, skuId);

        return PriceResolution.resolve(protocolPrice, vipLevelPrice, tiers, sku.getPrice(), quantity);
    }

    private BigDecimal queryDecimal(String sql, Object... args) {
        List<BigDecimal> rows = jdbcTemplate.query(sql,
                (rs, i) -> rs.getBigDecimal(1), args);
        return rows.isEmpty() ? null : rows.get(0);
    }

    private List<PriceResolution.Tier> queryTiers(Long tenantId, Long skuId) {
        List<Map<String, Object>> rows = jdbcTemplate.queryForList(
                "SELECT min_qty, max_qty, price FROM sku_tier_prices"
                        + " WHERE tenant_id = ? AND sku_id = ? AND deleted = 0 ORDER BY min_qty",
                tenantId, skuId);
        List<PriceResolution.Tier> tiers = new ArrayList<>();
        for (Map<String, Object> row : rows) {
            tiers.add(new PriceResolution.Tier(
                    (BigDecimal) row.get("min_qty"),
                    (BigDecimal) row.get("max_qty"),
                    (BigDecimal) row.get("price")));
        }
        return tiers;
    }
}
