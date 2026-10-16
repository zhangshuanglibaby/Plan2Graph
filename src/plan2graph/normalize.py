"""
检查引文是否出现在原文中；后续再处理重复任务、稳定编号，以及临时 ref 到任务编号的映射
"""

from plan2graph.models import GraphTask  # 使用内部任务的数据结构。
from plan2graph.response_models import ModelTask  # 使用已通过字段校验的模型任务。



"""查找任务引文在原计划中首次出现的位置"""
def find_task_quote_position(plan_text: str, source_quote: str) -> int:  # 查找任务引文在原计划中首次出现的位置
  if not source_quote.strip():  # 拒绝空字符串或只有空白的引文。
    raise ValueError("任务引文不能为空")  # 告诉调用方引文缺少内容。
  position = plan_text.find(source_quote)  # 按原样查找，不改动原文或引文。
  if position < 0:  # find 找不到片段时返回 -1。
    raise ValueError("任务引文不在原文中")  # 拒绝无法由原计划支持的引文。
  return position  # 返回从 0 开始计数的首次出现位置。



"""建立去重后的任务和 ref 对照表。"""
def build_tasks_and_ref_map(plan_text: str, model_tasks: list[ModelTask]) -> tuple[tuple[GraphTask, ...], dict[str, str]]:  # 建立去重后的任务和 ref 对照表。
  located: list[tuple[int, int, ModelTask]] = []  # 暂存原文位置、原列表顺序和任务。
  for index, task in enumerate(model_tasks):  # 逐个处理模型给出的任务。
    position = find_task_quote_position(plan_text, task.source_quote)  # 检查引文并找到首次出现的位置。
    located.append((position, index, task))  # 保存排序需要的信息。
  located.sort(key=lambda item: (item[0], item[1]))  # 先按原文位置排序，相同位置按原列表顺序排序。
  graph_tasks: list[GraphTask] = []  # 存放最终保留的任务。
  ref_to_id: dict[str, str] = {}  # 记录每个临时 ref 对应的编号。
  content_to_id: dict[tuple[str, str], str] = {}  # 记录每组“标题、引文”对应的编号。
  for position, _, task in located:  # 按排序后的顺序处理任务。
    if task.ref in ref_to_id:  # 检查临时 ref 是否已被其他任务使用。
      raise ValueError("重复的任务引用")  # 拒绝引用冲突。
    content_key = (task.title, task.source_quote)  # 用完全相同的标题和引文识别重复任务。
    if content_key in content_to_id:  # 检查该任务内容是否已经保留。
      ref_to_id[task.ref] = content_to_id[content_key]  # 将重复任务的 ref 指向已有编号。
      continue  # 不再新增一个图节点。
    task_id = f"T{len(graph_tasks) + 1}"  # 按实际保留的任务数量生成连续编号。
    graph_tasks.append(GraphTask(task_id, task.title, (task.source_quote,), position))  # 保存新任务及引文。
    ref_to_id[task.ref] = task_id  # 记录新任务的临时 ref。
    content_to_id[content_key] = task_id  # 记录该内容已对应的编号。
  return tuple(graph_tasks), ref_to_id  # 返回任务列表和引用对照表。
