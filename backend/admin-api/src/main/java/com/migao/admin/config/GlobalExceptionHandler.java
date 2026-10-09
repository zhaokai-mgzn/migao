package com.migao.admin.config;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.exception.PermissionDeniedException;
import com.migao.admin.security.PermissionDeniedResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.ConstraintViolation;
import jakarta.validation.ConstraintViolationException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.authentication.AuthenticationCredentialsNotFoundException;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.security.core.AuthenticationException;
import org.springframework.validation.FieldError;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.HttpMediaTypeNotSupportedException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.NoHandlerFoundException;
import org.springframework.web.multipart.support.MissingServletRequestPartException;

import java.sql.SQLException;
import java.util.List;
import java.util.stream.Collectors;

/**
 * 全局异常处理器
 * 统一处理各类异常，返回标准 ApiResponse 格式
 */
@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    /**
     * 处理业务异常
     */
    @ExceptionHandler(BusinessException.class)
    public ResponseEntity<ApiResponse<Void>> handleBusinessException(BusinessException e) {
        log.warn("业务异常: [{}] {} suggestion={}", e.getCode(), e.getMessage(), e.getSuggestion());
        // 根据错误类型自动生成 LLM 友好的 suggestion
        String suggestion = e.getSuggestion();
        if (suggestion == null) {
            suggestion = switch (e.getCode()) {
                case "NOT_FOUND" -> "请检查 ID 是否正确。如果使用了商品名称，请先用 product_search 查出 UUID 后重试";
                case "VALIDATION_ERROR" -> "请检查必填字段是否完整，字段格式是否正确";
                default -> null;
            };
        }
        // 逐条理由透传（issue #4308）：写面护栏失败要能「逐条展示」——复用既有信封字段
        // error.details:[{field,message}]，不新造字段；e.getDetails() 为 null 时与旧行为逐字相同。
        ApiResponse<Void> response = ApiResponse.error(e.getCode(), e.getMessage(), e.getDetails());
        if (suggestion != null) {
            response.setSuggestion(suggestion);
        }
        return ResponseEntity.status(e.getHttpStatus()).body(response);
    }

    /**
     * 处理参数校验异常（@Valid 注解）
     */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ApiResponse<Void>> handleValidationException(MethodArgumentNotValidException e) {
        List<ApiResponse.ErrorDetail> details = e.getBindingResult().getFieldErrors().stream()
                .map(this::mapFieldError)
                .collect(Collectors.toList());

        String message = details.stream()
                .map(ApiResponse.ErrorDetail::getMessage)
                .collect(Collectors.joining(", "));

        log.warn("参数校验失败: {}", message);
        ApiResponse<Void> response = ApiResponse.error("VALIDATION_ERROR", "参数校验失败", details);
        return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY).body(response);
    }

    /**
     * 处理约束校验异常（@Validated 注解）
     */
    @ExceptionHandler(ConstraintViolationException.class)
    public ResponseEntity<ApiResponse<Void>> handleConstraintViolationException(ConstraintViolationException e) {
        List<ApiResponse.ErrorDetail> details = e.getConstraintViolations().stream()
                .map(this::mapConstraintViolation)
                .collect(Collectors.toList());

        String message = details.stream()
                .map(ApiResponse.ErrorDetail::getMessage)
                .collect(Collectors.joining(", "));

        log.warn("约束校验失败: {}", message);
        ApiResponse<Void> response = ApiResponse.error("VALIDATION_ERROR", "参数校验失败", details);
        return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY).body(response);
    }

    /**
     * 处理认证异常
     */
    @ExceptionHandler(AuthenticationException.class)
    public ResponseEntity<ApiResponse<Void>> handleAuthenticationException(AuthenticationException e) {
        log.warn("认证失败: {}", e.getMessage());
        String code = "AUTH_REQUIRED";
        String message = "认证失败";

        if (e instanceof BadCredentialsException) {
            message = "用户名或密码错误";
        } else if (e instanceof AuthenticationCredentialsNotFoundException) {
            message = "未提供认证信息";
        }

        ApiResponse<Void> response = ApiResponse.error(code, message);
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body(response);
    }

    /**
     * 处理访问拒绝异常
     *
     * <p>{@code @RequirePermission} 拒绝时抛出的是 {@link PermissionDeniedException}，其
     * {@code requiredPermission} 是结构化字段（不再解析异常 message）：权限码会进
     * {@code error.message} 与 {@code error.details}，并由 {@link PermissionDeniedResponse}
     * 附上「不要重试同一工具 + 找管理员授权」的可执行 suggestion（issue #4105 F1）。</p>
     */
    @ExceptionHandler(AccessDeniedException.class)
    public ResponseEntity<ApiResponse<Void>> handleAccessDeniedException(AccessDeniedException e) {
        String requiredPermission = e instanceof PermissionDeniedException denied
                ? denied.getRequiredPermission() : null;
        log.warn("权限不足: {} (requiredPermission={})", e.getMessage(), requiredPermission);
        return ResponseEntity.status(HttpStatus.FORBIDDEN)
                .body(PermissionDeniedResponse.of(requiredPermission));
    }

    /**
     * 处理非法参数异常
     */
    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<ApiResponse<Void>> handleIllegalArgumentException(IllegalArgumentException e) {
        log.warn("非法参数: {}", e.getMessage());
        ApiResponse<Void> response = ApiResponse.error("VALIDATION_ERROR", e.getMessage());
        return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY).body(response);
    }

    /**
     * 处理非法状态异常
     */
    @ExceptionHandler(IllegalStateException.class)
    public ResponseEntity<ApiResponse<Void>> handleIllegalStateException(IllegalStateException e) {
        log.warn("非法状态: {}", e.getMessage());
        ApiResponse<Void> response = ApiResponse.error("ILLEGAL_STATE", e.getMessage());
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(response);
    }

    /**
     * 处理 405 —— 请求方法不被支持
     */
    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    public ResponseEntity<ApiResponse<Void>> handleMethodNotSupported(HttpRequestMethodNotSupportedException e) {
        log.warn("请求方法不被支持: {} (supported: {})", e.getMethod(), e.getSupportedHttpMethods());
        ApiResponse<Void> response = ApiResponse.error("METHOD_NOT_ALLOWED", "Method not allowed: " + e.getMethod());
        return ResponseEntity.status(HttpStatus.METHOD_NOT_ALLOWED).body(response);
    }

    /**
     * 处理 404 —— 请求的端点不存在
     */
    @ExceptionHandler(NoHandlerFoundException.class)
    public ResponseEntity<ApiResponse<Void>> handleNoHandlerFound(NoHandlerFoundException e) {
        log.warn("请求的资源不存在: {} {}", e.getHttpMethod(), e.getRequestURL());
        ApiResponse<Void> response = ApiResponse.error("NOT_FOUND", "请求的资源不存在: " + e.getRequestURL());
        return ResponseEntity.status(HttpStatus.NOT_FOUND).body(response);
    }

    /**
     * 处理请求体格式错误或缺失（JSON 解析失败、空 body、缺少 Content-Type 等）
     */
    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<ApiResponse<Void>> handleMessageNotReadable(HttpMessageNotReadableException e) {
        log.warn("请求体格式错误: {}", e.getMessage());
        ApiResponse<Void> response = ApiResponse.error("BAD_REQUEST", "请求体格式错误或缺失");
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(response);
    }

    /**
     * 处理不支持的 Content-Type
     */
    @ExceptionHandler(HttpMediaTypeNotSupportedException.class)
    public ResponseEntity<ApiResponse<Void>> handleMediaTypeNotSupported(HttpMediaTypeNotSupportedException e) {
        log.warn("不支持的 Content-Type: {}", e.getContentType());
        ApiResponse<Void> response = ApiResponse.error("UNSUPPORTED_MEDIA_TYPE",
                "不支持的 Content-Type: " + e.getContentType());
        return ResponseEntity.status(HttpStatus.UNSUPPORTED_MEDIA_TYPE).body(response);
    }

    /**
     * 处理 400 —— 缺少**必填**请求参数（{@code @RequestParam} 未标 {@code required=false} 而请求里没有）
     *
     * <p>issue #5982：此前无此分支 ⇒ 落兜底 {@code Exception} ⇒ 客户端集成错误被报成
     * 500「服务器内部错误」（监控误报、排障走偏）。此处给出**缺失的字段名**，错误体与既有
     * 400 / 422 同形（{@code error.details:[{field,message}]}）。</p>
     */
    @ExceptionHandler(MissingServletRequestParameterException.class)
    public ResponseEntity<ApiResponse<Void>> handleMissingServletRequestParameter(
            MissingServletRequestParameterException e) {
        String field = e.getParameterName();
        log.warn("缺少必填请求参数: {} (期望类型 {})", field, e.getParameterType());
        ApiResponse<Void> response = ApiResponse.error("BAD_REQUEST", "缺少必填参数: " + field,
                List.of(new ApiResponse.ErrorDetail(field, "缺少必填参数")));
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(response);
    }

    /**
     * 处理 400 —— 请求参数**类型不符**（有值但转不成目标类型，同为客户端错误 ⇒ 不是 500）
     */
    @ExceptionHandler(MethodArgumentTypeMismatchException.class)
    public ResponseEntity<ApiResponse<Void>> handleMethodArgumentTypeMismatch(
            MethodArgumentTypeMismatchException e) {
        String field = e.getName();
        String expected = e.getRequiredType() == null ? "?" : e.getRequiredType().getSimpleName();
        log.warn("请求参数类型不符: {} (期望 {})", field, expected);
        ApiResponse<Void> response = ApiResponse.error("BAD_REQUEST", "参数类型不正确: " + field,
                List.of(new ApiResponse.ErrorDetail(field, "参数类型不正确，期望 " + expected)));
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(response);
    }

    /**
     * 处理 400 —— 缺**必填的 multipart 部分**（{@code @RequestPart} 未标 {@code required=false} 而请求里没有）
     *
     * <p>issue #6008：与 #5982 **同族同因** —— 此前无此分支 ⇒ 落兜底 {@code Exception} ⇒ 客户端少传一个
     * 表单部分被报成 500「服务器内部错误」。本仓有**可达**的 multipart 端点
     * （{@code POST /api/admin/inbound-orders/opening-import} 的 {@code file}）⇒ 不是纸面残余。</p>
     */
    @ExceptionHandler(MissingServletRequestPartException.class)
    public ResponseEntity<ApiResponse<Void>> handleMissingServletRequestPart(
            MissingServletRequestPartException e) {
        String field = e.getRequestPartName();
        log.warn("缺少必填的表单部分: {}", field);
        ApiResponse<Void> response = ApiResponse.error("BAD_REQUEST", "缺少必填的表单部分: " + field,
                List.of(new ApiResponse.ErrorDetail(field, "缺少必填的表单部分")));
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(response);
    }

    /**
     * 处理数据库**外键违例**（客户端引用了库里不存在的行）
     *
     * <p>issue #6210：本仓此前**没有**这一族分支 ⇒ PG 的外键违例（Spring 包成
     * {@link DataIntegrityViolationException}）落兜底 {@code Exception} ⇒ 客户端引用了不存在的行
     * 也被报成 <b>500</b>「服务器内部错误」，且兜底那一行把 <b>完整堆栈</b>打进日志
     * ⇒ 约束名 {@code agent_sessions_ai_session_id_fkey} / 表名进日志。实证路径：转人工端点
     * {@code POST /api/admin/agent-sessions} 传不存在的 {@code aiSessionId}。</p>
     *
     * <p><b>射程刻意收窄 = 只认外键</b>：外键违例 = **请求里的引用**不存在 ⇒ 客户端错误，按本仓
     * {@code VALIDATION_ERROR} 语义返 <b>422</b>（与 {@code IllegalArgumentException} 同档；
     * 选它而不选 404 的理由见 PR body）。**其余约束违例（唯一 / 非空 / 检查 / 不可判）刻意不拦、
     * 交回 {@link #handleException} 的兜底 500** —— 本仓已有判据把「基础设施级失败 ⇒ 5xx」钉住
     * （{@code MerchantShipmentAtomicityTest}：建单写面注入唯一键失败 ⇒ **必须仍 5xx**，
     * 该判据更关心回滚；那是既有契约，不能由本单顺手改口径）。
     * ⇒ 本分支的射程 = 外键；所有非外键路径与原行为**逐字节相同**。</p>
     *
     * <p><b>日志面</b>：外键违例这一类 <b>不打异常本体与堆栈</b> —— 原始异常消息里带着**约束名 / 表名 /
     * schema**；只记请求坐标 + 约束**类别**（类别来自 {@code SQLState} 短枚举，不含标识符）。
     * 响应体也只给固定文案（不回声 {@code e.getMessage()}）。{@code request} 允许为 null
     * （非 HTTP 面直接调用本处理器时坐标记 {@code ?}）。</p>
     */
    @ExceptionHandler(DataIntegrityViolationException.class)
    public ResponseEntity<ApiResponse<Void>> handleDataIntegrityViolationException(
            DataIntegrityViolationException e, HttpServletRequest request) {
        ConstraintKind kind = ConstraintKind.of(firstSqlException(e));
        if (kind != ConstraintKind.FOREIGN_KEY) {
            // 非外键 ⇒ **不劫持**：交回既有兜底（唯一键冲突等仍是 500，且仍带堆栈、状态码零变化）。
            // DEBUG 只记「类别」这一格（短枚举、不含标识符）⇒ 运营侧仍可数「哪一类约束在打人」，
            // 而 INFO/WARN 形态与改前**逐字节相同**（不打破既有日志形状契约）。
            log.debug("非外键完整性约束违例（交兜底）: kind={}", kind);
            return handleException(e, request);
        }
        // 🔴 不打异常本体 / 堆栈：约束名与表名就在原始消息里（改前落兜底 ⇒ log.error(…, e) 泄漏）。
        log.warn("外键违例（已脱敏）: method={}, uri={}, tenant={}, kind={}",
                request == null ? "?" : request.getMethod(),
                request == null ? "?" : request.getRequestURI(),
                TenantContext.getTenantId(), kind);
        ApiResponse<Void> response = ApiResponse.error("VALIDATION_ERROR", "请求引用的数据不存在或已被删除");
        return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY).body(response);
    }

    /**
     * 处理所有其他异常
     *
     * <p>🔴 issue #6318：端点 500 必须**在日志里可定位**（「红了但查不到」= 判据面缺陷）——
     * 先记**请求坐标 + 异常类型**（{@code method / uri / tenant / type}），再记异常本体与堆栈。
     * 只记 {@code e.getMessage()} 时，500 的日志里既没有异常类型、也没有端点坐标：
     * 「哪个端点、哪个租户、什么异常」只能靠翻全量日志逐条猜。</p>
     *
     * <p>判据 = {@code StockBatchStocktakeEndpointRaceRealDbTest#endpointFiveHundredCarriesANamedExceptionAndCoordinatesInLog}
     * （把坐标或异常本体从这行里摘掉 ⇒ 端点级判据当场判红）。{@code request} 允许为 null
     * （非 HTTP 面直接调用本处理器时坐标记 {@code ?}）。</p>
     */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiResponse<Void>> handleException(Exception e, HttpServletRequest request) {
        log.error("系统异常: method={}, uri={}, tenant={}, type={}, msg={}",
                request == null ? "?" : request.getMethod(),
                request == null ? "?" : request.getRequestURI(),
                TenantContext.getTenantId(), e.getClass().getName(), e.getMessage(), e);
        ApiResponse<Void> response = ApiResponse.error("INTERNAL_ERROR", "服务器内部错误");
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(response);
    }

    // ========== 辅助方法 ==========

    /** 沿 cause 链找第一个 {@link SQLException}（Spring 会按库不同包 1~2 层）；找不到回 null。 */
    private static SQLException firstSqlException(Throwable e) {
        for (Throwable t = e; t != null; t = t.getCause()) {
            if (t instanceof SQLException sql) {
                return sql;
            }
        }
        return null;
    }

    /**
     * 约束**类别**（日志用 / 归口分流用的短枚举）—— 由 {@code SQLState} 推出。
     *
     * <p>只登记类别、不登记标识符：表名 / 约束名 / schema 一律不进日志（issue #6210 的日志面判据）。
     * 非 JDBC 异常（取不到 SQLState）⇒ {@link #NONE} ⇒ 与「不认识的约束」同样**不劫持**。</p>
     */
    private enum ConstraintKind {
        FOREIGN_KEY, UNIQUE, NOT_NULL, CHECK, OTHER, NONE;

        static ConstraintKind of(SQLException cause) {
            String state = cause == null ? null : cause.getSQLState();
            if (state == null) {
                return NONE;
            }
            return switch (state) {
                // 23502/23503/23505/23514 = SQL:2003 的类 23「完整性约束违例」（非空 / 外键 / 唯一 / 检查）
                case "23502" -> NOT_NULL;
                case "23503" -> FOREIGN_KEY;
                case "23505" -> UNIQUE;
                case "23514" -> CHECK;
                default -> OTHER;
            };
        }
    }

    private ApiResponse.ErrorDetail mapFieldError(FieldError error) {
        return new ApiResponse.ErrorDetail(error.getField(), error.getDefaultMessage());
    }

    private ApiResponse.ErrorDetail mapConstraintViolation(ConstraintViolation<?> violation) {
        String field = violation.getPropertyPath().toString();
        return new ApiResponse.ErrorDetail(field, violation.getMessage());
    }
}
