package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.exception.BusinessException;
import org.springframework.util.StringUtils;

import java.util.List;

/**
 * 订单的**安装信息**（issue #7856）—— 写侧单点扇出 / 读侧收敛的**唯一实现点**。
 *
 * <h2>两个字段（口径已定，键名不改）</h2>
 * <table border="1">
 *   <caption>语义边界</caption>
 *   <tr><th>键（{@code order_items.processing_info} 顶层，camelCase）</th><th>语义</th><th>载体</th></tr>
 *   <tr><td>{@link #KEY_INSTALL_COMMUNITY} = {@code installCommunity}</td>
 *       <td><b>安装小区</b>：这批帘子最终装进的那一户人家所在的小区（可带楼栋/单元/门牌）。
 *       <b>不是收货地址</b>（货是发给下单的窗帘店）。</td>
 *       <td><b>订单级语义</b>，但落在**每一行**的同名字符串（快照是行数组、没有订单级顶层对象）</td></tr>
 *   <tr><td>{@link #KEY_INSTALL_ROOM} = {@code installRoom}</td>
 *       <td><b>安装位置</b>：这一扇窗装在那户人家的哪个空间（主卧 / 次卧 / 客厅 / 阳台 …）。
 *       <b>不是部位/帘种</b>（布帘 / 纱帘 / 帘头 = {@code curtainType}）。</td>
 *       <td><b>件级</b>（= {@code order_items} 一行 = 一扇窗）</td></tr>
 * </table>
 *
 * <h2>为什么落在 {@code processing_info} 而不是给订单/明细加列（用户 2026-10-26 当场裁定）</h2>
 * <p>用户逐字：「不能作为订单基础字段吧？」⇒ 本信息是**纸面说明**（水洗唛 / 发货标签 / 入库标签），
 * 不参与算料 / 计价 / 派工 / 库存 / 检索，不是订单的基础事实。{@code order_items.processing_info}
 * 是**已登记**的 JSONB 扩展点（{@code tests/unit_ci_workflows/schema_health_ledger.json} 的
 * {@code jsonb_columns}），与 {@code formulaText} / {@code remark} 同一层 ⇒ **数据库零迁移**
 * （{@code orders} 仍 24 列、{@code order_items} 仍 32 列，后者已是超列预算的具名例外）。</p>
 *
 * <h2>为什么订单级语义要「扇出到每一行」</h2>
 * <p>加工单快照（{@code processing_orders.items_snapshot}）与订单明细都是**行数组**，没有订单级
 * 顶层对象 ⇒ 订单级事实只能逐行固化（同 {@code isUrgent} / {@code requiredDeliveryDate}
 * 的既有范式）。<b>写侧单点扇出</b>（{@link OrderService#persistOrderItems} —— 建单 / 内容更新
 * 三条路径的唯一共享入口）、<b>读侧收敛</b>（{@link #firstCommunity} 取第一条非空）⇒ 不让前端
 * 逐行写同一个字符串（那是第二份口径，总会漂）。</p>
 *
 * <h2>缺值口径</h2>
 * <p><b>缺值不落键</b>（与 {@code CRAFT_SPEC_SNAPSHOT_KEYS} 的白名单键族一致）：没填就不写这个键，
 * 不落 {@code null} / 空串 —— 读侧据此「缺值 = 纸面不印」，而不是印一行空的「安装小区: 」。</p>
 */
final class OrderInstallInfo {

    /** {@code processing_info} 顶层的**安装小区**键（订单级语义，逐行落同值）。 */
    static final String KEY_INSTALL_COMMUNITY = "installCommunity";

    /** {@code processing_info} 顶层的**安装位置**键（件级 = 一扇窗）。 */
    static final String KEY_INSTALL_ROOM = "installRoom";

    /** 安装小区上限（可带楼栋/单元/门牌，故比位置宽）：{@code VARCHAR(40)} 未建列，口径与纸面一致。 */
    static final int COMMUNITY_MAX_LENGTH = 40;

    /** 安装位置上限（「主卧」「客厅」「阳台」这类空间名）。 */
    static final int ROOM_MAX_LENGTH = 12;

    private OrderInstallInfo() {
    }

    /**
     * 归一 + 准入：**去首尾空白**、**内部换行/制表折叠为一个空格**、长度 ≤ 上限；空白 ⇒ {@code null}。
     *
     * <p>超长 ⇒ {@link BusinessException#validationError}（HTTP <b>422</b> —— 本仓字段校验的统一形态，
     * 与 {@code OrderService} 里其它字段准入同源；不是 400）。</p>
     *
     * <p>为什么折叠内部空白：纸面标签按单行打印，粘贴进来的换行会把一行撑成两行（50×70 标签上没有第二行的位置）。
     * 为什么空白 ⇒ {@code null} 而不是空串：缺值 = 不落键（否则「填了又删」会在快照里留下一个空字符串，
     * 读侧分不清「没填」与「填了个空」）。</p>
     */
    static String normalize(String raw, String label, int maxLength) {
        if (!StringUtils.hasText(raw)) {
            return null;
        }
        String value = raw.replaceAll("[\\r\\n\\t]+", " ").trim();
        if (!StringUtils.hasText(value)) {
            return null;
        }
        if (value.length() > maxLength) {
            throw BusinessException.validationError(
                    label + "不能超过 " + maxLength + " 个字（当前 " + value.length() + " 个）");
        }
        return value;
    }

    /** 安装小区：归一 + ≤{@link #COMMUNITY_MAX_LENGTH}；空白 ⇒ {@code null}（不落键）。 */
    static String normalizeCommunity(String raw) {
        return normalize(raw, "安装小区", COMMUNITY_MAX_LENGTH);
    }

    /** 安装位置：归一 + ≤{@link #ROOM_MAX_LENGTH}；空白 ⇒ {@code null}（不落键）。 */
    static String normalizeRoom(String raw) {
        return normalize(raw, "安装位置", ROOM_MAX_LENGTH);
    }

    /**
     * 单行取值：把该行的 {@code processing_info} 归一后取指定键，返回**去空白**后的字符串；
     * 缺键 / 非字符串 / 空白 ⇒ {@code null}（**不猜**、不回落）。
     */
    static String valueOf(Object processingInfo, String key, ObjectMapper objectMapper) {
        Object normalized = OrderLineCraftFields.normalize(processingInfo, objectMapper);
        // 存量行 `processing_info` 可能为 NULL ⇒ 归一结果也可能是 null（issue #5550 的空安全口径）
        if (normalized == null) {
            return null;
        }
        if (!(normalized instanceof java.util.Map<?, ?> map)) {
            return null;
        }
        Object value = map.get(key);
        if (!(value instanceof String text) || !StringUtils.hasText(text)) {
            return null;
        }
        return text.trim();
    }

    /**
     * **读侧收敛**（订单级投影）：取该订单明细里**第一条非空**的 {@code installCommunity}。
     *
     * <p>写侧把同一个字符串扇到每一行 ⇒ 正常情况每行都一样；这里取第一条非空是为了兼容
     * ① 存量行（扇出之前落的单没有该键）② 半扇出的历史数据（内容编辑过、只有部分行带）。
     * 全缺 ⇒ {@code null}（不拼「未填写」这类占位）。</p>
     */
    static String firstCommunity(List<OrderItem> items, ObjectMapper objectMapper) {
        if (items == null) {
            return null;
        }
        for (OrderItem item : items) {
            String community = valueOf(item.getProcessingInfo(), KEY_INSTALL_COMMUNITY, objectMapper);
            if (community != null) {
                return community;
            }
        }
        return null;
    }
}
