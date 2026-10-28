// case_ids: PG-098
package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.User;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.ClientRequestIdService;
import com.migao.admin.service.ProductionReworkService;
import com.migao.admin.service.ProductionScanCompleteService;
import com.migao.admin.service.ProductionScanService;
import com.migao.admin.service.ProductionService;
import com.migao.admin.service.WorkerAdminService;
import com.migao.admin.service.WorkerCuttingHeightService;
import com.migao.admin.worker.WorkerIdentity;
import com.migao.admin.worker.WorkerSessionService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 工人端**报返工**的两条端点（issue #7860）—— 只钉授权与身份，账实另在
 * {@code ProductionReworkServiceTest}。
 *
 * <p>🔴 三条判据（每条能单独变红）：</p>
 * <ol>
 *   <li><b>报返工不看页面键</b>：任一工序工人都能报（用户逐字「需要允许任一工序工人报返工」）——
 *       档案页面集里没有 {@code rework} / {@code inspect} 也照常进服务层；</li>
 *   <li><b>返工列表看页面键</b>：档案页面集不含 {@code rework} ⇒ 403，且服务层**零调用**
 *       （用户裁定「在工人档案中设置过可见权限的工人」）；</li>
 *   <li><b>身份只来自工人 session</b>：body 里的 {@code worker_id} / {@code worker_name} 一个字节都不读。</li>
 * </ol>
 */
@DisplayName("工人端报返工端点（#7860）：写不看页面键 / 列表按档案页面键 403 / 身份只认 session")
class WorkerReworkEndpointsTest {

    private static final Long TENANT = 20L;
    private static final String SESSION = "ws-1";
    private static final WorkerIdentity ZHANG =
            new WorkerIdentity("worker-zhang", "张三", WorkerIdentity.SOURCE_SERVER_SESSION, SESSION);

    private ProductionService productionService;
    private WorkerSessionService workerSessionService;
    private ProductionScanService productionScanService;
    private ProductionScanCompleteService productionScanCompleteService;
    private WorkerCuttingHeightService workerCuttingHeightService;
    private ProductionReworkService productionReworkService;
    private WorkerAdminService workerAdminService;
    private WorkerProductionController controller;

