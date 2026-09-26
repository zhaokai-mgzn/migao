package com.migao.admin.service;

import com.migao.admin.dto.InboundLabelPrintView;
import com.migao.admin.dto.InboundLabelView;
import com.migao.admin.dto.InboundOrderResponse;
import com.migao.admin.entity.InboundLabel;
import com.migao.admin.entity.Product;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.InboundLabelMapper;
import com.migao.admin.mapper.ProductMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * 入库标签服务（issue #5052 <b>P2</b>；设计真值源 {@code docs/design/inbound-photo-and-label.md} §7）。
 *
 * <h3>它负责四件事（对应设计的四条口径）</h3>
 * <ol>
 *   <li><b>短码生成</b>（§7.1）：8 位 Crockford Base32、随机、全局唯一；字母表 / 归一化 / 碰撞重试
 *       <b>复用</b> {@link WorkerShortLinkService} 的静态口径（{@code ALPHABET} / {@code randomCode} /
 *       {@code normalize} / {@code allocateUnique}）—— <b>不复制第二份字母表</b>；
 *       🔴 但**码空间独立**：{@code /i/}（入库标签）与 {@code /s/}（报工短链）是两张表、两个语义
 *       （#5052 边界逐字：「照其范式、不复用其表」）。</li>
 *   <li><b>打印计数 + 审计</b>（§7.3）：{@code print_count} 原子自增（并发不丢、重打同样计数），
 *       每次打印落一行 {@code audit_logs}（谁 / 何时 / 哪个短码 / 第几次）。</li>
 *   <li><b>详情读面</b>（§5.2 / 功能②）：按短码回该行单据的业务字段，够 P3 渲染 50×30mm 标签。</li>
 *   <li><b>公开入口</b>（§5.2）：{@code GET /i/{短码}} ⇒ 302 到**可配置**的落地页；
 *       不存在 ⇒ 404、已撤销 ⇒ <b>410</b>；**只回跳转、不泄露业务字段**。</li>
 * </ol>
 *
 * <h3>🔴 撤销 = 短码置 NULL，但扫码仍然 410（§7.3 的字面口径与它的可判定性）</h3>
 * <p>撤销把 {@code short_code} 置 NULL，同时把原码留档到 {@code revoked_code}
 * （{@code ck_inbound_labels_code_exactly_one} 钉住「恰有一个非空」）⇒ 扫码仍能分辨
 * 「已作废」（410）与「没这个码」（404）。只置 NULL 会把撤销静默说成「不存在」——
 * 也就是本仓最忌讳的那种「界面说作废、实际查不到」。</p>
 *
 * <h3>🔴 缺码不画假码（§7.1）⇒ 过账与发码**同一事务**（fail-closed）</h3>
 * <p>过账成功却拿不到短码，是一个**不可恢复**的中间态（没有「按单补码」的端点，工人也无从重来）
 * ⇒ 发码失败就让过账整体回滚：工人重试即可（幂等键随事务一起回滚，重试是首次执行）。
 * 「缺码时留空位并标注」只适用于**渲染**侧（P3 必须显式标注，绝不画占位二维码）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class InboundLabelService {

    /** 落地页**默认相对路径**（B 端 h5；`/b/` 的发布腿见 issue #5668 —— 本包只保证地址**可配**）。 */
    public static final String DEFAULT_LANDING_PATH = "/b/";

    /** 落地页带过去的短码参数名（P3 / #5668 消费：{@code /b/?code=<短码>}）。 */
    public static final String LANDING_CODE_PARAM = "code";

    /** 撤销后的扫码口径（§7.3）：**410 Gone**，不是 404（不把「作废」说成「不存在」）。 */
    public static final int GONE_STATUS = 410;

    private final InboundLabelMapper inboundLabelMapper;
    private final InboundOrderService inboundOrderService;
    private final ProductMapper productMapper;
    private final AuditLogService auditLogService;

    /**
     * 落地页地址（**单一配置**，不硬编码域名）。
     *
     * <p>与 {@code WorkerShortLinkService.REPORT_PAGE_PATH} 同一取舍：配置的是**相对路径**
     * （默认 {@code /b/}），302 的 {@code Location} 也用相对形式 ⇒ ① 请求 Host 可伪造，
     * 拼绝对 URL = 开放重定向面；② 换域名 / 改前端路由**只改这一处**（已打印的码全是
     * {@code https://app.migaozn.com/i/<短码>}，那一跳一个字都不能变）。</p>
     */
    @Value("${migao.inbound-label.landing-path:" + DEFAULT_LANDING_PATH + "}")
    private String landingPath = DEFAULT_LANDING_PATH;

    // ============================================================ ① 发码（过账后）

    /**
     * 为一张入库单的**每个明细行**确保一张标签（幂等：已有则复用**同一短码**，不换码）。
     *
     * <p>由 {@code WorkerInboundService.postDraft} 在过账成功之后、**同一事务内**调用
     * ⇒ 过账成功 ⇔ 每一行都有码（见类注释「缺码不画假码」）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public List<InboundLabel> ensureLabels(Long tenantId, String inboundOrderId,
                                           List<InboundOrderResponse.Item> items, String operator) {
        List<InboundLabel> labels = new ArrayList<>();
        if (items == null) {
            return labels;
        }
        for (InboundOrderResponse.Item item : items) {
            if (item == null || item.getId() == null) {
                continue;
            }
            labels.add(ensureLabel(tenantId, inboundOrderId, item.getId(), operator));
        }
        return labels;
    }

    /** 单行发码（幂等；**不复活已撤销的标签** —— 复活等于让作废的码重新可用）。 */
    @Transactional(rollbackFor = Exception.class)
    public InboundLabel ensureLabel(Long tenantId, String inboundOrderId, Long itemId, String operator) {
        InboundLabel existing = inboundLabelMapper.selectByItem(tenantId, itemId);
        if (existing != null) {
            return existing;
        }
        InboundLabel label = InboundLabel.builder()
                .tenantId(tenantId)
                .inboundOrderId(inboundOrderId)
                .inboundItemId(itemId)
                .shortCode(allocateUniqueCode())
                .printCount(0)
                .createdBy(operator)
                .deleted(0)
                .build();
        if (inboundLabelMapper.insertIgnoreConflict(label) == 0) {
            // 并发同 item：另一个请求刚插进去 ⇒ 回读那一行（同一张纸，不造第二张码）
            InboundLabel concurrent = inboundLabelMapper.selectByItem(tenantId, itemId);
            if (concurrent == null) {
                throw new IllegalStateException(
                        "入库标签插入被唯一索引拒绝，但回读不到该行（itemId=" + itemId + "）—— 拒绝静默丢码");
            }
            return concurrent;
        }
        log.info("[入库标签] 已发码: tenant={}, inboundOrder={}, item={}, shortCode={}, operator={}",
                tenantId, inboundOrderId, itemId, label.getShortCode(), operator);
        return label;
    }

    /**
     * 分配一个未被占用的短码 —— **复用**报工短链那份分配器（{@link WorkerShortLinkService#allocateUnique}）。
     *
     * <p>查重**同时看活码与留档码**（{@code selectByCode}）：已撤销的码绝不复发
     * ⇒ 老纸永远指不到新单上（部分唯一索引 {@code uk_inbound_labels_code}（有效码唯一）兜底）。</p>
     */
    private String allocateUniqueCode() {
        return WorkerShortLinkService.allocateUnique(code -> inboundLabelMapper.selectByCode(code) != null);
    }

    // ============================================================ ② 解析 / 详情

    /**
     * 按**印刷码**解析（跨租户；手抄形态 {@code O/I/L} 会被归一化）。
     *
     * @return 命中行（活码与留档码都命中）；未知 / 形态不合法 ⇒ {@code null}
     */
    public InboundLabel resolve(String rawCode) {
        String code = WorkerShortLinkService.normalize(rawCode);
        if (code.isEmpty()) {
            return null;
        }
        return inboundLabelMapper.selectByCode(code);
    }

    /** 工人面详情（§5.2）；跨租户 / 不存在 ⇒ <b>404</b>；已撤销 ⇒ <b>410</b>。 */
    public InboundLabelView detail(String rawCode, Long tenantId) {
        InboundLabel label = requirePrintableLabel(rawCode, tenantId);
        InboundOrderResponse order = inboundOrderService.detail(label.getInboundOrderId(), tenantId);
        InboundOrderResponse.Item item = findItem(order, label.getInboundItemId());

        InboundLabelView view = new InboundLabelView();
        view.setShortCode(label.printedCode());
        view.setInboundNo(order.getInboundNo());
        view.setItemId(label.getInboundItemId());
        view.setSupplier(order.getSupplier());
        view.setSupplierDocNo(order.getSupplierDocNo());
        view.setWarehouse(order.getWarehouse());
        view.setInboundDate(order.getInboundDate());
        view.setIssuedAt(label.getCreatedAt());
        view.setPrintCount(label.getPrintCount() == null ? 0 : label.getPrintCount());
        if (item != null) {
            view.setSkuCode(item.getSkuCode());
            view.setColorName(item.getColorName());
            view.setDoorWidth(item.getDoorWidth());
            view.setQuantity(item.getQuantity());
            view.setDyeLot(item.getDyeLot());
            view.setBatchNo(item.getBatchNo());
            view.setProductName(productNameOf(item.getProductId()));
        }
        return view;
    }

    // ============================================================ ③ 打印（计数 + 审计）

    /**
     * 记录一次打印：{@code print_count} **原子自增** + 落一行 {@code audit_logs}（§7.3「打印必留痕」）。
     *
     * <p>设备侧打印**前**必须先调它（{@code POST /api/worker/inbound/labels/{短码}/print}）——
     * 服务端可观测的判据 = 「每次打印都有计数 +1 与一行审计」，且**本方法之外没有任何地方**
     * 写 {@code print_count}（判据 = {@code InboundLabelSurfaceGuardTest} 的源码扫描 +
     * 本类的行为测试）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public InboundLabelPrintView recordPrint(String rawCode, Long tenantId, String operator, String operatorName,
                                             String ipAddress, String userAgent) {
        InboundLabel label = requirePrintableLabel(rawCode, tenantId);
        if (inboundLabelMapper.incrementPrintCount(label.getId(), tenantId) == 0) {
            // 并发撤销 / 软删：按「看不见」处理（404），绝不返回一个没落库的计数
            throw BusinessException.notFound("入库标签", "该标签刚刚被撤销或删除，本次打印未计数");
        }
        Integer count = inboundLabelMapper.selectPrintCount(label.getId(), tenantId);
        String code = label.printedCode();

        Map<String, Object> details = new LinkedHashMap<>();
        details.put("shortCode", code);
        details.put("printCount", count);
        details.put("inboundNo", label.getInboundOrderId());
        details.put("itemId", label.getInboundItemId());
        auditLogService.recordLog(tenantId, operator, operatorName,
                InboundLabel.ACTION_PRINT, InboundLabel.RESOURCE_TYPE, null,
                label.getId(), code, details, ipAddress, userAgent);

        log.info("[入库标签] 打印留痕: tenant={}, shortCode={}, 第 {} 次, operator={}",
                tenantId, code, count, operator);
        return new InboundLabelPrintView(code, count);
    }

    // ============================================================ ④ 撤销

    /**
     * 撤销一张标签（§7.3）：短码置 NULL + 原码留档 ⇒ 扫码 **410**。
     *
     * <p>本包**不开**撤销的 HTTP 入口（设计 §5.2 的新端点清单里没有它）—— 能力与判据落在服务层，
     * 由后续包（工人端页面 / 后台单据面）接线；今天没有任何产品路径能撤销一张刚打出来的标签。</p>
     *
     * @return true = 本次真的撤销了（false = 不存在 / 非本租户 / 已撤销过 —— 幂等）
     */
    @Transactional(rollbackFor = Exception.class)
    public boolean revoke(String rawCode, Long tenantId, String operator) {
        InboundLabel label = resolve(rawCode);
        if (label == null || !Objects.equals(label.getTenantId(), tenantId)) {
            return false;
        }
        return inboundLabelMapper.revoke(label.getId(), tenantId, OffsetDateTime.now(), operator) > 0;
    }

    // ============================================================ ⑤ 公开入口

    /**
     * {@code GET /i/{短码}} 的 302 {@code Location}（落地页 + 短码 + 租户）。
     *
     * <p>与 {@code WorkerShortLinkService.reportPageLocation} 同款：<b>相对 Location</b>
     * （不拼绝对 URL ⇒ 无开放重定向面；换域名不用改这一跳）。
     * 带上 {@code tenant_id} 的理由同 {@code /s/}：落地页（B 端 h5）判不出租户，
     * 而工人登录必须有租户 —— 该键是既有回落形态（{@code ?tenant_id=}），且租户 id 非敏感
     * （子域形态本身就是公开约定）。<b>除短码与租户 id 外不带任何业务字段</b>（§5.2：只回跳转）。</p>
     */
    public String landingLocation(String rawCode, Long tenantId) {
        String code = WorkerShortLinkService.normalize(rawCode);
        StringBuilder sb = new StringBuilder(landingPath);
        sb.append(landingPath.contains("?") ? '&' : '?').append(LANDING_CODE_PARAM).append('=').append(code);
        if (tenantId != null) {
            sb.append("&tenant_id=").append(tenantId);
        }
        return sb.toString();
    }

    // ============================================================ 内部

    /**
     * 取「可打印」的标签：跨租户 / 不存在 ⇒ <b>404</b>（不是 403 —— 不泄露存在性，§5.2 逐字）；
     * 已撤销 ⇒ <b>410</b>。
     *
     * <p>顺序即安全顺序：**先判租户、后判撤销** —— 反过来的话，跨租户去戳一个已撤销的码会拿到
     * 410（= 泄露「这个码存在过」）。</p>
     */
    private InboundLabel requirePrintableLabel(String rawCode, Long tenantId) {
        InboundLabel label = resolve(rawCode);
        if (label == null || !Objects.equals(label.getTenantId(), tenantId)) {
            throw BusinessException.notFound("入库标签",
                    "请核对标签上的短码（8 位，字母与数字；字母 O/I/L 会被当作 0/1 处理）");
        }
        if (label.isRevoked()) {
            throw new BusinessException("LABEL_REVOKED", "该入库标签已作废", GONE_STATUS,
                    "这张纸对应的标签已被撤销 —— 请按单据重新补打一张（旧码不再可用，不会静默回落到别的标签）");
        }
        return label;
    }

    /** 实读品名（商品已删 ⇒ null，**不编造**）。 */
    private String productNameOf(String productId) {
        if (!StringUtils.hasText(productId)) {
            return null;
        }
        Product product = productMapper.selectById(productId);
        return product == null ? null : product.getName();
    }

    /** 在单据详情里找那一行（找不到 ⇒ null：字段留空，不猜）。 */
    private static InboundOrderResponse.Item findItem(InboundOrderResponse order, Long itemId) {
        if (order == null || order.getItems() == null) {
            return null;
        }
        for (InboundOrderResponse.Item item : order.getItems()) {
            if (Objects.equals(item.getId(), itemId)) {
                return item;
            }
        }
        return null;
    }
}
