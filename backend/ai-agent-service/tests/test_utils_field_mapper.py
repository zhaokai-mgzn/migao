"""app/utils/field_mapper.py 单元测试（issue #2430，utils 域跨服务字段映射）

覆盖：
- java_to_python / python_to_java 双向映射 + 未知字段原样保留 + 自定义 mapping
- get_price 优先 price 回退 basePrice（含 price=0 的 `or` 链语义）
- get_main_image 优先 mainImage 回退 main_image 回退 images[0]
- get_category_id 优先 categoryId 回退 category_id
"""
# case_ids: UT-001

from app.utils.field_mapper import FieldMapper


class TestJavaToPython:
    def test_basic_mapping(self):
        data = {
            "basePrice": 99.9,
            "mainImage": "http://img.jpg",
            "categoryId": "c1",
            "orderNo": "O1",
        }
        assert FieldMapper.java_to_python(data) == {
            "price": 99.9,
            "main_image": "http://img.jpg",
            "category_id": "c1",
            "order_no": "O1",
        }

    def test_unknown_key_passthrough(self):
        result = FieldMapper.java_to_python({"unknownField": "val", "createdAt": "2026"})
        assert result["unknownField"] == "val"
        assert result["created_at"] == "2026"

    def test_custom_mapping(self):
        assert FieldMapper.java_to_python({"a": 1}, mapping={"a": "b"}) == {"b": 1}


class TestPythonToJava:
    def test_basic_mapping(self):
        result = FieldMapper.python_to_java({"price": 99.9, "main_image": "img"})
        assert result == {"basePrice": 99.9, "mainImage": "img"}

    def test_unknown_key_passthrough(self):
        assert FieldMapper.python_to_java({"x": 1}) == {"x": 1}

    def test_custom_mapping(self):
        assert FieldMapper.python_to_java({"b": 2}, mapping={"b": "a"}) == {"a": 2}


class TestGetPrice:
    def test_prefers_price(self):
        assert FieldMapper.get_price({"price": 10.0, "basePrice": 20.0}) == 10.0

    def test_falls_back_to_base_price(self):
        assert FieldMapper.get_price({"basePrice": 20.0}) == 20.0

    def test_price_zero_falls_back_to_base_price(self):
        # `or` 链语义：price=0 视为缺失，回退 basePrice
        assert FieldMapper.get_price({"price": 0.0, "basePrice": 20.0}) == 20.0

    def test_none_when_missing(self):
        assert FieldMapper.get_price({}) is None


class TestGetMainImage:
    def test_prefers_main_image_camel(self):
        assert FieldMapper.get_main_image({"mainImage": "a.jpg"}) == "a.jpg"

    def test_falls_back_to_main_image_snake(self):
        assert FieldMapper.get_main_image({"main_image": "b.jpg"}) == "b.jpg"

    def test_falls_back_to_images_first(self):
        assert FieldMapper.get_main_image({"images": ["first.jpg", "second.jpg"]}) == "first.jpg"

    def test_empty_images_returns_none(self):
        assert FieldMapper.get_main_image({"images": []}) is None

    def test_none_when_missing(self):
        assert FieldMapper.get_main_image({}) is None


class TestGetCategoryId:
    def test_prefers_category_id_camel(self):
        assert FieldMapper.get_category_id({"categoryId": "c1", "category_id": "c2"}) == "c1"

    def test_falls_back_to_snake(self):
        assert FieldMapper.get_category_id({"category_id": "c2"}) == "c2"

    def test_none_when_missing(self):
        assert FieldMapper.get_category_id({}) is None
