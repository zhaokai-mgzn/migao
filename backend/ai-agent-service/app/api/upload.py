"""
图片上传 API 路由

提供聊天场景的图片上传接口：
- POST /upload-image: 上传聊天图片（代理转发到 admin-api）

支持：
- 单次最多 3 张图片
- 仅接受图片类型（jpg, jpeg, png, gif, webp）
- 单张最大 5MB
- 按 tenant_id 隔离存储路径
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from loguru import logger
import httpx

from app.config import settings
from app.utils.auth import get_current_user, UserIdentity

router = APIRouter()

# 允许的图片 MIME 类型
ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/bmp",
}

# 允许的文件扩展名
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

# 单张图片最大 5MB
MAX_IMAGE_SIZE = 5 * 1024 * 1024

# 单次最多上传 3 张
MAX_FILES_PER_REQUEST = 3

# 图片文件头签名
IMAGE_SIGNATURES = {
    b'\xff\xd8\xff': 'image/jpeg',           # JPEG
    b'\x89PNG\r\n\x1a\n': 'image/png',       # PNG
    b'GIF87a': 'image/gif',                    # GIF87a
    b'GIF89a': 'image/gif',                    # GIF89a
    b'BM': 'image/bmp',                        # BMP
    # WebP: RIFF....WEBP（单独处理）
}


def _sniff_image_type(content: bytes) -> Optional[str]:
    """通过文件头 magic number 检测图片类型"""
    for signature, mime_type in IMAGE_SIGNATURES.items():
        if content[:len(signature)] == signature:
            return mime_type
    # WebP 特殊检测: RIFF????WEBP
    if content[:4] == b'RIFF' and content[8:12] == b'WEBP':
        return 'image/webp'
    return None


def _validate_image_file(file: UploadFile) -> None:
    """校验上传的图片文件"""
    # 校验 MIME 类型
    content_type = file.content_type or ""
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": {
                    "code": "INVALID_FILE_TYPE",
                    "message": f"不支持的文件类型: {content_type}，仅支持 JPG、PNG、GIF、WebP 格式",
                },
            },
        )

    # 校验扩展名
    filename = file.filename or ""
    ext = ""
    if "." in filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower()
    if ext and ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": {
                    "code": "INVALID_FILE_EXTENSION",
                    "message": f"不支持的文件扩展名: {ext}",
                },
            },
        )


async def _check_file_size(file: UploadFile) -> bytes:
    """读取文件内容并校验大小"""
    content = await file.read()
    if len(content) > MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": {
                    "code": "FILE_TOO_LARGE",
                    "message": f"文件大小超过限制（最大 5MB），当前: {len(content) / 1024 / 1024:.1f}MB",
                },
            },
        )
    return content


@router.post("/upload-image")
async def upload_chat_image(
    files: List[UploadFile] = File(..., description="图片文件（最多3张）"),
    user: UserIdentity = Depends(get_current_user),
):
    """
    上传聊天图片

    将图片代理转发到 admin-api 的文件上传接口，按 tenant_id 隔离存储。

    - 最多同时上传 3 张
    - 仅接受图片类型（jpg, jpeg, png, gif, webp）
    - 单张最大 5MB

    返回格式：
    ```json
    {
        "success": true,
        "data": {
            "files": [
                {"id": "file_id", "url": "https://..."}
            ]
        }
    }
    ```
    """
    # 校验文件数量
    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": {
                    "code": "TOO_MANY_FILES",
                    "message": f"单次最多上传 {MAX_FILES_PER_REQUEST} 张图片，当前: {len(files)} 张",
                },
            },
        )

    if not files:
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": {
                    "code": "NO_FILE",
                    "message": "请选择要上传的图片",
                },
            },
        )

    # 校验每个文件
    for file in files:
        _validate_image_file(file)

    # 按 tenant_id 构建隔离的存储目录
    directory = f"chat/{user.tenant_id}"

    uploaded_files = []

    async with httpx.AsyncClient(
        base_url=settings.ADMIN_API_BASE_URL,
        timeout=httpx.Timeout(30.0),
    ) as client:
        for file in files:
            # 读取文件内容并校验大小
            content = await _check_file_size(file)

            # 校验文件头 magic number
            sniffed_type = _sniff_image_type(content)
            declared_type = file.content_type or "image/jpeg"
            if sniffed_type is None or sniffed_type != declared_type:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "success": False,
                        "error": {
                            "code": "FILE_CONTENT_MISMATCH",
                            "message": "文件内容与声明类型不匹配",
                        },
                    },
                )

            # 构建 multipart 请求转发到 admin-api
            multipart_files = {
                "file": (file.filename or "image.jpg", content, file.content_type or "image/jpeg"),
            }
            multipart_data = {
                "directory": directory,
            }

            headers = {}
            if settings.SERVICE_TOKEN:
                headers["X-Service-Token"] = settings.SERVICE_TOKEN
            headers["X-Tenant-Id"] = str(user.tenant_id)
            if user.user_id:
                headers["X-User-Id"] = user.user_id

            try:
                response = await client.post(
                    "/api/admin/files/upload",
                    files=multipart_files,
                    data=multipart_data,
                    headers=headers,
                )
                response.raise_for_status()
                result = response.json()

                if result.get("success") and result.get("data"):
                    file_info = result["data"]
                    uploaded_files.append({
                        "id": file_info.get("id"),
                        "url": file_info.get("url"),
                        "name": file_info.get("name"),
                        "size": file_info.get("size"),
                    })
                else:
                    error_msg = result.get("error", {}).get("message", "上传失败")
                    logger.error(f"Admin API upload failed: {error_msg}")
                    raise HTTPException(
                        status_code=502,
                        detail={
                            "success": False,
                            "error": {
                                "code": "UPLOAD_PROXY_ERROR",
                                "message": f"图片上传失败: {error_msg}",
                            },
                        },
                    )

            except httpx.HTTPStatusError as e:
                logger.error(
                    f"Admin API upload HTTP error: status={e.response.status_code}, "
                    f"body={e.response.text}"
                )
                raise HTTPException(
                    status_code=502,
                    detail={
                        "success": False,
                        "error": {
                            "code": "UPLOAD_PROXY_ERROR",
                            "message": "图片上传服务暂时不可用",
                        },
                    },
                )
            except httpx.RequestError as e:
                logger.error(f"Admin API upload connection error: {e}")
                raise HTTPException(
                    status_code=502,
                    detail={
                        "success": False,
                        "error": {
                            "code": "UPLOAD_SERVICE_UNAVAILABLE",
                            "message": "图片上传服务连接失败",
                        },
                    },
                )

    logger.info(
        f"Chat image upload success: tenant_id={user.tenant_id}, "
        f"user_id={user.user_id}, count={len(uploaded_files)}"
    )

    return {
        "success": True,
        "data": {
            "files": uploaded_files,
        },
    }
