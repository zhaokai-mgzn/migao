package com.migao.admin.service.kf;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 介入判定（issue #9185）：规则短路，LLM 判定后续接入；先保证“高风险/要人工”永不漏。
 */
@Service
@ConditionalOnProperty(prefix = "wechat.kf", name = "enabled", havingValue = "true")
public class KfDecisionService {

    private static final List<String> HUMAN_WORDS = List.of("人工", "真人", "客服", "转人工");
    private static final List<String> RISK_WORDS = List.of("投诉", "退款", "赔偿", "起诉", "律师", "曝光", "差评");

    public record Decision(String decision, String reason) {
    }

    public Decision decide(int state, String text) {
        if (state != 0 && state != 1) {
            return new Decision("SILENT", "state=" + state + " 非 AI 可回复态");
        }
        String content = text == null ? "" : text;
        if (HUMAN_WORDS.stream().anyMatch(content::contains)) {
            return new Decision("ESCALATE_HUMAN", "明确要人工");
        }
        if (RISK_WORDS.stream().anyMatch(content::contains)) {
            return new Decision("ESCALATE_HUMAN", "高风险词命中");
        }
        return new Decision("AI_REPLY", "默认 AI 回复");
    }
}
