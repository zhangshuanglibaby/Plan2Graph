from plan2graph.mermaid import escape_mermaid_label  # 导入当前要测试的标签转义函数。
import plan2graph.mermaid as mermaid  # 导入整个模块，以便测试下一步要实现的输出函数。
from plan2graph.models import GraphRelation, GraphTask, PlanGraph, SkippedRelation  # 导入任务图及被跳过关系的数据结构。
from plan2graph.normalize import build_plan_graph  # 导入将结构化结果整理成任务图的函数。
from plan2graph.response_models import ModelRelation, ModelResult, ModelTask  # 导入手工构造结构化结果所需的类型。



"""
检查中英混合标题及特殊字符的处理结果
"""
def test_escape_mermaid_label_handles_special_characters() -> None:  # 检查中英混合标题及特殊字符的处理结果
  text = '开发["API"]\n联调 & 验收'  # 准备含引号、方括号、换行和 & 的标题。
  assert escape_mermaid_label(text) == '开发#91;#34;API#34;#93; 联调 #38; 验收'  # 核对数字字符编码及换行替换后的完整文字。






"""
检查另一组特殊字符和制表符。
"""
def test_escape_mermaid_label_handles_remaining_symbols_and_tab() -> None:  # 检查另一组特殊字符和制表符。
  text = "确认<配置>#1`阶段\t交付"  # 准备含尖括号、井号、反引号和制表符的标题。
  assert escape_mermaid_label(text) == "确认#60;配置#62;#35;1#96;阶段 交付"  # 检查特殊字符编码及制表符替换为空格。





"""
检查没有连线的任务仍会输出为节点。
"""
def test_render_mermaid_keeps_single_unconnected_task() -> None:  # 检查没有连线的任务仍会输出为节点。
  task = GraphTask("T1", "完成接口", ("完成接口",), 0)  # 创建一个编号为 T1 的任务。
  graph = PlanGraph((task,), (), ())  # 创建只有这个任务、没有关系和跳过记录的图。
  assert mermaid.render_mermaid(graph) == 'flowchart LR\n  T1["完成接口"]\n'  # 检查完整输出及末尾换行。




"""
检查节点按原文出现位置输出。
"""
def test_render_mermaid_orders_nodes_by_source_position() -> None:  # 检查节点按原文出现位置输出。
  earlier = GraphTask("T1", "实现接口", ("实现接口",), 0)  # 创建原文中先出现的任务。
  later = GraphTask("T2", "编写文档", ("编写文档",), 5)  # 创建原文中后出现的任务。
  graph = PlanGraph((later, earlier), (), ())  # 故意以相反顺序传入两个任务。
  assert mermaid.render_mermaid(graph) == 'flowchart LR\n  T1["实现接口"]\n  T2["编写文档"]\n'  # 检查输出仍按原文位置排列。






"""
检查确定依赖输出为实线箭头。
"""
def test_render_mermaid_outputs_hard_relation() -> None:  # 检查确定依赖输出为实线箭头。
  first = GraphTask("T1", "完成接口", ("完成接口",), 0)  # 创建前置任务。
  second = GraphTask("T2", "联调", ("联调",), 5)  # 创建依赖前置任务的后续任务。
  relation = GraphRelation("T1", "T2", "hard", "联调依赖完成接口", "接口是联调的前提")  # 创建 T1 指向 T2 的确定依赖。
  graph = PlanGraph((first, second), (relation,), ())  # 将两个任务和一条关系组成图。
  expected = 'flowchart LR\n  T1["完成接口"]\n  T2["联调"]\n  T1 --> T2\n'  # 约定先声明节点，再输出实线箭头。
  assert mermaid.render_mermaid(graph) == expected  # 核对完整 Mermaid 文本。





