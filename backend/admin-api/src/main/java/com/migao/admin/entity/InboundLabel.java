package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 入库标签实体（issue #5052 <b>P2</b>；设计真值源
 * {@code docs/design/inbound-photo-and-label.md} §7.1 / §7.3）。对应表：{@code inbound_labels}（V134）。
 *
 * <p>一行 = 一个入库单明细行（= 一个 SKU = 一个批次）= 一张 <b>50×30mm</b> 标签；
 * 标签上的码 = {@code https://app.migaozn.com/i/<8 位短码>}（§7.1 一次定死）。</p>
 *
 * <h3>撤销 = {@link #shortCode} 置 NULL（§7.3 逐字），原码留档 {@link #revokedCode}</h3>
 * <p>只置 NULL 会让「这张纸已作废」被读成「没这个码」（404）—— 那正是
 * {@code /s/} 侧 {@code WorkerShortLinkService} 刻意避免的形态。故撤销时把原码原样留档到
 * {@link #revokedCode}，扫码仍能判 <b>410 Gone</b>；两条列由
 * {@code ck_inbound_labels_code_exactly_one} 钉成「恰有一个非空」的结构不变量。</p>
 *
 * <h3>🔴 与 {@link ProcessingSetPartToken}（工人报工短链 {@code /s/}）是**两个码空间**</h3>
 * <p>#5052 边界逐字：「照其范式、不复用其表」—— 本实体照其范式（8 位 Crockford Base32 / 部分唯一索引 /
 * 原子自增计数），但**不复用其表**：混用会把「扫标签」变成「进报工页」。短码的生成 / 归一化口径
 * **复用** {@code WorkerShortLinkService} 的静态方法（{@code ALPHABET} / {@code randomCode} /
 * {@code normalize} / {@code allocateUnique}），**不复制第二份字母表**。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("inbound_labels")
public class InboundLabel {

    /**
     * 打印审计的动作**动词**（issue #4071 裁定 ①：{@code action} 只放动词、不含工具名）。
     */
    public static final String ACTION_PRINT = "print";

    /** 审计 / 业务资源的类型名（{@code audit_logs.resource_type}）。 */
    public static final String RESOURCE_TYPE = "inbound_label";

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String inboundOrderId;

    /** 入库单明细行 id（{@code inbound_order_items.id}） */
    private Long inboundItemId;

    /** 当前**有效**短码；撤销 ⇒ NULL（§7.3）。 */
    private String shortCode;

    /** 撤销时留档的原短码（与 {@link #shortCode} 恰有一个非空）。 */
    private String revokedCode;

    /** 打印次数（**原子自增**，重打同样计数）。 */
    private Integer printCount;

    private String createdBy;

    private OffsetDateTime revokedAt;

    private String revokedBy;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    /** 软删（{@code @TableLogic} ⇒ 查询自动带 {@code deleted = 0}）。 */
    @TableLogic
    private Integer deleted;

    /** 已撤销（短码已置 NULL）—— 扫码面据此判 <b>410</b> 而不是 404。 */
    public boolean isRevoked() {
        return shortCode == null;
    }

    /** 这张纸的**印刷码**（未撤销 = 活码；已撤销 = 留档码）—— 审计与响应一律用它。 */
    public String printedCode() {
        return shortCode != null ? shortCode : revokedCode;
    }
}
