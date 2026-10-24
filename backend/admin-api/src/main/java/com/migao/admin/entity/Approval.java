package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 具名审批（V181，issue #7374 P1-2）。
 *
 * <p>🔴 **业务对象不存审批结论副本**：需要审批的一方按 `objectType + objectRef` **读**本表，
 * 自己不再存一个「已批准」布尔 —— 否则审批被撤回后对象还写着已批准（双真值）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("approvals")
public class Approval {

    /** 五类封闭集合（表上有 CHECK；新增一类必须改迁移 + 改判据）。 */
    public static final String TYPE_CREDIT_OVERRIDE = "credit_override";
    public static final String TYPE_PRICE_CHANGE = "price_change";
    public static final String TYPE_REFUND = "refund";
    public static final String TYPE_PURCHASE_OVER = "purchase_over";
    public static final String TYPE_STOCKTAKE_DIFF = "stocktake_diff";

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String objectType;

    private String objectRef;

    private String objectLabel;

    private BigDecimal amount;

    /** 类型专属细节（改价旧价/新价、盘点差异行等）。JSON 字符串落库。 */
    private String payload;

    private String reason;

    private String status;

    private String requestedBy;

    private String requestedByName;

    private OffsetDateTime requestedAt;

    private String decidedBy;

    private String decidedByName;

    private OffsetDateTime decidedAt;

    private String decisionNote;

    /** 非空 = 这条审批已经被用掉了（超授信一笔一批）。 */
    private OffsetDateTime consumedAt;

    private String consumedRef;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
