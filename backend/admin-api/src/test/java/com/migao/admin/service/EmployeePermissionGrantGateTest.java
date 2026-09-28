// case_ids: HR-002, HR-004, DF-007
package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Permission;
import com.migao.admin.entity.Role;
import com.migao.admin.entity.RolePermission;
import com.migao.admin.entity.User;
import com.migao.admin.entity.UserRole;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.PermissionMapper;
import com.migao.admin.mapper.RoleMapper;
import com.migao.admin.mapper.RolePermissionMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.mapper.UserRoleMapper;
import com.migao.admin.security.PermissionInterceptor;
import com.migao.admin.security.SecurityUser;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
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
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 员工管理授权面的 <b>⊆ 门禁</b>（issue #4104 第 2 节「{@code employee:create} ≈ 租户内完全提权」）。
 *
 * <h2>判据来源</h2>
 * 用户 2026-09-26 裁定：**授予的权限码必须 ⊆ 操作者自身权限**（三选一里最严的一档）。
 * 改前 {@code UserService.assertAssignableRoleAndPermissions} 只拦「系统保留角色」与字面量
 * {@code "*"}，不拦「授予自己没有的码」⇒ 持 {@code employee:create} 者可给自己/他人写
 * {@code ["system:manage"]}（提权）。本类逐条钉住修复后的行为。
 *
 * <h2>断言口径（为什么这样写）</h2>
 * <ul>
 *   <li><b>拒绝要可判</b>：断言 403 + 独立错误码 {@code PERMISSION_ESCALATION_DENIED} +
 *       消息里**点名**违规码（不看日志、不只看 HTTP 状态）；</li>
 *   <li><b>拒绝要真的不落库</b>：{@code verify(never())} 断言 insert/update 从未发生
 *       —— "返回了 403" 不等于 "没写进去"；</li>
 *   <li><b>正向对照不能少</b>：合法子集赋值必须**成功且快照落库**，否则无法区分
 *       「正确拒绝」与「整条链路坏了」（RBAC.md 的取值纪律）；</li>
 *   <li><b>角色面也算授予集</b>：{@code role=admin} 隐含 {@code *}（{@code RoleService}
 *       的既有口径）⇒ 只看快照数组会被「授予一个比自己权限更大的角色」绕过。</li>
 * </ul>
 *
 * <p><b>同类守卫</b>：{@code EmployeeGrantChokepointMetaGuardTest}（类级元守卫：授权写面普查 +
 * 门禁调用点台账）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("员工授权面 ⊆ 门禁（#4104）：授予码必须 ⊆ 操作者自身权限，且拒绝时不落库")
class EmployeePermissionGrantGateTest {

    private static final Long TENANT = 1L;
    private static final String ACTOR = "actor-001";
    private static final String PHONE = "13800138000";

    private UserMapper userMapper;
    private RoleMapper roleMapper;
    private UserRoleMapper userRoleMapper;
    private RoleService roleService;
    private UserService userService;

    @BeforeEach
    void setUp() {
        // 初始化 MyBatis-Plus lambda 缓存（LambdaQueryWrapper 解析 User::getXxx 需要 TableInfo）
        MybatisConfiguration configuration = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(configuration, "");
        TableInfoHelper.initTableInfo(assistant, User.class);
        TableInfoHelper.initTableInfo(assistant, Role.class);
        TableInfoHelper.initTableInfo(assistant, UserRole.class);
        TableInfoHelper.initTableInfo(assistant, RolePermission.class);

        userMapper = mock(UserMapper.class);
        roleMapper = mock(RoleMapper.class);
        userRoleMapper = mock(UserRoleMapper.class);
        roleService = mock(RoleService.class);
        userService = userServiceWith(roleService);
        TenantContext.setTenantId(TENANT);
    }

    @AfterEach
    void tearDown() {
        SecurityContextHolder.clearContext();
        TenantContext.clear();
    }

    // ======================== 负向：越权授予被拒 + 不落库 ========================

