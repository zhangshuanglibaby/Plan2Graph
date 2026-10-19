
import argparse  # 解析命令行参数。
import json  # 将模型给出的原因转义为安全的单行文本。
import sys  # 将错误提示写入标准错误输出。
from pathlib import Path  # 用标准库路径对象读取计划文件。
from plan2graph import extract  # 复用已有的 DeepSeek 客户端与任务图抽取逻辑。
from plan2graph.mermaid import render_mermaid  # 复用已有的 Mermaid 文本生成函数。
import os  # 在新文件写完整后执行文件替换。
import tempfile  # 在输出目录创建临时文件。
from openai import APIError  # 识别模型 SDK 的连接及服务端错误。


"""
根据输入来源读取计划文本。
输入：
- input_path: 计划文件路径，或 - 表示标准输入。
输出：
- 计划文本，字符串。
"""
def read_plan_text(input_path: str) -> str:  # 根据输入来源读取计划文本。
  if input_path == "-":  # 减号表示从标准输入读取，而非查找名为减号的文件。
    return sys.stdin.read()  # 读取标准输入中的全部文本。
  return Path(input_path).read_text(encoding="utf-8")  # 其他值按 UTF-8 文件路径读取。


"""
读取可配置的计划字符数上限。
输入：
- 无
输出：
- 计划字符数上限，整数。
"""
def get_max_input_chars() -> int:  # 读取可配置的计划字符数上限。
  raw_limit = os.environ.get("PLAN2GRAPH_MAX_INPUT_CHARS", "20000")  # 未配置时默认允许 20000 字符。
  try:  # 将环境变量中的文本转换为整数。
    limit = int(raw_limit)  # 得到字符数上限。
  except ValueError as error:  # 拒绝无法转换为整数的配置。
    raise ValueError("PLAN2GRAPH_MAX_INPUT_CHARS 必须是正整数") from error  # 说明正确配置格式。
  if limit <= 0:  # 零和负数都不能作为上限。
    raise ValueError("PLAN2GRAPH_MAX_INPUT_CHARS 必须是正整数")  # 阻止无效值进入长度检查。
  return limit  # 返回有效的字符数上限。


"""
先写临时文件，再替换目标文件。
输入：
- output_path: 用户指定的输出文件路径。
- mermaid_text: 完整的 Mermaid 源码，字符串。
"""
def write_mermaid_file(output_path: str, mermaid_text: str) -> None:  # 先写临时文件，再替换目标文件。
  destination = Path(output_path)  # 保存用户指定的输出路径。
  temp_path: Path | None = None  # 记录临时文件路径，供失败时清理。
  try:  # 确保成功或失败后都处理临时文件。
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp", delete=False) as temp_file:  # 在目标目录创建临时文件。
      temp_path = Path(temp_file.name)  # 记住临时文件的位置。
      temp_file.write(mermaid_text)  # 将完整 Mermaid 源码写入临时文件。
    os.replace(temp_path, destination)  # 临时文件写完并关闭后才替换目标。
    temp_path = None  # 替换成功后，临时路径已不再存在。
  finally:  # 如果写入或替换失败，清理遗留的临时文件。
    if temp_path is not None:  # 只有创建过临时文件才需要清理。
      temp_path.unlink(missing_ok=True)  # 删除临时文件，不触碰旧图。


