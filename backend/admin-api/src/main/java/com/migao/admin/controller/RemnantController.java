package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.RemnantViews;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.RemnantService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 余料成本回收端点（V122，issue #5146）。
 *
 * <ul>
 *   <li>{@code GET  /api/admin/production/remnants} —— 余料台账（列表 + 回收率/报废率汇总一次回）</li>
 *   <li>{@code GET  /api/admin/production/remnants/small-item-specs} —— 小件用料尺寸表（**可配参数**）</li>
 *   <li>{@code PUT  /api/admin/production/remnants/small-item-specs} —— 全量替换（空列表 = 清空 = 未配置）</li>
 *   <li>{@code GET  /api/admin/production/remnants/match} —— 小件优先匹配（不产生任何推荐时**说明原因**）</li>
 *   <li>{@code POST /api/admin/production/remnants/{id}/recover} —— 回收记账（冲减用它的那张单）</li>
 *   <li>{@code POST /api/admin/production/remnants/{id}/scrap} —— 报废留痕（谁 / 何时 / 为什么）</li>
 * </ul>
 *
 * <p><b>权限 {@code processing:manage}</b>：与算料配置 / 工序库 / 工艺路线的写面同口径
 * （同属「生产口径配置」，共用同一权限码 —— 新开权限码会让既有 operator 岗位凭空多一处授权缺口）。
 * 类级声明即对全部端点生效。</p>
 *
 * <p>🔴 <b>本控制器不判任何口径、不算任何钱</b>：尺寸判定、同缸号优先、回收额、
 * 「未配置 ⇒ 不推荐」全在 {@link RemnantService}（可被单测逐值判红）；控制器只做参数搬运
 * 与租户上下文注入。</p>
 *
 * <p>🔴 <b>余料不是资产</b>：本控制器的任何端点都**不读也不写**库存金额
 * （{@code product_skus.cost_amount} / {@code stock_ledger_entries}）；
 * 台账读面也不出现在库存/资产读面里（静态判据 {@code RemnantNonAssetGuardTest}）。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/production/remnants")
@RequiredArgsConstructor
@RequirePermission("processing:manage")
public class RemnantController {

    private final RemnantService remnantService;

    /** 余料台账 + 汇总（度量与明细同一次回，前端不必发第二个请求）。 */
    @GetMapping
    public ApiResponse<RemnantViews.LedgerView> ledger(
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String batchNo,
            @RequestParam(required = false) String orderNo,
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size) {
        return ApiResponse.success(remnantService.ledger(
                TenantContext.getTenantId(), status, batchNo, orderNo, page, size));
    }

    /**
     * 小件用料尺寸表（§22 P3 的读面：{@code configured=false} ⇒ {@code notice} 说明「未启用」）。
     *
     * <p>前端「参数总览 → 余料回收」用它渲染**当前值**与**默认值可见**两件事。</p>
     */
    @GetMapping("/small-item-specs")
    public ApiResponse<RemnantViews.SpecsView> smallItemSpecs() {
        return ApiResponse.success(remnantService.specs(TenantContext.getTenantId()));
    }

    /**
     * 写小件用料尺寸表（**全量替换**）。
     *
     * <p>body = {@code {items: [{item_key, length_m, width_m, note?}]}}；
     * {@code items} 为空数组 ⇒ **清空** ⇒ 回到「未配置」（匹配随即不产生任何推荐 + 显式说明）。
     * 非法值 ⇒ {@code 422 + error.details:[{field,message}]} 逐条理由（不静默取整、不静默跳过）。</p>
     */
    @PutMapping("/small-item-specs")
    @SuppressWarnings("unchecked")
    public ApiResponse<RemnantViews.SpecsView> putSmallItemSpecs(@RequestBody Map<String, Object> body) {
        Object raw = body == null ? null : body.get("items");
        List<Map<String, Object>> items = raw instanceof List<?> list
                ? (List<Map<String, Object>>) list : List.of();
        return ApiResponse.success(remnantService.putSpecs(TenantContext.getTenantId(), items));
    }

    /**
     * 小件优先匹配（**只读**，不占余料、不记账）。
     *
     * @param orderItemId 订单明细行 id（小件需求来自该行勾选的特殊选项）
     * @param batchNo     该行实际领料的批次号（可空 ⇒ 服务层从批次消耗台账反查）
     */
    @GetMapping("/match")
    public ApiResponse<RemnantViews.MatchView> match(
            @RequestParam String orderItemId,
            @RequestParam(required = false) String batchNo) {
        return ApiResponse.success(remnantService.match(
                TenantContext.getTenantId(), orderItemId, batchNo));
    }

    /**
     * 回收记账：余料被用掉 ⇒ 状态转「已用」+ 回收额 = 用掉米数 × **该批次当时均价**
     * （冲减 {@code usedByOrderNo} 那张单的面料成本）。
     *
     * <p>🔴 <b>不新增任何批次消耗</b>（判据 3）：小件的料来自已经领下来的余料。</p>
     */
    @PostMapping("/{id}/recover")
    public ApiResponse<RemnantViews.RemnantLine> recover(@PathVariable Long id,
                                                         @RequestBody Map<String, Object> body) {
        return ApiResponse.success(remnantService.recover(TenantContext.getTenantId(), id,
                str(body, "orderItemId"), str(body, "orderNo"), str(body, "itemKey")));
    }

    /** 报废留痕：超期 / 尺寸不足 ⇒ 报废（原因必填 —— 留痕要答得出「为什么」）。 */
    @PostMapping("/{id}/scrap")
    public ApiResponse<RemnantViews.RemnantLine> scrap(@PathVariable Long id,
                                                       @RequestBody Map<String, Object> body) {
        return ApiResponse.success(remnantService.scrap(
                TenantContext.getTenantId(), id, str(body, "reason")));
    }

    private static String str(Map<String, Object> body, String key) {
        Object value = body == null ? null : body.get(key);
        if (value == null) {
            return null;
        }
        String text = String.valueOf(value).trim();
        return text.isEmpty() ? null : text;
    }
}
