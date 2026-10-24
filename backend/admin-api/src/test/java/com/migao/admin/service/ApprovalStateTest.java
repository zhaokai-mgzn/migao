// case_ids: APP-001
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 审批状态机（issue #7374，P1-2 段 1）—— 四态流转的**逐格**判据。
 *
 * <p>流转判错不会报错，只会「少收一道闸」：已驳回的还能被通过、用过的超授信还能再用一次。
 * 这两种错在数据上都长得像正常，所以必须逐格钉死。</p>
 */
@DisplayName("审批状态机：只有待审能裁决/撤回；只有已通过且未用能消费")
class ApprovalStateTest {

    @Test
    @DisplayName("只有 pending 能裁决（已通过/已驳回/已撤回都不能再改）")
    void onlyPendingCanBeDecided() {
        assertThat(ApprovalState.canDecide(ApprovalState.PENDING)).isTrue();
        assertThat(ApprovalState.canDecide(ApprovalState.APPROVED)).as("已通过不能再裁决（改判要走新申请）").isFalse();
        assertThat(ApprovalState.canDecide(ApprovalState.REJECTED)).isFalse();
        assertThat(ApprovalState.canDecide(ApprovalState.WITHDRAWN)).isFalse();
    }

    @Test
    @DisplayName("只有 pending 能撤回（已裁决的不能「撤回」—— 那会绕过裁决留痕）")
    void onlyPendingCanBeWithdrawn() {
        assertThat(ApprovalState.canWithdraw(ApprovalState.PENDING)).isTrue();
        assertThat(ApprovalState.canWithdraw(ApprovalState.APPROVED)).isFalse();
        assertThat(ApprovalState.canWithdraw(ApprovalState.REJECTED)).isFalse();
    }

    @Test
    @DisplayName("🔴 只有「已通过 + 未用掉」能消费（批一次用一次）")
    void onlyApprovedAndUnconsumedCanBeConsumed() {
        assertThat(ApprovalState.canConsume(ApprovalState.APPROVED, false)).isTrue();
        assertThat(ApprovalState.canConsume(ApprovalState.APPROVED, true)).as("用过的不能再放行第二单").isFalse();
        assertThat(ApprovalState.canConsume(ApprovalState.PENDING, false)).isFalse();
        assertThat(ApprovalState.canConsume(ApprovalState.REJECTED, false)).isFalse();
        assertThat(ApprovalState.canConsume(ApprovalState.WITHDRAWN, false)).isFalse();
    }

    @Test
    @DisplayName("初始状态显式是 pending（不靠列的 DEFAULT 隐式决定）")
    void initialStatusIsExplicit() {
        assertThat(ApprovalState.initialStatus()).isEqualTo(ApprovalState.PENDING);
    }

    @Test
    @DisplayName("四态常量是稳定标识（落库值与判据都按它）")
    void statusCodesAreStable() {
        assertThat(ApprovalState.PENDING).isEqualTo("pending");
        assertThat(ApprovalState.APPROVED).isEqualTo("approved");
        assertThat(ApprovalState.REJECTED).isEqualTo("rejected");
        assertThat(ApprovalState.WITHDRAWN).isEqualTo("withdrawn");
    }
}
