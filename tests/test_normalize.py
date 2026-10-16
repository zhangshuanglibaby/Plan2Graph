import pytest  # 使用 pytest 检查预期出现的错误。

from plan2graph.normalize import build_graph_relations, build_tasks_and_ref_map, find_task_quote_position, map_relation_to_graph  # 导入关系去重、任务处理和引文检查函数。
from plan2graph.response_models import ModelRelation, ModelTask  # 创建测试所需的模型任务和关系。


"""检查能找到引文的位置。"""
def test_finds_quote_position() -> None:  # 检查能找到引文的位置。
  assert find_task_quote_position("先做A，再做B", "B") == 6  # B 从第 6 个位置开始。


"""检查不存在于原文的引文会被拒绝。"""
def test_rejects_quote_not_in_plan() -> None:  # 检查不存在于原文的引文会被拒绝。
  with pytest.raises(ValueError, match="任务引文不在原文中"):  # 预期收到明确错误。
    find_task_quote_position("先做A", "先做B")  # 提供原文中没有的片段。


"""检查只有空格的引文会被拒绝。"""
def test_rejects_blank_quote() -> None:  # 检查只有空格的引文会被拒绝。
  with pytest.raises(ValueError, match="任务引文不能为空"):  # 预期收到明确错误。
    find_task_quote_position("先做A", "   ")  # 提供没有实际内容的引文。


"""检查编号按原文位置生成。"""
def test_tasks_are_numbered_in_source_order() -> None:  # 检查编号按原文位置生成。
  plan_text = "先实现接口，再编写文档"  # 准备包含两个任务的原文。
  model_tasks = [  # 故意让模型返回顺序与原文顺序相反。
    ModelTask(ref="doc", title="编写文档", source_quote="编写文档"),  # 文档任务排在返回列表前面。
    ModelTask(ref="api", title="实现接口", source_quote="实现接口"),  # 接口任务在原文中先出现。
  ]
  graph_tasks, ref_to_id = build_tasks_and_ref_map(plan_text, model_tasks)  # 整理任务并生成编号。
  assert [(task.id, task.title) for task in graph_tasks] == [("T1", "实现接口"), ("T2", "编写文档")]  # 检查原文顺序和编号。
  assert ref_to_id == {"api": "T1", "doc": "T2"}  # 检查临时引用与编号的对照。
  assert graph_tasks[0].source_quotes == ("实现接口",)  # 检查原文引文被保留。


"""检查位置相同时顺序保持稳定。"""
def test_same_position_keeps_model_order() -> None:  # 检查位置相同时顺序保持稳定。
  model_tasks = [  # 准备两项共用同一段引文的任务。
    ModelTask(ref="a", title="任务甲", source_quote="开发"),  # 第一项任务。
    ModelTask(ref="b", title="任务乙", source_quote="开发"),  # 第二项任务。
  ]
  graph_tasks, _ = build_tasks_and_ref_map("开发", model_tasks)  # 根据同一段原文建立任务列表。
  assert [task.title for task in graph_tasks] == ["任务甲", "任务乙"]  # 检查原返回顺序未被打乱。


"""检查两个任务不能共用同一个临时引用。"""
def test_duplicate_task_ref_is_rejected() -> None:  # 检查两个任务不能共用同一个临时引用。
  model_tasks = [  # 准备引用冲突的任务。
    ModelTask(ref="a", title="接口", source_quote="接口"),  # 第一项使用引用 a。
    ModelTask(ref="a", title="文档", source_quote="文档"),  # 第二项也使用引用 a。
  ]
  with pytest.raises(ValueError, match="重复的任务引用"):  # 预期收到明确错误。
    build_tasks_and_ref_map("接口和文档", model_tasks)  # 尝试建立有冲突的任务列表。


"""检查完全相同的任务合并为一个节点。"""
def test_identical_tasks_share_one_node() -> None:  # 检查完全相同的任务合并为一个节点。
  model_tasks = [  # 准备两个重复任务和一个独立任务。
    ModelTask(ref="doc", title="编写文档", source_quote="编写文档"),  # 独立的文档任务。
    ModelTask(ref="api1", title="实现接口", source_quote="实现接口"),  # 第一个接口任务。
    ModelTask(ref="api2", title="实现接口", source_quote="实现接口"),  # 内容相同但 ref 不同的接口任务。
  ]
  graph_tasks, ref_to_id = build_tasks_and_ref_map("实现接口后编写文档", model_tasks)  # 整理任务。
  assert [(task.id, task.title) for task in graph_tasks] == [("T1", "实现接口"), ("T2", "编写文档")]  # 检查只留下两个节点。
  assert ref_to_id == {"api1": "T1", "api2": "T1", "doc": "T2"}  # 检查两个旧 ref 都指向合并后的节点。


