// case_ids: PG-018, BM-006
package com.migao.admin.service;

import com.migao.admin.entity.ProcessingSetPartToken;
import com.migao.admin.mapper.ProcessingSetPartTokenMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.util.HashSet;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 稳定短链的**短码口径**（issue #4802；设计 {@code docs/design/worker-h5-scan-and-report.md} §1.3 / §1.4）。
 *
 * <p>本类钉四件事（每件都有**反向**断言，防「判据恒真」）：</p>
 * <ol>
 *   <li><b>人可读</b>：8 位 + 字符集 ⊆ Crockford Base32（**去掉 {@code I/L/O/U}**）
 *       —— 易混对 {@code O/0} 与 {@code I/L/1} 在生成面不可能同时出现；</li>
 *   <li><b>随机</b>（不是顺序号）：多次生成**不是一个常数**，且覆盖到字符集里的多个字符
 *       （只断言「长度 = 8」的话，一个恒返回 {@code "AAAAAAAA"} 的实现也能过）；</li>
 *   <li><b>手输归一化</b>：小写 / 空白 / Crockford 解码别名（{@code O→0}、{@code I/L→1}）
 *       ⇒ 抄错的那一个还能用；形态不合法（长度 ≠ 8、含 {@code U} 等字符集外字符）⇒ 空串（调用方 404）；</li>
 *   <li><b>碰撞重试 / 不静默造重码</b>：查重命中 ⇒ 换一个；连续命中到上限 ⇒ 显式抛错
 *       （**不得**返回一个已占用的短码）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("稳定短链短码：人可读 / 随机 / 归一化 / 碰撞重试（issue #4802）")
class WorkerShortLinkServiceTest {

    @Mock
    private ProcessingSetPartTokenMapper setPartTokenMapper;

    private WorkerShortLinkService service() {
        return new WorkerShortLinkService(setPartTokenMapper);
    }

    // ────────────────────────────────────────────── ① 人可读（字符集）

    @Test
    @DisplayName("短码 = 8 位，且字符集 ⊆ Crockford Base32（去掉 I/L/O/U）—— 千次生成零例外")
    void shortCodeIsHumanReadable() {
        assertThat(WorkerShortLinkService.CODE_LENGTH).isEqualTo(8);
        assertThat(WorkerShortLinkService.ALPHABET).hasSize(32);
        for (char confusing : new char[]{'I', 'L', 'O', 'U'}) {
            assertThat(WorkerShortLinkService.ALPHABET)
                    .as("易混字符 %s 不得出现在字符集里（设计 §1.4 逐字）", confusing)
                    .doesNotContain(String.valueOf(confusing));
        }
        for (int i = 0; i < 1000; i++) {
            String code = WorkerShortLinkService.randomCode();
            assertThat(code).hasSize(8);
            for (int j = 0; j < code.length(); j++) {
                assertThat(WorkerShortLinkService.ALPHABET.indexOf(code.charAt(j)))
                        .as("短码 %s 含字符集外字符 %s", code, code.charAt(j))
                        .isGreaterThanOrEqualTo(0);
            }
        }
    }

    @Test
    @DisplayName("短码是**随机**的（不是顺序号/常数）—— 1000 次生成既不全同、也不止用到 1 个字符")
    void shortCodeIsRandomNotSequential() {
        Set<String> codes = new HashSet<>();
        Set<Character> chars = new HashSet<>();
        for (int i = 0; i < 1000; i++) {
            String code = WorkerShortLinkService.randomCode();
            codes.add(code);
            for (char c : code.toCharArray()) {
                chars.add(c);
            }
        }
        // 反向：一个「恒返回同一个 8 位串」的实现会让下面两条必红
        assertThat(codes).as("1000 次生成必须产生多个不同短码（顺序号/常数即失败）").hasSizeGreaterThan(900);
        assertThat(chars).as("字符集覆盖必须够宽（否则等于可枚举）").hasSizeGreaterThan(25);
    }

    // ────────────────────────────────────────────── ② 手输归一化

    @Test
    @DisplayName("手输归一化：小写 / 空白 / Crockford 别名 O→0、I/L→1 都能换回 token")
    void normalizeAcceptsHumanTypedForms() {
        assertThat(WorkerShortLinkService.normalize("  7k3m9qp2 ")).isEqualTo("7K3M9QP2");
        // 抄错形态：0 抄成 O、1 抄成 I / L —— 生成面从不产出 O/I/L ⇒ 不会造成歧义
        assertThat(WorkerShortLinkService.normalize("7K3M9QPO")).isEqualTo("7K3M9QP0");
        assertThat(WorkerShortLinkService.normalize("7K3M9QP1")).isEqualTo("7K3M9QP1");
        assertThat(WorkerShortLinkService.normalize("7K3M9QPI")).isEqualTo("7K3M9QP1");
        assertThat(WorkerShortLinkService.normalize("7K3M9QPL")).isEqualTo("7K3M9QP1");
    }

