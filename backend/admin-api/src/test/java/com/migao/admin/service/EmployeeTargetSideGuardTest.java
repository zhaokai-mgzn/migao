// case_ids: HR-003, HR-008, DF-007
package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Role;
import com.migao.admin.entity.User;
import com.migao.admin.entity.UserRole;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.RoleMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.mapper.UserRoleMapper;
import com.migao.admin.security.PermissionInterceptor;
import com.migao.admin.security.SecurityUser;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.security.authentication.AnonymousAuthenticationToken;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 员工管理的 <b>目标侧 ⊆ 门禁</b>（issue #4104 第 2 节的**另一半**，用户 2026-09-26 裁定
 * 「不得管理权限高于自己的账号」）。
 *
 * <h2>为什么需要它（授予侧门禁挡不住的那条路）</h2>
 * 只拦「授予自己没有的码」是不够的：持 {@code employee:create} 者仍可对**权限高于自己的既有账号**
 * 执行管理动作 —— 把管理员密码重置了、把管理员停用了、把管理员删了，或改掉管理员的手机号再经短信登录
 * 接管账号。本类逐条钉住这些路径都**在落库之前**被拒。
 *
 * <h2>判据是子集比较，不是「只有管理员能改别人密码」那种粗规则</h2>
 * <ul>
 *   <li>同权限同事、下级岗位、以及**自己的账号**都必须照常可用 —— 见
 *       {@link #sameOrLowerPrivilegedPeer_canStillBeManaged()} / {@link #selfService_isExempt()}；
 *       粗规则会误伤日常操作，本类专门留了正向对照盯住这一点；</li>
 *   <li>三态与授予侧逐条一致：旁路身份、无操作者（引导/自助）不适用；判不出来 ⇒ **fail-closed 拒绝**。</li>
 * </ul>
 *
 * <p><b>拒绝形态</b>：403 + 独立错误码 {@code PERMISSION_OUTRANK_DENIED}，点名「账号 + 动作」，
 * 但**不回显目标账号持有哪些权限码**（那是别人的授权信息）——
 * {@link #employeeCreateHolder_resettingHigherPrivilegedAccount_isRejected()} 有负断言钉住这一点。</p>
 *
 * <p><b>同类守卫</b>：{@code EmployeeGrantChokepointMetaGuardTest}（元守卫：授权写面 + 目标侧写面普查）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("员工管理目标侧 ⊆ 门禁（#4104 另一半）：不得管理权限高于自己的账号")
class EmployeeTargetSideGuardTest {

    private static final Long TENANT = 1L;
    private static final String ACTOR = "actor-001";
    private static final String ADMIN = "admin-1";
    private static final String PEER = "peer-002";

    private UserMapper userMapper;
    private RoleMapper roleMapper;
    private UserRoleMapper userRoleMapper;
    private RoleService roleService;
    private UserService userService;

    @BeforeEach
    void setUp() {
        MybatisConfiguration configuration = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(configuration, "");
        TableInfoHelper.initTableInfo(assistant, User.class);
        TableInfoHelper.initTableInfo(assistant, Role.class);
        TableInfoHelper.initTableInfo(assistant, UserRole.class);

        userMapper = mock(UserMapper.class);
        roleMapper = mock(RoleMapper.class);
        userRoleMapper = mock(UserRoleMapper.class);
        roleService = mock(RoleService.class);
        userService = new UserService(userMapper, roleMapper, userRoleMapper, new PermissionInterceptor(roleService));
        TenantContext.setTenantId(TENANT);
    }

    @AfterEach
    void tearDown() {
        SecurityContextHolder.clearContext();
        TenantContext.clear();
    }

    // ======================== 负向：高权限目标一律拒绝 + 不落库 ========================

    @Test
    @DisplayName("🔴 employee:create 持有者重置**管理员**（* 权限）密码 ⇒ 403 PERMISSION_OUTRANK_DENIED，且连目标行都不读")
    void employeeCreateHolder_resettingHigherPrivilegedAccount_isRejected() {
        authenticateEmployee(ACTOR, "employee:list", "employee:create");
        when(roleService.getUserPermissions(ADMIN)).thenReturn(List.of("*"));

        assertThatThrownBy(() -> userService.resetPassword(ADMIN))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("重置密码")
                .hasMessageContaining(ADMIN)
                .satisfies(thrown -> {
                    BusinessException be = (BusinessException) thrown;
                    assertThat(be.getCode()).isEqualTo("PERMISSION_OUTRANK_DENIED");
                    assertThat(be.getHttpStatus()).isEqualTo(403);
                    assertThat(be.getSuggestion()).as("拒绝要可行动（说清不是参数问题 + 出口）").isNotBlank();
                    assertThat(be.getMessage())
                            .as("不回显目标账号持有哪些权限码（那是别人的授权信息）")
                            .doesNotContain("*");
                });

        verify(userMapper, never()).updateById(any(User.class));
        verify(userMapper, never()).selectById(anyString());
    }

    @Test
    @DisplayName("🔴 同一路径的删除 / 停用 / 启用 / 改资料：全部拒绝且不落库（同族动作不得一严一松）")
    void employeeCreateHolder_allAccountWritesOnHigherPrivilegedTarget_areRejected() {
        authenticateEmployee(ACTOR, "employee:list", "employee:create");
        when(roleService.getUserPermissions(ADMIN)).thenReturn(List.of("*", "system:manage"));

        assertThatThrownBy(() -> userService.deleteUser(ADMIN))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("删除员工")
                .hasFieldOrPropertyWithValue("code", "PERMISSION_OUTRANK_DENIED");
        assertThatThrownBy(() -> userService.disableUser(ADMIN))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("停用账号")
                .hasFieldOrPropertyWithValue("code", "PERMISSION_OUTRANK_DENIED");
        assertThatThrownBy(() -> userService.enableUser(ADMIN))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("启用账号")
                .hasFieldOrPropertyWithValue("code", "PERMISSION_OUTRANK_DENIED");
        assertThatThrownBy(() -> userService.changePassword(ADMIN, "NewPass123"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("修改密码")
                .hasFieldOrPropertyWithValue("code", "PERMISSION_OUTRANK_DENIED");
        assertThatThrownBy(() -> userService.updateUser(ADMIN, "改名", null, null, null, null))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("修改员工资料")
                .hasFieldOrPropertyWithValue("code", "PERMISSION_OUTRANK_DENIED");

        verify(userMapper, never()).updateById(any(User.class));
        verify(userMapper, never()).deleteById(anyString());
        verify(userMapper, never()).selectById(anyString());
    }

    @Test
    @DisplayName("🔴 fail-closed：操作者自身权限解析不出来（空集）⇒ 管理任何有权限的账号都拒绝")
    void unresolvableActorPermissions_failClosed() {
        authenticateEmployee(ACTOR);  // 空权限集
        when(roleService.getUserPermissions(PEER)).thenReturn(List.of("dashboard:view"));

        assertThatThrownBy(() -> userService.disableUser(PEER))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", "PERMISSION_OUTRANK_DENIED");

        verify(userMapper, never()).updateById(any(User.class));
    }

    // ======================== 正向对照：子集比较，不是粗规则 ========================

    @Test
    @DisplayName("✅ 同权限同事与下级岗位照常可管理（粗规则「只有 admin 能改别人密码」会误伤这些日常操作）")
    void sameOrLowerPrivilegedPeer_canStillBeManaged() {
        authenticateEmployee(ACTOR, "employee:list", "employee:create", "dashboard:view");
        // 同权限同事：目标权限集 == 操作者权限集的子集（相等）
        when(roleService.getUserPermissions(PEER)).thenReturn(List.of("employee:create", "dashboard:view"));
        User peer = User.builder().id(PEER).tenantId(TENANT).phone("13800138001").status("active").build();
        when(userMapper.selectById(PEER)).thenReturn(peer);

        userService.resetPassword(PEER);

        verify(userMapper).updateById(any(User.class));
    }

    @Test
    @DisplayName("✅ 自助（目标 = 操作者本人）不受影响：恒 ⊆，且不做第二次权限查询")
    void selfService_isExempt() {
        authenticateEmployee(ACTOR, "employee:list", "employee:create");
        User me = User.builder().id(ACTOR).tenantId(TENANT).phone("13800138000").status("active").build();
        when(userMapper.selectById(ACTOR)).thenReturn(me);

        userService.resetPassword(ACTOR);

        verify(userMapper).updateById(any(User.class));
        verify(roleService, times(1)).getUserPermissions(ACTOR);
        verify(roleService, never()).getUserPermissions(ADMIN);
    }

    @Test
    @DisplayName("✅ 旁路身份（平台管理员 super_admin）不适用 ⊆ 判定")
    void privilegedIdentity_isExempt() {
        SecurityUser principal = new SecurityUser("platform-1", TENANT, "platform-admin",
                List.of("super_admin"), List.of(new SimpleGrantedAuthority("ROLE_super_admin")));
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(principal, "n/a", principal.getAuthorities()));
        User admin = User.builder().id(ADMIN).tenantId(TENANT).phone("13800138002").status("active").build();
        when(userMapper.selectById(ADMIN)).thenReturn(admin);

        userService.resetPassword(ADMIN);

        verify(userMapper).updateById(any(User.class));
    }

    @Test
    @DisplayName("✅ 无操作者（匿名：公开注册引导 / 登录锁定等系统路径）不适用 ⊆ 判定")
    void anonymous_isExempt() {
        SecurityContextHolder.getContext().setAuthentication(new AnonymousAuthenticationToken(
                "anon-key", "anonymousUser", List.of(new SimpleGrantedAuthority("ROLE_ANONYMOUS"))));
        User admin = User.builder().id(ADMIN).tenantId(TENANT).phone("13800138003").status("active").build();
        when(userMapper.selectById(ADMIN)).thenReturn(admin);

        userService.resetPassword(ADMIN);

        verify(userMapper).updateById(any(User.class));
    }

    // ======================== helpers ========================

    private void authenticateEmployee(String actorId, String... permissions) {
        SecurityUser principal = new SecurityUser(actorId, TENANT, "13800138000", List.of("operator"),
                List.of(new SimpleGrantedAuthority("ROLE_operator")));
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(principal, "n/a", principal.getAuthorities()));
        when(roleService.getUserPermissions(actorId)).thenReturn(List.of(permissions));
    }
}
