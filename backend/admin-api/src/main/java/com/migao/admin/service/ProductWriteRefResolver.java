package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.Product;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.List;

/**
 * **写路径专用**的商品引用解析：只有**唯一确定**的商品才返回 id（issue #8788）。
 *
 * <p>为什么单开一个类，而不是给 {@link ProductService#resolveProductId} 加个严格开关：</p>
 * <ol>
 *   <li><b>语义不同</b>：共享解析器被**只读面**共用，它的「UUID 前缀取第一条 / 序号 / 名称模糊取第一条」
 *       是只读语义（查错了最坏多查一次）；写路径改错商品**不可逆** ⇒ 两条路必须能分别演进，</li>
 *   <li><b>共享解析器逐字不动</b>：改它会把读路径的行为一起改掉，而写路径的风险不该由读面买单，</li>
 *   <li><b>可读性</b>：{@code ProductService} 是存量超 3000 行的巨类（`tests/unit_ci_workflows/loc_freeze_ledger.json`
 *       冻结清单在册，行数**只许向下**）—— 新逻辑加到它身上等于让棘轮往回长。</li>
 * </ol>
 *
 * <p>三条硬差别（每条都对应一次真实误写风险）：</p>
 * <ul>
 *   <li><b>序号一律拒绝</b>：「第 3 个」= 按创建时间排序的第 3 件 ⇒ 任何一次增删都会让序号漂移；</li>
 *   <li><b>UUID 前缀要求唯一</b>：命中多条 ⇒ 拒绝（写路径不接受「低概率」）；</li>
 *   <li><b>名称要求唯一</b>：精确名称重名、或模糊包含命中多条 ⇒ 拒绝。</li>
 * </ul>
 *
 * <p>边界（照实登记）：本类只做**引用解析**，不做写入；命中多条 / 序号两种拒绝是**抛异常**
 * （由 {@code GlobalExceptionHandler} 翻成 422），一条都没命中返回 {@code null}（调用方按 404 处理）。</p>
 */
@Component
@RequiredArgsConstructor
public class ProductWriteRefResolver {

    private final ProductMapper productMapper;

    /**
     * 解析写路径的商品引用。
     *
     * @param raw      模型/用户给的原始引用（id / 名称 / id 前缀）
     * @param tenantId 租户（跨租户不可能命中）
     * @return 唯一确定的真实 id；**一条都没命中**返回 {@code null}（调用方按 NOT_FOUND 处理）
     * @throws BusinessException {@code PRODUCT_INDEX_NOT_ALLOWED}（422）入参是纯数字序号
     * @throws BusinessException {@code PRODUCT_AMBIGUOUS}（422）命中多条（消息含条数与候选名）
     */
    public String resolveUniqueProductId(String raw, Long tenantId) {
        if (!StringUtils.hasText(raw)) return null;
        String s = raw.trim();

        List<Product> all = productMapper.selectList(
                new LambdaQueryWrapper<Product>()
                        .eq(Product::getTenantId, tenantId)
                        .orderByAsc(Product::getCreatedAt));

        // 1. 精确 id（UUID 与非 UUID 的种子/历史 id 都走这里）—— 唯一确定，直通
        for (Product p : all) {
            if (s.equals(p.getId())) return p.getId();
        }

        // 2. 序号：写路径**一律拒绝**（序号按创建时间排序，增删商品后漂移）
        if (s.matches("\\d+")) {
            throw new BusinessException("PRODUCT_INDEX_NOT_ALLOWED",
                    "写操作不接受商品序号「" + s + "」：序号按创建时间排序，增删商品后会漂移，可能改错商品",
                    422,
                    "请先用 product_search 搜出候选、让商家确认后用商品的 id 重试");
        }

        // 3. 精确名称（唯一才写）
        List<Product> exact = new ArrayList<>();
        for (Product p : all) {
            if (s.equals(p.getName())) exact.add(p);
        }
        if (exact.size() == 1) return exact.get(0).getId();
        if (exact.size() > 1) throw ambiguous("精确名称", s, exact);

        // 4. 名称包含（唯一才写；多条 ⇒ 拒绝）
        List<Product> fuzzy = new ArrayList<>();
        for (Product p : all) {
            if (p.getName() != null && p.getName().contains(s)) fuzzy.add(p);
        }
        if (fuzzy.size() == 1) return fuzzy.get(0).getId();
        if (fuzzy.size() > 1) throw ambiguous("名称片段", s, fuzzy);

        // 5. UUID 前缀（唯一才写；多条 ⇒ 拒绝）
        if (s.length() >= 8) {
            String prefix = s.substring(0, Math.min(16, s.length()));
            List<Product> byPrefix = new ArrayList<>();
            for (Product p : all) {
                if (p.getId() != null && p.getId().startsWith(prefix)) byPrefix.add(p);
            }
            if (byPrefix.size() == 1) return byPrefix.get(0).getId();
            if (byPrefix.size() > 1) throw ambiguous("id 前缀", s, byPrefix);
        }

        return null;
    }

    /** 命中多条 ⇒ 具名拒绝（写路径**绝不**取第一条）。 */
    private BusinessException ambiguous(String shape, String raw, List<Product> hits) {
        StringBuilder names = new StringBuilder();
        for (int i = 0; i < Math.min(5, hits.size()); i++) {
            if (i > 0) names.append("、");
            names.append("「").append(hits.get(i).getName()).append("」");
        }
        return new BusinessException("PRODUCT_AMBIGUOUS",
                "「" + raw + "」按" + shape + "匹配到 " + hits.size() + " 个商品（" + names + "），未执行修改",
                422,
                "请先用 product_search 搜出候选、让商家确认后用该商品的 id 重试；写操作不会替你挑一个");
    }
}
