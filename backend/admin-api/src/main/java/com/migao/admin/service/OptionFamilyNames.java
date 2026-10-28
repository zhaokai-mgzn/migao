package com.migao.admin.service;

import java.util.List;
import java.util.Map;

/**
 * 「布/纱派生族」的名称口径（issue #8007，用户 2026-10-28 裁定）—— 全系统唯一一份。
 *
 * <h2>用户口径（逐字）</h2>
 * 「特殊选项里的这两项要改，只需要展示<b>余料带回</b>即可，后面的 {@code -布} 和 {@code -纱}
 * 应该是默认<b>跟随订单套行的帘种</b>来决定的，这样语义更清晰」「这个规则要<b>适用于全系统</b>」。
 *
 * <h2>三条口径</h2>
 * <ol>
 *   <li><b>录入 / 展示只出现语义名</b>（{@code 余料带回}）—— 材料不是商家的选择题；</li>
 *   <li><b>落库键由明细行的帘种派生</b>：{@code 纱帘 ⇒ 余料带回-纱}，{@code 布帘 / 帘头 / 未指定 ⇒ 余料带回-布}；</li>
 *   <li><b>join key 词表一字不改</b>（历史数据、工序规则、计件口径不动）⇒ 本类是**读侧的兼容层**：
 *       语义名与两种派生键都认，且不会把「布」规则误命中到纱帘单。</li>
 * </ol>
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

    /**
     * 派生族登记表：语义名 ⇒ 该族的派生键。
     *
     * <p>新增第二族时**只加一行**（前端 {@code SPECIAL_OPTION_FAMILIES}、
     * Python {@code routing.SPECIAL_OPTION_FAMILIES} 同步），不要另抄一套判定。</p>
     */
    private static final Map<String, List<String>> FAMILIES =
            Map.of(TAKE_AWAY_BASE, List.of(TAKE_AWAY_FABRIC, TAKE_AWAY_SHEER));

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
     */
    static boolean isCustomerTakeAway(List<String> options) {
        return options != null && options.stream().anyMatch(OptionFamilyNames::isFamilyName);
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
