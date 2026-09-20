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
     * 只写矩阵格的**一列可写面**（{@code unit_price}）+ {@code updated_at}
     * （issue #4937 / O1：{@code applicable} 已退场 ⇒ 写面不再写它）。
     *
     * <p><b>为什么用 {@code LambdaUpdateWrapper} 而不是实体 {@code updateById}</b>：
     * ① {@code updateById} 会把整行按实体回写（漏设字段即写成 null）；② 更关键的是
     * <b>MyBatis-Plus 的 NOT_NULL 策略会把 null 字段从 UPDATE 里省掉</b> ⇒
     * 「把价改回<b>未定价</b>（NULL）」这条语义<b>根本写不进去</b>
     * （静默保留旧价 = 商家以为改回未定价、实际照旧计价 ⇒ 工人工资错）。本方法**显式** SET 两列。</p>
     *
     * @param unitPrice {@code null} = 未定价（**≠ 0 元**）
     * @return 受影响行数（0 = 行不存在 / 非本租户 / 已软删）
     */
    default int updateUnitPrice(String id, Long tenantId, BigDecimal unitPrice,
                                OffsetDateTime updatedAt) {
        return update(null, new LambdaUpdateWrapper<ProductionOperationPosition>()
                .eq(ProductionOperationPosition::getId, id)
                .eq(ProductionOperationPosition::getTenantId, tenantId)
                .eq(ProductionOperationPosition::getDeleted, 0)
                .set(ProductionOperationPosition::getUnitPrice, unitPrice)
                .set(ProductionOperationPosition::getUpdatedAt, updatedAt));
    }

    /**
     * 「**设为不做**」形态（{@code applicable = false} + 价强制清空）—— 只被**删工序**
     * 那条路径用（{@code ProductionOperationCommandService#deleteDetaching} 的「一键摘格」，
     * issue #4665 A）。
     *
     * <p>⚠️ <b>与 {@link #updateUnitPrice} 并存是**有意**的</b>（issue #4937 / O1）：
     * 商家配置面的 {@code applicable} 已退场（{@code PUT /operation-positions/{id}} 收到该字段
     * **422**），但**删工序**那条路径仍需把命中的格标成「不做」以便护栏③放行
     * —— 这是**内部一致性动作**，不是商家配置入口。⛔ 不得据此重新开放商家改 {@code applicable} 的入口。</p>
     *
     * @param unitPrice  {@code null} = 明确不做 ⇒ 不报价（**≠ 0 元**）
     * @param applicable 该部位是否做这道工序（本路径恒 {@code false}）
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

    /**
     * **软删**矩阵行（issue #4665 C：删工序要「删干净」）。
     *
     * <p><b>为什么必须有这个方法</b>：工序被软删后矩阵行若还在，{@code GET /operation-positions}
     * 照旧返回它（读面过滤只有租户 + {@code deleted=0} + {@code status='active'}，**不看它挂的
     * 那道工序是否已删**）⇒ 工艺项表格里那一行**照旧显示** ⇒ 用户实测「依然删不干净」。
     * 删工序必须在**同一事务**里把这些矩阵行也软删。</p>
     *
     * <p><b>为什么显式写列</b>（#4608 的 P0 教训，本仓既有守卫）：MyBatis-Plus 全局逻辑删除会把
     * 逻辑删除字段从 {@code updateById} 的 SET 子句里**剔除** ⇒ {@code setDeleted(1); updateById(...)}
     * 永不落库，而调用仍返回成功 = **静默 no-op**。这里显式 {@code set(deleted, 1)} 绕过字段剔除，
     * 同时保住审计字段 {@code updated_at}（「谁在什么时候删的」的唯一证据）。</p>
     *
     * @return 受影响行数（0 = 行不存在 / 非本租户 / 已软删 ⇒ 调用方 fail-closed 回滚）
     */
    default int softDelete(String id, Long tenantId, OffsetDateTime updatedAt) {
        return update(null, new LambdaUpdateWrapper<ProductionOperationPosition>()
                .eq(ProductionOperationPosition::getId, id)
                .eq(ProductionOperationPosition::getTenantId, tenantId)
                .eq(ProductionOperationPosition::getDeleted, 0)
                .set(ProductionOperationPosition::getDeleted, 1)
                .set(ProductionOperationPosition::getUpdatedAt, updatedAt));
    }
}
