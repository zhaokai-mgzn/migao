// case_ids: PR-128
package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.ProductCreateRequest;
import com.migao.admin.dto.ProductResponse;
import com.migao.admin.entity.Category;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductColor;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.CategoryMapper;
import com.migao.admin.mapper.ProductAttributeMapper;
import com.migao.admin.mapper.ProductColorMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * 商品创建的**服务端幂等**接线判据（issue #6209）。
 *
 * <h2>病灶（现场证据）</h2>
 * {@code acceptance/2026-10-03/batch-writeface-sweep/out/E1-duplicate-submit.json}：同一
 * {@code X-Client-Request-Id} 串行提交 1 次 ⇒ 商品数 1；随后**并发 5 次**同一键 ⇒
 * 5 个请求**全部 200 且各返回一个新商品 id**，落地商品数 6，而 {@code client_request_keys}
 * **0 行** —— 该写面**从未接** {@link ClientRequestIdService}（订单 / 售后 / 发货 / 报工 /
 * 入库都已接同一份实现）。本单把漏接的写面接上，**不新造幂等框架**。
 *
 * <h2>判据（逐条都能单独变红）</h2>
 * <ol>
 *   <li><b>同键重复 ⇒ 恰好一条业务对象</b>：{@code claim} 判非首次 ⇒ 走
 *       {@link ClientRequestIdService#replay} 并把首次结果原样返回，**不得**再 insert 商品；</li>
 *   <li><b>幂等留痕</b>：首次执行成功后必须调 {@code complete}（写结果快照）；</li>
 *   <li><b>负向对照（防「一律只建一条」的假修）</b>：**不同**幂等键两次调用 ⇒ 两次都真执行
 *       （两条独立商品），且第二次不得被回放吞掉；</li>
 *   <li><b>无键 ⇒ 原路径逐字不变</b>（老客户端不得因为服务端升级而报错 / 不得产生 DB 往返）；</li>
 *   <li><b>失败释放占位</b>：业务失败 ⇒ {@code discard}，否则一次失败把该键永久占死。</li>
 * </ol>
 *
 * <p>真实并发（N=4 同键 ⇒ 恰 1 条业务对象 + {@code client_request_keys} 恰 1 行）由真库判据
 * {@code ProductCreateIdempotencyRealDbTest} 承担；端点是否真的把请求头接到服务上由
 * {@code ProductCreateIdempotencyEndpointTest} 承担 —— 本文件只钉**服务方法的接线与三态分支**。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("商品创建幂等接线（issue #6209）：同键不重复建品 + 不同键各建一份")
class ProductCreateIdempotencyTest {

    private static final Long TENANT_ID = 1L;
    private static final String KEY = "e1-product-create-key";
    private static final String PRODUCT_ID = "65b2e98fb11b57e89b14bc11346d2ac0";
    private static final String CATEGORY_ID = "cat-001";

    @Mock
    private ProductMapper productMapper;
    @Mock
    private CategoryMapper categoryMapper;
    @Mock
    private ProductColorMapper productColorMapper;
    @Mock
    private ProductSkuMapper productSkuMapper;
    @Mock
    private ProductAttributeMapper productAttributeMapper;
    @Mock
    private StockLedgerService stockLedgerService;
    @Mock
    private ClientRequestIdService clientRequestIdService;

    @InjectMocks
    private ProductService productService;

    @BeforeEach
    void setUp() {
        MybatisConfiguration configuration = new MybatisConfiguration();
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), Product.class);
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), ProductColor.class);
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), ProductSku.class);
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), Category.class);

        Category category = Category.builder().id(CATEGORY_ID).tenantId(TENANT_ID).name("窗帘").status("active").build();
        when(categoryMapper.selectById(any())).thenReturn(category);
        when(categoryMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(category);
        when(categoryMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(1L);
        // 建品给主键（真实 ID 由 MyBatis-Plus 分配；单测里显式回填，产物侧才判得出「同一条」）
        doAnswer(inv -> {
            Product p = inv.getArgument(0);
            p.setId(PRODUCT_ID);
            return 1;
        }).when(productMapper).insert(any(Product.class));
        // doCreateProduct 末尾按 id 回读装配响应（与 ProductServiceTest 同款装配）
        when(productMapper.selectById(PRODUCT_ID)).thenReturn(Product.builder()
                .id(PRODUCT_ID).name("线②验收重复提交").categoryId(CATEGORY_ID)
                .basePrice(new BigDecimal("9.00")).status("draft").build());
    }

    private ProductCreateRequest request() {
        ProductCreateRequest request = new ProductCreateRequest();
        request.setName("线②验收重复提交");
        request.setCategoryId(CATEGORY_ID);
        request.setBasePrice(new BigDecimal("9.00"));
        request.setStock(new BigDecimal("1.0"));
        request.setUnit("米");
        request.setPricingType("per_meter");
        request.setStatus("draft");
        return request;
    }

    @Test
    @DisplayName("同键重复提交 ⇒ 不重复建品，原样回放首次结果（恰好一条业务对象）")
    void sameKeyDoesNotCreateASecondProduct() {
        ProductResponse first = new ProductResponse();
        first.setId(PRODUCT_ID);
        first.setName("线②验收重复提交");
        when(clientRequestIdService.claim(TENANT_ID, KEY, ProductService.ENDPOINT_CREATE_PRODUCT)).thenReturn(false);
        when(clientRequestIdService.replay(TENANT_ID, KEY, ProductResponse.class)).thenReturn(Optional.of(first));

        ProductResponse result = productService.createProduct(request(), TENANT_ID, KEY);

        assertThat(result.getId()).as("同键重复必须回放**首次那一条**（不是新建一条）").isEqualTo(PRODUCT_ID);
        verify(productMapper, never()).insert(any(Product.class));
        verify(clientRequestIdService, never()).complete(anyLong(), anyString(), any());
    }

    @Test
    @DisplayName("幂等留痕：首次执行成功后写结果快照（complete）")
    void firstExecutionCompletesTheKey() {
        when(clientRequestIdService.claim(TENANT_ID, KEY, ProductService.ENDPOINT_CREATE_PRODUCT)).thenReturn(true);

        ProductResponse result = productService.createProduct(request(), TENANT_ID, KEY);

        assertThat(result.getId()).isEqualTo(PRODUCT_ID);
        verify(productMapper, times(1)).insert(any(Product.class));
        verify(clientRequestIdService, times(1)).complete(eq(TENANT_ID), eq(KEY), any());
    }

    @Test
    @DisplayName("负向对照：**不同**幂等键各建一份（防「一律只建一条」的假修）")
    void differentKeysEachCreateTheirOwnProduct() {
        when(clientRequestIdService.claim(TENANT_ID, "key-a", ProductService.ENDPOINT_CREATE_PRODUCT)).thenReturn(true);
        when(clientRequestIdService.claim(TENANT_ID, "key-b", ProductService.ENDPOINT_CREATE_PRODUCT)).thenReturn(true);

        productService.createProduct(request(), TENANT_ID, "key-a");
        productService.createProduct(request(), TENANT_ID, "key-b");

        verify(productMapper, times(2)).insert(any(Product.class));
        verify(clientRequestIdService, times(2)).complete(eq(TENANT_ID), anyString(), any());
    }

    @Test
    @DisplayName("无键 ⇒ 原路径逐字不变（零幂等交互，老客户端不受影响）")
    void withoutKeyTheOriginalPathIsUntouched() {
        ProductResponse result = productService.createProduct(request(), TENANT_ID, null);

        assertThat(result.getId()).isEqualTo(PRODUCT_ID);
        verifyNoInteractions(clientRequestIdService);
    }

    @Test
    @DisplayName("失败释放占位：业务失败 ⇒ discard（否则一次失败把该键永久占死）")
    void failureDiscardsThePlaceholder() {
        when(clientRequestIdService.claim(TENANT_ID, KEY, ProductService.ENDPOINT_CREATE_PRODUCT)).thenReturn(true);
        // 建品失败：状态非法 ⇒ 入口准入抛 422（发生在任何写之前）
        ProductCreateRequest bad = request();
        bad.setStatus("bogus_status");

        assertThatThrownBy(() -> productService.createProduct(bad, TENANT_ID, KEY))
                .isInstanceOf(BusinessException.class);

        verify(clientRequestIdService, times(1)).discard(TENANT_ID, KEY);
        verify(clientRequestIdService, never()).complete(anyLong(), anyString(), any());
    }
}
