package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionInstanceRepricingLog;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

/**
 * 未定价实例补价动作账 Mapper（V94，issue #4709 C）。
 *
 * <p>只有两件事：插入账行（{@link BaseMapper#insert}）与**按批回滚留痕**
 * （{@link #markRolledBack}）。回滚对实例行的还原走
 * {@link ProcessingPositionOperationMapper#revertFilledUnitPrice} 的 CAS 谓词 —— 两处**同一批次**，
 * 故调用方必须在同一事务里先还原实例行、再留痕（顺序反了会在「还原 0 行」时留下假回滚记录）。</p>
 */
@Mapper
public interface ProductionInstanceRepricingLogMapper extends BaseMapper<ProductionInstanceRepricingLog> {

    /**
     * 把**单个**账行标记为已回滚（{@code rolled_back_at = 现在}）。
     *
     * <p>按**行**而不是按批：回滚时若某行的实例值已被后续改动覆盖（CAS 影响 0 行），
     * 该账行**不得**被标记 —— 按批一把标会把「没还原的行」谎报成已回滚。
     * 谓词含 {@code rolled_back_at IS NULL} ⇒ 重复回滚是**幂等空操作**
     * （第二次影响 0 行，不刷新时间戳、不制造第二次「已回滚」记录）。</p>
     *
     * @return 1 = 本次标记成功；0 = 该账行不存在 / 跨租户 / 已回滚过
     */
    @Update("UPDATE production_instance_repricing_logs SET rolled_back_at = #{rolledBackAt} "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0 "
            + "AND rolled_back_at IS NULL")
    int markRolledBack(@Param("id") String id,
                       @Param("tenantId") Long tenantId,
                       @Param("rolledBackAt") java.time.OffsetDateTime rolledBackAt);
}
