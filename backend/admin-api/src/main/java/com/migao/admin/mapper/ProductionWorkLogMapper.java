package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionWorkLog;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/**
 * 报工记录 Mapper（V49，issue #3995）：报工三态 + 计件明细
 */
@Mapper
public interface ProductionWorkLogMapper extends BaseMapper<ProductionWorkLog> {

    /**
     * 该工人是否在这张加工单上**做过打包工序**（V197 / issue #7762 的授权判据）。
     *
     * <p>用户口径：「只有关联打包工序的工人扫码后才能操作出库」。判据取**既有报工记录**
     * （{@code production_work_logs.operation_name ILIKE '%打包%'}），不新造岗位/权限码 ——
     * 车间里「谁打了包」本来就只在报工里有痕迹。</p>
     */
    @com.baomidou.mybatisplus.annotation.InterceptorIgnore(tenantLine = "true")
    @Select("SELECT COUNT(1) FROM production_work_logs "
            + "WHERE tenant_id = #{tenantId} AND processing_order_id = #{processingOrderId} "
            + "AND worker_id = #{workerId} AND deleted = 0 AND operation_name ILIKE '%打包%'")
    int countPackerLogs(@Param("tenantId") Long tenantId,
                        @Param("processingOrderId") String processingOrderId,
                        @Param("workerId") String workerId);
}
