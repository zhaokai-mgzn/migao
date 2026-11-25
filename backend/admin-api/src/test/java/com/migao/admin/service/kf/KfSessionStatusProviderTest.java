// case_ids: KF-026
package com.migao.admin.service.kf;

import com.migao.admin.dto.AgentSessionListResponse;
import com.migao.admin.entity.KfSessionRemote;
import com.migao.admin.mapper.KfOutboxMapper;
import com.migao.admin.mapper.KfSendBudgetMapper;
import com.migao.admin.mapper.KfSessionRemoteMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 工作台会话列表的微信客服状态装饰（issue #9198 / 母单 #9194 子项 2）。
 *
 * <p>口径：**只有真有 kf_session_remote 镜像行的会话**才带渠道标识 ——
 * 普通人工会话的字段必须逐字不变（伪造渠道标识比缺失更糟：坐席会以为客户在微信里）。</p>
 */
class KfSessionStatusProviderTest {

    private final KfSessionRemoteMapper remoteMapper = mock(KfSessionRemoteMapper.class);
    private final KfOutboxMapper outboxMapper = mock(KfOutboxMapper.class);
    private final KfSendBudgetMapper budgetMapper = mock(KfSendBudgetMapper.class);
    private final KfSessionStatusProvider provider =
            new KfSessionStatusProvider(remoteMapper, outboxMapper, budgetMapper);

    private static AgentSessionListResponse row(String id, String aiSessionId) {
        return AgentSessionListResponse.builder().id(id).aiSessionId(aiSessionId).build();
    }

    private static KfSessionRemote remote(String sessionId, int state) {
        KfSessionRemote r = new KfSessionRemote();
        r.setSessionId(sessionId);
        r.setState(state);
        return r;
    }

    @Test
    @DisplayName("微信客服会话 ⇒ 渠道标识 + 最新发送状态 + 预算；普通会话字段不变")
    void decoratesOnlyKfSessions() {
        AgentSessionListResponse kf = row("as-1", "s-1");
        AgentSessionListResponse plain = row("as-2", "s-2");
        AgentSessionListResponse noAi = row("as-3", null);

        when(remoteMapper.selectBySessionIds(anyList())).thenReturn(List.of(remote("s-1", 2)));
        when(outboxMapper.selectLatestStatus("s-1")).thenReturn("accepted");
        when(budgetMapper.selectUsedInWindow("s-1")).thenReturn(2);

        provider.decorate(List.of(kf, plain, noAi));

        assertThat(kf.getChannel()).isEqualTo("wechat_kf");
        assertThat(kf.getSendStatus()).isEqualTo("accepted");
        assertThat(kf.getBudgetUsed()).isEqualTo(2);
        assertThat(kf.getBudgetLimit()).isEqualTo(5);

        assertThat(plain.getChannel()).isNull();
        assertThat(plain.getSendStatus()).isNull();
        assertThat(plain.getBudgetUsed()).isNull();
        // 没有 aiSessionId 的行根本不该去查（省查询，也避免误命中别人的会话）
        assertThat(noAi.getChannel()).isNull();
        verify(outboxMapper, never()).selectLatestStatus("s-2");
    }

    @Test
    @DisplayName("预算行缺失（新会话）⇒ 已用 0；outbox 无记录 ⇒ unknown")
    void missingBudgetAndOutboxHaveDefaults() {
        AgentSessionListResponse kf = row("as-1", "s-1");
        when(remoteMapper.selectBySessionIds(anyList())).thenReturn(List.of(remote("s-1", 0)));
        when(outboxMapper.selectLatestStatus("s-1")).thenReturn(null);
        when(budgetMapper.selectUsedInWindow("s-1")).thenReturn(null);

        provider.decorate(List.of(kf));

        assertThat(kf.getChannel()).isEqualTo("wechat_kf");
        assertThat(kf.getSendStatus()).isEqualTo("unknown");
        assertThat(kf.getBudgetUsed()).isZero();
        assertThat(kf.getBudgetLimit()).isEqualTo(5);
    }

    @Test
    @DisplayName("空列表 / 全无 aiSessionId ⇒ 零查询、不抛错")
    void emptyInputsAreNoOps() {
        provider.decorate(List.of());
        provider.decorate(List.of(row("as-3", null)));
        verify(remoteMapper, never()).selectBySessionIds(anyList());
    }
}