    @Test
    @DisplayName("🔴 employee:create 持有者授予 [\"system:manage\"] ⇒ 403 PERMISSION_ESCALATION_DENIED，且一行都不落库")
    void employeeCreateHolderGrantingSystemManage_isRejectedAndNothingPersisted() {
        authenticateEmployee(roleService, ACTOR, "employee:list", "employee:create");

        assertThatThrownBy(() -> userService.createUser(PHONE, "Init1234", "越权测试", "operator", "客服",
                "[\"system:manage\"]", TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("system:manage")
                .satisfies(thrown -> {
                    BusinessException be = (BusinessException) thrown;
                    assertThat(be.getCode()).isEqualTo("PERMISSION_ESCALATION_DENIED");
                    assertThat(be.getHttpStatus()).isEqualTo(403);
                    assertThat(be.getSuggestion()).as("拒绝要可行动（说清不是参数问题 + 出口）").isNotBlank();
                });

        verify(userMapper, never()).insert(any(User.class));
        verify(userRoleMapper, never()).insert(any(UserRole.class));
    }

    @Test
    @DisplayName("🔴 同一越权走 PUT（updateUser）同样被拒，且在**读取目标用户之前**就拒（不泄露 userId 是否存在）")
    void updateUser_grantingBeyondActor_isRejectedBeforeTouchingTarget() {
        authenticateEmployee(roleService, ACTOR, "employee:list", "employee:create");

        assertThatThrownBy(() -> userService.updateUser("user-999", "改名", null, null,
                "[\"system:manage\"]"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("system:manage")
                .hasFieldOrPropertyWithValue("code", "PERMISSION_ESCALATION_DENIED");

        verify(userMapper, never()).selectById(anyString());
        verify(userMapper, never()).updateById(any(User.class));
    }

    @Test
    @DisplayName("🔴 角色面也拦：授予 role=admin（隐含 *）被拒 —— 只看快照数组会被绕过")
    void roleImpliedWildcard_isRejected() {
        // ① 用**真** RoleService 钉住「角色码 → 生效码」的真值（admin 快路径，不查库、不依赖 mock 默认值）
        RoleService realRoleService = new RoleService(mock(RoleMapper.class), mock(PermissionMapper.class),
                mock(UserRoleMapper.class), mock(UserMapper.class), mock(RolePermissionMapper.class));
        assertThat(realRoleService.getEffectivePermissionCodesForRoleCode("admin", TENANT))
                .as("角色码 → 生效码的真值：admin 恒为 *（与 getUserPermissions 同一份口径）")
                .containsExactly("*");

        // ② 门禁行为：把该真值喂进判定链（只有"取码"被替身，判定本身仍是生产代码）
        authenticateEmployee(roleService, ACTOR, "employee:list", "employee:create");
        when(roleService.getEffectivePermissionCodesForRoleCode("admin", TENANT)).thenReturn(List.of("*"));

        assertThatThrownBy(() -> userService.createUser(PHONE, "Init1234", "新管理员", "admin", "管理员",
                "[]", TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessage("不能授予自己不具备的权限码: *（其中 * 来自角色 admin 的隐含权限）")
                .hasFieldOrPropertyWithValue("code", "PERMISSION_ESCALATION_DENIED");

        verify(userMapper, never()).insert(any(User.class));
    }

    @Test
    @DisplayName("🔴 角色码→码：真 RoleService 走 role_permissions（DB 真值），且只按**传入租户**查角色行")
    void roleResolverReadsRolePermissionsScopedToTenant() {
        RoleMapper gateRoleMapper = mock(RoleMapper.class);
        RolePermissionMapper gateRolePermissionMapper = mock(RolePermissionMapper.class);
        PermissionMapper gatePermissionMapper = mock(PermissionMapper.class);
        RoleService realRoleService = new RoleService(gateRoleMapper, gatePermissionMapper,
                mock(UserRoleMapper.class), mock(UserMapper.class), gateRolePermissionMapper);

        when(gateRoleMapper.selectOne(any(LambdaQueryWrapper.class)))
                .thenReturn(Role.builder().id("role-fin").code("finance").tenantId(TENANT).build());
        when(gateRolePermissionMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(RolePermission.builder().roleId("role-fin").permissionId("p-1").deleted(0).build()));
        when(gatePermissionMapper.selectBatchIds(any()))
                .thenReturn(List.of(Permission.builder().id("p-1").code("finance:create").build()));

        assertThat(realRoleService.getEffectivePermissionCodesForRoleCode("finance", TENANT))
                .as("角色行存在 ⇒ 生效码取自 role_permissions（与运行时同一份口径）")
                .containsExactly("finance:create");

        // 跨租户不查：角色行查询必须带 tenant_id（拒绝文案之外，这是"不泄露他租户"的机械判据）
        @SuppressWarnings("unchecked")
        ArgumentCaptor<LambdaQueryWrapper<Role>> captor = ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        verify(gateRoleMapper).selectOne(captor.capture());
        assertThat(captor.getValue().getSqlSegment())
                .as("角色码 → 码只按传入租户解析（不跨租户查 ⇒ 不泄露他租户的角色/权限是否存在）")
                .contains("tenant_id")
                .contains("code");
    }

    @Test
    @DisplayName("🔴 角色隐含的码超界也拦（role 的 role_permissions 含操作者没有的码）")
    void roleImpliedCodesBeyondActor_areRejected() {
        authenticateEmployee(roleService, ACTOR, "employee:list", "employee:create");
        when(roleService.getEffectivePermissionCodesForRoleCode("finance", TENANT))
                .thenReturn(List.of("finance:view", "finance:create"));

        assertThatThrownBy(() -> userService.createUser(PHONE, "Init1234", "财务小王", "finance", "财务",
                null, TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("finance:create")
                .hasMessageContaining("来自角色 finance")
                .hasFieldOrPropertyWithValue("code", "PERMISSION_ESCALATION_DENIED");

        verify(userMapper, never()).insert(any(User.class));
    }

    @Test
    @DisplayName("🔴 fail-closed：操作者自身权限解析不出来（空集）⇒ 任何授予都拒绝")
    void unresolvableActorPermissions_failClosed() {
        authenticateEmployee(roleService, ACTOR);  // 空权限集

        assertThatThrownBy(() -> userService.createUser(PHONE, "Init1234", "空权限操作者", "operator", "客服",
                "[\"dashboard:view\"]", TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("dashboard:view")
                .hasFieldOrPropertyWithValue("code", "PERMISSION_ESCALATION_DENIED");

        verify(userMapper, never()).insert(any(User.class));
    }

    @Test
    @DisplayName("🔴 快照不是合法 JSON 数组 ⇒ fail-closed（按未知码处理，不静默落库）")
    void unparseableSnapshot_isRejected() {
        authenticateEmployee(roleService, ACTOR, "employee:list", "employee:create");

        assertThatThrownBy(() -> userService.createUser(PHONE, "Init1234", "脏快照", "operator", "客服",
                "dashboard:view,order:list", TENANT))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", "PERMISSION_ESCALATION_DENIED");

        verify(userMapper, never()).insert(any(User.class));
    }

    // ======================== 正向对照 + 既有护栏不回退 ========================

    @Test
    @DisplayName("✅ 正向对照：合法子集赋值成功，且快照**真的**落库（区分「正确拒绝」与「链路坏了」）")
    void legitimateSubsetAssignment_isAcceptedAndSnapshotPersisted() {
        authenticateEmployee(roleService, ACTOR, "employee:list", "employee:create", "dashboard:view");
        when(userMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);
        when(roleMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);
        when(roleService.getEffectivePermissionCodesForRoleCode("operator", TENANT))
                .thenReturn(List.of("dashboard:view"));
        when(userMapper.insert(any(User.class))).thenAnswer(invocation -> {
            User inserted = invocation.getArgument(0);
            inserted.setId("user-new");
            return 1;
        });

        User created = userService.createUser(PHONE, "Init1234", "新客服", "operator", "客服",
                "[\"dashboard:view\",\"employee:list\"]", TENANT);

        assertThat(created.getId()).isEqualTo("user-new");
        ArgumentCaptor<User> captor = ArgumentCaptor.forClass(User.class);
        verify(userMapper).insert(captor.capture());
        assertThat(captor.getValue().getPermissions())
                .as("快照式语义：勾选即落库（未被门禁改写）")
                .isEqualTo("[\"dashboard:view\",\"employee:list\"]");
    }

    @Test
    @DisplayName("✅ 既有护栏不回退：系统保留角色仍 422、通配码仍 422（⊆ 门禁不得取代它们）")
    void existingBlocks_stillApply() {
        authenticateEmployee(roleService, ACTOR, "*");

        assertThatThrownBy(() -> userService.createUser(PHONE, "Init1234", "保留角色", "super_admin", "管理员",
                null, TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("系统保留角色")
                .hasFieldOrPropertyWithValue("code", "VALIDATION_ERROR")
                .hasFieldOrPropertyWithValue("httpStatus", 422);

        assertThatThrownBy(() -> userService.createUser(PHONE, "Init1234", "通配码", "operator", "客服",
                "[\"*\"]", TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("通配权限")
                .hasFieldOrPropertyWithValue("code", "VALIDATION_ERROR")
                .hasFieldOrPropertyWithValue("httpStatus", 422);

        verify(userMapper, never()).insert(any(User.class));
    }

    // ======================== 三态：旁路身份 / 无操作者 ========================

    @Test
    @DisplayName("✅ 旁路身份（平台管理员 super_admin）不适用 ⊆ 判定（它本身就是全权限）")
    void privilegedIdentity_isExempt() {
        SecurityUser principal = new SecurityUser("platform-1", TENANT, "platform-admin",
                List.of("super_admin"), List.of(new SimpleGrantedAuthority("ROLE_super_admin")));
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(principal, "n/a", principal.getAuthorities()));
        when(userMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);
        when(userMapper.insert(any(User.class))).thenAnswer(invocation -> {
            User inserted = invocation.getArgument(0);
            inserted.setId("user-new");
            return 1;
        });

        User created = userService.createUser(PHONE, "Init1234", "租户管理员", "admin", "管理员",
                "[\"system:manage\"]", TENANT);

        assertThat(created.getId()).isEqualTo("user-new");
        verify(userMapper).insert(any(User.class));
    }

    @Test
    @DisplayName("✅ 无操作者（匿名）不适用 ⊆ 判定：公开注册引导建新租户首个管理员，不得被砍")
    void anonymousBootstrap_isExempt() {
        SecurityContextHolder.getContext().setAuthentication(new AnonymousAuthenticationToken(
                "anon-key", "anonymousUser", List.of(new SimpleGrantedAuthority("ROLE_ANONYMOUS"))));
        when(userMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);
        when(userMapper.insert(any(User.class))).thenAnswer(invocation -> {
            User inserted = invocation.getArgument(0);
            inserted.setId("user-new");
            return 1;
        });

        User created = userService.createUser(PHONE, "Init1234", "企业管理员", "admin", "管理员",
                null, TENANT);

        assertThat(created.getId()).isEqualTo("user-new");
        assertThat(created.getRole()).isEqualTo("admin");
    }

    // ======================== 取值纪律：不泄露跨租户信息 ========================

    @Test
    @DisplayName("🔴 角色码→码按**目标租户**解析（只查本租户）+ 拒绝文案只点名请求里出现过的码")
    void tenantScopedResolution_andNoCatalogueLeak() {
        authenticateEmployee(roleService, ACTOR, "employee:list", "employee:create");
        when(roleService.getEffectivePermissionCodesForRoleCode("customer_service", TENANT))
                .thenReturn(List.of("after_sales:view"));

        assertThatThrownBy(() -> userService.createUser(PHONE, "Init1234", "客服小李", "customer_service", "客服",
                null, TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> {
                    String message = thrown.getMessage();
                    assertThat(message).contains("after_sales:view");
                    // 只回显请求里出现过的码，不回答「目录里有没有这个码」（跨租户信息不由此泄露）
                    assertThat(message).doesNotContain("不存在").doesNotContain("未注册").doesNotContain("租户");
                });

        // 角色码只按目标租户解析：不得出现「换个租户再查一次」的路径
        verify(roleService).getEffectivePermissionCodesForRoleCode(eq("customer_service"), eq(TENANT));
        verify(roleService).getUserPermissions(ACTOR);
    }

    // ======================== helpers ========================

    private UserService userServiceWith(RoleService gateRoleService) {
        return new UserService(userMapper, roleMapper, userRoleMapper, new PermissionInterceptor(gateRoleService));
    }

    private void authenticateEmployee(RoleService gateRoleService, String actorId, String... permissions) {
        SecurityUser principal = new SecurityUser(actorId, TENANT, "13800138000", List.of("operator"),
                List.of(new SimpleGrantedAuthority("ROLE_operator")));
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(principal, "n/a", principal.getAuthorities()));
        when(gateRoleService.getUserPermissions(actorId)).thenReturn(List.of(permissions));
    }
}
