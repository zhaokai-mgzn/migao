package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.ProcessingCategory;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.mapper.ProcessingCategoryMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * 开租默认加工项目录播种（issue #7148）。
 *
 * <h2>病灶</h2>
 * 加工项目录的两条种子路径都是「对<b>当时</b>的租户循环」：
 * <ul>
 *   <li>归档迁移 {@code db/migration-archive/V83__seed_processing_item_catalog.sql}（迁移时已存在的租户）；</li>
 *   <li>建库脚本 {@code db/init/schema.sql} 的 V83 终态块（建库时已存在的租户）。</li>
 * </ul>
 * ⇒ <b>迁移之后新入驻的租户，{@code processing_categories} / {@code processing_items} 都是 0 行</b>
 * （形态同 #4316 的工序库、#6295 的商品分类）—— 商家侧后果 = 下单页选不到任何加工项、
 * 加工费组合配不出来（只剩「从零自建」这一条路，不是开箱可用）。
 *
 * <h2>口径</h2>
 * 种 1 个分类「{@link OnboardingInitialData#DEFAULT_PROCESSING_CATEGORY_NAME}」+ {@link #CATALOG}
 * 里那份**存活目录**（{@code craftHint} / {@code description} 逐字照既有租户的那批行 ⇒
 * 新老租户的目录同值，不另写一份文案）。目录**不含** `接高` —— 它已由
 * {@code V123__retire_join_height_processing_item.sql} 撤出目录（软删 + 停用），种下就等于
 * 复活一个商家不该勾到的项。
 *
 * <h2>幂等（本类的核心不变量）</h2>
 * 幂等判据 = <b>该租户已有加工项（非软删）即不种</b>：先现取计数，{@code > 0} ⇒ 直接返回 0、不落任何行。
 * 重复入驻 / 重试 / 有人手工配过目录 ⇒ 行数恒定。**粒度是有意的「整份跳」**（同
 * {@link ProductCategorySeedService} 的口径，不做逐项补齐）：本类**只服务开租**这一个时点
 * （那时租户必然是空的），而逐项补齐会在「商家删掉某项后重跑」时把它**复活** ——
 * 那正是 V83 用 {@code ON CONFLICT (id) DO NOTHING} 明确拒绝的形态。
 * ⚠️ 如实登记：本仓 {@code processing_items} **没有** {@code (tenant_id, name)} 唯一约束，
 * 故幂等是**应用层**的；调用点只有开租事务一处（单线程、同事务内），没有并发面。
 *
 * <h2>为什么不吞异常</h2>
 * 与生产种子模板（{@link RegistrationService} 的 {@code applyProductionSeedTemplate}，尽力而为 +
 * error 日志）**有意不同**：目录对**任何**行业都要有（本类不按 industry 分支），
 * 缺了 = 该租户开箱不可用 ⇒ 落库失败就让它把开租整体回滚（申请人重试即可）。
 * 这条口径与后置条件校验（{@link RegistrationService} 的 {@code assertRequiredInitialData}）
 * 合起来，使「入驻链路漏种必需初始数据」这一族缺陷从**静默**变成**开租当场失败**。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProcessingItemSeedService {

    /** 默认分类的排序位（与建库脚本 / V83 的 `sort_order = 10` 同值）。 */
    private static final int DEFAULT_CATEGORY_SORT_ORDER = 10;

    /** 加工数量单位（issue #4882 口径：目录已无单价，`unit` = **加工数量**的单位）。 */
    private static final String DEFAULT_UNIT = "米";

    /**
     * 一条默认目录项。
     *
     * @param name        加工项名（= 加工费组合键的成员名，**差一个字取不到价**）
     * @param craftHint   显式声明的工艺（V78 口径：{@code null} = 未声明，不是「工艺=空」）
     * @param description 商家可读的说明（逐字照既有租户的那批行）
     */
    public record CatalogItem(String name, String craftHint, String description) {
    }

    /**
     * 默认加工项目录（<b>存活目录</b>）= 建库脚本 V83 终态块的 16 项 − V123 撤出的 `接高`
     * = <b>15 项</b>。名字取 V139 改名后的终态（`韩褶`，不是 ERP 附件的 `韩折`）。
     *
     * <p>与库里的目录**逐条同值**由类级元守卫
     * `tests/unit_ci_workflows/test_onboarding_processing_catalog_seed.py` 双向对账：
     * 以后再加 / 撤一个目录项（或改 `craftHint`）而漏改本常量 ⇒ 当场判红。</p>
     */
    public static final List<CatalogItem> CATALOG = List.of(
            new CatalogItem("打孔", "打孔", "ERP 加工费项（工艺声明：打孔）"),
            new CatalogItem("韩褶", "韩褶", "ERP 加工费项（工艺声明：韩褶）"),
            new CatalogItem("韩定+S钩", "韩褶", "ERP 加工费项（工艺声明：韩褶）"),
            new CatalogItem("穿杆", "穿杆", "ERP 加工费项（工艺声明：穿杆）"),
            new CatalogItem("平幔", "平幔", "ERP 加工费项（工艺声明：平幔）"),
            new CatalogItem("定型", null, "ERP 加工费特征（手选；不再由「工艺规格」录入）"),
            new CatalogItem("花边", null, "ERP 加工费特征（手选）"),
            new CatalogItem("扣环", null, "ERP 加工费特征（手选）"),
            new CatalogItem("拼接", null, "ERP 加工费特征（手选）"),
            new CatalogItem("双眼皮", null, "ERP 加工费特征（手选）"),
            new CatalogItem("缎带", null, "ERP 加工费单项（独立一行，不成组合）"),
            new CatalogItem("换货", null, "ERP 加工费单项"),
            new CatalogItem("超高", null, "自动推导特征（成品高+卷边 > 门幅）—— 不得手选"),
            new CatalogItem("超宽", null, "自动推导特征（成品宽+卷边 > 门幅）—— 不得手选"),
            new CatalogItem("倒幅", null, "自动推导特征（加工类型=定宽买高）—— 不得手选"));

    private final ProcessingCategoryMapper processingCategoryMapper;
    private final ProcessingItemMapper processingItemMapper;

    /**
     * 为租户种默认加工项目录（幂等）。
     *
     * @param tenantId 新租户 id（**显式传入**，不读 {@code TenantContext} —— 与生产种子模板同款：
     *                 「给哪个租户种」在调用点可读，也避免上下文错位时静默种到别的租户）
     * @return 本次真的种下的项数；{@code 0} = 该租户已有加工项 ⇒ 幂等跳过（不落行）
     */
    @Transactional(rollbackFor = Exception.class)
    public int seedDefaultCatalog(Long tenantId) {
        long existing = countProcessingItems(tenantId);
        if (existing > 0) {
            log.info("开租默认加工项目录：该租户已有 {} 项 ⇒ 不重复种（幂等）: tenantId={}", existing, tenantId);
            return 0;
        }

        String categoryId = ensureCategory(tenantId);
        for (CatalogItem item : CATALOG) {
            processingItemMapper.insert(ProcessingItem.builder()
                    .tenantId(tenantId)
                    .name(item.name())
                    .categoryId(categoryId)
                    .unit(DEFAULT_UNIT)
                    .description(item.description())
                    .craftHint(item.craftHint())
                    .status("active")
                    .build());
        }

        log.info("开租已种默认加工项目录: tenantId={}, categoryId={}, items={}",
                tenantId, categoryId, CATALOG.size());
        return CATALOG.size();
    }

    /**
     * 现取探针：该租户当前可见的加工项数（后置条件校验 / 判据共用，不复制第二份判定）。
     *
     * <p>显式带 {@code tenant_id} 谓词（不依赖拦截器注入）：它同时是「跨租户不可见」的判据面
     * —— 无租户上下文时也得给出确定读数。</p>
     */
    public long countProcessingItems(Long tenantId) {
        LambdaQueryWrapper<ProcessingItem> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(ProcessingItem::getTenantId, tenantId);
        Long count = processingItemMapper.selectCount(wrapper);
        return count == null ? 0L : count;
    }

    /**
     * 取该租户的「加工费」分类 id；没有就建一个（**不覆盖、不重复建**）。
     *
     * <p>按名字查而不是按 id 派生：商家可能自己先建过一个同名分类（或将来有别的路径先建），
     * 那时种子项必须挂到那个**已存在**的分类上，而不是并存两个同名的「加工费」。</p>
     */
    private String ensureCategory(Long tenantId) {
        List<ProcessingCategory> existing = processingCategoryMapper.selectList(
                new LambdaQueryWrapper<ProcessingCategory>()
                        .eq(ProcessingCategory::getTenantId, tenantId)
                        .eq(ProcessingCategory::getName,
                                OnboardingInitialData.DEFAULT_PROCESSING_CATEGORY_NAME));
        if (existing != null && !existing.isEmpty()) {
            return existing.get(0).getId();
        }
        ProcessingCategory category = ProcessingCategory.builder()
                .tenantId(tenantId)
                .name(OnboardingInitialData.DEFAULT_PROCESSING_CATEGORY_NAME)
                .sortOrder(DEFAULT_CATEGORY_SORT_ORDER)
                .status("active")
                .build();
        processingCategoryMapper.insert(category);
        return category.getId();
    }
}
