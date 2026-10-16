package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.PieceworkSettlementService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 计件结算单（issue #5653）—— 商家侧**生成 / 列 / 详情 / 作废**四个动作。
 *
 * <p>端点族 = 类级 {@code /api/admin/production/piecework} + 方法级 {@code /settlements…}
 * （四个端点逐条写全路径：路径级解析器只认「注解里带字符串字面量」的方法映射 ——
 * 无参 {@code @PostMapping} 在判据的源码面取不到，届时「端点不存在」会判红）。与既有只读报表
 * （{@code GET /api/admin/production/piecework/summary}）**同族同源** —— 结算金额逐值取自那份聚合。</p>
 *
 * <h2>🔴 「生成即冻结」的接口层形态（判据必须能证伪「改得动」）</h2>
 * 本类**只有** {@code POST}（生成 / 作废）与 {@code GET}（列 / 详情）—— 物理上**没有**
 * {@code PUT} / {@code PATCH} / {@code DELETE} 映射，服务层与 Mapper 也**没有**任何改写金额 / 期间 /
 * 工人的方法 ⇒ 对已生成单的任何更新动词在路由层就是 **404/405**。
 * 「不可改」因此是**接口层不存在**，不是「前端不给按钮」。
 *
 * <h2>权限（子菜单粒度：读 {@code production:view} / 写 {@code processing:manage}）</h2>
 * 复用既有两个码，**不新造码**：
 * <ul>
 *   <li><b>读</b> {@code production:view} —— 与「计件工资」页第一屏读端点
 *       {@code GET /production/piecework/summary} 逐字同码（同一页的读数不拆码）；</li>
 *   <li><b>写</b> {@code processing:manage} —— 结算单生成 / 作废是**加工工资口径的管理动作**，
 *       与本域既有管理写面（工序库写面 / 部位价目矩阵 {@code PUT /operation-positions/{id}} /
 *       补价 {@code POST /orders/{id}/repricing}）同码。🔴 **刻意不用** {@code production:execute}：
 *       那个码由 issue #5699 的 I4 台账具名把守**恰好四条**执行类写端点
 *       （实例化 / 报工 / 打印 / 发货 —— 「谁在车间干了活」），判据是「零外溢」；
 *       把结算单挂上去会**放宽**那条不变量，而结算不是执行类动作（本仓授权变更必须显式裁）。</li>
 * </ul>
 * 四个端点**逐个声明**（不靠类级兜底 —— 「未注解端点」是 `test_agent_permission_parity` 的判据 8，
 * 沉默放行正是它要治的形态）。
 */
@RestController
@RequestMapping("/api/admin/production/piecework")
@RequiredArgsConstructor
public class PieceworkSettlementController {

    private final PieceworkSettlementService settlementService;

    /**
     * 生成结算单（期间 × 工人）—— **生成即冻结**。
     * POST /api/admin/production/piecework/settlements  body: {@code {period:"YYYY-MM", worker_name:"张三"}}
     *
     * <p>金额逐值取自 {@code GET /production/piecework/summary?period=…&worker_name=…} 的 {@code total}。
     * 同期间同工人已有生效单 ⇒ **409** {@code PIECEWORK_SETTLEMENT_EXISTS}（可行动提示 = 先作废再重开）；
     * 该期间该工人无可结金额 ⇒ **422** {@code PIECEWORK_SETTLEMENT_NO_AMOUNT}（未定价 ≠ ¥0.00，
     * 不落 0 元单）。</p>
     */
    @PostMapping("/settlements")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> generate(@RequestBody(required = false) Map<String, Object> body) {
        return ApiResponse.success(settlementService.generate(
                asText(body, "period"), asText(body, "worker_name"), TenantContext.getTenantId()));
    }

    /**
     * 结算单列表（期间可选；**默认含已作废** —— 旧单留痕、可查）。
     * GET /api/admin/production/piecework/settlements?period=YYYY-MM[&include_voided=false]
     */
    @GetMapping("/settlements")
    @RequirePermission("production:view")
    public ApiResponse<Map<String, Object>> list(
            @RequestParam(required = false) String period,
            @RequestParam(name = "include_voided", required = false) Boolean includeVoided) {
        return ApiResponse.success(settlementService.list(period, includeVoided, TenantContext.getTenantId()));
    }

    /**
     * 结算单详情（冻结快照 + 该期间现取的报表读数 —— 同源在消费面上可见）。
     * GET /api/admin/production/piecework/settlements/{id}
     */
    @GetMapping("/settlements/{id}")
    @RequirePermission("production:view")
    public ApiResponse<Map<String, Object>> detail(@PathVariable String id) {
        return ApiResponse.success(settlementService.detail(id, TenantContext.getTenantId()));
    }

    /**
     * 作废结算单（**不物理删**；留痕谁 / 何时 / 为什么）。
     * POST /api/admin/production/piecework/settlements/{id}/void  body: {@code {reason:"..."}}
     *
     * <p>作废是**唯一**让某期间某工人能重开结算单的动作（期间唯一性只约束活跃单）。</p>
     */
    @PostMapping("/settlements/{id}/void")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> voidSettlement(@PathVariable String id,
                                                           @RequestBody(required = false) Map<String, Object> body) {
        return ApiResponse.success(settlementService.voidSettlement(
                id, asText(body, "reason"), TenantContext.getTenantId()));
    }

    /** body 取文本（空白 ⇒ null；与 {@code ProductionController.asText} 同语义）。 */
    private static String asText(Map<String, Object> body, String key) {
        if (body == null || body.get(key) == null) {
            return null;
        }
        String value = String.valueOf(body.get(key));
        return value.isBlank() ? null : value;
    }
}