def main(argv: list[str] | None = None) -> int:  # 定义命令入口，允许测试传入模拟参数。
  parser = argparse.ArgumentParser(prog="plan2graph", description="将计划文本转换为任务图。")  # 创建主命令。
  subparsers = parser.add_subparsers(dest="command")  # 创建子命令集合。
  generate_parser = subparsers.add_parser("generate", help="生成任务图（开发中）")  # 注册 generate 子命令。
  generate_parser.add_argument("input", help="计划文件路径，或 - 表示标准输入")  # 要求提供输入来源。
  generate_parser.add_argument("-o", "--output", help="Mermaid 输出文件路径")  # 接受可选的输出路径。
  args = parser.parse_args(argv)  # 解析参数；缺少输入时由 argparse 报错并退出。
  if args.command is None:  # 用户没有选择子命令时显示主帮助。
    parser.print_help()  # 保持原有的不传参数行为。
    return 0  # 显示帮助属于正常退出。
  if args.output is not None and args.input != "-" and Path(args.input).resolve() == Path(args.output).resolve():  # 比较输入与输出指向的实际路径。
    print("输出路径不能与输入文件相同。", file=sys.stderr)  # 告知用户路径冲突。
    return 2  # 在读取和模型调用前停止，保护原计划。
  try:  # 尝试读取用户指定的输入来源。
    plan_text = read_plan_text(args.input)  # 读取文件或标准输入。
  except FileNotFoundError:  # 只捕获输入文件不存在的错误。
    print("输入文件不存在：请检查文件路径。", file=sys.stderr)  # 给出可操作的错误提示。
    return 2  # 以非零状态结束，不继续生成。
  except UnicodeDecodeError:  # 捕获文本无法按指定编码解码的错误。
    print("输入编码错误：请提供 UTF-8 编码的计划文本。", file=sys.stderr)  # 告知用户如何修正输入。
    return 2  # 不继续生成，也不输出图。
  except OSError:  # 捕获目录被当成文件、无读取权限等其他输入读取错误。
    print("输入文件读取失败：请检查输入路径和读取权限。", file=sys.stderr)  # 给出排查方向。
    return 2  # 在调用模型之前结束。
  if not plan_text.strip():  # 去掉空白后检查内容；不改动实际传入的原文。
    print("输入为空：请提供非空计划文本。", file=sys.stderr)  # 向标准错误输出原因。
    return 2  # 用非零状态表示输入错误。
  try:  # 在创建模型客户端之前读取输入长度上限。
    max_input_chars = get_max_input_chars()  # 使用环境变量或默认的 20000 字符。
  except ValueError as error:  # 捕获上限配置不是正整数的情况。
    print(f"输入长度配置错误：{error}", file=sys.stderr)  # 告知用户如何修正配置。
    return 4  # 配置错误不进入模型调用。
  if len(plan_text) > max_input_chars:  # 按原文字符数检查，不截断计划。
    print(f"输入超出上限：最多 {max_input_chars} 字符。", file=sys.stderr)  # 报告当前限制。
    return 2  # 超限输入不能调用模型或生成图。
  try:  # 创建客户端时检查密钥及请求配置。
    extract.get_deepseek_max_tokens()  # 提前验证回答长度配置，让错误归入配置类。
    client = extract.create_deepseek_client()  # 此步只创建客户端，不发送模型请求。
  except ValueError as error:  # 捕获缺密钥或无效配置。
    print(f"DeepSeek 配置错误：{error}", file=sys.stderr)  # 向错误输出说明应检查的配置。
    return 4  # 配置错误使用独立的退出状态。
  try:  # 抽取任务图，成功后才进入 Mermaid 输出步骤。
    graph = extract.extract_plan_graph(plan_text, client)  # 从计划原文得到已校验的任务图。
  except APIError:  # 捕获 SDK 报告的连接、超时或服务端请求错误。
    print("模型请求失败：请检查网络、DeepSeek 服务状态及密钥权限。", file=sys.stderr)  # 给出排查方向，不打印可能含敏感信息的原始异常。
    return 5  # 请求失败时不生成或覆盖图。
  except RuntimeError as error:  # 捕获空回答、截断等抽取模块报告的响应错误。
    print(f"模型响应失败：{error}", file=sys.stderr)  # 将可读原因写到标准错误输出。
    return 5  # 不覆盖文件，也不输出成功图。
  except ValueError as error:  # 捕获证据或任务图结构最终未通过校验的错误。
    print(f"任务图结构错误：{error}", file=sys.stderr)  # 将失败类别和可读原因写入错误输出。
    return 6  # 不生成新图，也不覆盖已有输出。
  mermaid_text = render_mermaid(graph)  # 将已校验的任务图转换为 Mermaid 源码。
  if args.output is not None:  # 用户指定了输出文件时进入文件模式。
    try:  # 尝试写入用户指定的输出文件。
      write_mermaid_file(args.output, mermaid_text)  # 先写临时文件，再安全替换目标图。
    except OSError:  # 捕获目录不存在、无写入权限等文件系统错误。
      print("输出文件写入失败：请检查输出路径和写入权限。", file=sys.stderr)  # 向错误输出说明原因。
      return 3  # 以输出文件错误状态结束。
  else:  # 未指定输出文件时保持原有管道模式。
    sys.stdout.write(mermaid_text)  # 只向标准输出写入 Mermaid 源码。
  hard_count = sum(relation.kind == "hard" for relation in graph.relations)  # 统计实际画出的确定依赖。
  candidate_count = sum(relation.kind == "candidate" for relation in graph.relations)  # 统计实际画出的待确认关系。
  print(f"任务数：{len(graph.tasks)}，确定依赖数：{hard_count}，待确认关系数：{candidate_count}", file=sys.stderr)  # 成功后只向标准错误写摘要。
  for relation in graph.relations:  # 查看生成图中的每条关系。
    if relation.kind == "candidate":  # 只提示尚待确认的候选关系。
      reason = json.dumps(relation.reason, ensure_ascii=False)  # 转义换行等控制字符并保留中文。
      print(f"待确认关系 {relation.before} -> {relation.after}：{reason}", file=sys.stderr)  # 将诊断写入标准错误输出。
  for skipped in graph.skipped_relations:  # 逐条查看未画进图中的关系。
    relation = skipped.relation  # 取得该记录保存的原关系及两端任务编号。
    reason = json.dumps(skipped.skip_reason, ensure_ascii=False)  # 将跳过原因转成安全的单行文本。
    print(f"已跳过关系 {relation.before} -> {relation.after}：{reason}", file=sys.stderr)  # 只向标准错误输出关系及原因。
  return 0  # 成功生成后正常退出。