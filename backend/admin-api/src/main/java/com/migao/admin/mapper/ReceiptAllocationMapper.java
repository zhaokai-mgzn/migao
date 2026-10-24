package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ReceiptAllocation;
import org.apache.ibatis.annotations.Mapper;

/**
 * 客户收款核销 Mapper（issue #7370 段 3）。
 *
 * <p>SQL 一律走 `LambdaQueryWrapper`（租户条件由 TenantLineInnerInterceptor 注入）——
 * 本接口**不声明自定义 SQL**：核销的每一条读写都有「流水 / 订单 / 金额」三重口径，
 * 写在注解里就会绕开服务层的准入判据。判据 = {@code ReceiptAllocationMapperTest#mapperHasNoCustomSql}。</p>
 */
@Mapper
public interface ReceiptAllocationMapper extends BaseMapper<ReceiptAllocation> {
}
