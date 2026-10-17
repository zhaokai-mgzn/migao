// case_ids: OB-007
package com.migao.admin.service;

import com.migao.admin.entity.ProcessingCategory;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.mapper.ProcessingCategoryMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 开租默认加工项目录播种（issue #7148）。
 *
 * <p>病灶：加工项目录的两条种子路径（归档迁移 {@code V83__seed_processing_item_catalog.sql} 与
 * 建库脚本 {@code backend/admin-api/src/main/resources/db/init/schema.sql} 的终态块）都是
 * <b>「对当时的租户循环」</b> ⇒ <b>迁移之后新入驻的租户，加工项目录是 0 行</b>（形态同 #4316 的工序库、
 * #6295 的商品分类）。商家侧后果 = 下单页选不到任何加工项、加工费组合配不出来（只有从零自建这一条路）。</p>
 *
 * <h2>判据面（每条都能单独变红）</h2>
 * <ol>
 *   <li><b>判据 1（主判据）</b>：空目录租户 ⇒ 种 1 个「加工费」分类 + <b>整份存活目录</b>；
 *       每行的 {@code tenantId} = 入参租户、{@code categoryId} = 本次种下的那个分类、
 *       {@code craftHint} / {@code description} 逐条照目录、{@code status=active}；
 *       红证：把播循环摘掉（或改成只种一条）⇒ 本判据红（捕获不到那些行）。</li>
 *   <li><b>判据 2（目录口径）</b>：目录 = 15 项存活项 —— 含用户点名的 <code>韩褶 / 打孔 / 定型</code>、
 *       含 5 条带工艺声明的项；<b>不含</b> <code>接高</code>（V123 已把它撤出目录 —— 种下 = 复活一个
 *       商家不该勾到的项）。红证：往目录里加回 <code>接高</code> ⇒ 本判据红。</li>
 *   <li><b>判据 3（幂等）</b>：该租户已有加工项 ⇒ 返回 0、<b>零写操作</b>（分类也不种）；
 *       重复入驻 / 重试不种出重复项，也<b>不复活 / 不覆盖</b>商家改过、删过的行；</li>
 *   <li><b>判据 4（复用已有同名分类）</b>：目录为空但「加工费」分类已在 ⇒ 不重复建分类，
 *       种子项的 {@code categoryId} = 那个已有分类的 id（不另造一个同名分类）；</li>
 *   <li><b>判据 5（现取探针）</b>：{@code countProcessingItems} 对 null 计数归 0（不让 NPE 变成 500）。</li>
 * </ol>
 *
 * <p>⚠️ 射程（如实登记）：本判据是 mock 面（只证明「插了哪些行」）；
 * 「入驻后目录真的落库、外键真的被 {@code processing_items.category_id} 接受」这条端到端读数由真库判据
 * {@code NewTenantOnboardingCategoryRealDbTest} 承担；「Java 目录 ⇄ 库里目录不漂移」由类级元守卫
 * {@code tests/unit_ci_workflows/test_onboarding_processing_catalog_seed.py} 承担。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("#7148 开租默认加工项目录播种：具名 + 整份目录 + 幂等 + 复用分类")
class ProcessingItemSeedServiceTest {

    private static final Long TENANT_ID = 42L;
    private static final String EXISTING_CATEGORY_ID = "pc-existing-fee";

    @Mock
    private ProcessingCategoryMapper processingCategoryMapper;

    @Mock
    private ProcessingItemMapper processingItemMapper;

    @InjectMocks
    private ProcessingItemSeedService seedService;

    @Test
    @DisplayName("判据 1：空目录租户 ⇒ 种 1 个「加工费」分类 + 整份存活目录（字段逐条正确）")
    void seedsCategoryAndWholeCatalogForEmptyTenant() {
        when(processingItemMapper.selectCount(any())).thenReturn(0L);
        when(processingCategoryMapper.selectList(any())).thenReturn(List.of());
        doAnswer(inv -> {
            ((ProcessingCategory) inv.getArgument(0)).setId("pc-seeded-fee");
            return 1;
        }).when(processingCategoryMapper).insert(any(ProcessingCategory.class));

        int inserted = seedService.seedDefaultCatalog(TENANT_ID);

        ArgumentCaptor<ProcessingCategory> categoryCaptor = ArgumentCaptor.forClass(ProcessingCategory.class);
        verify(processingCategoryMapper, times(1)).insert(categoryCaptor.capture());
        ProcessingCategory category = categoryCaptor.getValue();
        assertThat(category.getName())
                .as("分类名必须取单一来源常量 OnboardingInitialData.DEFAULT_PROCESSING_CATEGORY_NAME")
                .isEqualTo(OnboardingInitialData.DEFAULT_PROCESSING_CATEGORY_NAME)
                .isEqualTo("加工费");
        assertThat(category.getTenantId()).as("必须种在**本租户**名下").isEqualTo(TENANT_ID);
        assertThat(category.getStatus()).isEqualTo("active");

        ArgumentCaptor<ProcessingItem> itemCaptor = ArgumentCaptor.forClass(ProcessingItem.class);
        verify(processingItemMapper, times(ProcessingItemSeedService.CATALOG.size()))
                .insert(itemCaptor.capture());
        List<ProcessingItem> rows = itemCaptor.getAllValues();

        assertThat(inserted)
                .as("返回值 = 本次真的种下的项数")
                .isEqualTo(ProcessingItemSeedService.CATALOG.size());
        assertThat(rows).extracting(ProcessingItem::getName)
                .as("目录逐条照 CATALOG 的顺序与写法种下（名字是取价组合键，差一个字取不到价）")
                .containsExactlyElementsOf(namesOfCatalog());
        assertThat(rows).extracting(ProcessingItem::getCraftHint)
                .as("craftHint 逐条照目录（工艺维的受控来源，不许现算）")
                .containsExactlyElementsOf(hintsOfCatalog());
        assertThat(rows).extracting(ProcessingItem::getDescription)
                .as("description 逐条照目录（与既有租户的那批行同值 —— 不另写一份文案）")
                .containsExactlyElementsOf(descriptionsOfCatalog());
        assertThat(rows).allSatisfy(row -> {
            assertThat(row.getTenantId()).as("每行都必须种在本租户名下").isEqualTo(TENANT_ID);
            assertThat(row.getCategoryId())
                    .as("每行的 categoryId 必须指向本次种下的那个分类（外键 REFERENCES processing_categories(id)）")
                    .isEqualTo("pc-seeded-fee");
            assertThat(row.getStatus()).isEqualTo("active");
            assertThat(row.getUnit()).as("加工数量单位默认米（issue #4882 口径）").isEqualTo("米");
        });
    }

