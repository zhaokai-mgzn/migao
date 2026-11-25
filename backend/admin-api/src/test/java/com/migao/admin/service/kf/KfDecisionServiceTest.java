// case_ids: KF-020
package com.migao.admin.service.kf;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class KfDecisionServiceTest {

    private final KfDecisionService service = new KfDecisionService();

    @Test
    @DisplayName("非 AI 态 ⇒ SILENT；要人工/高风险 ⇒ ESCALATE_HUMAN；默认 AI_REPLY")
    void decisions() {
        assertThat(service.decide(2, "你好").decision()).isEqualTo("SILENT");
        assertThat(service.decide(3, "你好").decision()).isEqualTo("SILENT");
        assertThat(service.decide(0, "我要转人工").decision()).isEqualTo("ESCALATE_HUMAN");
        assertThat(service.decide(1, "我要投诉退款").decision()).isEqualTo("ESCALATE_HUMAN");
        assertThat(service.decide(0, "这款多少钱").decision()).isEqualTo("AI_REPLY");
    }
}
