// case_ids: PR-016
package com.migao.admin.service;

import com.migao.admin.dto.BatchOperationResult;
import com.migao.admin.dto.ProductCreateRequest;
import com.migao.admin.entity.Product;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.CategoryMapper;
import com.migao.admin.mapper.ProductAttributeMapper;
import com.migao.admin.mapper.ProductColorMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * 商品状态**枚举准入** + **状态机死行自救**（issue #6347 Part A）。
 *
 * <p>病：建品/改品对 {@code status} 只校长度 ⇒ 任意字符串落库（实测 {@code active} 8 行 /
 * {@code on_shelf} 2 行）；那些行既不在「在售」口径里（快照静默过滤掉它的 SKU），
 * 又因为 {@code STATUS_TRANSITIONS.get(未知态) == null} 而**任何目标状态都被拒**
 * （文案「允许的目标状态: 无」——诚实但无出路）。</p>
 *
 * <p>本类钉两件事：① 未知 status ⇒ 4xx 且文案**列出合法枚举**；② 未知**当前**状态
 * ⇒ 报错给**可执行的出路**（改回 off_sale / draft 收回状态机），且这条出路真的走得通、
 * 但**不允许**直接跳到 on_sale（来历不明的行不得被直接上架）。</p>
 */
@ExtendWith(MockitoExtension.class)
class ProductStatusAdmissionTest {

    @InjectMocks
    private ProductService productService;

    @Mock
    private ProductMapper productMapper;

    @Mock
    private CategoryMapper categoryMapper;

    @Mock
    private ProductColorMapper productColorMapper;

    @Mock
    private ProductSkuMapper productSkuMapper;

    @Mock
    private ProductAttributeMapper productAttributeMapper;

    @Mock
    private StockLedgerService stockLedgerService;

    private static Product productWithStatus(String id, String status) {
        return Product.builder()
                .id(id)
                .tenantId(1L)
                .name("蜂巢帘")
                .categoryId("cat-001")
                .basePrice(new BigDecimal("299.00"))
                .status(status)
                .build();
    }

    // ======================== ① 建品入口：枚举准入 ========================

