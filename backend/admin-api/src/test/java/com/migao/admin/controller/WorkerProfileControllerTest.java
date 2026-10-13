package com.migao.admin.controller;

// case_ids: PG-072, PG-018, BM-006, DF-017, HR-001, HR-002

import com.migao.admin.exception.BusinessException;
import com.migao.admin.entity.User;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.WorkerAdminService;
import com.migao.admin.service.WorkerPageConfigService;
import com.migao.admin.worker.WorkerIdentity;
import com.migao.admin.worker.WorkerSessionService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 工人端身份 + 页面端点测试（V141，母单 #5161）：{@code GET /api/worker/me}。
 *
 * <p>判据（每条都能红）：</p>
 * <ol>
 *   <li><b>只回本租户本工人的页面集</b>：租户取自**会话行**（不是请求参数）—— 用
 *       {@link ArgumentCaptor} 钉住传给读配置的实参；</li>
 *   <li><b>无 / 失效工人 session ⇒ 401</b>，且**不进**配置读面（不降级成「默认全开」——
 *       匿名用户不能靠这个端点探到任何租户的配置）；</li>
 *   <li><b>不下发任何权限</b>：响应体里没有 {@code permissions} / {@code roles} / 任何商家权限码
 *       （工人页面码是**页面可见性**，不是权限；红证：谁敢往这个 payload 里塞 {@code permissions}
 *       ⇒ 本条红 + {@code AdminApiWorkerRoleGateTest} 的拒绝集合判据同批红）；</li>
 *   <li><b>零商家权限注解</b>：本控制器不得出现 {@code @RequirePermission}（工人面不挂商家码）。</li>
 * </ol>
 */
@DisplayName("WorkerProfileController 工人身份 + 页面（V141 / 母单 #5161）")
class WorkerProfileControllerTest extends BaseControllerTest {

    private static final String URL = "/api/worker/me";
    private static final String SESSION = "sess-worker-1";
    private static final WorkerIdentity ZHANG =
            new WorkerIdentity("worker-zhang", "张三", WorkerIdentity.SOURCE_SERVER_SESSION, SESSION);

