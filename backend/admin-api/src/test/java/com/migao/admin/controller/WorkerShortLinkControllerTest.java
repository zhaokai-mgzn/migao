// case_ids: PG-018, BM-006, DF-017, BM-045, BM-058
package com.migao.admin.controller;

import com.migao.admin.entity.ProcessingSetPartToken;
import com.migao.admin.entity.Tenant;
import com.migao.admin.mapper.ProcessingSetPartTokenMapper;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.service.WorkerShortLinkService;
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
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 工人端**稳定短链** {@code GET /s/{shortCode}}（issue #4802；设计
 * {@code docs/design/worker-h5-scan-and-report.md} §1.3 / §1.4 / §7.2）。
 *
 * <h2>红证（改前必红）</h2>
 * 改前（{@code origin/main}）本路径**没有路由**、且不在 {@code permitAll} ⇒ 未认证请求拿到
 * **401**（不是跳转，也不是 404）；本类的 {@code knownShortCodeRedirectsToReportPage} 在改前必红
 * （实测读数见 PR body 与 {@code SecurityConfigTest#shortLinkIsPublic}）。
 *
 * <h2>反向护栏（每条都对着一个真实缺陷形态）</h2>
 * <ul>
 *   <li><b>服务端 302</b>（不是前端 JS 跳转）：断言 HTTP **状态码 + Location 头** ——
 *       部分扫码工具只认服务端跳转（用户裁定③）；</li>
 *   <li><b>撤销 ⇒ 410</b>（不是 404、更不是「静默回落到别的码」）：{@code token} 置 NULL = 这张纸作废；</li>
 *   <li><b>不泄露身份 / 权限</b>：响应体**为空**，Location 逐字等于
 *       {@code /b/report/?t=<token>&tenant_id=<id>&tenant_code=<code>}（不含工人 id/姓名/权限/订单/工序）；</li>
 *   <li><b>冻结契约未被扩</b>：{@code /s/<32 位 token>} ⇒ **404** 且**一次库都不查**
 *       —— 本路径**只**认短码，{@code resolveOrder} / {@code resolve} 的既有五形态一字未动；</li>
 *   <li><b>手输可抄形态</b>：小写 / {@code O}/{@code I}/{@code L} 抄错形态 ⇒ 仍 302 到同一 token。</li>
 * </ul>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("稳定短链 /s/{短码} ⇒ 服务端 302（issue #4802）")
class WorkerShortLinkControllerTest {

    private static final String PART_CODE = "fake-part-code-fixture-4802";
    private static final String SHORT_CODE = "7K3M9QP2";
    /** 末位是 `0` / `1` 的短码：用来钉「抄成 O / I / L 仍能换回 token」。 */
    private static final String CODE_ZERO = "7K3M9QP0";
    private static final String CODE_ONE = "7K3M9QP1";

    @Mock
    private WorkerShortLinkService workerShortLinkService;

    @InjectMocks
    private WorkerShortLinkController controller;

    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(controller).build();
    }

    private static ProcessingSetPartToken row(String token, String shortCode) {
        return ProcessingSetPartToken.builder()
                .id("t-1").tenantId(7L).processingOrderId("po-1").setId("set-1")
                .orderItemId("i-1").positionKind("布帘").token(token).shortCode(shortCode)
                .deleted(0).build();
    }

    /** 用**真实**服务层装配（判归一化/查重口径时必须是真的，mock 掉就测不到形态判定）。 */
    private static MockMvc realMvc(ProcessingSetPartTokenMapper mapper) {
        TenantMapper tenantMapper = mock(TenantMapper.class);
        when(tenantMapper.selectOne(any()))
                .thenReturn(Tenant.builder().id(7L).code("migao").status("active").build());
        return MockMvcBuilders
                .standaloneSetup(new WorkerShortLinkController(
                        new WorkerShortLinkService(mapper, tenantMapper)))
                .build();
    }

    // ────────────────────────────────────────────── ① 302（核心判据）

    @Test
    @DisplayName("🔴 已知短码 ⇒ **302** + Location = 报工页（改前无此路由/未放行 ⇒ 必红）")
    void knownShortCodeRedirectsToReportPage() throws Exception {
        when(workerShortLinkService.resolve(anyString())).thenReturn(row(PART_CODE, SHORT_CODE));
        when(workerShortLinkService.tenantCodeOf(7L)).thenReturn("migao");

        mockMvc.perform(get("/s/" + SHORT_CODE))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", "/b/report/?t=" + PART_CODE + "&tenant_id=7&tenant_code=migao"))
                // 不泄露身份/权限：响应体为空
                .andExpect(content().string(""));
    }

    @Test
    @DisplayName("手输抄错形态（小写 / O→0 / I→1 / L→1）⇒ 同样 302（归一化只有服务层一份）")
    void humanTypedFormsStillRedirect() throws Exception {
        ProcessingSetPartTokenMapper mapper = mock(ProcessingSetPartTokenMapper.class);
        when(mapper.selectByShortCode(CODE_ZERO)).thenReturn(row(PART_CODE, CODE_ZERO));
        when(mapper.selectByShortCode(CODE_ONE)).thenReturn(row("a".repeat(32), CODE_ONE));
        MockMvc real = realMvc(mapper);

        real.perform(get("/s/7k3m9qp0"))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", "/b/report/?t=" + PART_CODE + "&tenant_id=7&tenant_code=migao"));
        real.perform(get("/s/7K3M9QPO"))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", "/b/report/?t=" + PART_CODE + "&tenant_id=7&tenant_code=migao"));
        real.perform(get("/s/7K3M9QPI"))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", "/b/report/?t=" + "a".repeat(32) + "&tenant_id=7&tenant_code=migao"));
        real.perform(get("/s/7K3M9QPL"))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", "/b/report/?t=" + "a".repeat(32) + "&tenant_id=7&tenant_code=migao"));
    }

    // ────────────────────────────────────────────── ② 未知 / 已撤销

    @Test
    @DisplayName("未知短码 ⇒ 404（且**没有** Location 头 = 没有跳转）")
    void unknownShortCodeIsNotFound() throws Exception {
        when(workerShortLinkService.resolve(anyString())).thenReturn(null);

        mockMvc.perform(get("/s/ZZZZZZZZ"))
                .andExpect(status().isNotFound())
                .andExpect(header().doesNotExist("Location"));
    }

    @Test
    @DisplayName("🔴 已撤销（token 置 NULL）⇒ **410**（不是 404、不静默回落 —— 这张纸作废）")
    void revokedShortCodeIsGone() throws Exception {
        when(workerShortLinkService.resolve(anyString())).thenReturn(row(null, SHORT_CODE));

        mockMvc.perform(get("/s/" + SHORT_CODE))
                .andExpect(status().isGone())
                .andExpect(header().doesNotExist("Location"));
    }

    // ────────────────────────────────────────────── ③ 冻结契约 / 长 token 路径

    @Test
    @DisplayName("🔴 /s/ **只**认短码：喂 32 位 token 进去 ⇒ 404 且一次库都不查（token 解析语义一字未扩）")
    void shortLinkDoesNotAcceptRawToken() throws Exception {
        ProcessingSetPartTokenMapper mapper = mock(ProcessingSetPartTokenMapper.class);
        MockMvc real = realMvc(mapper);

        real.perform(get("/s/" + PART_CODE))
                .andExpect(status().isNotFound())
                .andExpect(header().doesNotExist("Location"));
        verify(mapper, never()).selectByShortCode(anyString());

        // 反向自证（防「恒 404」）：同一个真实实现 + 合法短码 ⇒ 302
        when(mapper.selectByShortCode(SHORT_CODE)).thenReturn(row(PART_CODE, SHORT_CODE));
        real.perform(get("/s/" + SHORT_CODE))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", "/b/report/?t=" + PART_CODE + "&tenant_id=7&tenant_code=migao"));
    }

    @Test
    @DisplayName("企业编码取不到（租户非 active / 查不到）⇒ 302 仍带 tenant_id，只是不带 tenant_code（旧前端兼容）")
    void locationOmitsTenantCodeWhenUnavailable() throws Exception {
        when(workerShortLinkService.resolve(anyString())).thenReturn(row(PART_CODE, SHORT_CODE));
        when(workerShortLinkService.tenantCodeOf(7L)).thenReturn(null);

        mockMvc.perform(get("/s/" + SHORT_CODE))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", "/b/report/?t=" + PART_CODE + "&tenant_id=7"));
    }

    @Test
    @DisplayName("🔴 302 的 Location **追加** tenant_code（企业编码）—— 路径段与短码契约一字未动")
    void locationCarriesEnterpriseCodeAfterTenantId() throws Exception {
        when(workerShortLinkService.resolve(anyString())).thenReturn(row(PART_CODE, SHORT_CODE));
        when(workerShortLinkService.tenantCodeOf(7L)).thenReturn("migao");

        mockMvc.perform(get("/s/" + SHORT_CODE))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", "/b/report/?t=" + PART_CODE + "&tenant_id=7&tenant_code=migao"));
        verify(workerShortLinkService).tenantCodeOf(7L);
    }

    // ────────────────────────────────────────────── ④ JSON 解析（issue #8196 A 档）

    /**
     * 微信「扫普通链接二维码打开小程序」的 A 档：小程序**不跟随 HTTP 302**
     * （页面拿到的是 EnterOptions 里的 `q` = 完整链接）⇒ 同一个短码必须还有一份**显式**的
     * JSON 解析面，否则小程序只能看到一张 302 空响应。
     *
     * <p>落点选**显式子路径** `/s/{短码}/json` 而**不是**内容协商（`Accept: application/json`）——
     * 理由见 {@link WorkerShortLinkController#resolveJson}（印刷品红线：不带 Accept / 带 `*&#47;*` 的
     * 扫码工具会在内容协商下从 302 变成 JSON）。本组判据把这条决策钉死：JSON 面在**自己的路径**上，
     * 浏览器姿态（`Accept: text/html` 或干脆带 `Accept: application/json`）打到 `GET /s/{短码}` 仍是 302。</p>
     */
    @Test
    @DisplayName("🔴 JSON 解析面：GET /s/{短码}/json ⇒ 200 + reportPath/token（小程序 A 档用，改前 404 必红）")
    void jsonResolveReturnsReportPathAndToken() throws Exception {
        when(workerShortLinkService.resolve(anyString())).thenReturn(row(PART_CODE, SHORT_CODE));

        mockMvc.perform(get("/s/" + SHORT_CODE + "/json"))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.reportPath").value("/b/report/"))
                .andExpect(jsonPath("$.token").value(PART_CODE))
                // 🔴 不泄露超出 302 目标的信息：**只有** 302 的 Location 里那两个可用字段
                // （报告路径 + token）；工人身份 / 工序 / 订单 / 价格一律不出现。
                .andExpect(jsonPath("$.tenantId").doesNotExist())
                .andExpect(jsonPath("$.tenantCode").doesNotExist())
                .andExpect(jsonPath("$.workerId").doesNotExist())
                .andExpect(jsonPath("$.orderNo").doesNotExist())
                .andExpect(jsonPath("$.operation").doesNotExist())
                .andExpect(header().doesNotExist("Location"));
        // JSON 面**不查**企业编码（那是 302 才需要的登录预填参数）⇒ 少一次库、也少一项可泄露面
        verify(workerShortLinkService, never()).tenantCodeOf(any());
    }

    @Test
    @DisplayName("🔴 印刷品红线：`GET /s/{短码}` **不因 Accept** 变成 JSON —— 浏览器与扫码工具永远拿到 302")
    void browserPathStays302WhateverTheAcceptHeader() throws Exception {
        when(workerShortLinkService.resolve(anyString())).thenReturn(row(PART_CODE, SHORT_CODE));
        when(workerShortLinkService.tenantCodeOf(7L)).thenReturn("migao");

        String expected = "/b/report/?t=" + PART_CODE + "&tenant_id=7&tenant_code=migao";
        // 浏览器姿态
        mockMvc.perform(get("/s/" + SHORT_CODE).header("Accept", "text/html,application/xhtml+xml"))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", expected));
        // 即使客户端明说想要 JSON，旧的短码路径也**不**换语义（否则不带/带 */* 的扫码工具会静默失联）
        mockMvc.perform(get("/s/" + SHORT_CODE).header("Accept", MediaType.APPLICATION_JSON_VALUE))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", expected));
        // 没有 Accept 头（部分扫码工具）同样是 302
        mockMvc.perform(get("/s/" + SHORT_CODE))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", expected));
    }

    @Test
    @DisplayName("未知短码 ⇒ JSON 面 404（可判读的 error 体，且不含任何 token）")
    void jsonResolveUnknownIs404() throws Exception {
        when(workerShortLinkService.resolve(anyString())).thenReturn(null);

        mockMvc.perform(get("/s/ZZZZZZZZ/json"))
                .andExpect(status().isNotFound())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.error").value("not_found"))
                .andExpect(jsonPath("$.token").doesNotExist())
                .andExpect(jsonPath("$.reportPath").doesNotExist());
    }

    @Test
    @DisplayName("🔴 已撤销（token 置 NULL）⇒ JSON 面 **410**（不是 404、不落任何可用的 token）")
    void jsonResolveRevokedIs410() throws Exception {
        when(workerShortLinkService.resolve(anyString())).thenReturn(row(null, SHORT_CODE));

        mockMvc.perform(get("/s/" + SHORT_CODE + "/json"))
                .andExpect(status().isGone())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.error").value("revoked"))
                .andExpect(jsonPath("$.token").doesNotExist());
    }

    @Test
    @DisplayName("手输抄错形态在 JSON 面同样归一（小写 / O→0）—— 归一化仍只有服务层一份")
    void jsonResolveNormalizesHumanTypedForms() throws Exception {
        ProcessingSetPartTokenMapper mapper = mock(ProcessingSetPartTokenMapper.class);
        when(mapper.selectByShortCode(CODE_ZERO)).thenReturn(row(PART_CODE, CODE_ZERO));
        MockMvc real = realMvc(mapper);

        real.perform(get("/s/7k3m9qp0/json"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.token").value(PART_CODE));
        real.perform(get("/s/7K3M9QPO/json"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.token").value(PART_CODE));
    }

    @Test
    @DisplayName("JSON 面**只**认短码：喂 32 位 token 进去 ⇒ 404（token 解析语义一字未扩）")
    void jsonResolveDoesNotAcceptRawToken() throws Exception {
        ProcessingSetPartTokenMapper mapper = mock(ProcessingSetPartTokenMapper.class);
        MockMvc real = realMvc(mapper);

        real.perform(get("/s/" + PART_CODE + "/json"))
                .andExpect(status().isNotFound());
        verify(mapper, never()).selectByShortCode(anyString());
    }
}
