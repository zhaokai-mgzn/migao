# 模板库索引

8 个常见业务模式模板，供军师反推 case 时参考。

| 模板 | 适用场景 | 红牌 |
|---|---|---|
| [dashboard-jump.yml](./dashboard-jump.yml) | 看板跳转/卡片数字 | #387 #388 #389 |
| [order-classify.yml](./order-classify.yml) | 订单分类/状态流转 | #390 |
| [product-sku-stock.yml](./product-sku-stock.yml) | SKU 库存汇总 | #382 |
| [customer-list.yml](./customer-list.yml) | 客户列表/详情 | — |
| [aftersales-flow.yml](./aftersales-flow.yml) | 售后流程 | — |
| [auth-sms.yml](./auth-sms.yml) | 短信登录/注册 | #375 |
| [employee-role.yml](./employee-role.yml) | 员工/角色权限 | #384 #385 |
| [knowledge-ai.yml](./knowledge-ai.yml) | 知识库/AI | — |

## 模板字段

```yaml
name: 模板名
description: 适用场景
red_flags: 关联红牌 issue 列表

business_truths:  # 业务真值（人写参考，AI 反推时基于此）
  - ...

primary_specs:  # 主验收跑的 spec
  - tests/e2e/specs/...

reviewer_asserts:  # 复核验收跑的 API 断言（DB 是 reviewer 内部实现，不暴露）
  - API: GET /api/...
    expect: data > 0

confidence_required: 100%  # 自动 close 阈值

common_pitfalls:  # 常见错误，研发 review 时提醒
  - ...
```

## 维护规则

- 每次研发"case 不合理"反馈 → 改对应模板
- 每月看一次反推准确率，淘汰/合并模板
