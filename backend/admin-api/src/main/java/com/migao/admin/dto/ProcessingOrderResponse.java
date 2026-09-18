package com.migao.admin.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;

/**
 * 加工单响应 DTO（issue #3340）
 */
@Data
public class ProcessingOrderResponse {

    private String id;
    private String tenantId;
    private String orderId;
    private String orderNo;
    private String customerName;
    private String customerPhone;
    private String processingOrderNo;
    private String processor;
    private LocalDate expectedDeliveryDate;
    private String status;
    /** 快照明细：不含销售价（决策 2），加工项含 options */
    private List<ProcessingOrderItemBrief> items;
    private String remark;
    private Integer templateVersion;
    private OffsetDateTime generatedAt;
    private OffsetDateTime issuedAt;
    private OffsetDateTime inProcessingAt;
    private OffsetDateTime completedAt;
    private OffsetDateTime cancelledAt;
    private String cancelledReason;
    private Integer printCount;

    /**
     * 本单**实际使用**的路线键「帘种×工艺」（V60，issue #4308）。
     * T1/T2 时 = 默认 {@code 布帘×韩褶}；多部位订单取最需关注的一条
     * （{@code default} &gt; {@code missing_route} &gt; {@code partial} &gt; {@code derived}）。
     */
    private String routeKey;

    /**
     * 本单**派生出来想用**的路线键（V60，issue #4308）；两维全不命中时为 null。
     * {@code missing_route} 的提示靠它说出「识别的 X 在库里没有路线」。
     */
    private String routeRequestedKey;

    /**
     * 路线键来源（V60，issue #4308）：{@code derived} / {@code partial}（补信号）/
     * {@code missing_route}（建路线）/ {@code default}（补信号）。
     */
    private String routeSource;

    /**
     * 快照明细项
     */
    @Data
    public static class ProcessingOrderItemBrief {
        /**
         * 订单明细行 id（issue #4354；issue #4387 语义扩展）：**樘窗绑组**用 —— `craftLineId`
         * 按设计文档 §4.8 取「主布行的 {@code order_item.id}」，配布边行填的就是它。进快照是为了让
         * 「一樘窗 = 一组」这件事在**固化真相**里自解释（缺 `craftLineId` 时它就是本行自己的组键）。
         */
        private String itemId;
        private String productName;
        private String sku;
        private String colorName;
        private String sellingMethod;
        private String doorWidth;
        private BigDecimal width;
        private BigDecimal height;
        private BigDecimal quantity;
        private String unit;
        /** 加工项：含 id/name/unitPrice/quantity/unit/options（options 生成时从加工项目录补齐） */
        private List<ProcessingItemSnapshot> processingItems;
        /**
         * 下单勾选的**特殊选项**（issue #4230 v1a：订单侧新携带 {@code specialOptions: string[]}，
         * 落在既有 processingInfo JSONB 内，无需迁移）。
         *
         * <p>用 {@code Object} 而非 {@code List<String>}：脏数据（非数组形态）不得让整份快照解析
         * 失败 —— 快照里出现本字段而 DTO 没声明时，Jackson 的未知属性会让 {@code items} 整段
         * 变成 null（响应静默退化）；用 Object 同时解决「字段缺失」与「形态不干净」两种形态。</p>
         */
        private Object specialOptions;
        private String remark;

        // ── 工艺规格（craft spec，issue #4354 / 设计文档 §4.9 第③处展示）──────────────
        //
        // 快照（`items_snapshot`）是加工单的**固化真相**；下面这些键由订单侧下单时原样落库
        // （§4.2 / §4.3），本 DTO 逐键声明 —— **漏一个键，响应里 `items` 就整段变 null**
        // （Jackson 未知属性 ⇒ `toResponse` 的 convertValue 抛错被 catch ⇒ 静默退化）。
        //
        // 一律用 `Object`（同 `specialOptions` 的理由）：工艺规格来自多个写面（ai-agent /
        // 下单页 / 商家补录），形态不干净时**不得**让整份快照解析失败；取值一律**逐字透传**
        // 订单已落库的值，Java 不发明、不归一（缺键就是 null）。

        /** 部位/帘种（`布帘` / `纱帘` / `帘头`，与工序库 `production_routings.curtain_type` 同枚举）。 */
        private Object curtainType;
        /** 安装工艺（`韩褶` / `打孔` / `四爪钩` / `穿杆` / `平幔`）。 */
        private Object craft;
        /** 加工类型（`定高买宽` / `定宽买高`）。 */
        private Object cuttingMode;
        /** 打开方式（**开数**，正整数：`1` / `2` / `3` / `4` …，不是固定枚举；issue #4387 判据 1）。 */
        private Object openCount;
        /** 是否定型：`false` ⇒ 实例化时已剔除 `定型-布` / `复烫-布`（本包接线）。 */
        private Object isShaped;
        /** 褶距（米）。 */
        private Object pleatSpacing;
        /** 是否对花。 */
        private Object hasPattern;
        /** 花距（米）。 */
        private Object patternRepeat;
        /** 款式（`单色` / `拼色`）。 */
        private Object style;
        /** 房间名。 */
        private Object room;
        /** 面料批号。 */
        private Object batchNo;
        /** 明细行角色（`主布` / `配布边` / `纱`；缺省视为 `主布`）。 */
        private Object componentRole;
        /**
         * **樘窗**（一个窗户）的绑组标识（issue #4354 引入；issue #4387 语义扩展为「樘窗分组」）：
         * 同组 = 同一樘窗，是套级工序（#4384）与加工费（#4386）的归属层级。
         *
         * <p>⚠️ **不是「同组只生成一个部位」**（那是 #4354 只用于配布边吸收时的旧口径）：
         * 部位 = `order_items` 行 = 一件帘（布帘 / 纱帘 / 帘头）⇒ **布行与纱行同组时各成一个部位**，
         * 只有 `componentRole=配布边` 的行不独立成部位。判据见
         * {@code ProcessingOrderServiceTest#clothPlusSheerWindowProducesTwoPositions}。</p>
         */
        private Object craftLineId;
        /** 配布边米数来源（`跟随主布` / `人工指定`）。 */
        private Object metersSource;
        /** 加工费米数（= 主布行米数；配布边米数不参与）。 */
        private Object processingMeters;

        // ── 算料输出（§4.3；键名 snake_case 与 CALC_INFO_KEYS / routing.py 同口径，**不改名**）──
        //
        // ⚠️ 必须显式 `@JsonProperty`：全局 ObjectMapper **没有** SNAKE_CASE 命名策略
        // （快照其余键都是 camelCase），不标注 ⇒ 键映射不上 ⇒ 这几个字段恒为 null（静默）。

        /** 面料米数。 */
        @JsonProperty("fabric_meters")
        private Object fabricMeters;
        /** 总褶数。 */
        @JsonProperty("pleat_count")
        private Object pleatCount;
        /** 折数（每片）。 */
        @JsonProperty("per_panel_pleats")
        private Object perPanelPleats;
        /** 幅数（定宽买高）。 */
        @JsonProperty("panels")
        private Object panels;
        /** 打孔孔数。 */
        @JsonProperty("holes")
        private Object holes;
        /** 理论褶倍。 */
        @JsonProperty("fullness")
        private Object fullness;
        /** 实际褶倍。 */
        @JsonProperty("fullness_actual")
        private Object fullnessActual;
    }

    @Data
    public static class ProcessingItemSnapshot {
        private String id;
        private String name;
        private BigDecimal unitPrice;
        private BigDecimal quantity;
        private String unit;
        private Object options;
    }
}
