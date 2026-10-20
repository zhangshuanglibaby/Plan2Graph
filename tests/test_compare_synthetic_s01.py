import importlib.util  # 从固定文件加载仅用于 S01 的采集入口。
import json  # 核对保存到本地的失败现场。
import sys  # 模拟不带参数的脚本调用。
from pathlib import Path  # 定位脚本和临时输入文件。
from types import ModuleType  # 标注本地加载的模块类型。
from unittest.mock import Mock  # 用假客户端保证测试不联网。

import pytest  # 校验拒绝发送与错误记录。


def load_collector() -> ModuleType:  # 只加载函数，不运行脚本入口。
    path = Path(__file__).resolve().parents[1] / "scripts/compare_synthetic_s01.py"  # 找到固定采集脚本。
    spec = importlib.util.spec_from_file_location("compare_synthetic_s01_test", path)  # 构造独立的模块规格。
    assert spec is not None and spec.loader is not None  # 确保本地脚本可以加载。
    module = importlib.util.module_from_spec(spec)  # 创建不触发主函数的模块。
    spec.loader.exec_module(module)  # 加载定义但不发出网络请求。
    return module  # 返回可替换输入与客户端的模块。


def test_changed_s01_stops_before_client_creation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # 未授权的新字节不能进入模型客户端。
    collector = load_collector()  # 加载离线受控的脚本定义。
    changed_input = tmp_path / "changed.md"  # 将改动限制在临时目录。
    changed_input.write_text("这不是已授权的 S01 原文", encoding="utf-8")  # 准备不匹配的输入字节。
    monkeypatch.setattr(collector, "INPUT", changed_input)  # 仅在本测试中替换输入位置。
    monkeypatch.setattr(sys, "argv", ["compare_synthetic_s01.py"])  # 满足脚本固定入口参数检查。
    client_factory = Mock(side_effect=AssertionError("不应创建模型客户端"))  # 若触及客户端即失败。
    monkeypatch.setattr(collector.extract, "create_deepseek_client", client_factory)  # 拦截全部真实客户端创建。
    with pytest.raises(ValueError, match="内容指纹已改变"):  # 改动后的原文必须在网络调用前被拒绝。
        collector.main()  # 执行只会走到指纹门禁的入口。
    client_factory.assert_not_called()  # 确认没有模型客户端或请求。


def test_request_failure_keeps_redacted_local_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # 每次失败都留下脱敏现场。
    collector = load_collector()  # 加载不会自动运行的采集器。
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret-only")  # 用测试字符串模拟可能泄漏的密钥。
    record = {"arms": {"plan2graph": {"attempts": []}}}  # 准备唯一受测的采集侧。
    backend = Mock()  # 创建没有网络能力的假完成接口。
    backend.create.side_effect = RuntimeError("错误内容 test-secret-only")  # 让请求在返回之前失败。
    output = tmp_path / "record.json"  # 仅写入 pytest 的临时文件。
    recorder = collector.RecordingCompletions(backend, record, "plan2graph", output)  # 使用正式记录代理。
    with pytest.raises(RuntimeError, match="test-secret-only"):  # 保持原异常供正式流程处理。
        recorder.create(model="fake", messages=[{"role": "user", "content": "合成输入"}])  # 用非真实原文触发假请求。
    saved = json.loads(output.read_text(encoding="utf-8"))  # 检查失败后实际落盘的 JSON。
    attempt = saved["arms"]["plan2graph"]["attempts"][0]  # 检查唯一一次请求。
    assert attempt["request"]["model"] == "fake"  # 保存请求参数供后续核对。
    assert attempt["failure"]["message"] == "错误内容 [REDACTED]"  # 密钥不进入错误记录。
    assert "finished_at_utc" in attempt  # 即使失败也保存结束时间。
    assert "test-secret-only" not in output.read_text(encoding="utf-8")  # 确认整个结果文件没有测试密钥。


def test_direct_truncation_keeps_raw_response_as_failure(tmp_path: Path) -> None:  # 截断不能被写成已采集成功的图。
    collector = load_collector()  # 加载本地采集脚本。
    response = Mock()  # 准备不访问 DeepSeek 的假回答。
    response.choices = [Mock(finish_reason="length", message=Mock(content=None))]  # 模拟没有正文的截断回答。
    response.model_dump.return_value = {"choices": [{"finish_reason": "length", "message": {"content": None}}]}  # 保存原始失败状态。
    backend = Mock()  # 创建受控的假完成接口。
    backend.create.return_value = response  # 让第一次请求返回截断回答。
    record = {"model_alias": "fake", "max_tokens": 8, "arms": {"direct_mermaid": {"status": "not_started", "attempts": []}}}  # 准备直接生成侧。
    output = tmp_path / "record.json"  # 仅写入临时采集结果。
    recorder = collector.RecordingCompletions(backend, record, "direct_mermaid", output)  # 复用正式记录代理。
    collector.run_direct("合成输入", "固定规则", recorder, record)  # 对假响应运行直接生成路径。
    saved = json.loads(output.read_text(encoding="utf-8"))  # 读取本地记录的原始请求与响应。
    assert record["arms"]["direct_mermaid"]["status"] == "failed"  # 截断没有被标记成成功。
    assert "mermaid" not in record["arms"]["direct_mermaid"]  # 没有原文时不伪造 Mermaid。
    assert saved["arms"]["direct_mermaid"]["attempts"][0]["response"]["choices"][0]["finish_reason"] == "length"  # 原样保留截断信息。
    assert json.loads(saved["arms"]["direct_mermaid"]["attempts"][0]["request"]["messages"][1]["content"]) == {"plan_text": "合成输入"}  # 输入由固定 JSON 包装。
