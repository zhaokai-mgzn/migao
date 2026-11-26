// case_ids: KF-005
package com.migao.admin.controller;

import com.migao.admin.service.kf.KfCallbackService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class KfCallbackControllerTest {

    @Test
    @DisplayName("GET 验签成功返回明文；未配置返回 503")
    void verifyEndpoint() throws Exception {
        KfCallbackService service = mock(KfCallbackService.class);
        MockMvc mvc = MockMvcBuilders.standaloneSetup(new KfCallbackController(service)).build();

        when(service.isConfigured()).thenReturn(false);
        mvc.perform(get("/api/kf/callback")
                        .param("msg_signature", "s").param("timestamp", "1")
                        .param("nonce", "n").param("echostr", "e"))
                .andExpect(status().isServiceUnavailable());

        when(service.isConfigured()).thenReturn(true);
        when(service.verifyUrl("s", "1", "n", "e")).thenReturn("echo-ok");
        mvc.perform(get("/api/kf/callback")
                        .param("msg_signature", "s").param("timestamp", "1")
                        .param("nonce", "n").param("echostr", "e"))
                .andExpect(status().isOk())
                .andExpect(content().string("echo-ok"));
    }

    @Test
    @DisplayName("POST 转交 service 并回 200 空串")
    void receiveEndpoint() throws Exception {
        KfCallbackService service = mock(KfCallbackService.class);
        when(service.isConfigured()).thenReturn(true);
        MockMvc mvc = MockMvcBuilders.standaloneSetup(new KfCallbackController(service)).build();

        mvc.perform(post("/api/kf/callback")
                        .param("msg_signature", "s").param("timestamp", "1").param("nonce", "n")
                        .content("<xml/>"))
                .andExpect(status().isOk())
                .andExpect(content().string(""));

        verify(service).handle("<xml/>", "s", "1", "n");
    }
}
