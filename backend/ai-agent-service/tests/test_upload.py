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
    def test_valid_with_extension(self):
        _validate_image_file(_file("image/png", "photo.png"))

    def test_invalid_extension(self):
        with pytest.raises(HTTPException) as e:
            _validate_image_file(_file("image/png", "photo.exe"))
        assert e.value.status_code == 400
        assert e.value.detail["error"]["code"] == "INVALID_FILE_EXTENSION"

    def test_empty_extension_passthrough(self):
        _validate_image_file(_file("image/png", "photo"))

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
