// case_ids: PG-082, PG-083
package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.User;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.QualityCheckService;
import com.migao.admin.service.WorkerAdminService;
import com.migao.admin.time.BusinessClock;
import com.migao.admin.worker.WorkerIdentity;
import com.migao.admin.worker.WorkerSessionService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.time.OffsetDateTime;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * 工人端**质检单**端点（`/api/worker/quality/**`，issue #7162）。
 *
 * <p>对应用例：<b>PG-082</b>（`.github/cases/processing-order.yml`）。</p>
 *
 * <p>🔴 钉住的四件事（每条能单独变红）：</p>
 * <ol>
 *   <li><b>授权是服务端的</b>：工人档案的页面集里没有 {@code inspect} ⇒ <b>403</b>，且
 *       {@link QualityCheckService} 一次都不被调用（「藏起按钮」不是授权）；</li>
 *   <li><b>检验人只来自工人 session</b>：落库身份 = session 解出的 worker_id/name，
 *       body 里的 {@code worker_id} / {@code inspector_id} 一个字节都不读；{@code inspector_kind='worker'}；</li>
 *   <li><b>判定三态与原因必填复用服务层</b>：控制器只做身份/授权与取值，不重造第二份校验；</li>
 *   <li><b>未检 ≠ 合格</b>：最新判定读面在没有记录时给 {@code latest=null}（不编值）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("工人端质检单端点（#7162）")
class WorkerQualityControllerTest {

    private static final Long TENANT = 20L;
    private static final String SESSION = "ws-1";
    private static final String WORKER_ID = "worker-user-1";
    private static final String WORKER_NAME = "张师傅";
    private static final OffsetDateTime AT = OffsetDateTime.parse("2026-10-17T10:30:00+08:00");

    @Mock
    private WorkerSessionService workerSessionService;
    @Mock
    private WorkerAdminService workerAdminService;
    @Mock
    private QualityCheckService qualityCheckService;
    @Mock
    private BusinessClock businessClock;

    private WorkerQualityController controller;

    @BeforeEach
    void setUp() {
        controller = new WorkerQualityController(workerSessionService, workerAdminService,
                qualityCheckService, businessClock);
        TenantContext.setTenantId(TENANT);
        when(workerSessionService.resolveIdentity(SESSION)).thenReturn(
                new WorkerIdentity(WORKER_ID, WORKER_NAME, WorkerIdentity.SOURCE_SERVER_SESSION, SESSION));
        when(businessClock.nowOffset()).thenReturn(AT);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    private static User worker(String pagesJson) {
        return User.builder().id(WORKER_ID).tenantId(TENANT).workerNo("W-001")
                .nickname(WORKER_NAME).workerPages(pagesJson).build();
    }

    @Test
    @DisplayName("① 没开「质检」页 ⇒ 403，且不写任何质检记录（服务端准入，不是藏 UI）")
    void workerWithoutInspectPageIsDeniedAndWritesNothing() {
        when(workerAdminService.findOwnedWorker(WORKER_ID)).thenReturn(worker("[\"report\"]"));

        assertThatThrownBy(() -> controller.create(SESSION,
                Map.of("order_item_id", "item-1", "result", "pass")))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("权限不足");
        verifyNoInteractions(qualityCheckService);
    }

    @Test
    @DisplayName("① 档案查不到 / 未收窄（默认页不含质检）⇒ 同样 403")
    void missingProfileOrUnrestrictedDefaultsIsDenied() {
        when(workerAdminService.findOwnedWorker(WORKER_ID)).thenReturn(null);
        assertThatThrownBy(() -> controller.latest(SESSION, "item-1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("权限不足");

        when(workerAdminService.findOwnedWorker(WORKER_ID)).thenReturn(worker(null));
        assertThatThrownBy(() -> controller.latest(SESSION, "item-1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("权限不足");
        verifyNoInteractions(qualityCheckService);
    }

    @Test
    @DisplayName("② 开了「质检」页 ⇒ 落库身份 = session 的工人（kind=worker），body 伪造身份无效")
    void grantedWorkerDelegatesWithSessionIdentity() {
        when(workerAdminService.findOwnedWorker(WORKER_ID)).thenReturn(worker("[\"report\",\"inspect\"]"));
        when(qualityCheckService.create(any(), anyString(), anyString(), any(), anyString(), anyString(),
                anyString(), any(), any())).thenReturn(Map.of("id", "qi-1"));

        controller.create(SESSION, Map.of(
                "order_item_id", "item-1",
                "result", "rework",
                "reason", "布面污渍",
                // 伪造身份：必须被忽略（身份只认 X-Worker-Session-Id）
                "worker_id", "attacker",
                "inspector_id", "attacker"));

        ArgumentCaptor<String> workerId = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<String> workerName = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<String> kind = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<WorkerIdentity> actor = ArgumentCaptor.forClass(WorkerIdentity.class);
        verify(qualityCheckService).create(eq(TENANT), eq("item-1"), eq("rework"), eq("布面污渍"),
                workerId.capture(), workerName.capture(), kind.capture(), eq(AT), actor.capture());
        assertThat(workerId.getValue()).isEqualTo(WORKER_ID);
        assertThat(workerName.getValue()).isEqualTo(WORKER_NAME);
        assertThat(kind.getValue()).isEqualTo(QualityCheckService.INSPECTOR_WORKER);
        assertThat(kind.getValue()).isNotEqualTo("attacker");
        // issue #7165：工人端录判定把「本人」交给联动服务（合格时计件记给这位工人）
        assertThat(actor.getValue().workerId()).isEqualTo(WORKER_ID);
    }

    @Test
    @DisplayName("③ 最新判定：没有记录 ⇒ `latest=null`（未检 ≠ 合格），不编值")
    void latestReturnsNullWhenNoRecord() {
        when(workerAdminService.findOwnedWorker(WORKER_ID)).thenReturn(worker("[\"inspect\"]"));
        when(qualityCheckService.latest(TENANT, "item-1")).thenReturn(null);

        Map<String, Object> data = controller.latest(SESSION, "item-1").getData();

        assertThat(data).containsEntry("order_item_id", "item-1");
        assertThat(data.get("latest")).isNull();
    }

    @Test
    @DisplayName("③ 有记录 ⇒ 原样带出（含 inspector_kind，前端据此显示检验人）")
    void latestReturnsTheRecord() {
        when(workerAdminService.findOwnedWorker(WORKER_ID)).thenReturn(worker("[\"inspect\"]"));
        Map<String, Object> record = Map.of("result", "pass", "inspector_kind", "worker");
        when(qualityCheckService.latest(TENANT, "item-1")).thenReturn(record);

        assertThat(controller.latest(SESSION, "item-1").getData().get("latest")).isEqualTo(record);
        // 读面也不调写面
        verify(qualityCheckService, never()).create(any(), anyString(), anyString(), any(), anyString(),
                anyString(), anyString(), any(), any());
    }
}
