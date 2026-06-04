# OSS 分层存储策略

> 版本：v1.0  
> 日期：2026-06-04  
> 状态：设计完成，待实施

---

## 1. 背景

当前项目所有文件存储在单个 OSS Bucket (`ai-customer-service-admin-dev`)，存在以下问题：

1. **存储成本浪费**：聊天图片等临时数据占用永久存储空间
2. **管理复杂**：无法区分业务数据类型
3. **无法自动清理**：临时数据需要手动清理

---

## 2. 存储策略设计

### 2.1 双 Bucket 架构

```
OSS 存储架构
├── {permanent_bucket_name}  (永久存储)
│   ├── 管理前端静态托管 (Next.js 导出)
│   ├── 商品图片 (products/{tenant_id}/)
│   ├── 客户头像 (avatars/{tenant_id}/)
│   └── 营业执照 (business-licenses/{tenant_id}/)
│
└── {temporary_bucket_name}  (临时存储)
    └── 聊天图片 (chat/{tenant_id}/)
        └── 生命周期规则：{chat_image_retention_days} 天后自动删除
```

### 2.2 环境变量配置

| 环境变量 | 说明 | 示例值 |
|---------|------|--------|
| `OSS_PERMANENT_BUCKET` | 永久存储 Bucket | `ai-customer-service-admin-dev` |
| `OSS_TEMPORARY_BUCKET` | 临时存储 Bucket | `ai-customer-service-chat-dev` |
| `OSS_CHAT_RETENTION_DAYS` | 聊天图片保留天数 | `7` |
| `NEXT_PUBLIC_OSS_DOMAIN` | 永久 Bucket 域名（前端访问） | `https://ai-customer-service-admin-dev.oss-cn-hangzhou.aliyuncs.com` |

### 2.3 文件分类规则

| 文件类型 | 上传目录 | 目标 Bucket | 存储策略 |
|---------|---------|------------|---------|
| 商品图片 | `products/{tenant_id}/` | 永久 | 永久存储 |
| 客户头像 | `avatars/{tenant_id}/` | 永久 | 永久存储 |
| 营业执照 | `business-licenses/{tenant_id}/` | 永久 | 永久存储 |
| 聊天图片 | `chat/{tenant_id}/` | 临时 | 7 天后自动删除 |
| 其他 | `misc/{tenant_id}/` | 永久 | 永久存储 |

---

## 3. Terraform 配置

### 3.1 变量定义

```hcl
variable "permanent_bucket_name" {
  description = "永久存储 Bucket 名称（商品图片、管理前端等）"
  type        = string
  default     = "ai-customer-service-admin-dev"
}

variable "temporary_bucket_name" {
  description = "临时存储 Bucket 名称（聊天图片等）"
  type        = string
  default     = "ai-customer-service-chat-dev"
}

variable "chat_image_retention_days" {
  description = "聊天图片保留天数"
  type        = number
  default     = 7
}
```

### 3.2 永久存储 Bucket

```hcl
resource "alicloud_oss_bucket" "permanent" {
  bucket = var.permanent_bucket_name
  acl    = "public-read"

  website {
    index_document = "index.html"
    error_document = "404.html"
  }

  tags = {
    Environment = var.environment
    Type        = "permanent-storage"
  }
}
```

### 3.3 临时存储 Bucket（带生命周期规则）

```hcl
resource "alicloud_oss_bucket" "temporary" {
  bucket = var.temporary_bucket_name
  acl    = "public-read"

  lifecycle_rule {
    id      = "auto-delete-chat-images"
    prefix  = "chat/"
    enabled = true

    expiration {
      days = var.chat_image_retention_days
    }
  }

  tags = {
    Environment = var.environment
    Type        = "temporary-storage"
  }
}
```

### 3.4 SAE 环境变量注入

```hcl
# admin-api 环境变量
app_envs {
  name  = "OSS_PERMANENT_BUCKET"
  value = alicloud_oss_bucket.permanent.bucket
}
app_envs {
  name  = "OSS_TEMPORARY_BUCKET"
  value = alicloud_oss_bucket.temporary.bucket
}

# ai-agent-service 环境变量
app_envs {
  name  = "OSS_PERMANENT_BUCKET"
  value = alicloud_oss_bucket.permanent.bucket
}
app_envs {
  name  = "OSS_TEMPORARY_BUCKET"
  value = alicloud_oss_bucket.temporary.bucket
}
```

---

## 4. 代码实现

### 4.1 admin-api (Java)

```java
@ConfigurationProperties(prefix = "aliyun.oss")
public class OssConfig {
    private String endpoint;
    private String accessKeyId;
    private String accessKeySecret;
    private String permanentBucket;  // 新增
    private String temporaryBucket;  // 新增
}

@Service
public class OssService implements FileStorageService {
    
    /**
     * 根据目录自动选择 Bucket
     */
    public String upload(MultipartFile file, String directory) {
        String bucket = selectBucket(directory);
        return doUpload(bucket, file, directory);
    }
    
    private String selectBucket(String directory) {
        if (directory.startsWith("chat/")) {
            return ossConfig.getTemporaryBucket();
        }
        return ossConfig.getPermanentBucket();
    }
}
```

### 4.2 ai-agent-service (Python)

```python
# app/api/upload.py
from app.config import settings

def select_bucket(directory: str) -> str:
    """根据目录选择 Bucket"""
    if directory.startswith("chat/"):
        return settings.OSS_TEMPORARY_BUCKET
    return settings.OSS_PERMANENT_BUCKET

@router.post("/upload")
async def upload_file(file: UploadFile, directory: str = "misc"):
    bucket = select_bucket(directory)
    return await oss_client.upload(bucket, file, directory)
```

