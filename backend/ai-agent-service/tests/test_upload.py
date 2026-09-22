"""app/api/upload.py 单元测试 — 聊天图片上传校验与代理转发。

覆盖：magic number 嗅探、MIME/扩展名白名单、数量/大小限制、按 tenant_id
隔离目录、admin-api 代理转发成功/失败（HTTPStatusError/RequestError）。
"""
# case_ids: API-009

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

from app.api.upload import (
    _sniff_image_type,
    _validate_image_file,
    _check_file_size,
    upload_chat_image,
)
from app.utils.auth import UserIdentity


def _user(tenant_id=1, user_id="user_1"):
    return UserIdentity(
        user_id=user_id, tenant_id=tenant_id,
        identity_type="wechat_mini", role="customer",
    )


def _file(content_type, filename, content=b"\x00"):
    f = MagicMock()
    f.content_type = content_type
    f.filename = filename
    f.read = AsyncMock(return_value=content)
    return f


class TestSniffImageType:
    def test_bmp(self):
        assert _sniff_image_type(b"BM\x00\x00\x00\x00") == "image/bmp"

    def test_gif87a(self):
        assert _sniff_image_type(b"GIF87a\x00\x00") == "image/gif"

    def test_webp_mismatch_short(self):
        assert _sniff_image_type(b"RIFF\x00\x00\x00\x00AVI ") is None


