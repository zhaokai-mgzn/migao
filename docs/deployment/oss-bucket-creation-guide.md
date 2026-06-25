# OSS Bucket 创建指南

> 版本：v1.0  
> 日期：2026-06-04  
> 状态：新增

---

## 1. 概述

本指南详细说明如何创建 OSS 双 Bucket 存储架构，提供三种创建方式：

1. **Terraform 自动化创建**（推荐）
2. **阿里云控制台手动创建**
3. **aliyun CLI 命令行创建**

---

## 2. Bucket 规划

### 2.1 命名规范

```
{项目名}-{环境}-{用途}

示例：
- youke-admin-prod     （生产环境永久存储）
- youke-chat-prod      （生产环境临时存储）
- youke-admin-dev      （开发环境永久存储）
- youke-chat-dev       （开发环境临时存储）
```

### 2.2 当前项目 Bucket 清单

| Bucket 名称 | 环境 | 用途 | 存储策略 |
|------------|------|------|---------|
| `ai-customer-service-admin-dev` | 开发 | 永久存储（前端、商品图片等） | 永久 |
| `ai-customer-service-chat-dev` | 开发 | 临时存储（聊天图片） | 7 天自动删除 |

---

## 3. 方式一：Terraform 自动化创建（推荐）

### 3.1 前置条件

- ✅ 已安装 Terraform
- ✅ 已配置阿里云 AccessKey
- ✅ 已初始化 Terraform 项目

### 3.2 执行步骤

```bash
# 1. 进入 Terraform 目录
cd deploy/terraform

# 2. 初始化（首次执行）
terraform init

# 3. 预览变更
terraform plan \
  -var="permanent_bucket_name=ai-customer-service-admin-dev" \
  -var="temporary_bucket_name=ai-customer-service-chat-dev" \
  -var="chat_image_retention_days=7"

# 4. 确认无误后，应用变更
terraform apply \
  -var="permanent_bucket_name=ai-customer-service-admin-dev" \
  -var="temporary_bucket_name=ai-customer-service-chat-dev" \
  -var="chat_image_retention_days=7"

# 5. 查看输出
terraform output
```

### 3.3 预期输出

```
Apply complete! Resources: 2 added, 0 changed, 0 destroyed.

Outputs:

permanent_bucket_name = "ai-customer-service-admin-dev"
permanent_bucket_domain = "ai-customer-service-admin-dev.oss-cn-hangzhou.aliyuncs.com"
temporary_bucket_name = "ai-customer-service-chat-dev"
temporary_bucket_domain = "ai-customer-service-chat-dev.oss-cn-hangzhou.aliyuncs.com"
```

### 3.4 验证创建成功

```bash
# 查询 Bucket 信息
aliyun oss stat oss://ai-customer-service-admin-dev
aliyun oss stat oss://ai-customer-service-chat-dev

# 查看生命周期规则（临时 Bucket）
aliyun oss lifecycle-get oss://ai-customer-service-chat-dev
```

---

## 4. 方式二：阿里云控制台手动创建

### 4.1 创建永久存储 Bucket

**步骤：**

