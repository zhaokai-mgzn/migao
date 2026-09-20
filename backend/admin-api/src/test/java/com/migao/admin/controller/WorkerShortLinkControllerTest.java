// case_ids: PG-018, BM-006, DF-017
package com.migao.admin.controller;

import com.migao.admin.entity.ProcessingSetPartToken;
import com.migao.admin.mapper.ProcessingSetPartTokenMapper;
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
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
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
 *       {@code /w/?t=<token>&tenant_id=<id>}（不含工人 id/姓名/权限/订单/工序）；</li>
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
        return MockMvcBuilders
                .standaloneSetup(new WorkerShortLinkController(new WorkerShortLinkService(mapper)))
                .build();
    }

    // ────────────────────────────────────────────── ① 302（核心判据）

    @Test
    @DisplayName("🔴 已知短码 ⇒ **302** + Location = 报工页（改前无此路由/未放行 ⇒ 必红）")
    void knownShortCodeRedirectsToReportPage() throws Exception {
        when(workerShortLinkService.resolve(anyString())).thenReturn(row(PART_CODE, SHORT_CODE));

        mockMvc.perform(get("/s/" + SHORT_CODE))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", "/w/?t=" + PART_CODE + "&tenant_id=7"))
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
                .andExpect(header().string("Location", "/w/?t=" + PART_CODE + "&tenant_id=7"));
        real.perform(get("/s/7K3M9QPO"))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", "/w/?t=" + PART_CODE + "&tenant_id=7"));
        real.perform(get("/s/7K3M9QPI"))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", "/w/?t=" + "a".repeat(32) + "&tenant_id=7"));
        real.perform(get("/s/7K3M9QPL"))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", "/w/?t=" + "a".repeat(32) + "&tenant_id=7"));
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
                .andExpect(header().string("Location", "/w/?t=" + PART_CODE + "&tenant_id=7"));
    }
}
