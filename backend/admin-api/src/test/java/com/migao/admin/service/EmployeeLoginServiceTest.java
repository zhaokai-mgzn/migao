// case_ids: AU-001, AU-002, AU-003, AU-010
package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.LoginResponse;
import com.migao.admin.entity.Tenant;
import com.migao.admin.entity.User;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.PlatformAdminMapper;
import com.migao.admin.mapper.TenantAiConfigMapper;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.mapper.UserIdentityMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.security.JwtTokenProvider;
import com.migao.admin.security.LoginFailureGuard;
import com.migao.admin.support.LoginIdentifiers;
import jakarta.servlet.http.HttpServletResponse;
import org.apache.ibatis.annotations.Select;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.util.ReflectionTestUtils;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 员工登录（{@code <username>@<tenantCode>} + 密码）单元测试 —— issue #5485。
 *
 * <p>覆盖：
 * <ul>
 *   <li><b>AU-001</b> 成功签发（tenantCode → tenant_id → 该租户的用户）；</li>
 *   <li><b>AU-002</b> 不变式 <b>I1/I3</b>：A/B 两企业同名员工，各自凭据只解析到自己企业 ——
 *       既验行为（mock 的 mapper 按 (tenantId, username) 命中），也验**查询本身带租户条件**
 *       （反射读 {@code @Select} 的 SQL 文本：删掉 {@code tenant_id = #{tenantId}} ⇒ 本判据必红）；</li>
 *   <li><b>AU-003</b> 反枚举：企业编码不存在 / 用户名不存在 / 密码错误 / 状态非 active
 *       ⇒ **同一状态码 + 同一文案**；</li>
 *   <li><b>AU-010</b> 存量员工（{@code username IS NULL}）无法用员工登录。</li>
 * </ul>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("员工登录（用户名@企业编码 + 密码）")
class EmployeeLoginServiceTest {

    @InjectMocks
    private AuthService authService;

    @Mock
    private UserService userService;
    @Mock
    private RoleService roleService;
    @Mock
    private WechatService wechatService;
    @Mock
    private SmsService smsService;
    @Mock
    private JwtTokenProvider jwtTokenProvider;
    @Mock
    private PasswordEncoder passwordEncoder;
    @Mock
    private StringRedisTemplate redisTemplate;
    @Mock
    private UserMapper userMapper;
    @Mock
    private TenantMapper tenantMapper;
    @Mock
    private UserIdentityMapper userIdentityMapper;
    @Mock
    private PlatformAdminMapper platformAdminMapper;
    @Mock
    private TenantAiConfigMapper tenantAiConfigMapper;
    @Mock
    private CustomerService customerService;

    /** 登录失败计数（issue #5531）：本类不测它 ⇒ 用 mock（默认未锁定 ⇒ 既有行为不变）。 */
    @Mock
    private LoginFailureGuard loginFailureGuard;

    /** 两企业同名员工（I3 的构造）：A = acme(1)，B = globex(2)，两边用户名都叫 zhangsan。 */
    private final Tenant tenantA = Tenant.builder().id(1L).code("acme").name("甲公司").status("active").build();
    private final Tenant tenantB = Tenant.builder().id(2L).code("globex").name("乙公司").status("active").build();
    private final User zhangsanOfA = User.builder()
            .id("user-A").tenantId(1L).username("zhangsan").phone("13800000001")
            .passwordHash("$2a$10$hashA").role("operator").status("active")
            .mustChangePassword(false).build();
    private final User zhangsanOfB = User.builder()
            .id("user-B").tenantId(2L).username("zhangsan").phone("13800000002")
            .passwordHash("$2a$10$hashB").role("operator").status("active")
            .mustChangePassword(false).build();

    /** 可变夹具：反枚举用例需要同一 mock 在不同阶段返回不同值（避免重复 stubbing 的严格模式摩擦）。 */
    private final List<Tenant> tenantLookup = new ArrayList<>();
    private final List<User> userLookup = new ArrayList<>();

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(authService, "cookieName", "access_token");
        ReflectionTestUtils.setField(authService, "cookieDomain", "");
        ReflectionTestUtils.setField(authService, "cookiePath", "/");
        ReflectionTestUtils.setField(authService, "cookieSecure", true);
        ReflectionTestUtils.setField(authService, "cookieHttpOnly", true);
        ReflectionTestUtils.setField(authService, "cookieSameSite", "strict");

        when(tenantMapper.selectOne(any())).thenAnswer(inv -> tenantLookup.isEmpty() ? null : tenantLookup.get(0));
        when(userMapper.selectActiveByTenantAndUsername(any(), anyString()))
                .thenAnswer(inv -> userLookup.isEmpty() ? null : userLookup.get(0));
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    private void stubTokenIssuing() {
        when(jwtTokenProvider.generateAccessToken(anyString(), any(), anyString(), any(), any(), anyBoolean()))
                .thenReturn("access-token");
        when(jwtTokenProvider.generateRefreshToken(anyString(), any())).thenReturn("refresh-token");
        when(jwtTokenProvider.getAccessTokenExpiration()).thenReturn(7200L);
    }

    // ======================== AU-001 ========================

    @Test
    @DisplayName("AU-001 员工登录成功：企业编码解析租户 → 签发 token + 设置租户上下文")
    void employeeLogin_success_issuesTokenForOwnTenant() {
        tenantLookup.add(tenantA);
        userLookup.add(zhangsanOfA);
        when(passwordEncoder.matches("secret123", "$2a$10$hashA")).thenReturn(true);
        when(userService.getUserRoles(zhangsanOfA)).thenReturn(List.of("operator"));
        when(roleService.getUserPermissions("user-A")).thenReturn(List.of("orders.list"));
        stubTokenIssuing();

        LoginResponse result = authService.loginByEmployee(
                "zhangsan@acme", "secret123", mock(HttpServletResponse.class));

        assertThat(result.getAccessToken()).isEqualTo("access-token");
        assertThat(result.getUser().getId()).isEqualTo("user-A");
        assertThat(result.getUser().getIdentityType()).isEqualTo("employee");
        assertThat(result.getUser().getTenantId()).isEqualTo(1L);
        assertThat(result.getUser().getRoles()).containsExactly("operator");
        assertThat(result.getUser().getMustChangePassword()).isFalse();
        // 租户上下文必须落在解析出的租户上（后续 roles/permissions/租户名查询都按它走）
        assertThat(TenantContext.getTenantId()).isEqualTo(1L);
        // 查询逐字带租户条件（I1）
        verify(userMapper).selectActiveByTenantAndUsername(1L, "zhangsan");
    }

    // ======================== AU-002（I1 / I3） ========================

    @Test
    @DisplayName("AU-002 同名员工分属 A/B：zhangsan@acme 只解析到 A 企业（且绝不查 B）")
    void crossTenant_sameUsername_resolvesOnlyOwnTenant() {
        tenantLookup.add(tenantA);
        userLookup.add(zhangsanOfA);
        when(passwordEncoder.matches("secret123", "$2a$10$hashA")).thenReturn(true);
        when(userService.getUserRoles(zhangsanOfA)).thenReturn(List.of("operator"));
        when(roleService.getUserPermissions("user-A")).thenReturn(List.of());
        stubTokenIssuing();

        LoginResponse result = authService.loginByEmployee(
                "zhangsan@acme", "secret123", mock(HttpServletResponse.class));

        assertThat(result.getUser().getId()).isEqualTo("user-A");
        assertThat(result.getUser().getTenantId()).isEqualTo(1L);
        verify(userMapper).selectActiveByTenantAndUsername(1L, "zhangsan");
        // B 企业的同名用户**一个字节都不该被碰到**（跨租户兜底 = 串号，I1 禁止）
        verify(userMapper, never()).selectActiveByTenantAndUsername(eq(2L), anyString());
    }

    @Test
    @DisplayName("AU-002 同名员工分属 A/B：zhangsan@globex 只解析到 B 企业")
    void crossTenant_sameUsername_otherTenantResolvesToItsOwnUser() {
        tenantLookup.add(tenantB);
        userLookup.add(zhangsanOfB);
        when(passwordEncoder.matches("secret456", "$2a$10$hashB")).thenReturn(true);
        when(userService.getUserRoles(zhangsanOfB)).thenReturn(List.of("operator"));
        when(roleService.getUserPermissions("user-B")).thenReturn(List.of());
        stubTokenIssuing();

        LoginResponse result = authService.loginByEmployee(
                "zhangsan@globex", "secret456", mock(HttpServletResponse.class));

        assertThat(result.getUser().getId()).isEqualTo("user-B");
        assertThat(result.getUser().getTenantId()).isEqualTo(2L);
        verify(userMapper).selectActiveByTenantAndUsername(2L, "zhangsan");
        verify(userMapper, never()).selectActiveByTenantAndUsername(eq(1L), anyString());
    }

    @Test
    @DisplayName("AU-002 用户名查询的 SQL **本身**带 tenant_id 谓词（删掉它 ⇒ 本判据必红）")
    void usernameLookupSql_isTenantScoped() throws Exception {
        Method method = UserMapper.class.getMethod("selectActiveByTenantAndUsername", Long.class, String.class);
        String sql = String.join(" ", method.getAnnotation(Select.class).value()).toLowerCase();

        assertThat(sql)
                .as("用户名查询必须逐字带租户条件（I1：禁止无租户限定的用户名查询）")
                .contains("tenant_id = #{tenantid}")
                .contains("username = #{username}");
    }

    // ======================== AU-003（反枚举） ========================

    @Test
    @DisplayName("AU-003 反枚举：企业编码不存在/用户名不存在/密码错/状态非 active ⇒ 同一 401 同一文案")
    void antiEnumeration_allFailureModesShareOneStatusAndMessage() {
        HttpServletResponse response = mock(HttpServletResponse.class);
        List<BusinessException> failures = new ArrayList<>();

        // ① 企业编码不存在（这里**不**放 tenant，selectOne 返回 null）
        failures.add(catchBusiness(() -> authService.loginByEmployee("zhangsan@nosuch", "pw", response)));

        // ② 用户名在该企业下不存在
        tenantLookup.add(tenantA);
        userLookup.clear();
        failures.add(catchBusiness(() -> authService.loginByEmployee("zhangsan@acme", "pw", response)));

        // ③ 密码错误
        userLookup.add(zhangsanOfA);
        when(passwordEncoder.matches("wrong-pw", "$2a$10$hashA")).thenReturn(false);
        failures.add(catchBusiness(() -> authService.loginByEmployee("zhangsan@acme", "wrong-pw", response)));

        // ④ 状态非 active（SQL 已门禁 active；这里是纵深防御分支，同样不许换文案）
        User disabled = User.builder().id("user-X").tenantId(1L).username("zhangsan")
                .passwordHash("$2a$10$hashA").role("operator").status("disabled").build();
        userLookup.clear();
        userLookup.add(disabled);
        when(passwordEncoder.matches("secret123", "$2a$10$hashA")).thenReturn(true);
        failures.add(catchBusiness(() -> authService.loginByEmployee("zhangsan@acme", "secret123", response)));

        // ⑤ 标识格式不合法（含 @ 缺失 / 用户名过短）—— 同样不许泄露「格式错」这一信息
        failures.add(catchBusiness(() -> authService.loginByEmployee("zhangsan", "pw", response)));

        assertThat(failures)
                .as("四种真实病因 + 一种格式错误必须走同一出口")
                .hasSize(5)
                .allSatisfy(e -> {
                    assertThat(e.getCode()).isEqualTo("AUTH_FAILED");
                    assertThat(e.getHttpStatus()).isEqualTo(401);
                    assertThat(e.getMessage()).isEqualTo(LoginIdentifiers.AUTH_FAILED_MESSAGE);
                });
        assertThat(failures).extracting(BusinessException::getMessage).containsOnly("账号或密码错误");
    }

    private static BusinessException catchBusiness(Runnable action) {
        try {
            action.run();
        } catch (BusinessException e) {
            return e;
        }
        throw new AssertionError("预期抛出 BusinessException，但登录居然成功了");
    }

    @Test
    @DisplayName("AU-002 存量带下划线的企业编码（tenant_7478359537 形态）必须能解析并登录成功")
    void legacyUnderscoreTenantCode_resolvesAndLogsIn() {
        // dev 库现存 tenants.code 有 `tenant_7478359537` 这种（旧生成器 tenant_%06d%04d 的产物）。
        // 若企业编码字符集不含 `_`，这两个租户的员工**永远登不进来**，而管理员没有任何自救路径。
        Tenant legacy = Tenant.builder().id(20L).code("tenant_7478359537").name("老租户").status("active").build();
        tenantLookup.add(legacy);
        userLookup.add(User.builder()
                .id("user-A").tenantId(20L).username("zhangsan").phone("13800000001")
                .passwordHash("$2a$10$hashA").role("operator").status("active")
                .mustChangePassword(false).build());
        when(passwordEncoder.matches("secret123", "$2a$10$hashA")).thenReturn(true);
        when(userService.getUserRoles(any(User.class))).thenReturn(List.of("operator"));
        when(roleService.getUserPermissions("user-A")).thenReturn(List.of());
        stubTokenIssuing();

        LoginResponse result = authService.loginByEmployee(
                "zhangsan@tenant_7478359537", "secret123", mock(HttpServletResponse.class));

        assertThat(result.getUser().getTenantId()).isEqualTo(20L);
        verify(userMapper).selectActiveByTenantAndUsername(20L, "zhangsan");
    }

    // ======================== AU-010（存量行） ========================

    @Test
    @DisplayName("AU-010 存量员工（username 为 NULL）无法用员工登录：查询不命中 ⇒ 统一文案")
    void legacyUserWithoutUsername_cannotLoginByEmployee() {
        tenantLookup.add(tenantA);
        userLookup.clear();  // 存量行 username IS NULL ⇒ `username = #{username}` 永不命中

        BusinessException e = catchBusiness(() -> authService.loginByEmployee(
                "laowang@acme", "whatever", mock(HttpServletResponse.class)));

        assertThat(e.getCode()).isEqualTo("AUTH_FAILED");
        assertThat(e.getMessage()).isEqualTo(LoginIdentifiers.AUTH_FAILED_MESSAGE);
        // 定位仍然只在 A 企业内发生（没有「全平台按用户名找人」的兜底路径）
        verify(userMapper).selectActiveByTenantAndUsername(1L, "laowang");
        verify(userMapper, never()).selectActiveByTenantAndUsername(isNull(), anyString());
    }
}