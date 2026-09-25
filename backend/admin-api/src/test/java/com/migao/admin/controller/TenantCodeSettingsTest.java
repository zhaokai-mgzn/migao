// case_ids: AU-009
package com.migao.admin.controller;

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Tenant;
import com.migao.admin.mapper.TenantAiConfigMapper;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.service.AuditLogService;
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
import org.springframework.dao.DuplicateKeyException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 企业编码由管理员设置（issue #5485 AU-009）。
 *
 * <p>端点复用「企业基础信息」既有的 {@code PUT /api/admin/settings}（权限码 {@code system:manage}，
 * {@code GET} 侧本来就把 {@code code} 放在响应里）—— **不新造端点、不新造权限码**。</p>
 *
 * <p>三条校验（都返回 <b>422 + 明确文案</b>）：格式 / 全平台唯一（大小写不敏感、排除自己）/ 保留字。
 * 另加一条**存量兼容不变式**：编码**未变更**时跳过校验（管理员原样保存不能被自己的新校验拒掉），
 * 以及**字符集包含下划线**（dev 库现存 {@code tenant_7478359537} 这种存量编码）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("企业编码设置（格式 / 唯一 / 保留字）")
class TenantCodeSettingsTest {

    private MockMvc mockMvc;

    @Mock
    private TenantMapper tenantMapper;
    @Mock
    private TenantAiConfigMapper tenantAiConfigMapper;
    @Mock
    private AuditLogService auditLogService;
    @Mock
    private UserMapper userMapper;
    @Mock
    private PasswordEncoder passwordEncoder;
    @Mock
    private com.migao.admin.mapper.TenantPaymentQrcodeMapper paymentQrcodeMapper;

    @InjectMocks
    private SettingsController settingsController;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(settingsController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
        TenantContext.setTenantId(1L);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    private void givenCurrentCode(String code) {
        when(tenantMapper.selectById(1L)).thenReturn(
                Tenant.builder().id(1L).name("甲公司").code(code).status("active").build());
    }

    private org.springframework.test.web.servlet.ResultActions putCode(String code) throws Exception {
        return mockMvc.perform(put("/api/admin/settings")
                .contentType("application/json")
                .content("{\"code\":\"" + code + "\"}"));
    }

    // ======================== 通过 ========================

    @Test
    @DisplayName("AU-009 合法编码 ⇒ 200 且响应带出新编码")
    void validCode_accepted() throws Exception {
        givenCurrentCode("tenant_1000000001");
        when(tenantMapper.selectOne(any())).thenReturn(null);

        putCode("acme-fabric")
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.code").value("acme-fabric"));
    }

    @Test
    @DisplayName("AU-009 大写输入 ⇒ 规整为小写后接受（大小写不敏感）")
    void uppercaseNormalized() throws Exception {
        givenCurrentCode("tenant_1000000001");
        when(tenantMapper.selectOne(any())).thenReturn(null);

        putCode("AcmeFabric")
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.code").value("acmefabric"));
    }

    @Test
    @DisplayName("AU-009 存量带下划线的编码：可原样保留、也可改成另一个带下划线的形态（零数据迁移）")
    void underscoreLegacyCodes_accepted() throws Exception {
        givenCurrentCode("tenant_7478359537");
        when(tenantMapper.selectOne(any())).thenReturn(null);

        // 原样保存（未变更 ⇒ 跳过校验）—— 这是「管理员打开企业基础信息直接保存」的真实路径
        putCode("tenant_7478359537").andExpect(status().isOk());
        // 改成另一个带下划线的编码（字符集含 `_`）—— 否则那两个存量租户的员工永远登不进来
        putCode("fabric_2026").andExpect(status().isOk());
    }

    @Test
    @DisplayName("AU-009 编码未变更时**跳过**格式/保留字校验（存量保留字形态也能原样保存）")
    void unchangedCode_skipsValidation() throws Exception {
        givenCurrentCode("admin");

        // 原样保存 ⇒ 成功（校验只作用于变更；否则该页 name/logo/通知开关会一起存不了）
        putCode("admin").andExpect(status().isOk()).andExpect(jsonPath("$.data.code").value("admin"));
    }

    // ======================== 拒绝（全部 422 + 明确文案） ========================

    @Test
    @DisplayName("AU-009 格式不合规（大写保留字/空格/@/超长/单字符）⇒ 422 + 明确文案")
    void invalidFormat_rejectedWith422() throws Exception {
        givenCurrentCode("acme");

        for (String bad : new String[]{"BAD CODE", "ab@cd", "a", "x".repeat(33), "9-".repeat(20)}) {
            putCode(bad)
                    .andExpect(status().isUnprocessableEntity())
                    .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                    .andExpect(jsonPath("$.error.message").value(
                            org.hamcrest.Matchers.containsString("企业编码不合法")));
        }
    }

    @Test
    @DisplayName("AU-009 保留字黑名单（admin/api/www/app/platform/support/system/root/login/auth）⇒ 422")
    void reservedWords_rejectedWith422() throws Exception {
        givenCurrentCode("acme");

        for (String reserved : new String[]{"admin", "api", "www", "app", "platform",
                "support", "system", "root", "login", "auth"}) {
            putCode(reserved)
                    .andExpect(status().isUnprocessableEntity())
                    .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                    .andExpect(jsonPath("$.error.message").value(
                            org.hamcrest.Matchers.containsString("保留字")));
        }
    }

    @Test
    @DisplayName("AU-009 全平台已被占用（大小写不敏感、排除自己）⇒ 422 + 「换一个」")
    void occupied_rejectedWith422() throws Exception {
        givenCurrentCode("acme");
        when(tenantMapper.selectOne(any())).thenReturn(
                Tenant.builder().id(20L).code("taken-code").status("active").build());

        putCode("taken-code")
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                .andExpect(jsonPath("$.error.message").value(
                        org.hamcrest.Matchers.containsString("已被其他企业占用")));
    }

    @Test
    @DisplayName("AU-009 并发兜底：唯一约束冲突 ⇒ 转 422，不裸抛 500")
    void uniqueConstraintRace_convertedTo422() throws Exception {
        givenCurrentCode("acme");
        when(tenantMapper.selectOne(any())).thenReturn(null);
        when(tenantMapper.update(any(), any())).thenThrow(new DuplicateKeyException("tenants_code_key"));

        putCode("racing-code")
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                .andExpect(jsonPath("$.error.message").value(
                        org.hamcrest.Matchers.containsString("已被占用")));
    }

    @Test
    @DisplayName("AU-009 空编码 ⇒ 422（不静默忽略，也不误当成「未变更」）")
    void emptyCode_rejected() throws Exception {
        givenCurrentCode("acme");

        putCode("")
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.message").value("企业编码不能为空"));
    }
}