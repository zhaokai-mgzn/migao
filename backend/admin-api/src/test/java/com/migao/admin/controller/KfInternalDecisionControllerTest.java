// case_ids: KF-022
package com.migao.admin.controller;

import com.migao.admin.service.kf.KfDecisionService;
import com.migao.admin.service.kf.KfTransferService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class KfInternalDecisionControllerTest {

    @Test
    @DisplayName("decide/transfer 返回结构化结果")
    void endpoints() {
        KfDecisionService decision = mock(KfDecisionService.class);
        KfTransferService transfer = mock(KfTransferService.class);
        KfInternalDecisionController controller = new KfInternalDecisionController(decision, transfer);

        when(decision.decide(0, "转人工")).thenReturn(new KfDecisionService.Decision("ESCALATE_HUMAN", "明确要人工"));
        assertThat(controller.decide(new KfInternalDecisionController.DecideRequest(1L, "s1", 0, "转人工"))
                .getBody()).containsEntry("decision", "ESCALATE_HUMAN");

        when(transfer.transferToHuman(1L, "s1", "r")).thenReturn("a1");
        assertThat(controller.transfer(new KfInternalDecisionController.TransferRequest(1L, "s1", "r"))
                .getBody()).containsEntry("agent_session_id", "a1");
    }
}
