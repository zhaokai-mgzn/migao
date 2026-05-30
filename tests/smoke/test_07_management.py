"""
管理模块 API 冒烟测试 (P1)

覆盖无外部依赖的管理后台 CRUD 模块：
- 商品分类管理 (/api/admin/categories)
- 加工分类管理 (/api/admin/processing-categories)
- 角色管理 (/api/admin/roles)
- 快速回复模板 (/api/admin/quick-replies)
"""

import time

import pytest

from .helpers import SmokeTestClient, assert_success_response


def _unique_suffix() -> str:
    """生成唯一后缀，避免并发测试冲突"""
    return str(int(time.time() * 1000))


def _extract_data(resp):
    """从统一响应包装中提取 data 字段"""
    body = resp.json()
    return body.get("data", body)


@pytest.mark.p1
@pytest.mark.business
class TestCategoryAPI:
    """商品分类管理 API 测试"""

    def test_create_category(self, authed_admin_client: SmokeTestClient):
        """创建分类，验证返回 id 和 name"""
        suffix = _unique_suffix()
        payload = {
            "name": f"smoke测试分类_{suffix}",
            "level": 1,
            "sortOrder": 999,
            "status": "active",
        }
        resp = authed_admin_client.post("/api/admin/categories", json=payload)
        if resp.status_code == 404:
            pytest.skip("分类创建接口不存在")
        assert resp.status_code in (200, 201), (
            f"创建分类失败: status={resp.status_code}, body={resp.text[:300]}"
        )
        assert_success_response(resp, resp.status_code)
        data = _extract_data(resp)
        assert data.get("id") is not None, f"创建分类未返回 id: {data}"
        assert data.get("name") == payload["name"], (
            f"创建分类 name 不一致: 返回={data.get('name')}, 期望={payload['name']}"
        )

        # 清理
        category_id = data.get("id")
        if category_id:
            authed_admin_client.delete(f"/api/admin/categories/{category_id}")

    def test_list_categories(self, authed_admin_client: SmokeTestClient):
        """获取分类列表，验证返回数组结构"""
        resp = authed_admin_client.get("/api/admin/categories")
        if resp.status_code == 404:
            pytest.skip("分类列表接口不存在")
        assert resp.status_code == 200, (
            f"分类列表查询失败: status={resp.status_code}"
        )
        data = _extract_data(resp)
        # 分类列表可能是数组或分页
        if isinstance(data, dict):
            records = data.get("records", data.get("items", data.get("list", [])))
            assert isinstance(records, list), f"分类列表结构异常: {list(data.keys())}"
        else:
            assert isinstance(data, list), f"期望分类列表为数组，实际: {type(data)}"

    def test_category_tree(self, authed_admin_client: SmokeTestClient):
        """获取分类树形结构"""
        resp = authed_admin_client.get("/api/admin/categories/tree")
        if resp.status_code == 404:
            pytest.skip("分类树接口不存在")
        assert resp.status_code == 200, (
            f"分类树查询失败: status={resp.status_code}"
        )
        data = _extract_data(resp)
        assert isinstance(data, list), f"分类树应为数组，实际: {type(data)}"
        # 若有数据，校验包含基本字段
        if data:
            first = data[0]
            assert isinstance(first, dict), "分类树节点应为对象"
            assert "id" in first or "name" in first, (
                f"分类树节点缺少基础字段: {list(first.keys())}"
            )

    def test_update_category(self, authed_admin_client: SmokeTestClient):
        """更新分类名称"""
        suffix = _unique_suffix()
        # 先创建一个分类
        create_resp = authed_admin_client.post("/api/admin/categories", json={
            "name": f"smoke待更新_{suffix}",
            "level": 1,
            "sortOrder": 999,
            "status": "active",
        })
        if create_resp.status_code == 404:
            pytest.skip("分类创建接口不存在，跳过更新测试")
        if create_resp.status_code not in (200, 201):
            pytest.skip(f"前置创建失败: {create_resp.status_code}")

        category_id = _extract_data(create_resp).get("id")
        assert category_id, "前置创建未返回 id"

        try:
            new_name = f"smoke已更新_{suffix}"
            update_resp = authed_admin_client.put(
                f"/api/admin/categories/{category_id}",
                json={"name": new_name, "status": "active"},
            )
            assert update_resp.status_code == 200, (
                f"更新分类失败: status={update_resp.status_code}, body={update_resp.text[:300]}"
            )
            data = _extract_data(update_resp)
            assert data.get("name") == new_name, (
                f"更新后 name 不一致: 返回={data.get('name')}, 期望={new_name}"
            )
        finally:
            authed_admin_client.delete(f"/api/admin/categories/{category_id}")

    def test_delete_category(self, authed_admin_client: SmokeTestClient):
        """删除分类（可能因关联数据失败，验证非 5xx 即可）"""
        suffix = _unique_suffix()
        create_resp = authed_admin_client.post("/api/admin/categories", json={
            "name": f"smoke待删除_{suffix}",
            "level": 1,
            "sortOrder": 999,
            "status": "active",
        })
        if create_resp.status_code == 404:
            pytest.skip("分类创建接口不存在，跳过删除测试")
        if create_resp.status_code not in (200, 201):
            pytest.skip(f"前置创建失败: {create_resp.status_code}")

        category_id = _extract_data(create_resp).get("id")
        assert category_id, "前置创建未返回 id"

        del_resp = authed_admin_client.delete(f"/api/admin/categories/{category_id}")
        # 业务校验：删除接口不应抛 5xx；4xx 可能因关联数据导致，是预期
        assert del_resp.status_code < 500, (
            f"删除分类出现服务端错误: status={del_resp.status_code}, body={del_resp.text[:300]}"
        )


