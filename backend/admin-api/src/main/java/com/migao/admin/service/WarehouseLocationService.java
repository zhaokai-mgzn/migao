package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.WarehouseLocation;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.WarehouseLocationMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Locale;

/**
 * 仓位（V196，issue #7750）—— 成品仓的货位分配。
 *
 * <h3>分配口径（一句话：区域 A 内最小空闲号）</h3>
 * <p>先复用**已释放**的仓位（发货/撤销打包后释放），都占满才按序号新增
 * （{@code A-01}、{@code A-02}…）—— 不按「总数取最大」也不按「随机」：
 * 前者会一进一出就涨号、仓位上永远只增不减；后者让仓管没法按号找货。</p>
 *
 * <h3>并发（为什么「找空闲」和「占位」是两步）</h3>
 * <p>「找空闲」只是**推荐**：两个打包请求可能同时算出同一个空闲号。真正的互斥在
 * {@code finished_goods_stock} 的局部唯一索引（{@code (tenant_id, bin_code) WHERE status='in_stock'}）——
 * 插入由 {@code FinishedGoodsStockMapper#claimInStock} 的 {@code ON CONFLICT DO NOTHING} 原子完成，
 * 抢不到（返回 {@code null}）就回来换下一个空闲号。**本类不做占位**，只给候选。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class WarehouseLocationService {

    /** 成品仓默认区域（新号段在这里顺延）。 */
    public static final String DEFAULT_ZONE_CODE = "A";
    /** 默认区域名称（展示用）。 */
    public static final String DEFAULT_ZONE_NAME = "成品区";

    /** 找候选仓位的尝试上限（每次「找 → 占」失败都换下一个候选；正常 1 次内命中）。 */
    private static final int ALLOCATE_ATTEMPTS = 8;

    private final WarehouseLocationMapper locationMapper;

    /** 仓位清单（按仓位号排序；成品库存页/仓位选择用）。 */
    public List<WarehouseLocation> list(Long tenantId, Long warehouseId) {
        return locationMapper.selectList(new LambdaQueryWrapper<WarehouseLocation>()
                .eq(WarehouseLocation::getTenantId, tenantId)
                .eq(warehouseId != null, WarehouseLocation::getWarehouseId, warehouseId)
                .eq(WarehouseLocation::getStatus, "active")
                .orderByAsc(WarehouseLocation::getBinCode));
    }

    /**
     * 取一个**候选**空闲仓位（已存在的最小空闲号；全占满 ⇒ 建下一个号并返回）。
     *
     * <p>「空闲」= 没有任何 {@code in_stock} 成品占着它（由 {@code WarehouseLocationMapper} 的
     * {@code NOT EXISTS} 判定）—— 仓位表上**没有**单独的「占用」列：那会是第二份真相，
     * 发货/撤销漏改一次就永久占位。</p>
     */
    public WarehouseLocation nextFreeBin(Long tenantId, Long warehouseId) {
        for (int attempt = 0; attempt < ALLOCATE_ATTEMPTS; attempt++) {
            WarehouseLocation free = locationMapper.selectFirstFreeBin(tenantId, warehouseId);
            if (free != null) {
                return free;
            }
            int next = locationMapper.countBinsInZone(tenantId, warehouseId, DEFAULT_ZONE_CODE) + 1;
            String code = String.format(Locale.ROOT, "%s-%02d", DEFAULT_ZONE_CODE, next);
            // 原子占号：同号已存在 ⇒ 0 行（不抛异常，事务仍可用），下一轮重算
            locationMapper.claimBin(tenantId, warehouseId, DEFAULT_ZONE_CODE, DEFAULT_ZONE_NAME, code);
            WarehouseLocation created = locationMapper.selectByBinCode(tenantId, code);
            if (created != null) {
                return created;
            }
        }
        throw BusinessException.conflict("成品仓位分配失败（连续 " + ALLOCATE_ATTEMPTS + " 次占号冲突）",
                "请重试；重复提交不会让同一个仓位放两件成品");
    }
}
