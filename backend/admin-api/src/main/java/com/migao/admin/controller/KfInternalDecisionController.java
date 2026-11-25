package com.migao.admin.controller;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.migao.admin.service.kf.KfDecisionService;
import com.migao.admin.service.kf.KfTransferService;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/** AI 判定 / 转人工内部服务面（ServiceTokenFilter 保护）。 */
@RestController
@RequestMapping("/api/internal/kf")
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "wechat.kf", name = "enabled", havingValue = "true")
public class KfInternalDecisionController {

    private final KfDecisionService decisionService;
    private final KfTransferService transferService;

    @PostMapping("/decide")
    public ResponseEntity<Map<String, Object>> decide(@RequestBody DecideRequest request) {
        KfDecisionService.Decision d = decisionService.decide(request.state(), request.text());
        return ResponseEntity.ok(Map.of("decision", d.decision(), "reason", d.reason()));
    }

    @PostMapping("/transfer")
    public ResponseEntity<Map<String, Object>> transfer(@RequestBody TransferRequest request) {
        String agentSessionId = transferService.transferToHuman(
                request.tenantId(), request.sessionId(), request.reason());
        return ResponseEntity.ok(Map.of("agent_session_id", agentSessionId));
    }

    public record DecideRequest(@JsonProperty("tenant_id") Long tenantId,
                                @JsonProperty("session_id") String sessionId,
                                int state,
                                String text) {
    }

    public record TransferRequest(@JsonProperty("tenant_id") Long tenantId,
                                  @JsonProperty("session_id") String sessionId,
                                  String reason) {
    }
}
