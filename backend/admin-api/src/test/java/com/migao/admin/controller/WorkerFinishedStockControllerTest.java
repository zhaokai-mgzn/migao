// case_ids: WH-007, WH-008
package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.FinishedGoodsService;
import com.migao.admin.worker.WorkerIdentity;
import com.migao.admin.worker.WorkerSessionService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 工人端扫水洗唛出库端点（V197 / issue #7762）的准入判据。
 *
 * <p>三条会红的形态：① 无工人 session ⇒ 401（不降级、不拿 body 里的工人身份）；
 * ② 工人身份**只**来自 session（`worker_id` 由服务端解出并传给服务层）；
 * ③ 写面把 body 里的 `token` 原样交给服务层（不自己解析、不自己判权限）。</p>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("工人端扫水洗唛出库端点：session fail-closed + 身份服务端解出")
class WorkerFinishedStockControllerTest {

    @Mock private FinishedGoodsService finishedGoodsService;
    @Mock private WorkerSessionService workerSessionService;

    private WorkerFinishedStockController controller;

    @BeforeEach
    void setUp() {
        controller = new WorkerFinishedStockController(finishedGoodsService, workerSessionService);
        TenantContext.setTenantId(1L);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Test
    @DisplayName("无工人 session ⇒ 401，且不触达服务层（不降级为匿名扫码）")
    void noSessionIsRejected() {
        when(workerSessionService.resolveIdentity(null)).thenReturn(null);

        assertThatThrownBy(() -> controller.washLabel("tok", null))
                .isInstanceOf(BusinessException.class);
        assertThatThrownBy(() -> controller.finishedOutbound(Map.of("token", "tok"), null))
                .isInstanceOf(BusinessException.class);
        verify(finishedGoodsService, never()).washLabelView(anyLong(), any(), any(), any());
        verify(finishedGoodsService, never()).issueByWashLabel(anyLong(), any(), any(), any());
    }

    @Test
    @DisplayName("读面：工人身份由 session 解出并传给服务层（body 里的同名字段一律不信）")
    void readPassesSessionIdentity() {
        when(workerSessionService.resolveIdentity("s-1"))
                .thenReturn(new WorkerIdentity("w-1", "张三", WorkerIdentity.SOURCE_SERVER_SESSION, "s-1"));
        when(finishedGoodsService.washLabelView(1L, "tok", "w-1", "张三"))
                .thenReturn(Map.of("allowed", true, "bin_code", "A-01"));

        ApiResponse<Map<String, Object>> res = controller.washLabel("tok", "s-1");

        assertThat(res.getData()).containsEntry("allowed", true).containsEntry("bin_code", "A-01");
        verify(finishedGoodsService).washLabelView(1L, "tok", "w-1", "张三");
    }

    @Test
    @DisplayName("写面：body 的 token 原样交给服务层（授权与幂等都在服务端）")
    void writePassesTokenToService() {
        when(workerSessionService.resolveIdentity("s-1"))
                .thenReturn(new WorkerIdentity("w-1", "张三", WorkerIdentity.SOURCE_SERVER_SESSION, "s-1"));
        when(finishedGoodsService.issueByWashLabel(eq(1L), eq("tok"), eq("w-1"), eq("张三")))
                .thenReturn(Map.of("allowed", false, "reason", "已出库", "outbound_no", "CK-0001"));

        ApiResponse<Map<String, Object>> res = controller.finishedOutbound(Map.of("token", "tok"), "s-1");

        assertThat(res.getData()).containsEntry("outbound_no", "CK-0001");
    }
}
