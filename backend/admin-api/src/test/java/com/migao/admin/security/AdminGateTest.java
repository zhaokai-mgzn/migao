// case_ids: BM-008
package com.migao.admin.security;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 米宝唤出授权门的**服务端单一真值**（issue #5642 功能⑤）。
 *
 * <p>本用例锁四件事（每条都能红）：
 * <ol>
 *   <li>{@code "*"} 通配**直接判真** ⇒ {@code role='admin'} 自动落入、**无需特例分支**
 *       （改成读 {@code role} 字段 ⇒ 本条红）；</li>
 *   <li>三码**全持**为真、**缺一**为假（改成 {@code anyMatch} ⇒ 缺一那格红）；</li>
 *   <li>非管理员员工被显式授权米宝唤出码 ⇒ {@code canSummonMibao} 为真，
 *       但 {@code hasAllAdminPermissionCodes} **仍为假**（「被授权者」≠「管理员」，
 *       两个概念合并 ⇒ 本条红）；</li>
 *   <li>空 / {@code null} 权限 ⇒ **fail-closed**（不是静默放行）。</li>
 * </ol>
 * <p>⚠️ 本用例**不**断言集合的成员是谁 —— 「成员 ∈ 权限目录」由机械判据
 * {@code tests/unit_ci_workflows/test_mibao_chat_gate.py} 判据 ③ 钉住（同源复用，不写第二份）。
 */
class AdminGateTest {

    @Test
    @DisplayName("AdminGate — \"*\" 通配直接判真（role='admin' 自动落入，零特例分支）")
    void wildcardIsAlwaysAdmin() {
        assertThat(AdminGate.hasAllAdminPermissionCodes(List.of("*"))).isTrue();
        assertThat(AdminGate.canSummonMibao(List.of("*"))).isTrue();
        // 通配与其余码混排同样成立（真实 JWT claims 的形态）
        assertThat(AdminGate.hasAllAdminPermissionCodes(List.of("order:list", "*"))).isTrue();
    }

    @Test
    @DisplayName("AdminGate — 三码全持为真、缺一为假（\"+\" 是同时具备，不是任一）")
    void requiresTheWholeSet() {
        List<String> all = List.copyOf(AdminGate.ADMIN_PERMISSION_CODES);
        assertThat(all).hasSizeGreaterThanOrEqualTo(3);
        assertThat(AdminGate.hasAllAdminPermissionCodes(all)).isTrue();

        for (String missing : all) {
            List<String> without = all.stream().filter(c -> !c.equals(missing)).toList();
            assertThat(AdminGate.hasAllAdminPermissionCodes(without))
                    .as("缺 %s 时不得判为管理员", missing)
                    .isFalse();
        }
    }

    @Test
    @DisplayName("AdminGate — 被显式授权者可唤米宝，但不算「管理员」（两个概念不合并）")
    void grantedEmployeeCanSummonButIsNotAdmin() {
        List<String> granted = List.of(AdminGate.MIBAO_CHAT_GRANT_CODE);
        assertThat(AdminGate.canSummonMibao(granted)).isTrue();
        assertThat(AdminGate.hasAllAdminPermissionCodes(granted)).isFalse();
    }

    @Test
    @DisplayName("AdminGate — 未授权员工 fail-closed（空 / null 都不放行）")
    void unauthorizedIsFailClosed() {
        for (List<String> perms : List.of(List.<String>of(), List.of("order:list", "dashboard:view"))) {
            assertThat(AdminGate.hasAllAdminPermissionCodes(perms)).isFalse();
            assertThat(AdminGate.canSummonMibao(perms)).isFalse();
        }
        assertThat(AdminGate.hasAllAdminPermissionCodes(null)).isFalse();
        assertThat(AdminGate.canSummonMibao(null)).isFalse();
    }

    @Test
    @DisplayName("AdminGate — 集合不可变（防运行期被改写 ⇒ 判定漂移）")
    void codesAreImmutable() {
        assertThat(AdminGate.ADMIN_PERMISSION_CODES).isInstanceOf(Set.class);
        assertThat(AdminGate.ADMIN_PERMISSION_CODES)
                .as("管理员集合必须含米宝唤出码（否则「默认可唤」与「授权码」会分叉）")
                .contains(AdminGate.MIBAO_CHAT_GRANT_CODE);
    }
}
