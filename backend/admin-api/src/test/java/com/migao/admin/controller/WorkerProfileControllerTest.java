package com.migao.admin.controller;

// case_ids: PG-072, PG-065, PG-018, BM-006, DF-017, HR-001, HR-002

import com.migao.admin.exception.BusinessException;
import com.migao.admin.entity.User;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.WorkerAdminService;
import com.migao.admin.worker.WorkerIdentity;
import com.migao.admin.worker.WorkerPages;
import com.migao.admin.worker.WorkerSessionService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 工人端身份 + 页面端点测试（V141，母单 #5161；单层口径 issue #6828）：{@code GET /api/worker/me}。
 *
 * <p>判据（每条都能红）：</p>
 * <ol>
 *   <li><b>页面集只认工人档案</b>（{@code users.worker_pages}）：未收窄 ⇒ 全部页面；收窄 ⇒ 收窄集 ——
 *       企业级层已整层移除（issue #6828），本控制器**不得**再依赖任何企业级配置服务；</li>
 *   <li><b>无 / 失效工人 session ⇒ 401</b>，且**不读**任何工人档案（不降级成「默认全开」——
 *       匿名用户不能靠这个端点探到任何租户的东西）；</li>
 *   <li><b>不下发任何权限</b>：响应体里没有 {@code permissions} / {@code roles} / 任何商家权限码
 *       （工人页面码是**页面可见性**，不是权限）；</li>
 *   <li><b>零商家权限注解</b>：本控制器不得出现 {@code @RequirePermission}（工人面不挂商家码）。</li>
 * </ol>
 */
@DisplayName("WorkerProfileController 工人身份 + 页面（V141 / #6788 / #6828）")
class WorkerProfileControllerTest extends BaseControllerTest {

    private static final String URL = "/api/worker/me";
    private static final String SESSION = "sess-worker-1";
    private static final WorkerIdentity ZHANG =
            new WorkerIdentity("worker-zhang", "张三", WorkerIdentity.SOURCE_SERVER_SESSION, SESSION);

