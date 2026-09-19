package com.migao.admin.service;

import com.migao.admin.dto.RegistrationRequest;
import com.migao.admin.dto.RegistrationResponse;
import com.migao.admin.entity.Permission;
import com.migao.admin.entity.Role;
import com.migao.admin.entity.RolePermission;
import com.migao.admin.entity.TenantApplication;
import com.migao.admin.entity.User;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.PermissionMapper;
import com.migao.admin.mapper.RoleMapper;
import com.migao.admin.mapper.RolePermissionMapper;
import com.migao.admin.mapper.TenantApplicationMapper;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.mapper.UserMapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * RegistrationService 入驻申请服务测试（AI 自动甄别版）
 * 覆盖：AI 通过/驳回/系统繁忙降级、蜜罐、频率限制、手机号/企业名查重、驳回冷却、
 * 审批副作用（租户+管理员）、审核元数据落库
 */
// case_ids: OB-001, OB-002, OB-003, HR-006
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("RegistrationService 入驻申请服务测试（AI 自动甄别）")
class RegistrationServiceTest extends BaseServiceTest {

    @Mock private TenantApplicationMapper applicationMapper;
    @Mock private TenantMapper tenantMapper;
    @Mock private UserService userService;
    @Mock private SmsService smsService;
    @Mock private UserMapper userMapper;
    @Mock private RoleMapper roleMapper;
    @Mock private PermissionMapper permissionMapper;
    @Mock private RolePermissionMapper rolePermissionMapper;
    @Mock private RegistrationReviewClient reviewClient;
    @Mock private StringRedisTemplate redisTemplate;
    @Mock private ValueOperations<String, String> valueOperations;
    /**
     * 开租播种（issue #4430 / B2）：`approveApplication` 里**唯一**把「新租户工序库/路线库为空」
     * 这件事堵住的调用点。此前本测试对该服务**零引用** ⇒ 删掉那一行调用 **CI 全绿**
     * （实测：不 mock 时 `applyProductionSeedTemplate` 内部 NPE 被 catch 吞掉，
     * 既有断言照样通过），而线上后果是建单 fail-closed 422（#4316 回归）。
     */
    @Mock private ProductionSeedTemplateService productionSeedTemplateService;

    @InjectMocks private RegistrationService registrationService;

    private TenantApplication pendingApp;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        pendingApp = TenantApplication.builder().id(1L).companyName("测试公司")
                .phone("13800138000").contactName("张三").status("pending").build();