@pytest.mark.p1
@pytest.mark.business
class TestProcessingCategoryAPI:
    """加工分类管理 API 测试"""

    def _create_one(self, client: SmokeTestClient, suffix: str):
        return client.post("/api/admin/processing-categories", json={
            "name": f"smoke加工_{suffix}",
            "sortOrder": 999,
            "status": "active",
        })

    def test_create_processing_category(self, authed_admin_client: SmokeTestClient):
        """创建加工分类"""
        suffix = _unique_suffix()
        resp = self._create_one(authed_admin_client, suffix)
        if resp.status_code == 404:
            pytest.skip("加工分类创建接口不存在")
        assert resp.status_code in (200, 201), (
            f"创建加工分类失败: status={resp.status_code}, body={resp.text[:300]}"
        )
        data = _extract_data(resp)
        assert data.get("id") is not None, f"创建加工分类未返回 id: {data}"
        assert data.get("name") == f"smoke加工_{suffix}", (
            f"创建加工分类 name 不一致: {data}"
        )

        # 清理
        authed_admin_client.delete(f"/api/admin/processing-categories/{data['id']}")

    def test_list_processing_categories(self, authed_admin_client: SmokeTestClient):
        """获取加工分类列表"""
        resp = authed_admin_client.get("/api/admin/processing-categories")
        if resp.status_code == 404:
            pytest.skip("加工分类列表接口不存在")
        assert resp.status_code == 200, (
            f"加工分类列表查询失败: status={resp.status_code}"
        )
        data = _extract_data(resp)
        if isinstance(data, dict):
            records = data.get("records", data.get("items", data.get("list", [])))
            assert isinstance(records, list)
        else:
            assert isinstance(data, list), f"期望数组，实际: {type(data)}"

    def test_update_processing_category(self, authed_admin_client: SmokeTestClient):
        """更新加工分类"""
        suffix = _unique_suffix()
        create_resp = self._create_one(authed_admin_client, suffix)
        if create_resp.status_code == 404:
            pytest.skip("加工分类创建接口不存在")
        if create_resp.status_code not in (200, 201):
            pytest.skip(f"前置创建失败: {create_resp.status_code}")

        cat_id = _extract_data(create_resp).get("id")
        assert cat_id, "前置创建未返回 id"

        try:
            new_name = f"smoke加工已更新_{suffix}"
            update_resp = authed_admin_client.put(
                f"/api/admin/processing-categories/{cat_id}",
                json={"name": new_name, "status": "active"},
            )
            assert update_resp.status_code == 200, (
                f"更新加工分类失败: status={update_resp.status_code}, body={update_resp.text[:300]}"
            )
            data = _extract_data(update_resp)
            assert data.get("name") == new_name, (
                f"更新后 name 不一致: {data}"
            )
        finally:
            authed_admin_client.delete(f"/api/admin/processing-categories/{cat_id}")

    def test_delete_processing_category(self, authed_admin_client: SmokeTestClient):
        """删除加工分类"""
        suffix = _unique_suffix()
        create_resp = self._create_one(authed_admin_client, suffix)
        if create_resp.status_code == 404:
            pytest.skip("加工分类创建接口不存在")
        if create_resp.status_code not in (200, 201):
            pytest.skip(f"前置创建失败: {create_resp.status_code}")

        cat_id = _extract_data(create_resp).get("id")
        assert cat_id, "前置创建未返回 id"

        del_resp = authed_admin_client.delete(
            f"/api/admin/processing-categories/{cat_id}"
        )
        assert del_resp.status_code < 500, (
            f"删除加工分类出现服务端错误: status={del_resp.status_code}, body={del_resp.text[:300]}"
        )


