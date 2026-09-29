package com.migao.admin.security;

import java.util.Collection;
import java.util.HashSet;
import java.util.Set;

/**
 * 「谁是管理员」与「谁能唤出米宝」的**服务端单一真值**（issue #5642，功能⑤授权门）。
 *
 * <h2>为什么需要这个类（病根）</h2>
 * 用户 2026-09-26 裁定：「管理员可以在 H5 上唤出 migao Agent 进行对话，**其他员工需要授权**才能唤出」，
 * 且「管理员」的判定口径 = **按权限码**（不新增 role、不做 is_owner）。
 * 而实测（设计单 §1.1 读数① / §3.2.1）：本仓**没有任何权限码在管「谁能唤出米宝」**
 * —— {@code /api/chat/send} 无端点级码、bmini 的 {@code pages/chat} 无 UI 门
 * ⇒ 必须新增码并给出**一处**判定。若把这个集合抄到第二处（前端 / 第二份常量），
 * 「改一处而另一端不同步」就再也不会变红（同族反面教材：issue #4393 的 {@code craft-display} 三份副本无守卫）。
 *
 * <h2>口径（逐条，与设计单 §2.3 / §3.3 / §8.1 同源）</h2>
 * <ul>
 *   <li>{@code ADMIN_PERMISSION_CODES} = 管理员权限码集合，**全仓唯一字面量**
 *       （机械判据：{@code tests/unit_ci_workflows/test_mibao_chat_gate.py} 判据 ①）。</li>
 *   <li>判定 = {@code containsAll(ADMIN_PERMISSION_CODES)}，且 {@code "*"} 通配**直接判真**。
 *       ⇒ {@code role='admin'}（{@code RoleService} 四处分支恒为 {@code ["*"]}）**自动落入**，
 *       <b>无需为 admin 写任何特例分支</b> —— 这也正是「既有行为零回归」的落法：
 *       管理员走的是通配，不是白名单。</li>
 *   <li>管理员（三码全持）⇒ **默认可唤**；员工被显式勾了米宝唤出码 ⇒ 也可唤；
 *       两者皆不满足 ⇒ **不可唤**，且必须由端侧给出「需要管理员授权」+ 可行动引导
 *       （不是静默隐藏、不是 403 白屏）。</li>
 *   <li>⚠️ 能力位（{@code capabilities.mibaoChat}）是**UI 显隐与文案**的来源，**不是授权本身**：
 *       真正拦住数据面的仍是 {@code @RequirePermission} + {@code PermissionInterceptor}
 *       （既有架构契约，本单不砍）。</li>
 * </ul>
 */
public final class AdminGate {

    /**
     * 管理员权限码集合（**全仓唯一字面量**，改这一处即两端同步）。
     *
     * <p>三个成员的来历（设计单 §3.1）：
     * {@code dashboard:view} 与 {@code employee:create} 是既有码；
     * 第三个是本单**新建**的米宝唤出码（此前全仓 0 命中 ⇒ 「复用既有码」这个选项不存在）。
     */
    public static final Set<String> ADMIN_PERMISSION_CODES =
            Set.of("dashboard:view", "employee:create", "agent:chat");

    /**
     * 米宝唤出授权码 —— 企业管理员在「员工管理」里勾给某个员工的那个码。
     *
     * <p>它就是 {@link #ADMIN_PERMISSION_CODES} 里承载「使用 AI 助手」语义的成员；
     * 单独给个名字是为了让调用点的意图可读（「被显式授权」≠「三码全持的管理员」）。
     */
    public static final String MIBAO_CHAT_GRANT_CODE = "agent:chat";

    /**
     * 「本租户是否**启用智能客服**」——**唯一判定处**（可插拔指标的开关）。
     *
     * <p>用途：经营看板上「AI 接待占比」这类指标**只在企业用到智能客服时才该出现**
     * （用户 2026-09-29：「AI 接待占比这个需要设计成可插拔的，未来有部分企业可能未购买智能客服」）。</p>
     *
     * <p>🔴 **当前口径（用户 2026-09-29 裁定 = 方案 B）**：租户只要有**任一员工**持有会话读码
     * {@code agent:session}，即视为该租户在用智能客服。判定在**租户维度**（不是"我有没有权"）——
     * 否则无该码的决策者反而看不到 AI 接入情况，与「经营看板给决策者看」的初衷冲突。</p>
     *
     * <p>🔮 **未来口径（用户同句指示：「未来是跟着租户购买模块决定的」）**：本函数改为读
     * **租户已购模块**（例如 {@code tenants} 上的模块位 / 独立的租户模块表）。
     * ⇒ 届时**只改本函数体**：`Capabilities.aiService` 的签名、`/api/auth/me` 的契约、
     * 看板指标卡的注册表与判据都**不动**（这正是把它收敛成一处的理由）。</p>
     *
     * @param tenantHasAgentSessionRead 该租户是否有员工持有 {@code agent:session}
     * @return 启用 ⇒ {@code true}
     */
    public static boolean tenantUsesAiService(boolean tenantHasAgentSessionRead) {
        return tenantHasAgentSessionRead;
    }

    private AdminGate() {
    }

    /**
     * 是否持**全部**管理员权限码（唯一判定函数；全仓没有第二处）。
     *
     * @param permissions 生效权限集合（{@code RoleService.getUserPermissions} 的快照/角色口径）
     * @return {@code "*"} 通配 ⇒ {@code true}；否则 {@code containsAll(ADMIN_PERMISSION_CODES)}
     */
    public static boolean hasAllAdminPermissionCodes(Collection<String> permissions) {
        Set<String> perms = toSet(permissions);
        if (perms.isEmpty()) {
            return false;
        }
        // "*" 通配（role='admin' / super_admin / service）⇒ 直接判真
        if (perms.contains("*")) {
            return true;
        }
        return perms.containsAll(ADMIN_PERMISSION_CODES);
    }

    /**
     * 能否唤出米宝（L1 唤出门，设计单 §3.2.4 / §8.1）。
     *
     * <p>{@code 管理员（三码全持，含 "*" 通配） ∨ 被显式授权（勾了米宝唤出码）}。
     * ⚠️ 它**不**蕴含任何工具权限（L3）——「能对话」≠「能调工具」。
     *
     * @param permissions 生效权限集合
     * @return 可唤 ⇒ {@code true}
     */
    public static boolean canSummonMibao(Collection<String> permissions) {
        Set<String> perms = toSet(permissions);
        if (perms.isEmpty()) {
            return false;
        }
        return hasAllAdminPermissionCodes(perms) || perms.contains(MIBAO_CHAT_GRANT_CODE);
    }

    private static Set<String> toSet(Collection<String> permissions) {
        if (permissions == null || permissions.isEmpty()) {
            return Set.of();
        }
        return new HashSet<>(permissions);
    }
}
