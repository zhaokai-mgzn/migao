// case_ids: KF-020, KF-025
package com.migao.admin.service.kf;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * /api/internal/kf/decide 判定服务测试（issue #9185 规则短路 + issue #9196 语义判定）。
 *
 * <p>三条不可退让的口径：① **规则优先** —— 非 AI 态 / 人工词 / 风险词命中时**不发起**
 * 任何出站判定请求（省钱也省延迟，且高风险不漏）；② **升级取并集** —— 规则未命中而
 * 语义判定要求升级时取升级；③ **判定失败回退规则** —— 客户端异常/空结果不得让
 * /decide 抛错（客户消息必须有兜底）。</p>
 */
class KfDecisionServiceTest {

    /** 计数桩：记录 judge 被调用次数 —— 判据「不出站」必须可断言，而不是靠日志。 */
    static class CountingJudgeClient extends KfJudgeClient {
        final AtomicInteger calls = new AtomicInteger();
        private final Optional<Verdict> result;
        private final RuntimeException failure;

        CountingJudgeClient(Optional<Verdict> result) {
            this.result = result;
            this.failure = null;
        }

        CountingJudgeClient(RuntimeException failure) {
            this.result = Optional.empty();
            this.failure = failure;
        }

        @Override
        public Optional<Verdict> judge(long tenantId, String sessionId, String text) {
            calls.incrementAndGet();
            if (failure != null) {
                throw failure;
            }
            return result;
        }
    }

    private static KfJudgeClient.Verdict verdict(boolean escalate) {
        return new KfJudgeClient.Verdict("price", "none", "calm", 0.9, escalate, "询价");
    }

    @Test
    @DisplayName("非 AI 态 ⇒ SILENT，且不发起语义判定")
    void nonAiStateIsSilentWithoutJudge() {
        CountingJudgeClient judge = new CountingJudgeClient(Optional.of(verdict(true)));
        KfDecisionService service = new KfDecisionService(judge);

        assertThat(service.decide(1L, "s-1", 2, "你好").decision()).isEqualTo("SILENT");
        assertThat(service.decide(1L, "s-1", 3, "你好").decision()).isEqualTo("SILENT");
        assertThat(judge.calls.get()).isZero();
    }

    @Test
    @DisplayName("人工词 / 风险词 ⇒ ESCALATE_HUMAN，且不发起语义判定（规则优先）")
    void rulesWinWithoutJudge() {
        CountingJudgeClient judge = new CountingJudgeClient(Optional.of(verdict(false)));
        KfDecisionService service = new KfDecisionService(judge);

        assertThat(service.decide(1L, "s-1", 0, "我要转人工").decision()).isEqualTo("ESCALATE_HUMAN");
        assertThat(service.decide(1L, "s-1", 1, "我要投诉退款").decision()).isEqualTo("ESCALATE_HUMAN");
        assertThat(judge.calls.get()).isZero();
    }

    @Test
    @DisplayName("规则未命中 + 语义判定要升级 ⇒ ESCALATE_HUMAN（并集）")
    void judgeEscalatesWhenRulesMiss() {
        CountingJudgeClient judge = new CountingJudgeClient(Optional.of(verdict(true)));
        KfDecisionService service = new KfDecisionService(judge);

        KfDecisionService.Decision d = service.decide(1L, "s-1", 0, "你们这做工我很失望");
        assertThat(d.decision()).isEqualTo("ESCALATE_HUMAN");
        assertThat(d.reason()).contains("语义判定");
        assertThat(judge.calls.get()).isEqualTo(1);
    }

    @Test
    @DisplayName("规则未命中 + 语义判定不升级 ⇒ AI_REPLY")
    void judgeDoesNotEscalate() {
        CountingJudgeClient judge = new CountingJudgeClient(Optional.of(verdict(false)));
        KfDecisionService service = new KfDecisionService(judge);

        assertThat(service.decide(1L, "s-1", 0, "这款多少钱").decision()).isEqualTo("AI_REPLY");
        assertThat(judge.calls.get()).isEqualTo(1);
    }

    @Test
    @DisplayName("语义判定不可用（空结果 / 异常）⇒ 回退规则 AI_REPLY，不抛错")
    void judgeFailureFallsBackToRules() {
        KfDecisionService emptyJudge = new KfDecisionService(
                new CountingJudgeClient(Optional.empty()));
        assertThat(emptyJudge.decide(1L, "s-1", 0, "这款多少钱").decision()).isEqualTo("AI_REPLY");

        KfDecisionService failingJudge = new KfDecisionService(
                new CountingJudgeClient(new IllegalStateException("timeout")));
        assertThat(failingJudge.decide(1L, "s-1", 0, "这款多少钱").decision()).isEqualTo("AI_REPLY");
    }

    @Test
    @DisplayName("「客服」单独出现不算要人工（称呼/寒暄/询问）⇒ 交给语义判定，不升级")
    void bareCustomerServiceWordDoesNotEscalate() {
        CountingJudgeClient judge = new CountingJudgeClient(Optional.of(verdict(false)));
        KfDecisionService service = new KfDecisionService(judge);

        for (String text : new String[]{"客服你好", "你们客服在吗", "客服电话多少"}) {
            assertThat(service.decide(1L, "s-1", 0, text).decision())
                    .as("「%s」是寒暄/询问，不该被推给人工（裁定 A：默认 AI）", text)
                    .isEqualTo("AI_REPLY");
        }
        // 规则未命中 ⇒ 确实走了语义判定补召回（不是被规则直接放行）
        assertThat(judge.calls.get()).isEqualTo(3);
    }

    @Test
    @DisplayName("明确索取人工（我要人工/转人工/找客服处理/人工客服）⇒ ESCALATE_HUMAN，且不发起语义判定")
    void explicitHumanRequestEscalates() {
        CountingJudgeClient judge = new CountingJudgeClient(Optional.of(verdict(false)));
        KfDecisionService service = new KfDecisionService(judge);

        for (String text : new String[]{"我要人工", "转人工", "找客服处理", "人工客服"}) {
            assertThat(service.decide(1L, "s-1", 0, text).decision())
                    .as("「%s」是明确索取人工，永不漏", text)
                    .isEqualTo("ESCALATE_HUMAN");
        }
        assertThat(judge.calls.get()).isZero();
    }

    @Test
    @DisplayName("风险词表逐字未变（产业口径：投诉/退款/赔偿/起诉/律师/曝光/差评）")
    void riskWordsUnchanged() {
        assertThat(KfDecisionService.RISK_WORDS)
                .containsExactly("投诉", "退款", "赔偿", "起诉", "律师", "曝光", "差评");
    }
}
