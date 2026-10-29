// case_ids: PG-045, PR-098
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 布/纱派生族的名称口径（issue #8007 立机制；issue #8108 接入「绑带」族）—— 纯判定，不连库。
 *
 * <p>判据（每条都能红）：</p>
 * <ol>
 *   <li>🔴 <b>客户带走只认「余料带回」族</b>：语义名与两种派生键都认；而<b>勾绑带的单不得</b>被判成
 *       客户带走余料（红证 = 退回「任一族成员」判定 ⇒ 绑带那条红 —— 余料会落 {@code customer_taken}、
 *       不进可用池、不可回收/报废，是静默的账错）；</li>
 *   <li><b>规则匹配按族单向展开</b>：规则写语义名 ⇒ 命中任一派生键；规则写派生键 ⇒ 只命中同名
 *       （布帘规则不得命中纱帘单）；不跨族（{@code 绑带} 规则不得命中 {@code 余料带回-布}）；</li>
 *   <li><b>非族名不折叠</b>：{@code 加立边} / {@code 加logo条} 是两个<b>独立</b>选项名（各自对应独立
 *       工序与计件口径），不得被当成「同一语义的材料变体」—— 否则改名的炮口会误伤工资 key。</li>
 * </ol>
 */
@DisplayName("特殊选项布/纱派生族（issue #8007 / #8108）")
class OptionFamilyNamesTest {

    @Test
    @DisplayName("🔴 客户带走：语义名与两种派生键都算（红证：只认派生键 ⇒ 语义名那条红）")
    void customerTakeAwayAcceptsSemanticNameAndBothDerivedKeys() {
        assertThat(OptionFamilyNames.isCustomerTakeAway(List.of("余料带回"))).isTrue();
        assertThat(OptionFamilyNames.isCustomerTakeAway(List.of("余料带回-布"))).isTrue();
        assertThat(OptionFamilyNames.isCustomerTakeAway(List.of("余料带回-纱"))).isTrue();
        // 同一行里混着别的选项也要认出来
        assertThat(OptionFamilyNames.isCustomerTakeAway(List.of("加铅块", "拼1次", "余料带回"))).isTrue();
        // 别的选项名不得被误判成「客户带走」
        assertThat(OptionFamilyNames.isCustomerTakeAway(List.of("加铅块", "拼1次"))).isFalse();
        assertThat(OptionFamilyNames.isCustomerTakeAway(List.of())).isFalse();
        assertThat(OptionFamilyNames.isCustomerTakeAway(null)).isFalse();
    }

    @Test
    @DisplayName("🔴 issue #8108：勾绑带 ≠ 客户带走余料（红证：任一族成员判定 ⇒ 前四条红）")
    void customerTakeAwayIsScopedToTheLeftoverFamilyOnly() {
        // 「布/纱派生族」是**通用容器**，但「客户带走余料」只属于「余料带回」这一族的业务含义
        assertThat(OptionFamilyNames.isCustomerTakeAway(List.of("布绑带")))
                .as("勾布绑带 ⇒ 余料照常进可用池（不是客户的）").isFalse();
        assertThat(OptionFamilyNames.isCustomerTakeAway(List.of("纱绑带"))).isFalse();
        assertThat(OptionFamilyNames.isCustomerTakeAway(List.of("绑带")))
                .as("语义名同理：`绑带` 不属「余料带回」族").isFalse();
        assertThat(OptionFamilyNames.isCustomerTakeAway(List.of("布绑带", "余料做绑带"))).isFalse();
        // 正控（同一断言里给出「会判 true」的对照，防「恒 false」的空断言）
        assertThat(OptionFamilyNames.isCustomerTakeAway(List.of("布绑带", "余料带回-布"))).isTrue();
    }

    @Test
    @DisplayName("规则匹配：语义名按族展开；派生键只命中同名；非族名逐字")
    void ruleValueMatchesExpandsOnlySemanticNames() {
        // 配置面唯一可选值 = 语义名 ⇒ 布帘单 / 纱帘单都命中
        assertThat(OptionFamilyNames.ruleValueMatches("余料带回", "余料带回-布")).isTrue();
        assertThat(OptionFamilyNames.ruleValueMatches("余料带回", "余料带回-纱")).isTrue();
        assertThat(OptionFamilyNames.ruleValueMatches("余料带回", "余料带回")).isTrue();
        // 派生键规则**只**命中同名（布帘规则不得命中纱帘单）
        assertThat(OptionFamilyNames.ruleValueMatches("余料带回-布", "余料带回-布")).isTrue();
        assertThat(OptionFamilyNames.ruleValueMatches("余料带回-布", "余料带回-纱")).isFalse();
        // 反向不展开：派生键不是「全族」的别名，也不得凭空命中别的选项
        assertThat(OptionFamilyNames.ruleValueMatches("余料带回", "加立边")).isFalse();
        assertThat(OptionFamilyNames.ruleValueMatches("加立边", "余料带回-布")).isFalse();
    }

    @Test
    @DisplayName("🔴 issue #8108：绑带族的族匹配 —— 语义名展开两键，派生键不跨材料命中")
    void bandingFamilyMatchesLikeTheLeftoverFamily() {
        assertThat(OptionFamilyNames.ruleValueMatches("绑带", "布绑带")).isTrue();
        assertThat(OptionFamilyNames.ruleValueMatches("绑带", "纱绑带")).isTrue();
        assertThat(OptionFamilyNames.ruleValueMatches("绑带", "绑带")).isTrue();
        // 不跨材料：`布绑带` 规则只命中布帘单（红证：两侧都折叠成语义名 ⇒ 下面这条红）
        assertThat(OptionFamilyNames.ruleValueMatches("布绑带", "布绑带")).isTrue();
        assertThat(OptionFamilyNames.ruleValueMatches("布绑带", "纱绑带")).isFalse();
        // 不跨族：两个族的字面量不得互相命中
        assertThat(OptionFamilyNames.ruleValueMatches("绑带", "余料带回-布")).isFalse();
        assertThat(OptionFamilyNames.ruleValueMatches("余料带回", "布绑带")).isFalse();
    }

    @Test
    @DisplayName("非族名不折叠：加立边 / 加logo条 是独立选项名（不属任何布/纱族）")
    void independentOptionNamesAreNotFamilyMembers() {
        assertThat(OptionFamilyNames.isFamilyName("加立边")).isFalse();
        assertThat(OptionFamilyNames.isFamilyName("加logo条")).isFalse();
        // 名字里含「绑带」字样但**不是**族成员（自己的工序，不跟随帘种）
        assertThat(OptionFamilyNames.isFamilyName("余料做绑带")).isFalse();
        assertThat(OptionFamilyNames.ruleValueMatches("加立边", "加logo条")).isFalse();
        // 族成员（两族同口径）
        assertThat(OptionFamilyNames.isFamilyName("余料带回")).isTrue();
        assertThat(OptionFamilyNames.isFamilyName("余料带回-布")).isTrue();
        assertThat(OptionFamilyNames.isFamilyName("绑带")).isTrue();
        assertThat(OptionFamilyNames.isFamilyName("布绑带")).isTrue();
        assertThat(OptionFamilyNames.isFamilyName("纱绑带")).isTrue();
    }
}
