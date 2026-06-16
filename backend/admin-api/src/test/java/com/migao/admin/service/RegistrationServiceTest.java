package com.migao.admin.service;

import com.migao.admin.dto.RegistrationRequest;
import com.migao.admin.dto.RegistrationResponse;
import com.migao.admin.entity.TenantApplication;
import com.migao.admin.entity.User;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.PermissionMapper;
import com.migao.admin.mapper.RoleMapper;
import com.migao.admin.mapper.TenantApplicationMapper;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.mapper.UserMapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("RegistrationService 入驻申请服务测试")
class RegistrationServiceTest extends BaseServiceTest {

    @Mock private TenantApplicationMapper applicationMapper;
    @Mock private TenantMapper tenantMapper;
    @Mock private UserService userService;
    @Mock private SmsService smsService;
    @Mock private UserMapper userMapper;
    @Mock private RoleMapper roleMapper;
    @Mock private PermissionMapper permissionMapper;

    @InjectMocks private RegistrationService registrationService;

    private TenantApplication pendingApp;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        pendingApp = TenantApplication.builder().id(1L).companyName("测试公司")
                .phone("13800138000").contactName("张三").status("pending").build();
    }

    private RegistrationRequest buildRequest() {
        RegistrationRequest req = new RegistrationRequest();
        req.setCompanyName("测试公司");
        req.setContactName("张三");
        req.setPhone("13800138000");
        req.setSmsCode("123456");
        req.setIndustry("布艺");
        return req;
    }

    @Nested
    @DisplayName("submitApplication")
    class Submit {

        @Test
        @DisplayName("提交成功 → pending")
        void success() {
            when(smsService.verifyCode("13800138000", "123456")).thenReturn(true);
            when(applicationMapper.selectOne(any())).thenReturn(null, null);

            RegistrationResponse resp = registrationService.submitApplication(buildRequest());

            assertThat(resp.getStatus()).isEqualTo("pending");
            assertThat(resp.getMessage()).contains("已提交");
        }

        @Test
        @DisplayName("短信验证码错误 → VALIDATION_ERROR")
        void invalidSms() {
            when(smsService.verifyCode("13800138000", "123456")).thenReturn(false);

            assertThatThrownBy(() -> registrationService.submitApplication(buildRequest()))
                    .isInstanceOf(BusinessException.class)
                    .satisfies(ex -> assertThat(((BusinessException) ex).getCode()).isEqualTo("VALIDATION_ERROR"));
        }

        @Test
        @DisplayName("已有待审批申请 → VALIDATION_ERROR")
        void duplicatePending() {
            when(smsService.verifyCode("13800138000", "123456")).thenReturn(true);
            when(applicationMapper.selectOne(any())).thenReturn(pendingApp);

            assertThatThrownBy(() -> registrationService.submitApplication(buildRequest()))
                    .isInstanceOf(BusinessException.class);
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
            User adminUser = new User();
            adminUser.setId("user-admin");
            when(userService.createUser(anyString(), anyString(), anyString(), eq("admin"), anyString(), isNull(), eq(100L)))
                    .thenReturn(adminUser);

            registrationService.approveApplication(1L, "reviewer-001");

            verify(userService).createUser(anyString(), anyString(), anyString(), eq("admin"), anyString(), isNull(), anyLong());
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
