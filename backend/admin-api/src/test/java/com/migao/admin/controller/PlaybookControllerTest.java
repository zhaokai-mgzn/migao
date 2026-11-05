package com.migao.admin.controller;

// case_ids: MC-230

import com.migao.admin.security.RequirePermission;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;

import java.lang.reflect.Method;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 口径卡控制器的**权限面与路由面**判据（issue #8175）。
 *
 * <p>为什么值得单独钉：这是「读码 / 写码不许混」的机械形态。把退役（写面）挂到
 * `knowledge:view`，或把列表（读面）挂到 `knowledge:manage`，功能上都「能用」，
 * 但权限面已经错了 —— 而错误方向是**扩大**（读码能退役 = 任何能看知识库的人都能撤掉
 * 全企业的口径）。既有行为只有人眼能看出来，所以这里钉成反射判据。</p>
 *
 * <p>红证：把任一写端点的注解改成 {@code knowledge:view}（或删掉注解）⇒ 本类必红。
 * 满足权限注解的其它既有守卫（RBAC 单一真值源 / 端点写码）口径一致。</p>
 */
@DisplayName("PlaybookController：读面用读码、写面（落卡/审核/退役）用写码")
class PlaybookControllerTest {

    private static RequirePermission permissionOf(String name, Class<?>... types) throws Exception {
        Method m = PlaybookController.class.getMethod(name, types);
        return m.getAnnotation(RequirePermission.class);
    }

    @Test
    @DisplayName("列表是读面 ⇒ knowledge:view")
    void pageUsesReadCode() throws Exception {
        RequirePermission p = permissionOf("page", String.class, long.class, long.class);
        assertThat(p).isNotNull();
        assertThat(p.value()).isEqualTo("knowledge:view");
        assertThat(PlaybookController.class.getMethod("page", String.class, long.class, long.class)
                .getAnnotation(GetMapping.class)).isNotNull();
    }

    @Test
    @DisplayName("落卡 / 审核 / 退役是写面 ⇒ 三个都必须是 knowledge:manage")
    void writeEndpointsUseManageCode() throws Exception {
        assertThat(permissionOf("create", com.migao.admin.entity.Playbook.class).value())
                .isEqualTo("knowledge:manage");
        assertThat(permissionOf("activate", String.class).value()).isEqualTo("knowledge:manage");
        assertThat(permissionOf("retire", String.class).value()).isEqualTo("knowledge:manage");

        assertThat(PlaybookController.class.getMethod("create", com.migao.admin.entity.Playbook.class)
                .getAnnotation(PostMapping.class)).isNotNull();
        assertThat(PlaybookController.class.getMethod("activate", String.class)
                .getAnnotation(PostMapping.class).value()).containsExactly("/{id}/activate");
        assertThat(PlaybookController.class.getMethod("retire", String.class)
                .getAnnotation(PostMapping.class).value()).containsExactly("/{id}/retire");
    }

    @Test
    @DisplayName("路由落在 /api/admin/playbooks 下（租户上下文由拦截器注入，不靠路径参数）")
    void routesLiveUnderAdminPlaybooks() {
        RequestMapping mapping = PlaybookController.class.getAnnotation(RequestMapping.class);
        assertThat(mapping).isNotNull();
        assertThat(mapping.value()).containsExactly("/api/admin/playbooks");
    }
}
