"""阶段 5.2 的纯离线记录校验与指标原始计数。"""

import argparse  # 提供不触发模型请求的本地评估命令。
from collections.abc import Iterable, Mapping  # 读取记录与人工裁定的任务编号。
from csv import reader  # 按表格列读取固定样例清单。
from hashlib import sha256  # 核对渲染记录所指的 Mermaid 源码。
import json  # 使用标准 JSON 解析器读取离线评估记录文件。
from pathlib import Path  # 从评估工程根目录定位本地标注文件。
import re  # 仅读取人工标注中明确编号的关键任务小节。
import subprocess  # 在本机调用明确指定的 Mermaid 渲染器。
import sys  # 将离线命令的错误信息写到标准错误。
import tempfile  # 将待渲染源码与产物限制在临时目录。
from typing import Literal  # 将人工未匹配裁定限定为明确的文本。
from xml.etree import ElementTree  # 确认渲染器确实产生了可解析的 SVG 文件。

from plan2graph.mermaid import render_mermaid  # 用现有生成器核对图与源码是否对应。
from plan2graph.models import GraphRelation, GraphTask, PlanGraph, SkippedRelation  # 将 JSON 快照还原为项目原有的任务图对象。
from plan2graph.validate import would_create_cycle  # 检查全部展示关系是否构成环。


def validate_unrun_record(record: Mapping[str, object]) -> None:  # 校验尚无实际输出的评估记录。
  if record.get("status") != "未运行":  # 本入口只接受未运行状态。
    raise ValueError("未运行记录的 status 必须为“未运行”")  # 避免把其他状态误当成未运行。
  if record.get("source") != "未运行（无输出来源）":  # 未运行不能声称已有输出来源。
    raise ValueError("未运行记录的 source 必须为“未运行（无输出来源）”")  # 要求来源与状态一致。
  if record.get("run_id") is not None:  # 未运行没有可关联的实际运行批次。
    raise ValueError("未运行记录不能包含 run_id")  # 拒绝伪造或误填的运行身份。
  for field in ("graph", "mermaid_text"):  # 检查未运行时不应出现的两类输出。
    if record.get(field) is not None:  # 即使空图或空字符串也属于已填写的输出。
      raise ValueError(f"未运行记录不能包含 {field}")  # 保留出错字段供人工修正。


def validate_current_run_identity(record: Mapping[str, object], expected_run_id: str) -> None:  # 核对已运行记录是否属于指定的真实调用批次。
  if not isinstance(expected_run_id, str) or not expected_run_id.strip():  # 评估批次不能是空标识。
    raise ValueError("本轮 run_id 必须是非空字符串")  # 拒绝无法区分历史与本轮的批次。
  case_id = record.get("case_id")  # 读取样例身份，后续仍需与固定清单核对。
  if not isinstance(case_id, str) or not case_id.strip():  # 已运行记录必须指出所评估的样例。
    raise ValueError("本轮记录缺少 case_id")  # 不让匿名结果进入后续汇总。
  if record.get("source") != "本轮真实调用":  # 合成、历史和未运行记录不能冒充本轮质量结果。
    raise ValueError("本轮记录来源必须为“本轮真实调用”")  # 只校验声明，不据此证明调用确曾发生。
  if record.get("run_id") != expected_run_id:  # 每条记录必须匹配指定的同一批次。
    raise ValueError("本轮记录的 run_id 不匹配")  # 防止跨批次混算或缺失批次编号。
  if record.get("status") not in ("成功出图", "明确冲突停止", "其他失败"):  # 未运行和未知状态不能计入已运行样例。
    raise ValueError("本轮记录状态无效")  # 后续分母按明确的运行结果分类。


def validate_case_inventory(expected_case_ids: Iterable[str], records: Iterable[Mapping[str, object]]) -> None:  # 核对一次评估是否为固定清单中每个样例保留了一条记录。
  expected: set[str] = set()  # 收集事先固定的样例编号。
  for case_id in expected_case_ids:  # 先检查作为基准的清单自身是否有效。
    if not isinstance(case_id, str) or not case_id.strip() or case_id in expected:  # 空编号与重复编号都无法定义唯一评估集合。
      raise ValueError("固定样例清单存在空或重复的 case_id")  # 不以不可靠清单进行汇总。
    expected.add(case_id)  # 保留已确认格式的编号供后续核对。
  if not expected:  # 空清单不能构成阶段 5.2 的评估集合。
    raise ValueError("固定样例清单不能为空")  # 阻止空记录集被误认为完整。
  actual: set[str] = set()  # 收集本次提交的成功、失败和未运行记录编号。
  for record in records:  # 每条记录都必须映射到一个唯一的固定样例。
    case_id = record.get("case_id")  # 读取记录声明的样例编号。
    if not isinstance(case_id, str) or not case_id.strip():  # 无编号记录不能归入任何样例。
      raise ValueError("评估记录缺少 case_id")  # 拒绝静默忽略匿名记录。
    if case_id in actual:  # 一次评估中同一样例不能用多条结果重复计数。
      raise ValueError(f"评估记录重复 case_id：{case_id}")  # 报出重复的样例方便复核。
    actual.add(case_id)  # 保留已经出现的编号以核对完整集合。
  if actual != expected:  # 未运行样例也必须出现，清单外样例不得混入。
    missing = sorted(expected - actual)  # 找出被遗漏的固定样例。
    unexpected = sorted(actual - expected)  # 找出未列入事先清单的记录。
    raise ValueError(f"评估记录与固定清单不符：缺少 {missing}；清单外 {unexpected}")  # 不发布部分集合的指标。


