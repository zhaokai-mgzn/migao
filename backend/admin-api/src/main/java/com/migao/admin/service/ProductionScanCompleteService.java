package com.migao.admin.service;

import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.worker.WorkerIdentity;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.util.Map;

/**
 * 扫码报工主闭环（切片 ②，issue #4698；设计 {@code docs/design/set-code-and-scan-loop.md} §4 / §5）。
 *
 * <p><b>A 模式</b>（用户裁定②-3：「做完扫一次 = 完工」，零额外交互）：工人扫一次码 ⇒ 本类</p>
 * <ol>
 *   <li><b>幂等占位</b>（外层，{@code X-Client-Request-Id}）—— 与 {@link ProductionService#report}
 *       逐字同款：占位 → 执行 → 落快照；失败 ⇒ 释放占位（不把键永久占死）；</li>
 *   <li><b>解析 + 推断</b>（{@link ProductionScanService#resolve}，切片 ① 的**同一份**实现 ——
 *       本类不重写解析/推断）：token ⇒（套，部位）+ 下一道待做工序；</li>
 *   <li>🔴 <b>未确定工序 ⇒ 拒绝记账</b>（切片 ① 类注释的约定 + 设计 §3.3 / §5.3⑤）：
 *       推断零道 / 多道 / 旧码降级（需选套选部位）⇒ 抛 {@code NO_PENDING_OPERATION} /
 *       {@code SET_ALREADY_COMPLETED} / {@code SCAN_NEEDS_SELECTION}，<b>一个字节都不写</b>
 *       {@code production_work_logs}（红证见 {@code ProductionScanCompleteServiceTest}）；</li>
 *   <li><b>一次事务</b>（{@link ProductionService#applyScanComplete}，跨 bean 调用 ⇒ 代理生效）：
 *       报工明细 + CAS（{@code done_qty}/{@code status}）+ {@code done_at} + 必完全绿 ⇒ 加工单
 *       {@code completed}，要么全成要么全不成；</li>
 *   <li>回执带「本道完成 + 本套进度 + <b>下一道是什么</b>」⇒ 工人接着扫下一个码。</li>
 * </ol>
 *
 * <p><b>为什么是新端点（而不是复用既有 {@code .../report}）</b>：既有端点的 URL 里**强制**给了
 * {@code orderId} + {@code operationId} ⇒「哪道工序」是**客户端**决定的；A 模式把这件事交给系统
 * （推断 + 一键改），若复用就得让前端先解析再报工（两次请求），而「未确定」这个态在客户端无处安放
 * —— 设计 §4.2 方案 A 已定：**新增**入口、**不改** {@code report}（含不加 {@code @Transactional}）。
 * 路径走 {@code /api/worker/**}：工人身份由服务端从 session 解（issue #4733），且工人到不了
 * {@code /api/admin/**}。</p>
 *
 * <p><b>与设计的偏离（照实登记）</b>：</p>
 * <ul>
 *   <li>数量默认取<b>剩余应做</b>（应做 − 已报），不是设计 §4.1 字面的「应做数量」：既有
 *       {@code assertWithinPlannedQty} 对超上限是**拒绝不 clamp**（issue #4116 §5-3 的刻意口径），
 *       照字面默认「应做」会让「报了 6/11 米」的续报**一提交就 422**（与切片 ① 登记的「部分报工
 *       仍可继续」直接冲突）。首次报工两者相同（剩余 = 应做）。</li>
 *   <li>回执的「下一道」是**尽力而为**（{@code next_operation}）：报工已提交后再解析一次；
 *       解析抛错（如脏数据 {@code seq} 重复）只记 warn 并给 {@code null}，**绝不**让已提交的报工
 *       变成失败响应 —— 那会让调用方释放幂等键重试，把一次报工记两遍（静默重复计件）。</li>
 * </ul>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProductionScanCompleteService {

    /**
     * 幂等端点标识（诊断用；与 Controller 路径逐字一致 —— 改路径必须同改此处）。
     * 与 {@link ProductionService#ENDPOINT_REPORT} 是**两个**端点 ⇒ 同键跨端点复用会在
     * {@code client_request_keys.endpoint} 留证。
     */
    public static final String ENDPOINT_SCAN_COMPLETE = "POST /api/worker/production/scan/complete";

    private final ProductionScanService scanService;
    private final ProductionService productionService;
    private final ClientRequestIdService clientRequestIdService;

    /**
     * 扫码完成（A 模式闭环的唯一写入口）。
     *
     * @param body             {@code token}（必填）+ 可选 {@code operation_id}（一键改）、
     *                         {@code qty} / {@code qualified_qty} / {@code work_type}
     * @param tenantId         当前租户
     * @param clientRequestId  幂等键（{@code X-Client-Request-Id}）；缺失/空白 ⇒ 原路径逐字不变
     * @param identity         🔴 由**服务端**从工人 session 解出（body 里的 worker_id/worker_name
     *                         一个字节都不读 —— 那是工资凭证的根，见 issue #4733）
     * @return 报工结果（{@link ProductionService#applyScanComplete} 的键）+ 套号/部位/本套进度/下一道
     */
    public Map<String, Object> complete(Map<String, Object> body, Long tenantId,
                                        String clientRequestId, WorkerIdentity identity) {
        // ① 先占位：同键重复请求**不执行**（不落明细、不累加、不推进完工判定）
        if (!clientRequestIdService.claim(tenantId, clientRequestId, ENDPOINT_SCAN_COMPLETE)) {
            Map<String, Object> replayed = productionService.replayFirstResult(tenantId, clientRequestId);
            log.info("[扫码完成幂等] 同键重复请求：跳过执行，回放首次结果 tenantId={}", tenantId);
            return replayed;
        }
        try {
            Map<String, Object> result = doComplete(body, tenantId, identity);
            // 落结果快照（同键后续请求回放它）。放在 try 之外：快照写失败时**不得**释放占位
            // —— 报工已经落库，宁可让同键请求 fail-closed 报错，也不能退化成「再报一次」
            clientRequestIdService.complete(tenantId, clientRequestId, result);
            return result;
        } catch (RuntimeException e) {
            // 执行失败（校验/推断不确定/超上限/并发冲突/DB 错误）⇒ 释放占位，同 report 的取舍
            clientRequestIdService.discard(tenantId, clientRequestId);
            throw e;
        }
    }

    /** 解析 → 工序确定性校验 → 事务记账 → 回执（占位成功后才执行）。 */
    private Map<String, Object> doComplete(Map<String, Object> body, Long tenantId, WorkerIdentity identity) {
        String token = ProductionService.str(body == null ? null : body.get("token"));
        if (!StringUtils.hasText(token)) {
            throw BusinessException.validationError("扫码内容不能为空（token 缺失）");
        }
        String pickedOperationId = ProductionService.str(body == null ? null : body.get("operation_id"));

        // 解析 + 推断 = 切片 ① 的**同一份**实现（新码优先，未命中回落既有四形态）
        Map<String, Object> scan = scanService.resolve(token, pickedOperationId, tenantId);

        // 🔴 旧码降级形态（设计 §2.6）：只到加工单级 ⇒ 必须由工人选套 + 选部位。
        // **绝不默认取第 1 套** —— 默认 = 把进度/计件静默记到错的套上（正是要治的病）。
        // 本切片不提供选择交互（切片 ⑤）⇒ fail-closed 拒绝，并指路既有逐道报工入口。
        if (ProductionScanService.GRANULARITY_ORDER.equals(scan.get("granularity"))) {
            throw new BusinessException("SCAN_NEEDS_SELECTION",
                    "这是加工单级旧码（不含套号/部位），无法确定本次做的是哪一樘窗的哪个部位 ⇒ 拒绝记账",
                    422,
                    "请在工序列表里按部位逐道报工（旧码不默认取第 1 套：那会把进度记到错的窗上）；"
                            + "重新打印带套号 + 部位的新任务卡即可恢复一次扫码完工");
        }

        // 🔴 硬约束：工序必须确定（设计 §3.3 / §5.3⑤）。切片 ① 已保证「绝不产出非唯一确定的工序」，
        // 本类是**记账侧**的那一半：operation 为空（无待做工序 / 本套已完成）⇒ 拒绝，不猜、不静默取第一道。
        @SuppressWarnings("unchecked")
        Map<String, Object> operationView = (Map<String, Object>) scan.get("operation");
        if (operationView == null) {
            if (Boolean.TRUE.equals(scan.get("completed"))) {
                throw new BusinessException("SET_ALREADY_COMPLETED",
                        "本套（" + scan.get("set_no") + "）的工序都已完成，没有可报的工序（本次未记账）",
                        409,
                        "请勿重复提交；若实际还有活没干，请先在「生产 → 工序库」补该部位的工序");
            }
            throw new BusinessException("NO_PENDING_OPERATION",
                    "本套（" + scan.get("set_no") + "）的该部位推断不出待做工序 ⇒ 工序未确定，不得记账",
                    422,
                    "请刷新本单工序进度后重试；若确认还有活，请在「生产 → 工序库」补齐该部位的工序"
                            + "（系统不猜工序：计件记到猜的那道会发错工资）");
        }

        String operationId = String.valueOf(operationView.get("operation_id"));
        String orderId = String.valueOf(scan.get("order_id"));
        // 定位（与既有报工**同一份**判据）：订单 → 活跃加工单 → 活跃工序实例（三重校验）
        Order order = productionService.resolveOrder(orderId, tenantId);
        ProcessingOrder po = productionService.requireActiveProcessingOrder(order, tenantId);
        ProcessingPositionOperation op = productionService.requireActiveOperation(po.getId(), operationId, tenantId);

        // 数量：默认 = 剩余应做（首次报工 = 应做数量；见类注释的偏离登记）
        BigDecimal qty = ProductionService.bd(body == null ? null : body.get("qty"), null);
        if (qty == null) {
            qty = plannedRemaining(op);
            if (qty.signum() <= 0) {
                // 读到这里仍是 pending、但数量已满 = 并发/刚被别人报满（CAS 也会拦，这里给更准的话）
                throw new BusinessException("OPERATION_ALREADY_ADVANCED",
                        "工序「" + op.getOperationName() + "」已报满（本次未重复计件）",
                        409,
                        "请下拉刷新本加工单工序进度后再确认是否仍需报工");
            }
        }
        if (qty.signum() <= 0) {
            throw BusinessException.validationError("qty 必须大于 0");
        }
        Object rawQualified = body == null ? null : body.get("qualified_qty");
        BigDecimal qualifiedQty = rawQualified == null ? qty : ProductionService.bd(rawQualified, qty);
        if (qualifiedQty.signum() < 0) {
            throw BusinessException.validationError("qualified_qty 不能为负");
        }
        String workType = ProductionService.str(body == null ? null : body.get("work_type"), "normal");
        if (!ProductionService.WORK_TYPES.contains(workType)) {
            throw BusinessException.validationError("work_type 仅支持 normal/rework/scrap");
        }

        // ② 一次事务（跨 bean 调用 ⇒ @Transactional 代理生效）：明细 + CAS + done_at + 完工判定
        Map<String, Object> result = productionService.applyScanComplete(
                order, po, op, qty, qualifiedQty, workType, identity, tenantId);

        // ③ 一屏闭环回执：本道完成 + 本套（套号/部位/进度）+ 下一道是什么
        result.put("set_no", scan.get("set_no"));
        result.put("position", scan.get("position"));
        result.put("rerouted", Boolean.TRUE.equals(operationView.get("rerouted")));
        enrichNextOperation(result, token, tenantId);
        return result;
    }

    /**
     * 回执里的「下一道」（设计 §4.1 ⑥：工人接着扫下一个码 / 同一部位继续）。
     *
     * <p>🔴 <b>尽力而为</b>：此时报工**已经提交**，解析失败绝不能变成失败响应 —— 那会让调用方
     * 释放幂等键并重试，把一次报工记两遍（静默重复计件）。故只记 warn + 显式给 {@code null}
     * （三个键都在，值是 null = 未知，不是「没有下一道」）。</p>
     */
    private void enrichNextOperation(Map<String, Object> result, String token, Long tenantId) {
        try {
            Map<String, Object> next = scanService.resolve(token, null, tenantId);
            result.put("set_progress", next.get("set_progress"));
            result.put("set_completed", next.get("completed"));
            result.put("next_operation", next.get("operation"));
        } catch (RuntimeException e) {
            log.warn("[扫码完成] 下一道推断失败（本次报工已成功落库，仅缺「下一道」提示）: error={}",
                    e.getMessage());
            result.put("set_progress", null);
            result.put("set_completed", null);
            result.put("next_operation", null);
        }
    }

    /** 剩余应做数量 = 应做 − 已报（下限 0；`qty`/`done_qty` 为 NULL 按 0 读，与 isDone 同口径）。 */
    private static BigDecimal plannedRemaining(ProcessingPositionOperation op) {
        BigDecimal planned = op.getQty() == null ? BigDecimal.ZERO : op.getQty();
        BigDecimal done = op.getDoneQty() == null ? BigDecimal.ZERO : op.getDoneQty();
        BigDecimal remaining = planned.subtract(done);
        return remaining.signum() < 0 ? BigDecimal.ZERO : remaining;
    }
}
