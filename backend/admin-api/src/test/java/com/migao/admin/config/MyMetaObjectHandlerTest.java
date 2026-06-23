package com.migao.admin.config;

import com.baomidou.mybatisplus.core.handlers.MetaObjectHandler;
import org.apache.ibatis.reflection.MetaObject;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.time.OffsetDateTime;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * MyMetaObjectHandler 单元测试
 * 使用 Mockito spy 来验证 strictInsertFill / strictUpdateFill 的调用参数，
 * 避免 TableInfo 为 null 导致的 NPE（单元测试不需要实体类映射）。
 */
class MyMetaObjectHandlerTest {

    private MyMetaObjectHandler handler;
    private MetaObject metaObject;

    @BeforeEach
    void setUp() {
        handler = spy(new MyMetaObjectHandler());
        metaObject = mock(MetaObject.class);

        // 对所有 strictInsertFill / strictUpdateFill 调用做放行（避免 TableInfo NPE）
        // 注意：MyBatis-Plus 3.5.8 有两个 overload（Class+value / Supplier+Class），
        // 需要用明确的类型匹配器区分
        doReturn(handler).when(handler).strictInsertFill(
                any(MetaObject.class), anyString(),
                any(Class.class), any(OffsetDateTime.class));
        doReturn(handler).when(handler).strictUpdateFill(
                any(MetaObject.class), anyString(),
                any(Class.class), any(OffsetDateTime.class));
    }

    // ======================== insertFill 测试 ========================

    @Nested
    @DisplayName("insertFill")
    class InsertFill {

        @Test
        @DisplayName("应对 createdAt 调用 strictInsertFill")
        void shouldCallStrictInsertFillForCreatedAt() {
            handler.insertFill(metaObject);

            verify(handler).strictInsertFill(
                    eq(metaObject), eq("createdAt"),
                    eq(OffsetDateTime.class), any(OffsetDateTime.class));
        }

        @Test
        @DisplayName("应对 updatedAt 调用 strictInsertFill")
        void shouldCallStrictInsertFillForUpdatedAt() {
            handler.insertFill(metaObject);

            verify(handler).strictInsertFill(
                    eq(metaObject), eq("updatedAt"),
                    eq(OffsetDateTime.class), any(OffsetDateTime.class));
        }

        @Test
        @DisplayName("应同时填充 createdAt 和 updatedAt 两个字段")
        void shouldFillBothTimestamps() {
            handler.insertFill(metaObject);

            verify(handler, times(1)).strictInsertFill(
                    eq(metaObject), eq("createdAt"),
                    eq(OffsetDateTime.class), any(OffsetDateTime.class));
            verify(handler, times(1)).strictInsertFill(
                    eq(metaObject), eq("updatedAt"),
                    eq(OffsetDateTime.class), any(OffsetDateTime.class));
        }

        @Test
        @DisplayName("不应调用 strictUpdateFill（插入时不应执行更新填充逻辑）")
        void shouldNotCallStrictUpdateFill() {
            handler.insertFill(metaObject);

            verify(handler, never()).strictUpdateFill(
                    any(MetaObject.class), anyString(),
                    any(Class.class), any(OffsetDateTime.class));
        }
    }

    // ======================== updateFill 测试 ========================

    @Nested
    @DisplayName("updateFill")
    class UpdateFill {

        @Test
        @DisplayName("应对 updatedAt 调用 strictUpdateFill")
        void shouldCallStrictUpdateFillForUpdatedAt() {
            handler.updateFill(metaObject);

            verify(handler).strictUpdateFill(
                    eq(metaObject), eq("updatedAt"),
                    eq(OffsetDateTime.class), any(OffsetDateTime.class));
        }

        @Test
        @DisplayName("不应调用 strictInsertFill（更新时不应执行插入填充逻辑）")
        void shouldNotCallStrictInsertFill() {
            handler.updateFill(metaObject);

            verify(handler, never()).strictInsertFill(
                    any(MetaObject.class), anyString(),
                    any(Class.class), any(OffsetDateTime.class));
        }

        @Test
        @DisplayName("应只填充 updatedAt 一个字段")
        void shouldOnlyFillUpdatedAt() {
            handler.updateFill(metaObject);

            verify(handler, times(1)).strictUpdateFill(
                    eq(metaObject), eq("updatedAt"),
                    eq(OffsetDateTime.class), any(OffsetDateTime.class));
        }
    }

    // ======================== 字段类型验证 ========================

    @Test
    @DisplayName("insertFill 对 createdAt 应使用 OffsetDateTime 类型")
    void insertFill_createdAtShouldUseOffsetDateTimeType() {
        handler.insertFill(metaObject);

        verify(handler).strictInsertFill(
                eq(metaObject), eq("createdAt"),
                eq(OffsetDateTime.class), any(OffsetDateTime.class));
    }

    @Test
    @DisplayName("insertFill 对 updatedAt 应使用 OffsetDateTime 类型")
    void insertFill_updatedAtShouldUseOffsetDateTimeType() {
        handler.insertFill(metaObject);

        verify(handler).strictInsertFill(
                eq(metaObject), eq("updatedAt"),
                eq(OffsetDateTime.class), any(OffsetDateTime.class));
    }

    @Test
    @DisplayName("updateFill 对 updatedAt 应使用 OffsetDateTime 类型")
    void updateFill_shouldUseOffsetDateTimeType() {
        handler.updateFill(metaObject);

        verify(handler).strictUpdateFill(
                eq(metaObject), eq("updatedAt"),
                eq(OffsetDateTime.class), any(OffsetDateTime.class));
    }

    // ======================== @Component 和接口验证 ========================

    @Test
    @DisplayName("应有 @Component 注解")
    void shouldHaveComponentAnnotation() {
        var annotation = MyMetaObjectHandler.class.getAnnotation(
                org.springframework.stereotype.Component.class);
        assertThat(annotation).isNotNull();
    }

    @Test
    @DisplayName("应实现 MetaObjectHandler 接口")
    void shouldImplementMetaObjectHandler() {
        boolean implementsInterface = MetaObjectHandler.class
                .isAssignableFrom(MyMetaObjectHandler.class);
        assertThat(implementsInterface).isTrue();
    }
}
