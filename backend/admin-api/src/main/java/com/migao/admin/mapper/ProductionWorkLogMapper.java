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
    /**
     * 「打包工序」的**唯一关键词**（issue #7845）。
     *
     * <p>两处判据共用它，**不写第二份**：① 扫水洗唛的授权（本接口的 SQL LIKE）；
     * ② 扫码报工「本次报的是不是打包」的触发（{@code FinishedGoodsService#isPackOperation}）。
     * 用户口径（2026-10-26）：「只有打包工序绑定了成品帘入库」。</p>
     */
    String PACK_OPERATION_KEYWORD = "打包";

    @com.baomidou.mybatisplus.annotation.InterceptorIgnore(tenantLine = "true")
    @Select("SELECT COUNT(1) FROM production_work_logs "
            + "WHERE tenant_id = #{tenantId} AND processing_order_id = #{processingOrderId} "
            + "AND worker_id = #{workerId} AND deleted = 0 AND operation_name ILIKE CONCAT('%', #{keyword}, '%')")
    int countPackerLogs(@Param("tenantId") Long tenantId,
                        @Param("processingOrderId") String processingOrderId,
                        @Param("workerId") String workerId,
                        @Param("keyword") String keyword);

    /** 三参重载（既有调用方）：关键词取 {@link #PACK_OPERATION_KEYWORD}，行为与改前逐字相同。 */
    default int countPackerLogs(Long tenantId, String processingOrderId, String workerId) {
        return countPackerLogs(tenantId, processingOrderId, workerId, PACK_OPERATION_KEYWORD);
    }
}
