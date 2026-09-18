package com.migao.admin.service;

// case_ids=[PR-005, PR-007, PR-019]
// 加工项解耦（issue #4371）：商品不再持有加工项 ⇒ 本文件原有的
// 「Agent 创建商品 — 加工项价格合并」（#3056 一族）、「加工项增删」两个嵌套类，
// 以及「ID 解析」里的加工项 ID 解析用例，随被删代码一并删除
// （ProductService 已无 productProcessingItemMapper / processingItemMapper / 加工项解析入口）。
// 解耦本身的回归防线见 ProductProcessingDecouplingTest。

import com.migao.admin.dto.*;
import com.migao.admin.dto.agent.*;
import com.migao.admin.entity.*;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.*;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class AgentProductServiceTest {

    @InjectMocks private ProductService productService;
    @Mock private ProductMapper productMapper;
    @Mock private CategoryMapper categoryMapper;
    @Mock private ProductColorMapper productColorMapper;
    @Mock private ProductSkuMapper productSkuMapper;
    @Mock private ProductAttributeMapper productAttributeMapper;
    /** 库存台账（issue #4055）：手工调整的落账断言见 StockLedgerTest */
    @Mock private StockLedgerService stockLedgerService;

    private Product testProduct;
    private Category testCategory;

    @BeforeEach
    void setUp() {
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant asst = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(asst, Product.class);
        TableInfoHelper.initTableInfo(asst, Category.class);
        TableInfoHelper.initTableInfo(asst, ProductColor.class);
        TableInfoHelper.initTableInfo(asst, ProductSku.class);

        testCategory = Category.builder().id("cat-001").name("窗帘布艺").tenantId(1L).build();
        testProduct = Product.builder()
                .id("prod-001").name("遮光窗帘").tenantId(1L)
                .categoryId("cat-001").basePrice(new BigDecimal("99.00"))
                .status("on_sale").stock(100).unit("米").pricingType("per_meter").build();
    }

    @Nested @DisplayName("Agent 创建商品")
    class Create {
        @Test @DisplayName("基本创建 — name + price")
        void basic() {
            AgentProductCreateRequest req = new AgentProductCreateRequest();
            req.setName("新窗帘"); req.setBasePrice(new BigDecimal("50"));
            when(productMapper.insert(any(Product.class))).thenAnswer(inv -> {
                Product p = inv.getArgument(0); p.setId("prod-new"); return 1;
            });
            Product saved = Product.builder().id("prod-new").name("新窗帘")
                    .basePrice(new BigDecimal("50")).status("draft").build();
            when(productMapper.selectById("prod-new")).thenReturn(saved);

            ProductResponse result = productService.createProductForAgent(req, 1L);
            assertThat(result.getName()).isEqualTo("新窗帘");
        }

        @Test @DisplayName("缺少 name → BusinessException")
        void missingName() {
            AgentProductCreateRequest req = new AgentProductCreateRequest();
            req.setBasePrice(new BigDecimal("50"));
            assertThatThrownBy(() -> productService.createProductForAgent(req, 1L))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("商品名称不能为空");
        }

        @Test @DisplayName("分类按名称解析")
        void categoryByName() {
            AgentProductCreateRequest req = new AgentProductCreateRequest();
            req.setName("窗帘"); req.setCategoryId("窗帘布艺");
            when(categoryMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(testCategory));
            when(categoryMapper.selectById("cat-001")).thenReturn(testCategory);
            when(productMapper.insert(any(Product.class))).thenAnswer(inv -> {
                Product p = inv.getArgument(0); p.setId("p"); return 1;
            });
            when(productMapper.selectById("p")).thenReturn(
                    Product.builder().id("p").name("窗帘").categoryId("cat-001").status("draft").build());

            ProductResponse r = productService.createProductForAgent(req, 1L);
            assertThat(r).isNotNull();
        }
    }

    @Nested @DisplayName("Agent 部分更新")
    class Update {
        @Test @DisplayName("只更新价格 — updateById 被调用")
        void partial() {
            AgentProductUpdateRequest req = new AgentProductUpdateRequest();
            req.setBasePrice(new BigDecimal("150"));
            when(productMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testProduct);
            when(productMapper.updateById(any(Product.class))).thenReturn(1);
            // getProductById 内部会查询 colors/skus 等，简化验证
            when(productMapper.selectById("prod-001")).thenReturn(testProduct);
            when(productColorMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
            when(productAttributeMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());

            productService.updateProductForAgent("prod-001", req, 1L);
            verify(productMapper).updateById(any(Product.class));
        }

        @Test @DisplayName("商品不存在 → BusinessException")
        void notFound() {
            AgentProductUpdateRequest req = new AgentProductUpdateRequest();
            req.setBasePrice(new BigDecimal("150"));
            when(productMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);
            assertThatThrownBy(() -> productService.updateProductForAgent("prod-999", req, 1L))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("商品不存在");
        }

        // ── status（上下架）────────────────────────────────────────────────
        // 生产回归（issue #3560）：product_update 下发 status 而 AgentProductUpdateRequest 无该字段
        // + Jackson 静默忽略未知字段 + hasUpdate 永不被 status 置位 → 走 hasUpdate=false 分支返回
        // 商品详情（HTTP 200 + success）→ 米宝回「已下架」而 products.status 未变。
        // 修复：DTO 收 status → 委托既有 updateProductStatus（状态机唯一入口），不再假成功。

        @Test @DisplayName("status 变更 — 状态真的写到实体（非静默成功）")
        void statusApplied() {
            AgentProductUpdateRequest req = new AgentProductUpdateRequest();
            req.setStatus("off_sale");

            Product product = Product.builder()
                    .id("prod-001").name("遮光窗帘").tenantId(1L)
                    .categoryId("cat-001").basePrice(new BigDecimal("99.00"))
                    .status("on_sale").build();
            when(productMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(product);
            when(productMapper.selectById("prod-001")).thenReturn(product);
            when(productMapper.updateById(any(Product.class))).thenReturn(1);

            productService.updateProductForAgent("prod-001", req, 1L);

            ArgumentCaptor<Product> captor = ArgumentCaptor.forClass(Product.class);
            verify(productMapper, atLeastOnce()).updateById(captor.capture());
            assertThat(captor.getAllValues())
                    .as("status 必须真的落到实体（堵死 hasUpdate=false 静默成功）")
                    .anySatisfy(p -> assertThat(p.getStatus()).isEqualTo("off_sale"));
        }

        @Test @DisplayName("防回归 — 只传无法处理的字段不得返回成功（hasUpdate=false 模式）")
        void unsupportedFieldOnlyMustNotSucceed() {
            // 商品当前 draft，唯一可流转目标是 under_review/on_sale；off_sale 非法。
            // 修复前：status 被 DTO 丢弃 → hasUpdate=false → 返回商品详情（HTTP 200 success）= 假成功。
            // 修复后：状态机拒绝非法流转 → 抛业务错误。不允许「返回成功但零变更」的第三条路径。
            AgentProductUpdateRequest req = new AgentProductUpdateRequest();
            req.setStatus("off_sale");

            Product product = Product.builder()
                    .id("prod-001").name("遮光窗帘").tenantId(1L)
                    .categoryId("cat-001").basePrice(new BigDecimal("99.00"))
                    .status("draft").build();
            when(productMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(product);
            when(productMapper.selectById("prod-001")).thenReturn(product);

            assertThatThrownBy(() -> productService.updateProductForAgent("prod-001", req, 1L))
                    .as("只传无法处理的字段必须显式失败，禁止 hasUpdate=false 静默返回成功")
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("状态流转无效");
            verify(productMapper, never()).updateById(any(Product.class));
        }
    }

    @Nested @DisplayName("ID 解析")
    class Resolve {
        @Test @DisplayName("分类 UUID 匹配")
        void catUuid() {
            when(categoryMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(testCategory));
            assertThat(productService.resolveCategoryId("cat-001", 1L)).isEqualTo("cat-001");
        }

        @Test @DisplayName("分类名称匹配")
        void catName() {
            when(categoryMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(testCategory));
            assertThat(productService.resolveCategoryId("窗帘布艺", 1L)).isEqualTo("cat-001");
        }

        @Test @DisplayName("分类未找到 → null")
        void catNotFound() {
            when(categoryMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
            assertThat(productService.resolveCategoryId("不存在", 1L)).isNull();
        }
    }

    @Nested @DisplayName("Agent 库存调整（生产回归：假成功修复）")
    class StockAdjust {

        private ProductSku sku(long id, int stock) {
            ProductSku s = new ProductSku();
            s.setId(id);
            s.setProductId("prod-001");
            s.setTenantId(1L);
            s.setColorName("米白");
            s.setSellingMethod("bulk_cut");
            s.setDoorWidth("2.8米");
            s.setStock(stock);
            return s;
        }

        private void stubProductAndSkus(List<ProductSku> skus) {
            when(productMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testProduct);
            when(productMapper.selectById("prod-001")).thenReturn(testProduct);
            when(productColorMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
            // 第一次 selectList = adjust 加载 SKU；第二次 = getProductById 的 getTotalStock 读回
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(new java.util.ArrayList<>(skus), new java.util.ArrayList<>(skus));
            when(productSkuMapper.updateById(any(ProductSku.class))).thenReturn(1);
            when(productMapper.updateById(any(Product.class))).thenReturn(1);
            when(productAttributeMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
        }

        @Test @DisplayName("增加库存 — 均匀分配 + 余数给第一个 SKU")
        void increaseDistributesEvenly() {
            ProductSku a = sku(1L, 30);
            ProductSku b = sku(2L, 20);
            stubProductAndSkus(List.of(a, b));

            ProductResponse r = productService.adjustStockForAgent("prod-001", 3, "盘点", 1L);

            // 独立手工算例：+3 在 [30,20] 上均匀分配 → [32,21]，总和 53
            assertThat(a.getStock()).isEqualTo(32);
            assertThat(b.getStock()).isEqualTo(21);
            assertThat(r.getStock()).isEqualTo(53);
        }

        @Test @DisplayName("增加库存 — 整除时平均分配")
        void increaseEvenSplit() {
            ProductSku a = sku(1L, 30);
            ProductSku b = sku(2L, 20);
            stubProductAndSkus(List.of(a, b));

            ProductResponse r = productService.adjustStockForAgent("prod-001", 10, "进货", 1L);

            assertThat(a.getStock()).isEqualTo(35);
            assertThat(b.getStock()).isEqualTo(25);
            assertThat(r.getStock()).isEqualTo(60);
        }

        @Test @DisplayName("减少库存 — 从库存最大的 SKU 优先扣减")
        void decreaseGreedyFromLargest() {
            ProductSku a = sku(1L, 30);
            ProductSku b = sku(2L, 20);
            stubProductAndSkus(List.of(a, b));

            ProductResponse r = productService.adjustStockForAgent("prod-001", -25, "报损", 1L);

            // -25：最大 30 的 SKU 先扣 → [5, 20]，总和 25
            assertThat(a.getStock()).isEqualTo(5);
            assertThat(b.getStock()).isEqualTo(20);
            assertThat(r.getStock()).isEqualTo(25);
        }

        @Test @DisplayName("减少超出总量 — 抛库存不足且不写库")
        void decreaseInsufficientThrows() {
            ProductSku a = sku(1L, 30);
            ProductSku b = sku(2L, 20);
            stubProductAndSkus(List.of(a, b));

            assertThatThrownBy(() -> productService.adjustStockForAgent("prod-001", -60, "报损", 1L))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("库存不足");
            verify(productSkuMapper, never()).updateById(any(ProductSku.class));
        }

        @Test @DisplayName("无 SKU — 明确报错而非静默成功")
        void noSkusThrows() {
            stubProductAndSkus(List.of());

            assertThatThrownBy(() -> productService.adjustStockForAgent("prod-001", 10, "进货", 1L))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("SKU");
        }

        @Test @DisplayName("商品不存在 — notFound")
        void productNotFound() {
            when(productMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);

            assertThatThrownBy(() -> productService.adjustStockForAgent("prod-x", 10, "进货", 1L))
                    .isInstanceOf(BusinessException.class);
        }
    }
}
