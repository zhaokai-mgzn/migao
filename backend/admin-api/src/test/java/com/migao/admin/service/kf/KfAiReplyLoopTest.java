// case_ids: KF-015, KF-020, KF-021
package com.migao.admin.service.kf;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.KfSessionRemote;
import com.migao.admin.entity.Session;
import com.migao.admin.mapper.KfOutboxMapper;
import com.migao.admin.mapper.KfSendBudgetMapper;
import com.migao.admin.mapper.KfSessionRemoteMapper;
import com.migao.admin.mapper.SessionMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * {@code AI_REPLY} 一跳测试（issue #9302）。
 *
 * <p>四条不可退让的口径：① 判定 {@code AI_REPLY} ⇒ outbox <b>恰 1 条</b>、正文非空、
 * tenant/session 对得上；② 生成失败 / 超时 / 空正文 ⇒ <b>0 条 outbox</b> 且决策落
 * {@code ESCALATE_HUMAN}（安全底线）；③ 正文不得含 AI 无权承诺的话术、也不得含中间过程话术、
 * 且 0 次工具调用时不得报金额；④ 入队只走 {@code KfSendService}（预算护栏不得绕过）。</p>
 *
 * <p>这里用<b>真的</b> {@link KfSendService} + 假 mapper：断言直接落在
 * {@code kf_outbox.enqueue} 调用数与 parts 文本上，而不是「某个方法被调过」。</p>
 */
@DisplayName("KfAiReplyLoop — AI_REPLY 一跳")
class KfAiReplyLoopTest {

    private SessionMapper sessionMapper;
    private KfSessionRemoteMapper remoteMapper;
    private KfSendBudgetMapper budgetMapper;
    private KfOutboxMapper outboxMapper;
    private KfSendService sendService;
    private KfDecisionService decisionService;
    private KfReplyClient replyClient;
    private KfTransferService transferService;
    private KfAiReplyLoop loop;

    @BeforeEach
    void setUp() {
        sessionMapper = mock(SessionMapper.class);
        remoteMapper = mock(KfSessionRemoteMapper.class);
        budgetMapper = mock(KfSendBudgetMapper.class);
        outboxMapper = mock(KfOutboxMapper.class);
        decisionService = mock(KfDecisionService.class);
        replyClient = mock(KfReplyClient.class);
        transferService = mock(KfTransferService.class);
        sendService = new KfSendService(sessionMapper, remoteMapper, budgetMapper, outboxMapper,
                new ObjectMapper());
        loop = new KfAiReplyLoop(decisionService, replyClient, sendService, transferService);
    }

    private void givenSessionReady() {
        when(sessionMapper.selectById("s1")).thenReturn(Session.builder()
                .id("s1").tenantId(1L).channel("wechat_kf").build());
        when(remoteMapper.selectBySessionId("s1")).thenReturn(KfSessionRemote.builder()
                .sessionId("s1").tenantId(1L).openKfid("wk").externalUserid("wm").build());
        when(budgetMapper.tryConsume("s1", 1L)).thenReturn(1);
    }

    private void givenDecision(String decision) {
        when(decisionService.decide(1L, "s1", 0, "这款雪尼尔多少钱"))
                .thenReturn(new KfDecisionService.Decision(decision, "stub"));
    }

    private void givenGenerated(String text, int toolCalls) {
        when(replyClient.generate(1L, "s1", "这款雪尼尔多少钱"))
                .thenReturn(Optional.of(new KfReplyClient.Generated(text, toolCalls)));
    }

    /** 断言本次入站**没有**任何回复进入 outbox，并且走了转人工。 */
    private void assertEscalatedWithoutOutbox(KfAiReplyLoop.Outcome outcome) {
        assertThat(outcome.decision()).isEqualTo(KfAiReplyLoop.ESCALATE_HUMAN);
        assertThat(outcome.replied()).isFalse();
        verify(outboxMapper, never()).enqueue(anyLong(), anyString(), anyString(), anyString());
        verify(transferService).transferToHuman(eq(1L), eq("s1"), anyString());
    }

    @Test
    @DisplayName("AI_REPLY + 正常生成 ⇒ outbox 恰 1 条、正文非空、tenant/session 对得上")
    void aiReplyEnqueuesExactlyOneReply() {
        givenSessionReady();
        givenDecision(KfAiReplyLoop.AI_REPLY);
        givenGenerated("这款雪尼尔 68 元一米，门幅 2.8 米", 1);

        KfAiReplyLoop.Outcome outcome = loop.onCustomerMessage(1L, "s1", 0, "这款雪尼尔多少钱");

        assertThat(outcome.decision()).isEqualTo(KfAiReplyLoop.AI_REPLY);
        assertThat(outcome.replied()).isTrue();
        ArgumentCaptor<String> parts = ArgumentCaptor.forClass(String.class);
        verify(outboxMapper, times(1)).enqueue(eq(1L), eq("s1"), anyString(), parts.capture());
        assertThat(parts.getValue()).contains("这款雪尼尔 68 元一米");
        verify(transferService, never()).transferToHuman(anyLong(), anyString(), anyString());
        verify(budgetMapper, times(1)).tryConsume("s1", 1L);
    }

    @Test
    @DisplayName("生成失败（内核不可用/超时）⇒ 0 条 outbox + 决策转 ESCALATE_HUMAN")
    void generationFailureEscalatesWithoutOutbox() {
        givenSessionReady();
        givenDecision(KfAiReplyLoop.AI_REPLY);
        when(replyClient.generate(1L, "s1", "这款雪尼尔多少钱")).thenReturn(Optional.empty());

        assertEscalatedWithoutOutbox(loop.onCustomerMessage(1L, "s1", 0, "这款雪尼尔多少钱"));
    }

