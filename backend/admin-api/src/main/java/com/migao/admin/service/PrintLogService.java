package com.migao.admin.service;

import com.migao.admin.dto.PrintLogItemRequest;
import com.migao.admin.dto.PrintLogRecordResult;
import com.migao.admin.dto.PrintLogRequest;
import com.migao.admin.dto.PrintLogView;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.PrintLog;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.PrintLogMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.stream.Collectors;

/**
 * 打印流水（V201，issue #7902）—— 登记「谁、什么时候、打了哪种单据」+ 按订单读回。
 *
 * <h3>三条纪律</h3>
 * <ol>
 *   <li><b>请求体只带客户端知道的事</b>：订单号 / 订单状态 / 操作人 / 租户 / 时间 / 批号**全部服务端补**。
 *       否则「谁打的」可以由调用方自己写，流水就没有证据价值（判据见
 *       {@code PrintLogServiceTest#recordFillsServerSideSnapshotsPerDoc}）；</li>
 *   <li><b>闭集合 fail-closed</b>：{@code docType} / {@code channel} / {@code status} 三个值域
 *       与 {@link PrintLog} 的常量同一份口径（表上还有 CHECK 兜底）—— 自由串会让聚合永远对不上；</li>
 *   <li><b>打印是外部事实</b>：本服务只登记「已发起 + 结果」，**不**提供任何「确认已打印」的能力
 *       （纸出没出来服务端不可能知道，见 {@link PrintLog} 的类注释）。</li>
 * </ol>
 *
 * <h3>入参拒绝一律 400（不是 422）</h3>
 * <p>打印请求是**客户端输入**：条数 / 闭集合 / 长度这些东西在解析阶段就该拒，且没有「逐条护栏理由」
 * 需要回给表单（那是 422 的用途，见 {@code BusinessException.validationError}）。
 * 故这里用 400 + {@code VALIDATION_ERROR}，与分页入参闸同口径。</p>
 *
 * <h3>边界（照实登记）</h3>
 * <p>{@code clientIp} 取 {@code HttpServletRequest#getRemoteAddr()}（与 {@code WorkerInboundLabelController}
 * 的留痕同口径）。部署在反向代理之后时它可能是**代理地址** —— 这一列是审计辅助信息，
 * 不参与任何判定；要真实客户端 IP 需要一个全仓统一的「可信代理头」口径（本包不发明第二套）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PrintLogService {

    /** 一次请求最多登记多少条：一次联合打印 = 一次请求，10 张纸是「一个人一次操作」的合理上限。 */
    static final int MAX_DOCS_PER_REQUEST = 10;

    /** 列表默认条数。 */
    static final int DEFAULT_LIST_LIMIT = 20;

    /** 列表封顶条数（不许把「看流水」变成全表扫）。 */
    static final int MAX_LIST_LIMIT = 100;

    /** 与迁移列宽逐字一致（超长直接 400，不由 DB 静默截断）。 */
    private static final int MAX_DOC_TITLE = 32;
    private static final int MAX_MEDIA_ID = 32;
    private static final int MAX_FAIL_REASON = 255;

    /** 服务端派生字段的列宽：**截断**而不是拒绝（用户的 UA / 姓名长不该让一次打印失败）。 */
    private static final int MAX_OPERATOR_NAME = 64;
    private static final int MAX_CLIENT_IP = 64;
    private static final int MAX_USER_AGENT = 255;

    private final PrintLogMapper printLogMapper;
    private final OrderMapper orderMapper;
    private final ProcessingOrderMapper processingOrderMapper;

    /**
     * 登记一次打印（一次请求 = 一批，N 条共享 {@code batchId}）。
     *
     * @param orderId   订单 id（必须存在于本租户；否则 404 —— 流水不能挂在不存在的单上）
     * @param request   本次打印的文档清单（1~10 条）
     * @param tenantId  当前租户（服务端上下文，不接受客户端递交）
     * @param operator  当前操作人（id + 显示名快照；内部服务令牌下可为 null）
     * @param clientIp  来源 IP（审计辅助，可空）
     * @param userAgent UA（审计辅助，可空；**不**下发到读面、**不**写进日志）
     * @return 本次落库的 id + 登机时刻
     */
    @Transactional(rollbackFor = Exception.class)
    public PrintLogRecordResult record(String orderId, PrintLogRequest request, Long tenantId,
                                       Operator operator, String clientIp, String userAgent) {
        requireTenant(tenantId);
        Order order = requireOrder(orderId, tenantId);
        List<PrintLogItemRequest> docs = request == null ? null : request.getDocs();
        if (docs == null || docs.isEmpty()) {
            throw invalid("请至少提供一条打印记录（docs 不能为空）");
        }
        if (docs.size() > MAX_DOCS_PER_REQUEST) {
            throw invalid(String.format("一次最多登记 %d 条打印记录（本次 %d 条）",
                    MAX_DOCS_PER_REQUEST, docs.size()));
        }

        // 一批共享的元数据：批号 / 时刻 / 租户 / 操作人 / 来源
        String batchId = UUID.randomUUID().toString().replace("-", "");
        OffsetDateTime printedAt = OffsetDateTime.now();
        String operatorId = operator == null ? null : clip(operator.userId(), 36);
        String operatorName = operator == null ? null : clip(operator.displayName(), MAX_OPERATOR_NAME);
        String ip = clip(clientIp, MAX_CLIENT_IP);
        String ua = clip(userAgent, MAX_USER_AGENT);

        List<String> ids = new ArrayList<>(docs.size());
        for (int index = 0; index < docs.size(); index++) {
            PrintLog row = buildRow(order, docs.get(index), index, docs.size(), batchId, printedAt,
                    tenantId, operatorId, operatorName, ip, ua);
            printLogMapper.insert(row);
            ids.add(row.getId());
        }

        log.info("[print-log] 登记打印流水 orderId={}, orderNo={}, docTypes={}, batchId={}, operator={}",
                orderId, order.getOrderNo(), docTypeSummary(docs), batchId, operatorName);
        return new PrintLogRecordResult(ids, printedAt);
    }

    /**
     * 某张订单的打印流水（时间倒序）。
     *
     * @param limit 默认 {@value #DEFAULT_LIST_LIMIT}、封顶 {@value #MAX_LIST_LIMIT}（越界不报错，收敛到边界）
     * @throws BusinessException 404 订单不存在 / 非本租户（与「没打过」是两件事：空列表 ≠ 404）
     */
    public List<PrintLogView> listByOrder(String orderId, Integer limit, Long tenantId) {
        requireTenant(tenantId);
        requireOrder(orderId, tenantId);
        int effective = limit == null || limit <= 0 ? DEFAULT_LIST_LIMIT : Math.min(limit, MAX_LIST_LIMIT);
        return printLogMapper.selectByOrder(tenantId, orderId, effective).stream()
                .map(PrintLogView::from)
                .collect(Collectors.toList());
    }

    // ============================================================ 内部

    /**
     * 打印流水是**租户域资源**：没有租户上下文（平台管理员 / 内部服务令牌）⇒ 401 明确拒绝。
     *
     * <p>为什么不「放行成空结果」：{@code tenant_id IS NULL} 的查询恒空 / 插入则撞 NOT NULL（500）。
     * 前者会把「你没有租户」伪装成「这单没打过」，后者是一个本该 401 的 500 ——
     * 与「平台侧不读商家业务数据」的能力边界同口径（见 {@code MybatisPlusConfig} 的说明）。</p>
     */
    private static void requireTenant(Long tenantId) {
        if (tenantId == null) {
            throw BusinessException.tenantInvalid();
        }
    }

    /** 租户内订单；不存在 / 跨租户一律 404（403 会泄露「这个 id 存在，只是不归你」）。 */
    private Order requireOrder(String orderId, Long tenantId) {
        if (!StringUtils.hasText(orderId)) {
            throw BusinessException.notFound("订单");
        }
        Order order = orderMapper.selectById(orderId);
        if (order == null || (tenantId != null && !tenantId.equals(order.getTenantId()))) {
            throw BusinessException.notFound("订单");
        }
        return order;
    }

    /** 一条文档 → 一行流水（逐条校验 + 服务端快照）。 */
    private PrintLog buildRow(Order order, PrintLogItemRequest doc, int index, int batchSize, String batchId,
                              OffsetDateTime printedAt, Long tenantId, String operatorId, String operatorName,
                              String clientIp, String userAgent) {
        if (doc == null) {
            throw invalid(String.format("第 %d 条打印记录为空", index + 1));
        }
        String docType = requireClosedSet(doc.getDocType(), PrintLog.DOC_TYPES,
                index, "打印单据类型", "sales / processing / quotation / labels");
        String channel = optionalClosedSet(doc.getChannel(), PrintLog.CHANNEL_BROWSER, PrintLog.CHANNELS,
                index, "打印通道", "browser（系统打印）/ ble（蓝牙直连）");
        String status = optionalClosedSet(doc.getStatus(), PrintLog.STATUS_FIRED, PrintLog.STATUSES,
                index, "打印结果", "fired（已发起）/ failed（失败）");

        String docTitle = requireMaxLength(doc.getDocTitle(), MAX_DOC_TITLE, index, "纸面名");
        String mediaId = requireMaxLength(doc.getMediaId(), MAX_MEDIA_ID, index, "纸型 id");
        String failReason = requireMaxLength(doc.getFailReason(), MAX_FAIL_REASON, index, "失败原因");

        Integer sheets = doc.getSheets() == null ? PrintLog.MIN_SHEETS : doc.getSheets();
        if (sheets < PrintLog.MIN_SHEETS || sheets > PrintLog.MAX_SHEETS) {
            throw invalid(String.format("第 %d 条的出纸张数必须是 %d~%d（本次 %d）",
                    index + 1, PrintLog.MIN_SHEETS, PrintLog.MAX_SHEETS, sheets));
        }

        String processingOrderId = clip(doc.getProcessingOrderId(), 36);
        String processingOrderNo = resolveProcessingOrderNo(docType, processingOrderId, order.getId(), tenantId);

        return PrintLog.builder()
                .tenantId(tenantId)
                .orderId(order.getId())
                .orderNo(order.getOrderNo())
                .docType(docType)
                .docTitle(docTitle)
                .processingOrderId(processingOrderId)
                .processingOrderNo(processingOrderNo)
                .mediaId(mediaId)
                .sheets(sheets)
                .channel(channel)
                .batchId(batchId)
                .batchIndex(index)
                .batchSize(batchSize)
                .orderStatus(order.getStatus())
                .status(status)
                .failReason(failReason)
                .operatorId(operatorId)
                .operatorName(operatorName)
                .clientIp(clientIp)
                .userAgent(userAgent)
                .createdAt(printedAt)
                .build();
    }

    /**
     * 加工单号快照：只有「加工单 / 标签类」两张纸才有，且必须**属于本次这张订单**。
     *
     * <p>查不到 / 已作废 / 不属于本单 ⇒ 留空**不报错**：打印不能因为主数据缺失而失败
     * （纸已经出去了，拒收这条流水只会让历史少一段）。判据见
     * {@code PrintLogServiceTest#recordDoesNotBorrowAnotherOrdersProcessingOrderNo}。</p>
     */
    private String resolveProcessingOrderNo(String docType, String processingOrderId,
                                            String orderId, Long tenantId) {
        boolean needsIt = PrintLog.DOC_PROCESSING.equals(docType) || PrintLog.DOC_LABELS.equals(docType);
        if (!needsIt || !StringUtils.hasText(processingOrderId)) {
            return null;
        }
        ProcessingOrder processingOrder = processingOrderMapper.selectById(processingOrderId);
        if (processingOrder == null
                || !orderId.equals(processingOrder.getOrderId())
                || (tenantId != null && !tenantId.equals(processingOrder.getTenantId()))) {
            return null;
        }
        return clip(processingOrder.getProcessingOrderNo(), 64);
    }

    private static String requireClosedSet(String value, List<String> allowed, int index,
                                           String label, String readable) {
        if (!StringUtils.hasText(value)) {
            throw invalid(String.format("第 %d 条缺少%s（可选：%s）", index + 1, label, readable));
        }
        String trimmed = value.trim();
        if (!allowed.contains(trimmed)) {
            throw invalid(String.format("第 %d 条的%s「%s」不认识（可选：%s）", index + 1, label, value, readable));
        }
        return trimmed;
    }

    private static String optionalClosedSet(String value, String fallback, List<String> allowed, int index,
                                            String label, String readable) {
        if (!StringUtils.hasText(value)) {
            return fallback;
        }
        return requireClosedSet(value, allowed, index, label, readable);
    }

    private static String requireMaxLength(String value, int max, int index, String label) {
        if (!StringUtils.hasText(value)) {
            return null;
        }
        String trimmed = value.trim();
        if (trimmed.length() > max) {
            throw invalid(String.format("第 %d 条的%s最长 %d 个字符（本次 %d）",
                    index + 1, label, max, trimmed.length()));
        }
        return trimmed;
    }

    /** 服务端派生字段的统一处理：去空白、空串归 null、超长截断（用户属性不该让打印失败）。 */
    private static String clip(String value, int max) {
        if (!StringUtils.hasText(value)) {
            return null;
        }
        String trimmed = value.trim();
        return trimmed.length() <= max ? trimmed : trimmed.substring(0, max);
    }

    private static String docTypeSummary(List<PrintLogItemRequest> docs) {
        return docs.stream()
                .map(doc -> doc == null ? "null" : String.valueOf(doc.getDocType()))
                .collect(Collectors.joining(","));
    }

    /** 入参拒绝（400 + VALIDATION_ERROR；理由见类注释「入参拒绝一律 400」）。 */
    private static BusinessException invalid(String message) {
        return new BusinessException("VALIDATION_ERROR", message, 400);
    }

    /** 操作人（id + 显示名快照）：只从服务端安全上下文取，不接受客户端递交。 */
    public record Operator(String userId, String displayName) {
    }
}
