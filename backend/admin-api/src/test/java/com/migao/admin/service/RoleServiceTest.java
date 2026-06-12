package com.migao.admin.service;

import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.Permission;
import com.migao.admin.entity.Role;
import com.migao.admin.entity.User;
import com.migao.admin.entity.UserRole;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.PermissionMapper;
import com.migao.admin.mapper.RoleMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.mapper.UserRoleMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * RoleService 单元测试
 */
@ExtendWith(MockitoExtension.class)
class RoleServiceTest {

    @InjectMocks
    private RoleService roleService;

    @Mock
    private RoleMapper roleMapper;

    @Mock
    private PermissionMapper permissionMapper;

    @Mock
    private UserRoleMapper userRoleMapper;

    @Mock
    private UserMapper userMapper;

    private Role testRole;
    private UserRole testUserRole;

    @BeforeEach
    void setUp() {
        testRole = Role.builder()
                .id("role-001")
                .tenantId(1L)
                .name("管理员")
                .code("admin")
                .description("系统管理员")
                .status("active")
                .deleted(0)
                .build();

        testUserRole = UserRole.builder()
                .id("ur-001")
                .tenantId(1L)
                .userId("user-001")
                .roleId("role-001")
                .deleted(0)
                .build();
    }

    // ======================== getRolePage 测试 ========================

