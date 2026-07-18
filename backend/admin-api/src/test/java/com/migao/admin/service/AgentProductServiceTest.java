package com.migao.admin.service;

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
    @Mock private ProductProcessingItemMapper productProcessingItemMapper;
    @Mock private ProcessingItemMapper processingItemMapper;
    @Mock private ProductAttributeMapper productAttributeMapper;

    private Product testProduct;
    private Category testCategory;
    private ProcessingItem testPi;

    @BeforeEach
    void setUp() {
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant asst = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(asst, Product.class);
        TableInfoHelper.initTableInfo(asst, Category.class);
        TableInfoHelper.initTableInfo(asst, ProductColor.class);
        TableInfoHelper.initTableInfo(asst, ProductSku.class);
        TableInfoHelper.initTableInfo(asst, ProcessingItem.class);
        TableInfoHelper.initTableInfo(asst, ProductProcessingItem.class);

        testCategory = Category.builder().id("cat-001").name("窗帘布艺").tenantId(1L).build();
        testProduct = Product.builder()
                .id("prod-001").name("遮光窗帘").tenantId(1L)
                .categoryId("cat-001").basePrice(new BigDecimal("99.00"))
                .status("on_sale").stock(100).unit("米").pricingType("per_meter").build();
        testPi = ProcessingItem.builder().id("pi-001").name("打孔")
                .tenantId(1L).status("active").build();
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
            when(productProcessingItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
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
    }

    @Nested @DisplayName("加工项增删")
    class ProcessingItems {
        @Test @DisplayName("add 新加工项")
        void add() {
            AgentProcessingItemActionRequest req = new AgentProcessingItemActionRequest();
            req.setAction("add"); req.setItemIds(List.of("pi-001"));
            when(productMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testProduct);
            when(processingItemMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(testPi));
            when(productProcessingItemMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of());
            when(productProcessingItemMapper.insert(any(ProductProcessingItem.class))).thenReturn(1);
            when(processingItemMapper.selectById("pi-001")).thenReturn(testPi);

            productService.updateProductProcessingItems("prod-001", req, 1L);
            verify(productProcessingItemMapper).insert(any(ProductProcessingItem.class));
        }

        @Test @DisplayName("remove 加工项")
        void remove() {
            AgentProcessingItemActionRequest req = new AgentProcessingItemActionRequest();
            req.setAction("remove"); req.setItemIds(List.of("pi-001"));
            when(productMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testProduct);
            when(processingItemMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(testPi));
            when(productProcessingItemMapper.delete(any(LambdaQueryWrapper.class))).thenReturn(1);

            productService.updateProductProcessingItems("prod-001", req, 1L);
            verify(productProcessingItemMapper).delete(any(LambdaQueryWrapper.class));
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

        @Test @DisplayName("加工项 UUID 匹配")
        void piUuid() {
            when(processingItemMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(testPi));
            assertThat(productService.resolveProcessingItemIds(List.of("pi-001"), 1L))
                    .containsExactly("pi-001");
        }

        @Test @DisplayName("加工项名称匹配")
        void piName() {
            when(processingItemMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(testPi));
            assertThat(productService.resolveProcessingItemIds(List.of("打孔"), 1L))
                    .containsExactly("pi-001");
        }

        @Test @DisplayName("加工项序号匹配（1-based）")
        void piRow() {
            when(processingItemMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(testPi));
            assertThat(productService.resolveProcessingItemIds(List.of("1"), 1L))
                    .containsExactly("pi-001");
        }

        @Test @DisplayName("混合传入")
        void piMixed() {
            ProcessingItem pi2 = ProcessingItem.builder().id("pi-002").name("S钩")
                    .tenantId(1L).status("active").build();
            when(processingItemMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(testPi, pi2));
            List<String> r = productService.resolveProcessingItemIds(
                    List.of("pi-001", "S钩", "2"), 1L);
            assertThat(r).containsExactly("pi-001", "pi-002", "pi-002");
        }
    }
}