    private WorkerSessionService workerSessionService;
    private WorkerPageConfigService workerPageConfigService;
    private WorkerAdminService workerAdminService;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        workerSessionService = mock(WorkerSessionService.class);
        workerPageConfigService = mock(WorkerPageConfigService.class);
        workerAdminService = mock(WorkerAdminService.class);
        // 缺省：档案查得到但**未收窄**（issue #6788 的存量/新建默认）⇒ 下发 = 企业页逐值
        User worker = new User();
        worker.setId(ZHANG.workerId());
        when(workerAdminService.findOwnedWorker(ZHANG.workerId())).thenReturn(worker);
        mockMvc = buildMockMvc(
                new WorkerProfileController(workerSessionService, workerPageConfigService, workerAdminService));
    }

    @Test
    @DisplayName("有效 session ⇒ 身份 + **本租户**页面集（租户取自会话行，不取请求）")
    void returnsIdentityAndPagesOfTheSessionTenant() throws Exception {
        when(workerSessionService.resolveIdentity(SESSION)).thenReturn(ZHANG);
        when(workerSessionService.tenantIdOf(SESSION)).thenReturn(7L);
        when(workerPageConfigService.pagesFor(7L)).thenReturn(List.of("report", "cut_calc"));

        mockMvc.perform(get(URL).header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.worker_id").value("worker-zhang"))
                .andExpect(jsonPath("$.data.worker_name").value("张三"))
                .andExpect(jsonPath("$.data.pages[0]").value("report"))
                .andExpect(jsonPath("$.data.pages[1]").value("cut_calc"));

        // 页面集必须按**会话租户**读 —— 请求里没有任何租户入参可伪造
        ArgumentCaptor<Long> tenant = ArgumentCaptor.forClass(Long.class);
        verify(workerPageConfigService).pagesFor(tenant.capture());
        assertThat(tenant.getValue()).isEqualTo(7L);
        assertThat(tenant.getValue()).isNotEqualTo(TEST_TENANT_ID);
    }

    @Test
    @DisplayName("🔴 无 / 失效 session ⇒ 401，且**不进**配置读面（不降级成默认全开）")
    void invalidSessionIsRejectedWithoutReadingAnyConfig() throws Exception {
        when(workerSessionService.resolveIdentity(SESSION)).thenThrow(
                BusinessException.authFailed("尚未登录工人身份或登录已失效，请重新用工号 + PIN 登录"));

        mockMvc.perform(get(URL).header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isUnauthorized());

        // 无 session 头同样 401（服务层抛），且从未读任何租户的配置
        when(workerSessionService.resolveIdentity(null)).thenThrow(
                BusinessException.authFailed("尚未登录工人身份或登录已失效，请重新用工号 + PIN 登录"));
        mockMvc.perform(get(URL)).andExpect(status().isUnauthorized());

        verify(workerPageConfigService, never()).pagesFor(org.mockito.ArgumentMatchers.any());
        verify(workerPageConfigService, never()).get(org.mockito.ArgumentMatchers.any());
    }

    @Test
    @DisplayName("🔴 不下发任何权限：响应体没有 permissions / roles 键")
    void neverEmitsPermissionsOrRoles() throws Exception {
        when(workerSessionService.resolveIdentity(SESSION)).thenReturn(ZHANG);
        when(workerSessionService.tenantIdOf(SESSION)).thenReturn(7L);
        when(workerPageConfigService.pagesFor(7L)).thenReturn(List.of("report"));

        String body = mockMvc.perform(get(URL).header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isOk())
                .andReturn().getResponse().getContentAsString();

        assertThat(body).doesNotContain("permissions");
        assertThat(body).doesNotContain("\"roles\"");
    }

    @Test
    @DisplayName("零商家权限注解：工人面控制器不得挂 @RequirePermission（否则工人请求必 403）")
    void workerFaceCarriesNoMerchantPermissionAnnotation() throws Exception {
        assertThat(WorkerProfileController.class.getAnnotation(RequirePermission.class)).isNull();
        assertThat(WorkerProfileController.class.getMethod("me", String.class)
                .getAnnotation(RequirePermission.class)).isNull();
        // 路径必须落在 /api/worker/**（工人可达面的唯一入口）
        assertThat(WorkerProfileController.class.getAnnotation(
                org.springframework.web.bind.annotation.RequestMapping.class).value())
                .containsExactly("/api/worker");
    }

    // ════════════════════════════════════════════════════════════════════════════
    // 工人档案级收窄（issue #6788）：下发的 pages = 企业页 ∩ 工人档案上的收窄
    // ════════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("工人档案设了收窄 ⇒ 只下发交集（企业开 report/cut_calc/shipment + 个人勾 cut_calc/shipment ⇒ 两页）")
    void workerLevelNarrowingIsIntersectedWithTheEnterpriseSet() throws Exception {
        when(workerSessionService.resolveIdentity(SESSION)).thenReturn(ZHANG);
        when(workerSessionService.tenantIdOf(SESSION)).thenReturn(7L);
        when(workerPageConfigService.pagesFor(7L)).thenReturn(List.of("report", "cut_calc", "shipment"));
        User narrow = new User();
        narrow.setId(ZHANG.workerId());
        // 库里存的是原样 JSON 文本（见 User#workerPages 的「为什么不用 JacksonTypeHandler」）
        narrow.setWorkerPages("[\"cut_calc\",\"shipment\"]");
        when(workerAdminService.findOwnedWorker(ZHANG.workerId())).thenReturn(narrow);

        mockMvc.perform(get(URL).header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.pages[0]").value("cut_calc"))
                .andExpect(jsonPath("$.data.pages[1]").value("shipment"))
                // 个人勾了企业**没开**的页也不出现（企业级是天花板）
                .andExpect(jsonPath("$.data.pages.length()").value(2));

        // 档案按**会话里的 worker_id** 取（不接受任何请求入参指定看谁的菜单）
        verify(workerAdminService).findOwnedWorker(ZHANG.workerId());
    }

    @Test
    @DisplayName("🔴 档案查不到 / 读面异常 ⇒ **fail-open**：照旧下发企业页（绝不把工人挡在活外面）")
    void missingArchiveFallsBackToTheEnterpriseSet() throws Exception {
        when(workerSessionService.resolveIdentity(SESSION)).thenReturn(ZHANG);
        when(workerSessionService.tenantIdOf(SESSION)).thenReturn(7L);
        when(workerPageConfigService.pagesFor(7L)).thenReturn(List.of("report", "cut_calc"));
        when(workerAdminService.findOwnedWorker(ZHANG.workerId())).thenReturn(null);

        mockMvc.perform(get(URL).header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.pages[0]").value("report"))
                .andExpect(jsonPath("$.data.pages[1]").value("cut_calc"));
    }

    @Test
    @DisplayName("🔴 交集为空（收窄的页恰好被企业关了）⇒ 回落企业页，**不是**空数组"
            + "（工人端把空集读成「没读到权限 ⇒ 全开」，原样下发等于反向放宽）")
    void emptyIntersectionFallsBackToTheEnterpriseSetInsteadOfOpeningEverything() throws Exception {
        when(workerSessionService.resolveIdentity(SESSION)).thenReturn(ZHANG);
        when(workerSessionService.tenantIdOf(SESSION)).thenReturn(7L);
        when(workerPageConfigService.pagesFor(7L)).thenReturn(List.of("report", "order"));
        User narrow = new User();
        narrow.setId(ZHANG.workerId());
        narrow.setWorkerPages("[\"cut_calc\"]");
        when(workerAdminService.findOwnedWorker(ZHANG.workerId())).thenReturn(narrow);

        mockMvc.perform(get(URL).header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.pages[0]").value("report"))
                .andExpect(jsonPath("$.data.pages[1]").value("order"))
                .andExpect(jsonPath("$.data.pages.length()").value(2));
    }

    @Test
    @DisplayName("脏数据（形态不对的存储值）⇒ 当未收窄：照旧下发企业页（读侧 fail-open，不抛 500）")
    void malformedStoredPagesFallBackToTheEnterpriseSet() throws Exception {
        when(workerSessionService.resolveIdentity(SESSION)).thenReturn(ZHANG);
        when(workerSessionService.tenantIdOf(SESSION)).thenReturn(7L);
        when(workerPageConfigService.pagesFor(7L)).thenReturn(List.of("report"));
        User broken = new User();
        broken.setId(ZHANG.workerId());
        broken.setWorkerPages("[not json");
        when(workerAdminService.findOwnedWorker(ZHANG.workerId())).thenReturn(broken);

        mockMvc.perform(get(URL).header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.pages[0]").value("report"))
                .andExpect(jsonPath("$.data.pages.length()").value(1));
    }
}
