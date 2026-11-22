package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.RequestId;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.time.BusinessClock;
import lombok.extern.slf4j.Slf4j;

import java.time.format.DateTimeFormatter;
import java.util.UUID;

/**
 * 加工单号「取号 + 占号」（集群 P0-5，issue #9021）：与
 * {@code InboundOrderService#insertWithFreshInboundNo} / {@code OutboundOrderService#insertWithFreshOutboundNo}
 * <b>同一范式</b> —— 起点按库内当日最大号、一条 {@code INSERT … ON CONFLICT DO NOTHING} 原子占号、
 * 0 行换候选重来（有界）。
 *
 * <h2>为什么单独成类（不改回 {@code ProcessingOrderService} 里）</h2>
 * {@code ProcessingOrderService} 已在体量棘轮的**冻结清单**里（{@code loc_freeze_ledger.json}：
 * 只许变短、再长一行就判红）⇒ 新增逻辑不能再往里堆；取号与「单号/活跃单两种唯一冲突怎么分诊」
 * 本身也是自洽的一小块，放这里可被同类单据复用。
 *
 * <h2>病根（改前）</h2>
 * 进程内 {@code AtomicInteger}（{@code ThreadLocalRandom} 随机起点）先发号、之后才 {@code insert}：
 * 多实例 / 重启从同一位置起步 ⇒ 同一候选被两个事务取到 ⇒ 撞 {@code uk_processing_orders_no} 抛
 * {@code DuplicateKeyException}，而调用方把它一律翻成「加工单已生成」——<b>单子没落库却报成功</b>
 * （静默漏单）。
 *
 * <h2>为什么不能「捕获 {@code DuplicateKeyException} 再重试」</h2>
 * 异常会让 PG 把当前事务标记为 aborted ⇒ 同事务内的后续语句（连「查一下是不是已有单」都算）
 * 全部报错，只能开新事务救，而那会把半张单提前提交。{@code ON CONFLICT DO NOTHING} 在冲突时
 * 不报错、事务保持健康。
 *
 * <h2>0 行的两种含义必须分开</h2>
 * 本表还有 {@code uk_processing_orders_active}（同一订单至多一张活跃单）。无目标
 * {@code DO NOTHING} 把两种冲突都变成 0 行；0 行时先回查活跃单：查到 ⇒ 才是真的「已生成」
 * （带单号）；查不到 ⇒ 是取号冲突，换号重试。重试耗尽 ⇒ 显式 409 + requestId。
 */
@Slf4j
final class ProcessingOrderNoAllocator {

    /**
     * 取号重试上限：连续 {@value} 次候选号全被抢 ⇒ 显式 409。
     *
     * <p>取 20 是**同族口径**（{@code INBOUND_NO_ATTEMPTS} / {@code OUTBOUND_NO_ATTEMPTS} /
     * {@code BATCH_NO_ATTEMPTS} 均为 20），远超「同一天重启 20 次且每次都恰好撞上」的实际情况。
     * <b>已知代价</b>（如实登记）：当天已用号 ≥ 20 且重启后的第一批建单恰好全部撞上时会被显式拒绝
     * （回 409、零副作用：订单联动在 {@code ProcessingOrderService#commit} 的失败回退里已退回
     * confirmed），而不是静默重号。</p>
     */
    static final int ATTEMPTS = 20;

    private static final DateTimeFormatter DATE_FMT = DateTimeFormatter.ofPattern("yyyyMMdd");

    /**
     * <b>测试探针</b>（生产恒为 {@code null}）：把**第一次**取号钉成给定候选。
     *
     * <p><b>为什么需要它</b>：本缺陷的可达形态是「两个实例 / 重启后的新进程从同一位置起步 ⇒ 拿到
     * <b>同一个</b>候选」，而判据要稳定复现「第一条候选被抢 ⇒ 换号重来」必须能钉住候选；
     * 否则只能靠碰运气撞号，判据会退化成 flake（{@code migao-dev-flow} §28.1：修前必须红）。
     * 语义与 {@code InboundOrderService#setInboundNoProbeFirstCandidateForTest} /
     * {@code OutboundOrderService#setOutboundNoProbeFirstCandidateForTest} 逐字同款，
     * 且只在包内可见。</p>
     */
    static void setProbeFirstCandidateForTest(String candidate) {
        PROBE_FIRST_CANDIDATE = candidate;
    }

