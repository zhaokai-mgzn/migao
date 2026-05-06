"""
AI 智能客服系统 - 字段映射工具

统一处理 Java (camelCase) 和 Python (snake_case) 之间的字段映射
"""

from typing import Any, Dict, Optional


class FieldMapper:
    """字段映射器
    
    处理不同服务之间的字段命名差异
    """
    
    # Java (admin-api) -> Python (ai-agent-service) 字段映射
    JAVA_TO_PYTHON = {
        # 商品相关
        "basePrice": "price",
        "mainImage": "main_image",
        "categoryId": "category_id",
        "createdAt": "created_at",
        "updatedAt": "updated_at",
        "tenantId": "tenant_id",
        "userId": "user_id",
        "orderId": "order_id",
        "orderNo": "order_no",
        "customerId": "customer_id",
        "productId": "product_id",
    }
    
    # Python -> Java 字段映射（反向）
    PYTHON_TO_JAVA = {v: k for k, v in JAVA_TO_PYTHON.items()}
    
    @staticmethod
    def java_to_python(data: Dict[str, Any], mapping: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """将 Java 风格字段转换为 Python 风格
        
        Args:
            data: 原始数据字典
            mapping: 自定义映射表（可选）
            
        Returns:
            转换后的数据字典
        """
        if mapping is None:
            mapping = FieldMapper.JAVA_TO_PYTHON
            
        result = {}
        for key, value in data.items():
            # 使用映射表转换字段名
            new_key = mapping.get(key, key)
            result[new_key] = value
            
        return result
    
    @staticmethod
    def python_to_java(data: Dict[str, Any], mapping: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """将 Python 风格字段转换为 Java 风格
        
        Args:
            data: 原始数据字典
            mapping: 自定义映射表（可选）
            
        Returns:
            转换后的数据字典
        """
        if mapping is None:
            mapping = FieldMapper.PYTHON_TO_JAVA
            
        result = {}
        for key, value in data.items():
            # 使用映射表转换字段名
            new_key = mapping.get(key, key)
            result[new_key] = value
            
        return result
    
    @staticmethod
    def get_price(record: Dict[str, Any]) -> Optional[float]:
        """获取商品价格（兼容 price 和 basePrice）
        
        Args:
            record: 商品记录
            
        Returns:
            价格值
        """
        return record.get("price") or record.get("basePrice")
    
    @staticmethod
    def get_main_image(record: Dict[str, Any]) -> Optional[str]:
        """获取商品主图（兼容 mainImage 和 images[0]）
        
        Args:
            record: 商品记录
            
        Returns:
            主图 URL
        """
        main_image = record.get("mainImage") or record.get("main_image")
        if main_image:
            return main_image
        
        # 尝试从 images 数组获取第一张
        images = record.get("images")
        if images and len(images) > 0:
            return images[0]
        
        return None
    
    @staticmethod
    def get_category_id(record: Dict[str, Any]) -> Optional[str]:
        """获取分类 ID（兼容 categoryId 和 category_id）
        
        Args:
            record: 商品记录
            
        Returns:
            分类 ID
        """
        return record.get("categoryId") or record.get("category_id")
