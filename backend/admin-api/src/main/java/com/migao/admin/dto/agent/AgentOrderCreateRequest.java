package com.migao.admin.dto.agent;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.migao.admin.dto.OrderCreateRequest;
import lombok.Data;
import lombok.EqualsAndHashCode;

/**
 * Agent 下单请求 —— **人工路径 {@link OrderCreateRequest} 的子类型**（issue #4089 · A17 收敛）。
 *
 * <p><b>为什么是继承而不是第二套定义</b>：修复前本类是一份**平行 DTO**（自己的 {@code AgentOrderItem}、
 * 自己的一套注解），与表单 DTO 实测产生 **13 处分歧**（issue #4089 清单）：字段位置不同
 * （{@code skuCode}/{@code colorName} 顶层 vs {@code processingInfo} 内）、必填性/边界不同
 * （{@code subtotal} 可选 vs 必填）、{@code items} 无非空约束、{@code productName} 无非空约束……
 * 更贵的是 `OrderService.createOrderForAgent` 只能**手工 {@code new OrderCreateRequest}** 逐字段搬运
 * 再转交 —— 程序化构造的 Bean **不过 Bean Validation**，于是 Service 又得把那套判定**再写一遍**
 * （= 「校验双写」，两处口径必然漂移）。</p>
 *
 * <p><b>收敛后的口径</b>：本类只保留必需的幂等键，**其余字段与全部约束都继承自共享类型**
 * （唯一来源）。两条路径共用同一个 Validator、同一组注解、同一条文案；agent 侧只允许**收紧**
 * （在共享类型上加约束），不允许放宽 —— 由 {@code OrderDtoContractTest} 锁死。</p>
 *
 * <p><b>明细字段</b>：直接用继承来的 {@code List<OrderCreateRequest.OrderItemRequest>}
 * （不存在第二套明细类型）。SKU 规格键（{@code skuCode}/{@code colorName}）**只在
 * {@code processingInfo} 内**——这是唯一生产者（ai-agent {@code order_create} 工具）的真实形态，
 * 也是表单页的形态；服务端取价与库存两条路径都从 {@code processingInfo} 解析。</p>
 */
@Data
@EqualsAndHashCode(callSuper = true)
public class AgentOrderCreateRequest extends OrderCreateRequest {

    /**
     * 客户端幂等键（issue #4037）—— 由 {@code AgentOrderController} 从请求头
     * {@code X-Client-Request-Id} 注入，**不是业务字段**：不落 orders 表、不参与校验，
     * 仅供服务端做 {@code (tenant_id, client_request_id)} 去重与结果回放。
     *
     * <p>{@code @JsonIgnore}：请求体里的同名 JSON 字段一律忽略 —— 幂等键**只认请求头**，
     * 否则调用方可自选键绕过「同键只执行一次」（也能避免 body 值覆盖服务端注入的头值）。</p>
     */
    @JsonIgnore
    private String clientRequestId;
}