    /** 首次取号的测试候选（{@code null} = 不钉）；见 {@link #setProbeFirstCandidateForTest}。 */
    private static volatile String PROBE_FIRST_CANDIDATE = null;

    private ProcessingOrderNoAllocator() {
    }

    /**
     * 取号 + 落库：受影响行数 {@code 1} = 号归我（单据已落库）、{@code 0} = 号刚被抢走 ⇒ 换候选重来。
     *
     * <p>号段是 4 位十进制（{@code %04d}），超过 9999 回绕到 0 —— 与入库/出库单号的 {@code % 10_000}
     * 同口径；回绕后若又撞上已用号，由 {@link AtomicNoAllocator} 换候选重试。</p>
     */
    static void insertWithFresh(ProcessingOrderMapper mapper, ObjectMapper objectMapper,
                                BusinessClock businessClock, Order order, ProcessingOrder po) {
        // 主键由服务端生成：手写 INSERT 不走 MyBatis-Plus 的 ASSIGN_UUID（与入库/出库同口径）
        po.setId(UUID.randomUUID().toString().replace("-", ""));
        String prefix = "JG-" + businessClock.today().format(DATE_FMT) + "-";
        int start = nextSeq(mapper, prefix);
        String itemsSnapshotJson = snapshotJson(objectMapper, po.getItemsSnapshot());
        String taken = AtomicNoAllocator.take(ATTEMPTS, "加工单号", po.getTenantId(),
                attempt -> attempt == 0 && PROBE_FIRST_CANDIDATE != null
                        ? PROBE_FIRST_CANDIDATE
                        : prefix + String.format("%04d", (start + attempt) % 10_000),
                candidate -> {
                    po.setProcessingOrderNo(candidate);
                    if (mapper.insertIgnoreProcessingNoConflict(po, itemsSnapshotJson) == 1) {
                        return true;
                    }
                    // 0 行：先判「是不是已有活跃单」，只有**确实查到**才敢报「已生成」。
                    ProcessingOrder existing = mapper.selectActiveByOrderId(order.getId(), order.getTenantId());
                    if (existing != null) {
                        throw BusinessException.validationError(
                                "订单 " + order.getOrderNo() + " 加工单已生成（并发操作，单号 "
                                        + existing.getProcessingOrderNo() + "），请刷新后重试");
                    }
                    return false;
                });
        if (taken == null) {
            throw conflict("连续 " + ATTEMPTS + " 次候选号均被占用");
        }
    }

    /**
     * 当天取号起点 = <b>库内当日最大序号 + 1</b>（不是进程内计数器）。
     *
     * <p>起点钉在**库**上（跨租户全局，理由见 {@link ProcessingOrderMapper#selectMaxProcessingOrderNo}），
     * 冲突仍由 INSERT 的原子占号裁决。存量脏号（非数字后缀）⇒ 从 1 起试；真撞了就换候选，
     * 不会静默重号。</p>
     */
    private static int nextSeq(ProcessingOrderMapper mapper, String prefix) {
        String max = mapper.selectMaxProcessingOrderNo(prefix);
        if (max == null || max.length() <= prefix.length()) {
            return 1;
        }
        try {
            return (Integer.parseInt(max.substring(prefix.length())) + 1) % 10_000;
        } catch (NumberFormatException e) {
            return 1;
        }
    }

    /** 取号冲突的**可行动错误**：显式 409 + requestId（可凭它在日志里反查），**不得**复用「已生成」。 */
    private static BusinessException conflict(String detail) {
        String requestId = RequestId.current();
        log.error("加工单号取号冲突: detail={}, requestId={}", detail, requestId);
        return new BusinessException("PROCESSING_ORDER_NO_CONFLICT",
                "加工单号生成冲突，请重试（requestId=" + requestId + "）", 409);
    }

    /** 快照 → JSON 文本（手写 INSERT 的 JSONB 参数；见 mapper 的 {@code CAST(… AS jsonb)}）。 */
    private static String snapshotJson(ObjectMapper objectMapper, Object snapshot) {
        try {
            return objectMapper.writeValueAsString(snapshot);
        } catch (com.fasterxml.jackson.core.JsonProcessingException e) {
            throw new IllegalStateException("加工单快照序列化失败（items_snapshot 必须落库）", e);
        }
    }
}