"""
检查待确认关系输出为虚线箭头。
"""
def test_render_mermaid_outputs_candidate_relation() -> None:  # 检查待确认关系输出为虚线箭头。
  first = GraphTask("T1", "用户模型", ("用户模型",), 0)  # 创建可能需要先完成的任务。
  second = GraphTask("T2", "配置等级", ("配置等级",), 5)  # 创建可能依赖前一任务的任务。
  relation = GraphRelation("T1", "T2", "candidate", "最好先完成用户模型再配置等级", "是否必须等待尚待确认")  # 创建待确认关系。
  graph = PlanGraph((first, second), (relation,), ())  # 组成含一条待确认关系的图。
  expected = 'flowchart LR\n  T1["用户模型"]\n  T2["配置等级"]\n  T1 -.-> T2\n'  # 约定虚线箭头的完整输出。
  assert mermaid.render_mermaid(graph) == expected  # 核对待确认关系没有被画成实线。






"""
检查关系线按起点任务编号稳定输出。
"""
def test_render_mermaid_orders_relations_by_start_task() -> None:  # 检查关系线按起点任务编号稳定输出。
  first = GraphTask("T1", "接口", ("接口",), 0)  # 创建第一个任务。
  second = GraphTask("T2", "数据", ("数据",), 5)  # 创建第二个任务。
  third = GraphTask("T3", "联调", ("联调",), 10)  # 创建共同依赖前两个任务的任务。
  from_second = GraphRelation("T2", "T3", "hard", "联调依赖数据", "数据是前提")  # 准备起点较后的关系。
  from_first = GraphRelation("T1", "T3", "hard", "联调依赖接口", "接口是前提")  # 准备起点较前的关系。
  graph = PlanGraph((first, second, third), (from_second, from_first), ())  # 故意把关系按相反顺序传入。
  expected = 'flowchart LR\n  T1["接口"]\n  T2["数据"]\n  T3["联调"]\n  T1 --> T3\n  T2 --> T3\n'  # 约定节点之后按起点编号输出关系。
  assert mermaid.render_mermaid(graph) == expected  # 核对输出不受关系传入顺序影响。




"""
检查冲突候选关系不会被画出。
"""
def test_render_mermaid_omits_skipped_relation() -> None:  # 检查冲突候选关系不会被画出。
  first = GraphTask("T1", "接口", ("接口",), 0)  # 创建前置任务。
  second = GraphTask("T2", "联调", ("联调",), 5)  # 创建后续任务。
  hard = GraphRelation("T1", "T2", "hard", "联调依赖接口", "确定依赖")  # 创建应当显示的实线关系。
  conflicting = GraphRelation("T2", "T1", "candidate", "也许先联调", "顺序待确认")  # 创建会与实线形成环的候选关系。
  skipped = SkippedRelation(conflicting, "候选关系会使展示图成环")  # 记录该候选关系已被跳过。
  graph = PlanGraph((first, second), (hard,), (skipped,))  # 只把实线放进待展示关系列表。
  expected = 'flowchart LR\n  T1["接口"]\n  T2["联调"]\n  T1 --> T2\n'  # 图中不应出现反方向虚线。
  assert mermaid.render_mermaid(graph) == expected  # 检查跳过记录没有被当成待展示关系。





"""
检查节点输出确实使用了标签转义函数。
"""
def test_render_mermaid_escapes_node_title() -> None:  # 检查节点输出确实使用了标签转义函数。
  title = '完成["订单"]\n接口'  # 准备含方括号、引号和换行的任务标题。
  task = GraphTask("T1", title, (title,), 0)  # 用该标题创建任务节点。
  graph = PlanGraph((task,), (), ())  # 创建没有关系线的单节点图。
  expected = 'flowchart LR\n  T1["完成#91;#34;订单#34;#93; 接口"]\n'  # 约定转义后的完整输出。
  assert mermaid.render_mermaid(graph) == expected  # 检查特殊字符没有原样进入节点语句。