def load_fixed_case_inventory(document_path: Path) -> tuple[dict[str, str], ...]:  # 从口径文档中读取事先固定的本地样例身份。
  try:  # 文档缺失或无法解码时不能凭目录扫描重建清单。
    lines = document_path.read_text(encoding="utf-8").splitlines()  # 保留表格行的原始顺序。
  except (OSError, UnicodeError) as exc:  # 将读取问题明确归为清单不可用。
    raise ValueError("固定样例清单文档缺失或不可读") from exc  # 不生成空清单继续评估。
  try:  # 只定位阶段 5.2 口径文档中明确命名的表格。
    section_start = lines.index("### 固定样例清单（本地评估范围）")  # 找到固定清单小节。
    section_end = lines.index("## 四项指标", section_start + 1)  # 用下一节防止读入其他表格。
    table_start = next(index for index in range(section_start + 1, section_end) if lines[index].startswith("| `case_id` |"))  # 定位清单表头。
  except (ValueError, StopIteration) as exc:  # 缺少固定清单结构时拒绝猜测表格内容。
    raise ValueError("固定样例清单表格缺失") from exc  # 不从零散描述推断样例。
  table_lines = lines[table_start:section_end]  # 将读取范围限制到清单所在小节。
  if len(table_lines) < 3 or table_lines[1] != "| --- | --- | --- | --- | --- |":  # 表头后必须紧跟五列表格分隔行和至少一条数据。
    raise ValueError("固定样例清单表格格式无效")  # 拒绝列数或分隔行改变后继续错列读取。
  header = tuple(cell.strip() for cell in next(reader([table_lines[0]], delimiter="|"))[1:-1])  # 用列解析器读取 Markdown 表头。
  if header != ("`case_id`", "标注文件", "标注所指原计划", "主覆盖类型", "来源"):  # 列含义不能与读取顺序漂移。
    raise ValueError("固定样例清单表头无效")  # 避免将来源误读为其他字段。
  entries: list[dict[str, str]] = []  # 按文档顺序收集经过基本格式检查的清单项。
  seen_ids: set[str] = set()  # 拒绝相同样例编号重复出现。
  seen_annotations: set[str] = set()  # 拒绝同一标注文件占据两个清单位置。
  for line in table_lines[2:]:  # 只读取表头与分隔行后连续的数据行。
    if not line.strip():  # 清单后的空行表示表格结束。
      break  # 不把表格下方的解释文字当作样例。
    if not line.startswith("|") or not line.endswith("|"):  # 每条清单行都必须保留五列边界。
      raise ValueError("固定样例清单数据行格式无效")  # 不跳过损坏的数据行。
    cells = tuple(cell.strip() for cell in next(reader([line], delimiter="|"))[1:-1])  # 拆出该行的五个单元格。
    if len(cells) != 5 or any(not cell for cell in cells) or any(not cell.startswith("`") or not cell.endswith("`") for cell in cells[:3]):  # 路径与身份必须完整且采用表中约定的代码标记。
      raise ValueError("固定样例清单数据行格式无效")  # 不以不完整字段进入记录核对。
    case_id, annotation_path, plan_path = (cell[1:-1] for cell in cells[:3])  # 去掉标识与路径外层的 Markdown 标记。
    if not case_id or annotation_path != f"tests/fixtures/{case_id}_annotation.md" or not plan_path:  # 样例编号应唯一对应其标注文件。
      raise ValueError("固定样例清单路径与 case_id 不符")  # 不根据其他字段猜测缺失路径。
    if case_id in seen_ids or annotation_path in seen_annotations:  # 一份标注只在固定清单中出现一次。
      raise ValueError("固定样例清单存在重复样例")  # 不让重复记录增加样例权重。
    seen_ids.add(case_id)  # 标记已读取的样例编号。
    seen_annotations.add(annotation_path)  # 标记已读取的标注文件路径。
    entries.append({"case_id": case_id, "annotation_path": annotation_path, "plan_path": plan_path, "coverage_type": cells[3], "origin": cells[4]})  # 保留原表格中的身份、类型与来源声明。
  if not entries:  # 空表格不能充当固定评估集合。
    raise ValueError("固定样例清单不能为空")  # 防止空输入获得貌似完整的核对结果。
  return tuple(entries)  # 返回可供后续记录关联的离线清单，不赋予传输许可。


def validate_annotation_reference(record: Mapping[str, object], server_root: Path, expected_annotation_path: str) -> None:  # 核对记录引用的标注文件与本地字节指纹。
  case_id = record.get("case_id")  # 读取已由固定清单确定的样例编号。
  if not isinstance(case_id, str) or not case_id.strip():  # 匿名记录不能定位唯一的标注。
    raise ValueError("标注引用缺少 case_id")  # 避免错把其他样例的文件配进记录。
  if expected_annotation_path != f"tests/fixtures/{case_id}_annotation.md":  # 固定清单中的文件路径必须符合已约定的命名。
    raise ValueError("固定清单的标注路径与 case_id 不符")  # 不从记录自行发明标注路径。
  if record.get("annotation_path") != expected_annotation_path:  # 本条记录只能引用清单指定的文件。
    raise ValueError("记录的标注路径与固定清单不符")  # 拒绝另一份标注冒充当前样例。
  fixtures_root = (server_root / "tests" / "fixtures").resolve()  # 将读取范围限定在本工程的标注目录。
  annotation_file = (server_root / expected_annotation_path).resolve()  # 展开符号链接后再核对真实位置。
  if not annotation_file.is_relative_to(fixtures_root):  # 链接不应把读取目标带出标注目录。
    raise ValueError("标注文件不在 fixtures 目录内")  # 不读取任意外部文件。
  try:  # 缺失或不可读的标注不能当作已核对的金标准。
    annotation_bytes = annotation_file.read_bytes()  # 读取本地现存标注的原始字节。
  except OSError as exc:  # 将文件系统错误转换成明确的数据不完整提示。
    raise ValueError("标注文件缺失或不可读") from exc  # 不用空内容替代缺失文件。
  fingerprint = sha256(annotation_bytes).hexdigest()  # 计算和记录字段对应的内容指纹。
  if record.get("annotation_sha256") != fingerprint:  # 记录必须指向当下核对的这份标注内容。
    raise ValueError("标注文件内容指纹不一致")  # 改动标注后不能沿用旧记录直接发布指标。


