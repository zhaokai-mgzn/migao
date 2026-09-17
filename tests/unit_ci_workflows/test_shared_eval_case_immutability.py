# case_ids: MC-012
"""共享 `EvalCase` 跨文件污染的**常驻守卫 + 注入式红证**（issue #4061，L0 零 LLM）。

## 病灶（改前实测，非推断）

`tests/agent_eval/eval_cases.py`（生成物）的 `ALL_CASES` 是模块级共享单例。
`test_eval_namespace_isolation.py` 的 `test_real_collisions_would_recur_if_declarations_are_removed`
把 `namespaces` 逐条清空 —— 改的是**共享实例**，不是副本 ⇒ 同进程内
`test_eval_case_asset_truth.py::...::test_declares_a_namespace_that_is_actually_contested`
读到被清空的对象（`namespace_conflict_groups` 只剩 `{}`）⇒ 断言失败。

**CI 判不出来**：`pr-check.yml` 从仓库根按路径字母序收集，受害者的文件名排在投毒者前面
⇒ 恒绿；只有显式组合/分片/点名才红（判据在 CI 上永不触发 = 「不会红的假绿」§19.1）。

## 本文件锁什么（每条都有红证）

1. **注入式红证**：把上面那条真·坏行为（对**真共享对象**原地清空 `namespaces`）喂给
   生产用的守卫本体 ⇒ teardown **必须报红**（否则守卫就是空断言）；
2. **不级联**（负例 R2）：守卫报红时已把共享对象恢复干净 ⇒ 后续测试读到的仍是原值；
3. **深拷贝句柄有效**（负例 R2）：同样的改写作用在副本上 ⇒ 共享对象纹丝不动；
4. **守卫常驻**：本目录每个测试都在守卫覆盖内（摘掉 conftest 的 autouse 夹具 ⇒ 这条红）。

⚠️ 本文件的投毒一律**就地恢复**（守卫自身恢复 + `finally` 兜底），不得把污染留给后续测试。
"""
import pytest

from unit_ci_workflows import conftest as shared_guard


def _live_cases() -> list:
    """**共享**用例实例（故意不拷贝 —— 本文件要验的就是"改写它们会被抓住"）。"""
    import eval_cases
    return list(eval_cases.ALL_CASES)


def _namespaces_fingerprint() -> list:
    return [list(c.namespaces) for c in _live_cases()]


def _historical_bad_write() -> None:
    """issue #4061 的原始坏行为：逐条清空**共享实例**的 `namespaces`。"""
    for x in _live_cases():
        x.namespaces = []


class TestInjectionRedProof:
    """喂「原地改写共享对象」的坏行为 ⇒ 守卫必须报红（每条断言都要有红证）。"""

    def test_guard_fails_the_test_that_writes_through_to_the_shared_objects(self):
        """**真·红证**：驱动生产守卫本体跑一遍投毒测试体 ⇒ teardown 必须抛 Failed。"""
        before = shared_guard.eval_cases_fingerprint(_live_cases())
        guard = shared_guard.guard_shared_eval_cases()
        next(guard)                                   # setup
        try:
            _historical_bad_write()
            assert shared_guard.eval_cases_fingerprint(_live_cases()) != before, (
                "坏样本没真的改到共享对象 —— 本红证无判别力")
            with pytest.raises(pytest.fail.Exception):
                next(guard)                           # teardown ⇒ 必须报红
        finally:
            shared_guard.restore_shared_eval_cases()  # 兜底：万一守卫失效也不留污染

    def test_guard_restores_the_shared_objects_so_pollution_does_not_cascade(self):
        """负例（不级联）：守卫报红的同时把共享对象恢复 ⇒ 后续测试读到的仍是原值。"""
        pristine = _namespaces_fingerprint()
        guard = shared_guard.guard_shared_eval_cases()
        next(guard)
        try:
            _historical_bad_write()
            with pytest.raises(pytest.fail.Exception):
                next(guard)
            assert _namespaces_fingerprint() == pristine, (
                "守卫报了红却没恢复共享对象 ⇒ 污染仍会级联到后续测试")
        finally:
            shared_guard.restore_shared_eval_cases()

    def test_fresh_copy_absorbs_the_same_write_without_touching_the_shared_objects(
            self, eval_cases_snapshot):
        """负例 R2：同一坏行为作用在**深拷贝**上 ⇒ 共享对象指纹不变（拷贝方案真的隔离）。"""
        before = shared_guard.eval_cases_fingerprint(_live_cases())
        for x in eval_cases_snapshot:
            x.namespaces = []
        assert shared_guard.eval_cases_fingerprint(_live_cases()) == before, (
            "深拷贝没有隔离：改副本竟然改到了共享对象")
        assert [list(c.namespaces) for c in eval_cases_snapshot] != _pristine_namespaces(), (
            "副本上的改写没生效 —— 这条负例没有判别力（改的其实是同一个对象）")

    def test_the_guard_itself_leaves_no_residue_behind(self):
        """负例 R2：跑完本文件后共享对象与基线逐字段一致（守卫不误伤、不留尾）。"""
        assert shared_guard.eval_cases_fingerprint(_live_cases()) == shared_guard._BASELINE, (
            "共享对象已偏离基线 ⇒ 本文件自己把污染留给了后续测试")