1. 登录 [阿里云 OSS 控制台](https://oss.console.aliyun.com/)
2. 点击"创建 Bucket"
3. 填写配置：

| 配置项 | 值 | 说明 |
|--------|-----|------|
| **Bucket 名称** | `ai-customer-service-admin-dev` | 全局唯一 |
| **地域** | 华东1（杭州） | 与 SAE 同地域 |
| **存储类型** | 标准存储 | 适合频繁访问 |
| **读写权限** | 公共读 | 前端需要访问 |
| **版本控制** | 关闭 | 节省成本 |
| **服务端加密** | OSS 完全托管 | 默认即可 |
| **实时日志查询** | 关闭 | 开发环境可关闭 |

4. 点击"确定"创建

### 4.2 配置静态网站托管（永久 Bucket）

**步骤：**

1. 在 Bucket 列表中找到 `ai-customer-service-admin-dev`
2. 点击"基础配置" → "静态页面"
3. 配置：

| 配置项 | 值 |
|--------|-----|
| **默认首页** | `index.html` |
| **默认404页** | `404.html` |
| **子目录首页** | 开启 |

4. 点击"保存"

### 4.3 创建临时存储 Bucket

**步骤：**

1. 点击"创建 Bucket"
2. 填写配置：

| 配置项 | 值 |
|--------|-----|
| **Bucket 名称** | `ai-customer-service-chat-dev` |
| **地域** | 华东1（杭州） |
| **存储类型** | 标准存储 |
| **读写权限** | 公共读 |
| **版本控制** | 关闭 |

3. 点击"确定"创建

### 4.4 配置生命周期规则（临时 Bucket）

**步骤：**

1. 在 Bucket 列表中找到 `ai-customer-service-chat-dev`
2. 点击"基础配置" → "生命周期"
3. 点击"创建规则"
4. 配置：

| 配置项 | 值 |
|--------|-----|
| **策略** | 按前缀匹配 |
| **前缀** | `chat/` |
| **文件碎片过期策略** | 不勾选 |
| **删除文件** | 勾选，距最后修改时间 7 天 |

5. 点击"确定"保存

### 4.5 验证创建成功

**在控制台验证：**

1. 返回 Bucket 列表
2. 确认两个 Bucket 都存在：
   - `ai-customer-service-admin-dev`
   - `ai-customer-service-chat-dev`
3. 点击临时 Bucket → "基础配置" → "生命周期"
4. 确认规则已生效

---

## 5. 方式三：aliyun CLI 命令行创建

### 5.1 前置条件

```bash
# 安装 aliyun CLI
brew install aliyun-cli  # macOS

# 配置 AccessKey
aliyun configure
```

### 5.2 创建永久存储 Bucket

```bash
# 1. 创建 Bucket
aliyun oss mb oss://ai-customer-service-admin-dev \
  --region cn-hangzhou \
  --acl public-read

# 2. 配置静态网站托管
aliyun oss website --method put oss://ai-customer-service-admin-dev \
  --index-document index.html \
  --error-document 404.html \
  --subdir-index true

# 3. 验证创建
aliyun oss stat oss://ai-customer-service-admin-dev
```

### 5.3 创建临时存储 Bucket

```bash
# 1. 创建 Bucket
aliyun oss mb oss://ai-customer-service-chat-dev \
  --region cn-hangzhou \
  --acl public-read

# 2. 配置生命周期规则（7 天自动删除 chat/ 目录下的文件）
cat > lifecycle-rule.json <<EOF
{
  "Rule": [
    {
      "ID": "auto-delete-chat-images",
      "Prefix": "chat/",
      "Status": "Enabled",
      "Expiration": {
        "Days": 7
      }
    }
  ]
}
EOF

aliyun oss lifecycle --method put oss://ai-customer-service-chat-dev \
  lifecycle-rule.json

# 3. 验证创建
aliyun oss stat oss://ai-customer-service-chat-dev

# 4. 验证生命周期规则
aliyun oss lifecycle-get oss://ai-customer-service-chat-dev
```

### 5.4 预期输出

```
# 永久 Bucket
LastModifiedTime         Size(B)  StorageClass   ETAG
2026-06-04 15:30:00      0        Standard       D41D8CD98F00B204E9800098ECF8427E

# 临时 Bucket
LastModifiedTime         Size(B)  StorageClass   ETAG
2026-06-04 15:35:00      0        Standard       D41D8CD98F00B204E9800098ECF8427E

# 生命周期规则
{
  "Rule": [
    {
      "ID": "auto-delete-chat-images",
      "Prefix": "chat/",
      "Status": "Enabled",
      "Expiration": {
        "Days": 7
      }
    }
  ]
}
```

---

## 6. 生产环境部署清单

### 6.1 Bucket 命名

| 环境 | 永久 Bucket | 临时 Bucket |
|------|------------|------------|
| 开发 | `ai-customer-service-admin-dev` | `ai-customer-service-chat-dev` |
| 生产 | `youke-admin-prod` | `youke-chat-prod` |

### 6.2 创建步骤（生产环境）

```bash
# 使用 Terraform（推荐）
cd deploy/terraform

terraform init
terraform plan \
  -var="permanent_bucket_name=youke-admin-prod" \
  -var="temporary_bucket_name=youke-chat-prod" \
  -var="chat_image_retention_days=7"

terraform apply \
  -var="permanent_bucket_name=youke-admin-prod" \
  -var="temporary_bucket_name=youke-chat-prod" \
  -var="chat_image_retention_days=7"

# 记录输出
terraform output > ../production-oss-output.txt
```

### 6.3 验证清单

- [ ] 永久 Bucket 创建成功
- [ ] 临时 Bucket 创建成功
- [ ] 永久 Bucket 静态网站托管配置正确
- [ ] 临时 Bucket 生命周期规则生效（7 天自动删除）
- [ ] Bucket ACL 设置为 `public-read`
- [ ] Bucket 地域为 `cn-hangzhou`（与 SAE 同地域）
- [ ] 记录 Bucket 域名到部署文档

---

## 7. 常见问题

### 7.1 Bucket 名称已存在

**错误信息：**
```
BucketAlreadyExists: The requested bucket name is not available.
```

**解决方案：**
- OSS Bucket 名称全局唯一，请更换名称
- 建议格式：`{项目名}-{环境}-{用途}`

### 7.2 权限不足

**错误信息：**
```
AccessDenied: You do not have read permission on this Bucket.
```

**解决方案：**
- 检查 AccessKey 是否有 `oss:*` 权限
- 在 RAM 控制台授予 `AliyunOSSFullAccess` 权限

### 7.3 生命周期规则未生效

**现象：**
- 7 天后文件未被删除

**排查步骤：**
```bash
# 1. 查看生命周期规则
aliyun oss lifecycle-get oss://ai-customer-service-chat-dev

# 2. 确认规则状态为 "Enabled"
# 3. 确认前缀匹配正确（如 "chat/"）
# 4. 等待 OSS 后台执行（最多延迟 24 小时）
```

### 7.4 跨域访问失败

**现象：**
- 前端图片加载失败，报 CORS 错误

**解决方案：**
```bash
# 配置 CORS 规则
cat > cors-rule.json <<EOF
{
  "CORSRule": [
    {
      "AllowedOrigin": ["https://merchant.migaozn.com"],
      "AllowedMethod": ["GET"],
      "AllowedHeader": ["*"],
      "MaxAgeSeconds": 3600
    }
  ]
}
EOF

aliyun oss cors --method put oss://ai-customer-service-admin-dev \
  cors-rule.json
```

---

## 8. 成本预估

### 8.1 开发环境

| Bucket | 存储量 | 存储成本/月 | 请求成本/月 | 总计 |
|--------|--------|-----------|-----------|------|
| 永久 Bucket | ~500 MB | ¥0.08 | ¥0.01 | ¥0.09 |
| 临时 Bucket | ~200 MB | ¥0.03 | ¥0.01 | ¥0.04 |
| **总计** | **~700 MB** | **¥0.11** | **¥0.02** | **¥0.13** |

### 8.2 生产环境

| Bucket | 存储量 | 存储成本/月 | 请求成本/月 | 总计 |
|--------|--------|-----------|-----------|------|
| 永久 Bucket | ~5 GB | ¥0.80 | ¥0.10 | ¥0.90 |
| 临时 Bucket | ~1 GB | ¥0.16 | ¥0.05 | ¥0.21 |
| **总计** | **~6 GB** | **¥0.96** | **¥0.15** | **¥1.11** |

> 注：成本基于阿里云杭州地域标准存储价格估算

---

## 9. 下一步

Bucket 创建完成后，继续：

1. ✅ **配置 SAE 环境变量**（Terraform 自动注入）
2. ⏳ **修改 admin-api 代码**（OssService 支持多 Bucket）
3. ⏳ **修改 ai-agent-service 代码**（upload.py 路由）
4. ⏳ **更新前端配置**（NEXT_PUBLIC_OSS_DOMAIN）
5. ⏳ **部署验证**

---

## 10. 参考资料

- [阿里云 OSS 控制台](https://oss.console.aliyun.com/)
- [aliyun oss CLI 文档](https://help.aliyun.com/document_detail/44927.html)
- [OSS 生命周期规则](https://help.aliyun.com/document_detail/31904.html)
- [Terraform alicloud_oss_bucket](https://registry.terraform.io/providers/aliyun/alicloud/latest/docs/resources/oss_bucket)
