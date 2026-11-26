package com.migao.admin.service.kf;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Optional;

/**
 * 介入判定（issue #9185 规则短路 + issue #9196 语义判定）。
 *
 * <p>判定顺序 = <b>规则优先，语义补召回，升级取并集</b>：</p>
 * <ol>
 *   <li><b>非 AI 可回复态</b>（state ∉ {0,1}）⇒ {@code SILENT}，且**不发起**语义判定；</li>
 *   <li><b>规则命中</b>（人工词 / 风险词）⇒ {@code ESCALATE_HUMAN}，且**不发起**语义判定
 *       —— 省钱省延迟，且「高风险/要人工永不漏」；</li>
 *   <li><b>规则未命中</b> ⇒ 问 ai-agent 语义判定：它要升级则升级（并集），否则 {@code AI_REPLY}；</li>
 *   <li><b>判定不可用</b>（超时 / 异常 / 空结果）⇒ 回退规则结论 {@code AI_REPLY}，
 *       {@code /decide} 永不因判定服务故障而抛错。</li>
 * </ol>
 */
@Service
@ConditionalOnProperty(prefix = "wechat.kf", name = "enabled", havingValue = "true")
public class KfDecisionService {

    private static final List<String> HUMAN_WORDS = List.of("人工", "真人", "客服", "转人工");
    private static final List<String> RISK_WORDS = List.of("投诉", "退款", "赔偿", "起诉", "律师", "曝光", "差评");

    private final KfJudgeClient judgeClient;

    public KfDecisionService(KfJudgeClient judgeClient) {
        this.judgeClient = judgeClient;
    }

    public record Decision(String decision, String reason) {
    }

    public Decision decide(long tenantId, String sessionId, int state, String text) {
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
        try {
            Optional<KfJudgeClient.Verdict> verdict = judgeClient.judge(tenantId, sessionId, content);
            if (verdict.isPresent() && verdict.get().escalate()) {
                return new Decision("ESCALATE_HUMAN", "语义判定升级：" + verdict.get().reason());
            }
            if (verdict.isPresent()) {
                return new Decision("AI_REPLY", "语义判定 AI 可答：" + verdict.get().intent());
            }
            return new Decision("AI_REPLY", "语义判定不可用，回退规则");
        } catch (RuntimeException e) {
            // 兜底：判定客户端已自行吞异常，这里防的是契约变化（实现换了仍不许打穿 /decide）
            return new Decision("AI_REPLY", "语义判定异常，回退规则");
        }
    }
}
