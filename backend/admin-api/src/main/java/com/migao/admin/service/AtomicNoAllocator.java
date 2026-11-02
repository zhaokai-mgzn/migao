package com.migao.admin.service;

import lombok.extern.slf4j.Slf4j;

import java.util.function.IntFunction;
import java.util.function.Predicate;

/**
 * 业务单号「取号 + 占号」的**唯一**骨架（issue #6266 入库 / #8490 出库）：有界换候选重试。
 *
 * <h3>为什么抽出来（只修一处 = 没修）</h3>
 * <p>{@code #6266}（入库单号）与 {@code #8490}（出库单号）是**同一个病**：把「判单号是否被占」与
 * 「占用它」分在两条语句里（先 {@code exists(..)} 判假 ⇒ 返回候选 ⇒ <b>之后</b>才 {@code insert(..)}）。
 * 窗口在多实例 / 重启下可被利用（两边的进程内计数器从同一位置起步 ⇒ 同一候选 ⇒ 两边 {@code exists}
 * 都为假）⇒ 后到者撞唯一索引。修法只有一种：**在一条语句里占号**（{@code INSERT … ON CONFLICT … DO NOTHING}），
 * 按受影响行数 1/0 判号归谁，落败方换候选重来（有界），耗尽显式 409、<b>不静默重号</b>。</p>
 *
 * <p>把「重试骨架」放一处，是为了让**下一个人**加第三种单据号时不必再抄一遍循环 —— 抄一遍就多一份
 * 各自演化的上限 / 日志 / 耗尽语义（{@code migao-dev-flow} §23 类级固化）。本类**只管**重试与日志：
 * 候选怎么生成（计数器 / 日期 / 测试探针）、号怎么占（哪张表、哪条 SQL）、耗尽抛什么业务码，
 * 全部由调用方给 —— 本类不认任何表名。</p>
 *
 * <h3>为什么不是「捕获 {@code DuplicateKeyException} 再重试」</h3>
 * <p>冲突在本类入口处已经**不是异常**（{@code ON CONFLICT … DO NOTHING} 返回 0 行）：PG 的当前事务
 * <b>不会</b>进入 aborted 状态 ⇒ 可以在**同一个事务**里安全换号。若靠捕获异常，PG 已把事务标记为坏，
 * 只有 {@code REQUIRES_NEW} 救得回来，而那会把单据（及其明细）提前提交 ⇒ 后续行失败会留下半张单。</p>
 */
@Slf4j
final class AtomicNoAllocator {

    private AtomicNoAllocator() {
    }

    /**
     * 有界换候选：逐个尝试「生成候选 → 一条语句占号」，{@code claim} 返回 {@code true} 即停。
     *
     * @param attempts   换候选上限（调用方给，如 {@code INBOUND_NO_ATTEMPTS} / {@code OUTBOUND_NO_ATTEMPTS}）
     * @param label      日志里的面（「入库单号」/「出库单号」）—— 只用于排障，**不参与**判定
     * @param tenantId   日志里的租户（可为 {@code null}）—— 同上，不参与判定
     * @param candidateAt 第 {@code n} 次（从 0 起）该用哪个候选号；测试探针就挂在这一层
     * @param claim      用**一条语句**占号：{@code true} = 号归我（已落库）、{@code false} = 刚被抢走
     * @return 占到的号；{@code null} = {@code attempts} 次全被抢走 ⇒ 调用方转成显式 409（本类不猜业务码）
     */
    static String take(int attempts, String label, Long tenantId,
                       IntFunction<String> candidateAt, Predicate<String> claim) {
        for (int attempt = 0; attempt < attempts; attempt++) {
            String candidate = candidateAt.apply(attempt);
            if (claim.test(candidate)) {
                return candidate;
            }
            log.warn("{}刚被占用，换候选重来: tenant={}, candidate={}", label, tenantId, candidate);
        }
        return null;
    }
}
