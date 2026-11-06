// case_ids: MC-252
package com.migao.admin.service;

import com.migao.admin.entity.Product;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * 写路径的商品引用严格解析（issue #8788）。
 *
 * <p>病：{@code PATCH /api/admin/agent/products/{id}} 的三个写端点此前都走**共享**的
 * {@link ProductService#resolveProductId}，而它第 2/4/5 步分别是「UUID 前缀取第一条」
 * 「序号」「名称模糊取第一条」⇒ **改哪一件商品取决于「谁先被查到」**（200 OK 的数据事故）。</p>
 *
 * <p>本文件钉住 {@link ProductWriteRefResolver#resolveUniqueProductId} 的**唯一确定**不变式，三种形态各两条：</p>
 * <ul>
 *   <li>名称：唯一（精确/片段）⇒ 解析；重建名/命中多条 ⇒ {@code PRODUCT_AMBIGUOUS}；</li>
 *   <li>序号：**一律拒绝**（{@code PRODUCT_INDEX_NOT_ALLOWED}）—— 序号会随增删漂移；</li>
 *   <li>id 前缀：唯一 ⇒ 解析；命中多条 ⇒ {@code PRODUCT_AMBIGUOUS}；</li>
 * </ul>
 *
 * <p>另钉两条边界：精确 id（含非 UUID 的种子 id）直通；一条都不命中 ⇒ {@code null}（交给调用方 404）。</p>
 *
 * <p>边界（照实登记）：本判据只裁**解析**，不裁控制器把异常翻成 HTTP 的那一层
 * （后者由 {@code AgentProductControllerTest} 的既有 404 用例与 GlobalExceptionHandler 负责）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("写路径商品引用严格解析（ProductWriteRefResolver，issue #8788）")
class ProductWriteRefResolverTest {

    @Mock
    private ProductMapper productMapper;

    @InjectMocks
    private ProductWriteRefResolver resolver;

    private static final String UUID_A = "a1b2c3d4-e5f6-4a7b-8c9d-0123456789ab";
    private static final String UUID_B = "b2c3d4e5-f6a7-4b8c-9d0e-123456789abc";
    /** 与 {@link #UUID_PREFIX_TWIN_B} 共享 8 位前缀 `d4e5f6a7` —— 供「前缀命中多条」用。 */
    private static final String UUID_PREFIX_TWIN_A = "d4e5f6a7-b8c9-4d0e-9f1a-3456789abcde";
    private static final String UUID_PREFIX_TWIN_B = "d4e5f6a7-c9d0-4e1f-8a2b-456789abcdef";
    /** demo-seed 里**真实存在**的非 UUID 商品 id（历史/种子数据形态）。 */
    private static final String LEGACY_ID = "p-zg-001";

    private static Product product(String id, String name) {
        Product product = new Product();
        product.setId(id);
        product.setName(name);
        return product;
    }

    @BeforeEach
    void setUp() {
        when(productMapper.selectList(any())).thenReturn(Arrays.asList(
                product(UUID_A, "2699系列雪尼尔窗帘面料"),
                product(UUID_B, "云朵半遮光窗帘"),
                product(LEGACY_ID, "星空全遮光窗帘"),
                product(UUID_PREFIX_TWIN_A, "奶油风提花布-米白"),
                product(UUID_PREFIX_TWIN_B, "奶油风提花布-灰蓝")));
    }

    @Test
    @DisplayName("精确 UUID ⇒ 原样返回（写路径不额外「确认」，零猜测空间）")
    void exactUuidIsReturnedVerbatim() {
        assertThat(resolver.resolveUniqueProductId(UUID_A, 1L)).isEqualTo(UUID_A);
    }

    @Test
    @DisplayName("非 UUID 的种子 id（p-zg-001）⇒ 原样返回（不让真实 id 被当名称搜丢）")
    void legacyNonUuidIdIsReturnedVerbatim() {
        assertThat(resolver.resolveUniqueProductId(LEGACY_ID, 1L)).isEqualTo(LEGACY_ID);
    }

    @Test
    @DisplayName("精确名称唯一 ⇒ 解析到该商品")
    void uniqueExactNameResolves() {
        assertThat(resolver.resolveUniqueProductId("云朵半遮光窗帘", 1L)).isEqualTo(UUID_B);
    }

    @Test
    @DisplayName("重名（精确名称命中 2 条）⇒ PRODUCT_AMBIGUOUS，消息带条数 + 候选")
    void duplicateExactNameIsRefused() {
        when(productMapper.selectList(any())).thenReturn(Arrays.asList(
                product(UUID_A, "同名商品"),
                product(UUID_B, "同名商品")));

        assertThatThrownBy(() -> resolver.resolveUniqueProductId("同名商品", 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("匹配到 2 个商品")
                .hasMessageContaining("未执行修改")
                .satisfies(e -> assertThat(((BusinessException) e).getCode()).isEqualTo("PRODUCT_AMBIGUOUS"));
    }

    @Test
    @DisplayName("🔴 序号「3」⇒ PRODUCT_INDEX_NOT_ALLOWED（序号按创建时间排序，增删后漂移）")
    void indexIsRefused() {
        assertThatThrownBy(() -> resolver.resolveUniqueProductId("3", 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("序号")
                .hasMessageContaining("漂移")
                .satisfies(e -> assertThat(((BusinessException) e).getCode())
                        .isEqualTo("PRODUCT_INDEX_NOT_ALLOWED"));
    }

    @Test
    @DisplayName("名称片段唯一 ⇒ 解析到该商品")
    void uniqueFuzzyNameResolves() {
        assertThat(resolver.resolveUniqueProductId("云朵半遮光", 1L)).isEqualTo(UUID_B);
    }

    @Test
    @DisplayName("🔴 名称片段命中多条 ⇒ PRODUCT_AMBIGUOUS（绝不取第一条）")
    void ambiguousFuzzyNameIsRefused() {
        assertThatThrownBy(() -> resolver.resolveUniqueProductId("奶油风提花布", 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("匹配到 2 个商品")
                .satisfies(e -> assertThat(((BusinessException) e).getCode()).isEqualTo("PRODUCT_AMBIGUOUS"));
    }

    @Test
    @DisplayName("id 前缀唯一 ⇒ 解析到该商品")
    void uniqueUuidPrefixResolves() {
        assertThat(resolver.resolveUniqueProductId("b2c3d4e5", 1L)).isEqualTo(UUID_B);
    }

    @Test
    @DisplayName("🔴 id 前缀命中多条 ⇒ PRODUCT_AMBIGUOUS（写路径不接受「低概率」）")
    void duplicateUuidPrefixIsRefused() {
        assertThatThrownBy(() -> resolver.resolveUniqueProductId("d4e5f6a7", 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("匹配到 2 个商品")
                .satisfies(e -> assertThat(((BusinessException) e).getCode()).isEqualTo("PRODUCT_AMBIGUOUS"));
    }

    @Test
    @DisplayName("一条都不命中 ⇒ null（交给控制器 404，不在这里编一个 id）")
    void noMatchReturnsNull() {
        assertThat(resolver.resolveUniqueProductId("不存在的窗帘XYZ", 1L)).isNull();
    }
}
