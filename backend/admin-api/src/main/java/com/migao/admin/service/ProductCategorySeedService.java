package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.Category;
import com.migao.admin.mapper.CategoryMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 开租商品分类播种（issue #6295）。
 *
 * <h2>病灶</h2>
 * 开租链路（{@link RegistrationService#approveApplication}）此前不碰 `categories` ⇒
 * 新租户分类表为空，而 `POST /api/admin/products`（非草稿）要求 `categoryId` 非空
 * （`ProductService.validateRequiredForStatus`）⇒ <b>开箱第一次建商品必撞 422「分类ID不能为空」</b>。
 * 商品分类的**写面**（建品表单自带「管理分类」）虽可自助恢复，但那要求用户先撞一次错、
 * 再自己想到去建分类 —— 这不是「开箱可用」。
 *
 * <h2>幂等（本类的核心不变量）</h2>
 * 幂等判据 = <b>该租户已有分类（非软删）即不种</b>：先现取计数，{@code > 0} ⇒ 直接返回 0、不落任何行。
 * 重复入驻 / 重试 / 有人手工补种过 ⇒ 行数恒定（连续调用两次，第二次零 insert）。
 * ⚠️ 如实登记：本仓 `categories` 表<b>没有</b> {@code (tenant_id, name)} 唯一约束，
 * 故幂等是<b>应用层</b>的（与 `ProductionSeedTemplateService` 的键查同款）；调用点只有开租事务一处
 * （单线程、同事务内），没有并发面。
 *
 * <h2>为什么不吞异常</h2>
 * 与生产种子模板（{@link RegistrationService} 的 `applyProductionSeedTemplate`，尽力而为 + error 日志）
 * <b>有意不同</b>：默认分类是<b>单行、无依赖</b>的插入，且它缺了 = 该租户开箱不可用
 * ⇒ 落库失败就让它把开租整体回滚（申请人重试即可），不要产出「没有分类的新租户」。
 * 这条口径与后置条件校验（{@link RegistrationService} 的 `assertRequiredInitialData`）合起来，
 * 使「入驻链路漏种必需初始数据」这一族缺陷从**静默**变成**开租当场失败**。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProductCategorySeedService {

    private final CategoryMapper categoryMapper;

    /**
     * 为租户种一个默认商品分类（幂等）。
     *
     * @param tenantId 新租户 id
     * @return 1 = 本次真的种下了一行；0 = 该租户已有分类 ⇒ 幂等跳过（不落行）
     */
    @Transactional(rollbackFor = Exception.class)
    public int seedDefaultCategory(Long tenantId) {
        long existing = countCategories(tenantId);
        if (existing > 0) {
            log.info("开租默认商品分类：该租户已有 {} 个分类 ⇒ 不重复种（幂等）: tenantId={}", existing, tenantId);
            return 0;
        }

        Category category = Category.builder()
                .tenantId(tenantId)
                // 默认值单一来源：名字只在 OnboardingInitialData 里出现一次
                .name(OnboardingInitialData.DEFAULT_PRODUCT_CATEGORY_NAME)
                .parentId(null)
                .level(1)
                .sortOrder(0)
                .status("active")
                .build();
        categoryMapper.insert(category);

        log.info("开租已种默认商品分类: tenantId={}, categoryId={}, name={}",
                tenantId, category.getId(), category.getName());
        return 1;
    }

    /**
     * 现取探针：该租户当前可见的商品分类数（后置条件校验 / 判据共用，不复制第二份判定）。
     *
     * <p>显式带 {@code tenant_id} 谓词（不依赖拦截器注入）：它同时是「跨租户不可见」的判据面
     * —— 无租户上下文时也得给出确定读数。</p>
     */
    public long countCategories(Long tenantId) {
        LambdaQueryWrapper<Category> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(Category::getTenantId, tenantId);
        Long count = categoryMapper.selectCount(wrapper);
        return count == null ? 0L : count;
    }
}
