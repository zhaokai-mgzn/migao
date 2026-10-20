// case_ids: SP-002
package com.migao.admin.service;

import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.InboundOrderMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 入库单 → 供应商档案的引用解析（issue #7369 段 2）—— **用户 2026-10-20 裁定的 A 口径**。
 *
 * <p>口径逐字：「按名称**精确匹配**自动填 `supplier_id`，匹配不上的留 NULL 并出一张「待指派」清单，
 * **不改任何历史字段值**」。本判据守的就是这条口径的**三条分支**，尤其是「不猜」那一支：
 * 同名多家必须留 NULL —— 猜一家等于把两家的账并成一家，**不可逆**。</p>
 *
 * <p>红证方向：把「同名多家」那一支改成取第一条 ⇒ {@link #ambiguousNameIsLeftUnassigned} 当场红。</p>
 */
@ExtendWith(MockitoExtension.class)
class InboundOrderSupplierLinkTest {

    private static final Long TENANT = 2001L;

    @Mock
    private InboundOrderMapper inboundOrderMapper;

    @InjectMocks
    private InboundOrderService inboundOrderService;

    @Test
    @DisplayName("A 口径①：显式指定在用档案 ⇒ 原样采用（不去按名字猜）")
    void explicitActiveSupplierIsUsedAsIs() {
        when(inboundOrderMapper.selectSupplierStatusInTenant(TENANT, "sup-1")).thenReturn("active");

        assertThat(inboundOrderService.resolveSupplierId(TENANT, "sup-1", "某某布行"))
                .isEqualTo("sup-1");
        verify(inboundOrderMapper, never()).selectSupplierIdsByExactName(anyLong(), anyString());
    }

    @Test
    @DisplayName("A 口径①：跨租户/不存在的档案 ⇒ 422（当「不存在」处理，不泄露对方存在性）")
    void explicitForeignSupplierIsRejected() {
        when(inboundOrderMapper.selectSupplierStatusInTenant(TENANT, "sup-other")).thenReturn(null);

        assertThatThrownBy(() -> inboundOrderService.resolveSupplierId(TENANT, "sup-other", null))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("供应商档案不存在");
    }

    @Test
    @DisplayName("A 口径①：停用档案 ⇒ 422 并给出可行动出口（去「供应商」页启用）")
    void explicitInactiveSupplierIsRejected() {
        when(inboundOrderMapper.selectSupplierStatusInTenant(TENANT, "sup-off")).thenReturn("inactive");

        assertThatThrownBy(() -> inboundOrderService.resolveSupplierId(TENANT, "sup-off", null))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("已停用");
    }

    @Test
    @DisplayName("A 口径②：没给 id、文本精确匹配到唯一一家 ⇒ 自动补上")
    void uniqueExactNameIsAutoLinked() {
        when(inboundOrderMapper.selectSupplierIdsByExactName(TENANT, "杭州染整一厂"))
                .thenReturn(List.of("sup-1"));

        assertThat(inboundOrderService.resolveSupplierId(TENANT, null, "杭州染整一厂"))
                .isEqualTo("sup-1");
    }

    @Test
    @DisplayName("A 口径③：同名多家 = 歧义 ⇒ 留 NULL（**不猜**：猜错不可逆）")
    void ambiguousNameIsLeftUnassigned() {
        when(inboundOrderMapper.selectSupplierIdsByExactName(TENANT, "宏达布行"))
                .thenReturn(List.of("sup-a", "sup-b"));

        assertThat(inboundOrderService.resolveSupplierId(TENANT, null, "宏达布行")).isNull();
    }

    @Test
    @DisplayName("A 口径③：匹配不上 / 没有文本 ⇒ 留 NULL（进「待指派」清单）")
    void unmatchedNameIsLeftUnassigned() {
        when(inboundOrderMapper.selectSupplierIdsByExactName(TENANT, "没建过档的厂"))
                .thenReturn(List.of());

        assertThat(inboundOrderService.resolveSupplierId(TENANT, null, "没建过档的厂")).isNull();
        assertThat(inboundOrderService.resolveSupplierId(TENANT, null, null)).isNull();
        verify(inboundOrderMapper, never()).selectSupplierStatusInTenant(any(), any());
    }
}
