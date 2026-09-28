// case_ids: PR-113
package com.migao.admin.controller;

import com.migao.admin.entity.InboundLabel;
import com.migao.admin.mapper.InboundLabelMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.service.AuditLogService;
import com.migao.admin.service.InboundLabelService;
import com.migao.admin.service.InboundOrderService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 入库标签**公开入口** {@code GET /i/{短码}}（issue #5052 P2；设计 §5.2 / §7.1）。
 *
 * <h3>红证（改坏 ⇒ 必红）</h3>
 * <ul>
 *   <li>改前（{@code origin/main}）本路径**没有路由**且不在 {@code permitAll}
 *       ⇒ 未认证请求拿到 <b>401</b>（不是跳转、也不是 404）；{@code knownCodeRedirectsToLandingPage}
 *       在改前必红（安全链那一半见 {@code SecurityConfigTest#inboundLabelShortLinkIsPublic}）；</li>
 *   <li>把落地页地址硬编码成 {@code https://app.migaozn.com/b/} ⇒
 *       {@code landingPathComesFromConfiguration} 红（改配置不再影响 Location）；</li>
 *   <li>把 410 写成 404 ⇒ {@code revokedCodeIsGoneNotMissing} 红。</li>
 * </ul>
 *
 * <h3>公开入口**不**泄露什么（逐条断言）</h3>
 * <p>响应体为空；{@code Location} 里只有「落地页 + 短码 + 租户 id」——
 * 品名 / 色号 / 米数 / 供应商 / 单号一个都不出现（§5.2 逐字「只回跳转、不泄露业务字段」）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("入库标签公开入口 /i/{短码} ⇒ 服务端 302（#5052 P2）")
class InboundLabelShortLinkControllerTest {

    private static final String CODE = "7K3M9QP2";
    private static final String REVOKED_CODE = "4T7Y2BQ9";
    private static final Long TENANT = 7L;

    @Mock private InboundLabelMapper inboundLabelMapper;
    @Mock private InboundOrderService inboundOrderService;
    @Mock private ProductMapper productMapper;
    @Mock private AuditLogService auditLogService;

    private InboundLabelService inboundLabelService;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        inboundLabelService = new InboundLabelService(
                inboundLabelMapper, inboundOrderService, productMapper, auditLogService);
        mockMvc = MockMvcBuilders
                .standaloneSetup(new InboundLabelShortLinkController(inboundLabelService))
                .build();
    }

    @Test
    @DisplayName("🔴 有效短码 ⇒ 302 + 相对 Location（服务端跳转，不是前端 JS），响应体为空")
    void knownCodeRedirectsToLandingPage() throws Exception {
        when(inboundLabelMapper.selectByCode(CODE)).thenReturn(liveLabel(CODE));

        mockMvc.perform(get("/i/" + CODE))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", "/b/?code=" + CODE + "&tenant_id=" + TENANT))
                .andExpect(content().string(""));
    }

    @Test
    @DisplayName("🔴 只回跳转、不泄露业务字段：Location 里没有品名 / 米数 / 供应商 / 单号")
    void theRedirectLeaksNoBusinessFields() throws Exception {
        when(inboundLabelMapper.selectByCode(CODE)).thenReturn(liveLabel(CODE));

        String location = mockMvc.perform(get("/i/" + CODE))
                .andExpect(status().isFound())
                .andReturn().getResponse().getHeader("Location");

        // 这条纸面码的落地页只需要「哪一张标签」+「哪个租户」——多一个字段都是越权面
        org.assertj.core.api.Assertions.assertThat(location)
                .doesNotContain("RK-", "PC-", "SKU-", "遮光", "60.5", "亿家");
        // 落地页那一跳也不该把服务端当跳板（相对 Location ⇒ 无开放重定向面）
        org.assertj.core.api.Assertions.assertThat(location).doesNotStartWith("http");
        // 手抄形态同样能打开（小写 / O→0 / I,L→1 —— 纸面的码是给人抄的）
        when(inboundLabelMapper.selectByCode("7K3M9QP0")).thenReturn(liveLabel("7K3M9QP0"));
        mockMvc.perform(get("/i/7k3m9qpo"))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", "/b/?code=7K3M9QP0&tenant_id=" + TENANT));
    }

    @Test
    @DisplayName("🔴 落地页地址来自**单一配置**：改配置即改 Location（源码里没有硬编码域名）")
    void landingPathComesFromConfiguration() throws Exception {
        when(inboundLabelMapper.selectByCode(CODE)).thenReturn(liveLabel(CODE));

        ReflectionTestUtils.setField(inboundLabelService, "landingPath", "/b/label");
        mockMvc.perform(get("/i/" + CODE))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", "/b/label?code=" + CODE + "&tenant_id=" + TENANT));
    }

    @Test
    @DisplayName("未知短码 ⇒ 404；形态不合法 ⇒ 404 且一次库都不查")
    void unknownCodeIs404() throws Exception {
        when(inboundLabelMapper.selectByCode(anyString())).thenReturn(null);

        mockMvc.perform(get("/i/ZZZZZZZZ")).andExpect(status().isNotFound());
        mockMvc.perform(get("/i/abc")).andExpect(status().isNotFound());
        mockMvc.perform(get("/i/7K3M-9QP")).andExpect(status().isNotFound());
        mockMvc.perform(get("/i/7K3M9QP2X")).andExpect(status().isNotFound());
        // 形态不合法的一个都不该落到库上（只允许那一次合法形态的查询）
        verify(inboundLabelMapper, org.mockito.Mockito.times(1)).selectByCode("ZZZZZZZZ");
    }

    @Test
    @DisplayName("🔴 已撤销 ⇒ 410 Gone（不是 404：撤销不能被读成「没这个码」）")
    void revokedCodeIsGoneNotMissing() throws Exception {
        when(inboundLabelMapper.selectByCode(REVOKED_CODE)).thenReturn(revokedLabel(REVOKED_CODE));

        mockMvc.perform(get("/i/" + REVOKED_CODE))
                .andExpect(status().isGone())
                .andExpect(content().string(""));
    }

    // ============================================================ 夹具

    private static InboundLabel liveLabel(String code) {
        return InboundLabel.builder().id("label-1").tenantId(TENANT).inboundOrderId("order-1")
                .inboundItemId(1L).shortCode(code).printCount(0).deleted(0).build();
    }

    private static InboundLabel revokedLabel(String code) {
        return InboundLabel.builder().id("label-1").tenantId(TENANT).inboundOrderId("order-1")
                .inboundItemId(1L).shortCode(null).revokedCode(code).printCount(1).deleted(0).build();
    }
}
