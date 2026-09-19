package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 工艺路线<b>规则表</b>（V71 建表 / V72 扩列，issue #4427 + #4432 = 母单 #4423 P1+P2）。
 * 对应表：{@code production_route_rules}：触发（工艺/选项/…）× 部位限定 → 增删工序 / 覆盖计件系数。
 *
 * <p><b>形态与既有 {@code SPECIAL_OPTION_ROUTINGS} 同构</b> ⇒ 工艺变体与特殊选项统一进同一张表
 * （= #4365 阶段 2 目标）。P2 起它是<b>唯一</b>的规则真值源：旧 {@code production_option_routings} /
 * {@code production_option_factors} 的读取点全部改读本表，旧表行软删（issue #4432 §六·补）。</p>
 *
 * <p><b>三种 {@code action}</b>（{@code V72} 把 CHECK 放宽为 {@code ('insert','remove','factor')}）：</p>
 * <ul>
 *   <li>{@code insert} —— 把 {@code operation} 插到 {@code afterOperation} <b>之后</b>；
 *       锚点不在序列中 ⇒ <b>追加末尾</b>（与 {@code routing.py::_insert_after} 逐字同款）；</li>
 *   <li>{@code remove} —— 从序列里删掉 {@code operation}；</li>
 *   <li>{@code factor} —— 把命中工序的计件系数<b>覆盖</b>为 {@code factor}
 *       （{@code operation} 为空 = <b>平摊档</b>，该触发对该部位全部工序生效）。</li>
 * </ul>
 *
 * <p><b>⚠️ 顺序敏感（{@code priority} 升序生效）</b>：例「韩褶 + 布帘 insert 上车布 after 韩褶」
 * 必须排在「韩褶 insert 韩褶 after 三边」之后，否则锚点「韩褶」还不存在 ⇒ 上车布被追加到末尾
 * （工序顺序错 = 车间按错顺序干）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "production_route_rules", autoResultMap = true)
public class ProductionRouteRule {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 触发类型：{@code craft} / {@code option} / {@code shaped} / {@code processing_item} */
    private String triggerKind;

    /** 触发值：工艺名 / 特殊选项名（**逐字 = ERP 写法**，它是「订单选配 → 车间工序」的 join key） */
    private String triggerValue;

    /** 部位限定（布帘/纱帘/帘头）；{@code NULL} = 不限部位 */
    private String position;

    /** {@code insert} / {@code remove} / {@code factor} */
    private String action;

    /**
     * 要增/删/覆盖系数的<b>逻辑工序名</b>；{@code NULL} = 平摊档（仅 {@code action='factor'} 允许）。
     *
     * <p>V72 起可空 —— 与 {@code OPTION_FACTOR_SCOPES} 的「{@code operation_name} 为空 ⇒ 平摊」逐字一致。</p>
     */
    private String operation;

    /** {@code insert} 的锚点（逻辑工序名）；{@code NULL} = 追加末尾 */
    private String afterOperation;

    /** 生效顺序（**升序**，同序按声明顺序） */
    private Integer priority;

    /** 计件系数（仅 {@code action='factor'} 时有值；同一触发内后档覆盖前档） */
    private BigDecimal factor;

    /**
     * 该**特殊选项**对**顾客**的**元/套**单价（V77 加列，issue #4525；设计 §4.1）。
     *
     * <p><b>对客售价账（L3②）</b>：{@code NULL} = <b>未定价</b>（≠ 0）⇒ 取价侧必须显式可见
     * （{@code special_options[].priced=false} + 可行动 hint），<b>不得静默按 0 收</b>。
     * 只有 {@code triggerKind='option'} 行才有值；{@code craft} / {@code shaped} / {@code factor}
     * 行一律 {@code NULL}（工艺变体不按套收费）。</p>
     *
     * <p>⚠️ <b>计件路径绝不读本列</b>：{@code ProductionService} / {@code piecework} 与
     * {@link #factor} / {@code production_operations.unit_price} 是给工人付的成本账，
     * 与本列（对客售价）两套账不互读 —— 列名的 {@code customer_} 前缀就是让这条纪律
     * <b>在 grep 层可判</b>（本表同时承载车间路由语义与对客价语义）。</p>
     */
    private BigDecimal customerUnitPrice;

    private String status;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    private Integer deleted;
}
