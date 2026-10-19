"""阶段 0.4 的离线测试：只检查命令帮助和功能边界。"""

import pytest  # 导入自动测试工具。

from plan2graph.cli import main  # 导入命令入口函数。

from pathlib import Path  # 为临时计划文件的路径标注类型。

from io import StringIO  # 创建供测试使用的内存文本输入流。


"""
检查 --help 是否正常工作。
输入 --help 后，程序应正常退出，并显示帮助信息。
帮助信息应包含命令用法。
帮助信息不应输出错误。
"""
def test_help_exits_successfully(capsys: pytest.CaptureFixture[str]) -> None:  # 检查 --help 是否正常工作。
  with pytest.raises(SystemExit) as result:  # 捕获显示帮助后的退出状态。
    main(["--help"])  # 模拟用户输入 --help。
  output = capsys.readouterr()  # 读取命令显示的文字。
  assert result.value.code == 0  # 状态 0 表示正常退出。
  assert "usage: plan2graph" in output.out  # 帮助文字应包含命令用法。
  assert output.err == ""  # 正常帮助不应输出错误。
    

"""
检查不传参数的情况。
不传参数时，程序应正常退出，并显示帮助信息。
帮助信息应包含命令用法。
帮助信息不应输出错误。
"""
def test_no_arguments_shows_help(capsys: pytest.CaptureFixture[str]) -> None:  # 检查不传参数的情况。
  assert main([]) == 0  # 不传参数应正常结束。
  assert "usage: plan2graph" in capsys.readouterr().out  # 应显示帮助，而不是生成图。

"""
检查 generate 命令缺少输入时的参数提示。
输入 generate 命令时，程序应正常退出，并显示错误信息。
错误信息应指出缺少输入参数。
错误信息不应指出 generate 被当成未知命令。
"""
def test_generate_requires_input(capsys: pytest.CaptureFixture[str]) -> None:  # 检查 generate 缺少输入时的参数提示。
  with pytest.raises(SystemExit) as result:  # 捕获参数解析产生的退出状态。
    main(["generate"])  # 模拟只输入 generate、没有提供文件或标准输入标记。
  output = capsys.readouterr()  # 读取命令输出的错误提示。
  assert result.value.code == 2  # 缺少必需参数应属于命令用法错误。
  assert "the following arguments are required" in output.err  # 提示应指出缺少输入参数。
  assert "unrecognized arguments" not in output.err  # generate 不应再被当成未知命令。


"""
检查能否完整读取 UTF-8 计划文件。
计划文件应能正确读取，并保留中文和末尾换行。
"""
def test_read_plan_text_from_utf8_file(tmp_path: Path) -> None:  # 检查能否完整读取 UTF-8 计划文件。
  from plan2graph.cli import read_plan_text  # 在测试内导入下一步要实现的读取函数。
  input_file = tmp_path / "plan.md"  # 在 pytest 提供的临时目录中指定文件。
  input_file.write_text("先完成接口，再联调。\n", encoding="utf-8")  # 写入含中文和末尾换行的样例。
  assert read_plan_text(str(input_file)) == "先完成接口，再联调。\n"  # 确认内容和换行均未丢失。


"""
检查减号是否表示标准输入。
"""
def test_read_plan_text_from_stdin(monkeypatch: pytest.MonkeyPatch) -> None:  # 检查减号是否表示标准输入。
  from plan2graph.cli import read_plan_text  # 导入待验证的读取函数。
  monkeypatch.setattr("sys.stdin", StringIO("先完成接口。\n"))  # 临时用内存文本替代标准输入。
  assert read_plan_text("-") == "先完成接口。\n"  # 确认减号读取输入内容及末尾换行。


"""
检查空白计划会被拒绝。
"""
def test_generate_rejects_blank_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:  # 检查空白计划会被拒绝。
  input_file = tmp_path / "blank.md"  # 创建测试专用的计划文件路径。
  input_file.write_text(" \n\t", encoding="utf-8")  # 写入只有空格、换行和制表符的内容。
  status = main(["generate", str(input_file)])  # 模拟从该文件生成任务图。
  output = capsys.readouterr()  # 分别读取标准输出和错误输出。
  assert status != 0  # 空输入不能被报告为成功。
  assert "输入为空" in output.err  # 错误提示应指出真正原因。
  assert output.out == ""  # 失败时不能输出伪装成成功的图。


