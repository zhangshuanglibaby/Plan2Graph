"""
定义模型返回数据的字段；目前不调用模型。
检查模型返回的字段和类型是否符合格式
"""

from typing import Literal  # 限定关系类型只能使用约定的名称。

from pydantic import BaseModel, ConfigDict  # 导入数据模型和校验配置。

# 定义关系类型，避免写错。
class StrictFields(BaseModel):  # 给下面三个数据模型共用严格规则。
  model_config = ConfigDict(strict=True, extra="forbid")  # 不转换错误类型，也不接受未约定的字段。

"""模型任务"""
class ModelTask(StrictFields):  # 表示模型提出的一个任务。
  ref: str  # 本次响应内的临时任务引用。
  title: str  # 简短的任务标题。
  source_quote: str  # 输入计划中的任务原文片段。


"""模型关系"""
class ModelRelation(StrictFields):  # 表示模型提出的一条关系。
  before: str  # 前置任务的临时引用。
  after: str  # 后续任务的临时引用。
  kind: Literal["hard", "candidate"]  # 只允许确定依赖或待确认关系。
  source_quote: str  # 输入计划中的关系原文片段。
  reason: str  # 判定依据或待确认的问题。


"""模型响应"""
class ModelResult(StrictFields):  # 表示一次模型响应的完整数据。
  tasks: list[ModelTask]  # 模型提出的任务列表。
  relations: list[ModelRelation]  # 模型提出的关系列表。