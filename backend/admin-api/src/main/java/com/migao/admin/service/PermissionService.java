package com.migao.admin.service;

import com.migao.admin.entity.Permission;
import com.migao.admin.mapper.PermissionMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 权限服务类
 * 处理权限相关的业务逻辑
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PermissionService {

    private final PermissionMapper permissionMapper;

    /**
     * 查询所有权限列表
     *
     * @return 权限列表
     */
    public List<Permission> getAllPermissions() {
        LambdaQueryWrapper<Permission> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(Permission::getDeleted, 0)
                .eq(Permission::getStatus, "active")
                .orderByAsc(Permission::getCode);
        return permissionMapper.selectList(wrapper);
    }

    /**
     * 根据租户ID查询权限列表
     *
     * @param tenantId 租户ID
     * @return 权限列表
     */
    public List<Permission> getPermissionsByTenant(Long tenantId) {
        LambdaQueryWrapper<Permission> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(Permission::getTenantId, tenantId)
                .eq(Permission::getDeleted, 0)
                .eq(Permission::getStatus, "active")
                .orderByAsc(Permission::getCode);
        return permissionMapper.selectList(wrapper);
    }

    /**
     * 根据权限代码查询权限
     *
     * @param code 权限代码
     * @return 权限实体
     */
    public Permission getPermissionByCode(String code) {
        LambdaQueryWrapper<Permission> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(Permission::getCode, code)
                .eq(Permission::getDeleted, 0);
        return permissionMapper.selectOne(wrapper);
    }

    /**
     * 根据ID查询权限
     *
     * @param id 权限ID
     * @return 权限实体
     */
    public Permission getPermissionById(String id) {
        return permissionMapper.selectById(id);
    }

    /**
     * 创建权限
     *
     * @param permission 权限实体
     * @return 是否成功
     */
    public boolean createPermission(Permission permission) {
        // 检查权限代码是否已存在
        Permission existing = getPermissionByCode(permission.getCode());
        if (existing != null) {
            log.warn("权限代码已存在: {}", permission.getCode());
            return false;
        }

        int result = permissionMapper.insert(permission);
        return result > 0;
    }

    /**
     * 更新权限
     *
     * @param permission 权限实体
     * @return 是否成功
     */
    public boolean updatePermission(Permission permission) {
        int result = permissionMapper.updateById(permission);
        return result > 0;
    }

    /**
     * 删除权限
     *
     * @param id 权限ID
     * @return 是否成功
     */
    public boolean deletePermission(String id) {
        int result = permissionMapper.deleteById(id);
        return result > 0;
    }

    /**
     * 幂等补全租户权限目录（RBAC 修复，2026-09-03）
     *
     * 背景：旧版新租户初始化只 seed 5 条大类码（dashboard:view / product:manage /
     * processing:manage / knowledge:manage / system:manage），而代码鉴权
     * (@RequirePermission) 与前端菜单树实际使用 order:list / employee:create 等
     * 16 个细粒度码 → 角色管理页只能勾 5 条，无法为自定义角色授予订单/员工/客户等
     * 细粒度权限（POC RBAC 走查实证：DB 目录与菜单树交集仅 3 个码）。
     *
     * 本方法对存量租户补种缺失的细粒度码（幂等：已存在则跳过），使角色管理页
     * 可勾选完整权限目录。新租户已由 RegistrationService 全量 seed，无需调用。
     *
     * @param tenantId 租户ID
     * @return 补种数量
     */
    public int ensureFullPermissionCatalog(Long tenantId) {
        // 与 RegistrationService.initializeDefaultRolesAndPermissions 的目录保持一致
        // 🔴 issue #5246：此前本目录**漏了 4 个码**（processing:view / processing:update / inbound:view /
        // inbound:create），而 RegistrationService 有 ⇒ 存量租户的角色管理页勾不到这 4 个码
        // （新租户能勾、老租户不能 = 「同一份目录两处漂移」）。本次补齐 + 加两个读码，
        // 两处数组的**码列现已逐值相等**（守卫方式：按行抽第 2 列 diff）。
        String[][] catalog = {
                {"仪表板查看", "dashboard:view", "dashboard", "view", "查看数据概览"},
                {"商品管理", "product:manage", "product", "manage", "管理商品(旧大类码，兼容)"},
                {"商品列表", "product:list", "product", "list", "查看商品列表"},
                {"新增商品", "product:create", "product", "create", "新增/编辑/上下架商品"},
                {"商品分类", "product:category", "product", "category", "管理商品分类"},
                {"商品分类查看", "product:category:view", "product", "view", "查看商品分类"},
                {"加工管理", "processing:manage", "processing", "manage", "管理加工项"},
                {"加工单查看", "processing:view", "processing-order", "view", "查看加工单"},
                {"加工单操作", "processing:update", "processing-order", "update", "生成/发加工/取消加工单"},
                {"生产查看", "production:view", "production", "view", "查看生产看板/加工项/工艺配置/计件"},
                {"入库单查看", "inbound:view", "inbound-order", "view", "查看入库单/批次"},
                {"入库单操作", "inbound:create", "inbound-order", "create", "建单/过账/作废入库单"},
                {"知识库管理", "knowledge:manage", "knowledge", "manage", "管理知识库"},
                {"知识库查看", "knowledge:view", "knowledge", "view", "查看知识卡片"},
                {"订单列表", "order:list", "order", "list", "查看订单列表"},
                {"订单详情", "order:detail", "order", "detail", "查看订单详情"},
                // 订单写码（issue #5246 追加单）—— 与 RegistrationService 的目录**逐行同源同序**：
                // 存量租户的角色管理页若不补这两行，就勾不到 order:update/order:create，
                // 而端点已改用写码 ⇒ 老租户的运营岗位**改不了单**（新租户能、老租户不能）。
                {"订单操作", "order:update", "order", "update", "改订单状态/物流/备注/跟进/取消"},
                {"新增订单", "order:create", "order", "create", "创建订单"},
                {"订单退款", "order:refund", "order", "refund", "处理退款/售后工单"},
                {"售后查看", "after_sales:view", "after-sales", "view", "查看售后工单"},
                {"客户管理", "customer:view", "customer", "view", "查看客户"},
                {"客户维护", "customer:create", "customer", "create", "编辑/删除客户与标签"},
                {"财务对账", "finance:view", "finance", "view", "查看财务流水/对账"},
                {"财务操作", "finance:create", "finance", "create", "登记收支流水"},
                // 🔴 描述更正（issue #5642 功能⑤）：原文「米宝对话」那截是 aspirational 的（本码实测
                // 只管 `/api/admin/agent-sessions/*` = 在线接待）⇒ 与 `RegistrationService` 的目录
                // **逐值相等**地更正为「在线接待/会话监控」（两处目录必须同源，判据 9②）。
                {"会话监控", "agent:session", "agent", "session", "在线接待/会话监控"},
                {"会话操作", "agent:session:manage", "agent", "manage", "转接/结束会话/发消息"},
                // 米宝唤出码（issue #5642 功能⑤）：与 `RegistrationService.defaultPermissions`
                // 的同码条目**逐字同源**（名称/资源/动作/描述四项一致）。
                {"米宝对话", "agent:chat", "agent", "chat", "唤出米宝对话（管理员默认/员工需授权）"},
                {"员工列表", "employee:list", "employee", "list", "查看员工列表"},
                {"新增员工", "employee:create", "employee", "create", "新增/编辑/删除员工"},
                {"岗位权限查看", "system:view", "system", "view", "查看岗位与权限目录"},
                {"系统管理", "system:manage", "system", "manage", "企业信息/岗位权限/系统设置"}
        };

        // 查询当前租户已有码
        List<Permission> existing = getPermissionsByTenant(tenantId);
        java.util.Set<String> existingCodes = new java.util.HashSet<>();
        for (Permission p : existing) {
            existingCodes.add(p.getCode());
        }

        int inserted = 0;
        for (String[] row : catalog) {
            if (existingCodes.contains(row[1])) {
                continue; // 已存在，幂等跳过
            }
            Permission permission = Permission.builder()
                    .tenantId(tenantId)
                    .name(row[0])
                    .code(row[1])
                    .resourceType(row[2])
                    .action(row[3])
                    .description(row[4])
                    .status("active")
                    .build();
            permissionMapper.insert(permission);
            inserted++;
        }
        if (inserted > 0) {
            log.info("权限目录补种完成: tenantId={}, inserted={}", tenantId, inserted);
        }
        return inserted;
    }

}