    private WorkerSessionService workerSessionService;
    private WorkerAdminService workerAdminService;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        workerSessionService = mock(WorkerSessionService.class);
        workerAdminService = mock(WorkerAdminService.class);
        // 缺省：档案查得到但**未收窄**（issue #6788 的存量/新建默认）⇒ 下发 = 全部页面
        User worker = new User();
        worker.setId(ZHANG.workerId());
        when(workerAdminService.findOwnedWorker(ZHANG.workerId())).thenReturn(worker);
        mockMvc = buildMockMvc(new WorkerProfileController(workerSessionService, workerAdminService));
    }

    @Test
    @DisplayName("有效 session ⇒ 身份 + 页面集（未收窄 = 全部页面）")
    void returnsIdentityAndAllPagesWhenNotNarrowed() throws Exception {
        when(workerSessionService.resolveIdentity(SESSION)).thenReturn(ZHANG);

        mockMvc.perform(get(URL).header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.worker_id").value("worker-zhang"))
                .andExpect(jsonPath("$.data.worker_name").value("张三"))
                .andExpect(jsonPath("$.data.pages.length()").value(WorkerPages.defaultPages().size()))
                .andExpect(jsonPath("$.data.pages[0]").value("report"))
                .andExpect(jsonPath("$.data.pages[3]").value("shipment"));

        // 档案按**会话里的 worker_id** 取（不接受任何请求入参指定看谁的菜单）
        verify(workerAdminService).findOwnedWorker(ZHANG.workerId());
    }

    @Test
    @DisplayName("🔴 无 / 失效 session ⇒ 401，且**不读**任何工人档案")
    void invalidSessionIsRejectedWithoutReadingAnyArchive() throws Exception {
        when(workerSessionService.resolveIdentity(SESSION)).thenThrow(
                BusinessException.authFailed("尚未登录工人身份或登录已失效，请重新用工号 + PIN 登录"));

        mockMvc.perform(get(URL).header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isUnauthorized());

        // 无 session 头同样 401（服务层抛），且从未读任何档案
        when(workerSessionService.resolveIdentity(null)).thenThrow(
                BusinessException.authFailed("尚未登录工人身份或登录已失效，请重新用工号 + PIN 登录"));
        mockMvc.perform(get(URL)).andExpect(status().isUnauthorized());

        verify(workerAdminService, never()).findOwnedWorker(org.mockito.ArgumentMatchers.any());
    }

    @Test
    @DisplayName("🔴 不下发任何权限：响应体没有 permissions / roles 键")
    void neverEmitsPermissionsOrRoles() throws Exception {
        when(workerSessionService.resolveIdentity(SESSION)).thenReturn(ZHANG);

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
    // 工人档案级收窄（issue #6788）：下发的 pages = 档案上的收窄（唯一一层，issue #6828）
    // ════════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("档案设了收窄 ⇒ 只下发收窄集（顺序按闭词表）")
    void workerLevelNarrowingDecidesTheDeliveredPages() throws Exception {
        when(workerSessionService.resolveIdentity(SESSION)).thenReturn(ZHANG);
        User narrow = new User();
        narrow.setId(ZHANG.workerId());
        // 库里存的是原样 JSON 文本（见 User#workerPages 的「为什么不用 JacksonTypeHandler」）
        narrow.setWorkerPages("[\"shipment\",\"cut_calc\"]");
        when(workerAdminService.findOwnedWorker(ZHANG.workerId())).thenReturn(narrow);

        mockMvc.perform(get(URL).header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.pages.length()").value(2))
                .andExpect(jsonPath("$.data.pages[0]").value("cut_calc"))
                .andExpect(jsonPath("$.data.pages[1]").value("shipment"));
    }

    @Test
    @DisplayName("收窄到一页 ⇒ 只下发那一页（最窄的合法形态）")
    void singlePageNarrowing() throws Exception {
        when(workerSessionService.resolveIdentity(SESSION)).thenReturn(ZHANG);
        User narrow = new User();
        narrow.setId(ZHANG.workerId());
        narrow.setWorkerPages("[\"report\"]");
        when(workerAdminService.findOwnedWorker(ZHANG.workerId())).thenReturn(narrow);

        mockMvc.perform(get(URL).header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.pages.length()").value(1))
                .andExpect(jsonPath("$.data.pages[0]").value("report"));
    }

    @Test
    @DisplayName("🔴 档案查不到 ⇒ **fail-open**：照旧下发全部页面（绝不把工人挡在活外面）")
    void missingArchiveFallsBackToAllPages() throws Exception {
        when(workerSessionService.resolveIdentity(SESSION)).thenReturn(ZHANG);
        when(workerAdminService.findOwnedWorker(ZHANG.workerId())).thenReturn(null);

        mockMvc.perform(get(URL).header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.pages.length()").value(WorkerPages.defaultPages().size()));
    }

    @Test
    @DisplayName("脏数据（形态不对 / 全未知键的存储值）⇒ fail-open：下发全部页面，**不是**空数组"
            + "（工人端把空集读成「没读到权限 ⇒ 全开」，原样下发等于反向放宽）")
    void malformedStoredPagesFallBackToAllPages() throws Exception {
        when(workerSessionService.resolveIdentity(SESSION)).thenReturn(ZHANG);
        User broken = new User();
        broken.setId(ZHANG.workerId());
        broken.setWorkerPages("[not json");
        when(workerAdminService.findOwnedWorker(ZHANG.workerId())).thenReturn(broken);

        mockMvc.perform(get(URL).header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.pages.length()").value(WorkerPages.defaultPages().size()));

        User unknownOnly = new User();
        unknownOnly.setId(ZHANG.workerId());
        unknownOnly.setWorkerPages("[\"stock\"]");
        when(workerAdminService.findOwnedWorker(ZHANG.workerId())).thenReturn(unknownOnly);

        mockMvc.perform(get(URL).header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.pages.length()").value(WorkerPages.defaultPages().size()));
    }
}