    @Test
    @DisplayName("判据 2：目录 = 15 项存活项（含韩褶/打孔/定型，不含已撤出的接高）")
    void catalogIsTheLiveIndustryCatalog() {
        List<String> names = namesOfCatalog();

        assertThat(names)
                .as("用户点名的常用加工项必须在默认目录里")
                .contains("韩褶", "打孔", "定型");
        assertThat(names)
                .as("「接高」已在 V123 撤出加工项目录（软删 + 停用）⇒ 种下它就等于复活一个商家不该勾到的项")
                .doesNotContain("接高");
        assertThat(names)
                .as("存活目录 = 建库脚本那 16 项 − V123 撤出的 1 项")
                .hasSize(15);
        assertThat(ProcessingItemSeedService.CATALOG)
                .filteredOn(item -> item.craftHint() != null)
                .extracting(ProcessingItemSeedService.CatalogItem::name)
                .as("带工艺声明的 5 项（路线键「工艺」维的受控来源）")
                .containsExactly("打孔", "韩褶", "韩定+S钩", "穿杆", "平幔");
    }

    @Test
    @DisplayName("判据 3：已有加工项的租户 ⇒ 返回 0、零写操作（不重复种、不复活商家删过的行）")
    void seedingIsIdempotentWhenTenantAlreadyHasItems() {
        when(processingItemMapper.selectCount(any())).thenReturn(15L);

        int inserted = seedService.seedDefaultCatalog(TENANT_ID);

        assertThat(inserted).as("已有目录 ⇒ 幂等跳过（返回 0）").isZero();
        verify(processingCategoryMapper, never()).insert(any(ProcessingCategory.class));
        verify(processingItemMapper, never()).insert(any(ProcessingItem.class));
    }

    @Test
    @DisplayName("判据 4：目录为空但「加工费」分类已在 ⇒ 复用该分类，不另造同名分类")
    void reusesExistingCategoryWithoutDuplicatingIt() {
        when(processingItemMapper.selectCount(any())).thenReturn(0L);
        ProcessingCategory existing = ProcessingCategory.builder()
                .id(EXISTING_CATEGORY_ID).tenantId(TENANT_ID)
                .name(OnboardingInitialData.DEFAULT_PROCESSING_CATEGORY_NAME)
                .sortOrder(10).status("active").build();
        when(processingCategoryMapper.selectList(any())).thenReturn(List.of(existing));

        seedService.seedDefaultCatalog(TENANT_ID);

        verify(processingCategoryMapper, never()).insert(any(ProcessingCategory.class));
        ArgumentCaptor<ProcessingItem> itemCaptor = ArgumentCaptor.forClass(ProcessingItem.class);
        verify(processingItemMapper, times(ProcessingItemSeedService.CATALOG.size()))
                .insert(itemCaptor.capture());
        assertThat(itemCaptor.getAllValues()).extracting(ProcessingItem::getCategoryId)
                .as("种子项必须挂到那个**已存在**的「加工费」分类上")
                .containsOnly(EXISTING_CATEGORY_ID);
    }

    @Test
    @DisplayName("判据 5：countProcessingItems 对 null 计数归 0（不让 NPE 变成 500）")
    void countProcessingItemsIsNullSafe() {
        when(processingItemMapper.selectCount(any())).thenReturn(null);

        assertThat(seedService.countProcessingItems(TENANT_ID)).isZero();
        verify(processingItemMapper).selectCount(any());
    }

    private static List<String> namesOfCatalog() {
        return ProcessingItemSeedService.CATALOG.stream()
                .map(ProcessingItemSeedService.CatalogItem::name).toList();
    }

    private static List<String> hintsOfCatalog() {
        return ProcessingItemSeedService.CATALOG.stream()
                .map(ProcessingItemSeedService.CatalogItem::craftHint).toList();
    }

    private static List<String> descriptionsOfCatalog() {
        return ProcessingItemSeedService.CATALOG.stream()
                .map(ProcessingItemSeedService.CatalogItem::description).toList();
    }
}
