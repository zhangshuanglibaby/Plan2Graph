"""检查模型响应的必需字段、字段类型和允许的取值。"""

import pytest  # 导入测试工具。

from pydantic import ValidationError  # 导入数据不合格时的异常类型。

from plan2graph.response_models import ModelRelation, ModelResult, ModelTask  # 导入刚定义的数据模型。


"""检查符合约定的数据可以被接收。"""
def test_valid_result() -> None:  # 检查符合约定的数据可以被接收。
  data = {"tasks": [{"ref": "a", "title": "订单接口", "source_quote": "实现订单接口"}, {"ref": "b", "title": "支付对接", "source_quote": "完成支付对接"}], "relations": [{"before": "a", "after": "b", "kind": "hard", "source_quote": "支付对接依赖订单接口", "reason": "原文明确说明依赖"}]}  # 准备两个任务和一条关系。
  result = ModelResult.model_validate(data)  # 按字段约定解析数据。
  assert len(result.tasks) == 2  # 确认两个任务都被接收。
  assert result.relations[0].kind == "hard"  # 确认关系类型被保留。


"""检查缺少必需字段时会报错。"""
def test_missing_field_is_rejected() -> None:  # 检查缺少必需字段时会报错。
  with pytest.raises(ValidationError) as error:  # 捕获字段校验错误。
    ModelTask.model_validate({"ref": "a", "title": "订单接口"})  # 故意省略 source_quote。
  assert error.value.errors()[0]["type"] == "missing"  # 确认错误原因是缺字段。


"""检查数字不会被当成字符串。"""
def test_wrong_type_is_rejected() -> None:  # 检查数字不会被当成字符串。
  with pytest.raises(ValidationError) as error:  # 捕获字段校验错误。
    ModelTask.model_validate({"ref": "a", "title": 123, "source_quote": "实现订单接口"})  # 故意把标题写成数字。
  assert error.value.errors()[0]["type"] == "string_type"  # 确认错误原因是类型不对。


"""检查关系类型不能使用约定以外的值。"""
def test_unknown_kind_is_rejected() -> None:  # 检查关系类型不能使用约定以外的值。
  with pytest.raises(ValidationError) as error:  # 捕获字段校验错误。
    ModelRelation.model_validate({"before": "a", "after": "b", "kind": "maybe", "source_quote": "先做 A", "reason": "待核实"})  # 故意使用未约定的 maybe。
  assert error.value.errors()[0]["type"] == "literal_error"  # 确认错误原因是取值不允许。


"""检查未约定的字段不能混入任务。"""
def test_extra_field_is_rejected() -> None:  # 检查未约定的字段不能混入任务。
  with pytest.raises(ValidationError) as error:  # 捕获字段校验错误。
    ModelTask.model_validate({"ref": "a", "title": "订单接口", "source_quote": "实现订单接口", "duration": 3})  # 故意多加工期字段。
  assert error.value.errors()[0]["type"] == "extra_forbidden"  # 确认错误原因是多余字段。

"""检查符合约定的 JSON 文本能被解析。"""
def test_json_text_is_accepted() -> None:  # 检查符合约定的 JSON 文本能被解析。
  text = '{"tasks":[{"ref":"a","title":"订单接口","source_quote":"实现订单接口"}],"relations":[]}'  # 准备完整的 JSON 文本。
  result = ModelResult.model_validate_json(text)  # 将 JSON 文本解析为数据模型。
  assert result.tasks[0].ref == "a"  # 确认任务引用被正确读取。


"""检查不完整的 JSON 文本会报错。"""
def test_incomplete_json_is_rejected() -> None:  # 检查不完整的 JSON 文本会报错。
  with pytest.raises(ValidationError):  # 捕获 JSON 解析失败产生的校验错误。
    ModelResult.model_validate_json('{"tasks": [')  # 故意提供尚未写完的 JSON。