"""检查同名但引文不同的任务不会被误合并。"""
def test_same_title_with_different_quotes_stays_separate() -> None:  # 检查同名但引文不同的任务不会被误合并。
  model_tasks = [  # 准备两个同名任务。
      ModelTask(ref="a", title="实现接口", source_quote="接口A"),  # 第一个任务引用接口 A。
      ModelTask(ref="b", title="实现接口", source_quote="接口B"),  # 第二个任务引用接口 B。
  ]
  graph_tasks, ref_to_id = build_tasks_and_ref_map("实现接口A，再实现接口B", model_tasks)  # 整理任务。
  assert [task.id for task in graph_tasks] == ["T1", "T2"]  # 检查两个节点都保留下来。
  assert ref_to_id == {"a": "T1", "b": "T2"}  # 检查它们有各自的编号。



def test_repeated_build_is_stable_and_keeps_all_tasks() -> None:  # 检查相同输入得到相同结果，且任务不会因没有关系线而消失。
  plan_text = "接口和文档"  # 准备包含两个独立任务的原文。
  model_tasks = [  # 准备两个没有设置关系线的任务。
    ModelTask(ref="api", title="接口", source_quote="接口"),  # 第一个任务位于原文开头。
    ModelTask(ref="doc", title="文档", source_quote="文档"),  # 第二个任务位于原文后面。
  ]
  first = build_tasks_and_ref_map(plan_text, model_tasks)  # 第一次处理相同输入。
  second = build_tasks_and_ref_map(plan_text, model_tasks)  # 第二次处理相同输入。
  assert first == second  # 检查两次产生完全相同的任务和编号对照。
  assert [(task.id, task.first_position) for task in first[0]] == [("T1", 0), ("T2", 3)]  # 检查两个任务及原文位置都保留下来。


"""检查关系方向和任务编号转换。"""
def test_relation_direction_uses_task_ids() -> None:  # 检查关系方向和任务编号转换。
  plan_text = "任务A依赖任务B"  # 原文表示 B 是 A 的前置任务。
  model_tasks = [  # 准备原文中的两个任务。
      ModelTask(ref="a", title="任务A", source_quote="任务A"),  # A 在原文中先出现，编号应为 T1。
      ModelTask(ref="b", title="任务B", source_quote="任务B"),  # B 在原文中后出现，编号应为 T2。
  ]
  _, ref_to_id = build_tasks_and_ref_map(plan_text, model_tasks)  # 取得临时 ref 与任务编号的对照。
  model_relation = ModelRelation(before="b", after="a", kind="hard", source_quote=plan_text, reason="原文明确依赖")  # 指明 B 必须先于 A。
  graph_relation = map_relation_to_graph(model_relation, ref_to_id)  # 将关系两端换成任务编号。
  assert (graph_relation.before, graph_relation.after, graph_relation.kind) == ("T2", "T1", "hard")  # 检查方向是 B 到 A。
  assert graph_relation.source_quote == plan_text  # 检查引文仍被保留。


"""检查任务合并后指向同一对节点的关系只保留一次。"""
def test_duplicate_relations_after_task_merge_keep_first() -> None:  # 检查任务合并后指向同一对节点的关系只保留一次。
  ref_to_id = {"setup": "T1", "api1": "T2", "api2": "T2"}  # 两个接口 ref 都指向合并后的 T2。
  model_relations = [  # 准备两条转换后方向相同的确定依赖。
    ModelRelation(before="setup", after="api1", kind="hard", source_quote="先完成基础再做接口", reason="第一处依据"),  # 第一条关系。
    ModelRelation(before="setup", after="api2", kind="hard", source_quote="基础是接口前提", reason="第二处依据"),  # 第二条关系。
  ]
  graph_relations = build_graph_relations(model_relations, ref_to_id)  # 转换编号并去重。
  assert len(graph_relations) == 1  # 检查只保留一条关系。
  assert (graph_relations[0].before, graph_relations[0].after, graph_relations[0].kind) == ("T1", "T2", "hard")  # 检查方向和类型。
  assert graph_relations[0].source_quote == "先完成基础再做接口"  # 检查保留先出现的关系引文。