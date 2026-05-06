package com.aikf.admin.service;

import com.aikf.admin.dto.PageResponse;
import com.aikf.admin.entity.Role;
import com.aikf.admin.entity.User;
import com.aikf.admin.entity.UserRole;
import com.aikf.admin.exception.BusinessException;
import com.aikf.admin.mapper.RoleMapper;
import com.aikf.admin.mapper.UserMapper;
import com.aikf.admin.mapper.UserRoleMapper;
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
 * UserService 单元测试
 */
@ExtendWith(MockitoExtension.class)
class UserServiceTest {

    @InjectMocks
    private UserService userService;

    @Mock
    private UserMapper userMapper;

    @Mock
    private RoleMapper roleMapper;

    @Mock
    private UserRoleMapper userRoleMapper;

    private User testUser;

    @BeforeEach
    void setUp() {
        testUser = User.builder()
                .id("user-001")
                .tenantId(1L)
                .phone("13800138000")
                .passwordHash("$2a$10$hashedPassword")
                .nickname("测试管理员")
                .avatar("https://example.com/avatar.png")
                .role("admin")
                .status("active")
                .deleted(0)
                .build();
    }

    // ======================== getUserByUsernameAndTenant 测试 ========================

    @Test
    @DisplayName("根据用户名和租户查询 - 用户存在")
    void getUserByUsernameAndTenant_Found() {
        // given
        when(userMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testUser);

        // when
        User result = userService.getUserByUsernameAndTenant("13800138000", 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getPhone()).isEqualTo("13800138000");
        assertThat(result.getTenantId()).isEqualTo(1L);
    }

    @Test
    @DisplayName("根据用户名和租户查询 - 用户不存在")
    void getUserByUsernameAndTenant_NotFound() {
        // given
        when(userMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);

        // when
        User result = userService.getUserByUsernameAndTenant("nonexistent", 1L);

        // then
        assertThat(result).isNull();
    }

    // ======================== getUserById 测试 ========================

    @Test
    @DisplayName("根据ID查询用户 - 用户存在")
    void getUserById_Found() {
        // given
        when(userMapper.selectById("user-001")).thenReturn(testUser);

        // when
        User result = userService.getUserById("user-001");

        // then
        assertThat(result).isNotNull();
        assertThat(result.getId()).isEqualTo("user-001");
        assertThat(result.getNickname()).isEqualTo("测试管理员");
    }

    @Test
    @DisplayName("根据ID查询用户 - 用户不存在，抛异常")
    void getUserById_NotFound() {
        // given
        when(userMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> userService.getUserById("nonexistent"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                    assertThat(bex.getHttpStatus()).isEqualTo(404);
                });
    }

    // ======================== getUserPage (getAllUsers) 测试 ========================

