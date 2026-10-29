package com.migao.admin.service;

import java.util.List;
import java.util.Map;

/**
 * 「布/纱派生族」的名称口径（issue #8007 立机制；issue #8108 接入「绑带」族）—— 全系统唯一一份。
 *
 * <h2>用户口径（逐字）</h2>
 * 「特殊选项里的这两项要改，只需要展示<b>余料带回</b>即可，后面的 {@code -布} 和 {@code -纱}
 * 应该是默认<b>跟随订单套行的帘种</b>来决定的，这样语义更清晰」「这个规则要<b>适用于全系统</b>」；
 * issue #8108（2026-10-29）：「把这两项也合并成一个绑带选项，布/纱是跟随帘种来确定的」。
 *
 * <h2>三条口径</h2>
 * <ol>
 *   <li><b>录入 / 展示只出现语义名</b>（{@code 余料带回}）—— 材料不是商家的选择题；</li>
 *   <li><b>落库键由明细行的帘种派生</b>：{@code 纱帘 ⇒ 余料带回-纱}，{@code 布帘 / 帘头 / 未指定 ⇒ 余料带回-布}；</li>
 *   <li><b>join key 词表一字不改</b>（历史数据、工序规则、计件口径不动）⇒ 本类是**读侧的兼容层**：
 *       语义名与两种派生键都认，且不会把「布」规则误命中到纱帘单。</li>
 * </ol>
 *
 * <h2>🔴 族机制是通用的，业务含义不是</h2>
 * <p>「客户带走余料」<b>只</b>属于 {@code 余料带回} 这一族（{@link #isCustomerTakeAway}）；
 * {@code 绑带} 族是<b>车间工序</b>语义，勾它 ≠ 余料归客户。把「任一族的成员」当成「客户带走」
 * 曾是一个真实的静默账错（余料落 {@code customer_taken} ⇒ 不进可用池、不可回收 / 报废）——
 * 判据 = {@code OptionFamilyNamesTest.customerTakeAwayIsScopedToTheLeftoverFamilyOnly}。</p>
 *
 * <p>⚠️ 前端派生点在 {@code frontend/admin-web/src/lib/order-craft-fields.ts::SPECIAL_OPTION_FAMILIES}
 * （录入边界），展示收敛在 {@code craft-display.ts::optionList}（三端同源）；
 * 本类与它们同口径，两侧一致性由判据钉住。</p>
 */
final class OptionFamilyNames {

    /** 语义名（= 录入 / 展示面唯一该出现的名字） */
    static final String TAKE_AWAY_BASE = "余料带回";
    /** 派生键：布帘 / 帘头（材料是布） */
    static final String TAKE_AWAY_FABRIC = "余料带回-布";
    /** 派生键：纱帘（材料是纱） */
    static final String TAKE_AWAY_SHEER = "余料带回-纱";

    /** 语义名：绑带（issue #8108，用户 2026-10-29 裁定「把这两项也合并成一个绑带选项」） */
    static final String BANDING_BASE = "绑带";
    /** 派生键：布帘 / 帘头（材料是布）—— 仍是 join key，触发工序 {@code 绑带-布} */
    static final String BANDING_FABRIC = "布绑带";
    /** 派生键：纱帘（材料是纱）—— 触发工序 {@code 绑带-纱} */
    static final String BANDING_SHEER = "纱绑带";

    /**
     * 派生族登记表：语义名 ⇒ 该族的派生键。
     *
     * <p>新增第二族时**只加一行**（前端 {@code SPECIAL_OPTION_FAMILIES}、
     * Python {@code routing.SPECIAL_OPTION_FAMILIES} 同步），不要另抄一套判定。</p>
     */
    private static final Map<String, List<String>> FAMILIES = Map.of(
            TAKE_AWAY_BASE, List.of(TAKE_AWAY_FABRIC, TAKE_AWAY_SHEER),
            BANDING_BASE, List.of(BANDING_FABRIC, BANDING_SHEER));

    /**
     * 「客户带走余料」**只**属于这一族。
     *
     * <p>族机制是通用容器（#8007 立、#8108 复用），但「客户带走余料」是<b>业务含义</b>：它决定余料
     * 落 {@code customer_taken}、不进可用池、不可回收 / 不可报废。若按「任一族成员」判定，
     * 勾绑带的单会被误判成客户带走（= 静默的账错，且没有任何东西会变红）。</p>
     */
    private static final String CUSTOMER_TAKE_AWAY_FAMILY = TAKE_AWAY_BASE;

    private OptionFamilyNames() {
    }

    /** 该名字是否属于某个布/纱派生族（语义名或任一派生键） */
    static boolean isFamilyName(String name) {
        if (name == null) {
            return false;
        }
        for (Map.Entry<String, List<String>> family : FAMILIES.entrySet()) {
            if (family.getKey().equals(name) || family.getValue().contains(name)) {
                return true;
            }
        }
        return false;
    }

    /**
     * 订单侧选项列表是否含「客户带走余料」（语义名或两种派生键都认）。
     *
     * <p>为什么读侧要兼容语义名：语义名是**展示 / 录入口径**，而 AI Agent 与其他写入口
     * 可能原样写入客户说的「余料带回」—— 只认派生键会让这类单的余料**误入可用池**
     * （该归客户的东西被回收），是静默的账错。历史数据里的派生键照旧命中。</p>
     *
     * <p>🔴 <b>只认 {@code 余料带回} 族</b>（issue #8108）：{@code 绑带} 族等其它派生族是车间工序
     * 语义 ⇒ 勾它们<b>不是</b>「客户带走余料」。判据 = {@code OptionFamilyNamesTest} 的
     * {@code customerTakeAwayIsScopedToTheLeftoverFamilyOnly}（含正向对照，防「恒 false」空断言）。</p>
     */
    static boolean isCustomerTakeAway(List<String> options) {
        if (options == null) {
            return false;
        }
        List<String> variants = FAMILIES.get(CUSTOMER_TAKE_AWAY_FAMILY);
        return options.stream().anyMatch(
                name -> CUSTOMER_TAKE_AWAY_FAMILY.equals(name) || variants.contains(name));
    }

    /**
     * 规则侧取值是否命中订单侧取值（{@code CuttingHeightCalculator} 的 {@code option} 条件）。
     *
     * <ul>
     *   <li>逐字相等 ⇒ 命中（<b>既有口径一字不动</b>，派生键规则只命中同名订单值）；</li>
     *   <li>规则值 = <b>语义名</b> ⇒ 命中该族任一派生键（配置面只写语义名，匹配时按族展开）；</li>
     *   <li>其余 ⇒ 不命中（fail-closed，不把「加立边」这类独立选项名当族成员）。</li>
     * </ul>
     */
    static boolean ruleValueMatches(String ruleValue, String orderValue) {
        if (ruleValue == null || orderValue == null) {
            return false;
        }
        if (ruleValue.equals(orderValue)) {
            return true;
        }
        List<String> derived = FAMILIES.get(ruleValue);
        return derived != null && derived.contains(orderValue);
    }
}