        // Redis 计数默认 1（未超限）
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        when(valueOperations.increment(anyString())).thenReturn(1L);
        // 查重默认 0 条
        when(applicationMapper.selectCount(any())).thenReturn(0L);
        // 短信验证码默认通过
        when(smsService.verifyCode(anyString(), anyString())).thenReturn(true);
        // 落库后回填自增 ID，并让 selectById 返回同一实例（审批副作用链路）
        java.util.concurrent.atomic.AtomicReference<TenantApplication> insertedRef =
                new java.util.concurrent.atomic.AtomicReference<>();
        doAnswer(inv -> {
            TenantApplication app = inv.getArgument(0);
            app.setId(1L);
            insertedRef.set(app);
            return 1;
        }).when(applicationMapper).insert(any(TenantApplication.class));
        when(applicationMapper.selectById(1L)).thenAnswer(inv -> insertedRef.get());
    }

    private RegistrationRequest buildRequest() {
        RegistrationRequest req = new RegistrationRequest();
        req.setCompanyName("杭州测试布艺有限公司");
        req.setContactName("张三");
        req.setPhone("13800138000");
        req.setSmsCode("123456");
        req.setIndustry("布艺");
        return req;
    }

    private RegistrationReviewClient.ReviewVerdict verdict(String decision, String reason) {
        return new RegistrationReviewClient.ReviewVerdict(
                decision, 0.95, reason, List.of(), "summary", "ai");
    }

    @Nested
    @DisplayName("submitApplication — AI 自动甄别")
    class Submit {

        @Test
        @DisplayName("AI 甄别通过 → approved 且自动创建租户管理员")
        void aiApprove() {
            when(reviewClient.review(any())).thenReturn(verdict("approve", ""));
            doAnswer(inv -> { ((com.migao.admin.entity.Tenant) inv.getArgument(0)).setId(100L); return 1; })
                    .when(tenantMapper).insert(any(com.migao.admin.entity.Tenant.class));
            User adminUser = new User();
            adminUser.setId("user-admin");
            when(userService.createUser(anyString(), anyString(), anyString(), eq("admin"), anyString(), isNull(), eq(100L)))
                    .thenReturn(adminUser);

            RegistrationResponse resp = registrationService.submitApplication(buildRequest(), "1.2.3.4");

            assertThat(resp.getStatus()).isEqualTo("approved");
            assertThat(resp.getMessage()).contains("欢迎入驻");
            verify(userService).createUser(anyString(), anyString(), anyString(), eq("admin"), anyString(), isNull(), anyLong());
        }

        @Test
        @DisplayName("AI 甄别驳回 → rejected 且带驳回原因")
        void aiReject() {
            when(reviewClient.review(any())).thenReturn(verdict("reject", "企业名称暗示无资质金融业务"));

            RegistrationResponse resp = registrationService.submitApplication(buildRequest(), "1.2.3.4");

            assertThat(resp.getStatus()).isEqualTo("rejected");
            assertThat(resp.getRejectReason()).contains("金融");
        }

        @Test
        @DisplayName("AI 服务不可用 → fail-closed 系统繁忙驳回（不调 AI 放行）")
        void aiUnavailableFailClosed() {
            when(reviewClient.review(any())).thenReturn(null);

            RegistrationResponse resp = registrationService.submitApplication(buildRequest(), "1.2.3.4");

            assertThat(resp.getStatus()).isEqualTo("rejected");
            assertThat(resp.getRejectReason()).contains("系统繁忙");
        }

        @Test
        @DisplayName("蜜罐字段被填充 → 疑似脚本，不落库不调 AI，静默返回")
        void honeypot() {
            RegistrationRequest req = buildRequest();
            req.setWebsite("http://bot.example.com");

            RegistrationResponse resp = registrationService.submitApplication(req, "1.2.3.4");

            verify(applicationMapper, never()).insert(any(TenantApplication.class));
            verify(reviewClient, never()).review(any());
            assertThat(resp.getStatus()).isEqualTo("pending");
        }

        @Test
        @DisplayName("短信验证码错误 → VALIDATION_ERROR")
        void invalidSms() {
            when(smsService.verifyCode("13800138000", "123456")).thenReturn(false);

            assertThatThrownBy(() -> registrationService.submitApplication(buildRequest(), "1.2.3.4"))
                    .isInstanceOf(BusinessException.class)
                    .satisfies(ex -> assertThat(((BusinessException) ex).getCode()).isEqualTo("VALIDATION_ERROR"));
        }

        @Test
        @DisplayName("手机号每日提交超限 → VALIDATION_ERROR")
        void phoneDailyLimit() {
            when(valueOperations.increment(anyString())).thenReturn(4L);

            assertThatThrownBy(() -> registrationService.submitApplication(buildRequest(), "1.2.3.4"))
                    .isInstanceOf(BusinessException.class)
                    .satisfies(ex -> assertThat(((BusinessException) ex).getCode()).isEqualTo("VALIDATION_ERROR"));
        }

        @Test
        @DisplayName("IP 每小时提交超限 → VALIDATION_ERROR")
        void ipHourlyLimit() {
            when(valueOperations.increment(anyString())).thenReturn(1L, 6L);

            assertThatThrownBy(() -> registrationService.submitApplication(buildRequest(), "1.2.3.4"))
                    .isInstanceOf(BusinessException.class)
                    .satisfies(ex -> assertThat(((BusinessException) ex).getCode()).isEqualTo("VALIDATION_ERROR"));
        }

        @Test
        @DisplayName("同手机号已有 pending/approved 申请 → VALIDATION_ERROR")
        void phoneDuplicate() {
            when(applicationMapper.selectCount(any())).thenReturn(1L);

            assertThatThrownBy(() -> registrationService.submitApplication(buildRequest(), "1.2.3.4"))
                    .isInstanceOf(BusinessException.class);
        }

        @Test
        @DisplayName("同企业名（规范化）已有申请 → VALIDATION_ERROR")
        void companyDuplicate() {
            when(applicationMapper.selectCount(any()))
                    .thenReturn(0L, 1L); // 第一次 phone 查询 0，第二次企业名查询 1

            assertThatThrownBy(() -> registrationService.submitApplication(buildRequest(), "1.2.3.4"))
                    .isInstanceOf(BusinessException.class)
                    .satisfies(ex -> assertThat(((BusinessException) ex).getMessage()).contains("该企业已有入驻申请"));
        }

        @Test
        @DisplayName("企业名不同写法（去后缀/去括号）归一后命中查重")
        void companyDuplicateNormalized() {
            // "杭州测试布艺有限公司" 与 "杭州测试布艺（集团）有限公司" 归一相同
            assertThat(RegistrationService.normalizeCompanyName("杭州测试布艺有限公司"))
                    .isEqualTo(RegistrationService.normalizeCompanyName("杭州测试布艺（集团）有限公司"));
        }

        @Test
        @DisplayName("AI 驳回 24h 冷却期内 → 禁止重提")
        void rejectedCooldown() {
            TenantApplication rejected = TenantApplication.builder()
                    .id(9L).phone("13800138000").status("rejected")
                    .reviewSource("ai").reviewedAt(OffsetDateTime.now().minusHours(1))
                    .build();
            when(applicationMapper.selectCount(any())).thenReturn(0L);
            when(applicationMapper.selectOne(any())).thenReturn(rejected);

            assertThatThrownBy(() -> registrationService.submitApplication(buildRequest(), "1.2.3.4"))
                    .isInstanceOf(BusinessException.class)
                    .satisfies(ex -> assertThat(((BusinessException) ex).getMessage()).contains("小时后重新提交"));
        }

        @Test
        @DisplayName("系统繁忙驳回（review_source=system）不进入冷却 → 可立即重试")
        void systemRejectionNoCooldown() {
            TenantApplication rejected = TenantApplication.builder()
                    .id(9L).phone("13800138000").status("rejected")
                    .reviewSource("system").reviewedAt(OffsetDateTime.now().minusMinutes(5))
                    .build();
            when(applicationMapper.selectCount(any())).thenReturn(0L);
            when(applicationMapper.selectOne(any())).thenReturn(rejected);
            when(reviewClient.review(any())).thenReturn(verdict("approve", ""));
            doAnswer(inv -> { ((com.migao.admin.entity.Tenant) inv.getArgument(0)).setId(100L); return 1; })
                    .when(tenantMapper).insert(any(com.migao.admin.entity.Tenant.class));
            when(userService.createUser(anyString(), anyString(), anyString(), eq("admin"), anyString(), isNull(), eq(100L)))
                    .thenReturn(new User());

            RegistrationResponse resp = registrationService.submitApplication(buildRequest(), "1.2.3.4");

            assertThat(resp.getStatus()).isEqualTo("approved");
        }
    }

    @Nested
    @DisplayName("getApplications")
    class GetApplications {

        @Test
        @DisplayName("分页查询返回列表")
        void paginated() {
            Page<TenantApplication> mpPage = new Page<>(1, 10);
            mpPage.setTotal(1);
            mpPage.setRecords(java.util.List.of(pendingApp));
            when(applicationMapper.selectPage(any(Page.class), any())).thenReturn(mpPage);

            var result = registrationService.getApplications("pending", 1, 10);

            assertThat(result.getTotal()).isEqualTo(1);
            assertThat(result.getItems()).hasSize(1);
        }
    }

    @Nested
    @DisplayName("getApplicationDetail")
    class GetDetail {

        @Test
        @DisplayName("返回详情")
        void success() {
            when(applicationMapper.selectById(1L)).thenReturn(pendingApp);

            assertThat(registrationService.getApplicationDetail(1L).getCompanyName()).isEqualTo("测试公司");
        }

        @Test
        @DisplayName("不存在 → NOT_FOUND")
        void notFound() {
            when(applicationMapper.selectById(999L)).thenReturn(null);

            assertThatThrownBy(() -> registrationService.getApplicationDetail(999L))
                    .isInstanceOf(BusinessException.class);
        }
    }

    @Nested
    @DisplayName("approveApplication")
    class Approve {

        @Test
        @DisplayName("审批通过 → 创建租户管理员")
        void success() {
            when(applicationMapper.selectById(1L)).thenReturn(pendingApp);
            // 模拟 insert 后设置 entity ID（用具体类型避免 MyBatis-Plus 重载歧义）
            doAnswer(inv -> { ((com.migao.admin.entity.Tenant) inv.getArgument(0)).setId(100L); return 1; })
                    .when(tenantMapper).insert(any(com.migao.admin.entity.Tenant.class));
            mockRoleInsertIds();
            User adminUser = new User();
            adminUser.setId("user-admin");
            when(userService.createUser(anyString(), anyString(), anyString(), eq("admin"), anyString(), isNull(), eq(100L)))
                    .thenReturn(adminUser);

            registrationService.approveApplication(1L, "reviewer-001");

            verify(userService).createUser(anyString(), anyString(), anyString(), eq("admin"), anyString(), isNull(), anyLong());
        }

        @Test
        @DisplayName("岗位权限体系（#2969）：审批通过 → 初始化默认五岗 + role_permissions 预置")
        void successInitializesFiveDefaultPositionsWithPermissions() {
            when(applicationMapper.selectById(1L)).thenReturn(pendingApp);
            doAnswer(inv -> { ((com.migao.admin.entity.Tenant) inv.getArgument(0)).setId(100L); return 1; })
                    .when(tenantMapper).insert(any(com.migao.admin.entity.Tenant.class));
            mockRoleInsertIds();
            User adminUser = new User();
            adminUser.setId("user-admin");
            when(userService.createUser(anyString(), anyString(), anyString(), eq("admin"), anyString(), isNull(), eq(100L)))
                    .thenReturn(adminUser);

            registrationService.approveApplication(1L, "reviewer-001");

            // 五岗种子：管理员 / 客服 / 运营 / 销售 / 财务
            ArgumentCaptor<Role> roleCaptor = ArgumentCaptor.forClass(Role.class);
            verify(roleMapper, times(5)).insert(roleCaptor.capture());
            List<String> codes = roleCaptor.getAllValues().stream().map(Role::getCode).collect(Collectors.toList());
            assertThat(codes).contains("admin", "customer_service", "operator", "sales", "finance");
            assertThat(roleCaptor.getAllValues()).allSatisfy(r ->
                    assertThat(r.getStatus()).isEqualTo("active"));

            // 每个岗位预置默认权限（role_permissions 落库）
            ArgumentCaptor<RolePermission> rpCaptor = ArgumentCaptor.forClass(RolePermission.class);
            verify(rolePermissionMapper, atLeast(5)).insert(rpCaptor.capture());
            assertThat(rpCaptor.getAllValues()).extracting(RolePermission::getRoleId)
                    .contains("role-admin", "role-customer_service", "role-operator", "role-sales", "role-finance");
        }

        /** mock role insert 后回填 id（五岗种子依赖 role.getId() 关联 role_permissions） */
        private void mockRoleInsertIds() {
            doAnswer(inv -> {
                Role role = inv.getArgument(0);
                role.setId("role-" + role.getCode());
                return 1;
            }).when(roleMapper).insert(any(Role.class));
            doAnswer(inv -> { ((Permission) inv.getArgument(0)).setId("perm-demo"); return 1; })
                    .when(permissionMapper).insert(any(Permission.class));
            when(rolePermissionMapper.insert(any(RolePermission.class))).thenReturn(1);
        }

        /**
         * 审批通过的「开租播种」副作用（issue #4430 / B2）：必须**真的**调
         * {@code ProductionSeedTemplateService.applyTemplate}，且入参是**新建租户**的
         * id 与**归一后的**行业 code。
         *
         * <p>为什么必须有：这一行调用是「新租户工序库/路线库非空」的唯一来源，
         * 删掉它没有任何测试会红（本类此前对 `ProductionSeedTemplateService` 零引用），
         * 而线上后果是建单 fail-closed 422（#4316 回归）。</p>
         *
         * <p>入参口径：申请单里 industry 是**自由文本**（「布艺」），
         * `IndustryCodes.normalize` 归一为受控 code `curtain` 才能当模板键 ——
         * 断言用归一后的值，正是为了钉住「不归一 ⇒ 取不到模板 ⇒ 静默落空库」这条链。</p>
         */
        @Test
        @DisplayName("开租播种（#4430）：审批通过 → 按行业套用生产种子模板（入参 = 新租户 id + 归一行业码）")
        void successAppliesProductionSeedTemplate() {
            pendingApp.setIndustry("布艺");
            when(applicationMapper.selectById(1L)).thenReturn(pendingApp);
            doAnswer(inv -> { ((com.migao.admin.entity.Tenant) inv.getArgument(0)).setId(100L); return 1; })
                    .when(tenantMapper).insert(any(com.migao.admin.entity.Tenant.class));
            mockRoleInsertIds();
            when(userService.createUser(anyString(), anyString(), anyString(), eq("admin"), anyString(), isNull(), eq(100L)))
                    .thenReturn(new User());

            registrationService.approveApplication(1L, "reviewer-001");

            verify(productionSeedTemplateService).applyTemplate(100L, "curtain");
        }

        /**
         * 开租播种的**失败降级**语义（issue #4430 / B2）：种子套用抛异常时
         * **开租仍成功、异常不外抛**（{@code RegistrationService.applyProductionSeedTemplate}
         * 的 javadoc 明写：「开租可用」优先于「种子齐全」，可经 seed-templates/curtain/apply 补套）。
         *
         * <p>反向红线：若把 {@code catch} 去掉（改成上抛），本断言必红 —— 那会把已建好的租户、
         * 默认角色权限、管理员用户一起回滚，客户拿不到账号、申请单仍停在 pending。</p>
         */
        @Test
        @DisplayName("开租播种失败降级（#4430）：applyTemplate 抛异常 → 开租仍成功、异常不外抛")
        void successWhenSeedTemplateFails() {
            pendingApp.setIndustry("布艺");
            when(applicationMapper.selectById(1L)).thenReturn(pendingApp);
            doAnswer(inv -> { ((com.migao.admin.entity.Tenant) inv.getArgument(0)).setId(100L); return 1; })
                    .when(tenantMapper).insert(any(com.migao.admin.entity.Tenant.class));
            mockRoleInsertIds();
            when(userService.createUser(anyString(), anyString(), anyString(), eq("admin"), anyString(), isNull(), eq(100L)))
                    .thenReturn(new User());
            when(productionSeedTemplateService.applyTemplate(anyLong(), anyString()))
                    .thenThrow(new IllegalStateException("种子套用失败（模拟：工序库写入异常）"));

            registrationService.approveApplication(1L, "reviewer-001");

            // 调用点**确实存在**（删掉 `applyProductionSeedTemplate(tenant)` 那一行本断言即红）
            verify(productionSeedTemplateService).applyTemplate(100L, "curtain");
            // 开租成功：租户 + 管理员用户照常建出来，申请单落到 approved
            verify(tenantMapper).insert(any(com.migao.admin.entity.Tenant.class));
            verify(userService).createUser(anyString(), anyString(), anyString(), eq("admin"), anyString(), isNull(), eq(100L));
            assertThat(pendingApp.getStatus()).isEqualTo("approved");
        }

        @Test
        @DisplayName("审批通过携带 AI 甄别元数据 → 落库 review_* 列")
        void successWithReviewMeta() {
            pendingApp.setId(1L);
            when(applicationMapper.selectById(1L)).thenReturn(pendingApp);
            doAnswer(inv -> { ((com.migao.admin.entity.Tenant) inv.getArgument(0)).setId(100L); return 1; })
                    .when(tenantMapper).insert(any(com.migao.admin.entity.Tenant.class));
            when(userService.createUser(anyString(), anyString(), anyString(), eq("admin"), anyString(), isNull(), eq(100L)))
                    .thenReturn(new User());

            registrationService.approveApplication(1L, "ai",
                    new RegistrationService.ApplicationReview("ai", "[{\"level\":\"medium\"}]", "合规审查通过"));

            assertThat(pendingApp.getReviewSource()).isEqualTo("ai");
            assertThat(pendingApp.getRiskFlags()).contains("medium");
            assertThat(pendingApp.getReviewSummary()).isEqualTo("合规审查通过");
        }

        @Test
        @DisplayName("已处理的申请 → VALIDATION_ERROR")
        void alreadyProcessed() {
            pendingApp.setStatus("approved");
            when(applicationMapper.selectById(1L)).thenReturn(pendingApp);

            assertThatThrownBy(() -> registrationService.approveApplication(1L, "reviewer-001"))
                    .isInstanceOf(BusinessException.class)
                    .satisfies(ex -> assertThat(((BusinessException) ex).getCode()).isEqualTo("VALIDATION_ERROR"));
        }
    }

    @Nested
    @DisplayName("rejectApplication")
    class Reject {

        @Test
        @DisplayName("驳回成功 → rejected")
        void success() {
            when(applicationMapper.selectById(1L)).thenReturn(pendingApp);

            registrationService.rejectApplication(1L, "reviewer-001", "资料不全");

            verify(applicationMapper).selectById(1L);
            assertThat(pendingApp.getStatus()).isEqualTo("rejected");
            assertThat(pendingApp.getRejectReason()).isEqualTo("资料不全");
        }

        @Test
        @DisplayName("已处理的申请 → VALIDATION_ERROR")
        void alreadyProcessed() {
            pendingApp.setStatus("rejected");
            when(applicationMapper.selectById(1L)).thenReturn(pendingApp);

            assertThatThrownBy(() -> registrationService.rejectApplication(1L, "r1", "x"))
                    .isInstanceOf(BusinessException.class);
        }
    }
}
