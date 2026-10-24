package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.Supplier;
import org.apache.ibatis.annotations.Mapper;

/**
 * 供应商主数据 Mapper（issue #7369，P0-1 段 1）。
 *
 * <p>只有 BaseMapper：列表/详情/写入都是「本租户 + 软删」的常规查询，租户谓词由
 * {@code TenantLineInnerInterceptor} 注入 —— 不需要（也不该）在这里写第二套租户条件。
 */
@Mapper
public interface SupplierMapper extends BaseMapper<Supplier> {
}