    @BeforeEach
    void setUp() {
        productionService = Mockito.mock(ProductionService.class);
        workerSessionService = Mockito.mock(WorkerSessionService.class);
        productionScanService = Mockito.mock(ProductionScanService.class);
        productionScanCompleteService = Mockito.mock(ProductionScanCompleteService.class);
        workerCuttingHeightService = Mockito.mock(WorkerCuttingHeightService.class);
        productionReworkService = Mockito.mock(ProductionReworkService.class);
        workerAdminService = Mockito.mock(WorkerAdminService.class);
        controller = new WorkerProductionController(productionService, workerSessionService,
                productionScanService, productionScanCompleteService, workerCuttingHeightService,
                workerAdminService);
        // 字段注入（与该控制器对既有两个服务的装配纪律同款）⇒ 测试里直接装替身
        controller.productionReworkService = productionReworkService;
        TenantContext.setTenantId(TENANT);
        when(workerSessionService.resolveIdentity(SESSION)).thenReturn(ZHANG);
        when(productionReworkService.report(any(), anyLong(), any(), any()))
                .thenReturn(Map.of("rework_no", "RG202610260001"));
        when(productionReworkService.reworkOrders(anyLong()))
                .thenReturn(Map.of("orders", java.util.List.of()));
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    /** 档案（`workerPages` = 收窄后的 JSON；null = 未收窄 = 默认页面，不含 rework）。 */
    private static User worker(String pagesJson) {
        return User.builder().id("worker-zhang").tenantId(TENANT).workerNo("W-001")
                .nickname("张三").workerPages(pagesJson).build();
    }

    @Test
    @DisplayName("① 报返工不看页面键：档案只有默认页（无 rework/inspect）也照常进服务层")
    void reportReworkIgnoresPageKeys() {
        when(workerAdminService.findOwnedWorker(anyString())).thenReturn(worker(null));
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("token", "tk-1");
        body.put("reason", "布面污渍");
        body.put("worker_id", "worker-li");   // 🔴 伪造：必须一个字节都不读

        Map<String, Object> data = controller.reportRework(body, SESSION, "k-1").getData();

        assertThat(data).containsEntry("rework_no", "RG202610260001");
        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(productionReworkService).report(captor.capture(), eq(TENANT), eq("k-1"), eq(ZHANG));
        assertThat(captor.getValue()).containsEntry("reason", "布面污渍")
                .containsEntry("worker_id", "worker-li");
        // 服务层拿到的身份来自 session（上面 eq(ZHANG) 已钉住）；body 的伪造值只作为原样透传的输入存在
    }

    @Test
    @DisplayName("② 返工列表：档案页面集不含 rework ⇒ 403，服务层零调用")
    void listRequiresReworkPage() {
        when(workerAdminService.findOwnedWorker(anyString())).thenReturn(worker(null));

        assertThatThrownBy(() -> controller.reworkOrders(SESSION))
                .isInstanceOf(BusinessException.class)
                .extracting("code").isEqualTo("PERMISSION_DENIED");
        verify(productionReworkService, never()).reworkOrders(anyLong());
    }

    @Test
    @DisplayName("③ 返工列表：档案显式开了 rework ⇒ 正常返回（收窄集 = 默认页 + rework）")
    void listWorksWhenReworkGranted() {
        when(workerAdminService.findOwnedWorker(anyString())).thenReturn(
                worker("[\"report\",\"piecework\",\"order\",\"cut_calc\",\"shipment\",\"to_ship\",\"rework\"]"));

        Map<String, Object> data = controller.reworkOrders(SESSION).getData();

        assertThat(data).containsKey("orders");
        verify(productionReworkService).reworkOrders(TENANT);
    }

    @Test
    @DisplayName("④ 无工人 session ⇒ 401，两条端点都不进服务层")
    void withoutSessionRejected() {
        when(workerSessionService.resolveIdentity(null)).thenReturn(null);

        assertThatThrownBy(() -> controller.reportRework(Map.of("token", "tk-1"), null, null))
                .isInstanceOf(BusinessException.class);
        assertThatThrownBy(() -> controller.reworkOrders(null))
                .isInstanceOf(BusinessException.class);
        verify(productionReworkService, never()).report(any(), anyLong(), any(), any());
        verify(productionReworkService, never()).reworkOrders(anyLong());
    }

    @Test
    @DisplayName("⑤ 扫码视图带件级返工记录（issue #7973）：只加一个键，值来自服务端；未定位到件 ⇒ 不加")
    void scanAttachesPieceReworkRecords() {
        when(workerAdminService.findOwnedWorker(anyString())).thenReturn(worker(null));
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("set_no", "JG-20261026-0001-001");
        Map<String, Object> position = new LinkedHashMap<>();
        position.put("order_item_id", "item-1");
        view.put("position", position);
        when(productionScanService.resolve(anyString(), any(), any(), any(), anyLong(), any(), any()))
                .thenReturn(view);
        when(productionReworkService.pieceRecords(TENANT, "JG-20261026-0001-001", "item-1"))
                .thenReturn(List.of(Map.of("rework_no", "RG-1", "status", "draft")));

        Map<String, Object> data = controller.scan("tk-1", null, null, null, SESSION).getData();

        assertThat(data).containsKey("rework_records");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> records = (List<Map<String, Object>>) data.get("rework_records");
        assertThat(records).extracting(r -> r.get("rework_no")).containsExactly("RG-1");

        // 旧码降级形态（position = null）⇒ 没有件级记录可谈：不加键（不摆空壳）
        Map<String, Object> degraded = new LinkedHashMap<>();
        degraded.put("granularity", "order");
        degraded.put("position", null);
        when(productionScanService.resolve(anyString(), any(), any(), any(), anyLong(), any(), any()))
                .thenReturn(degraded);
        assertThat(controller.scan("tk-1", null, null, null, SESSION).getData())
                .doesNotContainKey("rework_records");
    }
}
