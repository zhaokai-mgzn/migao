package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionOperationPosition;
import org.apache.ibatis.annotations.Mapper;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 部位价目 + 适用性矩阵（V71 / V72，issue #4427 + #4432）
 * 对应表：{@code production_operation_positions}。
 */
@Mapper
public interface ProductionOperationPositionMapper extends BaseMapper<ProductionOperationPosition> {

    /**
     * 只写矩阵格的**两列可写面**（{@code unit_price} / {@code applicable}）+ {@code updated_at}
     * （issue #4587 ②）。
     *
     * <p><b>为什么用 {@code LambdaUpdateWrapper} 而不是实体 {@code updateById}</b>：
     * ① {@code updateById} 会把整行按实体回写（漏设字段即写成 null）；② 更关键的是
     * <b>MyBatis-Plus 的 NOT_NULL 策略会把 null 字段从 UPDATE 里省掉</b> ⇒
     * 「把价改回<b>未定价</b>（NULL）」与「明确不做 ⇒ 价强制清空」这两条语义<b>根本写不进去</b>
     * （静默保留旧价 = 商家以为改回未定价、实际照旧计价 ⇒ 工人工资错）。本方法**显式** SET 两列。</p>
     *
     * @param unitPrice  {@code null} = 未定价 / 明确不做（**≠ 0 元**）
     * @param applicable 该部位是否做这道工序
     * @return 受影响行数（0 = 行不存在 / 非本租户 / 已软删）
     */
    default int updatePriceAndApplicable(String id, Long tenantId, BigDecimal unitPrice,
                                         Boolean applicable, OffsetDateTime updatedAt) {
        return update(null, new LambdaUpdateWrapper<ProductionOperationPosition>()
                .eq(ProductionOperationPosition::getId, id)
                .eq(ProductionOperationPosition::getTenantId, tenantId)
                .eq(ProductionOperationPosition::getDeleted, 0)
                .set(ProductionOperationPosition::getUnitPrice, unitPrice)
                .set(ProductionOperationPosition::getApplicable, applicable)
                .set(ProductionOperationPosition::getUpdatedAt, updatedAt));
    }
}
