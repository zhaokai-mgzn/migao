// case_ids: PG-018
package com.migao.admin.service;

import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.mapper.ProcessingOrderMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 加工单级公开短链的**解析层**（issue #6867 / 实现包 B2；设计
 * {@code docs/design/worker-h5-scan-and-report.md} §11.3 / §11.6）。
 *
 * <h2>它钉什么</h2>
 * <ul>
 *   <li><b>形态判定在查库之前</b>：长度 ≠ 8 / 含字符集外字符 / 空白 ⇒ {@code null}，
 *       且**一次库都不查**（形态不合法不该产生任何 DB 访存）；</li>
 *   <li><b>归一化只有一份</b>：复用 {@code WorkerShortLinkService.normalize}（小写 / {@code O→0} /
 *       {@code I,L→1}）⇒ 查库入参是**归一化后**的短码（DB 里存的是大写 Crockford；第二份归一化
 *       会让手抄形态在两条入口上表现不一致）；</li>
 *   <li><b>命中行原样返回</b>（{@code qr_token} 为 {@code NULL} 的行**也要**能读出来 ——
 *       否则「已撤销」会被静默说成「没这个码」，410 永远出不来）；</li>
 *   <li><b>跨租户解析是刻意的</b>：只走 {@code selectByShortCodeGlobal}，**不**走带租户谓词的
 *       {@code selectByShortCode(shortCode, tenantId)}（公开入口没有租户上下文）。</li>
 * </ul>
 *
 * <h2>它不钉什么（如实登记）</h2>
 * 真库上的租户拦截器行为（{@code TenantContext} 为空时 {@code @InterceptorIgnore} 是否真的兜住）
 * 需要真 PG 集群，不在本类射程；注解本身的形态由
 * {@code ProcessingOrderShortCodeMapperTest#selectByShortCodeGlobalIsCrossTenantOnPurpose} 钉。
 */
@DisplayName("ProcessingOrderShortLinkService（/o/{短码} 的解析层，issue #6867 / B2）")
class ProcessingOrderShortLinkServiceTest {

    private static final String SHORT_CODE = "7K3M9QP2";

    @Test
    @DisplayName("形态不合法（长度 ≠ 8 / 字符集外 / 空白）⇒ null，且**一次库都不查**")
    void malformedCodesAreRejectedWithoutQueryingTheDb() {
        ProcessingOrderMapper mapper = mock(ProcessingOrderMapper.class);
        ProcessingOrderShortLinkService service = new ProcessingOrderShortLinkService(mapper);

        List<String> malformedCodes =
                List.of("", "   ", "TOO-SHORT", "7K3M9QP", "7K3M9QP2X", "7K3M9QP-", "ABCDEFGU");
        for (String malformed : malformedCodes) {
            assertThat(service.resolve(malformed))
                    .as("形态不合法必须返回 null：%s", malformed)
                    .isNull();
        }
        verify(mapper, never()).selectByShortCodeGlobal(anyString());
        verify(mapper, never()).selectByShortCode(anyString(), anyLong());
    }

    @Test
    @DisplayName("手抄形态归一化后查库：小写 / O→0 / I,L→1（查库入参是被归一化的短码）")
    void handwrittenCodesAreNormalizedBeforeQuerying() {
        ProcessingOrderMapper mapper = mock(ProcessingOrderMapper.class);
        when(mapper.selectByShortCodeGlobal("7K3M9QP0"))
                .thenReturn(ProcessingOrder.builder().id("po-1").tenantId(7L).shortCode("7K3M9QP0").build());

        assertThat(new ProcessingOrderShortLinkService(mapper).resolve("7k3m9qpo").getShortCode())
                .isEqualTo("7K3M9QP0");

        ArgumentCaptor<String> queried = ArgumentCaptor.forClass(String.class);
        verify(mapper).selectByShortCodeGlobal(queried.capture());
        assertThat(queried.getValue())
                .as("查库必须用归一化后的短码（DB 里存的是大写 Crockford；手抄别名在入口这一跳归一）")
                .isEqualTo("7K3M9QP0");
    }

    @Test
    @DisplayName("命中且 qr_token 为空（已撤销）⇒ 原样返回那一行（404 与 410 由控制器分）")
    void revokedRowIsReturnedVerbatim() {
        ProcessingOrderMapper mapper = mock(ProcessingOrderMapper.class);
        ProcessingOrder revoked = ProcessingOrder.builder()
                .id("po-1").tenantId(7L).shortCode(SHORT_CODE).build();
        when(mapper.selectByShortCodeGlobal(SHORT_CODE)).thenReturn(revoked);

        assertThat(new ProcessingOrderShortLinkService(mapper).resolve(SHORT_CODE)).isSameAs(revoked);
        assertThat(revoked.getQrToken())
                .as("qr_token 为 NULL 的行必须能被读出来，否则「已撤销」会被说成「没这个码」")
                .isNull();
    }

    @Test
    @DisplayName("未知短码 ⇒ null（不造值、不回落任何既有形态）")
    void unknownCodeIsNull() {
        ProcessingOrderMapper mapper = mock(ProcessingOrderMapper.class);
        when(mapper.selectByShortCodeGlobal(SHORT_CODE)).thenReturn(null);

        assertThat(new ProcessingOrderShortLinkService(mapper).resolve(SHORT_CODE)).isNull();
    }

    @Test
    @DisplayName("🔴 跨租户解析是刻意的：只走 selectByShortCodeGlobal，不走带租户谓词的那个")
    void resolutionIsCrossTenantOnPurpose() {
        ProcessingOrderMapper mapper = mock(ProcessingOrderMapper.class);
        when(mapper.selectByShortCodeGlobal(SHORT_CODE))
                .thenReturn(ProcessingOrder.builder().id("po-1").tenantId(7L).shortCode(SHORT_CODE).build());

        new ProcessingOrderShortLinkService(mapper).resolve(SHORT_CODE);

        verify(mapper).selectByShortCodeGlobal(SHORT_CODE);
        verify(mapper, never()).selectByShortCode(anyString(), anyLong());
    }
}
