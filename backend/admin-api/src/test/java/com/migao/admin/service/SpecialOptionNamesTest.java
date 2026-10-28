// case_ids: PG-045, PR-098
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 布/纱派生族的名称口径（issue #8007，用户 2026-10-28 裁定）—— 纯判定，不连库。
 *
 * <p>判据（每条都能红）：</p>
 * <ol>
 *   <li><b>客户带走认语义名 + 两种派生键</b>：红证 = 退回「逐字 contains 两个派生键」⇒
 *       语义名那条红（AI Agent / 其他写入口原样写入客户说的「余料带回」就会被漏判，
 *       该归客户的余料误入可用池）；</li>
 *   <li><b>规则匹配按族单向展开</b>：规则写语义名 ⇒ 命中任一派生键；规则写派生键 ⇒ 只命中同名
 *       （布帘规则不得命中纱帘单）。红证 = 两侧都折叠成语义名 ⇒ 最后一条红；</li>
 *   <li><b>非族名不折叠</b>：{@code 布绑带} / {@code 纱绑带} 是两个**独立**选项名（各自对应独立工序
 *       与计件口径），不得被当成「同一语义的材料变体」—— 否则改名的炮口会误伤工资 key。</li>
 * </ol>
 */
@DisplayName("特殊选项布/纱派生族（issue #8007）")
class SpecialOptionNamesTest {

    @Test
    @DisplayName("🔴 客户带走：语义名与两种派生键都算（红证：只认派生键 ⇒ 语义名那条红）")
    void customerTakeAwayAcceptsSemanticNameAndBothDerivedKeys() {
        assertThat(SpecialOptionNames.isCustomerTakeAway(List.of("余料带回"))).isTrue();
        assertThat(SpecialOptionNames.isCustomerTakeAway(List.of("余料带回-布"))).isTrue();
        assertThat(SpecialOptionNames.isCustomerTakeAway(List.of("余料带回-纱"))).isTrue();
        // 同一行里混着别的选项也要认出来
        assertThat(SpecialOptionNames.isCustomerTakeAway(List.of("加铅块", "拼1次", "余料带回"))).isTrue();
        // 别的选项名不得被误判成「客户带走」
        assertThat(SpecialOptionNames.isCustomerTakeAway(List.of("加铅块", "拼1次"))).isFalse();
        assertThat(SpecialOptionNames.isCustomerTakeAway(List.of())).isFalse();
        assertThat(SpecialOptionNames.isCustomerTakeAway(null)).isFalse();
    }

    @Test
    @DisplayName("规则匹配：语义名按族展开；派生键只命中同名；非族名逐字")
    void ruleValueMatchesExpandsOnlySemanticNames() {
        // 配置面唯一可选值 = 语义名 ⇒ 布帘单 / 纱帘单都命中
        assertThat(SpecialOptionNames.ruleValueMatches("余料带回", "余料带回-布")).isTrue();
        assertThat(SpecialOptionNames.ruleValueMatches("余料带回", "余料带回-纱")).isTrue();
        assertThat(SpecialOptionNames.ruleValueMatches("余料带回", "余料带回")).isTrue();
        // 派生键规则**只**命中同名（布帘规则不得命中纱帘单）
        assertThat(SpecialOptionNames.ruleValueMatches("余料带回-布", "余料带回-布")).isTrue();
        assertThat(SpecialOptionNames.ruleValueMatches("余料带回-布", "余料带回-纱")).isFalse();
        // 反向不展开：派生键不是「全族」的别名，也不得凭空命中别的选项
        assertThat(SpecialOptionNames.ruleValueMatches("余料带回", "加立边")).isFalse();
        assertThat(SpecialOptionNames.ruleValueMatches("加立边", "余料带回-布")).isFalse();
    }

    @Test
    @DisplayName("非族名不折叠：布绑带 / 纱绑带 是独立选项名（不属任何布/纱族）")
    void independentOptionNamesAreNotFamilyMembers() {
        assertThat(SpecialOptionNames.isFamilyName("布绑带")).isFalse();
        assertThat(SpecialOptionNames.isFamilyName("纱绑带")).isFalse();
        assertThat(SpecialOptionNames.ruleValueMatches("布绑带", "纱绑带")).isFalse();
        assertThat(SpecialOptionNames.isFamilyName("余料带回-布")).isTrue();
        assertThat(SpecialOptionNames.isFamilyName("余料带回")).isTrue();
    }
}