def validate_plan_reference(record: Mapping[str, object], server_root: Path, expected_annotation_path: str, expected_plan_path: str) -> None:  # 核对清单、标注与记录对同一原计划的引用。
  validate_annotation_reference(record, server_root, expected_annotation_path)  # 先确定标注路径及其内容指纹可信。
  plan_parts = Path(expected_plan_path).parts  # 将固定清单中的相对路径拆开检查。
  if len(plan_parts) != 4 or plan_parts[:3] != ("tests", "fixtures", "plans") or not plan_parts[3].endswith(".md"):  # 只允许 plans 目录中的单个 Markdown 文件。
    raise ValueError("固定清单的原计划路径无效")  # 不从清单读取任意路径。
  if record.get("plan_path") != expected_plan_path:  # 记录不能自行替换原计划路径。
    raise ValueError("记录的原计划路径与固定清单不符")  # 拒绝指向其他样例的计划。
  annotation_file = server_root / expected_annotation_path  # 使用已核对的标注定位其原计划声明。
  try:  # 标注需要可解码才能准确读取声明。
    annotation_text = annotation_file.read_text(encoding="utf-8")  # 读取本地标注中的原计划路径。
  except (OSError, UnicodeError) as exc:  # 内容无法读取或解码时不能推断引用。
    raise ValueError("标注文件无法读取原计划引用") from exc  # 保留引用不完整的原因。
  declared_paths = [line.removeprefix("原计划：") for line in annotation_text.splitlines() if line.startswith("原计划：")]  # 收集全部原计划声明以排除重复。
  if len(declared_paths) != 1 or declared_paths[0] != expected_plan_path:  # 缺失、重复或不一致都不能指向确定的原计划。
    raise ValueError("标注中的原计划引用与固定清单不符")  # 不凭记录补造标注里缺失的关联。
  plans_root = (server_root / "tests" / "fixtures" / "plans").resolve()  # 限定原计划的实际读取范围。
  plan_file = (server_root / expected_plan_path).resolve()  # 展开符号链接后再核对真实位置。
  if not plan_file.is_relative_to(plans_root):  # 不能通过链接读取目录外文件。
    raise ValueError("原计划文件不在 plans 目录内")  # 拒绝越界引用。
  try:  # 原计划不存在时不能只依赖记录里的旧指纹。
    plan_bytes = plan_file.read_bytes()  # 读取原计划本地副本的原始字节。
  except OSError as exc:  # 文件缺失或不可读都属于评估输入不完整。
    raise ValueError("原计划文件缺失或不可读") from exc  # 不把缺失文件视作空计划。
  if record.get("plan_sha256") != sha256(plan_bytes).hexdigest():  # 本地原计划必须与记录里的内容指纹吻合。
    raise ValueError("原计划文件内容指纹不一致")  # 文件改动后需重新核对记录。


def validate_batch_references(document_path: Path, server_root: Path, records: Iterable[Mapping[str, object]]) -> None:  # 将固定清单与一批离线记录的身份和本地文件引用逐条核对。
  inventory = load_fixed_case_inventory(document_path)  # 读取事先固定的文档清单，不从记录反推范围。
  batch = tuple(records)  # 固定一次遍历的记录，避免生成器被集合检查消耗。
  validate_case_inventory((entry["case_id"] for entry in inventory), batch)  # 先拒绝漏项、重复项和清单外样例。
  entries_by_id = {entry["case_id"]: entry for entry in inventory}  # 以清单身份查找对应的已固定路径。
  for record in batch:  # 每条记录都要通过标注与原计划的文件核对。
    entry = entries_by_id[record["case_id"]]  # 集合检查已确认编号存在且属于清单。
    validate_plan_reference(record, server_root, entry["annotation_path"], entry["plan_path"])  # 不接受记录自行指定其他文件或旧指纹。


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:  # 拒绝同一个 JSON 对象内相互覆盖的字段。
  result: dict[str, object] = {}  # 保留已经读取的字段和值。
  for key, value in pairs:  # 逐项检查解析器提供的原始字段顺序。
    if key in result:  # 重复的身份或指纹字段不能以后值覆盖前值。
      raise ValueError(f"评估记录 JSON 存在重复字段：{key}")  # 阻止含糊记录进入评估。
    result[key] = value  # 仅收集尚未出现的字段。
  return result  # 返回未发生键覆盖的 JSON 对象。


def _reject_nonfinite_json(value: str) -> None:  # 标准 JSON 不接受 NaN 或无穷大。
  raise ValueError(f"评估记录 JSON 包含非标准数值：{value}")  # 不让非有限值进入指标字段。


def load_record_batch(record_path: Path) -> tuple[dict[str, object], ...]:  # 从本地 JSON 文件读取尚未证明来源的离线记录。
  try:  # 缺失、不合法编码和 JSON 语法错误都不能视作空批次。
    text = record_path.read_text(encoding="utf-8")  # 仅读取调用者指定的本地文件。
  except (OSError, UnicodeError) as exc:  # 将文件读取错误标记为评估输入缺失。
    raise ValueError("评估记录文件缺失或不可读") from exc  # 不自动生成占位记录。
  try:  # 用结构化解析器读取记录，保留重复键检测。
    data = json.loads(text, object_pairs_hook=_reject_duplicate_json_keys, parse_constant=_reject_nonfinite_json)  # 不允许重复字段或非标准数值悄然通过。
  except json.JSONDecodeError as exc:  # 无效 JSON 不能退回文本匹配或忽略。
    raise ValueError("评估记录 JSON 格式无效") from exc  # 保留原始解析错误用于排查。
  if not isinstance(data, dict) or set(data) != {"records"}:  # 文件顶层只接受明确的一组记录。
    raise ValueError("评估记录 JSON 顶层必须只有 records")  # 防止读错其他类型的 JSON 文件。
  records = data["records"]  # 取得尚未经身份、来源或内容验证的原始记录。
  if not isinstance(records, list) or not records or any(not isinstance(record, dict) for record in records):  # 每条记录都须为对象且批次不能空。
    raise ValueError("评估记录 JSON 的 records 必须是非空对象列表")  # 拒绝部分数据或错误类型。
  return tuple(records)  # 返回数据供后续清单与文件引用核对。


def load_and_validate_record_references(document_path: Path, server_root: Path, record_path: Path) -> tuple[dict[str, object], ...]:  # 将本地 JSON 文件接入固定样例清单的引用校验。
  records = load_record_batch(record_path)  # 先读取明确结构的离线记录文件。
  validate_batch_references(document_path, server_root, records)  # 核对固定集合和每份标注、原计划的当前字节。
  return records  # 仅返回引用核对过的记录，不宣称它们是真实调用结果。


def is_success_output_consistent(record: Mapping[str, object]) -> bool:  # 核对成功记录的结构化图与 Mermaid 源码是否对应。
  if record.get("status") != "成功出图":  # 本入口只检查已经声明成功的记录。
    raise ValueError("输出一致性检查需要成功出图记录")  # 避免把未运行或失败误作成功图。
  graph = record.get("graph")  # 读取待核对的原始结构化图。
  if not isinstance(graph, PlanGraph):  # 缺少图时无法参与结构有效率的成功图计数。
    raise ValueError("成功出图记录缺少 PlanGraph")  # 不以 Mermaid 文本逆推结构化图。
  mermaid_text = record.get("mermaid_text")  # 读取与该图关联的实际源码。
  if not isinstance(mermaid_text, str) or not mermaid_text.strip():  # 空源码不能作为已捕获的成功输出。
    raise ValueError("成功出图记录缺少 Mermaid 源码")  # 要求保留当次实际输出。
  try:  # 异常图也要留在成功输出集合中继续接受结构检查。
    expected_text = render_mermaid(graph)  # 用仓库现有生成规则重建可比较的源码。
  except (ValueError, TypeError, IndexError):  # 错误编号可能导致排序或切片后的数字转换失败。
    return False  # 标记输出不一致，不在这里删掉结构无效的成功图。
  return mermaid_text == expected_text  # 精确比较源码，避免不同图的文本串到同一记录。


