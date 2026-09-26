// case_ids: HR-002, HR-001, HR-007
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.User;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.mapper.WorkerSessionMapper;
import com.migao.admin.security.LoginFailureGuard;
import com.migao.admin.worker.WorkerSessionService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.beans.BeanUtils;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 工人档案建号（issue #4869）：**首个工人怎么建出来**。
 *
 * <p><b>改前形态（红证形态）</b>：全仓零写入方 —— `users.worker_no` 只能靠手工 SQL 落，
 * 于是「工号 + PIN 登录」（#4733 已落码）在真实部署里<b>永远没有可登录的对象</b>；
 * 本测试类引用的 {@code WorkerAdminService} 在改前不存在 ⇒ **连编译都不过**。</p>
 *
 * <p><b>四条判据（逐条对应验收标准）</b>：</p>
 * <ol>
 *   <li>建号 ⇒ 能用该工号 + PIN 走既有 {@code WorkerSessionService.login} 登录成功，且归属当前租户；</li>
 *   <li>重复工号 ⇒ **明确拒绝**（409 + 文案含工号），不是 500、更不是静默建第二个；</li>
 *   <li>工人档案**零商家权限**：{@code role=worker} / 无 permissions / 无 username / 结构上无法写 user_roles；</li>
 *   <li>PIN 形态 fail-closed：工人端 PIN 输入框是数字键盘（`frontend/worker-h5/src/render.mjs`），
 *       非数字 PIN 建出来的账号**根本登不进** ⇒ 必须在建号时就拒。</li>
 * </ol>
 *
 * <p><b>为什么用内存假表 + 真 BCrypt、真登录服务</b>：判据要的是「建号 ⇒ 登录」这条链**端到端**成立，
 * 而不是「方法被调用过」。假表只模拟一件事 —— 租户过滤（跨租户查不到行），
 * 其余（BCrypt 编码、PIN 比对、会话签发）全部走**生产实现**。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("工人档案建号（#4869）：工号 + PIN ⇒ 可登录 / 不串租户 / 零商家权限")
class WorkerAdminServiceTest {

    private static final Long TENANT = 7L;
    private static final Long OTHER_TENANT = 8L;
    private static final String WORKER_NO = "W-1001";
    private static final String NAME = "张三";
    private static final String PIN = "246810";

    @Mock
    private UserMapper userMapper;
    @Mock
    private WorkerSessionMapper workerSessionMapper;

    private final PasswordEncoder passwordEncoder = new BCryptPasswordEncoder();

    private WorkerAdminService service;
    private WorkerSessionService loginService;

    /** 内存假表：只存「已成功建号的工人档案」，并**只按租户可见**。 */
    private final AtomicReference<User> workersTable = new AtomicReference<>();

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        // 初始化 MyBatis-Plus lambda 缓存（LambdaQueryWrapper 解析 User::getXxx 需要 TableInfo）
        // —— 不初始化时 `getSqlSegment()` 抛 can not find lambda cache（与 UserServiceTest 同款前置）
        com.baomidou.mybatisplus.core.MybatisConfiguration configuration =
                new com.baomidou.mybatisplus.core.MybatisConfiguration();
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(
                new org.apache.ibatis.builder.MapperBuilderAssistant(configuration, ""), User.class);

        service = new WorkerAdminService(userMapper, passwordEncoder);

        Map<String, String> store = new HashMap<>();
        StringRedisTemplate redis = org.mockito.Mockito.mock(StringRedisTemplate.class);
        ValueOperations<String, String> ops = org.mockito.Mockito.mock(ValueOperations.class);
        when(redis.opsForValue()).thenReturn(ops);
        when(ops.get(anyString())).thenAnswer(i -> store.get(i.getArgument(0, String.class)));
        when(ops.increment(anyString())).thenAnswer(i -> {
            String k = i.getArgument(0, String.class);
            long v = Long.parseLong(store.getOrDefault(k, "0")) + 1;
            store.put(k, String.valueOf(v));
            return v;
        });
        when(redis.expire(anyString(), anyLong(), any(TimeUnit.class))).thenReturn(true);
        when(redis.delete(anyString())).thenReturn(true);
        LoginFailureGuard guard = new LoginFailureGuard(redis,
                new io.micrometer.core.instrument.simple.SimpleMeterRegistry());
        loginService = new WorkerSessionService(workerSessionMapper, userMapper, passwordEncoder, guard);

