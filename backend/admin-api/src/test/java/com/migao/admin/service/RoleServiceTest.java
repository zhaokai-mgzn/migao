// case_ids: HR-004, HR-005, HR-006, HR-011
package com.migao.admin.service;

import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.Permission;
import com.migao.admin.entity.Role;
import com.migao.admin.entity.User;
import com.migao.admin.entity.UserRole;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.PermissionMapper;
import com.migao.admin.mapper.RoleMapper;
import com.migao.admin.mapper.RolePermissionMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.mapper.UserRoleMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
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
    private RolePermissionMapper rolePermissionMapper;

    @Mock
    private UserMapper userMapper;

    private Role testRole;
    private UserRole testUserRole;

    /**
     * 回退路径上 {@code operator} **应当**取到的全部权限码（= 种子矩阵的 operator 默认权限，逐码点名）。
     *
     * <p>🔴 issue #5683：回退路径（无 {@code role_permissions} 记录 / 无 {@code users.permissions}
     * 快照）上的账号**实际取到的权限集合**必须可判、且与种子矩阵对齐 —— 否则同一个岗位会长出两种行为
     * （有快照的账号走种子、无快照的历史账号走本回退），显形为**真实 403** 与**菜单凭空消失**。
     * 本清单是它的**行为面**判据（走真实服务，不靠读代码推断）；静态面
     * （{@code 回退 ⊆ 种子} 逐角色码穷举 + 差异具名登记、只许缩短 + 授权变更 census）在
     * {@code tests/unit_ci_workflows/test_agent_permission_parity.py} 的判据 14。两层互相独立。
     * ⚠️ 判据 14 **不主张**「两处必须逐值相等」—— 差异是否应存在是**授权决定**；本清单钉的是
     * #5683 这次**已批准**的取值。</p>
     */
    private static final List<String> OPERATOR_FALLBACK_SEED_PARITY = List.of(
            "dashboard:view",
            "order:list", "order:detail", "order:refund", "order:update", "order:create",
            "product:list", "product:create", "product:category", "product:category:view",
            "processing:manage", "production:view",
            "processing:view", "processing:update",   // issue #5683 补齐（此前回退缺这 2 个）
            "inbound:view", "inbound:create",         // issue #5683 补齐（此前回退缺这 2 个）
            "customer:view", "customer:create",
            "finance:view", "finance:create",
            "agent:session", "agent:session:manage",
            "employee:list",
            "after_sales:view", "knowledge:view",
            "production:execute");   // issue #5699 的 I4：生产执行**写**码（四个真写端点的守卫码）

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
        Role result = roleService.createRole("运营", "operator", "运营人员", 1L, List.of());

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
        assertThatThrownBy(() -> roleService.createRole("管理员2", "admin", "重复角色", 1L, null))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("角色代码已存在");
    }


    @Test
    @DisplayName("创建角色失败 - 编码被历史（已删除）角色占用（唯一索引无 deleted 条件，逻辑删除后重建同 code 曾 500）")
    void createRole_CodeOccupiedByDeleted() {
        // given
        Role deletedRole = Role.builder()
                .id("role-del")
                .code("stock_keeper")
                .tenantId(1L)
                .deleted(1)
                .build();
        when(roleMapper.selectOne(any(LambdaQueryWrapper.class)))
                .thenReturn(null)           // 第一次（deleted=0）无活跃记录
                .thenReturn(deletedRole);   // 第二次（deleted=1）历史占用

        // when & then
        assertThatThrownBy(() -> roleService.createRole("库管", "stock_keeper", "测试", 1L, null))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("历史角色");
    }

    // ======================== updateRole 测试 ========================

    @Test
    @DisplayName("更新角色成功")
    void updateRole_Success() {
        // given
        when(roleMapper.selectById("role-001")).thenReturn(testRole);
        when(roleMapper.updateById(any(Role.class))).thenReturn(1);

        // when
        Role result = roleService.updateRole("role-001", "超级管理员", "更新后的描述", null);

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
        Role result = roleService.updateRole("role-001", "新名称", null, null);

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
        assertThatThrownBy(() -> roleService.updateRole("nonexistent", "新名称", null, null))
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
    @DisplayName("为角色分配权限 - 全量替换 role_permissions 落库")
    void assignPermissions_Success() {
        // given
        when(roleMapper.selectById("role-001")).thenReturn(testRole);
        when(rolePermissionMapper.delete(any(LambdaQueryWrapper.class))).thenReturn(1);
        Permission perm1 = Permission.builder().id("perm-001").code("employee:list").build();
        Permission perm2 = Permission.builder().id("perm-002").code("employee:create").build();
        when(permissionMapper.selectBatchIds(List.of("perm-001", "perm-002")))
                .thenReturn(List.of(perm1, perm2));

        // when
        roleService.assignPermissions("role-001", List.of("perm-001", "perm-002"), 1L);

        // then：先清空旧关联，再插入新关联（仅存在的权限）
        verify(rolePermissionMapper).delete(any(LambdaQueryWrapper.class));
        @SuppressWarnings("unchecked")
        ArgumentCaptor<com.migao.admin.entity.RolePermission> captor =
                ArgumentCaptor.forClass(com.migao.admin.entity.RolePermission.class);
        verify(rolePermissionMapper, times(2)).insert(captor.capture());
        List<String> insertedIds = captor.getAllValues().stream()
                .map(com.migao.admin.entity.RolePermission::getPermissionId)
                .collect(java.util.stream.Collectors.toList());
        assertThat(insertedIds).containsExactlyInAnyOrder("perm-001", "perm-002");
    }

    @Test
    @DisplayName("为角色分配权限 - 空列表清空关联")
    void assignPermissions_ClearAll() {
        // given
        when(roleMapper.selectById("role-001")).thenReturn(testRole);
        when(rolePermissionMapper.delete(any(LambdaQueryWrapper.class))).thenReturn(2);

        // when
        roleService.assignPermissions("role-001", List.of(), 1L);

        // then：只清空，不插入
        verify(rolePermissionMapper).delete(any(LambdaQueryWrapper.class));
        verify(rolePermissionMapper, never()).insert(any(com.migao.admin.entity.RolePermission.class));
    }

    @Test
    @DisplayName("为角色分配权限失败 - 角色不存在")
    void assignPermissions_RoleNotFound() {
        // given
        when(roleMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> roleService.assignPermissions("nonexistent", List.of("perm-001"), 1L))
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

    // ======================== getUserPermissions 测试 ========================

    @Test
    @DisplayName("getUserPermissions: admin 角色用户返回 *")
    void getUserPermissions_AdminReturnsWildcard() {
        // given
        when(userRoleMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(UserRole.builder().id("ur-1").roleId("role-admin").userId("u1").tenantId(1L).deleted(0).build()));
        Role adminRole = Role.builder().id("role-admin").code("admin").tenantId(1L).deleted(0).build();
        when(roleMapper.selectBatchIds(List.of("role-admin"))).thenReturn(List.of(adminRole));

        // when
        List<String> result = roleService.getUserPermissions("u1");

        // then
        assertThat(result).containsExactly("*");
    }

    @Test
    @DisplayName("getUserPermissions: operator 角色获得业务常用权限（不含 system:manage 系统管理）")
    void getUserPermissions_OperatorGetsAllCommonPermissions() {
        // given
        when(userRoleMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(UserRole.builder().id("ur-1").roleId("role-op").userId("u2").tenantId(1L).deleted(0).build()));
        Role opRole = Role.builder().id("role-op").code("operator").tenantId(1L).deleted(0).build();
        when(roleMapper.selectBatchIds(List.of("role-op"))).thenReturn(List.of(opRole));
        // userMapper query for User.permissions merge
        User user = new User();
        user.setId("u2");
        user.setPermissions(null);
        when(userMapper.selectById("u2")).thenReturn(user);

        // when
        List<String> result = roleService.getUserPermissions("u2");

        // then: 11 个业务权限码（员工管理保留；系统管理归 admin 专属；#3081 快捷回复权限已移除）
        assertThat(result).contains(
                "dashboard:view",
                "order:list", "order:detail", "order:refund",
                "product:list", "product:create", "product:category",
                "processing:manage",
                "customer:view", "finance:view",
                "agent:session",
                "employee:list"
        );
        // #3081: agent:quickreply 权限已随快捷回复功能下线移除
        assertThat(result).doesNotContain("agent:quickreply");
        // 越权守卫：operator 不得持有 system:manage（角色管理/系统设置归 admin）
        assertThat(result).doesNotContain("system:manage");
    }

    @Test
    @DisplayName("getUserPermissions: product_manager 只获得商品和加工权限")
    void getUserPermissions_ProductManagerSubset() {
        // given
        when(userRoleMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(UserRole.builder().id("ur-1").roleId("role-pm").userId("u3").tenantId(1L).deleted(0).build()));
        Role pmRole = Role.builder().id("role-pm").code("product_manager").tenantId(1L).deleted(0).build();
        when(roleMapper.selectBatchIds(List.of("role-pm"))).thenReturn(List.of(pmRole));
        User user = new User();
        user.setId("u3");
        user.setPermissions(null);
        when(userMapper.selectById("u3")).thenReturn(user);

        // when
        List<String> result = roleService.getUserPermissions("u3");

        // then
        assertThat(result).contains("dashboard:view", "product:list", "product:create", "product:category", "processing:manage");
        assertThat(result).doesNotContain("order:list", "customer:view", "employee:list");
    }

    @Test
    @DisplayName("getUserPermissions: knowledge_editor 获得 dashboard + product:list")
    void getUserPermissions_KnowledgeEditorMinimal() {
        // given
        when(userRoleMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(UserRole.builder().id("ur-1").roleId("role-ke").userId("u4").tenantId(1L).deleted(0).build()));
        Role keRole = Role.builder().id("role-ke").code("knowledge_editor").tenantId(1L).deleted(0).build();
        when(roleMapper.selectBatchIds(List.of("role-ke"))).thenReturn(List.of(keRole));
        User user = new User();
        user.setId("u4");
        user.setPermissions(null);
        when(userMapper.selectById("u4")).thenReturn(user);

        // when
        List<String> result = roleService.getUserPermissions("u4");

        // then
        assertThat(result).contains("dashboard:view", "product:list");
        assertThat(result).hasSize(2);
    }

    @Test
    @DisplayName("getUserPermissions: admin 有 User.permissions 时仍返回 *")
    void getUserPermissions_AdminWithUserPermissionsStillReturnsWildcard() {
        // given: admin 角色的用户，User.permissions 字段有旧数据
        when(userRoleMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(UserRole.builder().id("ur-1").roleId("role-admin").userId("u5").tenantId(1L).deleted(0).build()));
        Role adminRole = Role.builder().id("role-admin").code("admin").tenantId(1L).deleted(0).build();
        when(roleMapper.selectBatchIds(List.of("role-admin"))).thenReturn(List.of(adminRole));
        // 关键：admin 用户即使有 User.permissions，也返回 *
        // 此测试验证 Bug Fix — admin 不应因 User.permissions 而降级

        // when
        List<String> result = roleService.getUserPermissions("u5");

        // then: 必须返回 *，不能返回受限权限
        assertThat(result).containsExactly("*");
    }

    @Test
    @DisplayName("getUserPermissions: 无 user_roles 时从 User.role 字段获取")
    void getUserPermissions_NoUserRoles_FallbackToUserRoleField() {
        // given
        when(userRoleMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
        User user = new User();
        user.setId("u6");
        user.setRole("product_manager");
        user.setPermissions(null);
        when(userMapper.selectById("u6")).thenReturn(user);

        // when
        List<String> result = roleService.getUserPermissions("u6");

        // then
        assertThat(result).contains("dashboard:view", "product:list", "processing:manage");
        assertThat(result).doesNotContain("order:list", "employee:list");
    }

    @Test
    @DisplayName("getUserPermissions: 有 users.permissions 快照（岗位权限体系 #2969）→ 直接以快照为准")
    void getUserPermissions_SnapshotFirst() {
        // given: operator 角色 + User.permissions 快照（员工管理保存时的勾选，含岗位默认权限预填）
        // 快照式短路：无需 stub userRoleMapper/roleMapper（快照优先，角色权限不再合并）
        User user = new User();
        user.setId("u7");
        // 快照：员工页保存的最终勾选（岗位默认权限 ∪ 自定义）
        user.setPermissions("[\"knowledge:manage\",\"report:view\"]");
        when(userMapper.selectById("u7")).thenReturn(user);

        // when
        List<String> result = roleService.getUserPermissions("u7");

        // then: 快照式 —— 员工权限 = 保存勾选，不再合并岗位角色硬编码（与岗位脱钩 #2969）
        assertThat(result).containsExactlyInAnyOrder("knowledge:manage", "report:view");
        assertThat(result).doesNotContain("dashboard:view", "order:list", "product:list");
    }

    @Test
    @DisplayName("getUserPermissions: 无 users.permissions 快照（历史员工）→ 回退角色权限逻辑兼容存量")
    void getUserPermissions_NoSnapshot_FallbackToRolePermissions() {
        // given: operator 角色，User.permissions 为空（历史员工未在员工页配置快照）
        when(userRoleMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(UserRole.builder().id("ur-1").roleId("role-op").userId("u7b").tenantId(1L).deleted(0).build()));
        Role opRole = Role.builder().id("role-op").code("operator").tenantId(1L).deleted(0).build();
        when(roleMapper.selectBatchIds(List.of("role-op"))).thenReturn(List.of(opRole));
        User user = new User();
        user.setId("u7b");
        user.setPermissions(null);
        when(userMapper.selectById("u7b")).thenReturn(user);

        // when
        List<String> result = roleService.getUserPermissions("u7b");

        // then: 兼容存量 —— 角色权限（operator 硬编码映射）
        assertThat(result).contains("dashboard:view", "order:list", "product:list");
    }

    @Test
    @DisplayName("getUserPermissions: admin User.role 字段返回 *")
    void getUserPermissions_AdminUserRoleFieldReturnsWildcard() {
        // given: User.role 是 admin（快照式短路：直接识别 admin 返回 *，无需 user_roles stub）
        User user = new User();
        user.setId("u8");
        user.setRole("admin");
        user.setPermissions("[\"product:list\"]"); // 旧数据
        when(userMapper.selectById("u8")).thenReturn(user);

        // when
        List<String> result = roleService.getUserPermissions("u8");

        // then: admin 必须返回 *，忽略 User.permissions
        assertThat(result).containsExactly("*");
    }

    @Test
    @DisplayName("getUserPermissions: 无角色无 User.role 返回空")
    void getUserPermissions_NoRolesEmpty() {
        // given
        when(userRoleMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
        User user = new User();
        user.setId("u9");
        user.setRole(null);
        user.setPermissions(null);
        when(userMapper.selectById("u9")).thenReturn(user);

        // when
        List<String> result = roleService.getUserPermissions("u9");

        // then
        assertThat(result).isEmpty();
    }

    // ======================== role_permissions 真实落库生效 ========================

    @Test
    @DisplayName("getUserPermissions: 自定义角色经 role_permissions 获得勾选权限（角色授权真实生效）")
    void getUserPermissions_CustomRoleFromRolePermissions() {
        // given: 自定义角色 custom_staff 分配了 employee:list + dashboard:view
        when(userRoleMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(UserRole.builder().id("ur-1").roleId("role-cs").userId("u10").tenantId(1L).deleted(0).build()));
        Role csRole = Role.builder().id("role-cs").code("custom_staff").tenantId(1L).deleted(0).build();
        when(roleMapper.selectBatchIds(List.of("role-cs"))).thenReturn(List.of(csRole));
        // role_permissions 关联存在 → 权限码来自关联表（而非硬编码回退）
        when(rolePermissionMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(
                        com.migao.admin.entity.RolePermission.builder().roleId("role-cs").permissionId("perm-1").deleted(0).build(),
                        com.migao.admin.entity.RolePermission.builder().roleId("role-cs").permissionId("perm-2").deleted(0).build()));
        when(permissionMapper.selectBatchIds(List.of("perm-1", "perm-2")))
                .thenReturn(List.of(
                        Permission.builder().id("perm-1").code("dashboard:view").build(),
                        Permission.builder().id("perm-2").code("employee:list").build()));
        User user = new User();
        user.setId("u10");
        user.setPermissions(null);
        when(userMapper.selectById("u10")).thenReturn(user);

        // when
        List<String> result = roleService.getUserPermissions("u10");

        // then：恰好是角色管理勾选的权限，不含 operator 等硬编码集合
        assertThat(result).containsExactlyInAnyOrder("dashboard:view", "employee:list");
        assertThat(result).doesNotContain("order:list", "system:manage", "product:list");
    }

    // ============ 回退路径（无权限快照 / 无岗位权限行）的**行为**判据（issue #5683）============
    // 病灶：同一个岗位的默认权限写在两处 —— 种子矩阵 `RegistrationService` 与硬编码回退
    // `RoleService.getPermissionCodesForRole` —— 两处靠**注释**声称同步，实测已分叉（operator 少 4 码，
    // 且注释当时逐字写着「与种子矩阵逐值同步」）。本段直接调用真实服务，把回退路径上账号**实际取到**
    // 的权限集合逐码点名钉住（`tenantId = null` ⇒ 跳过角色行查询 ⇒ 走的正是运行时那条回退）。

    @Test
    @DisplayName("回退路径: operator 取到的权限集合（#5683 已批准的取值，逐码点名，不以集合大小充数）")
    void fallbackOperator_MatchesSeedMatrixExactly() {
        // when：tenantId=null ⇒ 不查角色行 ⇒ 纯回退路径（运行时路径 (b)/(c) 的同一份实现）
        List<String> result = roleService.getEffectivePermissionCodesForRoleCode("operator", null);

        // then：**逐码点名**（`containsExactlyInAnyOrder` = 多一个 / 少一个都红）
        assertThat(result).containsExactlyInAnyOrderElementsOf(OPERATOR_FALLBACK_SEED_PARITY);
        // 越权守卫不因补码而松：回退同样不得给 system:manage / system:view（admin 专属）
        assertThat(result).doesNotContain("system:manage", "system:view");
    }

    @Test
    @DisplayName("回退路径: 无 user_roles 的历史账号（User.role=operator）拿到同一份集合")
    void fallbackLegacyAccount_NoUserRoles_GetsSeedParityForOperator() {
        // given：历史账号形态 —— 没有 user_roles 行、没有 users.permissions 快照（#5683 的受害者人群）
        when(userRoleMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
        User legacy = new User();
        legacy.setId("u-op-legacy");
        legacy.setRole("operator");
        legacy.setPermissions(null);
        when(userMapper.selectById("u-op-legacy")).thenReturn(legacy);

        // when
        List<String> result = roleService.getUserPermissions("u-op-legacy");

        // then：与纯回退路径同一份集合（两条运行时路径不得分叉）
        assertThat(result).containsExactlyInAnyOrderElementsOf(OPERATOR_FALLBACK_SEED_PARITY);
    }

    @Test
    @DisplayName("回退路径: product_manager（历史岗位码，不在种子矩阵）补上 processing:view")
    void fallbackProductManager_AddsProcessingViewOnly() {
        // 性质与 operator **不同**：本岗位**不在种子矩阵里**（POC 期历史角色码，回退表是它**唯一**的
        // 一份默认定义）⇒ operator 是「回退落后于种子」，本岗位是「只有一份定义、缺自己链上的读码」。
        List<String> result = roleService.getEffectivePermissionCodesForRoleCode("product_manager", null);

        assertThat(result).containsExactlyInAnyOrder(
                "dashboard:view",
                "product:list", "product:create", "product:category", "product:category:view",
                "processing:manage", "production:view",
                // issue #5683：它持节点码 `processing:manage`（看得见「智能派单」）却不持该页第一屏
                // 读码 ⇒ 点进去 403；本码即为此补。
                "processing:view");
        // 有意不给：订单 / 客户 / 员工面 —— 补它们属**另一次**授权放宽，超出 #5683 已批准范围。
        assertThat(result).doesNotContain("order:list", "customer:view", "employee:list");
    }

    @Test
    @DisplayName("回退路径: 客服/销售/财务也取到与种子一致的全集（#5683 裁定补齐，逐码点名）")
    void fallbackCustomerServiceSalesFinance_MatchSeedMatrixExactly() {
        // 补码前：这三个角色在回退 switch 里**没有 `case`** ⇒ 落 `default -> List.of()` ⇒ **空表**
        // ⇒ 持这些角色码且无权限快照的历史账号**零权限**（连「经营看板」都看不见）。
        // #5683 经人类裁定补齐（复核结论 (b) 类：原登记的主题是「写码」、且自述范围是 #5246 那一单的
        // 可见性变更范围 —— 它没有对「这三个角色在回退里整体为空」作出决定 ⇒ 该面属**未覆盖**）。
        // 🔴 码集逐字取自 `RegistrationService` 的对应默认列表（不增不减）；逐码点名，不以集合大小充数。
        assertThat(roleService.getEffectivePermissionCodesForRoleCode("customer_service", null))
                .containsExactlyInAnyOrder(
                        "dashboard:view", "order:list", "order:detail", "customer:view", "agent:session",
                        "processing:view", "inbound:view", "after_sales:view", "knowledge:view",
                        "agent:session:manage",
                        "production:execute");   // issue #5699 的 I4
        assertThat(roleService.getEffectivePermissionCodesForRoleCode("sales", null))
                .containsExactlyInAnyOrder(
                        "dashboard:view", "product:list", "order:list", "order:detail", "customer:view",
                        "processing:view", "inbound:view",
                        "production:execute");   // issue #5699 的 I4
        assertThat(roleService.getEffectivePermissionCodesForRoleCode("finance", null))
                .containsExactlyInAnyOrder(
                        "dashboard:view", "order:list", "order:detail", "finance:view",
                        "processing:view", "inbound:view", "finance:create",
                        "production:execute");   // issue #5699 的 I4
    }

    @Test
    @DisplayName("回退路径: 种子的五个岗位码在回退里都**非空** ⇒ 「整角色空表」形态已消灭（#5683）")
    void fallbackEverySeededRoleHasANonEmptyCase() {
        // 这是 #5683 判据 14 ① 在**行为面**的对应物：`∅ ⊆ 种子` 恒真 ⇒ 只判「回退不得更宽」会全绿，
        // 而该角色在回退路径上零权限。补码后每个种子岗位码都必须取到非空集合。
        for (String role : List.of("admin", "customer_service", "operator", "sales", "finance",
                "product_manager", "knowledge_editor")) {
            assertThat(roleService.getEffectivePermissionCodesForRoleCode(role, null))
                    .as("回退路径 `%s` 不得为空表（#5683：种子里有的每个岗位码都必须在回退里有 case）", role)
                    .isNotEmpty();
        }
    }

    @Test
    @DisplayName("getRolePermissions: 角色详情返回 role_permissions 关联的权限列表")
    void getRolePermissions_ReturnsRolePermissionRows() {
        // given
        when(roleMapper.selectById("role-cs")).thenReturn(
                Role.builder().id("role-cs").code("custom_staff").tenantId(1L).deleted(0).build());
        when(rolePermissionMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(
                        com.migao.admin.entity.RolePermission.builder().roleId("role-cs").permissionId("perm-1").deleted(0).build()));
        when(permissionMapper.selectBatchIds(List.of("perm-1")))
                .thenReturn(List.of(Permission.builder().id("perm-1").code("employee:list").build()));

        // when
        List<Permission> result = roleService.getRolePermissions("role-cs");

        // then
        assertThat(result).hasSize(1);
        assertThat(result.get(0).getCode()).isEqualTo("employee:list");
    }
}
