import pytest  # 用于检查预期发生的错误。

from plan2graph.models import GraphRelation, GraphTask  # 使用任务和关系的数据结构。
from plan2graph.validate import resolve_candidate_relations, validate_hard_acyclic, would_create_cycle  # 导入候选关系筛选及环检查函数。



"""正常的依赖链应当通过检查。"""
def test_hard_chain_has_no_cycle() -> None:  # 正常的依赖链应当通过检查。
  relations = (  # 准备 T1 到 T2 再到 T3 的关系。
    GraphRelation("T1", "T2", "hard", "先完成T1", "T2依赖T1"),  # 第一条硬依赖。
    GraphRelation("T2", "T3", "hard", "再完成T2", "T3依赖T2"),  # 第二条硬依赖。
  )  # 结束关系列表。
  validate_hard_acyclic(relations)  # 不抛出错误就表示这项测试通过。



"""绕回起点的硬依赖应当报错。"""
def test_hard_cycle_is_rejected() -> None:  # 绕回起点的硬依赖应当报错。
  relations = (  # 准备 T1 到 T2、T2 又到 T1 的关系。
    GraphRelation("T1", "T2", "hard", "T2依赖T1", "第一条依赖"),  # 第一条硬依赖。
    GraphRelation("T2", "T1", "hard", "T1依赖T2", "第二条依赖"),  # 第二条硬依赖。
  )  # 结束关系列表。
  with pytest.raises(ValueError, match="硬依赖存在环"):  # 预期得到明确的环错误。
    validate_hard_acyclic(relations)  # 检查这组无法成立的依赖。



"""候选关系不应被当作确定依赖。"""
def test_candidate_does_not_create_hard_cycle() -> None:  # 候选关系不应被当作确定依赖。
  relations = (  # 准备一条硬依赖和一条反方向的候选关系。
    GraphRelation("T1", "T2", "hard", "T2依赖T1", "确定依赖"),  # T1 到 T2 是硬依赖。
    GraphRelation("T2", "T1", "candidate", "也许先做T2", "顺序待确认"),  # 反方向关系仍待确认。
  )  # 结束关系列表。
  validate_hard_acyclic(relations)  # 此处不应报“硬依赖存在环”。



"""
检查新增关系是否会形成环。
"""
def test_new_relation_can_close_a_cycle() -> None:  # 检查新增关系会不会绕回起点。
  existing = (  # 准备已经保留的两条硬依赖。
    GraphRelation("T1", "T2", "hard", "T2依赖T1", "确定依赖"),  # 现有关系从 T1 指向 T2。
    GraphRelation("T2", "T3", "hard", "T3依赖T2", "确定依赖"),  # 现有关系从 T2 指向 T3。
  )  # 结束现有关系。
  proposed = GraphRelation("T3", "T1", "candidate", "也许先做T3", "顺序待确认")  # 准备从 T3 返回 T1 的候选关系。
  assert would_create_cycle(existing, proposed) is True  # 加上它会形成 T1 到 T2 到 T3 再到 T1 的环。



"""
检查不会形成环的新增关系。
"""
def test_new_relation_can_keep_graph_acyclic() -> None:  # 检查不会形成环的新增关系。
  existing = (GraphRelation("T1", "T2", "hard", "T2依赖T1", "确定依赖"),)  # 现有关系从 T1 指向 T2。
  proposed = GraphRelation("T1", "T3", "candidate", "也许先做T1", "顺序待确认")  # 准备从 T1 指向 T3 的候选关系。
  assert would_create_cycle(existing, proposed) is False  # 没有返回起点的路线，因此不形成环。




"""
检查候选关系逐条加入后的结果。
"""
def test_conflicting_candidate_is_skipped() -> None:  # 检查候选关系逐条加入后的结果。
  tasks = (  # 准备按原文顺序排列的三个任务。
    GraphTask("T1", "任务A", ("任务A",), 0),  # 第一个任务。
    GraphTask("T2", "任务B", ("任务B",), 1),  # 第二个任务。
    GraphTask("T3", "任务C", ("任务C",), 2),  # 第三个任务。
  )  # 结束任务列表。
  relations = (  # 准备一条硬依赖和两条候选关系。
    GraphRelation("T1", "T2", "hard", "B依赖A", "确定依赖"),  # 硬依赖从 T1 指向 T2。
    GraphRelation("T2", "T3", "candidate", "也许先做B", "顺序待确认"),  # 这条候选关系可以保留。
    GraphRelation("T3", "T1", "candidate", "也许先做C", "顺序待确认"),  # 这条候选关系会使展示图成环。
  )  # 结束关系列表。
  kept, skipped = resolve_candidate_relations(tasks, relations)  # 筛选最终展示的关系。
  assert [(item.before, item.after) for item in kept] == [("T1", "T2"), ("T2", "T3")]  # 检查保留下来的关系。
  assert len(skipped) == 1  # 检查恰好跳过一条关系。
  assert (skipped[0].relation.before, skipped[0].relation.after) == ("T3", "T1")  # 检查跳过的是成环的候选关系。
  assert skipped[0].skip_reason == "候选关系会使展示图成环"  # 检查跳过原因。




"""
检查候选关系的处理顺序稳定。
"""
def test_candidates_use_source_order_not_input_order() -> None:  # 检查候选关系的处理顺序稳定。
  tasks = (  # 准备两个有明确原文位置的任务。
    GraphTask("T1", "任务A", ("任务A",), 0),  # T1 在原文中先出现。
    GraphTask("T2", "任务B", ("任务B",), 10),  # T2 在原文中后出现。
  )  # 结束任务列表。
  relations = (  # 故意把反方向关系放在输入列表前面。
    GraphRelation("T2", "T1", "candidate", "也许先做B", "顺序待确认"),  # 输入中的第一条候选关系。
    GraphRelation("T1", "T2", "candidate", "也许先做A", "顺序待确认"),  # 原文位置更早的任务作为起点。
  )  # 结束关系列表。
  kept, skipped = resolve_candidate_relations(tasks, relations)  # 按任务原文位置筛选关系。
  assert [(item.before, item.after) for item in kept] == [("T1", "T2")]  # 先保留从 T1 出发的关系。
  assert [(item.relation.before, item.relation.after) for item in skipped] == [("T2", "T1")]  # 反方向关系随后因成环被跳过。





"""
空任务图不能通过结构检查。
"""
def test_empty_tasks_are_rejected() -> None:  # 空任务图不能通过结构检查。
  with pytest.raises(ValueError, match="任务列表不能为空"):  # 预期收到明确错误。
    resolve_candidate_relations((), ())  # 用空任务和空关系尝试生成图。