    @Test
    @DisplayName("生成空正文 / 只有空白 ⇒ 0 条 outbox + 转人工（绝不发空话）")
    void blankGenerationEscalates() {
        givenSessionReady();
        givenDecision(KfAiReplyLoop.AI_REPLY);
        givenGenerated("   ", 0);

        assertEscalatedWithoutOutbox(loop.onCustomerMessage(1L, "s1", 0, "这款雪尼尔多少钱"));
    }

    @Test
    @DisplayName("正文含 AI 无权承诺的话术（已为您转接/已通知人工）⇒ 转人工，不发给客户")
    void forbiddenPromiseEscalates() {
        givenSessionReady();
        givenDecision(KfAiReplyLoop.AI_REPLY);
        givenGenerated("已为您转接人工客服，请稍等", 1);

        assertEscalatedWithoutOutbox(loop.onCustomerMessage(1L, "s1", 0, "这款雪尼尔多少钱"));
    }

    @Test
    @DisplayName("正文是中间过程话术（正在查询/请稍等）⇒ 转人工（48h/5 条预算不许烧在中间气泡上）")
    void intermediateProcessEscalates() {
        givenSessionReady();
        givenDecision(KfAiReplyLoop.AI_REPLY);
        givenGenerated("正在查询库存，请稍等", 1);

        assertEscalatedWithoutOutbox(loop.onCustomerMessage(1L, "s1", 0, "这款雪尼尔多少钱"));
    }

    @Test
    @DisplayName("0 次工具调用却报出金额 ⇒ 视为模型编造 ⇒ 转人工")
    void priceWithoutToolCallEscalates() {
        givenSessionReady();
        givenDecision(KfAiReplyLoop.AI_REPLY);
        givenGenerated("这款雪尼尔 68 元一米", 0);

        assertEscalatedWithoutOutbox(loop.onCustomerMessage(1L, "s1", 0, "这款雪尼尔多少钱"));
    }

    @Test
    @DisplayName("金额来自工具调用（toolCalls≥1）⇒ 正常发送，不误杀")
    void priceWithToolCallIsDelivered() {
        givenSessionReady();
        givenDecision(KfAiReplyLoop.AI_REPLY);
        givenGenerated("这款雪尼尔 68 元一米", 2);

        assertThat(loop.onCustomerMessage(1L, "s1", 0, "这款雪尼尔多少钱").replied()).isTrue();
        verify(outboxMapper, times(1)).enqueue(eq(1L), eq("s1"), anyString(), anyString());
    }

    @Test
    @DisplayName("判定 ESCALATE_HUMAN ⇒ 不生成、不发、直接转人工")
    void decisionEscalateSkipsGeneration() {
        givenSessionReady();
        givenDecision(KfAiReplyLoop.ESCALATE_HUMAN);

        assertEscalatedWithoutOutbox(loop.onCustomerMessage(1L, "s1", 0, "这款雪尼尔多少钱"));
        verify(replyClient, never()).generate(anyLong(), anyString(), anyString());
    }

    @Test
    @DisplayName("判定 SILENT（人工接待中）⇒ 不抢话：不发也不转人工")
    void silentDecisionDoesNothing() {
        when(decisionService.decide(1L, "s1", 2, "这款雪尼尔多少钱"))
                .thenReturn(new KfDecisionService.Decision("SILENT", "state=2"));

        KfAiReplyLoop.Outcome outcome = loop.onCustomerMessage(1L, "s1", 2, "这款雪尼尔多少钱");

        assertThat(outcome.decision()).isEqualTo("SILENT");
        verify(outboxMapper, never()).enqueue(anyLong(), anyString(), anyString(), anyString());
        verify(transferService, never()).transferToHuman(anyLong(), anyString(), anyString());
    }

    @Test
    @DisplayName("预算耗尽（KfSendService 拒绝入队）⇒ 不绕开护栏、0 条 outbox + 转人工")
    void budgetExhaustedEscalates() {
        when(sessionMapper.selectById("s1")).thenReturn(Session.builder()
                .id("s1").tenantId(1L).channel("wechat_kf").build());
        when(remoteMapper.selectBySessionId("s1")).thenReturn(KfSessionRemote.builder()
                .sessionId("s1").tenantId(1L).openKfid("wk").build());
        when(budgetMapper.tryConsume("s1", 1L)).thenReturn(0);
        givenDecision(KfAiReplyLoop.AI_REPLY);
        givenGenerated("这款雪尼尔 68 元一米", 1);

        assertEscalatedWithoutOutbox(loop.onCustomerMessage(1L, "s1", 0, "这款雪尼尔多少钱"));
    }

    @Test
    @DisplayName("转人工失败不冒泡（客户消息已落库，同步轮必须继续推进游标）")
    void transferFailureDoesNotBubble() {
        givenSessionReady();
        givenDecision(KfAiReplyLoop.AI_REPLY);
        when(replyClient.generate(1L, "s1", "这款雪尼尔多少钱")).thenReturn(Optional.empty());
        doThrow(new IllegalStateException("渠道 secret 不可用"))
                .when(transferService).transferToHuman(eq(1L), eq("s1"), anyString());

        assertThat(loop.onCustomerMessage(1L, "s1", 0, "这款雪尼尔多少钱").decision())
                .isEqualTo(KfAiReplyLoop.ESCALATE_HUMAN);
        verify(outboxMapper, never()).enqueue(anyLong(), anyString(), anyString(), anyString());
    }
}
