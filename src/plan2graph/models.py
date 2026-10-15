"""

任务图的内部数据结构；目前不包含提取或校验逻辑。

- GraphTask：一个任务，也就是图上的一个节点，例如 T1：订单接口。
- GraphRelation：两个任务之间的一条关系。它用 before、after 中的任务编号指向两端，例如 T1 → T2；kind 说明这是确定依赖还是待确认关系。
- SkippedRelation：一条考虑过、但不画出来的关系。它保存原关系和跳过原因。
- PlanGraph：装下整张图的容器，分别存放所有任务、要展示的关系、被跳过的关系。
例如，PlanGraph 可以有三个任务，其中“发布说明”没有连线；它仍留在 tasks 中。如果一条候选关系因冲突被跳过，就放进 skipped_relations，不放进 relations。这样“待确认但会画虚线”和“已跳过、不画线”不会混淆



"""

from dataclasses import dataclass  # 使用标准库定义存放数据的对象。
from typing import Literal  # 将关系类型限定为两个约定的名称。

"""
分别表示确定依赖和待确认关系。
hard 表示确定依赖，candidate 表示待确认关系。
"""
RelationKind = Literal["hard", "candidate"]  # 分别表示确定依赖和待确认关系。

@dataclass(frozen=True)  # 创建字段不能被重新赋值的任务对象。
class GraphTask:  # 表示图中的一个任务，包括没有连线的任务。
  id: str  # 程序以后分配的编号，例如 T1。
  title: str  # 简短的任务标题。
  source_quotes: tuple[str, ...]  # 支持保留重复任务合并前的多处原文。
  first_position: int  # 任务首次出现在输入原文中的位置，从 0 开始计数。


@dataclass(frozen=True)  # 创建字段不能被重新赋值的关系对象。
class GraphRelation:  # 表示一条将来可能画出的关系。
  before: str  # 前置任务的编号。
  after: str  # 后续任务的编号。
  kind: RelationKind  # 确定依赖或待确认关系。
  source_quote: str  # 涉及这条关系的输入原文。
  reason: str  # 确定依赖的依据，或待确认的问题。


@dataclass(frozen=True)  # 创建字段不能被重新赋值的跳过记录。
class SkippedRelation:  # 表示一条没有画进图中的关系。
  relation: GraphRelation  # 保存原本考虑的关系。
  skip_reason: str  # 记录为什么跳过，例如候选边会造成环。


@dataclass(frozen=True)  # 创建字段不能被重新赋值的完整任务图。
class PlanGraph:  # 分开存放所有任务、保留的关系和跳过记录。
  tasks: tuple[GraphTask, ...]  # 所有任务，包括没有连线的任务。
  relations: tuple[GraphRelation, ...]  # 将来可以展示的关系。
  skipped_relations: tuple[SkippedRelation, ...]  # 未展示的关系及原因。