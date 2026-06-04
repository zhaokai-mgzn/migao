# #157 图片上传+视觉识别功能实施计划

## Context

米宝需要支持图片上传和视觉识别能力，让用户可以通过上传图片来：
1. 识别商品图片，自动提取商品信息
2. 识别订单截图，辅助创建订单
3. 识别任何问题图片，提供智能解答

## 现状分析

### ✅ 后端已就绪（无需改动）

1. **chat.py** (line 517-548): 已支持 `images` 字段，处理多模态消息
2. **llm/router.py**: `has_images()` 检测图片 → 自动路由到 `DASHSCOPE_VISION_MODEL`
3. **config.py**: `DASHSCOPE_VISION_MODEL = "qwen3.6-plus"`, `DASHSCOPE_VISION_ENABLED = True`
4. **UploadController**: `/api/admin/files/upload` 接口完整可用，无权限限制

### 🔧 前端需改造

1. **MessageInput.tsx**: 聊天输入框，需要添加图片上传按钮
2. **已有组件可复用**: `ImageUploader` 和 `FileUpload` 都实现了完整的上传逻辑

## 实施方案

### Step 1: 改造 MessageInput.tsx

**文件**: `frontend/admin-web/src/components/chat/MessageInput.tsx`

**改动**:
1. 添加状态管理：`const [images, setImages] = useState<string[]>([])`
2. 添加图片上传按钮（Paperclip 图标）
3. 点击按钮触发文件选择（复用 `fileApi.uploadFile`）
4. 上传成功后添加到 `images` 数组
5. 在输入框上方显示图片预览（可删除）
6. 发送消息时带上 `images` 字段
7. 发送后清空 `images` 数组

**UI 设计**:
```
┌─────────────────────────────────────────┐
│ [图片预览1] [图片预览2] [图片预览3] [x]  │  ← 最多3张，可删除
├─────────────────────────────────────────┤
│ 输入消息...                    [📎] [发送] │  ← 📎 是图片上传按钮
└─────────────────────────────────────────┘
```

### Step 2: 更新 chatStore 发送逻辑

**文件**: `frontend/admin-web/src/store/chat.ts`

**改动**:
- `sendMessage` action 接受 `images?: string[]` 参数
- 调用 `/api/chat/send` 时带上 `images` 字段

### Step 3: 消息列表显示图片

**文件**: `frontend/admin-web/src/components/chat/MessageList.tsx`

**改动**:
- 检查消息的 `images` 字段
- 如果存在，在消息气泡中显示图片网格
- 点击图片可预览大图

### Step 4: 后端 system prompt 更新（可选）

**文件**: `backend/ai-agent-service/app/agents/mibao.py`

**改动**:
- 在 system prompt 中说明米宝支持图片理解
- 示例："您可以上传商品图片，我会帮您识别商品信息并创建商品记录"

## 技术细节

### 前端上传流程

```typescript
// 1. 用户选择文件
const handleImageSelect = async (files: FileList) => {
  for (const file of Array.from(files)) {
    // 2. 上传到 OSS
    const res = await fileApi.uploadFile(file, 'chat-images')
    const imageUrl = res.data.data.url
    
    // 3. 添加到预览列表
    setImages(prev => [...prev, imageUrl])
  }
}

// 4. 发送消息时带上 images
const handleSend = async () => {
  await chatStore.sendMessage(message, images)
  setImages([])  // 清空
}
```

### 后端处理流程（已实现）

```python
# chat.py line 540-548
if images:
    user_message_content = [
        {"type": "text", "text": request.message}
    ]
    for img_url in images:
        user_message_content.append({
            "type": "image_url",
            "image_url": {"url": img_url}
        })

# llm/router.py line 83-84
if has_vision and settings.DASHSCOPE_VISION_ENABLED:
    return settings.DASHSCOPE_VISION_MODEL  # qwen3.6-plus
```

## 验收标准

1. ✅ 用户可以在聊天输入框上传图片（最多3张）
2. ✅ 图片上传后在输入框上方显示预览，可删除
3. ✅ 发送消息时图片随文本一起发送到后端
4. ✅ 米宝能够识别图片内容并给出智能回复
5. ✅ 历史消息中的图片能够正确显示
6. ✅ 图片上传失败时有友好提示

## 风险与注意事项

1. **文件大小限制**: 后端 `OssService` 限制 5MB，前端需提前校验
2. **图片格式**: 仅支持 jpg/png/webp/gif
3. **并发上传**: 多图上传时显示进度条
4. **Vision model 成本**: qwen3.6-plus 比 qwen-turbo 贵，但视觉能力强
5. **历史消息兼容**: 旧消息没有 images 字段，需要容错处理

## 测试计划

1. **单元测试**: 
   - MessageInput 组件的图片上传/删除逻辑
   - chatStore.sendMessage 带 images 参数

2. **集成测试**:
   - 上传图片 → 发送消息 → 验证后端收到 images 字段
   - Vision model 正确识别图片内容

3. **E2E 测试**:
   - 用户上传图片问"这是什么商品？" → 米宝回答商品信息
   - 用户上传订单截图 → 米宝提取订单信息

## 后续扩展（不在本次范围）

- 拖拽图片到聊天框直接上传
- 图片粘贴上传（Ctrl+V）
- 图片编辑（裁剪、标注）
- 批量图片处理（一次上传10张商品图）