def count_task_coverage(gold_task_count: int, matched_gold_ids: Iterable[int]) -> tuple[int, int]:  # 返回人工匹配的覆盖数和金标准任务总数。
  if isinstance(gold_task_count, bool) or not isinstance(gold_task_count, int) or gold_task_count < 1:  # 金标准任务数必须是正整数。
    raise ValueError("金标准任务数必须是正整数")  # 拒绝空样例或错误类型。
  seen: set[int] = set()  # 记录已经由人工匹配的金标准编号。
  for gold_id in matched_gold_ids:  # 逐一核对已裁定匹配的任务编号。
    if isinstance(gold_id, bool) or not isinstance(gold_id, int) or not 1 <= gold_id <= gold_task_count:  # 编号必须在 1 到总数之间。
      raise ValueError("匹配的金标准任务编号无效")  # 不把无效编号计入覆盖。
    if gold_id in seen:  # 同一金标准任务不能被重复计为覆盖。
      raise ValueError("金标准任务编号重复匹配")  # 保留一对一匹配的边界。
    seen.add(gold_id)  # 将有效且未出现过的编号计入集合。
  return len(seen), gold_task_count  # 只返回原始计数，不计算或伪造百分比。


def count_aligned_task_coverage(graph: PlanGraph, gold_task_count: int, alignment: Mapping[int, int | Literal["未匹配"]]) -> tuple[int, int]:  # 检查每个输出节点的人工裁定后计数。
  if any(isinstance(position, bool) or not isinstance(position, int) for position in alignment):  # 输出节点位置必须是整数，布尔值不能代替序号。
    raise ValueError("任务对齐位置无效")  # 拒绝无法对应任务列表的裁定键。
  if set(alignment) != set(range(len(graph.tasks))):  # 每个实际输出节点恰好需要一份裁定。
    raise ValueError("任务对齐不完整或包含额外位置")  # 漏裁定和多余裁定都不能发布覆盖计数。
  matched_gold_ids: list[int] = []  # 收集已经人工确认匹配的金标准编号。
  for position in range(len(graph.tasks)):  # 按图中任务的实际列表位置读取裁定。
    verdict = alignment[position]  # 取得该节点对应的金标准编号或明确未匹配结果。
    if verdict == "未匹配":  # 已确认无匹配的输出节点不增加覆盖数。
      continue  # 继续检查其他输出节点的裁定。
    matched_gold_ids.append(verdict)  # 待复核等其他值交给编号校验拒绝。
  return count_task_coverage(gold_task_count, matched_gold_ids)  # 复用编号范围与一对一约束，只返回原始计数。


def count_unsupported_hard_edges(graph: PlanGraph, verdicts: Mapping[int, str]) -> tuple[int, int]:  # 返回无依据实线数和实际实线总数。
  hard_positions = [index for index, relation in enumerate(graph.relations) if relation.kind == "hard"]  # 保留每条实线在原关系列表中的位置。
  if any(isinstance(index, bool) or not isinstance(index, int) for index in verdicts):  # 裁定键必须是实线的整数位置。
    raise ValueError("实线裁定位置无效")  # 不接受布尔值或字符串伪装的位置。
  if set(verdicts) != set(hard_positions):  # 每条实线恰好需要一份人工裁定，虚线不能混入。
    raise ValueError("实线裁定不完整或包含非实线位置")  # 拒绝漏裁定和额外裁定。
  for position in hard_positions:  # 逐条检查实线裁定是否已经定稿。
    if verdicts[position] not in ("有依据", "无依据"):  # 待复核或未知裁定尚不能发布指标。
      raise ValueError("实线裁定尚未完成")  # 不把争议自动算作有依据。
  unsupported = sum(verdicts[position] == "无依据" for position in hard_positions)  # 逐条计入无依据实线，包括重复边。
  return unsupported, len(hard_positions)  # 分母保留所有实际实线；零分母由汇总层记为不适用。


def is_graph_structurally_valid(graph: PlanGraph) -> bool:  # 检查成功图本身是否满足阶段 5.2 的结构条件。
  task_ids = [task.id for task in graph.tasks]  # 收集包含孤立任务在内的所有节点编号。
  if not task_ids or len(set(task_ids)) != len(task_ids) or any(re.fullmatch(r"T[1-9]\d*", task_id) is None for task_id in task_ids):  # 空图、重复或无法交给现有生成器的 ID 都是无效结构。
    return False  # 保留无效图供汇总层计入成功输出分母。
  known_ids = set(task_ids)  # 用实际节点编号核对每条展示关系的端点。
  kept = []  # 按原顺序保留已检查的实线和虚线。
  for relation in graph.relations:  # 跳过记录不属于实际展示图。
    if relation.before not in known_ids or relation.after not in known_ids:  # 任意端点不存在即为无效结构。
      return False  # 不尝试从输出文本补造缺失节点。
    if would_create_cycle(tuple(kept), relation):  # 自依赖及实线、虚线混合形成的环均不通过。
      return False  # 不自动删去实际输出的错误关系。
    kept.append(relation)  # 当前边合法后才加入后续判环的展示图。
  return True  # 仅表示形式结构有效，不代表语义或 Mermaid 渲染通过。


def count_structurally_valid_outputs(successful_graphs: Iterable[PlanGraph]) -> tuple[int, int]:  # 统计成功输出图中结构通过数与总数。
  valid_count = 0  # 记录结构有效的成功图数量。
  output_count = 0  # 记录全部成功图数量，包括结构无效的图。
  for graph in successful_graphs:  # 每张传入的成功图都必须进入分母。
    output_count += 1  # 先计入成功输出，再检查其结构。
    if is_graph_structurally_valid(graph):  # 只对通过全部结构条件的图增加分子。
      valid_count += 1  # 无效图保留在分母，但不进入分子。
  return valid_count, output_count  # 零分母时保留 (0, 0)，由后续汇总层标记不适用。


