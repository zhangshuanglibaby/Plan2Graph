"""检查内部数据结构能否表达任务图的基本情况。"""

from plan2graph.models import GraphRelation, GraphTask, PlanGraph, SkippedRelation  # 导入要测试的四个数据类。

def test_plan_graph_stores_tasks_and_relations() -> None:  # 检查一张图能同时保存不同状态的数据。
  tasks = (  # 准备四个任务，其中 T4 不参与任何关系。
    GraphTask("T1", "订单接口", ("实现订单接口",), 0),  # 创建第一个任务。
    GraphTask("T2", "支付对接", ("支付对接依赖订单接口",), 7),  # 创建第二个任务。
    GraphTask("T3", "监控配置", ("配置监控",), 20),  # 创建第三个任务。
    GraphTask("T4", "发布说明", ("编写发布说明",), 30),  # 创建没有连线的任务。
  )  # 结束任务列表。
  hard = GraphRelation("T1", "T2", "hard", "支付对接依赖订单接口", "支付对接需要订单接口")  # 保存一条确定关系。
  candidate = GraphRelation("T2", "T3", "candidate", "最好先完成支付对接再配置监控", "是否必须等待支付对接？")  # 保存一条待确认关系
  rejected = GraphRelation("T2", "T1", "candidate", "也许先做支付对接再实现订单接口", "需要核实顺序")  # 准备一条不展示的关系。
  skipped = SkippedRelation(rejected, "与 T1 指向 T2 的关系形成环；此处仅记录原因")  # 人工填写跳过原因，不执行环检测。
  graph = PlanGraph(tasks, (hard, candidate), (skipped,))  # 将任务和三种关系状态放入同一张图。

  assert len(graph.tasks) == 4  # 无连线的 T4 也应留在任务列表中。
  assert graph.tasks[3].id == "T4"  # 确认最后一个任务就是 T4。
  assert graph.relations == (hard, candidate)  # 只有确定和待确认关系列入可展示列表。
  assert graph.skipped_relations[0].relation == rejected  # 被跳过的关系单独保存。
  assert graph.skipped_relations[0].skip_reason != ""  # 跳过记录必须能装下原因。
  