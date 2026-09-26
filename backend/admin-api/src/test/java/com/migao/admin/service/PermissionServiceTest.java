// case_ids: HR-004

package com.migao.admin.service;

import com.migao.admin.entity.Permission;
import com.migao.admin.mapper.PermissionMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/**
 * PermissionService 单元测试
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("PermissionService 权限服务测试")
class PermissionServiceTest {

    @Mock
    private PermissionMapper permissionMapper;

    @InjectMocks
    private PermissionService permissionService;

    @Test
    @DisplayName("getAllPermissions — 返回激活且未删除的权限")
    void getAllPermissions_returnsActiveUndeleted() {
        Permission p1 = new Permission();
        p1.setId("1");
        p1.setCode("product:list");
        p1.setName("商品列表");
        p1.setDeleted(0);
        p1.setStatus("active");

        Permission p2 = new Permission();
        p2.setId("2");
        p2.setCode("order:list");
        p2.setName("订单列表");
        p2.setDeleted(0);
        p2.setStatus("active");

        when(permissionMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(p1, p2));

        List<Permission> result = permissionService.getAllPermissions();

        assertThat(result).hasSize(2);
        assertThat(result.get(0).getCode()).isEqualTo("product:list");
    }

    @Test
    @DisplayName("getPermissionsByTenant — 按租户过滤")
    void getPermissionsByTenant_filtersByTenant() {
        when(permissionMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of());

        List<Permission> result = permissionService.getPermissionsByTenant(1L);

        assertThat(result).isEmpty();
        verify(permissionMapper).selectList(any(LambdaQueryWrapper.class));
    }

    @Test
    @DisplayName("getPermissionByCode — 找到权限返回 Permission")
    void getPermissionByCode_found() {
        Permission p = new Permission();
        p.setId("1");
        p.setCode("product:list");
        when(permissionMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(p);

        Permission result = permissionService.getPermissionByCode("product:list");

        assertThat(result).isNotNull();
        assertThat(result.getCode()).isEqualTo("product:list");
    }

    @Test
    @DisplayName("getPermissionByCode — 不存在返回 null")
    void getPermissionByCode_notFound() {
        when(permissionMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);

        Permission result = permissionService.getPermissionByCode("nonexistent");

        assertThat(result).isNull();
    }

    @Test
    @DisplayName("createPermission — code 不重复则创建成功")
    void createPermission_codeNotExists_success() {
        when(permissionMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);
        when(permissionMapper.insert(any(Permission.class))).thenReturn(1);

        Permission p = new Permission();
        p.setCode("new:perm");
        p.setName("新权限");

        boolean result = permissionService.createPermission(p);

        assertThat(result).isTrue();
        verify(permissionMapper).insert(any(Permission.class));
    }

    @Test
    @DisplayName("createPermission — code 已存在返回 false")
    void createPermission_codeExists_returnsFalse() {
        Permission existing = new Permission();
        existing.setCode("existing:perm");
        when(permissionMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(existing);

        Permission p = new Permission();
        p.setCode("existing:perm");

        boolean result = permissionService.createPermission(p);
        assertThat(result).isFalse();
        verify(permissionMapper, never()).insert(any(Permission.class));
    }

    @Test
    @DisplayName("ensureFullPermissionCatalog — 幂等补种缺失的细粒度权限码")
    void ensureFullPermissionCatalog_backfillsMissingCodes() {
        // 存量租户仅有 5 条旧大类码
        Permission old = new Permission();
        old.setCode("dashboard:view");
        when(permissionMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(old));
        // insert 返回 1
        when(permissionMapper.insert(any(Permission.class))).thenReturn(1);

        int inserted = permissionService.ensureFullPermissionCatalog(1L);

        // 目录 30 码 - 已有 1 码 = 应补 29 码（#3081 快捷回复权限 agent:quickreply 已随功能下线移除）。
        // issue #5246 两批共加 7 码：2 个读码（after_sales:view / knowledge:view）
        // + 5 个写码（order:update / order:create / customer:create / finance:create / agent:session:manage）。
        // 数字**故意写死**：本方法正是「**存量**租户拿新码」的路径 ⇒ 目录少一行/多一行都必须让本用例红
        // （否则「新租户有、老租户没有」会静默复发）。
        // issue #5291：三个域新增**读**码（product:category:view / production:view / system:view）
        // ⇒ 27 → 30（应补 26 → 29）。本用例正是「**存量**租户拿新码」的路径。
        // issue #5642 功能⑤：新增**一个**码 `agent:chat`（米宝唤出权）⇒ 30 → 31（应补 29 → 30）。
        assertThat(inserted).isEqualTo(30);
        // 补种的码应含 order:list / employee:create / finance:view（此前角色管理无法授予）
        // + 本单的读码与写码（存量租户的运营/客服/财务要靠它们才能改单、转接会话、记账）
        verify(permissionMapper, atLeastOnce()).insert(argThat((Permission p) ->
                "order:list".equals(p.getCode()) || "employee:create".equals(p.getCode())
                        || "finance:view".equals(p.getCode()) || "customer:view".equals(p.getCode())
                        || "after_sales:view".equals(p.getCode()) || "knowledge:view".equals(p.getCode())
                        || "order:update".equals(p.getCode()) || "order:create".equals(p.getCode())
                        || "customer:create".equals(p.getCode()) || "finance:create".equals(p.getCode())
                        || "agent:session:manage".equals(p.getCode())
                        || "product:category:view".equals(p.getCode())
                        || "production:view".equals(p.getCode())
                        || "system:view".equals(p.getCode())
                        // issue #5642 功能⑤：米宝唤出码 —— 存量租户的角色管理页必须能勾到它，
                        // 否则「上线当天批量授权」（裁定⑧ 的交付物）在存量租户上无入口
                        || "agent:chat".equals(p.getCode())));
    }
}

