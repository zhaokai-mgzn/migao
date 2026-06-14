package com.migao.admin.service;

import com.migao.admin.entity.Permission;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.PermissionMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/**
 * PermissionService 单元测试
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("PermissionService 权限服务测试")
class PermissionServiceTest {

    @Mock
    private PermissionMapper permissionMapper;

    @InjectMocks
    private PermissionService permissionService;

    @Test
    @DisplayName("getAllPermissions — 返回激活且未删除的权限")
    void getAllPermissions_returnsActiveUndeleted() {
        Permission p1 = new Permission();
        p1.setId(1L);
        p1.setCode("product:list");
        p1.setName("商品列表");
        p1.setDeleted(0);
        p1.setStatus("active");

        Permission p2 = new Permission();
        p2.setId(2L);
        p2.setCode("order:list");
        p2.setName("订单列表");
        p2.setDeleted(0);
        p2.setStatus("active");

        when(permissionMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(p1, p2));

        List<Permission> result = permissionService.getAllPermissions();

        assertThat(result).hasSize(2);
        assertThat(result.get(0).getCode()).isEqualTo("product:list");
    }

    @Test
    @DisplayName("getPermissionsByTenant — 按租户过滤")
    void getPermissionsByTenant_filtersByTenant() {
        when(permissionMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of());

        List<Permission> result = permissionService.getPermissionsByTenant(1L);

        assertThat(result).isEmpty();
        verify(permissionMapper).selectList(any(LambdaQueryWrapper.class));
    }

    @Test
    @DisplayName("getPermissionByCode — 找到权限返回 Permission")
    void getPermissionByCode_found() {
        Permission p = new Permission();
        p.setId(1L);
        p.setCode("product:list");
        when(permissionMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(p);

        Permission result = permissionService.getPermissionByCode("product:list");

        assertThat(result).isNotNull();
        assertThat(result.getCode()).isEqualTo("product:list");
    }

    @Test
    @DisplayName("getPermissionByCode — 不存在返回 null")
    void getPermissionByCode_notFound() {
        when(permissionMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);

        Permission result = permissionService.getPermissionByCode("nonexistent");

        assertThat(result).isNull();
    }

    @Test
    @DisplayName("createPermission — code 不重复则创建成功")
    void createPermission_codeNotExists_success() {
        when(permissionMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);
        when(permissionMapper.insert(any(Permission.class))).thenReturn(1);

        Permission p = new Permission();
        p.setCode("new:perm");
        p.setName("新权限");

        Permission result = permissionService.createPermission(p);

        assertThat(result).isNotNull();
        verify(permissionMapper).insert(any(Permission.class));
    }

    @Test
    @DisplayName("createPermission — code 已存在抛出异常")
    void createPermission_codeExists_throwsException() {
        Permission existing = new Permission();
        existing.setCode("existing:perm");
        when(permissionMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(existing);

        Permission p = new Permission();
        p.setCode("existing:perm");

        assertThatThrownBy(() -> permissionService.createPermission(p))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("权限码");
    }
}