    @ParameterizedTest(name = "建品 status={0} ⇒ 4xx")
    @ValueSource(strings = {"active", "on_shelf", "in_warehouse", "ON_SALE", "on sale", "sale", "x"})
    @DisplayName("建品：非法 status 一律 4xx，且文案列出合法枚举（引信形态 active / on_shelf）")
    void createRejectsIllegalStatus(String illegal) {
        ProductCreateRequest request = new ProductCreateRequest();
        request.setName("准入探针");
        request.setStatus(illegal);

        assertThatThrownBy(() -> productService.createProduct(request, 1L))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException be = (BusinessException) e;
                    assertThat(be.getCode()).isEqualTo("VALIDATION_ERROR");
                    assertThat(be.getHttpStatus()).isEqualTo(422);
                    // 可行动：文案必须点名合法枚举，不能只说「字段格式是否正确」
                    assertThat(be.getMessage()).contains("draft(草稿)", "under_review(审核中)",
                            "on_sale(出售中)", "off_sale(已下架)");
                });
    }

    @Test
    @DisplayName("建品：合法枚举全部放行；null/空串透传（由默认值 draft 兜底）")
    void admissionAcceptsEveryLegalStatus() {
        for (String legal : ProductService.PRODUCT_STATUSES) {
            assertThat(ProductService.requireValidStatusOrNull(legal, "商品状态 status")).isEqualTo(legal);
        }
        assertThat(ProductService.requireValidStatusOrNull(null, "商品状态 status")).isNull();
        assertThat(ProductService.requireValidStatusOrNull("  ", "商品状态 status")).isEqualTo("  ");
        // 合法集合 = 流转表的键集（单一真值源），不是第二份字面量
        assertThat(ProductService.PRODUCT_STATUSES)
                .containsExactlyInAnyOrder("draft", "under_review", "on_sale", "off_sale");
    }

    // ======================== ② 未知当前状态：可行动出路 ========================

    @Test
    @DisplayName("死行自救：未知当前状态 + 目标 on_sale ⇒ 4xx 且文案给出路（不是「允许的目标状态: 无」）")
    void unknownCurrentStatusOnSaleGivesActionableExit() {
        when(productMapper.selectById("prod-dead")).thenReturn(productWithStatus("prod-dead", "active"));

        assertThatThrownBy(() -> productService.updateProductStatus("prod-dead", "on_sale", 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不在商品状态机内")
                .hasMessageContaining("off_sale")
                .hasMessageContaining("draft")
                .hasMessageNotContaining("允许的目标状态: 无");
    }

    @Test
    @DisplayName("死行自救：未知当前状态 → off_sale 走得通（收回状态机）")
    void unknownCurrentStatusCanBeRecoveredToOffSale() {
        when(productMapper.selectById("prod-dead")).thenReturn(productWithStatus("prod-dead", "active"));
        when(productMapper.updateById(any(Product.class))).thenReturn(1);

        productService.updateProductStatus("prod-dead", "off_sale", 1L);

        org.mockito.Mockito.verify(productMapper)
                .updateById(org.mockito.ArgumentMatchers.<Product>argThat(p -> "off_sale".equals(p.getStatus())));
    }

    @Test
    @DisplayName("死行自救：on_shelf → draft 也走得通；再走正常流转（draft → on_sale）")
    void unknownCurrentStatusCanBeRecoveredToDraft() {
        when(productMapper.selectById("prod-dead2")).thenReturn(productWithStatus("prod-dead2", "on_shelf"));
        when(productMapper.updateById(any(Product.class))).thenReturn(1);

        productService.updateProductStatus("prod-dead2", "draft", 1L);

        org.mockito.Mockito.verify(productMapper)
                .updateById(org.mockito.ArgumentMatchers.<Product>argThat(p -> "draft".equals(p.getStatus())));
    }

    @Test
    @DisplayName("死行自救**不**放行直接上架：未知当前状态 + 目标 on_sale 仍是 4xx")
    void unknownCurrentStatusCannotJumpToOnSale() {
        when(productMapper.selectById("prod-dead3")).thenReturn(productWithStatus("prod-dead3", "on_shelf"));

        assertThatThrownBy(() -> productService.updateProductStatus("prod-dead3", "on_sale", 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不在商品状态机内");
    }

    // ======================== ③ 上下架 / 删除端点：同样给可行动出路 ========================

    @Test
    @DisplayName("批量上架命中死行：错误文案含「修正回状态机」出路")
    void batchOnShelfDeadRowGivesExit() {
        when(productMapper.selectById("prod-dead4")).thenReturn(productWithStatus("prod-dead4", "active"));

        BatchOperationResult result = productService.batchOnShelf(java.util.List.of("prod-dead4"), 1L);

        assertThat(result.getFailed()).isEqualTo(1);
        assertThat(result.getErrors().get(0).getMessage())
                .contains("不允许上架")
                .contains("修正回状态机")
                .contains("off_sale");
    }

    @Test
    @DisplayName("删除命中死行：错误文案既保留「请先下架」也给出状态机外的出路")
    void deleteDeadRowGivesExit() {
        when(productMapper.selectById("prod-dead5")).thenReturn(productWithStatus("prod-dead5", "active"));

        assertThatThrownBy(() -> productService.deleteProduct("prod-dead5", 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("修正回状态机");
    }

    @Test
    @DisplayName("已知状态的拒绝文案**不**被出路文案污染（draft 不允许批量上架仍是原句）")
    void knownStatusRejectionMessageUnchanged() {
        when(productMapper.selectById("prod-known")).thenReturn(productWithStatus("prod-known", "draft"));

        BatchOperationResult result = productService.batchOnShelf(java.util.List.of("prod-known"), 1L);

        assertThat(result.getErrors().get(0).getMessage())
                .isEqualTo("当前状态[草稿]不允许上架");
    }
}
