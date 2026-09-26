// case_ids: AU-007, AU-008
package com.migao.admin.service;

import com.migao.admin.entity.User;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.RoleMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.mapper.UserRoleMapper;
import com.migao.admin.security.PermissionInterceptor;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.dao.DuplicateKeyException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 员工账号管理（用户名 + 初始密码）单元测试 —— issue #5485 AU-007 / AU-008。
 *
 * <p>两条业务真值：
 * <ul>
 *   <li><b>AU-007</b> 管理员设「用户名 + 初始密码」⇒ 员工可用该凭据登录（写面：转小写 + 格式校验）；
 *       同一企业内用户名重复 ⇒ <b>422 明确文案</b>（不是数据库异常裸抛 500）且提示换一个；</li>
 *   <li><b>AU-008</b> 不同企业可以用相同用户名 —— 唯一性校验**必须带租户条件**
 *       （把 {@code tenantId} 那一项删掉 ⇒ 用户名的租户条件判据必红），
 *       并发下由 {@code uk_users_tenant_username} 部分唯一索引兜底（冲突转 422）。</li>
 * </ul>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("员工账号管理（用户名）")
class AdminUserUsernameTest {

    @InjectMocks
    private UserService userService;

    @Mock
    private UserMapper userMapper;
    @Mock
    private RoleMapper roleMapper;
    @Mock
    private UserRoleMapper userRoleMapper;

    /**
     * ⊆ 门禁替身（issue #4104）：{@code UserService} 的授权写面依赖它；本类测的是用户名/初始密码
     * ⇒ 用替身（真实判定由 {@code EmployeePermissionGrantGateTest} 覆盖）。
     * ⚠️ 不声明它 ⇒ {@code @InjectMocks} 注入 null ⇒ NPE（**不是**静默放行）。
     */
    @Mock
    private PermissionInterceptor permissionInterceptor;

