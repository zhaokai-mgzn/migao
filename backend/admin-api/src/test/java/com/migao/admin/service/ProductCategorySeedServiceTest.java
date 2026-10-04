// case_ids: OB-006
package com.migao.admin.service;

import com.migao.admin.entity.Category;
import com.migao.admin.mapper.CategoryMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 开租默认商品分类播种（issue #6295）。
 *
 * <p>判据面（每条都能单独变红）：</p>
 * <ol>
 *   <li><b>判据 1（主判据）</b>：空分类租户 ⇒ <b>真的插了一行</b>，且该行的名字 = 单一来源常量
 *       {@link OnboardingInitialData#DEFAULT_PRODUCT_CATEGORY_NAME}、{@code tenant_id} = 入参租户、
 *       {@code status=active}、{@code parent_id=null}、{@code level=1}；
 *       红证：把 {@code seedDefaultCategory} 的 insert 摘掉 ⇒ 本判据红（捕获不到 insert）。</li>
 *   <li><b>判据 2（幂等）</b>：连续调用两次（第二次时该租户已有 1 个分类）⇒ 第二次返回 0、
 *       <b>零 insert</b> ⇒ 重复入驻 / 重试不种出重复分类；</li>
 *   <li><b>判据 3（不覆盖用户数据）</b>：租户已有分类（3 个）⇒ 不种、不删、不改（零写操作）；</li>
 *   <li><b>判据 4（现取探针）</b>：{@code countCategories} 对 null 计数归 0（不让 NPE 变成 500）。</li>
 * </ol>
 *
 * <p>⚠️ 射程（如实登记）：本判据是 mock 面（只证明「插了哪一行」），
 * 「新租户首建商品真的不再 422」这条端到端读数由真库判据
 * `NewTenantOnboardingCategoryRealDbTest` 承担。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("#6295 开租默认商品分类播种：具名 + 幂等 + 单一来源")
class ProductCategorySeedServiceTest {

    private static final Long TENANT_ID = 42L;

    @Mock
    private CategoryMapper categoryMapper;

    @InjectMocks
    private ProductCategorySeedService seedService;

    @Test
    @DisplayName("判据 1：空分类租户 ⇒ 种下 1 行具名分类（名字取自单一来源常量）")
    void seedsOneNamedCategoryForEmptyTenant() {
        when(categoryMapper.selectCount(any())).thenReturn(0L);

        int inserted = seedService.seedDefaultCategory(TENANT_ID);

        ArgumentCaptor<Category> captor = ArgumentCaptor.forClass(Category.class);
        verify(categoryMapper, times(1)).insert(captor.capture());
        Category row = captor.getValue();

        assertThat(inserted).as("空分类租户必须真的种下一行").isEqualTo(1);
        assertThat(row.getName())
                .as("默认分类必须具名，且名字来自单一来源 OnboardingInitialData.DEFAULT_PRODUCT_CATEGORY_NAME")
                .isEqualTo(OnboardingInitialData.DEFAULT_PRODUCT_CATEGORY_NAME)
                .isNotBlank();
        assertThat(row.getTenantId()).as("必须种在**本租户**名下").isEqualTo(TENANT_ID);
        assertThat(row.getStatus()).as("可编辑/可见的普通分类（active）").isEqualTo("active");
        assertThat(row.getParentId()).as("分类是扁平结构（issue #2905）").isNull();
        assertThat(row.getLevel()).isEqualTo(1);
        assertThat(row.getSortOrder()).isEqualTo(0);
    }

    @Test
    @DisplayName("判据 2：连续两次 ⇒ 第二次零 insert（幂等：重复入驻/重试不种出重复分类）")
    void seedingTwiceIsIdempotent() {
        // 第一次：该租户没有分类；第二次：已经有 1 个 ⇒ 走幂等跳过分支
        when(categoryMapper.selectCount(any())).thenReturn(0L, 1L);

        int first = seedService.seedDefaultCategory(TENANT_ID);
        int second = seedService.seedDefaultCategory(TENANT_ID);

        assertThat(first).as("首次：种下 1 行").isEqualTo(1);
        assertThat(second).as("再次：幂等跳过（返回 0）").isEqualTo(0);
        verify(categoryMapper, times(1)).insert(any(Category.class));
    }

    @Test
    @DisplayName("判据 3：租户已有分类 ⇒ 一行不写（不覆盖用户自己建的分类）")
    void doesNotTouchTenantThatAlreadyHasCategories() {
        when(categoryMapper.selectCount(any())).thenReturn(3L);

        int inserted = seedService.seedDefaultCategory(TENANT_ID);

        assertThat(inserted).as("已有分类 ⇒ 不种").isEqualTo(0);
        verify(categoryMapper, never()).insert(any(Category.class));
    }

    @Test
    @DisplayName("判据 4：countCategories 现取计数（null ⇒ 0，不让 NPE 变成 500）")
    void countCategoriesTreatsNullAsZero() {
        when(categoryMapper.selectCount(any())).thenReturn(null);
        assertThat(seedService.countCategories(TENANT_ID)).isEqualTo(0L);

        when(categoryMapper.selectCount(any())).thenReturn(2L);
        assertThat(seedService.countCategories(TENANT_ID)).isEqualTo(2L);
    }
}