def count_recorded_mermaid_renders(successful_outputs: Iterable[tuple[str, Mapping[str, object]]]) -> tuple[int, int]:  # 汇总已记录渲染核验的成功图。
  rendered_count = 0  # 记录渲染器报告成功的图数。
  output_count = 0  # 记录本轮传入的所有成功图数。
  for mermaid_text, check in successful_outputs:  # 每张成功图的源码与渲染记录成对传入。
    output_count += 1  # 渲染失败的成功图仍须进入分母。
    status = check.get("status")  # 读取实际渲染结果，不能从源码存在推断成功。
    if status not in ("成功", "失败"):  # 未执行或未知结果不构成完整渲染核验。
      raise ValueError("Mermaid 渲染核验未完成")  # 拒绝用已检查子集冒充全体成功输出。
    for field in ("renderer", "renderer_version"):  # 要求记录实际渲染器及其版本。
      value = check.get(field)  # 读取单项渲染环境证据。
      if not isinstance(value, str) or not value.strip() or value == "未确认":  # 空值或未知版本不能证明使用的渲染环境。
        raise ValueError(f"Mermaid 渲染记录缺少 {field}")  # 指明缺失的证据字段。
    fingerprint = sha256(mermaid_text.encode("utf-8")).hexdigest()  # 对本次成功图的原始源码计算指纹。
    if check.get("source_sha256") != fingerprint:  # 核对记录确实指向这份源码。
      raise ValueError("Mermaid 渲染源码指纹不一致")  # 不统计串样例或旧源码的渲染结果。
    if status == "失败":  # 实际渲染失败也必须留下可复核的原因。
      reason = check.get("failure_reason")  # 读取失败诊断。
      if not isinstance(reason, str) or not reason.strip():  # 缺少失败原因时记录尚不完整。
        raise ValueError("Mermaid 渲染失败记录缺少原因")  # 不悄悄吞掉失败案例。
    else:  # 只有记录完整且报告成功时才增加分子。
      rendered_count += 1  # 将该图计为渲染成功。
  return rendered_count, output_count  # 不在此处计算百分比或证明记录确由渲染器产生。


def _object_fields(value: object, fields: set[str], label: str) -> dict[str, object]:  # 检查结构化记录的字段没有缺失或隐式替换。
  if not isinstance(value, dict) or set(value) != fields:  # 固定数据契约，不根据未知字段推测含义。
    raise ValueError(f"{label}字段不完整或包含未知字段")  # 明确阻断不可复核的数据。
  return value  # 返回已核对形状的对象。


def _nonempty_text(value: object, label: str) -> str:  # 验证必须有内容的文本字段。
  if not isinstance(value, str) or not value.strip():  # 空白不能作为人工理由或运行身份。
    raise ValueError(f"{label}必须是非空字符串")  # 不以默认值补全记录。
  return value  # 保留原始文本供后续报告和复核。


def _nonnegative_int(value: object, label: str) -> int:  # 验证 JSON 序号不被布尔值冒充。
  if isinstance(value, bool) or not isinstance(value, int) or value < 0:  # 位置从零开始且必须为整数。
    raise ValueError(f"{label}必须是非负整数")  # 拒绝含糊的位置。
  return value  # 返回已验证的整数。


def _graph_relation(value: object) -> GraphRelation:  # 从明确字段恢复一条原始关系。
  data = _object_fields(value, {"before", "after", "kind", "source_quote", "reason"}, "关系")  # 不用 Mermaid 文本反推证据。
  if data["kind"] not in ("hard", "candidate"):  # 关系类型只接受项目已有的两类。
    raise ValueError("关系 kind 无效")  # 防止未知类型被悄悄排除在实线分母外。
  return GraphRelation(_nonempty_text(data["before"], "关系起点"), _nonempty_text(data["after"], "关系终点"), data["kind"], _nonempty_text(data["source_quote"], "关系引文"), _nonempty_text(data["reason"], "关系原因"))  # 保留原始方向与证据。


def decode_graph_snapshot(value: object) -> PlanGraph:  # 解码成功图，而不修复错误端点或环。
  data = _object_fields(value, {"tasks", "relations", "skipped_relations"}, "图快照")  # 成功图必须包含三种列表。
  if any(not isinstance(data[field], list) for field in ("tasks", "relations", "skipped_relations")):  # 元素集合必须明确。
    raise ValueError("图快照列表格式无效")  # 不将缺失列表解释为空列表。
  tasks: list[GraphTask] = []  # 保留成功图的原始任务顺序。
  for raw_task in data["tasks"]:  # 检查任务字段和引文类型。
    task = _object_fields(raw_task, {"id", "title", "source_quotes", "first_position"}, "任务")  # 每个任务都需要证据位置。
    quotes = task["source_quotes"]  # 原始引文可以有多处。
    if not isinstance(quotes, list) or not quotes or any(not isinstance(quote, str) or not quote.strip() for quote in quotes):  # 引文列表不可缺失或为空。
      raise ValueError("任务引文列表无效")  # 不伪造原计划引文。
    tasks.append(GraphTask(_nonempty_text(task["id"], "任务 ID"), _nonempty_text(task["title"], "任务标题"), tuple(quotes), _nonnegative_int(task["first_position"], "任务首次位置")))  # 不改变 ID 或原文顺序。
  relations = tuple(_graph_relation(item) for item in data["relations"])  # 保留全部实际展示边，包括重复边和错误端点。
  skipped: list[SkippedRelation] = []  # 跳过关系不计作实际展示边。
  for raw_skipped in data["skipped_relations"]:  # 每条跳过记录都保留原因与原关系。
    item = _object_fields(raw_skipped, {"relation", "skip_reason"}, "跳过关系")  # 缺原因不能成为有效快照。
    skipped.append(SkippedRelation(_graph_relation(item["relation"]), _nonempty_text(item["skip_reason"], "跳过原因")))  # 将其还原为原有类型。
  return PlanGraph(tuple(tasks), relations, tuple(skipped))  # 结构有效性在计数时独立检查。


def _annotation_gold_tasks(annotation_path: Path) -> tuple[tuple[int, str], ...]:  # 从已锁定文件读取人工确认的关键任务编号与原文标题。
  try:  # 标注读不到或解码失败时不能用记录自报的金标准继续计数。
    lines = annotation_path.read_text(encoding="utf-8").splitlines()  # 只读取本地标注文件。
    start = lines.index("## 关键任务") + 1  # 限定到人工标注的关键任务小节。
  except (OSError, UnicodeError, ValueError) as exc:  # 缺小节同样属于评估数据不完整。
    raise ValueError("标注中的关键任务小节缺失或不可读") from exc  # 不从原计划自动猜金标准。
  tasks: list[tuple[int, str]] = []  # 依次保留人工标注的任务编号。
  for line in lines[start:]:  # 只读到下一个同级标题为止。
    if line.startswith("## "):  # 不将后面的边或解释混入任务列表。
      break  # 关键任务小节已经结束。
    if not line.strip():  # 略过小节内的空行。
      continue  # 编号仍必须连续。
    match = re.fullmatch(r"(\d+)\. (.+)", line)  # 现有标注按数字、句点和空格列出关键任务。
    if match is None or int(match[1]) != len(tasks) + 1:  # 异常或缺号不能默认修补。
      raise ValueError("标注中的关键任务编号或格式无效")  # 让人工先修复金标准。
    tasks.append((int(match[1]), match[2]))  # 保留标注标题供记录逐项核对。
  if not tasks:  # 空任务集无法形成覆盖率分母。
    raise ValueError("标注中没有关键任务")  # 不将零项误认为通过。
  return tuple(tasks)  # 返回经过路径和指纹预先核对的本地金标准。


