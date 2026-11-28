package com.migao.admin.service.kf;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Optional;
import java.util.regex.Pattern;

/**
 * 介入判定（issue #9185 规则短路 + issue #9196 语义判定）。
 *
 * <p>判定顺序 = <b>默认 AI、例外升级</b>（2026-11-28 用户裁定 A：「大部分客服工作都要由我们的智能客服
 * 完成，只有 AI 搞不定的事情才转人工」）：</p>
 * <ol>
 *   <li><b>非 AI 可回复态</b>（state ∉ {0,1}）⇒ {@code SILENT}，且**不发起**语义判定；</li>
 *   <li><b>规则命中</b>（明确索取人工 / 风险词）⇒ {@code ESCALATE_HUMAN}，且**不发起**语义判定
 *       —— 省钱省延迟，且「高风险/要人工永不漏」；</li>
 *   <li><b>规则未命中</b> ⇒ 问 ai-agent 语义判定：它要升级则升级（并集），否则 {@code AI_REPLY}；</li>
 *   <li><b>判定不可用</b>（超时 / 异常 / 空结果）⇒ 回退规则结论 {@code AI_REPLY}，
 *       {@code /decide} 永不因判定服务故障而抛错。</li>
 * </ol>
 */
@Service
@ConditionalOnProperty(prefix = "wechat.kf", name = "enabled", havingValue = "true")
public class KfDecisionService {

    /**
     * 明确索取人工服务的形态（**默认 AI、例外升级**；issue #9302）。
     *
     * <p><b>为什么不能只匹配「客服」</b>：微信客服场景里「客服你好」「你们客服在吗」「客服电话多少」
     * 都是称呼 / 寒暄 / 询问，不是要人工。把「客服」单独判成升级 = 把本该 AI 接住的对话推给人工，
     * 与「大部分客服工作由智能客服完成」的裁定相反（历史实现就是这么写的，issue #9302 修）。</p>
     *
     * <p>所以只认两类形态：① {@code 人工} / {@code 真人} <b>单独出现</b>（中文里几乎专指人工服务，
     * 「我要人工」「转人工」「找人工」都覆盖）；② <b>动作词 + 对象词</b>（找 / 要 / 叫 / 联系 / 转 /
     * 需要 / 请 + 人工 / 真人 / 客服），如「找客服处理」「联系客服」「叫客服来」。</p>
     *
     * <p><b>不许为了「少升级」把它改回去</b>：漏掉明确索取比多接一轮更坏（客户已明说要人，AI 还抢着答），
     * 安全侧只往严里走；{@link #RISK_WORDS} 的风险词一个都不许删。</p>
     */
    private static final Pattern HUMAN_REQUEST =
            Pattern.compile("人工|真人|(找|要|叫|联系|转|需要|请)\\s*(人工|真人|客服)");

    /** 高风险词（投诉 / 退款 / 赔偿 / 起诉 / 律师 / 曝光 / 差评）—— 一个字都不许动（判据直接断言集合）。 */
    static final List<String> RISK_WORDS = List.of("投诉", "退款", "赔偿", "起诉", "律师", "曝光", "差评");

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
        if (HUMAN_REQUEST.matcher(content).find()) {
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
