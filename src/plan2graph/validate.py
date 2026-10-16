"""
放任务图的结构校验：检查整理好的图能不能成立。

负责检查整理后的结果。我们刚准备写的 validate_hard_acyclic，就是检查确定依赖有没有形成 T1 → T2 → T1 这样的环。
有环就报错，不能把它当作有效任务图
"""



from plan2graph.models import GraphRelation, GraphTask, SkippedRelation  # 使用任务、关系和跳过记录的数据结构。

"""
检查硬依赖是否形成环。
输入：
  - relations: 已经确定的关系集合
输出：
  - 是否形成环
"""
def validate_hard_acyclic(relations: tuple[GraphRelation, ...]) -> None:  # 检查硬依赖是否形成环。
  successors: dict[str, list[str]] = {}  # 记录每个任务后面连接了哪些任务。
  in_degree: dict[str, int] = {}  # 记录每个任务还需要多少个前置任务。
  for relation in relations:  # 逐条查看关系。
    if relation.kind != "hard":  # 候选关系暂时不参与硬依赖检查。
      continue  # 跳过这条候选关系。
    successors.setdefault(relation.before, []).append(relation.after)  # 记录关系的方向。
    in_degree.setdefault(relation.before, 0)  # 确保前置任务也在统计表中。
    in_degree[relation.after] = in_degree.get(relation.after, 0) + 1  # 后续任务多了一个前置任务。

  ready = [task_id for task_id, count in in_degree.items() if count == 0]  # 找出不需要等待的任务。
  processed = 0  # 记录能够依次处理的任务数。

  while ready:  # 只要还有不需要等待的任务，就继续处理。
    task_id = ready.pop()  # 取出一个当前可以处理的任务。
    processed += 1  # 将它计入已处理任务。
    for next_id in successors.get(task_id, []):  # 查看它后面的任务。
      in_degree[next_id] -= 1  # 前置任务已处理，等待数量减一。
      if in_degree[next_id] == 0:  # 检查后续任务是否已经无需等待。
        ready.append(next_id)  # 将它加入可处理任务。

  if processed != len(in_degree):  # 有任务始终无法处理，说明硬依赖绕成了环。
    raise ValueError("硬依赖存在环")  # 明确报告无效的图结构。

  


"""
  新增关系是否会形成环？
  输入：
   - relations: 已经确定的关系集合
   - new_relation: 新添加的关系
  输出：
   - 是否形成环
"""
def would_create_cycle(relations: tuple[GraphRelation, ...], new_relation: GraphRelation) -> bool:  # 判断新增关系是否会形成环。
  if new_relation.before == new_relation.after:  # 检查新关系是否直接连回自己。
    return True  # 自己指向自己就是环。

  successors: dict[str, list[str]] = {}  # 记录现有关系中每个任务后面连接的任务。
  for relation in relations:  # 遍历已经决定保留的关系。
    successors.setdefault(relation.before, []).append(relation.after)  # 按关系方向记录连接。

  visited: set[str] = set()  # 记录已经查找过的任务，避免反复查找。
  pending = [new_relation.after]  # 从新关系的终点开始，向后寻找。
  while pending:  # 还有任务可查找时继续。
    task_id = pending.pop()  # 取出一个待查找的任务。
    if task_id == new_relation.before:  # 如果能走回新关系的起点。
      return True  # 加上新关系就会形成环。
    if task_id in visited:  # 检查这个任务是否已经查找过。
      continue  # 已查找过就跳过。
    visited.add(task_id)  # 标记当前任务已经查找过。
    pending.extend(successors.get(task_id, []))  # 接着查找它后面的任务。

  return False  # 无法走回起点，新增关系不会形成环。




"""
筛选不会使展示图成环的候选关系。
输入：
  - tasks: 任务集合
  - relations: 已经确定的关系集合
输出：
  - 展示关系集合
  - 跳过记录集合
"""
def resolve_candidate_relations(tasks: tuple[GraphTask, ...], relations: tuple[GraphRelation, ...]) -> tuple[tuple[GraphRelation, ...], tuple[SkippedRelation, ...]]:  # 筛选不会使展示图成环的候选关系。
  if not tasks:  # 没有任何任务时，不能生成一张看似成功的空图。
    raise ValueError("任务列表不能为空")  # 明确报告空任务图。
  validate_hard_acyclic(relations)  # 硬依赖本身有环时直接报错。
  task_order = {task.id: (task.first_position, index) for index, task in enumerate(tasks)}  # 记录原文位置及任务编号顺序。
  for relation in relations:  # 检查每条关系是否指向已有任务。
    if relation.before not in task_order or relation.after not in task_order:  # 任意一端不存在都不能继续。
      raise ValueError("关系端点不存在于任务图")  # 明确报告无效端点。
  kept = [relation for relation in relations if relation.kind == "hard"]  # 先保留所有硬依赖。
  candidates = sorted(  # 按稳定顺序安排待检查的候选关系。
    (relation for relation in relations if relation.kind == "candidate"),  # 只挑出候选关系。
    key=lambda relation: (task_order[relation.before], task_order[relation.after]),  # 先比较原文位置，同位置比较任务编号顺序。
  )  # 完成排序。
  skipped: list[SkippedRelation] = []  # 收集不能画出的候选关系及原因。
  for relation in candidates:  # 按排序结果逐条尝试加入候选关系。
    if would_create_cycle(tuple(kept), relation):  # 检查它与已保留关系合起来是否成环。
      skipped.append(SkippedRelation(relation, "候选关系会使展示图成环"))  # 保存被跳过的关系和原因。
      continue  # 不把这条关系加入展示图。
    kept.append(relation)  # 没有成环，就保留这条候选关系。
  return tuple(kept), tuple(skipped)  # 分别返回展示关系和跳过记录。
