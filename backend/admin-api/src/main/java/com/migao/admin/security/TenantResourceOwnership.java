package com.migao.admin.security;

import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.AfterSalesTicketMapper;
import com.migao.admin.mapper.CategoryMapper;
import com.migao.admin.mapper.ProcessingCategoryMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.service.NotificationRuleService;
import com.migao.admin.service.NotificationTemplateService;
import com.migao.admin.service.OrderService;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

/**
 * 租户域资源的**归属认定表**（issue #6158）—— 资源键 → 「这个 id 属不属于当前租户」。
 *
 * <h3>为什么是这几行代码（最少代码阶梯）</h3>
 * <p>本单**不新造**第二套越权判定：每一个资源键都用该资源**写路径本来就会执行**的那条查询
 * （{@code selectById}）—— MyBatis-Plus 的 {@code TenantLineInnerInterceptor} 会按
 * {@code TenantContext} 自动追加 {@code tenant_id = 当前租户} ⇒ 他租户的行**查不到** ⇒
 * 与既有「合法载荷跨租户写 ⇒ 404」**完全同源**（不是新的判定路径）。</p>
 *
 * <p>注入 Mapper / Service 而不是自己写 SQL：标准库与 MyBatis-Plus 都做不了「按资源键分派一次
 * 带租户过滤的按 id 查询」—— 资源键到表/实体的映射是**业务信息**，只能写在业务侧；
 * 抽象成通用泛型层反而要多一层反射（过度建设）。认定形状已在 {@link #check} 里收口，
 * 5 个端点各自只需一行注解（见 {@link TenantOwnedResource}）。</p>
 */
@Component
@RequiredArgsConstructor
public class TenantResourceOwnership {

    private final ProductMapper productMapper;
    private final CategoryMapper categoryMapper;
    private final ProcessingItemMapper processingItemMapper;
    private final ProcessingCategoryMapper processingCategoryMapper;
    private final AfterSalesTicketMapper afterSalesTicketMapper;
    private final OrderService orderService;
    /**
     * 通知模板 / 规则的服务（issue #6167）—— 这两张表在 {@code IGNORE_TENANT_TABLES} 里，
     * 归属语义**不与其余租户域资源同源**（见 {@link #registerChecks()} 的登记说明）。
     */
    private final NotificationTemplateService notificationTemplateService;
    private final NotificationRuleService notificationRuleService;

    /**
     * 资源键 → 归属认定（认定不过 ⇒ 抛 {@code NOT_FOUND}，与既有 404 路径同一份异常与文案）。
     *
     * <p>{@code LinkedHashMap}：登记顺序 = 判据/报错时列出的顺序（人可读）。</p>
     */
    private final Map<String, OwnerCheck> checks = new LinkedHashMap<>();

    /**
     * 资源键 → **可写**认定（issue #6167）—— 只对「可读面比可写面宽」的资源登记
     * （现取：{@code tenant_id=0} 的系统内置行**可读不可写**的混合表）。
     *
     * <p>不登记的资源键没有这项检查：它们的「可见」与「可写」是同一个集合（租户插件自动追加
     * {@code tenant_id = 当前租户}），认过可见即认定可写 —— 这正是 T1（issue #6158）的形态，
     * 本单**不重判**它。</p>
     */
    private final Map<String, OwnerCheck> writableChecks = new LinkedHashMap<>();

    /** 归属认定：目标 id 属于当前租户 ⇒ 正常返回；否则抛 {@code NOT_FOUND}。 */
    @FunctionalInterface
    private interface OwnerCheck {
        void assertOwned(String id);
    }