def _validate_gold_tasks(raw: object, annotation_path: Path) -> int:  # 拒绝记录自行更换或增删金标准任务。
  if not isinstance(raw, list):  # JSON 必须显式列出人工编号与标题。
    raise ValueError("gold_tasks 必须是列表")  # 不从输出图推断金标准。
  gold = []  # 按记录顺序保留人工任务。
  for item in raw:  # 每个编号与标题都要与标注一一对应。
    task = _object_fields(item, {"id", "title"}, "gold_tasks")  # 拒绝未知或缺失字段。
    gold.append((_nonnegative_int(task["id"], "金标准编号"), _nonempty_text(task["title"], "金标准标题")))  # 不允许布尔值混入编号。
  expected = _annotation_gold_tasks(annotation_path)  # 以当前标注文件为唯一金标准来源。
  if tuple(gold) != expected:  # 标注中的合并任务不可拆成多条记录。
    raise ValueError("gold_tasks 与人工标注关键任务不一致")  # 阻止记录篡改覆盖率分母。
  return len(expected)  # 返回经过核对的分母。


def _indexed_verdicts(raw: object, index_key: str, value_key: str, label: str) -> dict[int, object]:  # 读取按原始列表位置标注的人工裁定。
  if not isinstance(raw, list):  # 裁定不得用 JSON 对象键隐式转成字符串编号。
    raise ValueError(f"{label}必须是列表")  # 不接受歧义编号。
  verdicts: dict[int, object] = {}  # 保存原始节点或边的位置。
  for item in raw:  # 每项都必须包含位置、裁定及理由。
    entry = _object_fields(item, {index_key, value_key, "reason"}, label)  # 原因不能为空。
    index = _nonnegative_int(entry[index_key], f"{label}位置")  # 位置从零开始。
    if index in verdicts:  # 重复裁定不能以后项覆盖前项。
      raise ValueError(f"{label}重复位置")  # 不凭列表顺序推断最终裁决。
    _nonempty_text(entry["reason"], f"{label}理由")  # 保留人工判断的可复核解释。
    verdicts[index] = entry[value_key]  # 计数函数进一步检查取值、一对一和覆盖范围。
  return verdicts  # 将完整性校验交给现有函数。


def _validate_execution(record: Mapping[str, object]) -> None:  # 核对已运行记录的状态与运行元信息。
  execution = _object_fields(record.get("execution"), {"exit_code", "error_category", "timestamp", "code_version", "prompt_version", "model_alias", "server_version", "request_parameters"}, "execution")  # 保留代码与请求参数。
  for field in ("timestamp", "code_version", "prompt_version", "model_alias", "server_version"):  # 未能核实的内容可以明确写未确认。
    _nonempty_text(execution[field], field)  # 不容许字段缺失或空白。
  if not isinstance(execution["request_parameters"], dict):  # 参数必须保持结构化。
    raise ValueError("request_parameters 必须是对象")  # 不从展示文本猜模型参数。
  exit_code = execution["exit_code"]  # 读取捕获到的命令退出状态。
  if exit_code is not None:  # 不适用或无法核实可显式记录 null。
    _nonnegative_int(exit_code, "exit_code")  # 拒绝字符串或负数。
  category = execution["error_category"]  # 成功时不应伪造错误类别。
  if record["status"] == "成功出图":  # 成功结果应该没有错误。
    if exit_code not in (0, None) or category is not None:  # 非零退出码或错误类别与成功不符。
      raise ValueError("成功出图的运行信息矛盾")  # 不从冲突记录生成指标。
  elif exit_code == 0 or not isinstance(category, str) or not category.strip():  # 失败应有明确类别且不应是零退出码。
    raise ValueError("失败记录缺少错误类别或退出码矛盾")  # 不静默跳过失败。
  if not isinstance(record.get("diagnostics"), list) or any(not isinstance(item, str) or not item.strip() for item in record["diagnostics"]):  # 诊断是文本列表。
    raise ValueError("diagnostics 必须是非空文本组成的列表")  # 不接受无法复核的错误详情。
  if record["status"] != "成功出图" and not record["diagnostics"]:  # 失败至少应留下一个原因。
    raise ValueError("失败记录缺少诊断")  # 保留原始失败案例。


def _metric(numerator: int, denominator: int) -> dict[str, int | float | None]:  # 计算总数比例，零分母为不适用。
  return {"numerator": numerator, "denominator": denominator, "rate": numerator / denominator if denominator else None}  # 不对逐例率求平均。


