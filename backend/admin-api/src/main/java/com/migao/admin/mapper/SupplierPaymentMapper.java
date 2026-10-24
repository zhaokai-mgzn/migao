package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.SupplierPayment;
import org.apache.ibatis.annotations.Mapper;

/**
 * 付款单 Mapper（issue #7369 段 3-B）。
 *
 * <p>刻意只继承 {@code BaseMapper}：所有查询走 Wrapper ⇒ 租户插件与软删口径**自动生效**，
 * 不存在「手写 SQL 忘了带 tenant_id」这一类越权口子。
 */
@Mapper
public interface SupplierPaymentMapper extends BaseMapper<SupplierPayment> {
}
