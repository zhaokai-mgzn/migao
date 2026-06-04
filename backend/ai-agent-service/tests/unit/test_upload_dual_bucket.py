"""
测试双 Bucket 路由逻辑

验证 ai-agent-service 上传时使用正确的 directory 前缀，
确保 admin-api 能够正确路由到临时或永久 Bucket。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import UploadFile
import io

from app.api.upload import upload_chat_image
from app.utils.auth import UserIdentity, UserRole


@pytest.fixture
def mock_user():
    """创建模拟用户"""
    return UserIdentity(
        user_id="user-123",
        tenant_id=456,  # tenant_id 必须是整数
        identity_type="wechat_mini",
        role=UserRole.CUSTOMER,
        external_id="wx-openid-789"
    )


@pytest.fixture
def mock_upload_file():
    """创建模拟上传文件"""
    # JPEG 文件头 magic number
    jpeg_content = b'\xff\xd8\xff\xe0' + b'fake image data' * 100
    file = UploadFile(
        filename="test.jpg",
        file=io.BytesIO(jpeg_content),
        headers={"content-type": "image/jpeg"}
    )
    return file


@pytest.mark.asyncio
async def test_upload_chat_image_uses_chat_directory(mock_user, mock_upload_file):
    """
    测试上传聊天图片时使用 chat/{tenant_id} 目录

    这个目录前缀会让 admin-api 的 OssService.selectBucket() 选择临时 Bucket，
    实现 7 天自动删除的生命周期策略。
    """
    with patch('app.api.upload.settings') as mock_settings, \
         patch('app.api.upload.httpx.AsyncClient') as mock_client_class:

        # 配置 mock
        mock_settings.ADMIN_API_BASE_URL = "http://localhost:8080"
        mock_settings.SERVICE_TOKEN = "test-token"

        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client

        # 模拟 admin-api 响应
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "success": True,
            "data": {
                "id": "file-123",
                "url": "https://example.com/chat/tenant-456/image.jpg",
                "name": "test.jpg",
                "size": 1024
            }
        }
        mock_client.post.return_value = mock_response

        # 执行上传
        result = await upload_chat_image(
            files=[mock_upload_file],
            user=mock_user
        )

        # 验证调用了 admin-api
        assert mock_client.post.called
        call_args = mock_client.post.call_args

        # 验证 directory 参数使用 chat/ 前缀
        assert "data" in call_args.kwargs
        assert call_args.kwargs["data"]["directory"] == f"chat/{mock_user.tenant_id}"

        # 验证返回结果
        assert result["success"] is True
        assert len(result["data"]["files"]) == 1


@pytest.mark.asyncio
async def test_upload_chat_image_directory_format(mock_user, mock_upload_file):
    """
    测试 directory 格式严格遵循 chat/{tenant_id} 规范

    确保 admin-api 能够正确识别并路由到临时 Bucket。
    """
    with patch('app.api.upload.settings') as mock_settings, \
         patch('app.api.upload.httpx.AsyncClient') as mock_client_class:

        mock_settings.ADMIN_API_BASE_URL = "http://localhost:8080"
        mock_settings.SERVICE_TOKEN = "test-token"

        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "success": True,
            "data": {
                "id": "file-123",
                "url": f"https://example.com/chat/{mock_user.tenant_id}/image.jpg",
                "name": "test.jpg",
                "size": 1024
            }
        }
        mock_client.post.return_value = mock_response

        await upload_chat_image(files=[mock_upload_file], user=mock_user)

        # 提取实际调用的 directory
        call_args = mock_client.post.call_args
        directory = call_args.kwargs["data"]["directory"]

        # 验证格式（tenant_id 是整数，会自动转换为字符串）
        assert directory.startswith("chat/")
        assert str(mock_user.tenant_id) in directory
        assert directory == f"chat/{mock_user.tenant_id}"


def test_bucket_routing_logic():
    """
    测试 Bucket 路由逻辑（与 admin-api OssService.selectBucket 保持一致）

    这个测试验证 directory 前缀与 Bucket 选择的映射关系：
    - chat/ -> 临时 Bucket（7 天自动删除）
    - 其他 -> 永久 Bucket
    """
    def select_bucket(directory: str) -> str:
        """模拟 admin-api 的 OssService.selectBucket()"""
        if directory and directory.startswith("chat/"):
            return "temporary-bucket"
        return "permanent-bucket"

    # 测试聊天图片路由到临时 Bucket
    assert select_bucket("chat/tenant-123") == "temporary-bucket"
    assert select_bucket("chat/tenant-456/session-789") == "temporary-bucket"

    # 测试其他目录路由到永久 Bucket
    assert select_bucket("products/123") == "permanent-bucket"
    assert select_bucket("avatars/user-456") == "permanent-bucket"
    assert select_bucket("documents/789") == "permanent-bucket"
    assert select_bucket("") == "permanent-bucket"
    assert select_bucket(None) == "permanent-bucket"
