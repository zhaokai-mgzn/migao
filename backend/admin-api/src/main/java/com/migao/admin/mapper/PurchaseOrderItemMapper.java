package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.PurchaseOrderItem;
import org.apache.ibatis.annotations.Mapper;

/**
 * PurchaseOrderItem Mapper（issue #7369 段 4）。
 *
 * <p>刻意只继承 {@code BaseMapper}：查询走 Wrapper ⇒ 租户插件与软删口径**自动生效**，
 * 不存在「手写 SQL 忘了带 tenant_id」这类越权口子。
 */
@Mapper
public interface PurchaseOrderItemMapper extends BaseMapper<PurchaseOrderItem> {
}
