package com.migao.admin.dto.agent;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import lombok.Data;

import java.util.List;

/**
 * 批量更新 —— 创建批次（= 预演）请求（issue #5314 冻结契约）。
 *
 * <pre>
 * POST /api/admin/agent/batches
 * req  {batchType, items:[{resourceId, field, oldValue, newValue}]}
 * resp {batchId, itemCount, status:"preview"}
 * </pre>
 *
 * <p><b>两段确认的第二段载体</b>：Agent 侧先用只读工具解析候选 → {@code interact(multiSelect)} 勾选，
 * 再把「逐条 before → after」交到这里冻结 ⇒ 预览表与落库依据是<b>同一份</b>。
 * 故 {@code oldValue} 不是装饰：服务端会拿它与 DB 当前值逐条核对（按**值**比对，
 * 数字不比字符串写法），不符即拒绝 —— 撤销的唯一依据不允许是调用方的一面之词。</p>
 *
 * <p>{@code batchType} 只做两个具名批量（{@code product_price} / {@code product_status}）：
 * 具名批量的可逆性与预览形态是确定的，通用批量不是。</p>
 */
@Data
public class AgentBatchCreateRequest {

    /** 白名单：product_price（商品级统一定价批量改价）/ product_status（批量上/下架）。 */
    @NotBlank(message = "batchType 不能为空")
    private String batchType;

    /** 批次条目（≤ 50 条；同一 resourceId 不得重复出现）。 */
    @NotEmpty(message = "items 不能为空")
    @Valid
    private List<Item> items;

    /** 一条 = 一个资源的一个字段的 before → after。 */
    @Data
    public static class Item {

        /** 资源 ID（商品 ID，逐字；名称解析留给单条路径 —— 批量条目必须精确可寻址）。 */
        @NotBlank(message = "resourceId 不能为空")
        private String resourceId;

        /** 字段名（product_price ⇒ basePrice / product_status ⇒ status）。 */
        @NotBlank(message = "field 不能为空")
        private String field;

        /**
         * 改前值（撤销的唯一依据）。服务端与 DB 当前值核对后，落库的是 **DB 真值**；
         * 可空 = 由服务端自行采集（Agent 侧正常都会带上，两段确认需要它渲染预览）。
         */
        private String oldValue;

        /** 改后值（执行时写入）。 */
        @NotBlank(message = "newValue 不能为空")
        private String newValue;
    }
}