    @Test
    @DisplayName("形态不合法 ⇒ 空串（长度 ≠ 8 / 含字符集外字符 U / 空）—— 调用方据此 404，不猜")
    void normalizeRejectsMalformedInput() {
        assertThat(WorkerShortLinkService.normalize("7K3M9QP")).isEmpty();          // 7 位
        assertThat(WorkerShortLinkService.normalize("7K3M9QP2X")).isEmpty();        // 9 位
        assertThat(WorkerShortLinkService.normalize("7K3M9QPU")).isEmpty();         // U 不在字符集
        assertThat(WorkerShortLinkService.normalize("7K3M9QP-")).isEmpty();
        assertThat(WorkerShortLinkService.normalize("")).isEmpty();
        assertThat(WorkerShortLinkService.normalize("   ")).isEmpty();
        assertThat(WorkerShortLinkService.normalize(null)).isEmpty();
        // 长 token（32 位）**不是**短码 ⇒ 在 /s/ 这条路径上判 404（冻结契约未被扩：见控制器测试）
        assertThat(WorkerShortLinkService.normalize("9f8e7d6c5b4a39281706f5e4d3c2b1a0")).isEmpty();
    }

    // ────────────────────────────────────────────── ③ 短码 ⇒ token

    @Test
    @DisplayName("短码 ⇒ 承载行（归一化后查库）；未知短码 ⇒ null，且**不**拿未归一化的原文去查")
    void resolveLooksUpNormalizedCode() {
        ProcessingSetPartToken zero = ProcessingSetPartToken.builder()
                .id("t-0").tenantId(7L).token("9f8e7d6c5b4a39281706f5e4d3c2b1a0")
                .shortCode("7K3M9QP0").deleted(0).build();
        ProcessingSetPartToken one = ProcessingSetPartToken.builder()
                .id("t-1").tenantId(7L).token("a".repeat(32))
                .shortCode("7K3M9QP1").deleted(0).build();
        when(setPartTokenMapper.selectByShortCode("7K3M9QP0")).thenReturn(zero);
        when(setPartTokenMapper.selectByShortCode("7K3M9QP1")).thenReturn(one);

        assertThat(service().resolve("7k3m9qp0")).as("小写形态").isSameAs(zero);
        assertThat(service().resolve("7K3M9QP0")).isSameAs(zero);
        // 抄错形态：0 抄成 O、1 抄成 I / L —— 生成面从不产出 O/I/L ⇒ 不会造成歧义
        assertThat(service().resolve("7K3M9QPO")).as("O 是 0 的抄错形态").isSameAs(zero);
        assertThat(service().resolve("7K3M9QPI")).as("I 是 1 的抄错形态").isSameAs(one);
        assertThat(service().resolve("7K3M9QPL")).as("L 是 1 的抄错形态").isSameAs(one);
    }

    @Test
    @DisplayName("未知/形态不合法的短码 ⇒ null 且**一次库都不查**（不把任意输入当短码去扫）")
    void resolveReturnsNullWithoutQueryingForMalformedInput() {
        assertThat(service().resolve("NOPE")).isNull();
        assertThat(service().resolve("")).isNull();
        assertThat(service().resolve(null)).isNull();
        verify(setPartTokenMapper, never()).selectByShortCode(anyString());
    }

    // ────────────────────────────────────────────── ④ 分配（碰撞重试）

    @Test
    @DisplayName("分配：先查重 ⇒ 返回未被占用的短码（第一次就空闲时只查一次）")
    void allocateReturnsFreeCode() {
        when(setPartTokenMapper.selectByShortCode(anyString())).thenReturn(null);

        String code = WorkerShortLinkService.allocateUnique(setPartTokenMapper);

        assertThat(code).hasSize(8);
        assertThat(WorkerShortLinkService.ALPHABET).contains(code.substring(0, 1));
    }

    @Test
    @DisplayName("🔴 连续碰撞到上限 ⇒ 显式抛错（**不得**返回一个已占用的短码 = 静默造重码）")
    void allocateFailsClosedOnRepeatedCollision() {
        when(setPartTokenMapper.selectByShortCode(anyString())).thenReturn(
                ProcessingSetPartToken.builder().id("occupied").shortCode("XXXXXXXX").build());

        assertThatThrownBy(() -> WorkerShortLinkService.allocateUnique(setPartTokenMapper))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("拒绝静默造重码");
    }

    // ────────────────────────────────────────────── ⑤ 302 目标形态（页面契约）

    @Test
    @DisplayName("302 目标 = 报工页 + token + 租户（相对 Location，不带请求 Host ⇒ 无开放重定向面）")
    void reportPageLocationShape() {
        assertThat(WorkerShortLinkService.reportPageLocation("9f8e7d6c5b4a39281706f5e4d3c2b1a0", 7L))
                .isEqualTo("/w/?t=9f8e7d6c5b4a39281706f5e4d3c2b1a0&tenant_id=7");
        assertThat(WorkerShortLinkService.reportPageLocation("abc", null)).isEqualTo("/w/?t=abc");
        assertThat(WorkerShortLinkService.reportPageLocation("abc", 7L))
                .as("必须**相对**（不以 http(s):// 或 // 开头）—— 否则就是拿请求 Host 拼绝对 URL")
                .startsWith("/w/")
                .doesNotStartWith("//")
                .doesNotContain("http");
    }
}