    /**
     * 登记认定表（构造后由 Spring 调用一次）。
     *
     * <p>⚠️ 登记时**不查询**，只登记「按 id 查询」这个动作 —— 查询发生在 {@link #check} 被调用时
     * （那时 {@code TenantContext} 已经是本次请求的主体）。</p>
     *
     * <p>public 的理由：判据要能直接装配它（{@code new TenantResourceOwnership(...)} 之后调用一次），
     * 不靠 Spring 容器起全套上下文 —— 同 {@code PgCluster} 收口的理由（装配只有一份）。</p>
     */
    @PostConstruct
    public void registerChecks() {
        checks.put("product", id -> {
            if (productMapper.selectById(id) == null) {
                throw BusinessException.notFound("商品");
            }
        });
        checks.put("category", id -> {
            if (categoryMapper.selectById(id) == null) {
                throw BusinessException.notFound("分类");
            }
        });
        checks.put("processing-item", id -> {
            if (processingItemMapper.selectById(id) == null) {
                throw BusinessException.notFound("加工项");
            }
        });
        checks.put("processing-category", id -> {
            if (processingCategoryMapper.selectById(id) == null) {
                throw BusinessException.notFound("加工分类");
            }
        });
        // 订单 `/content`：只判「这个订单在当前租户下可见吗」——**不**顺手带状态闸门
        // （闸门语义的唯一实现点是 OrderStatusTransitions，由服务层在那条路上执行；这里多判一次
        // 就是第二套判定，正是本单要避免的）。
        checks.put("order", id -> {
            if (!orderService.existsForCurrentTenant(id)) {
                throw BusinessException.notFound("订单");
            }
        });
        // 售后工单状态（**同类第 6 个实例**，本单顺手固化）：`AfterSalesTicketService.updateTicketStatus`
        // 的既有 404 路径同样是「带租户过滤的 selectById 查不到」，而 `@Valid` 先于它发生 ⇒
        // 同一条次序缺陷。登记理由见 TenantOwnershipRulesLedger 的说明（类级守卫会把它算进面内）。
        checks.put("after-sales-ticket", id -> {
            if (afterSalesTicketMapper.selectById(id) == null) {
                throw BusinessException.notFound("售后工单");
            }
        });
        // ─────────── issue #6167：混合表（可读面比可写面宽）───────────
        // notification_templates / notification_rules 在 MybatisPlusConfig.IGNORE_TENANT_TABLES 里
        // ⇒ 租户插件**不**给它们追加 tenant_id 过滤 ⇒ 「带租户过滤的按 id 查询」不像其余资源那样天然存在。
        // durable 依据（MybatisPlusConfig 注释逐字）：「查询条件 (tenant_id = 当前租户 OR tenant_id = 0)
        // 已在业务层显式过滤」⇒ 归属语义是**两条**：
        //   · 可读 = (tenant_id = 当前租户 OR tenant_id = 0)   ← 既有查询与 service 的 assertTenantOwned 组合出来
        //   · 可写 =  tenant_id = 当前租户                     ← service 的 assertTenantOwned 精确谓词
        // 本单只把「可写」这一条接入认定（读面一字不动 ⇒ 系统内置行仍可读）；
        // 认定用的查询复用 service 里那两条方法，**不**在安全层重写第二份谓词。
        checks.put("notification-template", id -> {
            if (!notificationTemplateService.existsForCurrentTenant(id)) {
                throw BusinessException.notFound("通知模板");
            }
        });
        writableChecks.put("notification-template", id -> {
            if (!notificationTemplateService.isWritableByCurrentTenant(id)) {
                // 可读而不可写 ⇒ 现存实现给 422 + 「系统内置…不允许修改」（不是 404——
                // 行对当前租户是可见的，用 404 会谎报不存在）。这里只用它区分「可见但不可写」。
                throw BusinessException.validationError(
                        "系统内置模板不允许修改，可复制后新建自定义模板");
            }
        });
        checks.put("notification-rule", id -> {
            if (!notificationRuleService.existsForCurrentTenant(id)) {
                throw BusinessException.notFound("通知规则");
            }
        });
        writableChecks.put("notification-rule", id -> {
            if (!notificationRuleService.isWritableByCurrentTenant(id)) {
                throw BusinessException.validationError(
                        "系统内置规则不允许修改，可复制后新建自定义规则");
            }
        });
    }

    /**
     * 已登记的资源键（**现取**，不写死 —— 判据与元守卫都读它）。
     *
     * @return 资源键集合（登记顺序）
     */
    public Set<String> registeredResources() {
        return checks.keySet();
    }

    /**
     * 归属认定：目标 id 不属于当前租户 ⇒ 抛 {@code NOT_FOUND}（404）。
     *
     * @param resource 资源键（见 {@link TenantOwnedResource#value()}）
     * @param id       {@code {id}} 路径变量
     */
    public void check(String resource, String id) {
        OwnerCheck check = checks.get(resource);
        if (check == null) {
            // fail-closed：登记缺失 ⇒ 显式报错。静默放行会让「新端点忘了登记」退化回
            // 「校验先于归属判定」的旧缺陷（issue #6158 的形态）重新进门。
            throw new IllegalStateException(
                    "未登记的租户域资源键: " + resource + "（已登记 = " + checks.keySet()
                            + "）；请在 TenantResourceOwnership.registerChecks() 里补上认定");
        }
        // 顺序是**语义要求**，不是偏好（issue #6167）：
        //   先「可见」—— 不可见（他租户行 / 行不存在）⇒ 404，与 T1（#6158）同源；
        //   后「可写」—— 可见但不可写 ⇒ 系统内置行（tenant_id=0），仍走既有 422 路径。
        // 若把可写判定放前面，他租户行会被读成 422 ⇒ 跨租户读数被污染（本单实例判据当场红）。
        check.assertOwned(id);

        // 「可见」不等于「可写」：混合表里 tenant_id=0 的系统内置行可读不可写。
        // 未登记可写认定的资源键 ⇒ 跳过（可见与可写同集合，由租户插件保证），不重判 T1 的形态。
        OwnerCheck writable = writableChecks.get(resource);
        if (writable != null) {
            writable.assertOwned(id);
        }
    }

    /**
     * 已登记**可写**认定的资源键（issue #6167，**现取**）—— 判据用它自证覆盖面。
     *
     * @return 资源键集合（登记顺序）
     */
    public Set<String> writableResources() {
        return writableChecks.keySet();
    }
}
