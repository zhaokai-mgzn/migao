// case_ids: DF-017, PG-020, OR-045
package com.migao.admin.shipment;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.controller.WorkerShipmentController;
import com.migao.admin.security.SecurityConfig;
import com.migao.admin.service.OrderStatusTransitions;
import com.migao.admin.worker.WorkerSessionService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.authorization.AuthorizationDecision;
import org.springframework.security.authorization.AuthorizationManager;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.web.access.intercept.RequestAuthorizationContext;
import org.springframework.web.bind.annotation.RequestMapping;

import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.List;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 🔴 <b>能力保留、载体分离</b>（issue #5648）：工人发货面必须挂在 {@code /api/worker/**}，
 * 且工人**零商家权限码**。
 *
 * <h3>红证方向（改回旧形态 ⇒ 必红）</h3>
 * <p>把 {@link WorkerShipmentController} 的映射改回 {@code /api/admin/shipment}
 * （= 发货只挂在管理后台下）⇒ 本类第 ①②③ 条断言当场红；同时第 ④ 条会证明
 * 工人的请求在那条路上会被门禁**拒绝**（{@code ADMIN_API_REJECTED_ROLES} 含 {@code worker}）
 * —— 那正是 issue #5648 实测的 403。</p>
 *
 * <p>第 ⑤ 条是为什么「不给工人商家权限码」的机械判据：工人 session 的权限集合是空的
 * （{@code WorkerSessionService} 只挂 {@code ROLE_WORKER}），加任何
 * {@code @RequirePermission} 都只会恒 403。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("工人发货面：载体分离（/api/worker/**）+ 零商家权限码")
class WorkerShipmentContractTest {

    @Mock private com.migao.admin.security.JwtAuthenticationFilter jwtAuthenticationFilter;
    @Mock private com.migao.admin.security.ServiceTokenFilter serviceTokenFilter;
    @Mock private com.migao.admin.security.WorkerSessionFilter workerSessionFilter;
    @Mock private com.migao.admin.security.PasswordChangeRequiredFilter passwordChangeRequiredFilter;
    @Mock private org.springframework.security.core.userdetails.UserDetailsService userDetailsService;

    private AuthorizationManager<RequestAuthorizationContext> adminGate() {
        return new SecurityConfig(jwtAuthenticationFilter, serviceTokenFilter, workerSessionFilter,
                passwordChangeRequiredFilter, userDetailsService, new ObjectMapper())
                .adminApiAuthorizationManager();
    }

    private AuthorizationDecision decide(Authentication authentication) {
        return adminGate().check(() -> authentication, null);
    }

    private Authentication workerAuth() {
        // 与 WorkerSessionFilter 落下的认证**逐字同形**：只挂 ROLE_WORKER 一个 authority
        return new UsernamePasswordAuthenticationToken("worker-zhang", null,
                List.of(new SimpleGrantedAuthority("ROLE_" + WorkerSessionService.WORKER_ROLE.toUpperCase())));
    }

    // ── ①② 路由落在工人可达面 ───────────────────────────────────────────────

    @Test
    @DisplayName("🔴 控制器映射在 /api/worker/** 下（改回 /api/admin/** ⇒ 工人 403，本断言当场红）")
    void controllerLivesUnderWorkerSurface() {
        RequestMapping mapping = WorkerShipmentController.class.getAnnotation(RequestMapping.class);
        assertThat(mapping).as("@RequestMapping 必须存在（否则路径由方法拼，工人可达面无法机械核对）").isNotNull();
        assertThat(mapping.value()).isNotEmpty();
        assertThat(mapping.value()[0])
                .as("工人可达面 = /api/worker/**（不匹配 /api/admin/** ⇒ 不被工人拒绝集合拦下）")
                .startsWith("/api/worker/");
    }

    @Test
    @DisplayName("🔴 四个动作端点（recognize / pack / ship / unpack）+ 一个读面都在工人路径下，且**不带** @RequirePermission")
    void endpointsAreWorkerScopedAndCarryNoMerchantPermissionCode() {
        List<String> actions = List.of("recognize", "pack", "ship", "unpack", "read");
        for (String action : actions) {
            Method method = Arrays.stream(WorkerShipmentController.class.getDeclaredMethods())
                    .filter(m -> m.getName().equals(action))
                    .findFirst()
                    .orElseThrow(() -> new AssertionError("缺工人发货端点方法: " + action));
            assertThat(method.getAnnotation(com.migao.admin.security.RequirePermission.class))
                    .as("%s 上不得挂商家权限码：工人 permissions=[] ⇒ 挂了就是恒 403（#4727/#4733 既有口径）", action)
                    .isNull();
            assertThat(method.getAnnotation(org.springframework.web.bind.annotation.PostMapping.class) != null
                    || method.getAnnotation(org.springframework.web.bind.annotation.GetMapping.class) != null)
                    .as("%s 必须有 HTTP 映射注解", action)
                    .isTrue();
        }
    }