"""
检查不存在的输入文件。
"""
def test_generate_reports_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:  # 检查不存在的输入文件。
  missing_file = tmp_path / "missing.md"  # 指定一个未创建的文件路径。
  status = main(["generate", str(missing_file)])  # 模拟用户传入该路径。
  output = capsys.readouterr()  # 读取命令的正常输出和错误输出。
  assert status != 0  # 文件不存在时不能成功退出。
  assert "输入文件不存在" in output.err  # 错误提示应指出具体问题。
  assert output.out == ""  # 失败时不能输出 Mermaid 图。


"""
检查无法按 UTF-8 解码的文件。
"""
def test_generate_reports_invalid_utf8(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:  # 检查无法按 UTF-8 解码的文件。
  input_file = tmp_path / "invalid.md"  # 指定测试专用文件。
  input_file.write_bytes(b"\xff")  # 写入不合法的 UTF-8 字节。
  status = main(["generate", str(input_file)])  # 模拟读取该文件。
  output = capsys.readouterr()  # 获取标准输出和错误输出。
  assert status != 0  # 解码失败不能成功退出。
  assert "UTF-8" in output.err  # 提示应说明文件编码要求。
  assert output.out == ""  # 失败时不能输出图。


"""
检查文件输入能生成 Mermaid 标准输出。
"""
def test_generate_file_outputs_mermaid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:  # 检查文件输入能生成 Mermaid 标准输出。
  import plan2graph.extract as extract  # 获取要在测试中替换的抽取模块。
  from plan2graph.models import GraphTask, PlanGraph  # 导入构造假任务图所需的数据类型。
  input_file = tmp_path / "plan.md"  # 准备临时计划文件路径。
  input_file.write_text("完成接口\n", encoding="utf-8")  # 写入测试计划。
  graph = PlanGraph((GraphTask("T1", "完成接口", ("完成接口",), 0),), (), ())  # 构造单节点任务图。
  client = object()  # 用普通对象代替真实 DeepSeek 客户端。
  monkeypatch.setattr(extract, "create_deepseek_client", lambda: client)  # 阻止测试创建真实客户端。
  def fake_extract(text: str, received_client: object) -> PlanGraph:  # 定义替代真实抽取流程的函数。
    assert text == "完成接口\n"  # 确认 CLI 传入了完整计划原文。
    assert received_client is client  # 确认 CLI 使用了测试客户端。
    return graph  # 返回预先构造的任务图。
  monkeypatch.setattr(extract, "extract_plan_graph", fake_extract)  # 阻止测试发出模型请求。
  status = main(["generate", str(input_file)])  # 模拟用户生成文件中的计划。
  output = capsys.readouterr()  # 读取 CLI 输出。
  assert status == 0  # 生成成功应正常退出。
  assert output.out == 'flowchart LR\n  T1["完成接口"]\n'  # 标准输出应只有 Mermaid 源码。
  assert "任务数：1，确定依赖数：0，待确认关系数：0" in output.err  # 成功摘要应在标准错误中报告三项数量。


"""
检查 generate - 的完整输入输出流程。
"""
def test_generate_stdin_outputs_mermaid(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:  # 检查 generate - 的完整输入输出流程。
  import plan2graph.extract as extract  # 获取要替换的抽取模块。
  from plan2graph.models import GraphTask, PlanGraph  # 导入测试用任务图类型。
  monkeypatch.setattr("sys.stdin", StringIO("完成接口\n"))  # 用内存文本模拟标准输入。
  graph = PlanGraph((GraphTask("T1", "完成接口", ("完成接口",), 0),), (), ())  # 准备预期的单节点图。
  client = object()  # 创建不会联网的假客户端。
  monkeypatch.setattr(extract, "create_deepseek_client", lambda: client)  # 避免创建真实客户端。
  def fake_extract(text: str, received_client: object) -> PlanGraph:  # 定义替代真实抽取的函数。
    assert text == "完成接口\n"  # 确认标准输入原文完整传入。
    assert received_client is client  # 确认使用的是假客户端。
    return graph  # 返回测试图。
  monkeypatch.setattr(extract, "extract_plan_graph", fake_extract)  # 避免发送模型请求。
  status = main(["generate", "-"])  # 模拟从标准输入生成图。
  output = capsys.readouterr()  # 分别读取正常输出和错误输出。
  assert status == 0  # 成功时退出状态为零。
  assert output.out == 'flowchart LR\n  T1["完成接口"]\n'  # 正常输出应是 Mermaid 源码。
  assert output.err == "任务数：1，确定依赖数：0，待确认关系数：0\n"  # 无关系的单任务图仍应输出成功摘要。



"""
检查 -o 将图写入文件。
"""
def test_generate_writes_output_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:  # 检查 -o 将图写入文件。
  import plan2graph.extract as extract  # 获取测试中需要替换的抽取模块。
  from plan2graph.models import GraphTask, PlanGraph  # 导入测试图的数据类型。
  input_file = tmp_path / "plan.md"  # 指定临时输入文件。
  output_file = tmp_path / "plan.mmd"  # 指定临时输出文件。
  input_file.write_text("完成接口\n", encoding="utf-8")  # 写入测试计划。
  graph = PlanGraph((GraphTask("T1", "完成接口", ("完成接口",), 0),), (), ())  # 准备测试图。
  client = object()  # 创建不会联网的假客户端。
  monkeypatch.setattr(extract, "create_deepseek_client", lambda: client)  # 避免创建真实客户端。
  def fake_extract(text: str, received_client: object) -> PlanGraph:  # 替代真实抽取流程。
    assert text == "完成接口\n"  # 核对传入的计划原文。
    assert received_client is client  # 核对使用的是假客户端。
    return graph  # 返回测试图。
  monkeypatch.setattr(extract, "extract_plan_graph", fake_extract)  # 避免模型请求。
  status = main(["generate", str(input_file), "-o", str(output_file)])  # 模拟指定输出文件。
  output = capsys.readouterr()  # 读取命令行输出。
  assert status == 0  # 文件写入成功应正常退出。
  assert output_file.read_text(encoding="utf-8") == 'flowchart LR\n  T1["完成接口"]\n'  # 核对文件内容。
  assert output.out == ""  # 文件模式不应再把图写到标准输出。
  assert output.err == "任务数：1，确定依赖数：0，待确认关系数：0\n"  # 写入 .mmd 成功后，摘要仍应输出到标准错误。


"""
检查输入输出同路径时不会覆盖计划。
"""
def test_generate_rejects_same_input_and_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:  # 检查输入输出同路径时不会覆盖计划。
  import plan2graph.extract as extract  # 获取客户端所在模块。
  input_file = tmp_path / "plan.md"  # 准备同时用作输入和输出的路径。
  input_file.write_text("完成接口\n", encoding="utf-8")  # 保存需要保护的原计划。
  monkeypatch.setattr(extract, "create_deepseek_client", lambda: pytest.fail("同路径输入不应调用模型"))  # 确保测试绝不联网。
  status = main(["generate", str(input_file), "-o", str(input_file)])  # 模拟误将输出指向输入文件。
  output = capsys.readouterr()  # 读取命令输出。
  assert status == 2  # 路径冲突应作为输入参数错误退出。
  assert "相同" in output.err  # 提示应明确说明路径冲突。
  assert output.out == ""  # 失败时不输出成功图。
  assert input_file.read_text(encoding="utf-8") == "完成接口\n"  # 原计划必须保持不变。


"""
检查输出文件无法写入时的提示。
"""
def test_generate_reports_output_write_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:  # 检查输出文件无法写入时的提示。
  import plan2graph.extract as extract  # 获取测试中需要替换的抽取模块。
  from plan2graph.models import GraphTask, PlanGraph  # 导入测试图的数据类型。
  input_file = tmp_path / "plan.md"  # 指定可正常读取的输入文件。
  output_file = tmp_path / "missing" / "plan.mmd"  # 指定父目录不存在的输出路径。
  input_file.write_text("完成接口\n", encoding="utf-8")  # 写入有效计划。
  graph = PlanGraph((GraphTask("T1", "完成接口", ("完成接口",), 0),), (), ())  # 准备有效任务图。
  monkeypatch.setattr(extract, "create_deepseek_client", lambda: object())  # 避免创建真实客户端。
  monkeypatch.setattr(extract, "extract_plan_graph", lambda text, client: graph)  # 避免模型请求。
  status = main(["generate", str(input_file), "-o", str(output_file)])  # 尝试写入不存在的目录。
  output = capsys.readouterr()  # 读取正常输出与错误输出。
  assert status == 3  # 用独立的非零状态表示输出文件错误。
  assert "输出文件写入失败" in output.err  # 错误提示应指出失败环节。
  assert output.out == ""  # 失败时不能输出成功图。
  assert not output_file.exists()  # 失败时不能留下目标文件。


"""
检查替换失败时旧图不变。
"""
def test_generate_preserves_existing_output_on_replace_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:  # 检查替换失败时旧图不变。
  import os  # 用于模拟最终的文件替换操作。
  import plan2graph.extract as extract  # 获取需要替换的抽取模块。
  from plan2graph.models import GraphTask, PlanGraph  # 导入测试图的数据类型。
  input_file = tmp_path / "plan.md"  # 指定输入文件。
  output_file = tmp_path / "plan.mmd"  # 指定已存在的输出文件。
  input_file.write_text("完成接口\n", encoding="utf-8")  # 写入计划。
  output_file.write_text("旧图内容\n", encoding="utf-8")  # 保存需要保护的旧图。
  graph = PlanGraph((GraphTask("T1", "完成接口", ("完成接口",), 0),), (), ())  # 准备新图。
  monkeypatch.setattr(extract, "create_deepseek_client", lambda: object())  # 阻止真实客户端创建。
  monkeypatch.setattr(extract, "extract_plan_graph", lambda text, client: graph)  # 阻止模型请求。
  def fail_replace(source: str, target: str) -> None:  # 模拟最终替换文件失败。
    raise OSError("模拟替换失败")  # 在旧文件被替换前制造错误。
  monkeypatch.setattr(os, "replace", fail_replace)  # 只在本测试中替换系统操作。
  status = main(["generate", str(input_file), "-o", str(output_file)])  # 尝试生成新图。
  output = capsys.readouterr()  # 读取命令输出。
  assert status == 3  # 文件替换失败应返回输出错误状态。
  assert "输出文件写入失败" in output.err  # 应说明失败环节。
  assert output.out == ""  # 失败时不能输出成功图。
  assert output_file.read_text(encoding="utf-8") == "旧图内容\n"  # 原有输出文件不能被改动。
  assert set(tmp_path.iterdir()) == {input_file, output_file}  # 临时文件也应清理干净。


"""
检查缺少密钥时的命令行提示。
"""
def test_generate_reports_missing_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:  # 检查缺少密钥时的命令行提示。
  import plan2graph.extract as extract  # 获取需要替换的客户端创建函数。
  input_file = tmp_path / "plan.md"  # 指定有效输入文件。
  output_file = tmp_path / "plan.mmd"  # 指定本不该生成的输出文件。
  input_file.write_text("完成接口\n", encoding="utf-8")  # 写入非空计划。
  def missing_key() -> None:  # 模拟客户端发现密钥缺失。
    raise ValueError("缺少 DEEPSEEK_API_KEY 环境变量")  # 使用现有抽取模块的错误描述。
  monkeypatch.setattr(extract, "create_deepseek_client", missing_key)  # 避免创建真实客户端或联网。
  status = main(["generate", str(input_file), "-o", str(output_file)])  # 模拟生成文件。
  output = capsys.readouterr()  # 读取正常输出和错误输出。
  assert status == 4  # 用独立状态表示配置错误。
  assert "DEEPSEEK_API_KEY" in output.err  # 提示用户需要检查哪项配置。
  assert output.out == ""  # 失败时不输出成功图。
  assert not output_file.exists()  # 失败时不创建输出文件。


"""
检查模型回答截断时的失败行为。
"""
def test_generate_reports_truncated_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:  # 检查模型回答截断时的失败行为。
  import plan2graph.extract as extract  # 获取需要替换的抽取模块。
  input_file = tmp_path / "plan.md"  # 指定有效计划文件。
  output_file = tmp_path / "plan.mmd"  # 指定已有的输出文件。
  input_file.write_text("完成接口\n", encoding="utf-8")  # 写入非空计划。
  output_file.write_text("旧图内容\n", encoding="utf-8")  # 保存需要保护的旧图。
  monkeypatch.setattr(extract, "create_deepseek_client", lambda: object())  # 避免创建真实客户端。
  def truncated_response(text: str, client: object) -> None:  # 模拟抽取时发现回答不完整。
    raise RuntimeError("DeepSeek 响应被截断")  # 使用现有抽取模块的错误描述。
  monkeypatch.setattr(extract, "extract_plan_graph", truncated_response)  # 避免模型请求。
  status = main(["generate", str(input_file), "-o", str(output_file)])  # 尝试生成新图。
  output = capsys.readouterr()  # 读取正常输出和错误输出。
  assert status == 5  # 用独立状态表示模型响应失败。
  assert "响应被截断" in output.err  # 明确告诉用户失败原因。
  assert output.out == ""  # 失败时不输出成功图。
  assert output_file.read_text(encoding="utf-8") == "旧图内容\n"  # 失败不能覆盖旧图。


"""
检查任务图结构失败时的命令行行为。
"""
def test_generate_reports_invalid_graph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:  # 检查任务图结构失败时的命令行行为。
  import plan2graph.extract as extract  # 获取需要替换的抽取模块。
  input_file = tmp_path / "plan.md"  # 指定有效输入文件。
  output_file = tmp_path / "plan.mmd"  # 指定已有输出文件。
  input_file.write_text("完成接口\n", encoding="utf-8")  # 写入非空计划。
  output_file.write_text("旧图内容\n", encoding="utf-8")  # 保留需要保护的旧图。
  monkeypatch.setattr(extract, "create_deepseek_client", lambda: object())  # 避免创建真实客户端。
  def invalid_graph(text: str, client: object) -> None:  # 模拟结构修复仍然失败。
    raise ValueError("结构修复失败：tasks.0.source_quote")  # 使用现有抽取模块的错误形式。
  monkeypatch.setattr(extract, "extract_plan_graph", invalid_graph)  # 避免模型请求。
  status = main(["generate", str(input_file), "-o", str(output_file)])  # 尝试生成图。
  output = capsys.readouterr()  # 读取命令输出。
  assert status == 6  # 用独立状态表示任务图结构错误。
  assert "结构" in output.err  # 提示应指出失败类别。
  assert output.out == ""  # 失败时不输出成功图。
  assert output_file.read_text(encoding="utf-8") == "旧图内容\n"  # 失败不能覆盖旧图。


"""
检查模型连接失败时的命令行行为。
"""
def test_generate_reports_connection_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:  # 检查模型连接失败时的命令行行为。
  import plan2graph.extract as extract  # 获取需要替换的抽取模块。
  from openai import APIConnectionError  # 导入 SDK 的连接错误类型。
  from httpx import Request  # 创建错误对象所需的假请求信息。
  input_file = tmp_path / "plan.md"  # 指定输入文件。
  output_file = tmp_path / "plan.mmd"  # 指定已有输出文件。
  input_file.write_text("完成接口\n", encoding="utf-8")  # 写入非空计划。
  output_file.write_text("旧图内容\n", encoding="utf-8")  # 保存需要保护的旧图。
  monkeypatch.setattr(extract, "create_deepseek_client", lambda: object())  # 避免创建真实客户端。
  def connection_failure(text: str, client: object) -> None:  # 模拟模型请求最终连接失败。
    raise APIConnectionError(request=Request("POST", "https://api.deepseek.com/chat/completions"))  # 只构造异常，不发送请求。
  monkeypatch.setattr(extract, "extract_plan_graph", connection_failure)  # 避免真实模型调用。
  status = main(["generate", str(input_file), "-o", str(output_file)])  # 尝试生成图。
  output = capsys.readouterr()  # 读取命令输出。
  assert status == 5  # 模型请求失败使用非零状态。
  assert "模型请求失败" in output.err  # 提示应说明失败发生在请求阶段。
  assert output.out == ""  # 失败时不输出成功图。
  assert output_file.read_text(encoding="utf-8") == "旧图内容\n"  # 失败不能覆盖旧图。


"""
检查目录被误当成输入文件的情况。
"""
def test_generate_reports_unreadable_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:  # 检查目录被误当成输入文件的情况。
  status = main(["generate", str(tmp_path)])  # 把临时目录路径当作计划文件传入。
  output = capsys.readouterr()  # 读取正常输出和错误输出。
  assert status == 2  # 无法读取输入应按输入错误退出。
  assert "输入文件读取失败" in output.err  # 提示应指明读取阶段出错。
  assert output.out == ""  # 失败时不输出成功图。


"""
检查过长计划会在模型调用前被拒绝。
"""
def test_generate_rejects_oversized_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:  # 检查过长计划会在模型调用前被拒绝。
  import plan2graph.extract as extract  # 获取客户端创建函数以设置安全检查。
  monkeypatch.delenv("PLAN2GRAPH_MAX_INPUT_CHARS", raising=False)  # 使用默认长度上限。
  input_file = tmp_path / "long.md"  # 指定临时输入文件。
  input_file.write_text("任" * 20001, encoding="utf-8")  # 写入比默认上限多一个字符的计划。
  monkeypatch.setattr(extract, "create_deepseek_client", lambda: pytest.fail("超限输入不应调用模型"))  # 确保测试不会创建客户端。
  status = main(["generate", str(input_file)])  # 尝试生成过长计划的图。
  output = capsys.readouterr()  # 读取命令输出。
  assert status == 2  # 超限属于输入错误。
  assert "超出上限" in output.err  # 提示应说明是长度问题。
  assert output.out == ""  # 失败时不输出 Mermaid 图。


"""
检查无效的输入长度配置。
"""
def test_generate_reports_invalid_input_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:  # 检查无效的输入长度配置。
  import plan2graph.extract as extract  # 获取需要设置防联网检查的模块。
  input_file = tmp_path / "plan.md"  # 指定临时输入路径。
  output_file = tmp_path / "plan.mmd"  # 指定不应生成的图文件。
  input_file.write_text("完成接口\n", encoding="utf-8")  # 写入有效计划以越过输入检查。
  monkeypatch.setenv("PLAN2GRAPH_MAX_INPUT_CHARS", "abc")  # 临时设置无法转换成整数的上限。
  monkeypatch.setattr(extract, "create_deepseek_client", lambda: pytest.fail("无效长度配置不应创建客户端"))  # 确保不会进入客户端创建流程。
  status = main(["generate", str(input_file), "-o", str(output_file)])  # 模拟文件输出命令。
  output = capsys.readouterr()  # 取得标准输出和标准错误。
  assert status == 4  # 配置错误使用状态 4，而非输入错误状态 2。
  assert "PLAN2GRAPH_MAX_INPUT_CHARS" in output.err  # 提示应指出具体配置项。
  assert output.out == ""  # 失败时不输出 Mermaid。
  assert not output_file.exists()  # 失败时不留下图文件。



"""
检查候选关系的图和诊断分流。
"""
def test_generate_reports_candidate_on_stderr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:  # 检查候选关系的图和诊断分流。
  import plan2graph.extract as extract  # 获取需要替换的抽取模块。
  from plan2graph.models import GraphRelation, GraphTask, PlanGraph  # 导入测试图的数据类型。
  input_file = tmp_path / "plan.md"  # 指定临时输入文件。
  input_file.write_text("最好先完成用户模型，再配置等级，但也许能并行。\n", encoding="utf-8")  # 写入含歧义的计划。
  first = GraphTask("T1", "用户模型", ("用户模型",), 0)  # 准备第一项任务。
  second = GraphTask("T2", "配置等级", ("配置等级",), 8)  # 准备第二项任务。
  relation = GraphRelation("T1", "T2", "candidate", "最好先完成用户模型，再配置等级", "是否必须等待尚待确认")  # 准备待确认关系。
  graph = PlanGraph((first, second), (relation,), ())  # 构造包含候选关系的图。
  monkeypatch.setattr(extract, "create_deepseek_client", lambda: object())  # 避免创建真实客户端。
  monkeypatch.setattr(extract, "extract_plan_graph", lambda text, client: graph)  # 避免模型请求。
  status = main(["generate", str(input_file)])  # 模拟生成标准输出模式的图。
  output = capsys.readouterr()  # 分别读取图和诊断。
  assert status == 0  # 候选关系不是生成失败。
  assert output.out == 'flowchart LR\n  T1["用户模型"]\n  T2["配置等级"]\n  T1 -.-> T2\n'  # 虚线只出现在 Mermaid 源码中。
  assert "待确认关系 T1 -> T2" in output.err  # 诊断应指出涉及哪两个任务。
  assert "是否必须等待尚待确认" in output.err  # 诊断应说明待确认原因。
  assert "任务数：2，确定依赖数：0，待确认关系数：1" in output.err  # 一条画出的候选关系应计入成功摘要。



"""
检查被跳过的关系只在诊断中说明。
"""
def test_generate_reports_skipped_relation_on_stderr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:  # 检查被跳过的关系只在诊断中说明。
  import plan2graph.extract as extract  # 获取需要临时替换的抽取模块。
  from plan2graph.models import GraphRelation, GraphTask, PlanGraph, SkippedRelation  # 导入构造测试图所需的数据类型。
  input_file = tmp_path / "plan.md"  # 指定临时输入文件。
  input_file.write_text("先完成接口，再联调。联调依赖接口；也许先联调再完成接口。\n", encoding="utf-8")  # 写入测试专用计划。
  first = GraphTask("T1", "接口", ("接口",), 3)  # 准备接口任务。
  second = GraphTask("T2", "联调", ("联调",), 7)  # 准备联调任务。
  hard = GraphRelation("T1", "T2", "hard", "联调依赖接口", "接口先完成")  # 准备应画出的确定依赖。
  conflicting = GraphRelation("T2", "T1", "candidate", "也许先联调再完成接口", "顺序待确认")  # 准备与确定依赖成环的候选关系。
  skipped = SkippedRelation(conflicting, "候选关系会使展示图成环")  # 记录候选关系未画出的原因。
  graph = PlanGraph((first, second), (hard,), (skipped,))  # 将保留关系与跳过记录分开放入任务图。
  monkeypatch.setattr(extract, "create_deepseek_client", lambda: object())  # 避免创建真实客户端。
  monkeypatch.setattr(extract, "extract_plan_graph", lambda text, client: graph)  # 避免联网并返回预设任务图。
  status = main(["generate", str(input_file)])  # 模拟从文件生成 Mermaid。
  output = capsys.readouterr()  # 分别取得标准输出和标准错误。
  assert status == 0  # 跳过一条冲突候选关系不应导致生成失败。
  assert output.out == 'flowchart LR\n  T1["接口"]\n  T2["联调"]\n  T1 --> T2\n'  # 图中只保留确定依赖。
  assert "已跳过关系 T2 -> T1" in output.err  # 诊断指出哪条关系未画出。
  assert "候选关系会使展示图成环" in output.err  # 诊断说明跳过原因。
  assert "任务数：2，确定依赖数：1，待确认关系数：0" in output.err  # 被跳过的候选关系不计数，已画出的确定依赖计为一条。