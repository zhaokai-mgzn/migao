# 使用阿里云官方 Python 基础镜像
FROM registry.cn-hangzhou.aliyuncs.com/aliyunlinux/alibaba-cloud-linux-3-base:latest

# 设置工作目录
WORKDIR /app

# 安装 Python 和系统依赖
RUN yum install -y python39 python39-pip && \
    yum clean all

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖（使用阿里云镜像源加速）
RUN pip3 install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 复制应用代码
COPY . .

# 创建日志和数据目录
RUN mkdir -p logs data/vector_store

# 暴露端口
EXPOSE 8000

# 启动应用
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