"""
检查混合关系和孤立节点的完整输出。
"""
def test_render_mermaid_combines_relations_and_isolated_task() -> None:  # 检查混合关系和孤立节点的完整输出。
  first = GraphTask("T1", "接口", ("接口",), 0)  # 创建第一个任务。
  second = GraphTask("T2", "数据", ("数据",), 5)  # 创建第二个任务。
  third = GraphTask("T3", "联调", ("联调",), 10)  # 创建接收两条关系的任务。
  isolated = GraphTask("T4", "文档", ("文档",), 15)  # 创建没有连线但仍需显示的任务。
  hard = GraphRelation("T1", "T3", "hard", "联调依赖接口", "确定依赖")  # 创建实线关系。
  candidate = GraphRelation("T2", "T3", "candidate", "也许先准备数据", "待确认")  # 创建虚线关系。
  graph = PlanGraph((isolated, third, second, first), (candidate, hard), ())  # 故意打乱节点和关系的传入顺序。
  expected = 'flowchart LR\n  T1["接口"]\n  T2["数据"]\n  T3["联调"]\n  T4["文档"]\n  T1 --> T3\n  T2 -.-> T3\n'  # 约定先输出全部节点，再按顺序输出两种箭头。
  assert mermaid.render_mermaid(graph) == expected  # 核对孤立节点保留且实线、虚线没有混淆。






"""
检查一个前置任务可以指向两个后续任务。
"""
def test_render_mermaid_outputs_fork() -> None:  # 检查一个前置任务可以指向两个后续任务。
  first = GraphTask("T1", "接口", ("接口",), 0)  # 创建共同的前置任务。
  second = GraphTask("T2", "文档", ("文档",), 5)  # 创建第一个后续任务。
  third = GraphTask("T3", "联调", ("联调",), 10)  # 创建第二个后续任务。
  to_second = GraphRelation("T1", "T2", "hard", "文档依赖接口", "确定依赖")  # 创建指向文档的关系。
  to_third = GraphRelation("T1", "T3", "hard", "联调依赖接口", "确定依赖")  # 创建指向联调的关系。
  graph = PlanGraph((first, second, third), (to_third, to_second), ())  # 故意反向传入两条关系以检查排序。
  expected = 'flowchart LR\n  T1["接口"]\n  T2["文档"]\n  T3["联调"]\n  T1 --> T2\n  T1 --> T3\n'  # 约定两条箭头都从 T1 出发。
  assert mermaid.render_mermaid(graph) == expected  # 检查没有凭空添加 T2 与 T3 之间的关系。




"""
检查编号和箭头方向在两个模块衔接后仍然正确。
"""
def test_render_mermaid_from_normalized_result() -> None:  # 检查编号和箭头方向在两个模块衔接后仍然正确。
  plan_text = "联调依赖接口"  # 原文先提到联调，后提到接口。
  api = ModelTask(ref="api", title="接口", source_quote="接口")  # 用临时引用表示接口任务。
  integration = ModelTask(ref="integration", title="联调", source_quote="联调")  # 用临时引用表示联调任务。
  relation = ModelRelation(before="api", after="integration", kind="hard", source_quote=plan_text, reason="联调依赖接口")  # 表示接口必须先于联调。
  result = ModelResult(tasks=[api, integration], relations=[relation])  # 手工构造结果，不调用 DeepSeek。
  graph = build_plan_graph(plan_text, result)  # 按原文位置编号，并将关系的临时引用转换为编号。
  expected = 'flowchart LR\n  T1["联调"]\n  T2["接口"]\n  T2 --> T1\n'  # 接口虽编号为 T2，仍是箭头起点。
  assert mermaid.render_mermaid(graph) == expected  # 核对最终 Mermaid 文本。







"""
检查三个任务组成的依赖链。
"""
def test_render_mermaid_outputs_chain() -> None:  # 检查三个任务组成的依赖链。
  first = GraphTask("T1", "设计", ("设计",), 0)  # 创建链的起点。
  second = GraphTask("T2", "开发", ("开发",), 2)  # 创建链的中间任务。
  third = GraphTask("T3", "验收", ("验收",), 4)  # 创建链的终点。
  first_edge = GraphRelation("T1", "T2", "hard", "设计后开发", "设计先完成")  # 连接起点和中间任务。
  second_edge = GraphRelation("T2", "T3", "hard", "开发后验收", "开发先完成")  # 连接中间任务和终点。
  graph = PlanGraph((first, second, third), (second_edge, first_edge), ())  # 倒序传入关系以同时检查输出排序。
  expected = 'flowchart LR\n  T1["设计"]\n  T2["开发"]\n  T3["验收"]\n  T1 --> T2\n  T2 --> T3\n'  # 写出预期的完整链。
  assert mermaid.render_mermaid(graph) == expected  # 核对两个箭头的方向和顺序。