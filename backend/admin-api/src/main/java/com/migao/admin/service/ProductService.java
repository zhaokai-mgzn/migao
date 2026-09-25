package com.migao.admin.service;

import com.migao.admin.dto.*;
import com.migao.admin.entity.Category;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductAttribute;
import com.migao.admin.entity.ProductColor;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.entity.StockLedger;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.CategoryMapper;
import com.migao.admin.mapper.ProductAttributeMapper;
import com.migao.admin.mapper.ProductColorMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.poi.ss.usermodel.*;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.springframework.beans.BeanUtils;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.io.OutputStream;
import java.math.BigDecimal;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 商品服务类
 * 处理商品的增删改查、上下架等操作
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProductService extends ServiceImpl<ProductMapper, Product> {

    private final ProductMapper productMapper;
    private final CategoryMapper categoryMapper;
    private final ProductColorMapper productColorMapper;
    private final ProductSkuMapper productSkuMapper;
    private final ProductAttributeMapper productAttributeMapper;
    /** 库存台账（issue #4055）：本类只负责在库存变更点写一行流水，查询/落账语义在该服务内 */
    private final StockLedgerService stockLedgerService;

    /**
     * 导出表头（**导出与导入共用的单一源**，issue #5154）。
     *
     * <p>导入面按导出面**反向定义**：{@link #IMPORT_HEADERS} 与它**逐字同名**的那 5 列
     * （商品名称/货号/价格/库存/描述）就是「一进一出同构」的机械判据 —— 两个数组都是具名常量，
     * 判据可以直接断言名字交集，而不是靠人读两段代码比对。</p>
     */
    static final String[] EXPORT_HEADERS = {"商品名称", "货号", "分类", "价格", "库存", "状态", "描述"};

    /**
     * 导入表头 = 导出面里与建品同义的 5 列 + **SKU 组合维度（颜色 × 门幅）** + 定位/覆盖用列。
     *
     * <p>行语义：**一个数据行 = 该货号的一个 SKU 行**（同一货号多行 = 一个商品的多 SKU）；
     * 颜色与门幅**都不填**时该行只建商品（无 SKU 商品，如配件）。</p>
     *
     * <p>SKU 组合只有**颜色 × 门幅**二维（用户裁定 2026-09-21，V113/#5058）——
     * 售卖方式是**商品级基础属性**，不得回退成 SKU 维度。</p>
     */
    static final String[] IMPORT_HEADERS =
            {"商品名称", "货号", "分类ID", "价格", "库存", "描述", "颜色", "门幅", "SKU编码"};

    /** 导入**必填**表头：缺列 ⇒ 整包拒绝（列都不在时逐行报错只会刷屏，且没有一行是能修的）。 */
    private static final List<String> REQUIRED_IMPORT_HEADERS = List.of("商品名称", "货号", "价格");

    /** 导入可列表头（缺了不报错；文案里列出来让商家知道模板该长什么样）。 */
    private static final List<String> OPTIONAL_IMPORT_HEADERS =
            List.of("分类ID", "库存", "描述", "颜色", "门幅", "SKU编码");

    /**
     * 商品品牌存储在 product_attributes 表的 attr_key
     */
    private static final String ATTR_KEY_BRAND = "brand";

    /**
     * 合法的状态流转映射
     */
    private static final Map<String, List<String>> STATUS_TRANSITIONS = new HashMap<>();
    static {
        STATUS_TRANSITIONS.put("draft", List.of("under_review", "on_sale"));
        STATUS_TRANSITIONS.put("under_review", List.of("on_sale", "draft"));
        STATUS_TRANSITIONS.put("on_sale", List.of("off_sale"));
        STATUS_TRANSITIONS.put("off_sale", List.of("on_sale", "under_review"));
    }

    /**
     * 商品状态 → 中文业务术语（错误消息用）。
     * 上下架/删除等校验报错会直接展示给企业客户，必须用中文（如「出售中」），
     * 不能用 on_sale/off_sale 等英文枚举。
     */
    private static final Map<String, String> PRODUCT_STATUS_LABELS = Map.of(
            "draft", "草稿",
            "under_review", "审核中",
            "on_sale", "出售中",
            "off_sale", "已下架"
    );

    /**
     * 库存台账 note（issue #4157）：建品/改品直写 SKU 库存的来源说明。
     *
     * <p>{@code reason} 复用 {@link StockLedger#REASON_MANUAL}（人工直接设定库存，与
     * {@link #adjustStockForAgent} 同族）—— 表上有 {@code ck_stock_ledger_reason} CHECK
     * 只放行 order/aftersales/manual/inbound，为「区分来源」去造第五个 reason 需要迁移，
     * 且是第二套口径。**建档/改品的库存变更**与**新 SKU 基线行**由 note 区分。</p>
     */
    private static final String LEDGER_NOTE_SKU_CHANGED = "商品建档/编辑：SKU 库存变更";
    private static final String LEDGER_NOTE_SKU_BASELINE = "商品建档/编辑：新 SKU 初始库存（基线行）";

    /**
     * 分页查询商品列表
     */
    public PageResponse<ProductResponse> getProducts(ProductQueryRequest query, Long tenantId) {
        LambdaQueryWrapper<Product> wrapper = new LambdaQueryWrapper<>();

        // 关键词搜索（名称 + 货号）
        if (StringUtils.hasText(query.getKeyword())) {
            wrapper.and(w -> w.like(Product::getName, query.getKeyword())
                    .or().like(Product::getSkuCode, query.getKeyword()));
        }

        // 商品标题模糊搜索
        if (StringUtils.hasText(query.getName())) {
            wrapper.like(Product::getName, query.getName());
        }

        // 商品ID精确搜索
        if (StringUtils.hasText(query.getProductId())) {
            wrapper.eq(Product::getId, query.getProductId());
        }

        // SKU货号模糊搜索
        if (StringUtils.hasText(query.getSkuCode())) {
            wrapper.like(Product::getSkuCode, query.getSkuCode());
        }

        // 分类筛选
        if (StringUtils.hasText(query.getCategoryId())) {
            wrapper.eq(Product::getCategoryId, query.getCategoryId());
        }

        // 状态筛选
        if (StringUtils.hasText(query.getStatus())) {
            wrapper.eq(Product::getStatus, query.getStatus());
        }

        // 商家推荐筛选（C 端新品推荐位：recommended=true）
        if (query.getRecommended() != null) {
            wrapper.eq(Product::getRecommended, query.getRecommended());
        }

        // 低库存筛选（#1291→#1396: 使用 SKU 级 EXISTS 子查询，口径统一 — 仅 on_sale 商品）
        if (query.getStockBelow() != null) {
            // 未显式指定 status 时，自动过滤 on_sale（排除已下架/已关闭商品）
            if (!StringUtils.hasText(query.getStatus())) {
                wrapper.eq(Product::getStatus, "on_sale");
            }
            wrapper.apply("EXISTS (SELECT 1 FROM product_skus ps WHERE ps.product_id = products.id AND ps.stock >= 0 AND ps.stock <= {0})", query.getStockBelow());
        }

        // 时间范围筛选（createdFrom/createdTo 优先于 startDate/endDate）
        String fromDate = StringUtils.hasText(query.getCreatedFrom()) ? query.getCreatedFrom() : query.getStartDate();
        String toDate = StringUtils.hasText(query.getCreatedTo()) ? query.getCreatedTo() : query.getEndDate();
        if (StringUtils.hasText(fromDate)) {
            OffsetDateTime startDateTime = LocalDate.parse(fromDate, DateTimeFormatter.ISO_LOCAL_DATE)
                    .atStartOfDay().atOffset(ZoneOffset.UTC);
            wrapper.ge(Product::getCreatedAt, startDateTime);
        }
        if (StringUtils.hasText(toDate)) {
            OffsetDateTime endDateTime = LocalDate.parse(toDate, DateTimeFormatter.ISO_LOCAL_DATE)
                    .plusDays(1).atStartOfDay().atOffset(ZoneOffset.UTC);
            wrapper.lt(Product::getCreatedAt, endDateTime);
        }

        // 排序（支持 camelCase 和 snake_case）
        if (StringUtils.hasText(query.getSortBy())) {
            boolean isAsc = "asc".equalsIgnoreCase(query.getSortOrder());
            switch (query.getSortBy()) {
                case "stock" -> {
                    // #1201: products.stock 常为 0（默认值），与前端展示值（SKU 汇总 sum）不同源。
                    // ORDER BY products.stock 无实际排序效果 → 改用 SKU 汇总子查询排序。
                    String direction = isAsc ? "ASC" : "DESC";
                    wrapper.last(" ORDER BY (SELECT COALESCE(SUM(ps.stock), 0) FROM product_skus ps WHERE ps.product_id = products.id) " + direction);
                }
                case "sales_count", "salesCount" -> wrapper.orderBy(true, isAsc, Product::getSalesCount);
                case "sales_amount", "salesAmount" -> wrapper.orderBy(true, isAsc, Product::getSalesAmount);
                case "created_at", "createdAt" -> wrapper.orderBy(true, isAsc, Product::getCreatedAt);
                default -> wrapper.orderByDesc(Product::getCreatedAt);
            }
        } else {
            wrapper.orderByDesc(Product::getCreatedAt);
        }

        // 执行分页查询
        Page<Product> page = new Page<>(query.getPage(), query.getSize());
        Page<Product> productPage = productMapper.selectPage(page, wrapper);

        // 获取分类名称映射
        Map<String, String> categoryNameMap = getCategoryNameMap(productPage.getRecords());

        // 转换为响应 DTO，附加 colorCount 和 totalStock
        List<ProductResponse> responses = productPage.getRecords().stream()
                .map(product -> {
                    ProductResponse response = convertToResponse(product, categoryNameMap.get(product.getCategoryId()));
                    // 附加颜色数和总库存（总库存以 SKU 汇总为准，覆盖 product.stock 可能为 0 的情况）
                    response.setColorCount(getColorCount(product.getId()));
                    BigDecimal totalStock = getTotalStock(product.getId());
                    response.setTotalStock(totalStock);
                    response.setStock(totalStock);
                    return response;
                })
                .collect(Collectors.toList());

        return PageResponse.of(productPage.getTotal(), productPage.getCurrent(), productPage.getSize(), responses);
    }

    /**
     * 根据ID查询商品详情
     */
    public ProductResponse getProductById(String id, Long tenantId) {
        Product product = productMapper.selectById(id);
        if (product == null) {
            throw BusinessException.notFound("商品");
        }

        // 获取分类名称
        String categoryName = null;
        if (StringUtils.hasText(product.getCategoryId())) {
            Category category = categoryMapper.selectById(product.getCategoryId());
            if (category != null) {
                categoryName = category.getName();
            }
        }

        ProductResponse response = convertToResponse(product, categoryName);
        response.setColorCount(getColorCount(id));
        BigDecimal totalStock = getTotalStock(id);
        response.setTotalStock(totalStock);
        response.setStock(totalStock);

        // 查询关联颜色列表
        List<ProductColor> colorEntities = productColorMapper.selectList(
                new LambdaQueryWrapper<ProductColor>()
                        .eq(ProductColor::getProductId, id)
                        .orderByAsc(ProductColor::getSortOrder)
                        .orderByAsc(ProductColor::getId)
        );
        Map<Long, String> colorNameMap = new HashMap<>();
        if (colorEntities != null && !colorEntities.isEmpty()) {
            List<ProductColorResponse> colorResponses = colorEntities.stream().map(c -> {
                ProductColorResponse cr = new ProductColorResponse();
                cr.setId(c.getId());
                cr.setProductId(c.getProductId());
                cr.setColorName(c.getColorName());
                cr.setMainColorHex(c.getMainColorHex());
                cr.setColorImageUrl(c.getColorImageUrl());
                cr.setRemark(c.getRemark());
                cr.setSortOrder(c.getSortOrder());
                cr.setCreatedAt(c.getCreatedAt());
                cr.setUpdatedAt(c.getUpdatedAt());
                colorNameMap.put(c.getId(), c.getColorName());
                return cr;
            }).collect(Collectors.toList());
            response.setColors(colorResponses);
        }

        // 查询关联 SKU 列表
        List<ProductSku> skuEntities = productSkuMapper.selectList(
                new LambdaQueryWrapper<ProductSku>()
                        .eq(ProductSku::getProductId, id)
                        .orderByAsc(ProductSku::getColorId)
                        .orderByAsc(ProductSku::getDoorWidth)
        );
        if (skuEntities != null && !skuEntities.isEmpty()) {
            List<ProductSkuResponse> skuResponses = skuEntities.stream().map(sku -> {
                ProductSkuResponse skuResp = new ProductSkuResponse();
                skuResp.setId(sku.getId());
                skuResp.setProductId(sku.getProductId());
                skuResp.setColorId(sku.getColorId());
                // 新数据直接取 SKU 的 colorName，旧数据从 product_colors 回退
                skuResp.setColorName(
                    StringUtils.hasText(sku.getColorName())
                        ? sku.getColorName()
                        : colorNameMap.get(sku.getColorId())
                );
                skuResp.setDoorWidth(sku.getDoorWidth());
                skuResp.setPrice(sku.getPrice());
                skuResp.setStock(sku.getStock());
                skuResp.setSkuCode(sku.getSkuCode());
                skuResp.setCreatedAt(sku.getCreatedAt());
                skuResp.setUpdatedAt(sku.getUpdatedAt());
                return skuResp;
            }).collect(Collectors.toList());
            response.setSkus(skuResponses);

            // 门幅仍从 SKU 派生（它是 SKU 组合维度之一，保持插入顺序去重）
            Set<String> dw = new LinkedHashSet<>();
            for (ProductSku sku : skuEntities) {
                if (StringUtils.hasText(sku.getDoorWidth())) dw.add(sku.getDoorWidth());
            }
            response.setDoorWidths(new ArrayList<>(dw));
        }

        // 售卖方式取自**商品列**（V108：它是商品级基础属性，不再是 SKU 组合维度）。
        // ⚠️ 原实现「从 SKU 派生 sellingMethods」已删除 —— 那种写法在 SKU 不再带该列之后
        // 会恒返回空数组（静默丢失商家配的售卖方式），且与「售卖方式是商品属性」的裁定相反。
        response.setSellingMethods(product.getSellingMethods() != null
                ? new ArrayList<>(product.getSellingMethods())
                : new ArrayList<>());

        // 回填商品属性：brand + specifications
        fillProductAttributes(response, id);

        return response;
    }

    /**
     * 创建商品
     */
    @Transactional(rollbackFor = Exception.class)
    public ProductResponse createProduct(ProductCreateRequest request, Long tenantId) {
        // issue #5063（V115）：库存是 1 位小数口径（0.1 米粒度）⇒ **超过 1 位小数显式拒绝**
        // （fail-closed；静默取整 = 账面与实物不符且无人发现，正是本单要治的形态）。
        // 判据单点在 StockQuantity；这里只做入口归一，不在 Service 里另写一套小数位判断。
        request.setStock(StockQuantity.requireOneDecimalOrNull(request.getStock(), "库存 stock"));

        // 空分类归一化（#3665 冒烟 B1）：前端草稿发的是 ''（DEFAULT_FORM.categoryId）而非缺省 null。
        // 若原样透传：validateCategory 因 hasText('')==false 跳过校验 → BeanUtils 把 '' 写进实体
        // → insert category_id='' → products_category_id_fkey 违例（500）。表列可空、草稿允许
        // 不选分类（ProductCreateRequest.categoryId 注释）→ 空串一律归一化为 NULL。
        request.setCategoryId(normalizeBlankToNull(request.getCategoryId()));

        // 根据目标状态校验必填字段（draft 状态放宽）
        validateRequiredForStatus(request.getStatus(), request.getCategoryId(), request.getBasePrice());

        // 校验分类是否存在
        validateCategory(request.getCategoryId());

        // 创建商品实体（categoryId 已在方法开头归一化：'' → null，不得再漏到实体）
        Product product = new Product();
        BeanUtils.copyProperties(request, product);
        product.setTenantId(tenantId);

        // 处理图片列表
        if (request.getImages() != null && !request.getImages().isEmpty()) {
            product.setImages(request.getImages());
            // 主图兜底（issue #3884）：未显式指定 mainImage 时，首图即默认主图。
            // 此前全后端无任何写 products.main_image 的路径，agent 却谎报「主图已设置成功」。
            if (!StringUtils.hasText(product.getMainImage())) {
                product.setMainImage(request.getImages().get(0));
            }
        }

        // 详情图列表（JSONB 存储于 products.detail_images）
        if (request.getDetailImages() != null) {
            product.setDetailImages(request.getDetailImages());
        }

        // 设置默认状态
        if (!StringUtils.hasText(product.getStatus())) {
            product.setStatus("draft");
        }

        // 设置编辑信息
        product.setEditedBy(getCurrentUsername());
        product.setEditedAt(OffsetDateTime.now());

        // 保存商品
        productMapper.insert(product);

        // 保存销售信息（颜色 + SKU），支持笛卡尔积自动生成
        saveColorsAndSkus(product.getId(), product.getSkuCode(), tenantId,
                request.getColors(),
                request.getSellingMethods(), request.getDoorWidths(),
                product.getBasePrice(), product.getStock(),
                request.getSkus(), true);

        // 保存商品属性（brand + specifications，存入 product_attributes 表）
        saveProductAttributes(product.getId(), tenantId, request.getBrand(), request.getSpecifications());

        log.info("创建商品成功: id={}, name={}", product.getId(), product.getName());

        return getProductById(product.getId(), tenantId);
    }

    /**
     * 更新商品
     */
    @Transactional(rollbackFor = Exception.class)
    public ProductResponse updateProduct(String id, ProductUpdateRequest request, Long tenantId) {
        // issue #5063（V115）：同 createProduct —— 库存输入最多 1 位小数，超过即显式拒绝
        request.setStock(StockQuantity.requireOneDecimalOrNull(request.getStock(), "库存 stock"));

        Product product = productMapper.selectById(id);
        if (product == null) {
            throw BusinessException.notFound("商品");
        }

        // 空分类归一化（#3665 冒烟 B1，与 createProduct 同口径）：'' 不得写进实体，否则 FK 违例
        request.setCategoryId(normalizeBlankToNull(request.getCategoryId()));

        // 根据目标状态校验必填字段（draft 状态放宽）
        validateRequiredForStatus(request.getStatus(), request.getCategoryId(), request.getBasePrice());

        // 校验分类是否存在
        validateCategory(request.getCategoryId());

        // 保存原始状态，防止 BeanUtils.copyProperties 绕过状态机
        String originalStatus = product.getStatus();
        // 保存原始主图（issue #3884）：BeanUtils.copyProperties 会把请求里的 null mainImage 覆写到实体，
        // 不先记下原值，主图兜底就无法区分「从未设置过」与「已设置过」→ 会误覆盖已设置的主图
        String originalMainImage = product.getMainImage();

        // 更新商品属性（categoryId 已在方法开头归一化：'' → null，不得再漏到实体）
        BeanUtils.copyProperties(request, product);
        product.setId(id);
        // 恢复状态：状态变更必须通过 updateProductStatus 接口（含状态机校验）
        product.setStatus(originalStatus);

        // 处理图片列表
        if (request.getImages() != null) {
            product.setImages(request.getImages());
        }

        // 主图兜底（issue #3884）：mainImage 未显式指定时——已设置过主图则保留原值
        // （copyProperties 已用请求 null 清掉实体值，需还原），否则传了图片时首图即默认主图
        if (!StringUtils.hasText(request.getMainImage())) {
            if (StringUtils.hasText(originalMainImage)) {
                product.setMainImage(originalMainImage);
            } else if (request.getImages() != null && !request.getImages().isEmpty()) {
                product.setMainImage(request.getImages().get(0));
            }
        }

        // 详情图列表（允许传空数组清空）
        if (request.getDetailImages() != null) {
            product.setDetailImages(request.getDetailImages());
        }

        // 更新编辑信息
        product.setEditedBy(getCurrentUsername());
        product.setEditedAt(OffsetDateTime.now());

        productMapper.updateById(product);

        // 更新销售信息（upsert：按 id/组合匹配原地更新，缺失才删；不再先删后插，
        // 保证订单 processingInfo 里存的旧 skuId/colorId 仍可被 OrderService.matchSkuId 寻址恢复库存）
        if (request.getColors() != null || request.getSkus() != null
                || request.getSellingMethods() != null || request.getDoorWidths() != null) {
            // price/stock 优先取请求值，否则用商品当前值
            BigDecimal skuPrice = request.getBasePrice() != null ? request.getBasePrice() : product.getBasePrice();
            BigDecimal skuStock = request.getStock() != null ? request.getStock() : product.getStock();
            saveColorsAndSkus(id, product.getSkuCode(), tenantId,
                    request.getColors(),
                    request.getSellingMethods(), request.getDoorWidths(),
                    skuPrice, skuStock,
                    request.getSkus(), true);
        } else if (request.getBasePrice() != null) {
            // 改价必须落到 SKU（issue #3743 / OR-014）：只给 basePrice、不给
            // colors/sellingMethods/doorWidths/skus 的部分更新（agent 的
            // `product_update(price=X)` 走的就是这条：updateProductForAgent 只 set basePrice）
            // 上面那个分支不成立 ⇒ `saveColorsAndSkus` 里唯一会把 basePrice 写进 SKU 的
            // `sku.setPrice(basePrice)` 从不执行 ⇒ product_skus.price 停留在旧价。
            //
            // 后果是**客户可见的错价**：商品库出现「商品级 basePrice ≠ SKU 级 price」两个价，
            // 而 agent 下单的**权威价**正是 SKU 级（OrderService 取价校验取 ProductSku.price）
            // ⇒ 米宝按旧 SKU 价报价并成交，商户刚改的价对 AI 报价无效。
            //
            // 显式带 `skus`（前端表单逐 SKU 定价）时走上面的分支、SKU 级价优先，本分支不参与。
            ProductSku priceSync = new ProductSku();
            priceSync.setPrice(request.getBasePrice());
            productSkuMapper.update(priceSync, new LambdaQueryWrapper<ProductSku>()
                    .eq(ProductSku::getProductId, id)
                    .eq(ProductSku::getTenantId, tenantId));
            log.info("商品改价已同步到 SKU: id={}, price={}", id, request.getBasePrice());
        }

        // 更新商品属性：仅当请求中明确提交 brand 或 specifications 时才重写，避免误清空
        if (request.getBrand() != null || request.getSpecifications() != null) {
            saveProductAttributes(id, tenantId, request.getBrand(), request.getSpecifications());
        }

        log.info("更新商品成功: id={}, name={}", id, product.getName());

        return getProductById(id, tenantId);
    }

    /**
     * 保存商品的颜色与 SKU 数据（create/update 通用，upsert 语义）。
     *
     * 断链防护（#商品模块自洽性）：update 场景不物理删除旧 SKU/颜色，而是
     * 1. 颜色/SKU 优先按 id 匹配（前端表单带真实 DB id）、其次按名称/组合匹配（Agent 按名称重建）；
     *    匹配到则原地 update（保留主键）→ 订单 processingInfo 里存的旧 skuId/colorId 仍然可寻址，
     *    OrderService.matchSkuId 的 skuId 直查与 colorId 回退两条路径都能恢复库存；
     * 2. 仅删除本次请求中"缺失"的旧行（缺失才删）；
     * 3. create 场景无现有行，等价于全量插入，行为与旧实现一致。
     */
    private void saveColorsAndSkus(String productId, String productSkuCode, Long tenantId,
                                    List<ProductColorInput> colorInputs,
                                    List<String> sellingMethods,
                                    List<String> doorWidths,
                                    BigDecimal basePrice,
                                    BigDecimal stock,
                                    List<ProductSkuInput> skuInputs,
                                    boolean pruneMissing) {
        // issue #5063（V115）：SKU 库存是库存链路的**权威列**，逐行准入（最多 1 位小数）——
        // 这里是所有建品/改品路径（表单 / Agent / 矩阵式生成）写 SKU stock 的**唯一收口**
        if (skuInputs != null) {
            for (ProductSkuInput input : skuInputs) {
                if (input != null) {
                    input.setStock(StockQuantity.requireOneDecimalOrNull(input.getStock(), "SKU 库存 stock"));
                }
            }
        }

        // 库存台账（issue #4157）：本方法是**建品/改品直写 SKU 库存**这条变更路径的唯一收口，
        // 此前不落账 ⇒「某 SKU 的库存为什么从 X 变成 Y」在这条路径上答不出。
        // 变更**之前**取快照，变更后用同一份既有比对落账（复用 StockLedgerService，不写第二套判据）。
        Map<Long, ProductSku> stockBeforeSave = stockLedgerService.snapshotSkus(List.of(productId));

        // 加载现有颜色与 SKU（仅当前商品，不跨租户；create 时为空）
        List<ProductColor> existingColors = productColorMapper.selectList(
                new LambdaQueryWrapper<ProductColor>().eq(ProductColor::getProductId, productId));
        List<ProductSku> existingSkus = productSkuMapper.selectList(
                new LambdaQueryWrapper<ProductSku>().eq(ProductSku::getProductId, productId));
        if (existingColors == null) existingColors = new ArrayList<>();
        if (existingSkus == null) existingSkus = new ArrayList<>();

        Map<Long, ProductColor> colorById = new HashMap<>();
        Map<String, ProductColor> colorByName = new HashMap<>();
        // 颜色名 → DB 主键：用于 SKU 匹配时解析 colorId（兼容旧数据 SKU 只有 colorId 无 colorName）
        Map<String, Long> colorIdByName = new HashMap<>();
        for (ProductColor c : existingColors) {
            colorById.put(c.getId(), c);
            if (StringUtils.hasText(c.getColorName())) {
                colorByName.putIfAbsent(c.getColorName(), c);
                colorIdByName.putIfAbsent(c.getColorName(), c.getId());
            }
        }
        Map<Long, ProductSku> skuById = new HashMap<>();
        for (ProductSku s : existingSkus) {
            skuById.put(s.getId(), s);
        }
        Set<Long> keptColorIds = new LinkedHashSet<>();
        Set<Long> keptSkuIds = new LinkedHashSet<>();
        // 本次新建的 SKU（issue #4157）：首行按「补一条基线行」落账（快照比对看不见新增行）
        List<ProductSku> createdSkus = new ArrayList<>();

        // 提取颜色名列表（优先用 colorName，即色号如 "2699-01"）
        List<String> colorNames = new ArrayList<>();
        if (colorInputs != null) {
            for (ProductColorInput input : colorInputs) {
                if (input == null) continue;
                colorNames.add(StringUtils.hasText(input.getColorName()) ? input.getColorName() : "");
            }
        }

        // 保存颜色到 product_colors（兼容前端旧逻辑）— upsert：按 id 优先、其次名称匹配
        Map<Long, Long> colorIdMap = new LinkedHashMap<>();
        if (colorInputs != null) {
            int idx = 0;
            for (ProductColorInput input : colorInputs) {
                if (input == null) continue;
                ProductColor matched = null;
                if (input.getId() != null && input.getId() > 0) {
                    matched = colorById.get(input.getId());
                }
                if (matched == null && StringUtils.hasText(input.getColorName())) {
                    matched = colorByName.get(input.getColorName());
                }
                if (matched != null) {
                    // 保留主键原地更新，避免旧 colorId 失效
                    matched.setColorName(input.getColorName());
                    matched.setMainColorHex(input.getMainColorHex());
                    matched.setColorImageUrl(input.getColorImageUrl());
                    matched.setRemark(input.getRemark());
                    matched.setSortOrder(input.getSortOrder() != null ? input.getSortOrder() : idx);
                    productColorMapper.updateById(matched);
                    keptColorIds.add(matched.getId());
                    if (StringUtils.hasText(matched.getColorName())) {
                        colorIdByName.put(matched.getColorName(), matched.getId());
                    }
                    if (input.getId() != null) {
                        colorIdMap.put(input.getId(), matched.getId());
                    }
                } else {
                    ProductColor entity = new ProductColor();
                    entity.setTenantId(tenantId);
                    entity.setProductId(productId);
                    entity.setColorName(input.getColorName());
                    entity.setMainColorHex(input.getMainColorHex());
                    entity.setColorImageUrl(input.getColorImageUrl());
                    entity.setRemark(input.getRemark());
                    entity.setSortOrder(input.getSortOrder() != null ? input.getSortOrder() : idx);
                    productColorMapper.insert(entity);
                    keptColorIds.add(entity.getId());
                    if (StringUtils.hasText(entity.getColorName())) {
                        colorIdByName.put(entity.getColorName(), entity.getId());
                    }
                    if (input.getId() != null) {
                        colorIdMap.put(input.getId(), entity.getId());
                    }
                }
                idx++;
            }
        }

        // 构建颜色 → 序号映射（用于 SKU 编码生成）
        Map<String, Integer> colorSeqMap = new LinkedHashMap<>();
        int seq = 1;
        for (String cn : colorNames) {
            if (StringUtils.hasText(cn)) {
                colorSeqMap.putIfAbsent(cn, seq++);
            }
        }

        // 笛卡尔积自动生成 SKU：colors × doorWidths（**仅此二维**）
        // 用户裁定 2026-09-21：「商品的售卖方式整卷/散件不能作为 SKU 的组合项，只能作为基础属性，
        // 商品的 SKU 由颜色+门幅组成即可」⇒ 原 `colors × sellingMethods × doorWidths` 里
        // 那一维已删（售卖方式落 products.selling_methods）。`sellingMethods` 形参保留只为
        // 兼容调用方签名与「矩阵式建品」判据（**不再参与组合**）。
        if ((skuInputs == null || skuInputs.isEmpty())
                && !colorNames.isEmpty()
                && doorWidths != null && !doorWidths.isEmpty()) {
            skuInputs = new ArrayList<>();
            for (String colorName : colorNames) {
                for (String dw : doorWidths) {
                    ProductSkuInput sku = new ProductSkuInput();
                    sku.setColorName(colorName);
                    sku.setDoorWidth(dw);
                    sku.setPrice(basePrice);
                    sku.setStock(stock != null && stock.compareTo(BigDecimal.ZERO) > 0
                            ? stock : BigDecimal.valueOf(100));
                    // 自动生成 SKU 编码
                    Integer colorSeq = colorSeqMap.get(colorName);
                    sku.setSkuCode(generateSkuCode(productId, productSkuCode,
                            colorSeq != null ? colorSeq : 0, dw));
                    skuInputs.add(sku);
                }
            }
        }

        if (skuInputs != null) {
            for (ProductSkuInput input : skuInputs) {
                if (input == null) continue;
                if (!StringUtils.hasText(input.getDoorWidth())) {
                    continue;
                }
                // 解析 colorId（兼容前端旧逻辑，新数据走 colorName）
                Long mappedColorId = null;
                if (input.getColorId() != null) {
                    mappedColorId = colorIdMap.getOrDefault(input.getColorId(), input.getColorId());
                    if (mappedColorId != null && mappedColorId <= 0) {
                        mappedColorId = null;
                    }
                }
                // Agent 按名称重建时 colorId 为空：用颜色名解析出 DB colorId，
                // 以便按 colorId 匹配到"只有 colorId 无 colorName"的旧数据 SKU
                if (mappedColorId == null && StringUtils.hasText(input.getColorName())) {
                    mappedColorId = colorIdByName.get(input.getColorName());
                }
                // upsert：按 id 优先、其次按组合（colorId/colorName + 门幅）匹配
                ProductSku matched = matchExistingSku(skuById, existingSkus, input, mappedColorId);
                if (matched != null) {
                    // 保留主键原地更新，避免订单里存的旧 skuId 失效
                    matched.setColorId(mappedColorId != null ? mappedColorId : matched.getColorId());
                    matched.setColorName(input.getColorName());
                    matched.setDoorWidth(input.getDoorWidth());
                    matched.setPrice(input.getPrice() != null ? input.getPrice() : matched.getPrice());
                    matched.setStock(input.getStock() != null ? input.getStock() : matched.getStock());
                    if (StringUtils.hasText(input.getSkuCode())) {
                        matched.setSkuCode(input.getSkuCode());
                    }
                    productSkuMapper.updateById(matched);
                    keptSkuIds.add(matched.getId());
                } else {
                    ProductSku entity = new ProductSku();
                    entity.setTenantId(tenantId);
                    entity.setProductId(productId);
                    entity.setColorId(mappedColorId);
                    entity.setColorName(input.getColorName());
                    entity.setDoorWidth(input.getDoorWidth());
                    entity.setPrice(input.getPrice() != null ? input.getPrice() : BigDecimal.ZERO);
                    entity.setStock(input.getStock() != null ? input.getStock() : BigDecimal.ZERO);
                    // 优先使用传入的 skuCode，未传入则自动生成
                    String skuCode = StringUtils.hasText(input.getSkuCode())
                            ? input.getSkuCode()
                            : generateSkuCode(productId, productSkuCode,
                                    colorSeqMap.getOrDefault(input.getColorName(), 0),
                                    input.getDoorWidth());
                    entity.setSkuCode(skuCode);
                    entity.setSalesCount(BigDecimal.ZERO);
                    productSkuMapper.insert(entity);
                    createdSkus.add(entity);
                    keptSkuIds.add(entity.getId());
                }
            }
        }

        // 缺失才删：删除本次请求未保留的旧 SKU/颜色（先 SKU 后颜色）
        // pruneMissing=false 的是**批量导入**路径（issue #5154）：商家在导入页看不到库里已有的 SKU，
        // 按「提交集合 = 全量声明」删会把批次挂着的 SKU 静默删掉（断链）⇒ 导入一律只增改不删。
        if (pruneMissing) {
            for (ProductSku s : existingSkus) {
                if (!keptSkuIds.contains(s.getId())) {
                    productSkuMapper.deleteById(s.getId());
                }
            }
            for (ProductColor c : existingColors) {
                if (!keptColorIds.contains(c.getId())) {
                    productColorMapper.deleteById(c.getId());
                }
            }
        }

        // 库存台账（issue #4157）：两条腿都落账 ——
        //   ① 既有 SKU 的**真实**变化：变更前快照 vs 变更后实际值（无变化不落行 ⇒ 台账里不出现
        //      delta=0 噪声行；`recordChangesAgainstSnapshot` 是既有唯一比对实现）；
        //   ② 新 SKU 首行 = **基线行**（用户 2026-09-25 裁定，见 #5496 建议①）：与既有「历史不回填」
        //      口径一致 —— 存量不追补，但**新发生的变更必须落账** ⇒ 链条从 0 起算、首行有前驱，
        //      而不是在「新 SKU 首次库存」处断头。
        stockLedgerService.recordChangesAgainstSnapshot(tenantId, stockBeforeSave,
                StockLedger.REASON_MANUAL, null, LEDGER_NOTE_SKU_CHANGED);
        for (ProductSku created : createdSkus) {
            BigDecimal initial = StockQuantity.orZero(created.getStock());
            if (initial.compareTo(BigDecimal.ZERO) == 0) {
                // 初始库存为 0 不落行：0 变更行是噪声（与手工调整 / 快照比对同一口径）
                continue;
            }
            stockLedgerService.record(tenantId, productId, created.getId(), created.getSkuCode(),
                    BigDecimal.ZERO, initial, StockLedger.REASON_MANUAL, null, LEDGER_NOTE_SKU_BASELINE);
        }

        // SKU 变更后回写商品级 stock（issue #4038）：商品库存的**唯一权威是 SKU 级**，
        // `products.stock` 只是派生冗余列。此前该列可被任意写（建品/改品都写它）却无人读，
        // 于是持续漂移：实测 311/497 个商品与 SKU 汇总不一致、有 SKU 的 351 个里 299 个恒为 0
        // （而 SKU 合计可以很大，如实测 `2699系列雪尼尔窗帘面料` 商品级 0 / SKU 合计 9599）。
        syncProductStockFromSkus(productId);
    }

    /**
     * 把商品级 `products.stock` 回写为 SKU 汇总（派生列，非权威）—— 唯一写入入口。
     *
     * <p>与 {@link #adjustStockForAgent} 同一口径（那里也是「商品级 stock 仅作冗余展示，
     * 同步为 SKU 汇总值」）。只在**有 SKU 记录**时回写：无 SKU 的商品该列是唯一现存信息，
     * 回写成 `SUM(空) = 0` 会把有值的库存抹掉（issue #4038 的 R2 负例）。
     */
    private void syncProductStockFromSkus(String productId) {
        List<ProductSku> skus = productSkuMapper.selectList(
                new LambdaQueryWrapper<ProductSku>()
                        .eq(ProductSku::getProductId, productId)
                        .select(ProductSku::getStock));
        if (skus == null || skus.isEmpty()) {
            return;
        }
        // issue #5063（V115）：库存列是 NUMERIC(12,1) ⇒ 用 BigDecimal 求和（改前 mapToInt 会把
        // 小数米数截断成整数再把派生列写错 —— 派生列一旦错了，列表页显示的就是假库存）。
        BigDecimal total = StockQuantity.sum(
                skus.stream().map(ProductSku::getStock).collect(Collectors.toList()));
        // 只带 id + stock 的部分更新：MyBatis-Plus updateById 不覆盖未设置字段
        Product stockSync = new Product();
        stockSync.setId(productId);
        stockSync.setStock(total);
        productMapper.updateById(stockSync);
    }

    /**
     * 在现有 SKU 中匹配输入：
     * 1. 优先按真实 DB id（前端表单携带）；2. 其次按组合（colorId/colorName + doorWidth，Agent 按名称重建路径）。
     *
     * <p><b>V108（用户裁定 2026-09-21）</b>：组合里<b>不再有售卖方式</b> ——
     * 「商品的售卖方式整卷/散件不能作为 SKU 的组合项，只能作为基础属性，商品的 SKU 由颜色+门幅组成即可」
     * ⇒ SKU 组合 = 颜色 × 门幅。原「售卖方式中文标签 vs 英文枚举」的归一化比较随之删除
     * （该维度不存在了）；调用方若仍传售卖方式，它<b>不参与匹配</b>。</p>
     *
     * <p>门幅的**归一化口径**（issue #3616，同族 #3539/#3546）保留：「2.8米」与「2.8」库内两种写法
     * 都真实存在（demo-seed 落 '2.8米'、eval 种子落 '2.8'；{@link #toWidthShort(String)} 早已把两者
     * 当同一门幅）。字面 {@code Objects.equals} 会把**同一组合**判为不同 → 旧行被当成「缺失」物理删除
     * + 插入新行（主键漂移 → 订单 processingInfo 里旧 skuId 断链，正是本方法上方注释要防的），
     * 且失败静默无报错 ⇒ 必须过 {@link #normalizeDoorWidth(String)}（双侧归一），
     * 不新增第二套映射、不新增/删除 SKU 行。</p>
     */
    private ProductSku matchExistingSku(Map<Long, ProductSku> skuById, List<ProductSku> existingSkus,
                                        ProductSkuInput input, Long resolvedColorId) {
        if (input.getId() != null && input.getId() > 0) {
            ProductSku byId = skuById.get(input.getId());
            if (byId != null) {
                return byId;
            }
        }
        for (ProductSku s : existingSkus) {
            boolean colorMatches = (resolvedColorId != null && resolvedColorId.equals(s.getColorId()))
                    || (StringUtils.hasText(input.getColorName())
                        && input.getColorName().equals(s.getColorName()));
            // 组合 = 颜色 + 门幅（V108：售卖方式已不是 SKU 维度 ⇒ 不再参与匹配）
            if (colorMatches
                    && java.util.Objects.equals(normalizeDoorWidth(input.getDoorWidth()),
                                                normalizeDoorWidth(s.getDoorWidth()))) {
                return s;
            }
        }
        return null;
    }

    /**
     * 生成 SKU 编码
     * 格式: {货号}-{颜色序号2位}-{门幅缩写}
     * 示例: 50181A94-01-28（有货号优先用货号），984D744B-01-28（无货号兜底用ID前缀）
     *
     * <p>V108：售卖方式缩写那一段（原 {@code -SJ-}/{@code -ZJ-}）已删 ——
     * SKU 组合只有 颜色 × 门幅，售卖方式是商品级属性，不属于 SKU 身份。</p>
     */
    private String generateSkuCode(String productId, String productSkuCode, int colorSeq,
                                   String doorWidth) {
        String prefix;
        if (StringUtils.hasText(productSkuCode)) {
            prefix = productSkuCode.toUpperCase();
        } else {
            prefix = productId.length() >= 8 ? productId.substring(0, 8).toUpperCase() : productId.toUpperCase();
        }
        return String.format("%s-%02d-%s", prefix, colorSeq, toWidthShort(doorWidth));
    }

    /** 门幅 → 数字缩写: "2.8米"→"28", "3.2米"→"32" */
    private String toWidthShort(String doorWidth) {
        if (doorWidth == null) return "XX";
        // 提取数字部分（含小数点），拼接成简短代码
        String digits = doorWidth.replaceAll("[^0-9.]", "");
        // 去掉小数点: "2.8"→"28", "3.2"→"32", "3.4"→"34"
        return digits.replace(".", "");
    }

    /**
     * 保存/更新商品属性（brand + specifications）到 product_attributes 表
     * 先删后插，语义为全量覆盖。调用方负责判断是否需要调用。
     */
    private void saveProductAttributes(String productId, Long tenantId,
                                       String brand, Map<String, String> specifications) {
        // 删除已有属性（用于更新场景）
        productAttributeMapper.delete(new LambdaQueryWrapper<ProductAttribute>()
                .eq(ProductAttribute::getProductId, productId));

        List<ProductAttribute> attrs = new ArrayList<>();
        if (StringUtils.hasText(brand)) {
            ProductAttribute attr = new ProductAttribute();
            attr.setProductId(productId);
            attr.setTenantId(tenantId);
            attr.setAttrKey(ATTR_KEY_BRAND);
            attr.setAttrValue(brand);
            attrs.add(attr);
        }
        if (specifications != null) {
            specifications.forEach((key, value) -> {
                if (StringUtils.hasText(key) && StringUtils.hasText(value)) {
                    ProductAttribute attr = new ProductAttribute();
                    attr.setProductId(productId);
                    attr.setTenantId(tenantId);
                    attr.setAttrKey(key);
                    attr.setAttrValue(value);
                    attrs.add(attr);
                }
            });
        }
        if (!attrs.isEmpty()) {
            attrs.forEach(productAttributeMapper::insert);
        }
    }

    /**
     * 查询商品属性并填充到 ProductResponse。
     * brand 单独取出，其余属性放入 specifications map。
     */
    private void fillProductAttributes(ProductResponse response, String productId) {
        List<ProductAttribute> attrs = productAttributeMapper.selectList(
                new LambdaQueryWrapper<ProductAttribute>()
                        .eq(ProductAttribute::getProductId, productId)
        );
        if (attrs == null || attrs.isEmpty()) {
            return;
        }
        Map<String, String> specifications = new LinkedHashMap<>();
        for (ProductAttribute attr : attrs) {
            if (!StringUtils.hasText(attr.getAttrKey())) {
                continue;
            }
            if (ATTR_KEY_BRAND.equals(attr.getAttrKey())) {
                response.setBrand(attr.getAttrValue());
            } else {
                specifications.put(attr.getAttrKey(), attr.getAttrValue());
            }
        }
        if (!specifications.isEmpty()) {
            response.setSpecifications(specifications);
        }
    }

    /**
     * 删除商品（逻辑删除）
     * 状态约束与 batchDelete 一致：仅 draft/off_sale 可删，on_sale/under_review 拒绝。
     */
    @Transactional(rollbackFor = Exception.class)
    public void deleteProduct(String id, Long tenantId) {
        Product product = productMapper.selectById(id);
        if (product == null) {
            throw BusinessException.notFound("商品");
        }

        String currentStatus = product.getStatus() != null ? product.getStatus() : "draft";
        if (!Set.of("draft", "off_sale").contains(currentStatus)) {
            String statusLabel = PRODUCT_STATUS_LABELS.getOrDefault(currentStatus, currentStatus);
            throw BusinessException.validationError("当前状态[" + statusLabel + "]不允许删除，请先下架后再删除");
        }

        productMapper.deleteById(id);
        log.info("删除商品成功: id={}", id);
    }

    /**
     * 校验商品是否可售（供订单域 createOrder 扣库存前调用，属商品侧职责）。
     * 可售条件：商品存在、未被逻辑删除（selectById 经 @TableLogic 自动过滤 deleted=0）、
     * 属于当前租户、status = on_sale。
     *
     * @return null 表示可售；否则返回不可售原因（中文，可直接透传前端/agent 展示）
     */
    public String validateSellable(String productId, Long tenantId) {
        Product product = productMapper.selectById(productId);
        if (product == null) {
            return "商品不存在或已删除";
        }
        if (product.getTenantId() != null && !product.getTenantId().equals(tenantId)) {
            return "商品不属于当前租户";
        }
        if (!"on_sale".equals(product.getStatus())) {
            return "商品当前状态[" + (product.getStatus() != null ? product.getStatus() : "未知")
                    + "]，不可售卖";
        }
        return null;
    }

    /**
     * 更新商品状态（含状态流转校验）
     */
    @Transactional(rollbackFor = Exception.class)
    public void updateProductStatus(String id, String status, Long tenantId) {
        Product product = productMapper.selectById(id);
        if (product == null) {
            throw BusinessException.notFound("商品");
        }
        applyStatusTransition(product, status);
        productMapper.updateById(product);

        log.info("更新商品状态成功: id={}, status={}", id, status);
    }

    /**
     * 状态流转校验（不写库、不改实体）——违反状态机时抛业务错误。
     *
     * 状态机唯一入口，供 @see #updateProductStatus（表单端点）与
     * @see #updateProductForAgent（Agent 更新端点）共用，避免两处各写一套流转规则。
     * 单独抽出是为了让调用方能「先校验后落库」：非法流转在任何写入之前失败。
     */
    private void validateStatusTransition(String currentStatus, String status) {
        if (currentStatus == null) {
            currentStatus = "draft";
        }

        List<String> allowedTransitions = STATUS_TRANSITIONS.get(currentStatus);
        if (allowedTransitions == null || !allowedTransitions.contains(status)) {
            String currentLabel = PRODUCT_STATUS_LABELS.getOrDefault(currentStatus, currentStatus);
            String targetLabel = PRODUCT_STATUS_LABELS.getOrDefault(status, status);
            List<String> allowedLabels = allowedTransitions != null
                    ? allowedTransitions.stream().map(s -> PRODUCT_STATUS_LABELS.getOrDefault(s, s)).toList()
                    : List.of();
            throw BusinessException.validationError(
                    String.format("状态流转无效: %s → %s，允许的目标状态: %s",
                            currentLabel, targetLabel,
                            allowedLabels.isEmpty() ? "无" : String.join("/", allowedLabels)));
        }
    }

    /**
     * 状态流转校验并就地落到实体（不写库，由调用方统一持久化）。
     */
    private void applyStatusTransition(Product product, String status) {
        validateStatusTransition(product.getStatus(), status);
        product.setStatus(status);
        product.setEditedBy(getCurrentUsername());
        product.setEditedAt(OffsetDateTime.now());
    }

    /**
     * 设置/取消商品推荐标记（C 端「新品推荐」位控制，商家显式打标）
     *
     * @param id          商品 ID
     * @param recommended true=推荐 / false=取消推荐
     * @param tenantId    租户 ID
     */
    public void updateProductRecommended(String id, Boolean recommended, Long tenantId) {
        Product product = productMapper.selectById(id);
        if (product == null) {
            throw BusinessException.notFound("商品");
        }
        if (Boolean.TRUE.equals(recommended)) {
            // 只允许推荐已上架商品（下架商品不应出现在 C 端推荐位）
            String currentStatus = product.getStatus() == null ? "draft" : product.getStatus();
            if (!"on_sale".equals(currentStatus)) {
                String label = PRODUCT_STATUS_LABELS.getOrDefault(currentStatus, currentStatus);
                throw BusinessException.validationError(
                        String.format("仅上架商品可设为推荐，当前状态: %s", label));
            }
        }
        product.setRecommended(recommended);
        product.setEditedBy(getCurrentUsername());
        product.setEditedAt(OffsetDateTime.now());
        productMapper.updateById(product);
        log.info("更新商品推荐标记成功: id={}, recommended={}, tenantId={}", id, recommended, tenantId);
    }

    // ========== 批量操作 ==========

    /**
     * 批量上架
     * 只有 off_sale/in_warehouse 状态的商品可上架
     */
    @Transactional(rollbackFor = Exception.class)
    public BatchOperationResult batchOnShelf(List<String> productIds, Long tenantId) {
        BatchOperationResult result = BatchOperationResult.create();
        if (productIds == null || productIds.isEmpty()) {
            return result;
        }
        Set<String> allowedStatuses = Set.of("off_sale");

        for (String id : productIds) {
            Product product = productMapper.selectById(id);
            if (product == null) {
                result.addError(id, "商品不存在");
                continue;
            }
            String currentStatus = product.getStatus() != null ? product.getStatus() : "draft";
            if (!allowedStatuses.contains(currentStatus)) {
                String statusLabel = PRODUCT_STATUS_LABELS.getOrDefault(currentStatus, currentStatus);
                result.addError(id, "当前状态[" + statusLabel + "]不允许上架");
                continue;
            }
            product.setStatus("on_sale");
            product.setEditedBy(getCurrentUsername());
            product.setEditedAt(OffsetDateTime.now());
            productMapper.updateById(product);
            result.addSuccess();
        }

        log.info("批量上架完成: success={}, failed={}", result.getSuccess(), result.getFailed());
        return result;
    }

    /**
     * 批量下架
     * 只有 on_sale 状态的商品可下架
     */
    @Transactional(rollbackFor = Exception.class)
    public BatchOperationResult batchOffShelf(List<String> productIds, Long tenantId) {
        BatchOperationResult result = BatchOperationResult.create();
        if (productIds == null || productIds.isEmpty()) {
            return result;
        }

        for (String id : productIds) {
            Product product = productMapper.selectById(id);
            if (product == null) {
                result.addError(id, "商品不存在");
                continue;
            }
            String currentStatus = product.getStatus() != null ? product.getStatus() : "draft";
            if (!"on_sale".equals(currentStatus)) {
                String statusLabel = PRODUCT_STATUS_LABELS.getOrDefault(currentStatus, currentStatus);
                result.addError(id, "当前状态[" + statusLabel + "]不允许下架");
                continue;
            }
            product.setStatus("off_sale");
            product.setEditedBy(getCurrentUsername());
            product.setEditedAt(OffsetDateTime.now());
            productMapper.updateById(product);
            result.addSuccess();
        }

        log.info("批量下架完成: success={}, failed={}", result.getSuccess(), result.getFailed());
        return result;
    }

    /**
     * 批量删除
     * 只有 draft/off_sale 状态可删除；on_sale 不可删
     */
    @Transactional(rollbackFor = Exception.class)
    public BatchOperationResult batchDelete(List<String> productIds, Long tenantId) {
        BatchOperationResult result = BatchOperationResult.create();
        if (productIds == null || productIds.isEmpty()) {
            return result;
        }
        Set<String> allowedStatuses = Set.of("draft", "off_sale");

        for (String id : productIds) {
            Product product = productMapper.selectById(id);
            if (product == null) {
                result.addError(id, "商品不存在");
                continue;
            }
            String currentStatus = product.getStatus() != null ? product.getStatus() : "draft";
            if (!allowedStatuses.contains(currentStatus)) {
                String statusLabel = PRODUCT_STATUS_LABELS.getOrDefault(currentStatus, currentStatus);
                result.addError(id, "当前状态[" + statusLabel + "]不允许删除");
                continue;
            }
            productMapper.deleteById(id);
            result.addSuccess();
        }

        log.info("批量删除完成: success={}, failed={}", result.getSuccess(), result.getFailed());
        return result;
    }

    // ========== 导入/导出 ==========

    /**
     * 批量导入商品 + SKU（issue #5154）—— 迁移 / 期初批次建账的**前置**：
     * SKU 不存在 ⇒ 入库批次挂不上 ⇒ 闭环断在这里。
     *
     * <h2>四条口径</h2>
     * <ol>
     *   <li><b>幂等</b>：幂等键 = {@code (tenant_id, 货号)}（{@code products.sku_code}）。
     *       命中即**原地更新**（保留商品主键，SKU 按「颜色 + 门幅」匹配后原地更新）
     *       ⇒ 同一文件重复导入不产生重复商品/SKU，且订单/批次里存的旧 skuId 不断链。
     *       货号因此是**必填列**（缺了它无从保证幂等 —— 宁可报错，不要静默建重复）。</li>
     *   <li><b>逐行校验报告，不静默跳过</b>：每个数据行必落在「成功 / 失败 / 空白」三桶之一
     *       （{@code total == successCount + failCount + blankRows}，见 {@link ProductImportResult}），
     *       失败行带**行号 + 货号 + 可行动原因**。</li>
     *   <li><b>只增改不删</b>：文件里没有的既有颜色/SKU **不删**（{@code pruneMissing=false}）。
     *       表单改品的口径是「提交上来的集合 = 全量声明」（商家在表单里看得见全部现有 SKU），
     *       但导入页上商家**看不到**库里已有的 SKU ⇒ 按缺失删会静默删掉批次挂着的 SKU（断链）。</li>
     *   <li><b>一进一出同构</b>：表头按**名字**定位（{@link #IMPORT_HEADERS} 与 {@link #EXPORT_HEADERS}
     *       逐字同名的那 5 列就是导出面），列序无关、允许多余列、容忍模板里的 `*` 号。</li>
     * </ol>
     *
     * <h2>行级原子（不是整包回滚）</h2>
     * 校验全部在写入**之前**完成 ⇒ 非法行零落库副作用；同一文件里的合法行照常落库，
     * 并在报告里逐行可见（迁移场景下"全对才导"会让商家反复重传整包）。
     */
    @Transactional(rollbackFor = Exception.class)
    public ProductImportResult importProducts(MultipartFile file, Long tenantId) {
        ProductImportResult result = ProductImportResult.create();

        try (Workbook workbook = WorkbookFactory.create(file.getInputStream())) {
            Sheet sheet = workbook.getSheetAt(0);
            if (sheet == null) {
                throw BusinessException.validationError("Excel文件为空");
            }
            Map<String, Integer> header = resolveImportHeader(sheet.getRow(0));

            // ── 阶段 1：全文件解析 + 校验（**零写入**）──
            List<ImportedRow> parsed = new ArrayList<>();
            int lastRow = sheet.getLastRowNum();
            for (int i = 1; i <= lastRow; i++) {
                result.setTotal(result.getTotal() + 1);
                int rowNo = i + 1;                       // Excel 行号（1-based，表头 = 1）
                Row row = sheet.getRow(i);
                if (isBlankRow(row)) {
                    result.addBlankRow();                // 显式报数 —— 不是 `continue` 了事
                    continue;
                }
                String skuCode = cellByHeader(row, header, "货号");
                try {
                    parsed.add(parseImportedRow(row, rowNo, header));
                } catch (Exception e) {
                    result.addError(rowNo, skuCode, messageOf(e));
                }
            }

            // ── 阶段 2：同货号归组（一货号 = 一个商品，行 = 该商品的 SKU 行）──
            Map<String, List<ImportedRow>> groups = new LinkedHashMap<>();
            for (ImportedRow parsedRow : parsed) {
                List<ImportedRow> group = groups.computeIfAbsent(
                        parsedRow.skuCode, k -> new ArrayList<>());
                String conflict = conflictWithGroup(group, parsedRow);
                if (conflict != null) {
                    result.addError(parsedRow.rowNo, parsedRow.skuCode, conflict);
                    continue;
                }
                group.add(parsedRow);
            }

            // ── 阶段 3：逐货号落库（组内一致 ⇒ 组级原子：本组任一步失败则本组所有行都报错）──
            for (List<ImportedRow> group : groups.values()) {
                try {
                    upsertImportedProduct(group, tenantId, result);
                    for (int i = 0; i < group.size(); i++) {
                        result.addSuccess();
                    }
                } catch (Exception e) {
                    log.warn("导入货号 {} 失败", group.get(0).skuCode, e);
                    for (ImportedRow row : group) {
                        result.addError(row.rowNo, row.skuCode, messageOf(e));
                    }
                }
            }

        } catch (BusinessException e) {
            throw e;
        } catch (Exception e) {
            log.error("解析Excel文件失败", e);
            throw BusinessException.validationError("解析Excel文件失败: " + e.getMessage());
        }

        log.info("导入商品完成: total={}, success={}, failed={}, blank={}, created={}, updated={}",
                result.getTotal(), result.getSuccessCount(), result.getFailCount(), result.getBlankRows(),
                result.getCreatedProducts(), result.getUpdatedProducts());
        return result;
    }

    /**
     * 表头解析：按**名字**建「表头 → 列号」索引（列序无关），缺失必填列 ⇒ 整包拒绝。
     *
     * <p>为什么是名字而不是列号：改前实现把列号写死（0=名称/1=货号/…），于是①加了 SKU 维度就只能改列号、
     * 导出面与导入面靠"人肉对齐"；②商家挪一列就静默错位。按名字定位后，
     * 「导出面里同名的那几列」天然就是导入面（一进一出同构的机械形态）。</p>
     */
    private Map<String, Integer> resolveImportHeader(Row headerRow) {
        if (headerRow == null) {
            throw BusinessException.validationError(
                    "Excel 缺少表头行（第 1 行）—— 请在商品管理页点「下载导入模板」获取标准表头");
        }
        Map<String, Integer> index = new HashMap<>();
        for (int c = 0; c <= headerRow.getLastCellNum(); c++) {
            String name = normalizeHeader(getCellStringValue(headerRow, c));
            if (name != null) {
                index.putIfAbsent(name, c);
            }
        }
        List<String> missing = REQUIRED_IMPORT_HEADERS.stream()
                .filter(h -> !index.containsKey(h))
                .toList();
        if (!missing.isEmpty()) {
            throw BusinessException.validationError(String.format(
                    "Excel 表头缺少必填列：%s（可列：%s）—— 请在商品管理页点「下载导入模板」获取标准表头",
                    String.join("、", missing), String.join("、", OPTIONAL_IMPORT_HEADERS)));
        }
        return index;
    }

    /** 表头归一化：去空白 + 去模板里的必填星号（`商品名称*` 与 `商品名称` 视为同一列）。 */
    private static String normalizeHeader(String raw) {
        if (!StringUtils.hasText(raw)) {
            return null;
        }
        String name = raw.replace("*", "").replace("＊", "").trim();
        return StringUtils.hasText(name) ? name : null;
    }

    /** 整行留空（无任何非空单元格）⇒ 计入 {@code blankRows}，既不算成功也不算失败。 */
    private boolean isBlankRow(Row row) {
        if (row == null || row.getLastCellNum() < 0) {
            return true;
        }
        for (int c = 0; c < row.getLastCellNum(); c++) {
            if (StringUtils.hasText(getCellStringValue(row, c))) {
                return false;
            }
        }
        return true;
    }

    /**
     * 按**表头名**读字符串单元格。
     *
     * <p>表头里没有这一列 ⇒ {@code null}（**可列缺失不是错误**：{@code 分类ID} / {@code 描述} /
     * {@code 颜色} / {@code 门幅} / {@code SKU编码} 都是可列）。</p>
     *
     * <p>为什么单独一个方法而不是直接 {@code getCellStringValue(row, header.get(x))}：
     * {@code header.get(x)} 是 {@code Integer}，缺列时是 {@code null} ⇒ 传进 {@code int} 形参
     * 会在**每一行**拆箱 NPE（本单实测踩过：少一列「分类ID」⇒ 全表每一行都报
     * 「NullPointerException（无错误信息）」，且没有任何一行被导入）。</p>
     */
    private String cellByHeader(Row row, Map<String, Integer> header, String headerName) {
        Integer cellIndex = header.get(headerName);
        return row == null || cellIndex == null ? null : getCellStringValue(row, cellIndex);
    }

    /**
     * 解析一个数据行（**只读、零副作用**）—— 所有校验都在这里完成，因此失败行不会写任何东西。
     */
    private ImportedRow parseImportedRow(Row row, int rowNo, Map<String, Integer> header) {
        ImportedRow parsedRow = new ImportedRow();
        parsedRow.rowNo = rowNo;

        parsedRow.name = cellByHeader(row, header, "商品名称");
        if (!StringUtils.hasText(parsedRow.name)) {
            throw BusinessException.validationError("商品名称不能为空");
        }

        parsedRow.skuCode = cellByHeader(row, header, "货号");
        if (!StringUtils.hasText(parsedRow.skuCode)) {
            throw BusinessException.validationError(
                    "货号不能为空 —— 货号是重复导入去重的依据（幂等键 = 货号），缺了它无法保证"
                            + "「同一文件重跑不产生重复商品」");
        }

        parsedRow.categoryId = normalizeBlankToNull(cellByHeader(row, header, "分类ID"));
        // 分类不存在 ⇒ 本行报错（而不是留到 insert 时 FK 违例变成 500）
        validateCategory(parsedRow.categoryId);
        parsedRow.description = cellByHeader(row, header, "描述");

        parsedRow.price = readCellNumber(row, header.get("价格"), "价格", rowNo);
        if (parsedRow.price == null) {
            throw BusinessException.validationError("价格不能为空（价格是必填列：商品基础价与 SKU 价都以它为准）");
        }
        if (parsedRow.price.compareTo(BigDecimal.ZERO) <= 0) {
            throw BusinessException.validationError(
                    "价格必须大于 0，当前值 " + parsedRow.price.toPlainString());
        }

        // issue #5063（V115）：库存是 1 位小数口径（0.1 米粒度）⇒ 复用 StockQuantity 的准入判据，
        // **不在这里另写一套小数位判断**；超过 1 位小数显式拒绝（禁止静默取整/截断）。
        parsedRow.stock = StockQuantity.requireOneDecimalOrNull(
                readCellNumber(row, header.get("库存"), "库存", rowNo), "第 " + rowNo + " 行库存");

        parsedRow.colorName = normalizeBlankToNull(cellByHeader(row, header, "颜色"));
        parsedRow.doorWidth = normalizeBlankToNull(cellByHeader(row, header, "门幅"));
        if ((parsedRow.colorName == null) != (parsedRow.doorWidth == null)) {
            throw BusinessException.validationError(String.format(
                    "颜色与门幅必须**成对填写**（SKU 组合 = 颜色 × 门幅）：本行%s"
                            + " —— 两者都填才生成 SKU，都不填则该行只建商品",
                    parsedRow.colorName == null ? "只填了门幅" : "只填了颜色"));
        }
        parsedRow.hasSku = parsedRow.colorName != null;
        parsedRow.skuCodeOfSku = normalizeBlankToNull(cellByHeader(row, header, "SKU编码"));
        return parsedRow;
    }

    /**
     * 读一个数值单元格（**不猜、不吞**）：空/缺列 ⇒ {@code null}（= 未填），非数字 ⇒ 显式报错。
     *
     * <p>改前实现把这两种情况都当成 {@code 0}（`getCellNumericValue` 对空单元格返回 0、
     * 库存解析异常被 catch 后 `log.warn("库存解析失败，默认0")` 继续跑）——
     * 商家填的 60 米会静默变 0，而报告里一行错都没有。</p>
     */
    private BigDecimal readCellNumber(Row row, Integer cellIndex, String field, int rowNo) {
        Cell cell = cellIndex == null ? null : row.getCell(cellIndex);
        if (cell == null) {
            return null;
        }
        switch (cell.getCellType()) {
            case NUMERIC:
                return BigDecimal.valueOf(cell.getNumericCellValue());
            case STRING: {
                String text = cell.getStringCellValue().trim();
                if (!StringUtils.hasText(text)) {
                    return null;
                }
                try {
                    return new BigDecimal(text);
                } catch (NumberFormatException e) {
                    throw BusinessException.validationError(String.format(
                            "第 %d 行的%s不是数字：「%s」—— 请填数字后重试", rowNo, field, text));
                }
            }
            case BLANK:
                return null;
            default:
                throw BusinessException.validationError(String.format(
                        "第 %d 行的%s单元格类型无法解析（请填数字）", rowNo, field));
        }
    }

    /**
     * 同货号行之间的三条一致性校验 —— 三条都是「不静默」的形态：
     * <ol>
     *   <li>商品级字段互相矛盾（**含价格** —— 涉钱字段不取"最后一行为准"）；</li>
     *   <li>同一 {@code (颜色, 门幅)} 组合重复（否则后一行会**静默覆盖**前一行的库存）；</li>
     *   <li>有的行填了 SKU 维度、有的没填（那一行的库存会**无处安放**而静默丢失）。</li>
     * </ol>
     *
     * @return 冲突的可行动说明；{@code null} = 无冲突（该行可以并入本组）
     */
    private String conflictWithGroup(List<ImportedRow> group, ImportedRow cur) {
        if (group.isEmpty()) {
            return null;
        }
        ImportedRow head = group.get(0);
        String[] fields = {"商品名称", "分类ID", "描述"};
        String[] headValues = {head.name, head.categoryId, head.description};
        String[] curValues = {cur.name, cur.categoryId, cur.description};
        for (int i = 0; i < fields.length; i++) {
            if (!Objects.equals(headValues[i], curValues[i])) {
                return conflictText(cur, head, fields[i], curValues[i], headValues[i]);
            }
        }
        if (head.price.compareTo(cur.price) != 0) {
            return conflictText(cur, head, "价格", cur.price.toPlainString(), head.price.toPlainString());
        }
        if (head.hasSku != cur.hasSku) {
            return String.format(
                    "第 %d 行与第 %d 行不一致：同一货号的行必须**要么都填**颜色+门幅、**要么都不填**"
                            + "（混填会让本行的库存无处安放）", cur.rowNo, head.rowNo);
        }
        if (cur.hasSku && group.stream().anyMatch(r -> r.hasSku
                && Objects.equals(r.colorName, cur.colorName)
                && Objects.equals(normalizeDoorWidth(r.doorWidth), normalizeDoorWidth(cur.doorWidth)))) {
            return String.format(
                    "第 %d 行的「颜色 + 门幅」组合重复：货号 %s 的 %s/%s 在同一文件里已出现过"
                            + " —— 同一组合只能出现一次，否则后一行会**静默覆盖**前一行的库存",
                    cur.rowNo, cur.skuCode, cur.colorName, cur.doorWidth);
        }
        return null;
    }

    private String conflictText(ImportedRow cur, ImportedRow head, String field,
                                String curValue, String headValue) {
        return String.format(
                "第 %d 行与第 %d 行的「%s」不一致（%s vs %s）—— 同一货号 %s 只能有一份商品级信息"
                        + "（价格等涉钱字段不取「最后一行为准」）",
                cur.rowNo, head.rowNo, field, orDash(curValue), orDash(headValue), cur.skuCode);
    }

    private static String orDash(String value) {
        return StringUtils.hasText(value) ? value : "空";
    }

    private static String messageOf(Throwable e) {
        return StringUtils.hasText(e.getMessage())
                ? e.getMessage()
                : e.getClass().getSimpleName() + "（无错误信息，请把该行内容反馈给技术支持）";
    }

    /**
     * 建品 upsert（幂等键 = 租户 + 货号）+ 写入本组的颜色/SKU。
     *
     * <p>写入 SKU 走的是**与表单建品/改品完全同一条路径**（{@link #saveColorsAndSkus} +
     * {@link #matchExistingSku} 的「颜色 + 门幅」匹配），不另造第二套写 SKU 的代码 ——
     * 两套口径迟早分叉（一处原地更新、一处删旧插新 ⇒ 旧 skuId 断链）。</p>
     */
    private void upsertImportedProduct(List<ImportedRow> group, Long tenantId, ProductImportResult result) {
        ImportedRow head = group.get(0);
        boolean groupHasSku = group.stream().anyMatch(r -> r.hasSku);

        // 幂等键查询：命中 ⇒ 原地更新（不新建行）；未命中 ⇒ 新建
        Product existing = productMapper.selectByTenantAndSkuCode(tenantId, head.skuCode);

        String productId;
        if (existing == null) {
            Product product = new Product();
            product.setName(head.name);
            product.setSkuCode(head.skuCode);
            product.setCategoryId(head.categoryId);
            product.setBasePrice(head.price);
            product.setDescription(head.description);
            // 有 SKU 组时该列是**派生列**（#4038，写完 SKU 由 syncProductStockFromSkus 回写汇总）
            product.setStock(StockQuantity.orZero(head.stock));
            product.setTenantId(tenantId);
            // 导入一律 draft（与既有导入口径一致）：上架是商家的显式动作，不由导入代劳
            product.setStatus("draft");
            product.setEditedBy(getCurrentUsername());
            product.setEditedAt(OffsetDateTime.now());
            productMapper.insert(product);
            productId = product.getId();
            result.addCreatedProduct();
        } else {
            Product patch = new Product();
            patch.setId(existing.getId());
            patch.setName(head.name);
            patch.setCategoryId(head.categoryId);
            patch.setBasePrice(head.price);
            patch.setDescription(head.description);
            // 「未填 = 不改」：无 SKU 组且库存列留空时不动既有库存（不得把留空当 0 清零）
            if (!groupHasSku && head.stock != null) {
                patch.setStock(head.stock);
            }
            patch.setEditedBy(getCurrentUsername());
            patch.setEditedAt(OffsetDateTime.now());
            productMapper.updateById(patch);
            productId = existing.getId();
            result.addUpdatedProduct();
        }

        List<ProductColorInput> colorInputs = new ArrayList<>();
        Set<String> doorWidths = new LinkedHashSet<>();
        List<ProductSkuInput> skuInputs = new ArrayList<>();
        for (ImportedRow row : group) {
            if (!row.hasSku) {
                continue;
            }
            if (colorInputs.stream().noneMatch(c -> Objects.equals(c.getColorName(), row.colorName))) {
                ProductColorInput color = new ProductColorInput();
                color.setColorName(row.colorName);
                colorInputs.add(color);
            }
            doorWidths.add(row.doorWidth);
            ProductSkuInput sku = new ProductSkuInput();
            sku.setColorName(row.colorName);
            sku.setDoorWidth(row.doorWidth);
            sku.setPrice(row.price);
            sku.setStock(row.stock);        // null = 未填 ⇒ 既有 SKU 保留原库存（saveColorsAndSkus 的既有语义）
            sku.setSkuCode(row.skuCodeOfSku);
            skuInputs.add(sku);
        }

        saveColorsAndSkus(productId, head.skuCode, tenantId, colorInputs, null,
                new ArrayList<>(doorWidths), head.price, StockQuantity.orZero(head.stock),
                skuInputs, false);
    }

    /**
     * 解析后的**一个数据行** = 该商品的一个 SKU 行（无 SKU 维度时只贡献商品级字段）。
     * 纯数据载体 + 只读校验的产物，不含任何写副作用。
     */
    private static final class ImportedRow {
        private int rowNo;
        private String name;
        private String skuCode;
        private String categoryId;
        private BigDecimal price;
        private BigDecimal stock;
        private String description;
        private String colorName;
        private String doorWidth;
        private String skuCodeOfSku;
        private boolean hasSku;
    }

    /**
     * 导出商品
     */
    public void exportProducts(ProductQueryRequest query, Long tenantId, HttpServletResponse response) throws IOException {
        // 查询商品列表（不分页，全量导出）
        query.setPage(1L);
        query.setSize(10000L);
        PageResponse<ProductResponse> pageResult = getProducts(query, tenantId);
        List<ProductResponse> products = pageResult.getItems();

        // 设置响应头
        String filename = URLEncoder.encode("商品列表.xlsx", StandardCharsets.UTF_8);
        response.setContentType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
        response.setHeader("Content-Disposition", "attachment; filename=" + filename);

        try (Workbook workbook = new XSSFWorkbook(); OutputStream out = response.getOutputStream()) {
            Sheet sheet = workbook.createSheet("商品列表");

            // 表头
            String[] headers = EXPORT_HEADERS;
            Row headerRow = sheet.createRow(0);
            CellStyle headerStyle = workbook.createCellStyle();
            Font headerFont = workbook.createFont();
            headerFont.setBold(true);
            headerStyle.setFont(headerFont);

            for (int i = 0; i < headers.length; i++) {
                Cell cell = headerRow.createCell(i);
                cell.setCellValue(headers[i]);
                cell.setCellStyle(headerStyle);
            }

            // 数据行
            for (int i = 0; i < products.size(); i++) {
                ProductResponse p = products.get(i);
                Row row = sheet.createRow(i + 1);
                row.createCell(0).setCellValue(p.getName() != null ? p.getName() : "");
                row.createCell(1).setCellValue(p.getSkuCode() != null ? p.getSkuCode() : "");
                row.createCell(2).setCellValue(p.getCategoryName() != null ? p.getCategoryName() : "");
                row.createCell(3).setCellValue(p.getBasePrice() != null ? p.getBasePrice().doubleValue() : 0);
                row.createCell(4).setCellValue(p.getStock() != null ? p.getStock().doubleValue() : 0);
                row.createCell(5).setCellValue(getStatusLabel(p.getStatus()));
                row.createCell(6).setCellValue(p.getDescription() != null ? p.getDescription() : "");
            }

            // 自动列宽
            for (int i = 0; i < headers.length; i++) {
                sheet.autoSizeColumn(i);
            }

            workbook.write(out);
        }
    }

    /**
     * 生成导入模板 —— 表头就是 {@link #IMPORT_HEADERS}（与导入解析**同一个常量**，
     * 因此"模板能填的列"与"导入认识的列"不可能分叉）。
     *
     * <p>示例行刻意演示两种形态：同一货号两行 = 一个商品的 2 个 SKU（颜色 × 门幅）；
     * 货号 PJ-001 一行的颜色/门幅留空 = 只建商品（无 SKU 商品）。</p>
     */
    public void generateImportTemplate(HttpServletResponse response) throws IOException {
        String filename = URLEncoder.encode("商品导入模板.xlsx", StandardCharsets.UTF_8);
        response.setContentType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
        response.setHeader("Content-Disposition", "attachment; filename=" + filename);

        try (Workbook workbook = new XSSFWorkbook(); OutputStream out = response.getOutputStream()) {
            Sheet sheet = workbook.createSheet("商品导入");

            // 表头
            Row headerRow = sheet.createRow(0);
            CellStyle headerStyle = workbook.createCellStyle();
            Font headerFont = workbook.createFont();
            headerFont.setBold(true);
            headerStyle.setFont(headerFont);

            for (int i = 0; i < IMPORT_HEADERS.length; i++) {
                Cell cell = headerRow.createCell(i);
                cell.setCellValue(IMPORT_HEADERS[i]);
                cell.setCellStyle(headerStyle);
            }

            // 示例行
            Object[][] examples = {
                    {"雪尼尔遮光帘", "MH-001", "", 128.5, 60.5, "米白色雪尼尔", "米白", "2.8m", "MH-001-01-28"},
                    {"雪尼尔遮光帘", "MH-001", "", 128.5, 12, "米白色雪尼尔", "米白", "3.2m", "MH-001-01-32"},
                    {"罗马杆配件", "PJ-001", "", 35, 8, "2.8m 铝合金杆", "", "", ""},
            };
            for (int r = 0; r < examples.length; r++) {
                Row row = sheet.createRow(r + 1);
                for (int c = 0; c < examples[r].length; c++) {
                    Object value = examples[r][c];
                    if (value instanceof Number number) {
                        row.createCell(c).setCellValue(number.doubleValue());
                    } else {
                        row.createCell(c).setCellValue(String.valueOf(value));
                    }
                }
            }

            for (int i = 0; i < IMPORT_HEADERS.length; i++) {
                sheet.autoSizeColumn(i);
            }

            workbook.write(out);
        }
    }

    // ========== 私有辅助方法 ==========

    /**
     * 获取单元格字符串值
     *
     * <p>数字单元格按**十进制原样**读（issue #5154）：Excel 里门幅常被敲成数字 `2.8`、货号常被敲成
     * `12345`。改前这里是 `String.valueOf((long) value)` ⇒ `2.8` 变 `"2"`（**门幅少 0.8 米**，
     * 而且因为没有报错、商家无从发现）。唯一消费方是本类的导入通路（导出侧自己写值、不读回），
     * 故就地改正，不另建一套读数函数。</p>
     */
    private String getCellStringValue(Row row, int cellIndex) {
        Cell cell = row.getCell(cellIndex);
        if (cell == null) return null;
        return switch (cell.getCellType()) {
            case STRING -> cell.getStringCellValue().trim();
            case NUMERIC -> BigDecimal.valueOf(cell.getNumericCellValue()).stripTrailingZeros().toPlainString();
            case BOOLEAN -> String.valueOf(cell.getBooleanCellValue());
            default -> null;
        };
    }

    /**
     * 状态标签
     */
    private String getStatusLabel(String status) {
        if (status == null) return "";
        return switch (status) {
            case "on_sale" -> "出售中";
            case "off_sale" -> "已下架";
            case "under_review" -> "审核中";
            case "draft" -> "草稿";
            default -> status;
        };
    }

    /**
     * 校验分类是否存在
     */
    private void validateCategory(String categoryId) {
        if (!StringUtils.hasText(categoryId)) {
            return;
        }
        Category category = categoryMapper.selectById(categoryId);
        if (category == null) {
            throw BusinessException.validationError("分类不存在");
        }
    }

    /**
     * 空分类归一化（#3665 冒烟 B1）：空串/纯空白一律归一化为 null。
     *
     * 背景：admin-web 存草稿时 categoryId 初值是 ''（`DEFAULT_FORM.categoryId: ''`），
     * `handleSubmit` 用 `...form` 原样透传，`buildProductPayload` 不清洗 → 后端
     * validateCategory 因 hasText('')==false 跳过校验，BeanUtils.copyProperties 把 ''
     * 写进实体 → insert/update category_id='' → products_category_id_fkey 违例（500）。
     * 产品契约是「草稿可不选分类」（products.category_id 列本就可空；见
     * ProductCreateRequest.categoryId 注释），故服务端统一以 null 表达"未选分类"，
     * 覆盖所有调用方（admin-web / agent BFF）。
     */
    private static String normalizeBlankToNull(String value) {
        return StringUtils.hasText(value) ? value : null;
    }

    /**
     * 根据目标状态校验必填字段：draft 状态允许留空，其他状态需严格校验。
     */
    private void validateRequiredForStatus(String status, String categoryId, java.math.BigDecimal basePrice) {
        // 未传或为 draft 时不做必填校验
        if (!StringUtils.hasText(status) || "draft".equalsIgnoreCase(status)) {
            return;
        }
        if (!StringUtils.hasText(categoryId)) {
            throw BusinessException.validationError("分类ID不能为空");
        }
        if (basePrice == null) {
            throw BusinessException.validationError("基础价格不能为空");
        }
        if (basePrice.signum() <= 0) {
            throw BusinessException.validationError("基础价格必须大于 0");
        }
    }

    /**
     * 获取分类名称映射
     */
    private Map<String, String> getCategoryNameMap(List<Product> products) {
        List<String> categoryIds = products.stream()
                .map(Product::getCategoryId)
                .filter(StringUtils::hasText)
                .distinct()
                .collect(Collectors.toList());

        if (categoryIds.isEmpty()) {
            return new HashMap<>();
        }

        LambdaQueryWrapper<Category> wrapper = new LambdaQueryWrapper<>();
        wrapper.in(Category::getId, categoryIds);
        List<Category> categories = categoryMapper.selectList(wrapper);

        Map<String, String> map = new HashMap<>();
        for (Category c : categories) {
            map.put(c.getId(), c.getName());
        }
        return map;
    }

    /**
     * 获取商品颜色数量
     */
    private int getColorCount(String productId) {
        Long count = productColorMapper.selectCount(
                new LambdaQueryWrapper<ProductColor>()
                        .eq(ProductColor::getProductId, productId)
        );
        return count != null ? count.intValue() : 0;
    }

    /**
     * 获取SKU总库存
     */
    private BigDecimal getTotalStock(String productId) {
        List<ProductSku> skus = productSkuMapper.selectList(
                new LambdaQueryWrapper<ProductSku>()
                        .eq(ProductSku::getProductId, productId)
                        .select(ProductSku::getStock)
        );
        // issue #5063（V115）：SKU 级是库存唯一权威（#4038），汇总必须是 BigDecimal
        // —— 改前 mapToInt 把 60.5 截成 60，商品详情/列表显示的就是**假库存**。
        return StockQuantity.sum(skus.stream().map(ProductSku::getStock).collect(Collectors.toList()));
    }

    /**
     * 获取当前登录用户名
     */
    private String getCurrentUsername() {
        try {
            Authentication auth = SecurityContextHolder.getContext().getAuthentication();
            if (auth != null && auth.getName() != null) {
                return auth.getName();
            }
        } catch (Exception e) {
            // ignore
        }
        return "system";
    }

    /**
     * 转换为响应 DTO
     */
    @SuppressWarnings("unchecked")
    private ProductResponse convertToResponse(Product product, String categoryName) {
        ProductResponse response = new ProductResponse();
        BeanUtils.copyProperties(product, response);
        response.setCategoryName(categoryName);

        // 处理图片列表
        if (product.getImages() instanceof List) {
            response.setImages((List<String>) product.getImages());
        }

        // 详情图列表（BeanUtils 拷贝同名同类型字段后仍显式设置以提高可读性）
        if (product.getDetailImages() != null) {
            response.setDetailImages(product.getDetailImages());
        }

        return response;
    }

    /**
     * 按颜色+规格维度查询低库存 SKU（用于库存告警）
     *
     * @param threshold 库存阈值，SKU 库存低于此值视为低库存
     * @param limit     最大返回条数
     * @return 低库存 SKU 列表
     */
    public List<LowStockByColorResponse> getLowStockByColor(int threshold, int limit) {
        return productMapper.findLowStockByColor(threshold, limit);
    }

    // ======================== Agent BFF 方法 ========================

    /**
     * Agent 专用创建商品。
     * 自动填充默认值、解析分类/加工项 ID（支持名称/UUID/序号）。
     */
    @Transactional(rollbackFor = Exception.class)
    public ProductResponse createProductForAgent(com.migao.admin.dto.agent.AgentProductCreateRequest request,
                                                  Long tenantId) {
        ProductCreateRequest createReq = new ProductCreateRequest();

        // name: 手动校验
        if (!StringUtils.hasText(request.getName())) {
            throw BusinessException.validationError("商品名称不能为空");
        }
        createReq.setName(request.getName());

        // categoryId: 解析（名称/UUID/前缀 → UUID）
        if (StringUtils.hasText(request.getCategoryId())) {
            String resolved = resolveCategoryId(request.getCategoryId(), tenantId);
            if (resolved == null) {
                throw new BusinessException("CATEGORY_NOT_FOUND",
                        "无法找到匹配的分类：" + request.getCategoryId(),
                        422);
            }
            createReq.setCategoryId(resolved);
        }

        // 价格/库存/描述/品牌 直接透传
        createReq.setBasePrice(request.getBasePrice());
        createReq.setStock(request.getStock() != null ? request.getStock() : BigDecimal.ZERO);
        createReq.setDescription(request.getDescription());
        createReq.setBrand(request.getBrand());

        // 货号: 空则自动生成
        if (StringUtils.hasText(request.getSkuCode())) {
            createReq.setSkuCode(request.getSkuCode());
        }
        // 不设 skuCode — createProduct 会在 saveColorsAndSkus 中自动生成

        // unit / pricingType: 智能默认
        createReq.setUnit(StringUtils.hasText(request.getUnit()) ? request.getUnit() : "米");
        createReq.setPricingType(StringUtils.hasText(request.getPricingType())
                ? request.getPricingType() : "per_meter");

        // status: 默认 draft
        createReq.setStatus(StringUtils.hasText(request.getStatus()) ? request.getStatus() : "draft");
        // 图片
        if (request.getImages() != null) createReq.setImages(request.getImages());
        if (request.getDetailImages() != null) createReq.setDetailImages(request.getDetailImages());

        // 退货回补库存开关（issue #2991）：null 保持默认 false（定制退货不可再售）
        createReq.setAllowReturnRestock(Boolean.TRUE.equals(request.getAllowReturnRestock()));

        // 颜色: 字符串 → ProductColorInput
        if (request.getColors() != null && !request.getColors().isEmpty()) {
            List<ProductColorInput> colorInputs = request.getColors().stream()
                    .map(c -> {
                        ProductColorInput ci = new ProductColorInput();
                        ci.setColorName(c);
                        return ci;
                    })
                    .collect(Collectors.toList());
            createReq.setColors(colorInputs);
        }

        // 售卖方式: "散剪"/"整卷" → bulk_cut/full_roll（商品级基础属性，V108）
        if (request.getSellingMethods() != null) {
            createReq.setSellingMethods(request.getSellingMethods().stream()
                    .map(this::translateSellingMethod)
                    .collect(Collectors.toList()));
        }

        // 1 卷 = 多少米（商品货号级基础参数，V108）：null = 未配置 ⇒ 不写（不猜）
        if (request.getRollLengthM() != null) {
            createReq.setRollLengthM(request.getRollLengthM());
        }

        // 门幅 直接透传
        if (request.getDoorWidths() != null) createReq.setDoorWidths(request.getDoorWidths());

        // 规格
        if (request.getSpecifications() != null) createReq.setSpecifications(request.getSpecifications());

        return createProduct(createReq, tenantId);
    }

    /**
     * Agent 专用部分更新商品。
     * null 字段 = 不修改。数组字段 (colors/sellingMethods/doorWidths) 传了才触发 SKU 重建。
     */
    @Transactional(rollbackFor = Exception.class)
    public ProductResponse updateProductForAgent(String id,
                                                   com.migao.admin.dto.agent.AgentProductUpdateRequest request,
                                                   Long tenantId) {
        Product product = productMapper.selectOne(
                new LambdaQueryWrapper<Product>()
                        .eq(Product::getId, id)
                        .eq(Product::getTenantId, tenantId));
        if (product == null) {
            throw BusinessException.notFound("商品");
        }

        ProductUpdateRequest updateReq = new ProductUpdateRequest();
        boolean hasUpdate = false;

        // ── 改前价**服务端回查**（issue #5317，口径照抄 #5314 的批次核对）──
        // `before_price` 由模型从 product_detail 带回，此前服务端**从不核对** ⇒ 护栏证明的是
        // 「模型**声称**改前是多少」，只防「漏填」不防「填错」。核对比对**同一实现**
        // （`AgentWriteValues.sameValue`，批次 create 用的是它）⇒ 不存在"批次严、单条松"的漂移。
        // 缺席不核对（口径与批次 `oldValue` 缺席一致）；一旦声明就必须为真。
        if (request.getBasePrice() != null && request.getBeforePrice() != null
                && !AgentWriteValues.sameValue(
                        AgentWriteValues.FIELD_BASE_PRICE,
                        request.getBeforePrice().toPlainString(),
                        product.getBasePrice() == null
                                ? null : product.getBasePrice().toPlainString())) {
            throw BusinessException.validationError("改前价与商品当前价不符：" + id
                    + " 当前 " + product.getBasePrice() + "，收到 " + request.getBeforePrice()
                    + " —— 请先用 product_detail 取当前价，重新预览后再提交");
        }

        // name: null = 不修改，传了就更新
        if (request.getName() != null) {
            updateReq.setName(request.getName());
            hasUpdate = true;
        } else {
            updateReq.setName(product.getName()); // 保持原名（满足 @NotBlank）
        }

        // categoryId: 解析后更新
        if (request.getCategoryId() != null) {
            String resolved = resolveCategoryId(request.getCategoryId(), tenantId);
            if (resolved == null) {
                throw new BusinessException("CATEGORY_NOT_FOUND",
                        "无法找到匹配的分类：" + request.getCategoryId(), 422);
            }
            updateReq.setCategoryId(resolved);
            hasUpdate = true;
        }

        if (request.getBasePrice() != null) { updateReq.setBasePrice(request.getBasePrice()); hasUpdate = true; }
        if (request.getSkuCode() != null) { updateReq.setSkuCode(request.getSkuCode()); hasUpdate = true; }
        if (request.getDescription() != null) { updateReq.setDescription(request.getDescription()); hasUpdate = true; }
        if (request.getBrand() != null) { updateReq.setBrand(request.getBrand()); hasUpdate = true; }
        if (request.getUnit() != null) { updateReq.setUnit(request.getUnit()); hasUpdate = true; }
        if (request.getPricingType() != null) { updateReq.setPricingType(request.getPricingType()); hasUpdate = true; }
        if (request.getStock() != null) { updateReq.setStock(request.getStock()); hasUpdate = true; }
        if (request.getImages() != null) { updateReq.setImages(request.getImages()); hasUpdate = true; }
        if (request.getDetailImages() != null) { updateReq.setDetailImages(request.getDetailImages()); hasUpdate = true; }
        if (request.getSpecifications() != null) { updateReq.setSpecifications(request.getSpecifications()); hasUpdate = true; }
        if (request.getStockDeductionMode() != null) { /* 不支持通过 update 修改，忽略 */ }
        if (request.getAllowReturnRestock() != null) { updateReq.setAllowReturnRestock(request.getAllowReturnRestock()); hasUpdate = true; }

        // 颜色/售卖方式/门幅: 传了才处理（会触发 SKU 重建）
        if (request.getColors() != null) {
            updateReq.setColors(request.getColors().stream().map(c -> {
                ProductColorInput ci = new ProductColorInput();
                ci.setColorName(c);
                return ci;
            }).collect(Collectors.toList()));
            hasUpdate = true;
        }
        if (request.getSellingMethods() != null) {
            updateReq.setSellingMethods(request.getSellingMethods().stream()
                    .map(this::translateSellingMethod).collect(Collectors.toList()));
            hasUpdate = true;
        }
        // 1 卷 = 多少米（V108）：null = 不修改（部分更新口径，与其它字段一致）
        if (request.getRollLengthM() != null) {
            updateReq.setRollLengthM(request.getRollLengthM());
            hasUpdate = true;
        }
        if (request.getDoorWidths() != null) { updateReq.setDoorWidths(request.getDoorWidths()); hasUpdate = true; }

        // status 也是有效更新：只传 status 时不能落进下面的 !hasUpdate 分支（那正是本 issue 的假成功路径）。
        // 这里先做状态机校验（不写库）：非法流转必须在任何写入之前失败，不留部分写入。
        if (request.getStatus() != null) {
            validateStatusTransition(product.getStatus(), request.getStatus());
            hasUpdate = true;
        }

        if (!hasUpdate) {
            return getProductById(id, tenantId);
        }

        ProductResponse response = updateProduct(id, updateReq, tenantId);

        // status（上下架）：委托状态机唯一入口 applyStatusTransition（issue #3560）。
        // 回归背景：product_update 一直在请求体里下发 status，但本 DTO 曾无该字段 + 本方法从不读取它
        // → Jackson 静默忽略 → hasUpdate 保持 false → 上一行 !hasUpdate 分支返回商品详情
        // （HTTP 200 + success）→ 米宝回「已下架」而 products.status 未变。与 stock 同型的"假成功"。
        //
        // 为什么放在 updateProduct 之后：updateProduct 内部刻意 `product.setStatus(originalStatus)`
        // （注释「状态变更必须通过 updateProductStatus 接口（含状态机校验）」）——它靠 BeanUtils
        // 拷贝请求到实体，而 ProductUpdateRequest 也有 status 字段，会绕过状态机。故状态只能由本方法
        // 在商品更新完成后单独落库；非法流转抛错时整方法 @Transactional 回滚，不留部分写入。
        if (request.getStatus() != null) {
            Product latest = productMapper.selectById(id);
            if (latest == null) {
                throw BusinessException.notFound("商品");
            }
            applyStatusTransition(latest, request.getStatus());
            productMapper.updateById(latest);
        }

        return response;
    }

    /**
     * Agent 专用库存调整（生产回归修复：杜绝"假成功"）。
     *
     * 背景：updateProduct 对 stock 的处理依赖 SKU 重建条件（colors/skus 等字段非空），
     * 单独传 stock 时被静默忽略但接口仍返回 success —— 米宝曾报"库存已调整"而库表未变。
     * 本方法直接对现有 SKU 分配增减量并写库，语义与商品列表的总库存（SKU 汇总）一致。
     *
     * 分配规则（确定性）：
     * - 增加：在 SKU 间均匀分配，余数给第一个 SKU；
     * - 减少：从库存最大的 SKU 优先扣减（单 SKU 扣到 0 为止），总量不足时抛 INSUFFICIENT_STOCK。
     *
     * @param productId  商品 ID（UUID；名称需调用方先 resolveProductId）
     * @param adjustment 调整量（正=增加，负=减少，0 报参数错误）
     * @param reason     调整原因（仅日志记录）
     * @param tenantId   租户 ID
     * @return 更新后的商品详情（stock 为 SKU 汇总，供调用方读回校验）
     */
    @Transactional(rollbackFor = Exception.class)
    public ProductResponse adjustStockForAgent(String productId, BigDecimal adjustment, String reason, Long tenantId) {
        Product product = productMapper.selectOne(
                new LambdaQueryWrapper<Product>()
                        .eq(Product::getId, productId)
                        .eq(Product::getTenantId, tenantId));
        if (product == null) {
            throw BusinessException.notFound("商品");
        }
        if (adjustment == null || adjustment.signum() == 0) {
            throw BusinessException.validationError("调整量 adjustment 不能为空或 0");
        }
        // issue #5063（V115）：库存调整量是**库存类输入** ⇒ 最多 1 位小数，超过即显式拒绝
        // （fail-closed；静默取整/截断会让「盘点 +2.755」这种输入变成账上另一个数，且无人发现）
        adjustment = StockQuantity.requireOneDecimal(adjustment, "调整量 adjustment");

        List<ProductSku> skus = productSkuMapper.selectList(
                new LambdaQueryWrapper<ProductSku>().eq(ProductSku::getProductId, productId));
        if (skus == null || skus.isEmpty()) {
            throw BusinessException.validationError("商品没有 SKU，无法调整库存，请先在商品详情维护 SKU");
        }

        // 库存台账（issue #4055）：分配算法会原地改写 sku.getStock()，变更前值必须先记下来
        Map<Long, BigDecimal> stockBefore = new LinkedHashMap<>();
        for (ProductSku sku : skus) {
            stockBefore.put(sku.getId(), StockQuantity.orZero(sku.getStock()));
        }

        BigDecimal total = StockQuantity.sum(stockBefore.values());
        BigDecimal newTotal = total.add(adjustment);
        if (newTotal.compareTo(BigDecimal.ZERO) < 0) {
            throw new BusinessException("INSUFFICIENT_STOCK",
                    "库存不足：当前总库存 " + total.toPlainString()
                            + "，无法减少 " + adjustment.abs().toPlainString(), 422);
        }

        // 改前是 `int base = adjustment / skus.size()` + `int remainder = adjustment % skus.size()`：
        // 整数除法本身不丢量，但**它要求 adjustment 先变成 int** —— 而 adjustment 现在是 1 位小数
        // （如 2.7 米分摊到 3 个 SKU）。⇒ 换写成「0.1 米刻度」的**整数**运算：
        // 除不尽的余数**显式**给第一个 SKU，分配总量与 adjustment **恒等**（不静默丢、不静默补）。
        // 为什么不用 BigDecimal.divide：除不尽时它要么抛（ArithmeticException 打断盘点），
        // 要么被迫指定舍入（那就真的丢量了）—— 两者都不可接受。
        if (adjustment.signum() > 0) {
            // 均匀分配，余数给第一个 SKU —— **两段式**（顺序不可交换，逐条有理由）：
            //   ① **整米**部分先按旧规则分摊（`base = 整米 / n`、余数给第一个 SKU）
            //      ⇒ 整数调整量的分配结果与改前**逐值相同**（用户裁定「不能损失客户」：
            //         +3 在 [30,20] 上仍是 [32,21]，而不是「各 +1.5」）；
            //   ② **0.1 米余数**（< 1 米，至多 9 个刻度）整块给第一个 SKU
            //      ⇒ 总量与 adjustment **恒等**，不静默丢、不静默补。
            // 为什么不能直接用 `tenths / n` 一步分摊：那会把 +3 摊成各 +1.5 —— 数值上更"均匀"，
            // 但**改了既有整数场景的落库值**，正是本单红线。
            long addTenths = StockQuantity.tenths(adjustment);
            long wholeMeters = addTenths / 10;
            long fracTenths = addTenths % 10;
            long base = wholeMeters / skus.size();
            long remainder = wholeMeters % skus.size();
            for (int i = 0; i < skus.size(); i++) {
                ProductSku sku = skus.get(i);
                long add = (base + (i == 0 ? remainder : 0)) * 10 + (i == 0 ? fracTenths : 0);
                sku.setStock(StockQuantity.orZero(sku.getStock()).add(StockQuantity.fromTenths(add)));
            }
        } else {
            // 从库存最大的 SKU 优先扣减
            long toReduce = StockQuantity.tenths(adjustment.abs());
            List<ProductSku> sorted = new ArrayList<>(skus);
            sorted.sort((x, y) -> StockQuantity.orZero(y.getStock())
                    .compareTo(StockQuantity.orZero(x.getStock())));
            for (ProductSku sku : sorted) {
                if (toReduce <= 0) {
                    break;
                }
                long current = StockQuantity.tenths(StockQuantity.orZero(sku.getStock()));
                long take = Math.min(current, toReduce);
                sku.setStock(StockQuantity.fromTenths(current - take));
                toReduce -= take;
            }
            if (toReduce > 0) {
                throw new BusinessException("INSUFFICIENT_STOCK",
                        "库存不足：当前总库存 " + total.toPlainString()
                                + "，无法减少 " + adjustment.abs().toPlainString(), 422);
            }
        }

        for (ProductSku sku : skus) {
            productSkuMapper.updateById(sku);
            BigDecimal before = stockBefore.getOrDefault(sku.getId(), BigDecimal.ZERO);
            BigDecimal after = StockQuantity.orZero(sku.getStock());
            // 台账「有没有变化」必须 compareTo（`2.70` 与 `2.7` equals 为 false）—— 否则落假 delta=0 行
            if (before.compareTo(after) != 0) {
                // 库存台账（issue #4055）：每次 SKU 库存变更写一行流水（before/after 首尾相接可对账）。
                // 未拿到分配量的 SKU（调整量小于 SKU 数）不落行 —— 台账里不出现 0 变更噪声。
                stockLedgerService.record(tenantId, productId, sku.getId(), sku.getSkuCode(),
                        before, after, StockLedger.REASON_MANUAL, null, reason);
            }
        }
        // 商品级 stock 仅作冗余展示，同步为 SKU 汇总值
        product.setStock(newTotal);
        productMapper.updateById(product);

        log.info("[Agent] 库存调整: product={}, adjustment={}, reason={}, total={}->{}, tenant={}",
                productId, adjustment, reason, total, newTotal, tenantId);
        return getProductById(productId, tenantId);
    }

    // ======================== ID 解析辅助方法 ========================

    /**
     * 解析商品 ID：支持 UUID / 商品名称 / UUID 前缀 / 序号（1-based）。
     * 匹配优先级：UUID 完整匹配 → UUID 前缀 → 名称精确匹配 → 序号 → 名称模糊匹配。
     *
     * @return 真实 UUID，未找到返回 null
     */
    /**
     * 更新单个 SKU 的价格。按颜色/门幅匹配。
     *
     * <p>归一化（issue #3539）：agent / 前端按**中文业务术语**传参（「2.8米」），
     * 而 product_skus 落库的是数值（2.8）——直接字面 eq 必然 0 行命中，
     * 对外表现为「SKU不存在」。
     *
     * <p>故：门幅先按原值精确匹配，未命中再按「去掉 米/m 后缀」双侧归一化兜底
     * —— 库内两种写法都真实存在（种子 SKU 是 '2.8'，agent 建品落库的是 '2.8米'），
     * 只做输入侧去后缀会反向打不到后者。
     *
     * <p><b>V108（用户裁定 2026-09-21）</b>：售卖方式那一维已从匹配里删除 ——
     * SKU 组合只有 颜色 × 门幅（售卖方式是商品级 {@code products.selling_methods}）。
     * 调用方若仍传售卖方式，它**不参与定位**（同色同门幅只有一行 SKU）。
     */
    public void updateSkuPrice(String productId, String color,
                                String doorWidth, java.math.BigDecimal price,
                                java.math.BigDecimal beforePrice, Long tenantId) {
        java.util.List<ProductSku> candidates =
                selectSkuCandidatesForPriceUpdate(productId, color, doorWidth, tenantId);
        if (candidates.isEmpty()) {
            throw BusinessException.notFound("SKU",
                    "未找到匹配的 SKU。请用 product_detail 查看可用 SKU 后重试");
        }
        ProductSku sku = candidates.get(0);
        if (candidates.size() > 1) {
            log.warn("SKU调价匹配到多个({})候选，取第一个: product={}, color={}",
                    candidates.size(), productId, color);
        }
        // ── 改前价**服务端回查**（issue #5317）：与匹配到的这一行 SKU 的当前价按值核对，
        // 判据同一实现（`AgentWriteValues.sameValue`）—— 编一个改前价必被拒。缺席不核对。
        if (beforePrice != null && !AgentWriteValues.sameValue(
                AgentWriteValues.FIELD_BASE_PRICE, beforePrice.toPlainString(),
                sku.getPrice() == null ? null : sku.getPrice().toPlainString())) {
            throw BusinessException.validationError("改前价与 SKU 当前价不符：" + productId
                    + "（" + color + " / " + doorWidth + "）当前 " + sku.getPrice()
                    + "，收到 " + beforePrice + " —— 请先用 product_detail 取当前价后重试");
        }
        sku.setPrice(price);
        productSkuMapper.updateById(sku);
        log.info("SKU价格已更新: product={}, color={}, width={}, price={}",
                productId, color, doorWidth, price);
    }

    /**
     * SKU 调价候选匹配：门幅精确匹配优先；未命中时放宽门幅条件、在 Java 侧做「去 米/m 后缀」
     * 双侧归一化比较（不改写库内值，也不新增 SKU 行）。
     * 返回最多 2 条，供调用方「取第一个 + 多命中告警」（常见于不填门幅时同名颜色有多个门幅）。
     */
    private java.util.List<ProductSku> selectSkuCandidatesForPriceUpdate(String productId, String color,
                                                                        String doorWidth,
                                                                        Long tenantId) {
        java.util.List<ProductSku> exact = productSkuMapper.selectList(
                skuPriceUpdateScope(productId, color, tenantId)
                        .eq(StringUtils.hasText(doorWidth), ProductSku::getDoorWidth, doorWidth)
                        .last("LIMIT 2"));
        if (!exact.isEmpty() || !StringUtils.hasText(doorWidth)) {
            return exact;
        }
        String targetWidth = normalizeDoorWidth(doorWidth);
        return productSkuMapper.selectList(
                        skuPriceUpdateScope(productId, color, tenantId))
                .stream()
                .filter(s -> targetWidth.equals(normalizeDoorWidth(s.getDoorWidth())))
                .limit(2)
                .collect(java.util.stream.Collectors.toList());
    }

    /** 调价定位范围：商品 + 租户（拦截器之外显式带租户）+ 可选的颜色 */
    private LambdaQueryWrapper<ProductSku> skuPriceUpdateScope(String productId, String color,
                                                               Long tenantId) {
        return new LambdaQueryWrapper<ProductSku>()
                .eq(ProductSku::getProductId, productId)
                .eq(ProductSku::getTenantId, tenantId)
                .eq(StringUtils.hasText(color), ProductSku::getColorName, color);
    }

    /**
     * 门幅归一化：「2.8米」「2.8m」「2.8 M」→「2.8」。
     * 仅用于匹配比较，<b>不回写库</b>（库内保持原写法，避免 SKU 编码/前端展示口径漂移）。
     * 与 {@link #toWidthShort(String)} 同源假设：门幅的语义是数字，「2.8米」与「2.8」等价。
     *
     * <p><b>单一入口</b>（issue #3616）：调价路径 {@link #selectSkuCandidatesForPriceUpdate} 与
     * 建品/更新商品路径 {@link #matchExistingSku} 都必须走本方法，禁止裸比字面值
     * （有静态不变式测试锁定，见 ProductServiceTest#skuMatch_NoBareEqualityComparison_OnDoorWidth）。
     */
    private static String normalizeDoorWidth(String rawDoorWidth) {
        if (rawDoorWidth == null) {
            return null;
        }
        return rawDoorWidth.trim().replaceAll("(?i)\\s*[米m]$", "").trim();
    }

    /**
     * Agent/前端行内编辑专用：按 SKU id 精确改价。
     * 校验 skuId 属于该商品且价格 ≥ 0，原地更新价格行（不删除/重建，保证订单回滚可寻址），
     * 返回更新后的 SKU。
     */
    @Transactional(rollbackFor = Exception.class)
    public ProductSkuResponse updateSkuPriceById(String productId, Long skuId,
                                                  BigDecimal price, Long tenantId) {
        Product product = productMapper.selectOne(
                new LambdaQueryWrapper<Product>()
                        .eq(Product::getId, productId)
                        .eq(Product::getTenantId, tenantId));
        if (product == null) {
            throw BusinessException.notFound("商品");
        }
        if (price == null) {
            throw BusinessException.validationError("缺少 price 字段");
        }
        if (price.signum() < 0) {
            throw BusinessException.validationError("价格不能为负数");
        }
        ProductSku sku = productSkuMapper.selectOne(
                new LambdaQueryWrapper<ProductSku>()
                        .eq(ProductSku::getId, skuId)
                        .eq(ProductSku::getProductId, productId)
                        .eq(ProductSku::getTenantId, tenantId));
        if (sku == null) {
            throw BusinessException.notFound("SKU",
                    "未找到属于该商品的 SKU（id=" + skuId + "）。请用 product_detail 查看可用 SKU 后重试");
        }
        sku.setPrice(price);
        productSkuMapper.updateById(sku);
        log.info("SKU价格已更新(单SKU): product={}, skuId={}, price={}, tenant={}",
                productId, skuId, price, tenantId);
        return toSkuResponse(sku);
    }

    /**
     * ProductSku 实体 → ProductSkuResponse（与 getProductById 中字段口径一致）
     */
    private ProductSkuResponse toSkuResponse(ProductSku sku) {
        ProductSkuResponse resp = new ProductSkuResponse();
        resp.setId(sku.getId());
        resp.setProductId(sku.getProductId());
        resp.setColorId(sku.getColorId());
        resp.setColorName(sku.getColorName());
        resp.setDoorWidth(sku.getDoorWidth());
        resp.setPrice(sku.getPrice());
        resp.setStock(sku.getStock());
        resp.setSkuCode(sku.getSkuCode());
        resp.setCreatedAt(sku.getCreatedAt());
        resp.setUpdatedAt(sku.getUpdatedAt());
        return resp;
    }

    public String resolveProductId(String raw, Long tenantId) {
        if (!StringUtils.hasText(raw)) return null;
        String s = raw.trim();

        java.util.List<Product> all = productMapper.selectList(
                new LambdaQueryWrapper<Product>()
                        .eq(Product::getTenantId, tenantId)
                        .orderByAsc(Product::getCreatedAt));

        // 1. 精确 UUID
        for (Product p : all) {
            if (s.equals(p.getId())) return p.getId();
        }

        // 2. UUID 前缀（LLM 可能截断 UUID）
        if (s.length() >= 8) {
            for (Product p : all) {
                if (p.getId() != null && p.getId().startsWith(s.substring(0, Math.min(16, s.length())))) {
                    return p.getId();
                }
            }
        }

        // 3. 精确名称
        for (Product p : all) {
            if (s.equals(p.getName())) return p.getId();
        }

        // 4. 序号（1-based，按创建时间排序）
        if (s.matches("\\d+")) {
            int idx = Integer.parseInt(s) - 1;
            if (idx >= 0 && idx < all.size())
                return all.get(idx).getId();
        }

        // 5. 名称模糊匹配（包含关键字）
        for (Product p : all) {
            if (p.getName() != null && p.getName().contains(s)) return p.getId();
        }

        return null;
    }

    /**
     * 解析分类 ID：支持 UUID / 名称 / UUID 前缀。
     *
     * @return 真实 UUID，未找到返回 null
     */
    String resolveCategoryId(String raw, Long tenantId) {
        if (!StringUtils.hasText(raw)) return null;

        java.util.List<Category> cats = categoryMapper.selectList(
                new LambdaQueryWrapper<Category>().eq(Category::getTenantId, tenantId));

        // 1. 精确 UUID 匹配
        for (Category c : cats) {
            if (raw.equals(c.getId())) return c.getId();
        }

        // 2. 名称匹配
        for (Category c : cats) {
            if (raw.equals(c.getName())) return c.getId();
        }

        // 3. UUID 前缀匹配（LLM 可能截断 UUID）
        if (raw.length() >= 8) {
            for (Category c : cats) {
                if (c.getId() != null
                        && c.getId().startsWith(raw.substring(0, Math.min(16, raw.length())))) {
                    return c.getId();
                }
            }
        }

        return null;
    }

    /**
     * 售卖方式中文 → 英文（幂等：英文原样透传）。
     *
     * <p><b>单一入口</b>（issue #3616）：建品/更新商品的入参翻译、调价路径的查询条件
     * （{@link #updateSkuPrice}）、以及组合匹配 {@link #matchExistingSku} 的双侧比较，
     * 全部复用本方法，禁止另建第二套映射。
     */
    private String translateSellingMethod(String raw) {
        if (raw == null) return null;
        return switch (raw.trim()) {
            case "散剪" -> "bulk_cut";
            case "整卷" -> "full_roll";
            case "按片" -> "per_piece";
            case "定高" -> "fixed_height";
            case "买通" -> "buy_through";
            default -> raw; // 已经是英文则直接透传
        };
    }

    /**
     * 统计待补库存 SKU 数（排除已删除 + 已下架商品下的 SKU）
     * #1396: 口径统一 — 三个入口（Dashboard 卡片、low-stock-by-color API、商品列表 stockBelow）
     *         使用相同的过滤条件：p.deleted=0 AND p.status='on_sale'
     *
     * @param tenantId  租户 ID
     * @param threshold 库存阈值（SKU stock ≤ threshold 视为低库存）
     * @return 低库存 SKU 总数
     */
    public long getLowStockSkuCount(Long tenantId, int threshold) {
        return productMapper.countLowStockSkus(tenantId, threshold);
    }
}
