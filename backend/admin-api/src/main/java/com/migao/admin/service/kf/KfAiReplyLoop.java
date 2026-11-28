package com.migao.admin.service.kf;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Optional;
import java.util.regex.Pattern;

/**
 * {@code AI_REPLY} 一跳（issue #9302）：判定 → 内核产文 → 入队 → 失败兜底。
 *
 * <p><b>为什么需要这一跳</b>：{@link KfDecisionService} 早就会返回 {@code AI_REPLY}，但全仓没有
 * 消费者 ⇒ 客户在微信里发的消息永远等不到回复。本类补的就是「判定说 AI 可以答」之后的那一步。</p>
 *
 * <p><b>形态</b>：智能客服 = 通道（kf）+ 判定 + 回复。C 端对话内核只在这里被<b>内部调用</b>产文，
 * <b>没有 agent 形态</b>（无 persona 开场白 / 悬浮助手 / 独立聊天面板），本类也不发卡片、
 * 不说「已为您转接」这类它无权兑现的话。</p>
 *
 * <p><b>三条闸门</b>（母单 #9302 裁定 2026-11-28，依据 = 微信客服 48h ≤5 条 / 单条 ≤2048 字节）：</p>
 * <ol>
 *   <li><b>一次入站至多 1 条回复</b>：本类对一条客户消息只调一次
 *       {@link KfSendService#enqueueReply} —— 中间过程（「正在查询…」）由内核侧丢弃，
 *       这里再按话术兜一层；</li>
 *   <li><b>写动作不外包给通道</b>：内核只产文本，卡片/确认/落单不在本通道做；需要写动作的诉求
 *       由 {@link KfDecisionService} 升级为转人工；</li>
 *   <li><b>数值只能来自工具</b>：本轮 0 次工具调用却报出金额/价格 ⇒ 视为编造 ⇒ 转人工。</li>
 * </ol>
 *
 * <p><b>fail-closed（安全底线）</b>：生成失败 / 超时 / 空正文 / 不可投递（中间过程话术、过短、
 * 含 AI 无权承诺的话术、无工具支撑的数值）⇒ <b>不写 outbox</b> + 转人工。绝不把半句话、空话或
 * 假承诺发给客户。</p>
 *
 * <p><b>护栏一律复用</b>：入队只走 {@link KfSendService}（预算 / 48h 窗口 / 正文长度 / 会话有效），
 * 本类<b>不碰</b> {@code kf_outbox}。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "wechat.kf", name = "enabled", havingValue = "true")
public class KfAiReplyLoop {

    public static final String AI_REPLY = "AI_REPLY";
    public static final String ESCALATE_HUMAN = "ESCALATE_HUMAN";

    /**
     * AI 无权承诺的话术族（与 C 端 prompt 禁令 / {@code capability_denial} 族同口径）：
     * 模型仍可能用自然语言承诺它做不到的事，出现即视为<b>不可投递</b>。
     */
    private static final List<String> FORBIDDEN_PROMISES =
            List.of("已为您转接", "已转接人工", "已通知人工", "已提交转人工");

    /**
     * 中间过程话术（闸门 1）：微信客服一条回复要占 48h/5 条预算里的一格，「正在查询…」这类
     * 中间气泡既烧预算又更差 ⇒ 出现即视为不可投递（正常路径由内核侧只留最终文本）。
     */
    private static final List<String> INTERMEDIATE_PROCESS_PHRASES =
            List.of("正在查询", "正在为您查", "正在帮您查", "稍等", "请稍候", "我看看", "马上为您查");

    /** 金额/价格的形态（闸门 3）：0 次工具调用却出现 ⇒ 视为模型自己编的。 */
    private static final Pattern PRICE_LIKE =
            Pattern.compile("\\d[\\d.,]*\\s*(元|块|万元)|[¥￥]\\s*\\d");

    /**
     * 「低置信」的<b>确定性代理</b>：模型自报的置信度在生成侧不可得（内核只回 final_answer，
     * 本包不引入 LLM 判据），所以只拦「短到没有信息量」的半成品（如「。」），短于此长度即不可投递。
     */
    private static final int MIN_VISIBLE_CHARS = 2;

    private final KfDecisionService decisionService;
    private final KfReplyClient replyClient;
    private final KfSendService sendService;
    private final KfTransferService transferService;

    /** 一跳的结果（可解释；落日志，不落库）。 */
    public record Outcome(String decision, boolean replied, String reason) {
    }

    /**
     * 处理一条<b>已落库</b>的客户消息。
     *
     * @param state 会话当前段状态（来自 {@code kf_session_remote.state}）
     */
    public Outcome onCustomerMessage(Long tenantId, String sessionId, int state, String text) {
        KfDecisionService.Decision decision = decisionService.decide(tenantId, sessionId, state, text);
        if (!AI_REPLY.equals(decision.decision())) {
            if (ESCALATE_HUMAN.equals(decision.decision())) {
                escalate(tenantId, sessionId, decision.reason());
            }
            return new Outcome(decision.decision(), false, decision.reason());
        }

        Optional<KfReplyClient.Generated> generated = replyClient.generate(tenantId, sessionId, text);
        if (generated.isEmpty() || !deliverable(generated.get())) {
            // 生成失败 / 超时 / 空正文 / 不可投递 ⇒ 转人工；绝不发半成品
            escalate(tenantId, sessionId, "AI 回复不可投递（生成失败/空文本/中间过程/无权承诺/无工具支撑的数值）");
            return new Outcome(ESCALATE_HUMAN, false, "AI 回复不可投递，转人工");
        }

        try {
            // 闸门 1：一次入站**只入队这一条**（中间过程不落 outbox）
            sendService.enqueueReply(tenantId, sessionId, generated.get().text());
        } catch (RuntimeException e) {
            // 预算耗尽 / 会话已结束 / 正文超限等既有护栏拒绝 ⇒ 不绕开它，转人工兜底
            escalate(tenantId, sessionId, "回复入队被护栏拒绝：" + e.getClass().getSimpleName());
            return new Outcome(ESCALATE_HUMAN, false, "入队失败，转人工");
        }
        log.info("[kf-reply] AI 回复已入队 session={} toolCalls={} reason={}",
                sessionId, generated.get().toolCalls(), decision.reason());
        return new Outcome(AI_REPLY, true, decision.reason());
    }

    /** 可投递判定：非空白、有信息量、不含中间过程 / 无权承诺话术、数值有工具支撑。 */
    static boolean deliverable(KfReplyClient.Generated generated) {
        if (generated == null || generated.text() == null || generated.text().isBlank()) {
            return false;
        }
        String reply = generated.text().strip();
        if (reply.length() < MIN_VISIBLE_CHARS) {
            return false;
        }
        if (FORBIDDEN_PROMISES.stream().anyMatch(reply::contains)) {
            return false;
        }
        if (INTERMEDIATE_PROCESS_PHRASES.stream().anyMatch(reply::contains)) {
            return false;
        }
        // 闸门 3：没有任何工具调用却报出金额 ⇒ 模型编的数，不能发给客户
        return !(generated.toolCalls() == 0 && PRICE_LIKE.matcher(reply).find());
    }

    /**
     * 转人工（best-effort）：失败<b>只记日志</b> —— 客户消息已落库、同步轮必须继续推进游标，
     * 不能让企微接口异常把整轮 sync 打死（同 {@code KfSyncWorker} 的「消息优先」口径）。
     */
    private void escalate(Long tenantId, String sessionId, String reason) {
        try {
            transferService.transferToHuman(tenantId, sessionId, reason);
            log.info("[kf-reply] 转人工 session={} reason={}", sessionId, reason);
        } catch (RuntimeException e) {
            log.warn("[kf-reply] 转人工失败（未发送任何回复）session={} reason={} err={}",
                    sessionId, reason, e.getMessage());
        }
    }
}
