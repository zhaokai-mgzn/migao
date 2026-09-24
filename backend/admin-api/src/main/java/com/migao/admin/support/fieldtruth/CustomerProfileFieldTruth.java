package com.migao.admin.support.fieldtruth;

import com.migao.admin.entity.CustomerProfile;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * {@code customer_profiles} 的字段级真值声明（{@link FieldTruth} 机制的<b>首个载体</b>，issue #5362）。
 *
 * <p><b>逐字段核实</b>（不是整表一刀切 —— 同一张表里有真值/无真值并存）：
 * 建档路径确实给 {@code vipLevel} / {@code customerStatus} / {@code sourceChannel} /
 * {@code registeredAt} / {@code lastActiveAt} … 赋了值，而 {@code rScore} / {@code avgOrderValue} /
 * {@code lastOrderAt} … 全仓零写入点 ⇒ 前者是<b>真值</b>，后者只是 DB 列默认值
 * （{@code DEFAULT 0} / {@code DEFAULT 0.00} / {@code DEFAULT 30}）被读出来冒充真值。
 *
 * <p><b>口径来源（照抄既有正确形态，不新发明一套）</b>：{@code product_skus.avg_cost} 的
 * {@code COMMENT ON COLUMN} 早已把「未知」与「0」分开 ——
 * 「{@code NULL = 未知（存量库存无成本真值来源，一律不回填、不猜 0）}」/
 * 「不得用 {@code 0} 冒充「成本为零」」。本声明把同一条口径落到客户画像上：
 * <b>无真值 ⇒ 读面一律 {@code null}（未知），不得把 DB 默认 0 / 建档种子常量当真值。</b>
 *
 * <p>⚠️ <b>DB 列当前仍保留历史 {@code DEFAULT 0}</b>（存量行也仍是 0）：本单只做「声明 + 判据 + 暴露面」，
 * 列默认值与存量回填属 A1（补 RFM / 消费额计算）的口径设计，不在本单。
 *
 * <p><b>为什么不是散文</b>：本文件的每一条都被
 * {@code CustomerProfileFieldTruthGateTest} 对着源码写入点与遮蔽清单逐字段机械核对 ——
 * 把任一字段改判（有真值 ↔ 无真值）都会让判据变红。
 */
public final class CustomerProfileFieldTruth {

    public static final String TABLE = "customer_profiles";

    private static final FieldTruth.Declaration DECLARATION = build();

    private CustomerProfileFieldTruth() {
    }

    public static FieldTruth.Declaration declaration() {
        return DECLARATION;
    }

    /** 便捷查询（未声明的字段返回 {@code null}）。 */
    public static FieldTruth truthOf(String field) {
        return DECLARATION.truthOf(field);
    }

