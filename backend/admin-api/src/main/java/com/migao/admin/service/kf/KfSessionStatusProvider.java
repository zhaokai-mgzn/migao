package com.migao.admin.service.kf;

import com.migao.admin.dto.AgentSessionListResponse;
import com.migao.admin.entity.KfSessionRemote;
import com.migao.admin.mapper.KfOutboxMapper;
import com.migao.admin.mapper.KfSendBudgetMapper;
import com.migao.admin.mapper.KfSessionRemoteMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 工作台人工会话列表的微信客服状态装饰（issue #9198 / 母单 #9194 子项 2）。
 *
 * <p>补三项坐席可观察的状态：渠道标识（{@code wechat_kf}）、最新一条发送状态
 * （{@code kf_outbox.status}：pending/sending/accepted/failed/unknown）、48h/5 条预算余量。</p>
 *
 * <p><b>只装饰真有 {@code kf_session_remote} 镜像行的会话</b> —— 给普通人工会话伪造渠道标识
 * 比缺失更糟：坐席会以为客户在微信里，于是绕过站内消息直接等回复。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "wechat.kf", name = "enabled", havingValue = "true")
public class KfSessionStatusProvider {

    /** 渠道标识（与前端 `wechat_kf` 常量对齐）。 */
    public static final String CHANNEL = "wechat_kf";
    /** 微信客服发送预算：48h 内最多 5 条（与 kf_send_budget 的 CHECK 约束同源）。 */
    public static final int BUDGET_LIMIT = 5;
    /** 无 outbox 记录（AI 尚未发过）时的保守状态。 */
    public static final String STATUS_UNKNOWN = "unknown";

    private final KfSessionRemoteMapper remoteMapper;
    private final KfOutboxMapper outboxMapper;
    private final KfSendBudgetMapper budgetMapper;

    /** 就地补给列表项；非微信客服会话的字段**逐字不变**。 */
    public void decorate(List<AgentSessionListResponse> rows) {
        if (rows == null || rows.isEmpty()) {
            return;
        }
        List<String> aiSessionIds = rows.stream()
                .map(AgentSessionListResponse::getAiSessionId)
                .filter(StringUtils::hasText)
                .distinct()
                .collect(Collectors.toList());
        if (aiSessionIds.isEmpty()) {
            return;
        }
        List<KfSessionRemote> remotes = remoteMapper.selectBySessionIds(aiSessionIds);
        if (remotes == null || remotes.isEmpty()) {
            return;
        }
        Set<String> kfSessionIds = new HashSet<>();
        for (KfSessionRemote remote : remotes) {
            if (remote != null && remote.getSessionId() != null) {
                kfSessionIds.add(remote.getSessionId());
            }
        }
        for (AgentSessionListResponse row : rows) {
            String aiSessionId = row.getAiSessionId();
            if (aiSessionId == null || !kfSessionIds.contains(aiSessionId)) {
                continue;
            }
            row.setChannel(CHANNEL);
            String status = outboxMapper.selectLatestStatus(aiSessionId);
            row.setSendStatus(StringUtils.hasText(status) ? status : STATUS_UNKNOWN);
            Integer used = budgetMapper.selectUsedInWindow(aiSessionId);
            row.setBudgetUsed(used == null ? 0 : used);
            row.setBudgetLimit(BUDGET_LIMIT);
        }
    }
}
