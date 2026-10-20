package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.SupplierPaymentAllocation;
import org.apache.ibatis.annotations.Mapper;

/**
 * 付款冲抵明细 Mapper（issue #7369 段 3-B）。同上：只走 Wrapper，靠租户插件与软删兜口径。
 */
@Mapper
public interface SupplierPaymentAllocationMapper extends BaseMapper<SupplierPaymentAllocation> {
}