    private static FieldTruth.Declaration build() {
        Map<String, FieldTruth.Entry> f = new LinkedHashMap<>();

        // ── 基础信息 ──
        f.put("id", has("MyBatis-Plus 框架生成：CustomerProfile 的 @TableId(type = IdType.ASSIGN_UUID)"));
        f.put("tenantId", has("建档路径 builder 显式下发（CustomerService#createFromSession / #createFromOrder 的 .tenantId(...)）"));
        f.put("wechatOpenid", has("CustomerService#createFromSession 的 builder .wechatOpenid(wechatOpenid)（C 端身份绑定键，真值来自登录）"));
        f.put("wechatUnionid", none("全仓零写入点（无 setWechatUnionid / builder / SQL SET）⇒ 该列恒 null：unionid 从未被采集"));
        f.put("wechatNickname", has("createFromSession .wechatNickname(wechatNickname) / createFromOrder .wechatNickname(customerName) / updateCustomer 非空拷贝"));
        f.put("phone", has("createFromOrder .phone(customerPhone)（下单建档主键）+ updateCustomer 非空拷贝"));
        f.put("gender", has("CustomerService#updateCustomer 非空拷贝（值来自请求；DB DEFAULT 'unknown' 不是它的唯一来源）"));
        f.put("regionProvince", has("CustomerService#updateCustomer 非空拷贝（省市区由客户管理页/Agent 录入）"));
        f.put("regionCity", has("CustomerService#updateCustomer 非空拷贝（同上）"));
        f.put("regionDistrict", has("CustomerService#updateCustomer 非空拷贝（同上）"));
        f.put("avatarUrl", none("全仓零写入点（无 setAvatarUrl / builder / SQL SET；admin-web 的 CustomerProfile 类型声明了它但后端从不写）⇒ 该列恒 null"));

        // ── 客户等级与状态 ──
        f.put("vipLevel", has("建档默认 \"normal\"（常量种子）+ CustomerService#updateCustomer 非空拷贝（真值级：人工/Agent 调整的 VIP 等级会落库）"));
        f.put("customerStatus", has("建档默认 \"active\"（常量种子）+ CustomerService#updateCustomer 非空拷贝（真值级：active/silent/churn_warning/churned 可被改写）"));
        f.put("sourceChannel", has("createFromSession .sourceChannel(sourceChannel != null ? sourceChannel : \"wechat_mini\") / createFromOrder .sourceChannel(\"order\")（真值来自建档来源）"));

        // ── RFM 评分（issue #5362 的核心取证面：有列、有读面、无计算）──
        f.put("rScore", none("全仓零写入点（setRScore / builder / SQL SET 零命中）：无任何 RFM 计算逻辑，DB DEFAULT 0 不是「1-5 分」的真值"));
        f.put("fScore", none("全仓零写入点：同上（频率分从未被计算）"));
        f.put("mScore", none("全仓零写入点：同上（金额分从未被计算）"));
        f.put("rfmTotalScore", none("全仓零写入点：同上（3-15 分的总分从未被计算，读出来恒为 DB DEFAULT 0）"));

        // ── 统计数据 ──
        f.put("totalOrders", none("只有建档常量种子（createCustomer setTotalOrders(0) / builder .totalOrders(0) / createFromOrder .totalOrders(1)），无任何增量维护 ⇒ 老客户恒 0 或 1"));
        f.put("totalConsumption", none("只有建档常量种子（setTotalConsumption(BigDecimal.ZERO) / builder .totalConsumption(ZERO)）：createFromOrder 同一处写 .totalOrders(1) + .totalConsumption(ZERO) —— 有 1 单却消费 0 元，自证是占位而非真值"));
        f.put("totalRefundAmount", none("全仓零写入点（setTotalRefundAmount / builder / SQL SET 零命中），DB DEFAULT 0.00 会被读成「从未退款」"));
        f.put("avgOrderValue", none("全仓零写入点（客单价从未被计算），DB DEFAULT 0.00 会被读成「客单价 0 元」"));
        f.put("repurchaseRate", none("全仓零写入点（复购率从未被计算），DB DEFAULT 0.0000 会被读成「复购率 0%」"));
        f.put("lifecycleStage", none("只有建档常量 \"new\"（builder + setLifecycleStage(\"new\")），不在 updateCustomer 拷贝白名单、无任何生命周期计算 ⇒ 老客户恒 \"new\""));

        // ── 时间字段 ──
        f.put("firstOrderAt", none("全仓零写入点（首单时间从未被写）⇒ 该列恒 null：不是「未知」而是「没接」"));
        f.put("lastOrderAt", none("全仓零写入点（最近下单时间从未被写）⇒ 该列恒 null：CRM 的「最近下单」其实只有 lastActiveAt 在动"));
        f.put("lastActiveAt", has("createFromSession / createFromOrder 命中既有客户时 existing.setLastActiveAt(OffsetDateTime.now())（真值级：值来自真实活跃事件）"));
        f.put("registeredAt", has("建档 setRegisteredAt(OffsetDateTime.now()) / builder .registeredAt(now)（真值级：建档时刻）"));

        // ── 备注与标签 ──
        f.put("agentNotes", has("createFromOrder 写入「首单收货地址：…」 / updateCustomer 非空拷贝（客服备注真值来自人工/Agent）"));
        f.put("tags", has("addTagToCustomer / removeTagFromCustomer 的 profile.setTags(tagIds)（真值来自 customer_tags 表关联）+ updateCustomer 非空拷贝"));
        f.put("customFields", has("CustomerService#updateCustomer 非空拷贝（自定义字段由调用方下发）"));

        // ── 工艺画像与常用物流（issue #3984，V47）──
        f.put("craftMode", has("updateCustomer 的 existing.setCraftMode(requireValidCraftMode(profile.getCraftMode()))（真值级：值经白名单校验后落库）"));
        f.put("craftProfile", has("CustomerService#updateCustomer 非空拷贝（M3-F 报价协商会读它）"));
        f.put("defaultLogisticsType", has("CustomerService#updateCustomer 非空拷贝（客户常用物流方式）"));
        f.put("defaultLogisticsCompany", has("CustomerService#updateCustomer 非空拷贝（常用承运商）"));

        // ── 默认收货信息（issue #4419，V70）──
        f.put("defaultReceiverName", has("CustomerService#updateCustomer 非空拷贝（收货人姓名，新增订单选客户时逐字带出）"));
        f.put("defaultReceiverPhone", has("CustomerService#updateCustomer 非空拷贝（客户列表 keyword 搜索覆盖此列，issue #4436）"));
        f.put("defaultReceiverAddress", has("CustomerService#updateCustomer 非空拷贝（单字段文本地址，与 orders.customer_address 同口径）"));

        // ── 生命周期预测 ──
        f.put("churnRiskScore", none("全仓零写入点（流失风险评分从未被计算），DB DEFAULT 0.0000 会被读成「流失风险 0」"));
        f.put("nextPurchasePredictionDays", none("全仓零写入点（预计下次购买天数从未被预测），DB DEFAULT 30 会被读成「每个客户都将于 30 天后复购」"));

        // ── 审计字段 ──
        f.put("createdAt", has("MyBatis-Plus 框架生成：@TableField(fill = FieldFill.INSERT) + MyMetaObjectHandler"));
        f.put("updatedAt", has("MyBatis-Plus 框架生成：@TableField(fill = FieldFill.INSERT_UPDATE) + MyMetaObjectHandler"));

        return new FieldTruth.Declaration(CustomerProfile.class, TABLE, f);
    }

    private static FieldTruth.Entry has(String reason) {
        return new FieldTruth.Entry(FieldTruth.HAS_TRUTH, reason);
    }

    private static FieldTruth.Entry none(String reason) {
        return new FieldTruth.Entry(FieldTruth.NO_TRUTH, reason);
    }
}