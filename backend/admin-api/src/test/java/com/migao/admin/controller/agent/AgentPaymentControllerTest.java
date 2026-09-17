package com.migao.admin.controller.agent;

// case_ids: ST-011

import com.migao.admin.config.TenantContext;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.entity.TenantPaymentQrcode;
import com.migao.admin.mapper.TenantPaymentQrcodeMapper;
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
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * AgentPaymentController 单元测试（C 端收款二维码展示，issue #3990）
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("AgentPaymentController 收款二维码")
class AgentPaymentControllerTest {

    private MockMvc mockMvc;

    @Mock
    private TenantPaymentQrcodeMapper paymentQrcodeMapper;

    @InjectMocks
    private AgentPaymentController agentPaymentController;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(1L);
        mockMvc = MockMvcBuilders.standaloneSetup(agentPaymentController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Test
    @DisplayName("GET 收款二维码 -> 按类型返回精简字段")
    void returnsLiteQrcodes() throws Exception {
        var wechat = TenantPaymentQrcode.builder()
                .id("qr-1").tenantId(1L).paymentType("wechat")
                .imageUrl("https://img/wechat.png").payeeName("亿家纺织")
                .status("active").deleted(0).build();
        when(paymentQrcodeMapper.selectList(any())).thenReturn(List.of(wechat));

        mockMvc.perform(get("/api/admin/agent/payment-qrcodes"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.wechat.imageUrl").value("https://img/wechat.png"))
                .andExpect(jsonPath("$.data.wechat.payeeName").value("亿家纺织"));
    }

    @Test
    @DisplayName("无收款码 -> 返回空对象")
    void returnsEmptyWhenNone() throws Exception {
        when(paymentQrcodeMapper.selectList(any())).thenReturn(List.of());
        mockMvc.perform(get("/api/admin/agent/payment-qrcodes"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));
    }
}