    @Test
    @DisplayName("分页查询用户列表 - 无筛选条件")
    void getUserPage_DefaultPagination() {
        // given
        Page<User> mockPage = new Page<>(1, 20);
        mockPage.setRecords(List.of(testUser));
        mockPage.setTotal(1);

        when(userMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(mockPage);

        // when
        PageResponse<User> result = userService.getUserPage(1, 20, null, null, null, 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getTotal()).isEqualTo(1);
        assertThat(result.getItems()).hasSize(1);
        // 验证密码已脱敏
        assertThat(result.getItems().get(0).getPasswordHash()).isNull();
    }

    @Test
    @DisplayName("分页查询用户列表 - 带角色和关键词筛选")
    void getUserPage_WithFilters() {
        // given
        Page<User> mockPage = new Page<>(1, 10);
        mockPage.setRecords(List.of(testUser));
        mockPage.setTotal(1);

        when(userMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(mockPage);

        // when
        PageResponse<User> result = userService.getUserPage(1, 10, "admin", "active", "测试", 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getItems()).hasSize(1);
        verify(userMapper).selectPage(any(Page.class), any(LambdaQueryWrapper.class));
    }

    @Test
    @DisplayName("分页查询用户列表 - 空结果")
    void getUserPage_EmptyResult() {
        // given
        Page<User> emptyPage = new Page<>(1, 20);
        emptyPage.setRecords(List.of());
        emptyPage.setTotal(0);

        when(userMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(emptyPage);

        // when
        PageResponse<User> result = userService.getUserPage(1, 20, null, null, null, 1L);

        // then
        assertThat(result.getTotal()).isEqualTo(0);
        assertThat(result.getItems()).isEmpty();
    }

    // ======================== createUser 测试 ========================

    @Test
    @DisplayName("创建用户成功")
    void createUser_Success() {
        // given
        when(userMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null); // 手机号不重复
        when(userMapper.insert(any(User.class))).thenAnswer(invocation -> {
            User u = invocation.getArgument(0);
            u.setId("user-new");
            return 1;
        });
        // assignRoleToUser 内部查询角色
        Role adminRole = Role.builder().id("role-001").code("admin").tenantId(1L).build();
        when(roleMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(adminRole);
        when(userRoleMapper.insert(any(UserRole.class))).thenReturn(1);

        // when
        User result = userService.createUser("13900139000", "password123", "新用户", "admin", 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getId()).isEqualTo("user-new");
        assertThat(result.getPhone()).isEqualTo("13900139000");
        assertThat(result.getRole()).isEqualTo("admin");
        assertThat(result.getStatus()).isEqualTo("active");
        // 密码已脱敏
        assertThat(result.getPasswordHash()).isNull();
        verify(userMapper).insert(any(User.class));
    }

    @Test
    @DisplayName("创建用户成功 - 密码被加密存储")
    void createUser_PasswordEncrypted() {
        // given
        when(userMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);
        when(userMapper.insert(any(User.class))).thenAnswer(invocation -> {
            User u = invocation.getArgument(0);
            u.setId("user-enc");
            // 验证密码已被 BCrypt 加密
            assertThat(u.getPasswordHash()).startsWith("$2a$");
            assertThat(u.getPasswordHash()).isNotEqualTo("password123");
            return 1;
        });
        when(roleMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null); // 角色不存在，仅日志

        // when
        User result = userService.createUser("13700137000", "password123", "加密测试", "operator", 1L);

        // then
        assertThat(result).isNotNull();
        verify(userMapper).insert(any(User.class));
    }

    @Test
    @DisplayName("创建用户失败 - 手机号已注册")
    void createUser_PhoneDuplicate() {
        // given
        when(userMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testUser);

        // when & then
        assertThatThrownBy(() -> userService.createUser("13800138000", "password123", "重复用户", "admin", 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("手机号已被注册");
    }

    @Test
    @DisplayName("创建用户 - 角色为空时默认 operator")
    void createUser_DefaultRole() {
        // given
        when(userMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);
        when(userMapper.insert(any(User.class))).thenAnswer(invocation -> {
            User u = invocation.getArgument(0);
            u.setId("user-default");
            return 1;
        });

        // when
        User result = userService.createUser("13600136000", "password123", "默认角色", null, 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getRole()).isEqualTo("operator");
    }

    // ======================== updateUser 测试 ========================

    @Test
    @DisplayName("更新用户信息成功")
    void updateUser_Success() {
        // given
        when(userMapper.selectById("user-001")).thenReturn(testUser);
        when(userMapper.updateById(any(User.class))).thenReturn(1);

        // when
        User result = userService.updateUser("user-001", "新昵称", "https://example.com/new-avatar.png", null);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getNickname()).isEqualTo("新昵称");
        assertThat(result.getAvatar()).isEqualTo("https://example.com/new-avatar.png");
        assertThat(result.getPasswordHash()).isNull(); // 已脱敏
        verify(userMapper).updateById(any(User.class));
    }

    @Test
    @DisplayName("更新用户信息 - 变更角色")
    void updateUser_ChangeRole() {
        // given
        when(userMapper.selectById("user-001")).thenReturn(testUser);
        when(userMapper.updateById(any(User.class))).thenReturn(1);
        when(userRoleMapper.delete(any(LambdaQueryWrapper.class))).thenReturn(1);
        when(roleMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null); // 角色不存在仅日志

        // when
        User result = userService.updateUser("user-001", null, null, "operator");

        // then
        assertThat(result.getRole()).isEqualTo("operator");
        verify(userRoleMapper).delete(any(LambdaQueryWrapper.class));
    }

    @Test
    @DisplayName("更新用户信息失败 - 用户不存在")
    void updateUser_NotFound() {
        // given
        when(userMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> userService.updateUser("nonexistent", "新昵称", null, null))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    // ======================== toggleUserStatus (disable/enable) 测试 ========================

    @Test
    @DisplayName("禁用用户成功")
    void disableUser_Success() {
        // given
        when(userMapper.selectById("user-001")).thenReturn(testUser);
        when(userMapper.updateById(any(User.class))).thenReturn(1);

        // when
        userService.disableUser("user-001");

        // then
        verify(userMapper).updateById(argThat((User u) -> "disabled".equals(u.getStatus())));
    }

    @Test
    @DisplayName("禁用用户失败 - 已是禁用状态")
    void disableUser_AlreadyDisabled() {
        // given
        testUser.setStatus("disabled");
        when(userMapper.selectById("user-001")).thenReturn(testUser);

        // when & then
        assertThatThrownBy(() -> userService.disableUser("user-001"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("已处于禁用状态");
    }

    @Test
    @DisplayName("启用用户成功")
    void enableUser_Success() {
        // given
        testUser.setStatus("disabled");
        when(userMapper.selectById("user-001")).thenReturn(testUser);
        when(userMapper.updateById(any(User.class))).thenReturn(1);

        // when
        userService.enableUser("user-001");

        // then
        verify(userMapper).updateById(argThat((User u) -> "active".equals(u.getStatus())));
    }

    @Test
    @DisplayName("启用用户失败 - 已是启用状态")
    void enableUser_AlreadyActive() {
        // given
        when(userMapper.selectById("user-001")).thenReturn(testUser);

        // when & then
        assertThatThrownBy(() -> userService.enableUser("user-001"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("已处于启用状态");
    }

    @Test
    @DisplayName("禁用/启用 - 用户不存在")
    void toggleUserStatus_UserNotFound() {
        // given
        when(userMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> userService.disableUser("nonexistent"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    // ======================== resetPassword 测试 ========================

    @Test
    @DisplayName("重置密码成功 - 默认密码为手机号后6位")
    void resetPassword_Success() {
        // given
        when(userMapper.selectById("user-001")).thenReturn(testUser);
        when(userMapper.updateById(any(User.class))).thenReturn(1);

        // when
        String defaultPassword = userService.resetPassword("user-001");

        // then
        assertThat(defaultPassword).isEqualTo("138000"); // 13800138000 后6位
        verify(userMapper).updateById(argThat((User u) -> {
            // 验证密码已被 BCrypt 加密
            return u.getPasswordHash() != null && u.getPasswordHash().startsWith("$2a$");
        }));
    }

    @Test
    @DisplayName("重置密码成功 - 短手机号回退")
    void resetPassword_ShortPhone() {
        // given
        testUser.setPhone("12345");
        when(userMapper.selectById("user-001")).thenReturn(testUser);
        when(userMapper.updateById(any(User.class))).thenReturn(1);

        // when
        String defaultPassword = userService.resetPassword("user-001");

        // then
        assertThat(defaultPassword).isEqualTo("12345"); // 短于6位直接用全部
    }

    @Test
    @DisplayName("重置密码失败 - 用户不存在")
    void resetPassword_UserNotFound() {
        // given
        when(userMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> userService.resetPassword("nonexistent"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    // ======================== getUserRoles 测试 ========================

    @Test
    @DisplayName("获取用户角色 - 有角色")
    void getUserRoles_HasRole() {
        // given / when
        List<String> roles = userService.getUserRoles(testUser);

        // then
        assertThat(roles).containsExactly("admin");
    }

    @Test
    @DisplayName("获取用户角色 - 角色为空")
    void getUserRoles_NoRole() {
        // given
        testUser.setRole(null);

        // when
        List<String> roles = userService.getUserRoles(testUser);

        // then
        assertThat(roles).isEmpty();
    }
}
