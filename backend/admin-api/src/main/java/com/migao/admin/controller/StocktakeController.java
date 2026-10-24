package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.StocktakeView;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.ApprovalService;
import com.migao.admin.service.StocktakeService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 盘点（issue #7373，P1-1 段 2）。
 *
 * <p>授权零 delta：与仓/库存同域 ⇒ 读 `inbound:view`、写 `inbound:create`（不新造权限码）。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/stocktakes")
@RequiredArgsConstructor
public class StocktakeController {

    private final StocktakeService stocktakeService;

    /** 列表：`GET /api/admin/stocktakes`。 */
    @GetMapping
    @RequirePermission("inbound:view")
    public ApiResponse<List<StocktakeView>> list() {
        return ApiResponse.success(stocktakeService.list());
    }

    /** 详情：`GET /api/admin/stocktakes/{id}`。 */
    @GetMapping("/{id}")
    @RequirePermission("inbound:view")
    public ApiResponse<StocktakeView> detail(@PathVariable String id) {
        return ApiResponse.success(stocktakeService.detail(id));
    }

    /**
     * 出盘点任务：`POST /api/admin/stocktakes?warehouseId=`。
     *
     * <p>账面数是**出任务当刻**的快照（该仓有货的全部批次）。</p>
     */
    @PostMapping
    @RequirePermission("inbound:create")
    public ApiResponse<StocktakeView> open(@RequestParam Long warehouseId,
                                           @RequestParam(required = false) String note) {
        log.info("[stocktake] 出任务 warehouse={}", warehouseId);
        return ApiResponse.success(stocktakeService.open(warehouseId, note, currentOperator()));
    }

    /**
     * 录实盘：`POST /api/admin/stocktakes/{id}/count`，body `{"counts": {"<batchId>": 12.5}}`。
     */
    @PostMapping("/{id}/count")
    @RequirePermission("inbound:create")
    public ApiResponse<StocktakeView> count(@PathVariable String id,
                                            @RequestBody Map<String, Object> body) {
        Object raw = body == null ? null : body.get("counts");
        Map<Long, BigDecimal> counts = new LinkedHashMap<>();
        if (raw instanceof Map<?, ?> map) {
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                Long batchId = Long.valueOf(String.valueOf(entry.getKey()));
                counts.put(batchId, entry.getValue() == null
                        ? null : new BigDecimal(String.valueOf(entry.getValue())));
            }
        }
        return ApiResponse.success(stocktakeService.record(id, counts));
    }

    /**
     * 完成盘点：`POST /api/admin/stocktakes/{id}/complete`。
     *
     * <p>🔴 有差异且没有已通过的「盘点差异」审批 ⇒ **写面直接拒**（不是前端提示）。</p>
     */
    @PostMapping("/{id}/complete")
    @RequirePermission("inbound:create")
    public ApiResponse<StocktakeView> complete(@PathVariable String id) {
        return ApiResponse.success(stocktakeService.complete(id));
    }

    /** 作废：`POST /api/admin/stocktakes/{id}/cancel`。 */
    @PostMapping("/{id}/cancel")
    @RequirePermission("inbound:create")
    public ApiResponse<StocktakeView> cancel(@PathVariable String id) {
        return ApiResponse.success(stocktakeService.cancel(id));
    }

    /** 当前操作人（只从服务端安全上下文取）。 */
    private ApprovalService.Operator currentOperator() {
        var authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication != null
                && authentication.getPrincipal() instanceof SecurityUser user) {
            return new ApprovalService.Operator(user.getUserId(), user.getDisplayName());
        }
        return null;
    }
}
