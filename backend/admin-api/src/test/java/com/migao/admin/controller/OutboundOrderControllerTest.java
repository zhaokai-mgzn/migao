// case_ids: WH-004
package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.OutboundOrderCreateRequest;
import com.migao.admin.dto.OutboundOrderView;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.OutboundOrderService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.lang.reflect.Method;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 出库单 Controller 契约（V196，issue #7750 / 用例 WH-004）。
 *
 * <p>守三条：① 三个端点都把**当前租户**透传给服务（跨租户读 = 数据泄漏，不是过滤问题）；
 * ② 建单走 {@code createAndPost}（**建单即过账**，不存在「先建草稿」的入口）；
 * ③ 读码 = 独立读码 {@code stock:view}、写码沿用 {@code inbound:create}（issue #8087 拆码，
 * 不新造 {@code outbound:*} —— 新码今天无人持有，页面会对所有人不可见）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("出库单 Controller（V196 / issue #7750）")
class OutboundOrderControllerTest {

    @Mock private OutboundOrderService outboundOrderService;

    @InjectMocks private OutboundOrderController controller;

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Test
    @DisplayName("列表把关键词 / 类别 / 当前租户透传给服务")
    void listPassesTenantAndFilters() {
        TenantContext.setTenantId(7L);
        when(outboundOrderService.list(any(), any(), any())).thenReturn(List.of(new OutboundOrderView()));

        ApiResponse<List<OutboundOrderView>> res = controller.list("CK-20261025", "fabric");

        assertThat(res.getData()).hasSize(1);
        verify(outboundOrderService).list(eq("CK-20261025"), eq("fabric"), eq(7L));
    }

    @Test
    @DisplayName("详情按 id + 当前租户读")
    void detailPassesTenant() {
        TenantContext.setTenantId(7L);
        when(outboundOrderService.detail(any(), any())).thenReturn(new OutboundOrderView());

        controller.detail("ck-1");

        verify(outboundOrderService).detail(eq("ck-1"), eq(7L));
    }

    @Test
    @DisplayName("🔴 建单 = 建单即过账：只走 createAndPost，操作人取自认证上下文（无认证 = system）")
    void createGoesThroughCreateAndPost() {
        TenantContext.setTenantId(7L);
        when(outboundOrderService.createAndPost(any(), any(), any())).thenReturn(new OutboundOrderView());

        OutboundOrderCreateRequest req = new OutboundOrderCreateRequest();
        controller.create(req);

        verify(outboundOrderService).createAndPost(eq(req), eq(7L), eq("system"));
    }

    @Test
    @DisplayName("权限边界：读 stock:view / 写 inbound:create（不挪用 product:list 或 processing:manage）")
    void permissionCodesMatchInboundDomain() throws Exception {
        assertThat(permissionOf("list", String.class, String.class)).isEqualTo("stock:view");
        assertThat(permissionOf("detail", String.class)).isEqualTo("stock:view");
        assertThat(permissionOf("create", OutboundOrderCreateRequest.class)).isEqualTo("inbound:create");
    }

    private static String permissionOf(String method, Class<?>... params) throws Exception {
        Method m = OutboundOrderController.class.getDeclaredMethod(method, params);
        RequirePermission annotation = m.getAnnotation(RequirePermission.class);
        assertThat(annotation).as("%s 必须声明 @RequirePermission（无注解 = 只靠路径门禁）", method).isNotNull();
        return annotation.value();
    }
}