def evaluate_records(document_path: Path, server_root: Path, records: Iterable[Mapping[str, object]], expected_run_id: str, *, mode: Literal["synthetic", "current"] = "synthetic") -> dict[str, object]:  # 从完整的离线记录生成可审查的逐例与汇总结果。
  if mode not in ("synthetic", "current"):  # 不允许记录自身决定这次报告的性质。
    raise ValueError("评估模式无效")  # 避免把合成数据当成真实结果。
  _nonempty_text(expected_run_id, "run_id")  # 同一份报告必须绑定明确的批次。
  batch = tuple(records)  # 固定一次遍历的原始记录集合。
  validate_batch_references(document_path, server_root, batch)  # 在计数之前核对固定清单和两种原文件指纹。
  entries = {entry["case_id"]: entry for entry in load_fixed_case_inventory(document_path)}  # 取得预先固定的样例类型。
  counts = {"structural": [0, 0], "coverage": [0, 0], "unsupported_hard": [0, 0], "renderable": [0, 0]}  # 保留四项指标的原始分子分母。
  statuses = {"未运行": 0, "成功出图": 0, "明确冲突停止": 0, "其他失败": 0}  # 失败和未运行也要进入报告。
  cases: list[dict[str, object]] = []  # 按固定清单顺序生成逐样例结果。
  by_id = {record["case_id"]: record for record in batch}  # 清单检查已拒绝重复编号。
  for case_id, entry in entries.items():  # 不依赖 JSON 文件的排列顺序。
    record = by_id[case_id]  # 取得当前固定样例的原始记录。
    status = record.get("status")  # 只有四类状态可以入账。
    if not isinstance(status, str) or status not in statuses:  # 未知状态不可计数。
      raise ValueError(f"{case_id} 的状态无效")  # 防止结果静默遗漏。
    statuses[status] += 1  # 记录成功、冲突、失败或未运行的数量。
    gold_count = _validate_gold_tasks(record.get("gold_tasks"), server_root / entry["annotation_path"])  # 防止金标准分母由 JSON 自行定义。
    item: dict[str, object] = {"case_id": case_id, "coverage_type": entry["coverage_type"], "status": status, "source": record.get("source"), "gold_task_count": gold_count}  # 留下来源声明与样例身份。
    if status == "未运行":  # 未运行样例不能进入任何本轮质量分母。
      validate_unrun_record(record)  # 不允许混入批次或图信息。
      item["reason"] = _nonempty_text(record.get("reason"), "未运行原因")  # 逐例报告待运行原因。
      if any(record.get(field) is not None for field in ("execution", "diagnostics", "task_alignment", "hard_edge_verdicts", "render_check")):  # 未运行不可预填裁定或运行信息。
        raise ValueError("未运行记录包含运行结果或人工裁定")  # 不将预测写成观察值。
      cases.append(item)  # 未运行仍保留在固定清单中。
      continue  # 其余核验只处理有结果的记录。
    if record.get("source") != ("本地离线构造" if mode == "synthetic" else "本轮真实调用") or record.get("run_id") != expected_run_id:  # 分离不同来源和批次。
      raise ValueError(f"{case_id} 的来源或 run_id 与评估模式不符")  # 声明不能跨模式复用。
    if mode == "current":  # 本轮模式还需显式通过已运行身份核对。
      validate_current_run_identity(record, expected_run_id)  # 此校验只能证明记录自称，不能证明模型曾被调用。
    _validate_execution(record)  # 检查状态、错误类别、退出码和运行参数。
    item["execution"] = record["execution"]  # 留下原始运行声明供人工复核。
    item["diagnostics"] = record["diagnostics"]  # 保留原始失败及冲突诊断。
    if status != "成功出图":  # 失败没有可评分图，但关键任务仍在覆盖率分母。
      if any(record.get(field) is not None for field in ("graph", "mermaid_text", "task_alignment", "hard_edge_verdicts", "render_check")):  # 拒绝凭空填成功图。
        raise ValueError("失败记录包含成功图或人工裁定")  # 不用失败数据凑成功输出。
      counts["coverage"][1] += gold_count  # 已运行失败的覆盖分子为零。
      item["counts"] = {"coverage": _metric(0, gold_count)}  # 逐例展示失败样例的任务分母。
      cases.append(item)  # 保存失败信息。
      continue  # 失败不进入成功图指标。
    graph = decode_graph_snapshot(record.get("graph"))  # 从 JSON 恢复当次成功图的完整快照。
    consistent = is_success_output_consistent({**record, "graph": graph})  # 错误编号可能使源码无法从快照重建。
    if not consistent and is_graph_structurally_valid(graph):  # 结构合法时不同的源码不能混入同一份输出。
      raise ValueError(f"{case_id} 的成功图与 Mermaid 源码不一致")  # 拒绝串样例。
    item["output_consistent"] = consistent  # 错误结构仍留在成功输出中并单列不一致诊断。
    alignment = _indexed_verdicts(record.get("task_alignment"), "task_index", "gold_id", "任务对齐")  # 逐节点人工裁定。
    covered, total_gold = count_aligned_task_coverage(graph, gold_count, alignment)  # 按一对一人工匹配计任务覆盖。
    verdicts = _indexed_verdicts(record.get("hard_edge_verdicts"), "relation_index", "verdict", "实线裁定")  # 逐条实际实线裁定。
    unsupported, hard_total = count_unsupported_hard_edges(graph, verdicts)  # 零实线时保留零分母。
    render_check = record.get("render_check")  # 取得与当次源码绑定的渲染记录。
    if not isinstance(render_check, dict):  # 没有实际渲染结果不能发布可渲染率。
      raise ValueError("成功图缺少 Mermaid 渲染核验")  # 测试构造的记录也只能用于测试。
    render_count, _ = count_recorded_mermaid_renders(((record["mermaid_text"], render_check),))  # 核对版本、结果、失败原因与源码指纹。
    valid = int(is_graph_structurally_valid(graph))  # 结构无效的成功图仍留在分母。
    case_counts = {"structural": _metric(valid, 1), "coverage": _metric(covered, total_gold), "unsupported_hard": _metric(unsupported, hard_total), "renderable": _metric(render_count, 1)}  # 形成可复查的逐例原始计数。
    for name, metric in case_counts.items():  # 不对逐例率取平均。
      counts[name][0] += metric["numerator"]  # 叠加该指标的分子。
      counts[name][1] += metric["denominator"]  # 叠加该指标的分母。
    item["counts"] = case_counts  # 将四项计数附在对应样例下。
    item["render_check"] = render_check  # 保留渲染来源声明与失败原因。
    item["task_alignment"] = record["task_alignment"]  # 保留人工对齐细节而非仅展示比例。
    item["hard_edge_verdicts"] = record["hard_edge_verdicts"]  # 保留每条实线的裁定。
    cases.append(item)  # 成功图完成全部核验后进入报告。
  metrics = {name: _metric(*value) for name, value in counts.items()}  # 使用总原始计数计算四项汇总率。
  return {"mode": mode, "run_id": expected_run_id, "inventory_count": len(entries), "statuses": statuses, "metrics": metrics, "cases": cases, "provenance_verified": False, "acceptance_ready": False}  # 文件声明不证明模型来源或人工裁定真实性。


