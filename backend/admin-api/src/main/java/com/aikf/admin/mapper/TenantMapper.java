package com.aikf.admin.mapper;

import com.aikf.admin.entity.Tenant;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/**
 * 租户Mapper接口
 */
@Mapper
public interface TenantMapper extends BaseMapper<Tenant> {
}