### 4.3 前端配置

```typescript
// next.config.js
module.exports = {
  images: {
    domains: [
      // 永久 Bucket（商品图片等）
      process.env.NEXT_PUBLIC_OSS_DOMAIN?.replace('https://', '') || '',
      // 临时 Bucket（聊天图片）
      process.env.NEXT_PUBLIC_CHAT_OSS_DOMAIN?.replace('https://', '') || '',
    ],
  },
}
```

---

## 5. 部署步骤

### 5.1 开发环境（已有数据）

```bash
# 1. 更新 Terraform 配置
cd deploy/terraform
terraform init
terraform plan -var="permanent_bucket_name=ai-customer-service-admin-dev" \
               -var="temporary_bucket_name=ai-customer-service-chat-dev"

# 2. 应用变更（会创建第二个 Bucket）
terraform apply

# 3. 更新 SAE 环境变量（自动注入）
# Terraform 会自动更新 SAE 应用的 app_envs

# 4. 重新部署服务
gh workflow run deploy-admin-api.yml
gh workflow run deploy-ai-agent-service.yml
```

### 5.2 生产环境（全新部署）

```bash
# 1. 配置 terraform.tfvars
cat > terraform.tfvars <<EOF
permanent_bucket_name     = "youke-admin-prod"
temporary_bucket_name     = "youke-chat-prod"
chat_image_retention_days = 7
EOF

# 2. 部署基础设施
terraform init
terraform plan
terraform apply

# 3. 后续步骤参考 deployment-aliyun.md
```

---

## 6. 成本对比

### 当前方案（单 Bucket）

| 数据类型 | 存储量（预估） | 存储成本/月 |
|---------|-------------|-----------|
| 管理前端 | ~50 MB | ¥0.01 |
| 商品图片 | ~500 MB | ¥0.08 |
| 聊天图片 | ~2 GB（持续增长） | ¥0.32 |
| **总计** | **~2.5 GB** | **¥0.41** |

### 新方案（双 Bucket + 生命周期）

| 数据类型 | 存储量（预估） | 存储成本/月 |
|---------|-------------|-----------|
| 永久 Bucket | ~550 MB | ¥0.09 |
| 临时 Bucket | ~200 MB（自动清理） | ¥0.03 |
| **总计** | **~750 MB** | **¥0.12** |

**成本节省：约 70%**

---

## 7. 迁移计划

### 7.1 向后兼容

- 现有文件路径不变，只是存储位置可能迁移
- 前端访问域名不变（仍通过 `NEXT_PUBLIC_OSS_DOMAIN`）
- API 接口不变

### 7.2 数据迁移（可选）

如果需要将现有聊天图片迁移到临时 Bucket：

```bash
# 使用 ossutil 批量迁移
ossutil cp oss://ai-customer-service-admin-dev/chat/ \
           oss://ai-customer-service-chat-dev/chat/ \
           --recursive

# 迁移完成后删除旧数据
ossutil rm oss://ai-customer-service-admin-dev/chat/ --recursive
```

---

## 8. 监控与告警

### 8.1 存储量监控

```bash
# 查询 Bucket 存储量
aliyun oss stat oss://ai-customer-service-admin-dev
aliyun oss stat oss://ai-customer-service-chat-dev

# 设置告警（存储量 > 10GB）
aliyun cms PutMetricRule \
  --RuleName "OSS-Storage-High" \
  --Namespace acs_oss \
  --MetricName StorageUtilization \
  --ComparisonOperator ">=" \
  --Threshold 10240
```

### 8.2 生命周期规则监控

```bash
# 查询生命周期规则执行情况
aliyun oss lifecycle-get oss://ai-customer-service-chat-dev
```

---

## 9. 检查清单

### 部署前

- [ ] Terraform 变量配置完成（`terraform.tfvars`）
- [ ] 永久 Bucket 名称确认（生产环境建议用 `youke-admin-prod`）
- [ ] 临时 Bucket 名称确认（生产环境建议用 `youke-chat-prod`）
- [ ] 聊天图片保留天数确认（默认 7 天）

### 部署后

- [ ] 永久 Bucket 创建成功
- [ ] 临时 Bucket 创建成功
- [ ] 生命周期规则生效
- [ ] SAE 环境变量更新
- [ ] admin-api 重新部署
- [ ] ai-agent-service 重新部署
- [ ] 商品图片上传测试通过
- [ ] 聊天图片上传测试通过
- [ ] 前端图片显示正常

---

## 10. 故障排查

### 10.1 常见问题

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| 聊天图片上传失败 | 临时 Bucket 未创建 | 检查 Terraform 输出 |
| 商品图片 404 | Bucket 名称错误 | 检查 `OSS_PERMANENT_BUCKET` 环境变量 |
| 聊天图片未自动删除 | 生命周期规则未生效 | 检查 `lifecycle_rule` 配置 |
| 前端图片显示异常 | NEXT_PUBLIC_OSS_DOMAIN 错误 | 检查前端环境变量 |

### 10.2 日志查询

```bash
# 查询 admin-api 日志
aliyun sae GetApplicationLog --AppId <admin-api-app-id> --Lines 100

# 查询 ai-agent-service 日志
aliyun sae GetApplicationLog --AppId <ai-agent-app-id> --Lines 100
```

---

## 11. 参考资料

- [阿里云 OSS 生命周期规则](https://help.aliyun.com/document_detail/31904.html)
- [阿里云 OSS 多 Bucket 管理](https://help.aliyun.com/document_detail/31827.html)
- [Terraform alicloud_oss_bucket](https://registry.terraform.io/providers/aliyun/alicloud/latest/docs/resources/oss_bucket)
