package com.migao.admin.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;

/**
 * 入库标签**详情读面**（issue #5052 P2；设计 §5.2 / §7.1）—— 功能②（拍照补打）的硬依赖。
 *
 * <p>字段集 = 「工人扫到 / 拍到一张标签后，要能核对并重打一张 <b>50×30mm</b> 标签」所需的全部内容：
 * 短码原文 + 品名 / 色号 / 门幅 / 米数 + 供应商 + 入库日期（+ 单号 / 批次号 / 货号 / 缸号做对账锚点）。
 * P3 用它渲染（设备侧 canvas，与洗水码同款范式），<b>不需要</b>服务端位图（§7.2 已改判为设备侧渲染）。</p>
 *
 * <p>🔴 这里**只有字段、没有图**：{@code GET .../bitmap} 不在本包（用户已改判为设备侧渲染）
 * ⇒ 结构上不存在「拿到位图就能本地直打、绕过 {@code /print}」的旁路（§7.3「打印必留痕」）。</p>
 */
@Data
@JsonInclude(JsonInclude.Include.NON_NULL)
public class InboundLabelView {

    /** 短码原文（P3 拼 {@code https://<稳定域名>/i/<短码>}；域名由前端单一配置给，服务端不硬编码） */
    private String shortCode;

    /** 入库单号 {@code RK-yyyyMMdd-NNNN} */
    private String inboundNo;

    /** 明细行 id（一个 SKU 行 = 一个批次 = 一张标签） */
    private Long itemId;

    /** 货号快照 */
    private String skuCode;

    /** 品名（{@code products.name}，实读时取；商品已删 ⇒ null，不编造） */
    private String productName;

    /** 色号 */
    private String colorName;

    /** 门幅 */
    private String doorWidth;

    /** 入库数量（米，1 位小数：与 {@code product_skus.stock} 粒度一致） */
    private BigDecimal quantity;

    /** 供应商缸号（外部事实，可空） */
    private String dyeLot;

    /** 系统批次号 {@code PC-yyyyMMdd-NNNN}（过账后才有） */
    private String batchNo;

    /** 供应商（文本，MVP 不建主数据） */
    private String supplier;

    /** 供应商送货单号 */
    private String supplierDocNo;

    /** 仓库 / 仓位 */
    private String warehouse;

    /** 入库日期（业务日期） */
    private LocalDate inboundDate;

    /** 标签生成时间（= 过账时间附近的那个时刻，用于「这张纸是什么时候出的」） */
    private OffsetDateTime issuedAt;

    /** 已打印次数（**服务端计数**；重打同样计数 ⇒ 每打一次都 +1，§7.3） */
    private Integer printCount;
}
