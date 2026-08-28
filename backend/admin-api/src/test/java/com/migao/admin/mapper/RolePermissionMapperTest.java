package com.migao.admin.mapper;
// case_ids: HR-004, HR-005

import com.migao.admin.entity.RolePermission;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mybatis.spring.annotation.MapperScan;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * RolePermissionMapper 验证测试
 * 角色-权限关联表（V16）的 Mapper 为纯 BaseMapper（无自定义 SQL），
 * 验证其注册与实体映射正确。
 */
@DisplayName("RolePermissionMapper 注册验证")
class RolePermissionMapperTest {

    @Test
    @DisplayName("RolePermissionMapper 是 MyBatis-Plus BaseMapper 且标注 @Mapper")
    void mapper_isBaseMapperAndAnnotated() throws Exception {
        assertThat(BaseMapper.class.isAssignableFrom(RolePermissionMapper.class))
                .as("RolePermissionMapper 应继承 BaseMapper<RolePermission>")
                .isTrue();

        org.apache.ibatis.annotations.Mapper annotation =
                RolePermissionMapper.class.getAnnotation(org.apache.ibatis.annotations.Mapper.class);
        assertThat(annotation).as("RolePermissionMapper 应标注 @Mapper 以被扫描注册").isNotNull();
    }

    @Test
    @DisplayName("RolePermission 实体对应表 role_permissions")
    void entity_mapsToRolePermissionsTable() throws Exception {
        com.baomidou.mybatisplus.annotation.TableName tableName =
                RolePermission.class.getAnnotation(com.baomidou.mybatisplus.annotation.TableName.class);
        assertThat(tableName).isNotNull();
        assertThat(tableName.value()).isEqualTo("role_permissions");
    }
}
