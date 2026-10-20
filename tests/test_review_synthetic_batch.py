import json  # 创建不触及模型服务的本地假采集记录。
import sys  # 加载脚本目录内的核验入口。
from pathlib import Path  # 将假记录写入 pytest 的临时目录。

import pytest  # 核对五例门禁和原文一致性失败。

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"  # 定位本仓库脚本目录。
sys.path.insert(0, str(SCRIPTS))  # 只加载函数，不运行任何 CLI 入口。

import compare_synthetic_s01 as collector  # 复用已锁定的合成原文。
import review_synthetic_batch as reviewer  # 仅执行核验函数。


def fake_record() -> dict:  # 为 S01 构造两侧均有实际请求的合成快照。
    text = collector.INPUT.read_text(encoding="utf-8")  # 使用本地既有合成原文。
    user = collector.extract.build_extraction_messages(text)[1]  # 构造与正式路径相同的输入包装。
    direct_prompt, prompt_hash = collector.load_direct_prompt()  # 固定已有直接侧提示词。
    first = {"model": "test-alias", "max_tokens": 100, "messages": collector.extract.build_extraction_messages(text)}  # 用假模型别名记录请求。
    second = {"model": "test-alias", "max_tokens": 100, "messages": [{"role": "system", "content": direct_prompt}, user]}  # 两侧共享 user 消息。
    return {"case": "S01", "source": "assistant_synthetic_not_stage_5_3_acceptance", "input_path": str(collector.INPUT), "input_sha256": collector.INPUT_SHA256, "direct_prompt_version": "direct-mermaid-v1", "direct_prompt_document_sha256": prompt_hash, "model_alias": "test-alias", "max_tokens": 100, "timeout_seconds": 30, "arms": {"plan2graph": {"status": "failed", "attempts": [{"request": first, "response": {"choices": [{"finish_reason": "length", "message": {"content": None}}]}}]}, "direct_mermaid": {"status": "collected", "mermaid": "flowchart LR\nA[\"示例\"]\n", "attempts": [{"request": second, "response": {"choices": [{"finish_reason": "stop", "message": {"content": "flowchart LR\nA[\"示例\"]\n"}}]}}]}}}  # 不含任何真实 API 回答。


def test_review_rejects_modified_user_before_renderer(tmp_path: Path) -> None:  # 两侧原文不一致时不得启动官方渲染。
    record = fake_record()  # 构造自洽的离线快照。
    record["arms"]["direct_mermaid"]["attempts"][0]["request"]["messages"][1]["content"] = "被改动"  # 只改动直接侧 user。
    path = tmp_path / "altered.json"  # 将假结果写入临时目录。
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")  # 保留 JSON 结构以触发内容核对。
    with pytest.raises(ValueError, match="请求原文不一致"):  # 在渲染前拒绝不同输入。
        reviewer.review([path] * 5, "invalid-renderer")  # 即使指定无效渲染器也应先报输入错误。


def test_review_requires_five_distinct_cases_before_renderer(tmp_path: Path) -> None:  # 不允许挑选重复的成功样例代替失败例。
    path = tmp_path / "s01.json"  # 准备唯一的假 S01 快照。
    path.write_text(json.dumps(fake_record(), ensure_ascii=False), encoding="utf-8")  # 无需模型或渲染器。
    case, record = reviewer.inspect_record(path)  # 单例在校验通过后可读取。
    assert case == "S01" and record["case"] == "S01"  # 确认测试快照本身有效。
    with pytest.raises(ValueError, match="不完整或重复"):  # 重复五次仍不能构成固定样例集。
        reviewer.review([path] * 5, "invalid-renderer")  # 必须在外部进程启动前失败。


def test_review_rejects_modified_system_prompt(tmp_path: Path) -> None:  # 提示词被替换时不能宣称公平对比。
    record = fake_record()  # 构造未触及模型的本地快照。
    record["arms"]["direct_mermaid"]["attempts"][0]["request"]["messages"][0]["content"] = "另一份提示词"  # 篡改直接侧 system。
    path = tmp_path / "prompt.json"  # 使用测试临时文件。
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")  # 保持其他字段不变。
    with pytest.raises(ValueError, match="请求原文不一致"):  # system 内容也必须一致。
        reviewer.inspect_record(path)  # 在渲染器运行之前发现偏差。


def test_review_rejects_truncated_success(tmp_path: Path) -> None:  # 截断正文即使非空也不能伪装成功。
    record = fake_record()  # 从自洽的合成快照出发。
    record["arms"]["direct_mermaid"]["attempts"][0]["response"]["choices"][0]["finish_reason"] = "length"  # 模拟模型截断。
    path = tmp_path / "truncated.json"  # 仅创建临时 JSON。
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")  # 保留原始 Mermaid 以检验状态门禁。
    with pytest.raises(ValueError, match="成功状态与响应结束原因矛盾"):  # 不把截断当成成功图。
        reviewer.inspect_record(path)  # 不需要启动 mmdc。