def render_with_local_mmdc(mermaid_text: str, executable: str, *, timeout: int = 60) -> dict[str, object]:  # 用本地 Mermaid CLI 渲染一份捕获的源码。
  _nonempty_text(mermaid_text, "Mermaid 源码")  # 空图不可当成真实渲染任务。
  _nonempty_text(executable, "渲染器路径")  # 用户必须明确指定本地可执行文件。
  try:  # 版本号必须来自本次指定的渲染器本身。
    version_result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=timeout, check=False)  # 不使用 shell 或公共渲染网站。
  except (OSError, subprocess.TimeoutExpired) as exc:  # 缺少可执行文件或超时无法确定渲染环境。
    raise ValueError("本地 Mermaid 渲染器不可用") from exc  # 不生成猜测的版本号。
  version = (version_result.stdout or version_result.stderr).strip()  # 记录实际进程报告的版本。
  if version_result.returncode != 0 or not version:  # 无版本号时不能形成可复核记录。
    raise ValueError("本地 Mermaid 渲染器版本无法核实")  # 不把未知版本冒充成功。
  fingerprint = sha256(mermaid_text.encode("utf-8")).hexdigest()  # 将渲染结果绑定到当次 Mermaid 字节。
  with tempfile.TemporaryDirectory(prefix="plan2graph-render-") as directory:  # 输入和输出都留在本机临时目录。
    source = Path(directory) / "graph.mmd"  # 创建本次渲染的唯一源码路径。
    target = Path(directory) / "graph.svg"  # 输出 SVG 用于核对实际渲染结果。
    source.write_text(mermaid_text, encoding="utf-8")  # 不传递原计划或标注文件。
    try:  # 限制渲染器运行时间，错误仍记为渲染失败。
      result = subprocess.run([executable, "-i", str(source), "-o", str(target)], capture_output=True, text=True, timeout=timeout, check=False)  # 按 Mermaid CLI 参数调用。
    except subprocess.TimeoutExpired:  # 超时也属于可报告的真实渲染失败。
      return {"status": "失败", "renderer": executable, "renderer_version": version, "source_sha256": fingerprint, "failure_reason": "本地渲染超时"}  # 不冒充成功。
    except OSError as exc:  # 进程无法启动属于渲染环境问题。
      raise ValueError("本地 Mermaid 渲染器无法执行") from exc  # 不将未执行当成渲染失败。
    if result.returncode != 0:  # 非零退出码不能由输出文件存在覆盖。
      reason = (result.stderr or result.stdout).strip() or f"渲染器退出码 {result.returncode}"  # 保留渲染失败诊断。
      return {"status": "失败", "renderer": executable, "renderer_version": version, "source_sha256": fingerprint, "failure_reason": reason}  # 失败仍进入渲染率分母。
    try:  # 成功退出后还需要确认确实输出了 SVG。
      image = ElementTree.parse(target).getroot()  # XML 解析可排除空文件和坏产物。
    except (OSError, ElementTree.ParseError):  # 缺文件或错误 XML 不是渲染成功。
      return {"status": "失败", "renderer": executable, "renderer_version": version, "source_sha256": fingerprint, "failure_reason": "渲染器没有产出有效 SVG"}  # 留下失败原因。
    if image.tag != "{http://www.w3.org/2000/svg}svg":  # 其他 XML 不能被误认为 Mermaid 图。
      return {"status": "失败", "renderer": executable, "renderer_version": version, "source_sha256": fingerprint, "failure_reason": "渲染器产物不是 SVG"}  # 拒绝错文件。
  return {"status": "成功", "renderer": executable, "renderer_version": version, "source_sha256": fingerprint, "failure_reason": None}  # 仅本机进程实际成功后返回通过。


def evaluate_file(document_path: Path, server_root: Path, record_path: Path, expected_run_id: str, renderer: str, *, mode: Literal["synthetic", "current"] = "synthetic") -> dict[str, object]:  # 从磁盘记录到本机渲染与汇总的完整离线入口。
  if mode not in ("synthetic", "current"):  # 外部渲染命令启动前先限制来源模式。
    raise ValueError("评估模式无效")  # 不接受未知模式。
  _nonempty_text(expected_run_id, "run_id")  # 错误批次不能触发渲染进程。
  records = load_and_validate_record_references(document_path, server_root, record_path)  # 先核对 20 条记录的文件引用。
  for record in records:  # 所有已运行样例都必须在渲染前属于同一批次。
    if record.get("status") != "未运行" and (record.get("source") != ("本地离线构造" if mode == "synthetic" else "本轮真实调用") or record.get("run_id") != expected_run_id):  # 失败样例也不得跨批次混入。
      raise ValueError("评估记录来源或 run_id 与评估模式不符")  # 避免先渲染后发现报告数据无效。
  prepared: list[dict[str, object]] = []  # 不修改输入 JSON 或其磁盘内容。
  for record in records:  # 为每条成功图重新取得渲染结果。
    if record.get("status") == "成功出图":  # 失败和未运行无需渲染。
      mermaid_text = _nonempty_text(record.get("mermaid_text"), "Mermaid 源码")  # 只能使用当次记录保存的源码。
      prepared.append({**record, "render_check": render_with_local_mmdc(mermaid_text, renderer)})  # 忽略文件中自称成功的旧渲染记录。
    else:  # 无成功输出的样例保留原始字段。
      prepared.append(dict(record))  # 不伪造渲染结果。
  report = evaluate_records(document_path, server_root, prepared, expected_run_id, mode=mode)  # 在全部渲染后统一核对字段与四项指标。
  report["render_evidence"] = "本机指定的 Mermaid CLI 本次执行；未证明输入记录来源"  # 明确渲染执行与模型来源是不同证据。
  return report  # 返回包含逐例计数和失败原因的报告。


def main(argv: list[str] | None = None) -> int:  # 提供无需联网或调用模型的评估命令。
  parser = argparse.ArgumentParser(description="离线核对 Plan2Graph 评估记录并使用本机 Mermaid CLI 渲染成功图。")  # 明确命令性质。
  parser.add_argument("records", type=Path, help="本地 JSON 记录文件")  # 输入只能来自明确的文件路径。
  parser.add_argument("--run-id", required=True, help="要核对的批次编号")  # 不合并不同运行批次。
  parser.add_argument("--renderer", required=True, help="本地 mmdc 可执行文件路径")  # 不安装或调用线上渲染服务。
  parser.add_argument("--mode", choices=("synthetic", "current"), default="synthetic", help="合成测试或本轮来源声明")  # 默认不宣称真实模型质量。
  args = parser.parse_args(argv)  # 将输入参数与项目 CLI 分开。
  server_root = Path(__file__).resolve().parents[2]  # 从已安装包对应的工程目录定位本地标注。
  document = server_root / "doc" / "阶段5.2评估指标口径.md"  # 使用固定清单而非扫描目录猜样例。
  try:  # 缺少记录、渲染器或裁定都不能产出成功报告。
    report = evaluate_file(document, server_root, args.records, args.run_id, args.renderer, mode=args.mode)  # 执行全部本地检查。
  except ValueError as exc:  # 面向 IDE/终端给出简明的错误类型。
    print(f"离线评估未完成：{exc}", file=sys.stderr)  # 不输出部分指标 JSON。
    return 2  # 非零状态提示报告不可发布。
  print(json.dumps(report, ensure_ascii=False, indent=2))  # 将完整逐例报告输出到标准输出。
  return 0  # 仅表示离线输入和计算已完成，不证明模型效果达标。


if __name__ == "__main__":  # 支持 python -m plan2graph.evaluation 从 IDE 运行。
  raise SystemExit(main())  # 将命令状态返回给调用者。