@pytest.mark.p1
@pytest.mark.business
class TestRoleAPI:
    """角色管理 API 测试"""

    def test_list_roles(self, authed_admin_client: SmokeTestClient):
        """获取角色列表"""
        resp = authed_admin_client.get("/api/admin/roles", params={
            "page": 1,
            "size": 20,
        })
        if resp.status_code == 404:
            pytest.skip("角色列表接口不存在")
        assert resp.status_code == 200, (
            f"角色列表查询失败: status={resp.status_code}, body={resp.text[:300]}"
        )
        data = _extract_data(resp)
        if isinstance(data, dict):
            records = data.get("records", data.get("items", data.get("list", [])))
            assert isinstance(records, list), f"角色列表结构异常: {list(data.keys())}"
        else:
            assert isinstance(data, list), f"期望角色列表为数组，实际: {type(data)}"

    def test_create_role(self, authed_admin_client: SmokeTestClient):
        """创建角色（如 API 支持）"""
        suffix = _unique_suffix()
        payload = {
            "name": f"smoke角色_{suffix}",
            "code": f"SMOKE_ROLE_{suffix}",
            "description": "smoke 测试创建的临时角色",
            "permissionIds": [],
        }
        resp = authed_admin_client.post("/api/admin/roles", json=payload)
        if resp.status_code == 404:
            pytest.skip("角色创建接口不存在")
        if resp.status_code in (401, 403):
            pytest.skip(f"创建角色需更高权限: status={resp.status_code}")
        assert resp.status_code in (200, 201), (
            f"创建角色失败: status={resp.status_code}, body={resp.text[:300]}"
        )
        data = _extract_data(resp)
        assert data.get("id") is not None, f"创建角色未返回 id: {data}"

        # 清理
        role_id = data.get("id")
        if role_id:
            authed_admin_client.delete(f"/api/admin/roles/{role_id}")


@pytest.mark.p1
@pytest.mark.business
class TestQuickReplyAPI:
    """快速回复模板 API 测试"""

    def _create_one(self, client: SmokeTestClient, suffix: str):
        return client.post("/api/admin/quick-replies", json={
            "category": "smoke测试",
            "title": f"smoke快回_{suffix}",
            "content": f"这是 smoke 测试创建的快捷回复内容 {suffix}",
            "shortcut": f"/smk{suffix[-4:]}",
            "isPublic": True,
        })

    def test_create_quick_reply(self, authed_admin_client: SmokeTestClient):
        """创建快速回复"""
        suffix = _unique_suffix()
        resp = self._create_one(authed_admin_client, suffix)
        if resp.status_code == 404:
            pytest.skip("快速回复创建接口不存在")
        assert resp.status_code in (200, 201), (
            f"创建快速回复失败: status={resp.status_code}, body={resp.text[:300]}"
        )
        data = _extract_data(resp)
        assert data.get("id") is not None, f"创建快速回复未返回 id: {data}"
        assert data.get("title") == f"smoke快回_{suffix}", (
            f"创建快速回复 title 不一致: {data}"
        )

        # 清理
        authed_admin_client.delete(f"/api/admin/quick-replies/{data['id']}")

    def test_list_quick_replies(self, authed_admin_client: SmokeTestClient):
        """获取快速回复列表"""
        resp = authed_admin_client.get("/api/admin/quick-replies", params={
            "page": 1,
            "size": 20,
        })
        if resp.status_code == 404:
            pytest.skip("快速回复列表接口不存在")
        assert resp.status_code == 200, (
            f"快速回复列表查询失败: status={resp.status_code}"
        )
        data = _extract_data(resp)
        if isinstance(data, dict):
            records = data.get("records", data.get("items", data.get("list", [])))
            assert isinstance(records, list), (
                f"快速回复列表结构异常: {list(data.keys())}"
            )
        else:
            assert isinstance(data, list), f"期望数组，实际: {type(data)}"

    def test_update_quick_reply(self, authed_admin_client: SmokeTestClient):
        """更新快速回复"""
        suffix = _unique_suffix()
        create_resp = self._create_one(authed_admin_client, suffix)
        if create_resp.status_code == 404:
            pytest.skip("快速回复创建接口不存在")
        if create_resp.status_code not in (200, 201):
            pytest.skip(f"前置创建失败: {create_resp.status_code}")

        reply_id = _extract_data(create_resp).get("id")
        assert reply_id, "前置创建未返回 id"

        try:
            new_title = f"smoke快回已更新_{suffix}"
            update_resp = authed_admin_client.put(
                f"/api/admin/quick-replies/{reply_id}",
                json={
                    "category": "smoke测试",
                    "title": new_title,
                    "content": "已更新的快速回复内容",
                    "isPublic": True,
                },
            )
            assert update_resp.status_code == 200, (
                f"更新快速回复失败: status={update_resp.status_code}, "
                f"body={update_resp.text[:300]}"
            )
            data = _extract_data(update_resp)
            assert data.get("title") == new_title, (
                f"更新后 title 不一致: {data}"
            )
        finally:
            authed_admin_client.delete(f"/api/admin/quick-replies/{reply_id}")

    def test_delete_quick_reply(self, authed_admin_client: SmokeTestClient):
        """删除快速回复"""
        suffix = _unique_suffix()
        create_resp = self._create_one(authed_admin_client, suffix)
        if create_resp.status_code == 404:
            pytest.skip("快速回复创建接口不存在")
        if create_resp.status_code not in (200, 201):
            pytest.skip(f"前置创建失败: {create_resp.status_code}")

        reply_id = _extract_data(create_resp).get("id")
        assert reply_id, "前置创建未返回 id"

        del_resp = authed_admin_client.delete(f"/api/admin/quick-replies/{reply_id}")
        assert del_resp.status_code in (200, 204), (
            f"删除快速回复失败: status={del_resp.status_code}, body={del_resp.text[:300]}"
        )
