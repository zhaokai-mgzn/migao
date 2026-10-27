package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 打印流水（V201，issue #7902）—— 谁、什么时候、打了哪种单据。
 *
 * <h3>这张表是「外部事实」的登记面，不是业务状态的副本</h3>
 * <p>纸出没出来，服务端**不可能知道**（浏览器打印对话框的最终结果不在任何接口里，蓝牙直连也一样）
 * ⇒ {@link #STATUS_FIRED} 的含义是「已发起到打印」，{@link #STATUS_FAILED} 是「明确失败」。
 * ⛔ 别加「已打印」这种第三态：那会把一个不可验证的承诺写成数据库事实。</p>
 *
 * <p>🔴 {@code orderNo} / {@code orderStatus} / {@code docTitle} / {@code operatorName} 都是**当时的快照**，
 * 真值仍在 {@code orders} / {@code users}。快照存在的唯一理由是历史可读（单作废、人改名之后流水仍要说得清）
 * —— 它们**只用于显示**，任何业务判断都不许读它们。</p>
 *
 * <h3>三个闭集合（表上有 CHECK 兜底，本类同一份口径）</h3>
 * <p>新增一种单据 / 通道 / 结果 ⇒ 必须同时改迁移与这里的常量（判据：
 * {@code PrintLogServiceTest} 的白名单拒绝用例 + {@code PrintLogSurfaceGuardTest}）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("print_logs")
public class PrintLog {

    // ── doc_type：四类单据（封闭集合，与迁移的 ck_print_logs_doc_type 逐字一致） ──

    /** 销售单（订单详情页的主单据）。 */
    public static final String DOC_SALES = "sales";
    /** 加工单 / 作业单（加工单 + 面料单两型纸面）。 */
    public static final String DOC_PROCESSING = "processing";
    /** 报价单（客户报价，未成单也可打）。 */
    public static final String DOC_QUOTATION = "quotation";
    /** 标签类（水洗唛 / 入库标签，按部位或按件一张）。 */
    public static final String DOC_LABELS = "labels";

    /** doc_type 封闭集合（顺序即前端展示顺序：销售单 → 加工单 → 报价单 → 标签）。 */
    public static final java.util.List<String> DOC_TYPES =
            java.util.List.of(DOC_SALES, DOC_PROCESSING, DOC_QUOTATION, DOC_LABELS);

    // ── channel：两条打印通道 ──

    /** 系统打印（浏览器 window.print()）。 */
    public static final String CHANNEL_BROWSER = "browser";
    /** 蓝牙直连（设备侧直打，绕开浏览器对话框）。 */
    public static final String CHANNEL_BLE = "ble";

    public static final java.util.List<String> CHANNELS = java.util.List.of(CHANNEL_BROWSER, CHANNEL_BLE);

    // ── status：两档结果（服务端只可能知道这两档，见类注释） ──

    /** 已发起到打印（纸出没出来服务端不知道）。 */
    public static final String STATUS_FIRED = "fired";
    /** 明确的失败（原因在 failReason）。 */
    public static final String STATUS_FAILED = "failed";

    public static final java.util.List<String> STATUSES = java.util.List.of(STATUS_FIRED, STATUS_FAILED);

    /** 出纸张数的合法区间（与迁移的 ck_print_logs_sheets 一致）。 */
    public static final int MIN_SHEETS = 1;
    public static final int MAX_SHEETS = 999;

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String orderId;

    /** 订单号快照（订单作废/软删后仍可读；只用于显示）。 */
    private String orderNo;

    private String docType;

    /** 打印当时的纸面名（「加工单」/「面料单」/「水洗唛」/「销售单」/「报价单」）。 */
    private String docTitle;

    private String processingOrderId;

    /** 加工单号快照（加工单 / 水洗唛那两张才有）。 */
    private String processingOrderNo;

    /** 纸型 id（a4 / continuous-241x140 / label-50x110，登记在 admin-web 的 print-media.json）。 */
    private String mediaId;

    /** 这次出纸几张（水洗唛按部位一张）。 */
    private Integer sheets;

    private String channel;

    /** 一次联合打印的 N 条共享同一个 batchId。 */
    private String batchId;

    /** 这一批里的第几条（0 起）。 */
    private Integer batchIndex;

    /** 这一批共几条。 */
    private Integer batchSize;

    /** 打印当时的订单状态快照（分清首打与发货后补打）。 */
    private String orderStatus;

    private String status;

    private String failReason;

    private String operatorId;

    /** 姓名快照（改名/离职后历史仍可读）。 */
    private String operatorName;

    private String clientIp;

    private String userAgent;

    private OffsetDateTime createdAt;

    /** doc_type 是否在封闭集合内。 */
    public static boolean isKnownDocType(String docType) {
        return DOC_TYPES.contains(docType);
    }

    /** channel 是否在封闭集合内。 */
    public static boolean isKnownChannel(String channel) {
        return CHANNELS.contains(channel);
    }

    /** status 是否在封闭集合内。 */
    public static boolean isKnownStatus(String status) {
        return STATUSES.contains(status);
    }
}
