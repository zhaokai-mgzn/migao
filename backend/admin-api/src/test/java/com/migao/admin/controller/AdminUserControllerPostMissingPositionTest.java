// case_ids: API-023
package com.migao.admin.controller;

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Role;
import com.migao.admin.service.RoleService;
import com.migao.admin.service.UserService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * {@code POST /api/admin/users} <b>缺岗位/角色</b>的 HTTP 语义（issue #5987）。
 *
 * <h2>缺陷（修前实测）</h2>
 * 请求体只有 {@code {"name","phone","username","password"}}（既无 {@code position}，也无
 * {@code role} / {@code roleIds}）⇒ 控制器把 {@code role} 兜底成 {@code operator}，
 * 账号拿到<b>运营级 26 码</b>（含 {@code order:create} / {@code inbound:create} /
 * {@code finance:create} / {@code order:refund} 等写权限）+ 岗位名也被写成 {@code operator}。
 * 后台员工页**强制选岗位** ⇒ 页面走不到，仅 API 直连（AI 工具面 / 集成方 / 脚本）可达。
 *
 * <h2>期望（fail-closed）</h2>
 * 缺省不再按 {@code operator} 兜底 ⇒ <b>400</b>，文案**点名要选岗位**，且闸门在
 * <b>调用 {@code userService.createUser} 之前</b>（{@code verifyNoInteractions} = 「没落库」的行为等价读数）。
 *
 * <h2>对照读数（证明本文件不是「什么都返 400」）</h2>
 * <ul>
 *   <li>带 {@code position}（岗位 = 角色体系 #2969）⇒ 200，且 role/position 都按岗位解析结果下发；</li>
 *   <li>带 {@code role}` 不传 position（既有契约 {@code employee-role.position-fallback}）⇒ 仍 200，
 *       position 回退为角色名。</li>
 * </ul>
 *
 * <p>本文件是**实例判据**（真端点 + 真 {@code @RestControllerAdvice} 经 MockMvc 分发链）；
 * 服务层实例判据 = {@code EmployeeGrantChokepointMetaGuardTest}，
 * 类级元守卫（缺省角色字面量台账）在同一文件。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("API 建号缺岗位/角色（#5987）：400 + 未落库，不按 operator 兜底")
class AdminUserControllerPostMissingPositionTest {

    private static final String URL = "/api/admin/users";
    private static final long TENANT_ID = 24L;

    private MockMvc mockMvc;

    @Mock
    private UserService userService;

    @Mock
    private RoleService roleService;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders
                .standaloneSetup(new AdminUserController(userService, roleService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
        TenantContext.setTenantId(TENANT_ID);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Test
    @DisplayName("🔴 缺 position 且缺 role/roleIds ⇒ 422 VALIDATION_ERROR（文案点名「岗位」），且一行都不落库")
    void missingPositionAndRoleIsRejected() throws Exception {
        String body = mockMvc.perform(post(URL)
                        .contentType("application/json")
                        .content("{\"phone\":\"13900000001\",\"password\":\"init-pass-123\","
                                + "\"name\":\"无岗位\",\"username\":\"nobody\"}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                .andReturn().getResponse().getContentAsString();

        // 「可行动文案」= 点名要选岗位（用户/集成方知道下一步做什么）
        assertThat(body).contains("岗位");
        // 闸门必须在**业务层之前**拦住：没进 service = 没落库（"返回了 422" 不等于 "没写进去"）
        verifyNoInteractions(userService);
    }

    @Test
    @DisplayName("领域闸门（即使绕过控制器校验）：岗位解析不出角色 ⇒ 422「无法解析该岗位/角色」，不落库")
    void blankPositionIsRejected() throws Exception {
        mockMvc.perform(post(URL)
                        .contentType("application/json")
                        .content("{\"phone\":\"13900000002\",\"password\":\"init-pass-123\","
                                + "\"name\":\"空岗位\",\"position\":\"不存在的岗位\"}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"));

        verifyNoInteractions(userService);
    }

    @Test
    @DisplayName("显式传 role=\"\" （缺省的另一种写法）⇒ 422「角色不能为空」，不落库")
    void blankRoleIsRejected() throws Exception {
        mockMvc.perform(post(URL)
                        .contentType("application/json")
                        .content("{\"phone\":\"13900000005\",\"password\":\"init-pass-123\","
                                + "\"name\":\"空角色\",\"position\":\"客服\",\"role\":\"\"}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"));

        verifyNoInteractions(userService);
    }

    @Test
    @DisplayName("对照①：带 position（岗位=角色体系 #2969）⇒ 200，role/position 按岗位解析下发")
    void withPositionItReachesTheService() throws Exception {
        Role operatorRole = Role.builder().id("role-op").code("operator").tenantId(TENANT_ID).build();
        when(roleService.getRoleByPosition("运营", TENANT_ID)).thenReturn(operatorRole);
        when(roleService.getRolePermissions("role-op")).thenReturn(List.of());
        when(userService.createUser(any(), any(), any(), any(), any(), any(), any(), any(), anyBoolean()))
                .thenAnswer(invocation -> {
                    com.migao.admin.entity.User u = new com.migao.admin.entity.User();
                    u.setId("user-op");
                    return u;
                });

        mockMvc.perform(post(URL)
                        .contentType("application/json")
                        .content("{\"phone\":\"13900000003\",\"password\":\"init-pass-123\",\"name\":\"运营小王\""
                                + ",\"position\":\"运营\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));

        verify(userService).createUser(eq("13900000003"), eq("init-pass-123"), eq("运营小王"),
                eq("operator"), eq("运营"), any(), eq(TENANT_ID), eq(null), eq(true));
    }

    @Test
    @DisplayName("对照②：带 role 不传 position ⇒ 200，position 回退为角色名（既有契约不回归）")
    void roleOnlyStillFallsBackPositionToRole() throws Exception {
        // 显式 role ⇒ 角色不由岗位解析；岗位名回退为角色名（同日岗位解析只喂权限快照预填）
        when(roleService.getRoleByPosition("finance", TENANT_ID)).thenReturn(null);
        com.migao.admin.entity.User persisted = new com.migao.admin.entity.User();
        persisted.setId("user-finance");
        when(userService.createUser(any(), any(), any(), any(), any(), any(), any(), any(), anyBoolean()))
                .thenReturn(persisted);

        mockMvc.perform(post(URL)
                        .contentType("application/json")
                        .content("{\"phone\":\"13900000004\",\"password\":\"init-pass-123\",\"name\":\"财务小李\""
                                + ",\"role\":\"finance\"}"))
                .andExpect(status().isOk());

        verify(userService).createUser(eq("13900000004"), eq("init-pass-123"), eq("财务小李"),
                eq("finance"), eq("finance"), any(), eq(TENANT_ID), eq(null), eq(true));
    }
}
