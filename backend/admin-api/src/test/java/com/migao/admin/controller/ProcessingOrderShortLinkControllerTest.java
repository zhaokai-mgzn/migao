// case_ids: PG-018
package com.migao.admin.controller;

import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.Tenant;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingSetPartTokenMapper;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.service.ProcessingOrderShortLinkService;
import com.migao.admin.service.WorkerShortLinkService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 加工单级**公开短链** {@code GET /o/{shortCode}}（issue #6867 / 实现包 B2；设计
 * {@code docs/design/worker-h5-scan-and-report.md} §11.3 / §11.6 / §11.9(B2 行) / §11.10）。
 *
 * <h2>它钉什么（每条都对着一个真实缺陷形态）</h2>
 * <ul>
 *   <li><b>响应三形态</b>：命中且 {@code qr_token} 非空 ⇒ 302；短码未知 / 形态不合法 ⇒ 404；
 *       行在但 {@code qr_token} 为 NULL（已撤销）⇒ <b>410</b>（不是 404、更不是「静默回落到别的码」）；</li>
 *   <li><b>Location 三参数逐参断言</b>：{@code t} / {@code tenant_id} / {@code tenant_code}
 *       —— 与 {@code /s/} 逐字同款（带三参数，缺 {@code tenant_code} ⇒ 新前端登录口径下工人报不了工）；</li>
 *   <li><b>公开入口不泄露</b>：响应体为空，且 {@code Location} 的查询参数**恰好三个**
 *       （多一个参数 ⇒ 红：别把加工单号 / 客户名 / 工序 / 价格带进 URL）；</li>
 *   <li><b>撤销语义</b>：撤销 = {@code qr_token} 置 NULL、<b>{@code short_code} 一字未动</b>
 *       ⇒ 同一张纸先 410、重新发码后同一短码仍 302（已打印的纸不作废）；且本入口**只读**
 *       （对 {@code fillMissingShortCode} / {@code revokeQrToken} 一次都不调）；</li>
 *   <li><b>跨租户解析是刻意的</b>：公开入口没有租户上下文 ⇒ 必须走
 *       {@code selectByShortCodeGlobal}（{@code @InterceptorIgnore}），**不得**走带 {@code tenantId}
 *       的那个（那会让纸上的码恒 500 或恒 404）；</li>
 *   <li><b>类级（第二份拼装进不来）</b>：302 的 {@code Location} 只能由
 *       {@link WorkerShortLinkService#reportPageLocation} 拼 —— 本包的两个解析文件里
 *       **不得**出现自拼报工页的字面量。</li>
 * </ul>
 *
 * <h2>它不钉什么（如实登记）</h2>
 * 本类**不**证明「扫一张纸 ≠ 拿到数据」的**另一跳**：{@code /api/worker/**} 需要有效工人 session
 * （fail-closed ⇒ 无 session = 401）那一半由
 * {@code SecurityConfigTest#workerProductionScanWithoutWorkerSessionIsUnauthorized} 钉；
 * 也不证明真库上的部分唯一索引兜底（B1 的射程，见 {@code ProcessingOrderShortCodeMapperTest}）。
 */
@DisplayName("加工单级短链 /o/{短码} ⇒ 服务端 302（issue #6867 / B2）")
class ProcessingOrderShortLinkControllerTest {

    /** 8 位 Crockford Base32（末位 {@code 2} ⇒ 抄成 {@code O/I/L} 的别名红证另有专门用例）。 */
    private static final String SHORT_CODE = "7K3M9QP2";
    private static final String FIXTURE_TOKEN = "fake-po-code-fixture-6867";
    private static final String REISSUED_TOKEN = "fake-po-code-reissued-6867";

    private static ProcessingOrder row(String qrToken, String shortCode) {
        return ProcessingOrder.builder()
                .id("po-1").tenantId(7L).orderId("order-1")
                .processingOrderNo("JG-20261014-0001")
                .qrToken(qrToken).shortCode(shortCode).deleted(0).build();
    }

    /** 用**真实**服务层装配（归一化 / 跨租户解析 / Location 拼装都必须是生产那一份）。 */
    private static MockMvc realMvc(ProcessingOrderMapper orderMapper) {
        TenantMapper tenantMapper = mock(TenantMapper.class);
        when(tenantMapper.selectOne(any()))
                .thenReturn(Tenant.builder().id(7L).code("migao").status("active").build());
        WorkerShortLinkService shortLinkService =
                new WorkerShortLinkService(mock(ProcessingSetPartTokenMapper.class), tenantMapper);
        return MockMvcBuilders.standaloneSetup(
                new ProcessingOrderShortLinkController(
                        new ProcessingOrderShortLinkService(orderMapper), shortLinkService)).build();
    }

    private static Map<String, String> queryParams(String location) {
        Map<String, String> params = new LinkedHashMap<>();
        int mark = location.indexOf('?');
        assertThat(mark).as("Location 必须带查询串：%s", location).isGreaterThanOrEqualTo(0);
        for (String pair : location.substring(mark + 1).split("&")) {
            String[] kv = pair.split("=", 2);
            params.put(kv[0], kv.length > 1 ? URLDecoder.decode(kv[1], StandardCharsets.UTF_8) : "");
        }
        return params;
    }

    @Test
    @DisplayName("命中且 qr_token 非空 ⇒ 302 + Location 三参数（与 /s/ 逐字同款，逐参断言）")
    void knownShortCodeRedirectsToReportPage() throws Exception {
        ProcessingOrderMapper mapper = mock(ProcessingOrderMapper.class);
        when(mapper.selectByShortCodeGlobal(SHORT_CODE)).thenReturn(row(FIXTURE_TOKEN, SHORT_CODE));

        MockHttpServletResponse response = realMvc(mapper).perform(get("/o/" + SHORT_CODE))
                .andExpect(status().isFound())
                .andReturn().getResponse();

        String location = response.getHeader("Location");
        assertThat(location).isEqualTo("/w/?t=" + FIXTURE_TOKEN + "&tenant_id=7&tenant_code=migao");
        Map<String, String> params = queryParams(location);
        assertThat(params.get("t")).as("token 参数").isEqualTo(FIXTURE_TOKEN);
        assertThat(params.get("tenant_id")).as("租户 id 参数").isEqualTo("7");
        assertThat(params.get("tenant_code")).as("企业编码参数").isEqualTo("migao");

        // 公开入口没有租户上下文 ⇒ 必须是跨租户那个读面（带 tenantId 的那个查不出来）
        verify(mapper).selectByShortCodeGlobal(SHORT_CODE);
        verify(mapper, never()).selectByShortCode(anyString(), any());
    }

    @Test
    @DisplayName("🔴 公开入口不泄露业务字段：体为空 + Location 查询参数**恰好**三个（多一个 ⇒ 红）")
    void the302LeaksNothingBeyondTheThreeTenantParams() throws Exception {
        ProcessingOrderMapper mapper = mock(ProcessingOrderMapper.class);
        when(mapper.selectByShortCodeGlobal(SHORT_CODE)).thenReturn(row(FIXTURE_TOKEN, SHORT_CODE));

        MockHttpServletResponse response = realMvc(mapper).perform(get("/o/" + SHORT_CODE))
                .andExpect(status().isFound())
                .andReturn().getResponse();

        assertThat(response.getContentAsString()).as("302 的响应体必须为空").isEmpty();
        String location = response.getHeader("Location");
        assertThat(queryParams(location)).containsOnlyKeys("t", "tenant_id", "tenant_code");
        assertThat(location)
                .as("Location 里不得出现任何业务字段（加工单号 / 客户 / 工序 / 价格）")
                .doesNotContain("JG-20261014-0001");
    }

    @Test
    @DisplayName("短码未知 ⇒ 404（且响应体为空、不泄露存在性）")
    void unknownShortCodeReturns404() throws Exception {
        ProcessingOrderMapper mapper = mock(ProcessingOrderMapper.class);
        when(mapper.selectByShortCodeGlobal(SHORT_CODE)).thenReturn(null);

        MockHttpServletResponse response = realMvc(mapper).perform(get("/o/" + SHORT_CODE))
                .andExpect(status().isNotFound())
                .andReturn().getResponse();
        assertThat(response.getContentAsString()).isEmpty();
        assertThat(response.getHeader("Location")).isNull();
    }

    @Test
    @DisplayName("形态不合法（长度 ≠ 8 / 字符集外）⇒ 404，且**一次库都不查**")
    void malformedShortCodeIs404AndNeverQueriesTheDb() throws Exception {
        ProcessingOrderMapper mapper = mock(ProcessingOrderMapper.class);
        MockMvc mvc = realMvc(mapper);

        for (String malformed : List.of("TOO-SHORT", "7K3M9QP", "7K3M9QP2X", "7K3M9QP-", "ABCDEFGU")) {
            mvc.perform(get("/o/" + malformed)).andExpect(status().isNotFound());
        }
        // 32 位 qr_token 喂进本入口 ⇒ 也不是短码（本路径**只**认短码，不回落任何既有形态）
        mvc.perform(get("/o/" + "0123456789abcdef0123456789abcdef")).andExpect(status().isNotFound());
        verify(mapper, never()).selectByShortCodeGlobal(anyString());
    }

    @Test
    @DisplayName("手抄形态可抄：小写 / O→0 / I,L→1 仍 302 到同一 token")
    void handwrittenFormsStillResolve() throws Exception {
        ProcessingOrderMapper mapper = mock(ProcessingOrderMapper.class);
        when(mapper.selectByShortCodeGlobal("7K3M9QP0")).thenReturn(row(FIXTURE_TOKEN, "7K3M9QP0"));
        when(mapper.selectByShortCodeGlobal("7K3M9QP1")).thenReturn(row(FIXTURE_TOKEN, "7K3M9QP1"));
        MockMvc mvc = realMvc(mapper);

        for (String handwritten : List.of("7k3m9qp0", "7K3M9QPO", "7K3M9QP1", "7K3M9QPI", "7K3M9QPL")) {
            mvc.perform(get("/o/" + handwritten))
                    .andExpect(status().isFound());
        }
    }

    @Test
    @DisplayName("🔴 已撤销（qr_token 置 NULL）⇒ 410，且 short_code 不变：重新发码后同一短码仍 302")
    void revokedRowReturns410AndTheShortCodeSurvivesReissue() throws Exception {
        ProcessingOrderMapper mapper = mock(ProcessingOrderMapper.class);
        ProcessingOrder revoked = row(null, SHORT_CODE);
        when(mapper.selectByShortCodeGlobal(SHORT_CODE)).thenReturn(revoked);
        MockMvc mvc = realMvc(mapper);

        MockHttpServletResponse gone = mvc.perform(get("/o/" + SHORT_CODE))
                .andExpect(status().isGone())
                .andReturn().getResponse();
        assertThat(gone.getContentAsString()).isEmpty();
        assertThat(gone.getHeader("Location")).as("410 不得带跳转").isNull();

        // 「重新发码」= 只补 token（B1 的 fillMissingShortCode 只补 NULL 行），短码一字未动
        ProcessingOrder reissued = row(REISSUED_TOKEN, SHORT_CODE);
        when(mapper.selectByShortCodeGlobal(SHORT_CODE)).thenReturn(reissued);
        MockHttpServletResponse found = mvc.perform(get("/o/" + SHORT_CODE))
                .andExpect(status().isFound())
                .andReturn().getResponse();

        assertThat(found.getHeader("Location"))
                .isEqualTo("/w/?t=" + REISSUED_TOKEN + "&tenant_id=7&tenant_code=migao");
        assertThat(reissued.getShortCode()).as("短码必须一字未动（已打印的纸不作废）").isEqualTo(SHORT_CODE);

        // 公开入口**只读**：不补码、不撤销（那是管理面的写路径）
        verify(mapper, never()).fillMissingShortCode(any(), any(), any(), any());
        verify(mapper, never()).revokeQrToken(any(), any(), any());
    }

    @Test
    @DisplayName("🔴 类级：302 的 Location 只能由 WorkerShortLinkService.reportPageLocation 拼（不许第二套）")
    void the302TargetComesFromTheSingleExistingBuilder() throws Exception {
        Path root = mainJavaRoot();
        String controller = Files.readString(
                root.resolve("com/migao/admin/controller/ProcessingOrderShortLinkController.java"),
                StandardCharsets.UTF_8);
        String service = Files.readString(
                root.resolve("com/migao/admin/service/ProcessingOrderShortLinkService.java"),
                StandardCharsets.UTF_8);

        assertThat(controller)
                .as("控制器必须复用既有 reportPageLocation（复制第二份拼装 = 第二条真相源）")
                .contains("WorkerShortLinkService.reportPageLocation(");
        assertThat(controller)
                .as("不得自拼报工页 URL（那会让改落地页路径只改一处）")
                .doesNotContain("\"/w/");
        assertThat(service)
                .as("解析层也不得自拼报工页 URL")
                .doesNotContain("\"/w/");
    }

    /** admin-api 主源码根（`./mvnw test` 在模块内跑 ⇒ 两种工作目录都要兜住）。 */
    private static Path mainJavaRoot() {
        for (Path base : List.of(Path.of("src/main/java"), Path.of("backend/admin-api/src/main/java"))) {
            if (Files.isDirectory(base.resolve("com/migao/admin"))) {
                return base;
            }
        }
        throw new IllegalStateException("找不到 admin-api 主源码根（src/main/java 与仓库相对路径都不存在）");
    }
}
