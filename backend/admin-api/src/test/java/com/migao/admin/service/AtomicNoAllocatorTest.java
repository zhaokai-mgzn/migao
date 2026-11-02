// case_ids: OR-076
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 取号重试骨架（issue #8490；与 #6266 的入库建单取号**共用同一份实现**）。
 *
 * <p>本类只测骨架的**判定语义**（什么时候停、什么时候返回 null、异常怎么走）：真库那半
 * （唯一索引在插入那一刻的裁决、未提交行对并发事务的不可见）由
 * {@code OutboundNoTakeRaceRealDbTest} / {@code InboundNoTakeRaceRealDbTest} 承担 —— 两者互补，不重复。</p>
 */
@DisplayName("取号重试骨架 AtomicNoAllocator（#8490 / 与 #6266 共用）")
class AtomicNoAllocatorTest {

    @Test
    @DisplayName("号归我就停：第一次占号成功 ⇒ 只占一次、返回第一个候选")
    void stopsAtTheFirstClaimedCandidate() {
        AtomicInteger claims = new AtomicInteger();

        String taken = AtomicNoAllocator.take(20, "出库单号", 1L,
                attempt -> "CK-DEMO-" + attempt,
                candidate -> {
                    claims.incrementAndGet();
                    return true;
                });

        assertThat(taken).as("返回值 = 抢到的候选").isEqualTo("CK-DEMO-0");
        assertThat(claims).as("成功后不许再试（多试一次就是多一次无谓的 INSERT）").hasValue(1);
    }

    @Test
    @DisplayName("被抢就换候选：前两次 0 行 ⇒ 第三次成功，且每次候选都不同")
    void retriesWithAFreshCandidateUntilClaimed() {
        List<String> tried = new ArrayList<>();

        String taken = AtomicNoAllocator.take(20, "出库单号", 1L,
                attempt -> "CK-DEMO-" + attempt,
                candidate -> {
                    tried.add(candidate);
                    return tried.size() == 3;
                });

        assertThat(taken).isEqualTo("CK-DEMO-2");
        assertThat(tried).as("落败者必须换候选（拿同一个号重试 = 白试）")
                .containsExactly("CK-DEMO-0", "CK-DEMO-1", "CK-DEMO-2");
    }

    @Test
    @DisplayName("预算耗尽 ⇒ 返回 null（业务码/文案由调用方给，本类不猜 409），且恰试 attempts 次")
    void returnsNullWhenTheBudgetIsExhausted() {
        AtomicInteger claims = new AtomicInteger();

        String taken = AtomicNoAllocator.take(3, "出库单号", 1L,
                attempt -> "CK-DEMO-" + attempt,
                candidate -> {
                    claims.incrementAndGet();
                    return false;
                });

        assertThat(taken).as("耗尽 = null（调用方转成显式 409，不静默重号）").isNull();
        assertThat(claims).as("上限是硬上界").hasValue(3);
    }

    @Test
    @DisplayName("上限 0 ⇒ 一次都不试（不许「至少试一次」的暗默认）")
    void zeroAttemptsTriesNothing() {
        AtomicInteger claims = new AtomicInteger();

        String taken = AtomicNoAllocator.take(0, "出库单号", 1L,
                attempt -> "CK-DEMO-" + attempt,
                candidate -> {
                    claims.incrementAndGet();
                    return true;
                });

        assertThat(taken).isNull();
        assertThat(claims).hasValue(0);
    }

    @Test
    @DisplayName("占号语句抛异常 ⇒ 原样冒泡（不吞、不改写、不重试成「看起来成功」）")
    void claimFailurePropagates() {
        assertThatThrownBy(() -> AtomicNoAllocator.take(20, "出库单号", 1L,
                attempt -> "CK-DEMO-" + attempt,
                candidate -> {
                    throw new IllegalStateException("连接断了");
                }))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("连接断了");
    }
}
