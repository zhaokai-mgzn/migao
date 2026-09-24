"""图片识别内核测试包（issue #5321 包 1：识别内核抽离 + 页面快通道）

同 `tests/test_production/__init__.py` / `tests/test_clarification/__init__.py`：
本目录的测试文件名带 `test_` 前缀（pytest.ini 只收 `test_*.py`），
故 `tech-stack.yml` 显式登记 `app/vision/(.+)\.py → tests/test_vision/test_{1}.py`
—— 否则通用规则会要求 `tests/test_vision/<源文件名>.py`，那样**不可被 pytest 收集**
（门禁「绿」而测试从不运行 = 本仓库最忌的静默失效）。
"""
# case_ids: CH-021