    @BeforeEach
    void setUp() {
        // LambdaQueryWrapper 解析 User::getXxx 需要 TableInfo 缓存（同 UserServiceTest 的工装）
        MybatisConfiguration configuration = new MybatisConfiguration();
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), User.class);
    }

    /**
     * 抓「用户名查重」那一次 selectOne：createUser 会先按**手机号**查重、再按**用户名**查重，
     * 故按 SQL 片段区分（不是靠调用序号 —— 序号一改就静默抓错对象）。
     */
    @SuppressWarnings("unchecked")
    private LambdaQueryWrapper<User> capturedUsernameQuery() {
        ArgumentCaptor<LambdaQueryWrapper<User>> captor = ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        verify(userMapper, org.mockito.Mockito.atLeastOnce()).selectOne(captor.capture());
        return captor.getAllValues().stream()
                .filter(w -> w.getSqlSegment().contains("username"))
                .reduce((first, second) -> second)
                .orElseThrow(() -> new AssertionError("没有发生「按用户名查重」的查询 —— 租户内唯一性校验缺失"));
    }

    /** 只让**按 column 查重**的那一次命中已有行（另一列查重返回 null，模拟真实库）。 */
    private void givenExistingByColumn(String column, User existing) {
        when(userMapper.selectOne(any())).thenAnswer(inv -> {
            LambdaQueryWrapper<User> wrapper = inv.getArgument(0);
            return wrapper.getSqlSegment().contains(column) ? existing : null;
        });
    }

    // ======================== AU-007 ========================

    @Test
    @DisplayName("AU-007 创建员工：username + 初始密码 ⇒ 转小写、置强制改密、按**租户内**查重")
    void createUser_withUsername_normalizesAndForcesChange() {
        when(userMapper.selectOne(any())).thenReturn(null);

        User created = userService.createUser("13800000001", "Init1234", "张三", "operator", "客服",
                null, 1L, "ZhangSan", true);

        assertThat(created.getUsername()).as("写入与登录统一转小写").isEqualTo("zhangsan");
        assertThat(created.getMustChangePassword()).as("管理员设的密码是初始密码 ⇒ 强制改密").isTrue();

        String sql = capturedUsernameQuery().getSqlSegment();
        assertThat(sql)
                .as("唯一性校验必须落在租户内（I3：不同企业可同名）")
                .contains("username")
                .contains("tenant_id");
    }

    @Test
    @DisplayName("AU-007 创建员工：username 格式不合规 ⇒ 422 明确文案（提示规则），不写库")
    void createUser_invalidUsername_rejectedWith422() {
        assertThatThrownBy(() -> userService.createUser("13800000002", "Init1234", "李四", "operator", "客服",
                null, 1L, "ZH", true))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", "VALIDATION_ERROR")
                .hasFieldOrPropertyWithValue("httpStatus", 422)
                .hasMessageContaining("用户名不合法");

        verify(userMapper, never()).insert(any(User.class));
    }

    @Test
    @DisplayName("AU-007 本企业内用户名重复 ⇒ 422 明确文案（提示换一个），不是 500")
    void createUser_duplicateInSameTenant_rejectedWith422() {
        User existing = User.builder().id("other-user").tenantId(1L).username("zhangsan").build();
        givenExistingByColumn("username", existing);

        assertThatThrownBy(() -> userService.createUser("13800000003", "Init1234", "王五", "operator", "客服",
                null, 1L, "zhangsan", true))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", "VALIDATION_ERROR")
                .hasFieldOrPropertyWithValue("httpStatus", 422)
                .hasMessageContaining("已被占用")
                .hasMessageContaining("请换一个");

        verify(userMapper, never()).insert(any(User.class));
    }

    @Test
    @DisplayName("AU-007 并发兜底：唯一索引冲突（DuplicateKeyException）⇒ 转 422，不裸抛 500")
    void createUser_uniqueIndexRace_convertedTo422() {
        when(userMapper.selectOne(any())).thenReturn(null);
        when(userMapper.insert(any(User.class))).thenThrow(new DuplicateKeyException("uk_users_tenant_username"));

        assertThatThrownBy(() -> userService.createUser("13800000004", "Init1234", "赵六", "operator", "客服",
                null, 1L, "zhangsan", true))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", "VALIDATION_ERROR")
                .hasFieldOrPropertyWithValue("httpStatus", 422)
                .hasMessageContaining("已被占用");
    }

    @Test
    @DisplayName("AU-007 重置密码 ⇒ 强制改密 = 是（管理员知道这个密码，它只是初始密码）")
    void resetPassword_marksMustChange() {
        User existing = User.builder().id("user-001").tenantId(1L).phone("13800138000")
                .username("zhangsan").mustChangePassword(false).build();
        when(userMapper.selectById("user-001")).thenReturn(existing);

        String defaultPassword = userService.resetPassword("user-001");

        assertThat(defaultPassword).as("默认密码仍是手机号后 6 位（口径未变）").isEqualTo("138000");
        ArgumentCaptor<User> captor = ArgumentCaptor.forClass(User.class);
        verify(userMapper).updateById(captor.capture());
        assertThat(captor.getValue().getMustChangePassword()).isTrue();
    }

    @Test
    @DisplayName("AU-007 管理员改密码（编辑员工时下发 password）同样置强制改密")
    void changePassword_byAdmin_marksMustChange() {
        User existing = User.builder().id("user-001").tenantId(1L).phone("13800138000").build();
        when(userMapper.selectById("user-001")).thenReturn(existing);

        userService.changePassword("user-001", "NewPass123", true);

        ArgumentCaptor<User> captor = ArgumentCaptor.forClass(User.class);
        verify(userMapper).updateById(captor.capture());
        assertThat(captor.getValue().getMustChangePassword()).isTrue();
    }

    // ======================== AU-008 ========================

    @Test
    @DisplayName("AU-008 另一企业用同名 ⇒ 允许（查重带自己的 tenantId，命中不了别家的 zhangsan）")
    void createUser_sameUsernameInAnotherTenant_allowed() {
        // 本租户（2）下没有同名 ⇒ selectOne 返回 null（= 别家租户那一行不在本查询的结果集里）
        when(userMapper.selectOne(any())).thenReturn(null);

        User created = userService.createUser("13800000005", "Init1234", "张三（乙公司）", "operator", "客服",
                null, 2L, "zhangsan", true);

        assertThat(created.getUsername()).isEqualTo("zhangsan");
        String sql = capturedUsernameQuery().getSqlSegment();
        assertThat(sql)
                .as("查重必须同时含 username 与 tenant_id —— 删掉租户条件会变成全球唯一（AU-008 必红）")
                .contains("username")
                .contains("tenant_id");
    }

    @Test
    @DisplayName("AU-008 改自己的用户名：查重排除自己（否则改不动）")
    void updateUser_usernameExcludesSelf() {
        User existing = User.builder().id("user-001").tenantId(1L).phone("13800138000")
                .username("zhangsan").role("operator").status("active").build();
        when(userMapper.selectById("user-001")).thenReturn(existing);
        // 命中自己那一行 ⇒ 因为排除自己，不得报重复
        when(userMapper.selectOne(any())).thenReturn(existing);

        User updated = userService.updateUser("user-001", null, null, null, null, null, null, "zhangsan-new");

        assertThat(updated.getUsername()).isEqualTo("zhangsan-new");
        verify(userMapper).updateById(any(User.class));
    }

    @Test
    @DisplayName("AU-008 改成别家租户已占用的用户名（本租户没有）⇒ 允许；本租户被别人占用 ⇒ 422")
    void updateUser_usernameConflictScopeIsTenantLocal() {
        User mine = User.builder().id("user-001").tenantId(1L).phone("13800138000")
                .username("zhangsan").role("operator").status("active").build();
        when(userMapper.selectById("user-001")).thenReturn(mine);

        // ① 本租户无人占用 ⇒ 通过
        when(userMapper.selectOne(any())).thenReturn(null);
        assertThat(userService.updateUser("user-001", null, null, null, null, null, null, "zhangsan")
                .getUsername()).isEqualTo("zhangsan");

        // ② 本租户被**别人**占用 ⇒ 422
        User other = User.builder().id("user-999").tenantId(1L).username("zhangsan").build();
        when(userMapper.selectOne(any())).thenReturn(other);
        assertThatThrownBy(() -> userService.updateUser(
                "user-001", null, null, null, null, null, null, "zhangsan"))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("httpStatus", 422)
                .hasMessageContaining("已被占用");
    }

    @Test
    @DisplayName("AU-008 不传 username ⇒ 不修改（null 语义，不误清空已有用户名）")
    void updateUser_usernameNull_meansUnchanged() {
        User existing = User.builder().id("user-001").tenantId(1L).phone("13800138000")
                .username("zhangsan").role("operator").status("active").build();
        when(userMapper.selectById("user-001")).thenReturn(existing);

        User updated = userService.updateUser("user-001", "新昵称", null, null, null, null, null, null);

        assertThat(updated.getUsername()).as("null = 不修改").isEqualTo("zhangsan");
        verify(userMapper, never()).selectOne(any());
    }
}