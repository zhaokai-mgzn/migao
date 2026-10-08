package com.migao.admin.service;

import java.util.List;

/**
 * 开租「必需初始数据」清单 —— <b>单一真值源</b>（issue #6295 的类级固化）。
 *
 * <h2>为什么需要这份清单（缺陷形态，#6295）</h2>
 * 开租（{@link RegistrationService#approveApplication}）此前只种了<b>行业生产种子模板</b>
 * （`production_operations` / `production_route_templates` …，见 #4361），
 * <b>唯独漏了商品分类</b> ⇒ 新租户 `categories` 表为空，而
 * `POST /api/admin/products` 在非草稿状态下要求 `categoryId` 非空
 * （`ProductService.validateRequiredForStatus`）⇒ <b>开箱第一次建商品必撞 422「分类ID不能为空」</b>。
 *
 * <p>这是**一族**缺陷（「入驻链路漏种必需初始数据」），不是一处：只要清单只活在人的记忆里，
 * 下一次新增域（客户标签 / 工艺 / 岗位…）就会再漏一次。故把清单落成**代码里的常量**，
 * 由两处消费：</p>
 * <ol>
 *   <li><b>运行期</b>：{@link RegistrationService} 的入驻后置条件校验逐条现取校验
 *       {@link #REQUIRED} 里 {@code enforced=true} 的项，缺一 ⇒ 开租 fail-closed（整体回滚）；</li>
 *   <li><b>研发期</b>：`tests/unit_ci_workflows/test_onboarding_required_seed_guard.py` 拿本文件当
 *       <b>真值源</b>与 `RegistrationService` 的入驻链路对账 —— 清单里有、链路里没种 ⇒ 红；
 *       链路里出现了<b>未登记</b>的种子调用 ⇒ 红（未登记即红）。</li>
 * </ol>
 *
 * <h2>约定（新增必需初始数据时照此办）</h2>
 * 入驻链路里任何名字形如 {@code *Seed*Service} 的播种协作者的调用（本仓现有形态：
 * `productCategorySeedService.seedDefaultCategory(...)` / `productionSeedTemplateService.applyTemplate(...)`）
 * <b>必须</b>在本清单登记一条 {@link Item}：写明 {@code key}、{@code description}、
 * {@code seedAnchor}（= 调用点里逐字出现的 `<接收者>.<方法>`），并声明是否 {@code enforced}。
 * 非 enforced（尽力而为）项必须在
 * `tests/unit_ci_workflows/onboarding_required_seed_ledger.json` 的 {@code best_effort} 里
 * 写明理由 + 重启条件（豁免台账<b>只许缩短</b>）。
 */
public final class OnboardingInitialData {

    /**
     * 默认商品分类名（<b>默认值的唯一来源</b>，issue #6295）。
     *
     * <p>「具名、可编辑」：租户管理员可随时在「商品 → 管理分类」里改名/增删；这里只保证
     * <b>开箱即有一个可选的分类</b>，不是不可变的系统保留项。</p>
     */
    public static final String DEFAULT_PRODUCT_CATEGORY_NAME = "窗帘成品";

    /** 清单键：默认商品分类（{@link ProductCategorySeedService#seedDefaultCategory}）。 */
    public static final String PRODUCT_CATEGORY_KEY = "product_category";

    /** 清单键：行业生产种子模板（{@link RegistrationService} 的 `applyProductionSeedTemplate`）。 */
    public static final String PRODUCTION_TEMPLATE_KEY = "production_template";

    /**
     * 一条必需初始数据。
     *
     * @param key         稳定键（进报错文案与台账，不随实现改名）
     * @param description 这项数据「不种会怎样」（写清后果，便于判红时归因）
     * @param seedAnchor  入驻链路里<b>逐字</b>出现的播种调用锚（`<接收者>.<方法>`，**不写行号**）
     * @param enforced    {@code true} = 无条件必需（后置条件校验 + 判据都按硬约束判）；
     *                    {@code false} = 尽力而为（有合法不种的分支 ⇒ 必须在豁免台账写明理由）
     */
    public record Item(String key, String description, String seedAnchor, boolean enforced) {
    }

    /**
     * 开租必需初始数据清单（<b>现取真值源</b>）。
     *
     * <p>⚠️ 往这里加一条 = 同时兑现两件事：① 入驻链路里真的种了它（或进豁免台账写明为什么不必种）；
     * ② 判据 `test_onboarding_required_seed_guard.py` 会当场按锚逐字对账。</p>
     */
    public static final List<Item> REQUIRED = List.of(
            new Item(PRODUCT_CATEGORY_KEY,
                    "默认商品分类：不种 ⇒ 新租户首建商品必撞 422「分类ID不能为空」（issue #6295）",
                    "productCategorySeedService.seedDefaultCategory",
                    true),
            new Item(PRODUCTION_TEMPLATE_KEY,
                    "行业生产种子模板：不种 ⇒ 新租户建单 fail-closed 422 ERR_ROUTING_NOT_FOUND（issue #4361/#4316）",
                    "productionSeedTemplateService.applyTemplate",
                    false));

    private OnboardingInitialData() {
    }
}