        // 假表：insert 存副本（生产实现会清空返回对象的 passwordHash，不能共用引用）；
        // selectOne 模拟「租户隔离」—— 别的租户查不到这一行。
        when(userMapper.insert(any(User.class))).thenAnswer(inv -> {
            User row = inv.getArgument(0);
            if (row.getId() == null) {
                row.setId("worker-1");
            }
            User copy = new User();
            BeanUtils.copyProperties(row, copy);
            workersTable.set(copy);
            return 1;
        });
        when(userMapper.selectOne(any())).thenAnswer(inv -> {
            User row = workersTable.get();
            Long tenant = TenantContext.getTenantId();
            if (row == null || tenant == null || !tenant.equals(row.getTenantId())) {
                return null;
            }
            User copy = new User();
            BeanUtils.copyProperties(row, copy);
            return copy;
        });

        TenantContext.setTenantId(TENANT);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ============ ① 建号 ⇒ 能用工号 + PIN 登录 ⇒ 归属租户正确 ============

    @Test
    @DisplayName("① 建号 ⇒ 该工号 + PIN 登录成功，worker_id/worker_no/worker_name 全对（改前无此路径 ⇒ 红）")
    void createdWorkerCanLogInWithWorkerNoAndPin() {
        User created = service.createWorker(WORKER_NO, NAME, PIN);

        assertThat(created.getWorkerNo()).isEqualTo(WORKER_NO);
        assertThat(created.getTenantId()).isEqualTo(TENANT);
        assertThat(created.getRole()).isEqualTo("worker");
        assertThat(created.getStatus()).isEqualTo("active");

        Map<String, Object> payload = loginService.login(TENANT, WORKER_NO, PIN, "PAD-车间-01");

        assertThat(payload.get("worker_id")).isEqualTo(created.getId());
        assertThat(payload.get("worker_no")).isEqualTo(WORKER_NO);
        assertThat(payload.get("worker_name")).isEqualTo(NAME);
    }

    @Test
    @DisplayName("① 反向：PIN 错 ⇒ 401（建号确实落了可校验的 BCrypt 哈希，不是明文、不是空）")
    void wrongPinIsRejected() {
        service.createWorker(WORKER_NO, NAME, PIN);

        assertThatThrownBy(() -> loginService.login(TENANT, WORKER_NO, "000000", null))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("工号或 PIN 不正确");
    }

    @Test
    @DisplayName("① 归属租户：别个租户用同一工号 + 正确 PIN ⇒ 401（档案不跨租户可见）")
    void workerArchiveIsNotVisibleFromAnotherTenant() {
        service.createWorker(WORKER_NO, NAME, PIN);

        assertThatThrownBy(() -> loginService.login(OTHER_TENANT, WORKER_NO, PIN, null))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("工号或 PIN 不正确");
    }

    // ============ ② 重复工号 ⇒ 明确拒绝（不是 500） ============

    @Test
    @DisplayName("② 重复工号 ⇒ 409 + 文案含工号 + 不落第二行（改前 ⇒ 建出两个同名工号 / 库层 500）")
    void duplicateWorkerNoIsRejectedExplicitly() {
        service.createWorker(WORKER_NO, NAME, PIN);

        assertThatThrownBy(() -> service.createWorker(WORKER_NO, "李四", "135791"))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", "CONFLICT")
                .hasMessageContaining(WORKER_NO);

        verify(userMapper, times(1)).insert(any(User.class));
    }

