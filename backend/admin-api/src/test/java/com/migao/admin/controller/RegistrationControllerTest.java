package com.migao.admin.controller;

import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.RegistrationRequest;
import com.migao.admin.dto.RegistrationResponse;
import com.migao.admin.dto.RegistrationReviewRequest;
import com.migao.admin.entity.TenantApplication;
import com.migao.admin.service.RegistrationService;
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
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * RegistrationController 单元测试
 * 覆盖：公开注册（happy path + validation error）、超管查询、审批
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("RegistrationController 企业入驻测试")
class RegistrationControllerTest extends BaseControllerTest {

    private MockMvc mockMvc;

    @Mock
    private RegistrationService registrationService;

    @InjectMocks
    private RegistrationController registrationController;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        setSuperAdminUser(); // 覆盖为 super_admin，匹配 checkSuperAdminPermission() 新逻辑
        mockMvc = buildMockMvc(registrationController);
    }

    @AfterEach
    void tearDown() {
        super.baseTearDown();
    }

    // ======================== 公开注册 ========================

    @Test
    @DisplayName("submitRegistration — 提交入驻申请成功 → 200")
    void submitRegistration_success() throws Exception {
        RegistrationResponse response = RegistrationResponse.builder()
                .applicationId(100L)
                .status("pending")
                .message("入驻申请已提交，我们将尽快审核")
                .build();
        when(registrationService.submitApplication(any(RegistrationRequest.class)))
                .thenReturn(response);

        mockMvc.perform(post("/api/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(validRegistrationRequest())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.applicationId").value(100))
                .andExpect(jsonPath("$.data.status").value("pending"))
                .andExpect(jsonPath("$.data.message").value("入驻申请已提交，我们将尽快审核"));

        verify(registrationService).submitApplication(any(RegistrationRequest.class));
    }

    @Test
    @DisplayName("submitRegistration — 缺少必填字段 → 422")
    void submitRegistration_missingRequiredFields() throws Exception {
        mockMvc.perform(post("/api/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"));
    }

    // ======================== 超管查询 ========================

    @Test
    @DisplayName("getRegistrations — 查询入驻申请列表 → 200")
    void getRegistrations_success() throws Exception {
        TenantApplication app = TenantApplication.builder()
                .id(1L)
                .companyName("测试企业")
                .contactName("张三")
                .phone("13800138000")
                .status("pending")
                .build();

        PageResponse<TenantApplication> page = PageResponse.of(1L, 1L, 10L, List.of(app));
        when(registrationService.getApplications(eq("pending"), eq(1), eq(10)))
                .thenReturn(page);

        mockMvc.perform(get("/api/super-admin/registrations")
                        .param("status", "pending")
                        .param("page", "1")
                        .param("size", "10"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.total").value(1))
                .andExpect(jsonPath("$.data.items[0].companyName").value("测试企业"));

        verify(registrationService).getApplications(eq("pending"), eq(1), eq(10));
    }

    @Test
    @DisplayName("getRegistrationDetail — 查询入驻申请详情 → 200")
    void getRegistrationDetail_success() throws Exception {
        TenantApplication app = TenantApplication.builder()
                .id(1L)
                .companyName("测试企业")
                .contactName("张三")
                .phone("13800138000")
                .status("pending")
                .build();
        when(registrationService.getApplicationDetail(1L)).thenReturn(app);

        mockMvc.perform(get("/api/super-admin/registrations/1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.id").value(1))
                .andExpect(jsonPath("$.data.companyName").value("测试企业"));

        verify(registrationService).getApplicationDetail(1L);
    }

    @Test
    @DisplayName("getRegistrations — 非管理员 → 403")
    void getRegistrations_nonAdmin() throws Exception {
        setOperatorUser();

        mockMvc.perform(get("/api/super-admin/registrations")
                        .param("page", "1")
                        .param("size", "10"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("PERMISSION_DENIED"));
    }

    // ======================== 审批 ========================

    @Test
    @DisplayName("approveRegistration — 审批通过 → 200")
    void approveRegistration_success() throws Exception {
        mockMvc.perform(put("/api/super-admin/registrations/1/approve"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));

        verify(registrationService).approveApplication(eq(1L), eq(TEST_USER_ID));
    }

    @Test
    @DisplayName("rejectRegistration — 驳回申请 → 200")
    void rejectRegistration_success() throws Exception {
        RegistrationReviewRequest request = new RegistrationReviewRequest();
        request.setRejectReason("不符合入驻条件");

        mockMvc.perform(put("/api/super-admin/registrations/1/reject")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));

        verify(registrationService).rejectApplication(eq(1L), eq(TEST_USER_ID), eq("不符合入驻条件"));
    }

    // ======================== helper ========================

    private static RegistrationRequest validRegistrationRequest() {
        RegistrationRequest req = new RegistrationRequest();
        req.setCompanyName("测试企业");
        req.setContactName("张三");
        req.setPhone("13800138000");
        req.setSmsCode("123456");
        req.setIndustry("布艺纺织");
        req.setAddress("浙江省杭州市");
        return req;
    }
}