class TestValidateImageFile:
    """`_validate_image_file` 的成功路径**没有返回值**（返回 None）⇒ 只写「调用不抛异常」= 空断言。

    真断言只能施加在**可观察后果**上：① 走通完整上传链路（证明它真的放行，而非被别处拦住）；
    ② 扩展名白名单**大小写不敏感**（`.PNG` 归一后放行 / `.PNGX` 仍拒）；③ 无扩展名靠 MIME 放行。
    """

    @pytest.mark.asyncio
    async def test_valid_with_extension(self):
        """合法扩展名 ⇒ 校验放行，且**真的走到了代理转发**（不是「没抛异常」）。"""
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
        f = _file("image/png", "photo.png", png)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={
            "success": True, "data": {"id": "f1", "url": "https://oss/photo.png"},
        })
        client = MagicMock()
        client.post = AsyncMock(return_value=resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.api.upload.httpx.AsyncClient", return_value=client):
            result = await upload_chat_image(files=[f], user=_user(tenant_id=3))

        assert result["success"] is True
        assert result["data"]["files"] == [
            {"id": "f1", "url": "https://oss/photo.png", "name": None, "size": None}
        ], "合法扩展名必须真的被转发到 admin-api 并回填 id/url"
        # 转发时用的文件名/类型逐字透传（证明扩展名没被改写或丢掉）
        assert client.post.call_args.kwargs["files"]["file"][0] == "photo.png"
        assert client.post.call_args.kwargs["files"]["file"][2] == "image/png"

    def test_extension_whitelist_is_case_insensitive(self):
        """`.PNG` 大写扩展名 ⇒ 归一后放行；`.PNGX` ⇒ 仍按 INVALID_FILE_EXTENSION 拒（只收窄不放宽）。"""
        _validate_image_file(_file("image/png", "PHOTO.PNG"))  # 不抛 = 归一化生效
        with pytest.raises(HTTPException) as e:
            _validate_image_file(_file("image/png", "photo.pngx"))
        assert e.value.detail["error"]["code"] == "INVALID_FILE_EXTENSION"
        assert e.value.detail["error"]["message"] == "不支持的文件扩展名: .pngx", (
            "错误信息必须带上**归一后**的扩展名（小写 + 带点）"
        )

    @pytest.mark.asyncio
    async def test_empty_extension_passthrough(self):
        """无扩展名（`photo`）⇒ 扩展名校验**跳过**、由 MIME 放行，并真的走到代理转发。

        这是有意的设计（客户端可能传无扩展名文件）：判据不是「没抛异常」，
        而是「扩展名缺失**不构成**拒绝理由，且内容嗅探仍生效」。
        """
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
        f = _file("image/png", "photo", png)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"success": True, "data": {"id": "f2", "url": "u2"}})
        client = MagicMock()
        client.post = AsyncMock(return_value=resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.api.upload.httpx.AsyncClient", return_value=client):
            result = await upload_chat_image(files=[f], user=_user(tenant_id=3))

        assert result["success"] is True
        assert [x["id"] for x in result["data"]["files"]] == ["f2"]
        assert client.post.call_args.kwargs["files"]["file"][0] == "photo", (
            "无扩展名文件名必须原样透传（不得被补成 .jpg 之类）"
        )

    def test_empty_extension_still_subject_to_mime_whitelist(self):
        """无扩展名**不等于**免检：MIME 不在白名单 ⇒ 仍 400 INVALID_FILE_TYPE。"""
        with pytest.raises(HTTPException) as e:
            _validate_image_file(_file("application/octet-stream", "photo"))
        assert e.value.detail["error"]["code"] == "INVALID_FILE_TYPE"

    def test_invalid_extension(self):
        with pytest.raises(HTTPException) as e:
            _validate_image_file(_file("image/png", "photo.exe"))
        assert e.value.status_code == 400
        assert e.value.detail["error"]["code"] == "INVALID_FILE_EXTENSION"

    def test_invalid_mime(self):
        with pytest.raises(HTTPException) as e:
            _validate_image_file(_file("application/pdf", "a.pdf"))
        assert e.value.detail["error"]["code"] == "INVALID_FILE_TYPE"


class TestCheckFileSize:
    @pytest.mark.asyncio
    async def test_too_large(self):
        big = b"\xff\xd8\xff" + b"0" * (5 * 1024 * 1024)
        f = _file("image/jpeg", "big.jpg", big)
        with pytest.raises(HTTPException) as e:
            await _check_file_size(f)
        assert e.value.detail["error"]["code"] == "FILE_TOO_LARGE"

    @pytest.mark.asyncio
    async def test_ok(self):
        f = _file("image/jpeg", "ok.jpg", b"\xff\xd8\xff\xe0")
        content = await _check_file_size(f)
        assert content == b"\xff\xd8\xff\xe0"


class TestUploadChatImageValidation:
    @pytest.mark.asyncio
    async def test_too_many_files(self):
        files = [_file("image/png", f"p{i}.png") for i in range(4)]
        with pytest.raises(HTTPException) as e:
            await upload_chat_image(files=files, user=_user())
        assert e.value.detail["error"]["code"] == "TOO_MANY_FILES"

    @pytest.mark.asyncio
    async def test_no_file(self):
        with pytest.raises(HTTPException) as e:
            await upload_chat_image(files=[], user=_user())
        assert e.value.detail["error"]["code"] == "NO_FILE"

    @pytest.mark.asyncio
    async def test_invalid_type_rejected_before_proxy(self):
        f = _file("text/plain", "a.txt", b"hello")
        with pytest.raises(HTTPException) as e:
            await upload_chat_image(files=[f], user=_user())
        assert e.value.detail["error"]["code"] == "INVALID_FILE_TYPE"


class TestUploadChatImageProxy:
    def _mock_client(self, post_result):
        client = MagicMock()
        client.post = AsyncMock(return_value=post_result)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        return client

    def _ok_response(self, payload):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=payload)
        return resp

    @pytest.mark.asyncio
    async def test_success_single_file(self):
        jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF"
        f = _file("image/jpeg", "pic.jpg", jpeg)
        resp = self._ok_response({
            "success": True,
            "data": {"id": "f1", "url": "https://oss/a.jpg", "name": "pic.jpg", "size": 4},
        })
        with patch("app.api.upload.httpx.AsyncClient", return_value=self._mock_client(resp)):
            result = await upload_chat_image(files=[f], user=_user(tenant_id=7))

        assert result["success"] is True
        files = result["data"]["files"]
        assert len(files) == 1
        assert files[0]["id"] == "f1"
        assert files[0]["url"] == "https://oss/a.jpg"

    @pytest.mark.asyncio
    async def test_tenant_directory_isolation(self):
        jpeg = b"\xff\xd8\xff\xe0"
        f = _file("image/jpeg", "pic.jpg", jpeg)
        resp = self._ok_response({"success": True, "data": {"id": "f1", "url": "u"}})
        client = self._mock_client(resp)
        with patch("app.api.upload.httpx.AsyncClient", return_value=client):
            await upload_chat_image(files=[f], user=_user(tenant_id=42))

        kwargs = client.post.call_args.kwargs
        assert kwargs["data"]["directory"] == "chat/42"
        assert kwargs["headers"]["X-Tenant-Id"] == "42"
        assert kwargs["headers"]["X-User-Id"] == "user_1"

    @pytest.mark.asyncio
    async def test_magic_number_mismatch(self):
        f = _file("image/jpeg", "pic.jpg", b"not-a-real-image")
        resp = self._ok_response({"success": True, "data": {}})
        with patch("app.api.upload.httpx.AsyncClient", return_value=self._mock_client(resp)):
            with pytest.raises(HTTPException) as e:
                await upload_chat_image(files=[f], user=_user())
        assert e.value.detail["error"]["code"] == "FILE_CONTENT_MISMATCH"

    @pytest.mark.asyncio
    async def test_http_status_error(self):
        jpeg = b"\xff\xd8\xff\xe0"
        f = _file("image/jpeg", "pic.jpg", jpeg)
        resp = MagicMock()
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("err", request=MagicMock(), response=MagicMock(status_code=500, text="boom"))
        )
        with patch("app.api.upload.httpx.AsyncClient", return_value=self._mock_client(resp)):
            with pytest.raises(HTTPException) as e:
                await upload_chat_image(files=[f], user=_user())
        assert e.value.detail["error"]["code"] == "UPLOAD_PROXY_ERROR"

    @pytest.mark.asyncio
    async def test_request_error(self):
        jpeg = b"\xff\xd8\xff\xe0"
        f = _file("image/jpeg", "pic.jpg", jpeg)
        resp = MagicMock()
        resp.raise_for_status = MagicMock(
            side_effect=httpx.RequestError("conn refused", request=MagicMock())
        )
        with patch("app.api.upload.httpx.AsyncClient", return_value=self._mock_client(resp)):
            with pytest.raises(HTTPException) as e:
                await upload_chat_image(files=[f], user=_user())
        assert e.value.detail["error"]["code"] == "UPLOAD_SERVICE_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_admin_api_returns_failure(self):
        jpeg = b"\xff\xd8\xff\xe0"
        f = _file("image/jpeg", "pic.jpg", jpeg)
        resp = self._ok_response({"success": False, "error": {"message": "存储满"}})
        with patch("app.api.upload.httpx.AsyncClient", return_value=self._mock_client(resp)):
            with pytest.raises(HTTPException) as e:
                await upload_chat_image(files=[f], user=_user())
        assert e.value.status_code == 502
        assert e.value.detail["error"]["code"] == "UPLOAD_PROXY_ERROR"
