
from plan2graph.models import PlanGraph  # 使用现有的任务图数据结构。




"""
将任务标题转换为可放入 Mermaid 引号中的文字。
输入：
  - text: 任务标题
输出：
  - 转换后的文字
"""
def escape_mermaid_label(text: str) -> str:  # 将任务标题转换为可放入 Mermaid 引号中的文字。
  pieces: list[str] = []  # 逐个保存处理后的字符。
  for character in text:  # 依次检查标题中的每个字符。
    if character.isspace() and character != " ":  # 检查换行、制表符等非普通空格。
      pieces.append(" ")  # 用普通空格代替，避免拆开图语句。
    elif ord(character) < 32 or ord(character) == 127:  # 检查其他不可见控制字符。
      pieces.append(" ")  # 不让控制字符进入图语句。
    elif character in '&"<>[]#`':  # 检查可能影响标签解析的特殊字符。
      pieces.append(f"#{ord(character)};")  # 转成 Mermaid 支持的数字字符编码。
    else:  # 其余字符不需要转换。
      pieces.append(character)  # 保留原字符，包括中文。
  return "".join(pieces)  # 合并处理后的字符。





"""
将任务图逐步转换为 Mermaid 文本。
输入：
  - graph: 任务图
输出：
  - 转换后的 Mermaid 文本
"""
def render_mermaid(graph: PlanGraph) -> str:  # 将任务图逐步转换为 Mermaid 文本。
  lines = ["flowchart LR"]  # 第一行声明从左到右的流程图。
  for task in sorted(graph.tasks, key=lambda item: (item.first_position, int(item.id[1:]))):  # 先按原文位置排序；位置相同时按 T 后面的编号排序。
    label = escape_mermaid_label(task.title)  # 转义节点标题中的特殊字符。
    lines.append(f'  {task.id}["{label}"]')  # 添加带编号和标题的节点行。
  for relation in sorted(graph.relations, key=lambda item: (int(item.before[1:]), int(item.after[1:]), item.kind != "hard")):  # 依次按起点、终点的数字编号排序；两端相同时先输出确定依赖。
    if relation.kind == "hard":  # 这一步只处理确定依赖。
      lines.append(f"  {relation.before} --> {relation.after}")  # 输出从前置任务指向后续任务的实线箭头。
    elif relation.kind == "candidate":  # 待确认关系使用另一种箭头，不当作确定依赖。
      lines.append(f"  {relation.before} -.-> {relation.after}")  # 输出从前置候选任务指向后续任务的虚线箭头。
  return "\n".join(lines) + "\n"  # 合并各行，并保留文件末尾换行。