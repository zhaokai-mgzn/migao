package com.migao.admin.waybill;

import com.migao.admin.entity.TenantLogisticsConfig;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.TenantLogisticsConfigMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.OffsetDateTime;

/**
 * 物流取号的**租户级配置**读写（issue #8698；口径 §3-5「没配 = 全 manual，配了才走它」）。
 *
 * <p>三条口径：</p>
 * <ol>
 *   <li><b>缺行 ⇒ 全 manual</b>：不播种、不编默认承运商（{@code configuredCarrierCode} 返回 {@code null}）；</li>
 *   <li><b>只存选择，不存凭据</b>：P0 没有任何第三方凭据；P1 的凭据面口径见
 *       {@code docs/logistics-waybill-api-research.md} §3-4（只进服务端、按租户存、
 *       前端产物不得出现）；</li>
 *   <li><b>写面白名单 = 注册表</b>：只接受登记过的 code 或 {@code manual}（写一个不存在的
 *       code 会让「配了却永远手动」变成一个没有任何东西会报的静默失败）。</li>
 * </ol>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class TenantLogisticsConfigService {

    private final TenantLogisticsConfigMapper mapper;
    private final CarrierRegistry registry;

    /** 本租户配置的承运商 code；**没配 ⇒ {@code null}**（= 全 manual，不返回默认值）。 */
    public String configuredCarrierCode(Long tenantId) {
        TenantLogisticsConfig row = mapper.selectActiveByTenant(tenantId);
        if (row == null) {
            return null;
        }
        String code = row.getCarrierCode();
        return code == null || code.isBlank() ? null : code.trim();
    }

    /**
     * 写本租户承运商（upsert；{@code null/空} ⇒ 清空 = 回到全 manual）。
     *
     * @return 写后的承运商 code（{@code null} = 全 manual）
     */
    public String put(Long tenantId, String carrierCode) {
        String normalized = carrierCode == null || carrierCode.isBlank() ? null : carrierCode.trim();
        if (normalized != null && !registry.isKnown(normalized)) {
            throw BusinessException.validationError(
                    "未知承运商：" + normalized + "（可选：" + registry.carriers().size() + " 家已登记承运商或 manual）");
        }
        TenantLogisticsConfig existing = mapper.selectActiveByTenant(tenantId);
        OffsetDateTime now = OffsetDateTime.now();
        if (existing == null) {
            mapper.insert(TenantLogisticsConfig.builder()
                    .tenantId(tenantId)
                    .carrierCode(normalized)
                    .createdAt(now)
                    .updatedAt(now)
                    .deleted(0)
                    .build());
        } else {
            existing.setCarrierCode(normalized);
            existing.setUpdatedAt(now);
            mapper.updateById(existing);
        }
        log.info("物流取号承运商配置已更新: tenantId={}, carrierCode={}", tenantId, normalized);
        return normalized;
    }
}
