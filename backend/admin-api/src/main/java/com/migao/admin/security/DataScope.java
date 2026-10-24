package com.migao.admin.security;

import java.util.Collection;
import java.util.Objects;

/**
 * 数据范围（issue #7372，P0-4 段 1）—— **纯函数**：把「角色配置」翻译成「查询要加什么限制」。
 *
 * <h3>为什么权限码不够</h3>
 * <p>权限码管「能不能进这个模块」。一个「业务员」角色拿到 `order:list` 就能看见全公司的订单 ——
 * 授权到模块 ≠ 授权到数据。</p>
 *
 * <h3>两态 + 取宽</h3>
 * <ul>
 *   <li>{@code tenant}：全租户（**默认**，存量角色零回归）；</li>
 *   <li>{@code self}：只看**本人**创建的单据（`created_by = 当前用户 id`）。</li>
 * </ul>
 * <p>一个用户可有多个角色 ⇒ 与权限一致的取法：**取最宽**。只要有一个角色是 `tenant`，该用户就是 `tenant`；
 * 只有**全部**角色都是 `self` 才收窄 —— 否则「多给一个只读角色反而缩小了可见面」，那是反直觉的越权陷阱。</p>
 *
 * <h3>为什么单独一个类而不是写在拦截器里</h3>
 * <p>「谁的数据」这个判定会被至少四处用到（列表 / 详情 / 导出 / 黄金策查询），写进拦截器就只能拦 HTTP，
 * 拦不住服务间调用；写成纯函数则可被每一处**显式**调用，并由元守卫钉住「新查询面必须调用它」。</p>
 */
public final class DataScope {

    /** 全租户（默认）。 */
    public static final String TENANT = "tenant";

    /** 只看本人创建。 */
    public static final String SELF = "self";

    private DataScope() {
    }

    /**
     * 由该用户的全部角色范围解析出**生效**范围（取最宽）。
     *
     * <p><b>未知取值按最窄处理（fail-closed）</b>：列有 `DEFAULT 'tenant'`，所以 `null` 只可能来自
     * 「配置没写进来」，按默认（tenant）处理；而**拼错的取值**（如 `department`）一律当 `self` ——
     * 宁可让用户少看见数据（他会当场来问），也不要因为一个拼写错误把全公司数据放开（没人会发现）。</p>
     *
     * @param roleScopes 该用户所有角色的 `data_scope`（可含 null / 未知值）
     * @return {@link #TENANT} 或 {@link #SELF}
     */
    public static String resolve(Collection<String> roleScopes) {
        if (roleScopes == null || roleScopes.isEmpty()) {
            // 没有角色 ⇒ 走到查询面通常已因权限码被拦；这里按**最宽**兜底，避免把「没配角色」变成
            // 一次静默的数据缩水（存量账号零回归）。宁可宽在明处，也不要窄得没人发现。
            return TENANT;
        }
        for (String scope : roleScopes) {
            if (scope == null || TENANT.equals(scope)) {
                return TENANT;
            }
        }
        return SELF;
    }

    /**
     * 该范围内的列表查询要加的**本人用户 id** 过滤值。
     *
     * @return {@code null} = 不加限制；非 null = 只取该 `created_by` 的单据
     */
    public static String ownerFilter(String resolvedScope, String currentUserId) {
        return SELF.equals(resolvedScope) ? currentUserId : null;
    }

    /**
     * 详情读面的可见性判定：越权对象必须**当成不存在**（空集 / 404），不是 403 ——
     * 403 会泄露「这个 id 存在，只是你看不到」。
     *
     * @param resolvedScope 生效范围
     * @param ownerId       该对象的 `created_by`（null = 无制单人，如 C 端自助单）
     * @param currentUserId 当前用户 id
     */
    public static boolean visible(String resolvedScope, String ownerId, String currentUserId) {
        if (!SELF.equals(resolvedScope)) {
            return true;
        }
        if (currentUserId == null) {
            return false;
        }
        return Objects.equals(ownerId, currentUserId);
    }
}
