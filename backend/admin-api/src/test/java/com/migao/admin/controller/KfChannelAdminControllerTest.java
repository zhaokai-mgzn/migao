// case_ids: KF-030
package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.service.kf.KfChannelAdminService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class KfChannelAdminControllerTest {

    private KfChannelAdminService service;
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        service = mock(KfChannelAdminService.class);
        mvc = MockMvcBuilders.standaloneSetup(new KfChannelAdminController(service)).build();
        TenantContext.setTenantId(1L);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Test
    @DisplayName("列表只回渠道视图（无 secret）")
    void list() throws Exception {
        when(service.list(1L)).thenReturn(List.of(new KfChannelAdminService.ChannelView(
                "ch-1", "corp", "wk-1", "self_built", "active", "t", "t")));

        mvc.perform(get("/api/admin/kf/channels"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data[0].openKfid").value("wk-1"))
                .andExpect(jsonPath("$.data[0].secret").doesNotExist());
    }

    @Test
    @DisplayName("接入请求字段 snake_case 映射 + 返回 verified")
    void create() throws Exception {
        when(service.create(eq(1L), any())).thenReturn(new KfChannelAdminService.CreateResult(
                new KfChannelAdminService.ChannelView("ch-1", "corp", "wk-1", "self_built",
                        "active", "t", "t"), true, "ok"));

        mvc.perform(post("/api/admin/kf/channels")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"corp_id\":\"corp\",\"open_kfid\":\"wk-1\",\"secret\":\"sec\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.verified").value(true));
        verify(service).create(1L, new KfChannelAdminService.CreateCommand("corp", "wk-1", "sec"));
    }

    @Test
    @DisplayName("生成客服链接返回 url")
    void link() throws Exception {
        when(service.link(1L, "ch-1", "tenant:1")).thenReturn("https://kf.example/q");

        mvc.perform(post("/api/admin/kf/channels/ch-1/link")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"scene_param\":\"tenant:1\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.url").value("https://kf.example/q"));
    }
}
