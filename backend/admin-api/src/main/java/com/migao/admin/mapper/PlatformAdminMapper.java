package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.PlatformAdmin;
import org.apache.ibatis.annotations.Mapper;

/**
 * 平台管理员 Mapper 接口
 * 使用 MyBatis-Plus 内置方法（selectById, selectOne 等）
 * 该表无 tenant_id 字段，已在 MybatisPlusConfig 中注册跳过租户过滤
 */
@Mapper
public interface PlatformAdminMapper extends BaseMapper<PlatformAdmin> {
}
