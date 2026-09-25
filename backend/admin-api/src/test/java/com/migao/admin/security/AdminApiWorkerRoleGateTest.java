// case_ids: DF-017, PG-020, BM-005
package com.migao.admin.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.security.authentication.AnonymousAuthenticationToken;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.authorization.AuthorizationDecision;
import org.springframework.security.authorization.AuthorizationManager;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.web.access.intercept.RequestAuthorizationContext;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * `/api/admin/**` 门禁的**工人角色拒绝**（issue #4733，设计 #4716 W7 / C11）。
 *
 * <p><b>拒绝集合的来源（不新造第二套）</b>：{@code worker} 由 <b>#4727</b>（PR #4738，已落 main）
 * 按 #4716 设计 C11 **预留**进 {@code ADMIN_API_REJECTED_ROLES}；<b>本单（#4733）不复制第二份判定</b>，
 * 只做两件事：① 落码「工人可达面 = {@code /api/worker/**}」（不匹配 {@code /api/admin/**}）；
 * ② 把该集合的既有判据钉成**红证**（本文件）。</p>
 *
 * <p><b>红证形态（worker 加入拒绝集合之前必红）</b>：旧口径的第三分支是「其余角色视为商户员工角色
 * ⇒ 允许进入」。工人持 {@code role=worker} 且 {@code permissions=[]} ⇒ 该分支**放行** ⇒ 工人可进管理后台；
 * 而 {@code permissions=[]} 只能拦住带 {@code @RequirePermission} 的端点（#4727 审计：有 11 个
 * controller 完全没有该注解）⇒ 「工人无商家权限」不成立。实测（本单，在 {@code origin/main@791fdd6b1}
 * 的**父提交**上跑）：{@code worker 角色访问 /api/admin/** granted = true}。</p>
 *
 * <p><b>反向护栏</b>：既有三条分支一字不改 —— 平台管理员/内部服务放行、customer/agent 拒绝、
 * 商户员工角色放行（逐条断言）。</p>
 *
 * <p>为什么不走 {@code @SpringBootTest + MockMvc}：本类断言的是**门禁判定本体**（纯函数），
 * 用 {@code SecurityConfig} 的真实 bean 直接调，既避开全上下文装配，又不会因为
 * 「工厂/过滤器」那一层而把判据的失败原因搅浑。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("/api/admin/** 门禁：工人角色拒绝（W7）+ 既有分支不回归")
class AdminApiWorkerRoleGateTest {

    @Mock
    private JwtAuthenticationFilter jwtAuthenticationFilter;
    @Mock
    private ServiceTokenFilter serviceTokenFilter;
    @Mock
    private WorkerSessionFilter workerSessionFilter;
    @Mock
    private PasswordChangeRequiredFilter passwordChangeRequiredFilter;
    @Mock
    private org.springframework.security.core.userdetails.UserDetailsService userDetailsService;

    private AuthorizationManager<RequestAuthorizationContext> gate() {
        SecurityConfig config = new SecurityConfig(jwtAuthenticationFilter, serviceTokenFilter,
                workerSessionFilter, passwordChangeRequiredFilter, userDetailsService, new ObjectMapper());
        return config.adminApiAuthorizationManager();
    }

    private AuthorizationDecision decide(Authentication authentication) {
        return gate().check(() -> authentication, null);
    }

    private Authentication auth(String... roles) {
        List<SimpleGrantedAuthority> authorities = java.util.Arrays.stream(roles)
                .map(r -> new SimpleGrantedAuthority("ROLE_" + r.toUpperCase()))
                .toList();
        return new UsernamePasswordAuthenticationToken("principal-1", null, authorities);
    }

    // ============================================================ ① 工人必须被拒（红证）

    @Test
    @DisplayName("🔴 工人角色（worker）访问 /api/admin/** ⇒ 必拒（改前放行 ⇒ 红）")
    void workerRoleDeniedOnAdminApi() {
        assertThat(decide(auth("worker")).isGranted())
                .as("工人是计件归属身份，不是商家员工 —— 必须拒绝（否则 /api/admin/user、/api/admin/menus 那批无注解端点会放行）")
                .isFalse();
    }

    @Test
    @DisplayName("🔴 工人角色同时挂商户员工角色（伪造叠加）⇒ 仍拒（worker 一票否决，不给「叠加绕过」留口子）")
    void workerRoleDeniedEvenWhenCombinedWithStaffRole() {
        assertThat(decide(auth("worker", "operator")).isGranted()).isFalse();
        assertThat(decide(auth("operator", "worker")).isGranted()).isFalse();
    }

    // ============================================================ ② 既有分支不回归

    @Test
    @DisplayName("反向护栏：平台管理员 / 内部服务仍放行（既有分支一字不改）")
    void adminAndServiceStillAllowed() {
        assertThat(decide(auth("admin")).isGranted()).isTrue();
        assertThat(decide(auth("super_admin")).isGranted()).isTrue();
        assertThat(decide(auth("service")).isGranted()).isTrue();
    }

    @Test
    @DisplayName("反向护栏：customer / agent 仍一律拒绝（垂直越权防护不回归）")
    void customerAndAgentStillDenied() {
        assertThat(decide(auth("customer")).isGranted()).isFalse();
        assertThat(decide(auth("agent")).isGranted()).isFalse();
    }

    @Test
    @DisplayName("反向护栏：商户员工角色（含自定义角色）仍允许进入，细粒度交业务层（既有口径）")
    void merchantStaffStillAllowed() {
        assertThat(decide(auth("operator")).isGranted()).isTrue();
        assertThat(decide(auth("custom_role_x")).isGranted()).isTrue();
    }

    @Test
    @DisplayName("反向护栏：未认证 / 匿名仍拒绝")
    void anonymousStillDenied() {
        assertThat(gate().check(() -> null, null).isGranted()).isFalse();
        Authentication anonymous = new AnonymousAuthenticationToken(
                "k", "anonymous", List.of(new SimpleGrantedAuthority("ROLE_ANONYMOUS")));
        assertThat(decide(anonymous).isGranted()).isFalse();
    }
}
