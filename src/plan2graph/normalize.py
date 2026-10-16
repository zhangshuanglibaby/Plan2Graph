"""
检查引文是否出现在原文中；后续再处理重复任务、稳定编号，以及临时 ref 到任务编号的映射
"""

from plan2graph.models import GraphRelation, GraphTask, SkippedRelation  # 使用内部任务、关系和跳过记录的数据结构。
from plan2graph.response_models import ModelRelation, ModelTask  # 使用已通过字段校验的模型关系和任务。



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



"""将关系两端的临时 ref 转成任务编号。"""
def map_relation_to_graph(model_relation: ModelRelation, ref_to_id: dict[str, str]) -> GraphRelation:  # 将关系两端的临时 ref 转成任务编号。
  if model_relation.before not in ref_to_id:  # 检查前置任务是否存在。
    raise ValueError(f"前置任务引用不存在：{model_relation.before}")  # 报告找不到的前置 ref。
  if model_relation.after not in ref_to_id:  # 检查后续任务是否存在。
    raise ValueError(f"后续任务引用不存在：{model_relation.after}")  # 报告找不到的后续 ref。
  if model_relation.before == model_relation.after:  # 检查关系是否把同一个任务连向自己。
    raise ValueError("任务不能依赖自身")  # 对直接自依赖给出明确错误。
  return GraphRelation(  # 建立使用稳定编号的内部关系。
    before=ref_to_id[model_relation.before],  # 转换前置任务编号。
    after=ref_to_id[model_relation.after],  # 转换后续任务编号。
    kind=model_relation.kind,  # 保留关系类型。
    source_quote=model_relation.source_quote,  # 保留关系引文。
    reason=model_relation.reason,  # 保留关系依据。
  )



"""转换关系并去除同向同类型的重复项。"""
def build_graph_relations(model_relations: list[ModelRelation], ref_to_id: dict[str, str]) -> tuple[tuple[GraphRelation, ...], tuple[SkippedRelation, ...]]:  # 返回保留的关系和跳过记录。
  graph_relations: list[GraphRelation] = []  # 保存可以继续处理的关系。
  skipped_relations: list[SkippedRelation] = []  # 保存因任务合并而跳过的关系。
  seen: set[tuple[str, str, str]] = set()  # 记录已出现的关系方向和类型。
  for model_relation in model_relations:  # 按模型返回的顺序逐条处理。
    graph_relation = map_relation_to_graph(model_relation, ref_to_id)  # 把临时 ref 换成任务编号。
    if graph_relation.before == graph_relation.after:  # 检查不同 ref 合并后是否指向同一个任务。
      skipped_relations.append(SkippedRelation(graph_relation, "任务合并后形成自依赖"))  # 保存未画出的关系及原因。
      continue  # 不把这条自依赖加入可展示的关系。
    key = (graph_relation.before, graph_relation.after, graph_relation.kind)  # 用方向和类型识别重复关系。
    if key in seen:  # 检查是否已保留相同关系。
      continue  # 重复时保留先出现的关系。
    seen.add(key)  # 记录这条关系已经出现。
    graph_relations.append(graph_relation)  # 保存第一次出现的关系。
  return tuple(graph_relations), tuple(skipped_relations)  # 分别返回保留结果和跳过记录。。