    @Test
    @DisplayName("分页查询角色列表 - 无筛选条件")
    void getRolePage_DefaultPagination() {
        // given
        Page<Role> mockPage = new Page<>(1, 20);
        mockPage.setRecords(List.of(testRole));
        mockPage.setTotal(1);

        when(roleMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(mockPage);

        // when
        PageResponse<Role> result = roleService.getRolePage(1, 20, null, 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getTotal()).isEqualTo(1);
        assertThat(result.getItems()).hasSize(1);
        assertThat(result.getItems().get(0).getName()).isEqualTo("管理员");
    }

    @Test
    @DisplayName("分页查询角色列表 - 带关键词筛选")
    void getRolePage_WithKeyword() {
        // given
        Page<Role> mockPage = new Page<>(1, 10);
        mockPage.setRecords(List.of(testRole));
        mockPage.setTotal(1);

        when(roleMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(mockPage);

        // when
        PageResponse<Role> result = roleService.getRolePage(1, 10, "admin", 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getItems()).hasSize(1);
        verify(roleMapper).selectPage(any(Page.class), any(LambdaQueryWrapper.class));
    }

    @Test
    @DisplayName("查询所有角色列表")
    void getAllRoles_Success() {
        // given
        when(roleMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(testRole));

        // when
        List<Role> result = roleService.getAllRoles(1L);

        // then
        assertThat(result).hasSize(1);
        assertThat(result.get(0).getCode()).isEqualTo("admin");
    }

    // ======================== createRole 测试 ========================

    @Test
    @DisplayName("创建角色成功")
    void createRole_Success() {
        // given
        when(roleMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null); // code 不重复
        when(roleMapper.insert(any(Role.class))).thenAnswer(invocation -> {
            Role r = invocation.getArgument(0);
            r.setId("role-new");
            return 1;
        });

        // when
        Role result = roleService.createRole("运营", "operator", "运营人员", 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getId()).isEqualTo("role-new");
        assertThat(result.getName()).isEqualTo("运营");
        assertThat(result.getCode()).isEqualTo("operator");
        assertThat(result.getStatus()).isEqualTo("active");
        verify(roleMapper).insert(any(Role.class));
    }

    @Test
    @DisplayName("创建角色失败 - 角色代码已存在")
    void createRole_CodeDuplicate() {
        // given
        when(roleMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testRole);

        // when & then
        assertThatThrownBy(() -> roleService.createRole("管理员2", "admin", "重复角色", 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("角色代码已存在");
    }

    // ======================== updateRole 测试 ========================

    @Test
    @DisplayName("更新角色成功")
    void updateRole_Success() {
        // given
        when(roleMapper.selectById("role-001")).thenReturn(testRole);
        when(roleMapper.updateById(any(Role.class))).thenReturn(1);

        // when
        Role result = roleService.updateRole("role-001", "超级管理员", "更新后的描述");

        // then
        assertThat(result).isNotNull();
        assertThat(result.getName()).isEqualTo("超级管理员");
        assertThat(result.getDescription()).isEqualTo("更新后的描述");
        verify(roleMapper).updateById(any(Role.class));
    }

    @Test
    @DisplayName("更新角色 - 仅更新名称")
    void updateRole_OnlyName() {
        // given
        when(roleMapper.selectById("role-001")).thenReturn(testRole);
        when(roleMapper.updateById(any(Role.class))).thenReturn(1);

        // when
        Role result = roleService.updateRole("role-001", "新名称", null);

        // then
        assertThat(result.getName()).isEqualTo("新名称");
        assertThat(result.getDescription()).isEqualTo("系统管理员"); // 原描述不变
    }

    @Test
    @DisplayName("更新角色失败 - 角色不存在")
    void updateRole_NotFound() {
        // given
        when(roleMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> roleService.updateRole("nonexistent", "新名称", null))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    // ======================== deleteRole 测试 ========================

    @Test
    @DisplayName("删除角色成功")
    void deleteRole_Success() {
        // given
        when(roleMapper.selectById("role-001")).thenReturn(testRole);
        when(userRoleMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(0L);
        when(roleMapper.deleteById("role-001")).thenReturn(1);

        // when
        roleService.deleteRole("role-001");

        // then
        verify(roleMapper).deleteById("role-001");
    }

    @Test
    @DisplayName("删除角色失败 - 有用户使用该角色")
    void deleteRole_HasUsers() {
        // given
        when(roleMapper.selectById("role-001")).thenReturn(testRole);
        when(userRoleMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(3L);

        // when & then
        assertThatThrownBy(() -> roleService.deleteRole("role-001"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("3 个用户");
    }

    @Test
    @DisplayName("删除角色失败 - 角色不存在")
    void deleteRole_NotFound() {
        // given
        when(roleMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> roleService.deleteRole("nonexistent"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    // ======================== assignPermissions 测试 ========================

    @Test
    @DisplayName("为角色分配权限 - 占位实现正常执行")
    void assignPermissions_Success() {
        // given
        when(roleMapper.selectById("role-001")).thenReturn(testRole);

        // when
        roleService.assignPermissions("role-001", List.of("perm-001", "perm-002"));

        // then: 占位实现不抛异常即为成功
        verify(roleMapper).selectById("role-001");
    }

    @Test
    @DisplayName("为角色分配权限失败 - 角色不存在")
    void assignPermissions_RoleNotFound() {
        // given
        when(roleMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> roleService.assignPermissions("nonexistent", List.of("perm-001")))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    // ======================== getUserRoles 测试 ========================

    @Test
    @DisplayName("查询用户角色 - 有角色关联")
    void getUserRoles_HasRoles() {
        // given
        when(userRoleMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(testUserRole));
        when(roleMapper.selectBatchIds(List.of("role-001")))
                .thenReturn(List.of(testRole));

        // when
        List<Role> result = roleService.getUserRoles("user-001");

        // then
        assertThat(result).hasSize(1);
        assertThat(result.get(0).getCode()).isEqualTo("admin");
    }

    @Test
    @DisplayName("查询用户角色 - 无角色关联")
    void getUserRoles_NoRoles() {
        // given
        when(userRoleMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of());

        // when
        List<Role> result = roleService.getUserRoles("user-002");

        // then
        assertThat(result).isEmpty();
    }

    // ======================== assignRoleToUser 测试 ========================

    @Test
    @DisplayName("为用户分配角色成功")
    void assignRoleToUser_Success() {
        // given
        when(userRoleMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);
        when(userRoleMapper.insert(any(UserRole.class))).thenReturn(1);

        // when
        roleService.assignRoleToUser("user-001", "role-001", 1L);

        // then
        verify(userRoleMapper).insert(any(UserRole.class));
    }

    @Test
    @DisplayName("为用户分配角色失败 - 已拥有该角色")
    void assignRoleToUser_AlreadyAssigned() {
        // given
        when(userRoleMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testUserRole);

        // when & then
        assertThatThrownBy(() -> roleService.assignRoleToUser("user-001", "role-001", 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("已拥有该角色");
    }

    // ======================== removeRoleFromUser 测试 ========================

    @Test
    @DisplayName("移除用户角色成功")
    void removeRoleFromUser_Success() {
        // given
        when(userRoleMapper.delete(any(LambdaQueryWrapper.class))).thenReturn(1);

        // when
        roleService.removeRoleFromUser("user-001", "role-001");

        // then
        verify(userRoleMapper).delete(any(LambdaQueryWrapper.class));
    }

    @Test
    @DisplayName("移除用户角色失败 - 用户未拥有该角色")
    void removeRoleFromUser_NotAssigned() {
        // given
        when(userRoleMapper.delete(any(LambdaQueryWrapper.class))).thenReturn(0);

        // when & then
        assertThatThrownBy(() -> roleService.removeRoleFromUser("user-001", "role-999"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("未拥有该角色");
    }
}