def _pristine_namespaces() -> list:
    """基线里各用例的 `namespaces`（深拷贝，供负例比对）。"""
    return [list(c.namespaces) for c in shared_guard._PRISTINE]


class TestGuardIsResident:
    """守卫的**常驻性**：不是"这个文件里自测一下"，而是盖住本目录的每个测试。"""

    def test_every_test_in_this_directory_is_covered_by_the_guard(self, request):
        """本目录任一测试都带 autouse 守卫（摘掉 conftest 的夹具 / 去掉 autouse ⇒ 这条红）。"""
        assert "_shared_eval_cases_stay_pristine" in request.fixturenames, (
            "本目录的 autouse 守卫没生效 —— 原地改写共享对象的测试会静默通过"
            f"（本测试的夹具：{sorted(request.fixturenames)}）")

    def test_the_guard_is_not_a_per_file_opt_in(self):
        """守卫必须挂在 **conftest**（目录级），不是某个测试文件里 —— 否则新文件天然漏网。"""
        assert shared_guard.__file__.endswith("unit_ci_workflows/conftest.py"), (
            f"守卫不在本目录 conftest 里（实得 {shared_guard.__file__}）⇒ 覆盖面无从保证")


class TestHandleReturnsIndependentObjects:
    """深拷贝句柄自身的红线：交出的必须是**独立对象**，不是共享实例（含嵌套容器）。"""

    def test_handle_does_not_hand_out_the_shared_instances(self):
        live_ids = {id(c) for c in _live_cases()}
        handed_out = shared_guard.shared_eval_cases()
        assert not (live_ids & {id(c) for c in handed_out}), (
            "`shared_eval_cases()` 交出了共享实例本身 —— 改写它就会污染同进程其它测试")

    def test_handle_deep_copies_nested_containers_too(self):
        """嵌套容器（list/dict）也必须独立 —— 浅拷贝漏掉 `case.namespaces.append(...)`。"""
        before = _namespaces_fingerprint()
        handed_out = shared_guard.shared_eval_cases()
        target = next(c for c in handed_out if c.namespaces)
        target.namespaces.append("smoke:deep-copy-canary")
        assert _namespaces_fingerprint() == before, (
            "嵌套列表被共享了（浅拷贝）—— `append` 照样能污染共享对象")

    def test_restore_also_undoes_a_swapped_module_global(self):
        """兜底：有人把模块全局 `ALL_CASES` 整个换掉 ⇒ 守卫要能连**绑定**一起还原。"""
        import eval_cases
        original = eval_cases.ALL_CASES
        try:
            eval_cases.ALL_CASES = tuple(reversed(original))
            assert shared_guard.eval_cases_fingerprint(
                _live_cases()) != shared_guard._BASELINE
            shared_guard.restore_shared_eval_cases()
            assert eval_cases.ALL_CASES is original, (
                "守卫没还原 `ALL_CASES` 的绑定 —— 换掉全局的破坏会一直留着")
        finally:
            shared_guard.restore_shared_eval_cases()