    @Test
    @DisplayName("② 并发兜底：唯一索引撞车（DuplicateKeyException）⇒ 409 而不是 500")
    void duplicateKeyRaceIsRejectedExplicitly() {
        when(userMapper.insert(any(User.class)))
                .thenThrow(new DuplicateKeyException("uk_users_tenant_worker_no"));

        assertThatThrownBy(() -> service.createWorker(WORKER_NO, NAME, PIN))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", "CONFLICT")
                .hasMessageContaining(WORKER_NO);
    }

    // ============ ③ 工人档案零商家权限 ============

    @Test
    @DisplayName("③ 工人档案零商家权限：role=worker / 无 permissions / 无 username / 不置强制改密 / 无 phone")
    void workerArchiveCarriesNoMerchantAuthority() {
        service.createWorker(WORKER_NO, NAME, PIN);

        ArgumentCaptor<User> captor = ArgumentCaptor.forClass(User.class);
        verify(userMapper).insert(captor.capture());
        User row = captor.getValue();

        assertThat(row.getRole()).isEqualTo("worker");
        assertThat(row.getPermissions()).isNull();
        assertThat(row.getUsername()).isNull();
        assertThat(row.getPhone()).isNull();
        assertThat(row.getMustChangePassword()).isNotEqualTo(Boolean.TRUE);
        // 落库的那一行是 BCrypt 哈希；返回给调用方的对象已脱敏（与 UserService.createUser 同口径）
        assertThat(workersTable.get().getPasswordHash()).startsWith("$2");
        assertThat(row.getPasswordHash()).isNull();
    }

    @Test
    @DisplayName("③ 结构级：建号服务**不得**持有任何角色/权限写入依赖（新增 ⇒ 必红 = 工人会拿到 user_roles）")
    void createServiceCannotWriteUserRoles() {
        List<String> dependencyTypes = new ArrayList<>();
        for (java.lang.reflect.Field f : WorkerAdminService.class.getDeclaredFields()) {
            dependencyTypes.add(f.getType().getSimpleName());
        }

        assertThat(dependencyTypes)
                .as("工人**不得**有任何 user_roles 行 —— 建号服务一旦能写角色/权限，工人就会拿到商家权限")
                .doesNotContain("RoleService", "RoleMapper", "UserRoleMapper", "PermissionInterceptor");
    }

    @Test
    @DisplayName("③ 角色码单一字面量：建号用的角色 = 登录服务用的角色（两处不一致 ⇒ 建出来登不进 / 或登进后台）")
    void workerRoleLiteralIsSingleSource() {
        assertThat(WorkerAdminService.WORKER_ROLE)
                .isEqualTo(WorkerSessionService.WORKER_ROLE)
                .isEqualTo("worker");
    }

    // ============ ④ 入参 fail-closed ============

    @Test
    @DisplayName("④ 非数字 PIN ⇒ 422 且零写入（工人端 PIN 输入框是数字键盘，非数字 PIN 建了也登不进）")
    void nonNumericPinIsRejected() {
        assertThatThrownBy(() -> service.createWorker(WORKER_NO, NAME, "pin123"))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", "VALIDATION_ERROR")
                .hasMessageContaining("PIN");

        assertThatThrownBy(() -> service.createWorker(WORKER_NO, NAME, "123"))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", "VALIDATION_ERROR")
                .hasMessageContaining("PIN");

        verify(userMapper, never()).insert(any(User.class));
    }

    @Test
    @DisplayName("④ 工号/姓名缺失或空白 ⇒ 422 且零写入（不建出「无工号工人」这种登不进的档案）")
    void blankWorkerNoOrNameIsRejected() {
        assertThatThrownBy(() -> service.createWorker("   ", NAME, PIN))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("工号");

        assertThatThrownBy(() -> service.createWorker(WORKER_NO, "", PIN))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("姓名");

        verify(userMapper, never()).insert(any(User.class));
    }

