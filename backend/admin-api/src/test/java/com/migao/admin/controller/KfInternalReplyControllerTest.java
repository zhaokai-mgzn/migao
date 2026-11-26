// case_ids: KF-019
package com.migao.admin.controller;

import com.migao.admin.service.kf.KfBudgetExhaustedException;
import com.migao.admin.service.kf.KfSendService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class KfInternalReplyControllerTest {

    @Test
    @DisplayName("入队成功返回 msgid；预算耗尽返回 429")
    void reply() {
        KfSendService service = mock(KfSendService.class);
        KfInternalReplyController controller = new KfInternalReplyController(service);

        when(service.enqueueReply(1L, "s1", "你好")).thenReturn("m1");
        ResponseEntity<Map<String, Object>> ok = controller.reply(
                new KfInternalReplyController.ReplyRequest(1L, "s1", "你好"));
        assertThat(ok.getStatusCode().value()).isEqualTo(200);
        assertThat(ok.getBody()).containsEntry("msgid", "m1");

        when(service.enqueueReply(1L, "s1", "x")).thenThrow(new KfBudgetExhaustedException("s1"));
        ResponseEntity<Map<String, Object>> limited = controller.reply(
                new KfInternalReplyController.ReplyRequest(1L, "s1", "x"));
        assertThat(limited.getStatusCode().value()).isEqualTo(429);
    }
}
