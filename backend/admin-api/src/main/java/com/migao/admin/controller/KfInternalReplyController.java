package com.migao.admin.controller;

import com.migao.admin.service.kf.KfBudgetExhaustedException;
import com.migao.admin.service.kf.KfSendService;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * AI/工作台 → 回复入队（内部服务面，ServiceTokenFilter 保护）。
 *
 * <p>只入队，不阻塞等发送；真正 send_msg 由 {@code KfOutboxSender} 异步做。</p>
 */
@RestController
@RequestMapping("/api/internal/kf")
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "wechat.kf", name = "enabled", havingValue = "true")
public class KfInternalReplyController {

    private final KfSendService sendService;

    @PostMapping("/reply")
    public ResponseEntity<Map<String, Object>> reply(@RequestBody ReplyRequest request) {
        try {
            String msgid = sendService.enqueueReply(request.tenantId(), request.sessionId(), request.text());
            return ResponseEntity.ok(Map.of("msgid", msgid));
        } catch (KfBudgetExhaustedException e) {
            return ResponseEntity.status(429).body(Map.of("error", "budget_exhausted"));
        }
    }

    public record ReplyRequest(@JsonProperty("tenant_id") Long tenantId,
                               @JsonProperty("session_id") String sessionId,
                               String text) {
    }
}
