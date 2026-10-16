package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.PieceworkSettlement;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

import java.time.OffsetDateTime;

/**
 * 计件结算单 Mapper（V156，issue #5653）。
 *
 * <p>三件事：<b>原子生成</b>（{@link #insertActiveIfAbsent}）、{@link BaseMapper 只读查询}、
 * <b>作废留痕</b>（{@link #voidActive}）。⚠️ 本接口**没有**任何 UPDATE 金额 / 期间 / 工人的方法
 * —— 「生成即冻结」在**结构上**成立（改得动的路径不存在），不是靠前端不给按钮。</p>
 */
@Mapper
public interface PieceworkSettlementMapper extends BaseMapper<PieceworkSettlement> {

    /**
     * 生成**活跃**结算单（{@code ON CONFLICT DO NOTHING} 原子闸）。
     *
     * <p><b>为什么不能「先查后插」</b>：那是非原子读（TOCTOU）—— 两个并发请求同时判定「还没有」
     * 后争抢部分唯一索引 {@code uk_piecework_settlements_active} ⇒ 后到的那个把
     * {@code DuplicateKeyException} 冒泡成 **HTTP 500**（同族实证见 {@code #6301} 的探针读数
     * {@code [200,500,500,500,500,500]}）。冲突在语句内部消解后，调用方按返回值给**具名 409**。</p>
     *
     * <p>⚠️ {@code ON CONFLICT} 目标**必须带索引谓词**（部分唯一索引；PG 冲突推断要求谓词匹配
     * —— 与 {@code StockBatchConsumptionMapper.insertStocktakeIfAbsent} /
     * {@code ProcessingSetPartTokenMapper.insertIgnoreConflict} 本地 PG 实测同款）。</p>
     *
     * @return 1 = 本次真的落了这一行；0 = 同租户 × 期间 × 工人**已有活跃单**（并发败者 / 重复生成）
     */
    @Insert("INSERT INTO piecework_settlements (id, tenant_id, period, worker_name, total_amount, "
            + "line_items, generated_by, generated_at, created_at, updated_at, deleted) "
            + "VALUES (#{row.id}, #{row.tenantId}, #{row.period}, #{row.workerName}, #{row.totalAmount}, "
            + "CAST(#{lineItemsJson} AS jsonb), #{row.generatedBy}, #{row.generatedAt}, "
            + "#{row.createdAt}, #{row.updatedAt}, 0) "
            + "ON CONFLICT (tenant_id, period, worker_name) WHERE voided_at IS NULL AND deleted = 0 "
            + "DO NOTHING")
    int insertActiveIfAbsent(@Param("row") PieceworkSettlement row,
                             @Param("lineItemsJson") String lineItemsJson);

    /**
     * 作废一张**活跃**单（{@code voided_at IS NULL} 的 CAS 谓词 ⇒ 重复作废是幂等空操作）。
     *
     * <p>本方法**只**改 {@code voided_at} / {@code voided_by} / {@code void_reason} / {@code updated_at}
     * —— 金额、期间、工人、明细快照**不在 SET 子句里**（「作废 ≠ 改写」由 SQL 文本机械保证）。</p>
     *
     * @return 1 = 本次作废成功；0 = 该单不存在 / 跨租户 / 已作废过
     */
    @Update("UPDATE piecework_settlements SET voided_at = #{voidedAt}, voided_by = #{voidedBy}, "
            + "void_reason = #{voidReason}, updated_at = #{voidedAt} "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0 AND voided_at IS NULL")
    int voidActive(@Param("id") String id,
                   @Param("tenantId") Long tenantId,
                   @Param("voidedBy") String voidedBy,
                   @Param("voidReason") String voidReason,
                   @Param("voidedAt") OffsetDateTime voidedAt);
}