    @Test
    @DisplayName("🔴 类上也没有 @RequirePermission（类级注解同样会把整条工人面变成恒 403）")
    void controllerClassCarriesNoPermissionCode() {
        assertThat(WorkerShipmentController.class.getAnnotation(com.migao.admin.security.RequirePermission.class))
                .isNull();
    }

    // ── ④ 工人到不了 /api/admin/**（零商家权限红线） ─────────────────────────

    @Test
    @DisplayName("🔴 工人身份访问 /api/admin/** ⇒ 必拒（发货**不能**靠把工人放进管理后台来解决）")
    void workerIsDeniedOnAdminApi() {
        assertThat(decide(workerAuth()).isGranted())
                .as("工人零商家权限：发货面必须在 /api/worker/** 上能力保留、载体分离（#4727 先例）")
                .isFalse();
    }

    @Test
    @DisplayName("反向护栏：既有分支不回归（管理员/服务放行，customer/agent 拒，商户员工放行）")
    void existingGateBranchesUnchanged() {
        assertThat(decide(auth("admin")).isGranted()).isTrue();
        assertThat(decide(auth("service")).isGranted()).isTrue();
        assertThat(decide(auth("customer")).isGranted()).isFalse();
        assertThat(decide(auth("agent")).isGranted()).isFalse();
        assertThat(decide(auth("operator")).isGranted()).isTrue();
    }

    private Authentication auth(String role) {
        return new UsernamePasswordAuthenticationToken("p", null,
                List.of(new SimpleGrantedAuthority("ROLE_" + role.toUpperCase())));
    }

    // ── ⑤ 状态机：packed 加进来，既有五条流转一个字不改 ──────────────────────

    @Test
    @DisplayName("🔴 packed 进入状态机：producing → packed → shipped 可走，pending → packed 不可走")
    void packedEntersTheStateMachine() {
        OrderStatusTransitions.assertTransitionAllowed("confirmed", "packed");
        OrderStatusTransitions.assertTransitionAllowed("producing", "packed");
        OrderStatusTransitions.assertTransitionAllowed("packed", "shipped");
        assertThatThrownBy(() -> OrderStatusTransitions.assertTransitionAllowed("pending", "packed"))
                .isInstanceOf(com.migao.admin.exception.BusinessException.class);
        assertThatThrownBy(() -> OrderStatusTransitions.assertTransitionAllowed("shipped", "packed"))
                .isInstanceOf(com.migao.admin.exception.BusinessException.class);
        assertThat(OrderStatusTransitions.label("packed")).isEqualTo("已打包");
    }

    @Test
    @DisplayName("🔴 反向护栏：既有五条流转逐字未改（回归判据 —— 加状态不许顺手改老口径）")
    void existingTransitionsAreUnchanged() {
        assertThat(OrderStatusTransitions.STATUS_TRANSITIONS.get("pending"))
                .isEqualTo(Set.of("confirmed", "cancelled"));
        assertThat(OrderStatusTransitions.STATUS_TRANSITIONS.get("confirmed"))
                .isEqualTo(Set.of("producing", "packed", "shipped", "cancelled"));
        assertThat(OrderStatusTransitions.STATUS_TRANSITIONS.get("producing"))
                .isEqualTo(Set.of("packed", "shipped", "cancelled"));
        assertThat(OrderStatusTransitions.STATUS_TRANSITIONS.get("shipped")).isEqualTo(Set.of("completed"));
        assertThat(OrderStatusTransitions.STATUS_TRANSITIONS.get("completed")).isEmpty();
        assertThat(OrderStatusTransitions.STATUS_TRANSITIONS.get("cancelled")).isEmpty();
        // 标签：既有六条一字未改
        assertThat(OrderStatusTransitions.label("pending")).isEqualTo("待付款");
        assertThat(OrderStatusTransitions.label("shipped")).isEqualTo("已发货");
        assertThat(OrderStatusTransitions.label("cancelled")).isEqualTo("已取消");
    }

    @Test
    @DisplayName("🔴 状态机是**唯一实现点**：OrderService 不得再自带一份流转表（两份迟早分叉）")
    void stateMachineHasASingleImplementation() throws Exception {
        java.lang.reflect.Field field =
                com.migao.admin.service.OrderService.class.getDeclaredField("STATUS_TRANSITIONS");
        field.setAccessible(true);
        assertThat(field.get(null))
                .as("OrderService 的流转表必须**就是** OrderStatusTransitions 那一份（同一个对象）")
                .isSameAs(OrderStatusTransitions.STATUS_TRANSITIONS);
    }
}