    @Test
    @DisplayName("④ 工号首尾空白被规整（与登录侧 trim 同口径 ⇒ 复制粘贴带空格的工号也能登）")
    void workerNoIsTrimmedOnCreate() {
        User created = service.createWorker("  " + WORKER_NO + "  ", NAME, PIN);

        assertThat(created.getWorkerNo()).isEqualTo(WORKER_NO);
        assertThat(loginService.login(TENANT, WORKER_NO, PIN, null).get("worker_no")).isEqualTo(WORKER_NO);
    }

    // ============ 列表（只列工人档案，且脱敏） ============

    @Test
    @DisplayName("列表：只查 role=worker 的行，且响应脱敏（不返回 password_hash）")
    @SuppressWarnings("unchecked")
    void listWorkersOnlyReturnsWorkerArchives() {
        User worker = User.builder().id("worker-1").tenantId(TENANT).workerNo(WORKER_NO)
                .nickname(NAME).role("worker").status("active")
                .passwordHash(passwordEncoder.encode(PIN)).build();
        Page<User> page = new Page<>(1, 10);
        page.setRecords(List.of(worker));
        page.setTotal(1);
        when(userMapper.selectPage(any(), any())).thenReturn(page);

        PageResponse<User> result = service.listWorkers(1, 10, null, null);

        assertThat(result.getTotal()).isEqualTo(1);
        assertThat(result.getItems()).hasSize(1);
        assertThat(result.getItems().get(0).getPasswordHash()).isNull();

        ArgumentCaptor<Wrapper<User>> captor = ArgumentCaptor.forClass(Wrapper.class);
        verify(userMapper).selectPage(any(), captor.capture());
        Wrapper<User> wrapper = captor.getValue();
        assertThat(wrapper.getSqlSegment()).contains("role =");
        assertThat(((LambdaQueryWrapper<User>) wrapper).getParamNameValuePairs()).containsValue("worker");
    }

    @Test
    @DisplayName("列表：关键词同时搜工号与姓名（管理员手上有的是纸上的工号）")
    @SuppressWarnings("unchecked")
    void listWorkersSupportsKeywordSearch() {
        Page<User> page = new Page<>(1, 10);
        page.setRecords(List.of());
        page.setTotal(0);
        when(userMapper.selectPage(any(), any())).thenReturn(page);

        service.listWorkers(1, 10, WORKER_NO, "active");

        ArgumentCaptor<Wrapper<User>> captor = ArgumentCaptor.forClass(Wrapper.class);
        verify(userMapper).selectPage(any(), captor.capture());
        // ⚠️ MP 的 paramNameValuePairs 是在 getSqlSegment() 期间惰性填充的 ⇒ 必须先取 SQL 段再读参数
        LambdaQueryWrapper<User> wrapper = (LambdaQueryWrapper<User>) captor.getValue();
        assertThat(wrapper.getSqlSegment()).contains("worker_no");
        Map<String, Object> params = wrapper.getParamNameValuePairs();
        assertThat(params.values().toString())
                .as("工号是管理员手上唯一能对着纸抄的东西 ⇒ 关键词必须能搜工号（LIKE，值含 %）")
                .contains(WORKER_NO)
                .contains("active");
    }

    @Test
    @DisplayName("建号必须落 `worker_no IS NOT NULL`（这是「只认工人档案」的机械判据，登录侧靠它）")
    void createdArchiveIsIdentifiableAsWorker() {
        service.createWorker(WORKER_NO, NAME, PIN);

        ArgumentCaptor<User> captor = ArgumentCaptor.forClass(User.class);
        verify(userMapper).insert(captor.capture());

        assertThat(Arrays.asList(captor.getValue().getWorkerNo(), captor.getValue().getRole()))
                .doesNotContainNull();
    }
}
