"""检查阶段 5.2 离线记录与原始指标计数的边界。"""

from hashlib import sha256  # 为合成渲染记录计算对应源码指纹。
import json  # 序列化仅供离线读取测试的临时 JSON 文件。
from pathlib import Path  # 构造临时标注目录并交给离线核对入口。
import subprocess  # 为本地渲染器的测试桩构造进程结果。

import pytest  # 用于核对无效记录会被拒绝。

from plan2graph.evaluation import _annotation_gold_tasks, count_aligned_task_coverage, count_recorded_mermaid_renders, count_structurally_valid_outputs, count_task_coverage, count_unsupported_hard_edges, decode_graph_snapshot, evaluate_file, evaluate_records, is_graph_structurally_valid, is_success_output_consistent, load_and_validate_record_references, load_fixed_case_inventory, load_record_batch, main, render_with_local_mmdc, validate_annotation_reference, validate_batch_references, validate_case_inventory, validate_current_run_identity, validate_plan_reference, validate_unrun_record  # 导入纯离线记录校验、真实渲染入口与指标汇总。
from plan2graph.mermaid import render_mermaid  # 从合成图生成测试所需的 Mermaid 源码。
from plan2graph.models import GraphRelation, GraphTask, PlanGraph  # 构造不涉及模型的任务图。


def test_unrun_record_without_output_is_valid() -> None:  # 未运行记录可以只有身份和状态。
  record = {"status": "未运行", "source": "未运行（无输出来源）"}  # 准备未填写运行身份和图的记录。
  validate_unrun_record(record)  # 不抛错表示该最小边界通过。


def test_unrun_record_accepts_null_optional_fields() -> None:  # 可选字段显式为空也不冒充输出。
  record = {  # 准备带空值的未运行记录。
    "status": "未运行",  # 声明该样例尚未运行。
    "source": "未运行（无输出来源）",  # 明确没有输出来源。
    "run_id": None,  # 未运行没有批次编号。
    "graph": None,  # 未运行没有结构化图。
    "mermaid_text": None,  # 未运行没有 Mermaid 源码。
  }  # 结束记录。
  validate_unrun_record(record)  # 空值不应被误判为已有结果。


@pytest.mark.parametrize(  # 分别核对状态与来源不一致的情况。
  ("field", "value"),  # 指定要替换的字段和错误值。
  [  # 枚举两种错误身份。
    ("status", "成功出图"),  # 成功状态不能进入未运行校验入口。
    ("source", "本轮真实调用"),  # 未运行不能声称有真实调用来源。
  ],  # 结束错误身份列表。
)  # 结束参数化设置。
def test_unrun_record_rejects_inconsistent_identity(field: str, value: str) -> None:  # 检查身份字段一致性。
  record = {"status": "未运行", "source": "未运行（无输出来源）"}  # 先准备合法身份。
  record[field] = value  # 将一个身份字段替换成错误值。
  with pytest.raises(ValueError):  # 不一致的记录应被拒绝。
    validate_unrun_record(record)  # 校验不能静默接受错误身份。


@pytest.mark.parametrize(  # 分别核对未运行记录中的伪造输出。
  ("field", "value"),  # 指定要加入的字段和值。
  [  # 枚举批次、结构化图和 Mermaid 源码。
    ("run_id", "run-1"),  # 未运行不应有批次身份。
    ("run_id", ""),  # 空字符串也不能充作批次身份。
    ("graph", {}),  # 空图对象仍然是假装存在图。
    ("mermaid_text", ""),  # 空源码仍然是假装存在源码。
  ],  # 结束伪造输出列表。
)  # 结束参数化设置。
def test_unrun_record_rejects_run_or_output(field: str, value: object) -> None:  # 校验无运行结果的边界。
  record = {"status": "未运行", "source": "未运行（无输出来源）"}  # 先准备合法的未运行身份。
  record[field] = value  # 填入不该出现的运行信息或输出。
  with pytest.raises(ValueError, match=field):  # 错误提示应指出具体字段。
    validate_unrun_record(record)  # 拒绝将该记录当成干净的未运行样例。


@pytest.mark.parametrize(  # 本轮真实调用的三类运行结果均有明确状态。
  "status",  # 每次改变运行结果状态。
  ["成功出图", "明确冲突停止", "其他失败"],  # 成功与两类失败都属于已运行样例。
)  # 结束参数化设置。
def test_current_run_identity_accepts_recorded_outcomes(status: str) -> None:  # 不因失败结果而排除已运行样例。
  record = {"case_id": "example", "run_id": "run-1", "source": "本轮真实调用", "status": status}  # 准备同一批次的身份字段。
  validate_current_run_identity(record, "run-1")  # 仅核对身份与状态，不声称这是真实模型结果。


@pytest.mark.parametrize(  # 历史、合成、未运行和混入其他批次均应拒绝。
  ("field", "value"),  # 每次破坏一个身份字段。
  [  # 枚举不能进入本轮指标的记录。
    ("case_id", ""),  # 匿名记录没有可核对的样例身份。
    ("run_id", "run-old"),  # 历史批次不能混入当前批次。
    ("run_id", None),  # 缺失批次也不能计入。
    ("source", "历史记录"),  # 历史记录不能靠状态冒充新调用。
    ("source", "本地离线构造"),  # 合成记录不能冒充模型质量。
    ("status", "未运行"),  # 未运行样例不属于已运行质量分母。
    ("status", "未知"),  # 未知状态尚不能分类。
  ],  # 结束错误身份列表。
)  # 结束参数化设置。
def test_current_run_identity_rejects_mixed_sources(field: str, value: object) -> None:  # 身份不一致时拒绝计数。
  record = {"case_id": "example", "run_id": "run-1", "source": "本轮真实调用", "status": "成功出图"}  # 准备合成的字段自洽记录。
  record[field] = value  # 将一个字段替换为不可信值。
  with pytest.raises(ValueError):  # 不能静默纳入本轮汇总。
    validate_current_run_identity(record, "run-1")  # 校验应指出身份错误。


def test_current_run_identity_requires_nonempty_batch_id() -> None:  # 汇总入口必须指定批次。
  record = {"case_id": "example", "run_id": "run-1", "source": "本轮真实调用", "status": "成功出图"}  # 准备供身份校验的合成记录。
  with pytest.raises(ValueError, match="run_id"):  # 空批次不具备隔离意义。
    validate_current_run_identity(record, "")  # 不允许跨批次不加区分地计数。


def test_case_inventory_keeps_unrun_case_in_fixed_list() -> None:  # 完整集合必须包含未运行的样例。
  records = (  # 准备顺序与固定清单不同的合成记录。
    {"case_id": "second", "status": "未运行"},  # 未运行样例仍占据一条记录。
    {"case_id": "first", "status": "成功出图"},  # 已运行样例也占据一条记录。
  )  # 结束合成记录。
  validate_case_inventory(("first", "second"), records)  # 集合完整且每项唯一时不报错。


@pytest.mark.parametrize(  # 分别检查漏项、重复、清单外和匿名记录。
  ("records", "message"),  # 每次只改变记录集合及预期错误类型。
  [  # 枚举不能用于完整评估的集合。
    (({"case_id": "first"},), "缺少"),  # 固定样例即使未运行也不能被遗漏。
    (({"case_id": "first"}, {"case_id": "first"}, {"case_id": "second"}), "重复"),  # 同一样例不能重复计数。
    (({"case_id": "first"}, {"case_id": "second"}, {"case_id": "third"}), "清单外"),  # 未预先固定的样例不能混入。
    (({"case_id": "first"}, {"case_id": ""}, {"case_id": "second"}), "缺少 case_id"),  # 空身份不能静默跳过。
  ],  # 结束无效记录集合。
)  # 结束参数化设置。
def test_case_inventory_rejects_incomplete_or_duplicate_records(records: tuple[dict[str, str], ...], message: str) -> None:  # 不允许只统计已提交的子集。
  with pytest.raises(ValueError, match=message):  # 错误应指明固定集合的问题。
    validate_case_inventory(("first", "second"), records)  # 用预先给定的两个编号核对记录。


@pytest.mark.parametrize(  # 固定清单本身不能是空集合或含糊编号。
  "case_ids",  # 每次改变预设的样例编号。
  [(), ("first", "first"), ("first", ""), ("first", None)],  # 覆盖空清单、重复、空字符串和缺失编号。
)  # 结束参数化设置。
def test_case_inventory_rejects_invalid_expected_ids(case_ids: tuple[object, ...]) -> None:  # 不从错误的清单计算完整性。
  with pytest.raises(ValueError, match="固定样例清单"):  # 清单有误时直接报告。
    validate_case_inventory(case_ids, ({"case_id": "first"},))  # 不把记录本身当作基准。


def _local_inventory_document(tmp_path: Path, rows: tuple[str, ...]) -> Path:  # 创建只含清单表格的离线测试文档。
  document = tmp_path / "inventory.md"  # 将测试文档放在临时目录。
  lines = [  # 准备与口径文档相同的表格边界。
    "### 固定样例清单（本地评估范围）",  # 固定小节标题供读取入口定位。
    "| `case_id` | 标注文件 | 标注所指原计划 | 主覆盖类型 | 来源 |",  # 明确五列的字段含义。
    "| --- | --- | --- | --- | --- |",  # 明确五列表格分隔行。
    *rows,  # 注入本次需要检查的合成样例行。
    "",  # 表格在空行处结束。
    "## 四项指标",  # 后续章节不属于固定清单。
  ]  # 结束合成文档行。
  document.write_text("\n".join(lines), encoding="utf-8")  # 保存供离线读取的临时文档。
  return document  # 返回本次测试唯一的清单路径。


def test_fixed_inventory_loads_current_twenty_cases() -> None:  # 实际口径表应与仓库内本地标注集合对应。
  server_root = Path(__file__).resolve().parents[1]  # 定位测试所在工程根目录。
  document = server_root / "doc" / "阶段5.2评估指标口径.md"  # 只读使用当前固定清单文档。
  entries = load_fixed_case_inventory(document)  # 将文档表格转换成离线清单项。
  assert len(entries) == 20  # 当前已确认的本地标注恰有二十份。
  assert {entry["annotation_path"] for entry in entries} == {f"tests/fixtures/{path.name}" for path in (server_root / "tests" / "fixtures").glob("*_annotation.md")}  # 不把旧八份或目录外文件计入清单。
  assert all((server_root / entry["plan_path"]).is_file() for entry in entries)  # 文档所指的原计划副本都在本地。
  assert all("transfer_permission" not in entry for entry in entries)  # 来源列不能被误读成模型传输许可。


@pytest.mark.parametrize(  # 固定表格中的漏项、重复和损坏行不能静默略过。
  ("rows", "message"),  # 每次改变输入行和预期错误。
  [  # 枚举不合格的清单数据。
    ((), "不能为空"),  # 空表格不构成固定评估集合。
    (("| `first` | `tests/fixtures/first_annotation.md` | `tests/fixtures/plans/合成.md` | 链式依赖 | 合成 |",) * 2, "重复"),  # 同一样例不能重复进入集合。
    (("| `first` | `tests/fixtures/second_annotation.md` | `tests/fixtures/plans/合成.md` | 链式依赖 | 合成 |",), "case_id"),  # 标注文件名必须对应样例编号。
    (("| `first` | `tests/fixtures/first_annotation.md` | `tests/fixtures/plans/合成.md` | 链式依赖 | |",), "格式"),  # 来源声明不能留空。
  ],  # 结束无效表格数据。
)  # 结束参数化设置。
def test_fixed_inventory_rejects_invalid_rows(tmp_path: Path, rows: tuple[str, ...], message: str) -> None:  # 损坏行应明确阻断读取。
  document = _local_inventory_document(tmp_path, rows)  # 保存本次合成表格。
  with pytest.raises(ValueError, match=message):  # 错误应指出缺失或不一致。
    load_fixed_case_inventory(document)  # 不退回从目录扫描推断清单。


def test_fixed_inventory_rejects_missing_or_changed_table(tmp_path: Path) -> None:  # 表格位置和列结构必须清楚。
  document = tmp_path / "missing.md"  # 准备不存在的文档路径。
  with pytest.raises(ValueError, match="缺失或不可读"):  # 文档缺失应直接报错。
    load_fixed_case_inventory(document)  # 不能接受空清单。
  document = _local_inventory_document(tmp_path, ("| `first` | `tests/fixtures/first_annotation.md` | `tests/fixtures/plans/合成.md` | 链式依赖 | 合成 |",))  # 准备一份可变更的合成表格。
  document.write_text(document.read_text(encoding="utf-8").replace("主覆盖类型", "许可"), encoding="utf-8")  # 模拟第五列之前的表头含义被改动。
  with pytest.raises(ValueError, match="表头"):  # 不允许错误列名仍按来源或覆盖类型读取。
    load_fixed_case_inventory(document)  # 表头漂移必须可见。


def test_annotation_reference_matches_fixed_path_and_file_bytes(tmp_path: Path) -> None:  # 本地标注应同时匹配清单路径和字节指纹。
  fixtures = tmp_path / "tests" / "fixtures"  # 创建不接触项目样例的临时目录路径。
  fixtures.mkdir(parents=True)  # 准备模拟工程内标注目录。
  annotation = fixtures / "first_annotation.md"  # 准备固定样例对应的标注文件路径。
  annotation.write_text("# 合成标注\n", encoding="utf-8")  # 写入纯离线的测试标注。
  fingerprint = sha256(annotation.read_bytes()).hexdigest()  # 对测试标注原始字节计算记录指纹。
  record = {"case_id": "first", "annotation_path": "tests/fixtures/first_annotation.md", "annotation_sha256": fingerprint}  # 准备与清单及文件一致的合成记录。
  validate_annotation_reference(record, tmp_path, "tests/fixtures/first_annotation.md")  # 路径和指纹一致时通过。
  annotation.write_text("# 已改动的合成标注\n", encoding="utf-8")  # 模拟标注文件在记录生成后被改动。
  with pytest.raises(ValueError, match="指纹"):  # 旧记录不能继续对应已改动标注。
    validate_annotation_reference(record, tmp_path, "tests/fixtures/first_annotation.md")  # 拒绝内容已经漂移的记录。


@pytest.mark.parametrize(  # 标注身份、清单路径与记录路径都必须吻合。
  ("field", "value", "message"),  # 每次破坏一个字段并指定错误类型。
  [  # 枚举不可靠的标注引用。
    ("case_id", "", "case_id"),  # 匿名记录无法指向固定样例。
    ("case_id", "second", "固定清单"),  # 不能借别的编号引用当前标注。
    ("annotation_path", "tests/fixtures/second_annotation.md", "记录的标注路径"),  # 当前记录不能偷偷换用另一份标注。
    ("annotation_sha256", "old", "指纹"),  # 错误或过期的内容指纹不能通过。
  ],  # 结束无效引用列表。
)  # 结束参数化设置。
def test_annotation_reference_rejects_mismatched_record(tmp_path: Path, field: str, value: str, message: str) -> None:  # 每次只验证一个记录错配原因。
  fixtures = tmp_path / "tests" / "fixtures"  # 准备合成标注目录。
  fixtures.mkdir(parents=True)  # 创建本次测试独立的目录。
  annotation = fixtures / "first_annotation.md"  # 选择固定样例的测试标注。
  annotation.write_text("# 合成标注\n", encoding="utf-8")  # 保存可计算指纹的本地内容。
  record = {"case_id": "first", "annotation_path": "tests/fixtures/first_annotation.md", "annotation_sha256": sha256(annotation.read_bytes()).hexdigest()}  # 先构造完整合成记录。
  record[field] = value  # 仅替换本次需要验证的字段。
  with pytest.raises(ValueError, match=message):  # 错误应指出对应的不一致来源。
    validate_annotation_reference(record, tmp_path, "tests/fixtures/first_annotation.md")  # 错配标注不能进入后续汇总。


def test_annotation_reference_rejects_missing_file(tmp_path: Path) -> None:  # 标注文件不存在时不能假定金标准仍可核对。
  record = {"case_id": "first", "annotation_path": "tests/fixtures/first_annotation.md", "annotation_sha256": "old"}  # 准备只有路径和旧指纹的合成记录。
  with pytest.raises(ValueError, match="缺失或不可读"):  # 文件不存在应明确报告。
    validate_annotation_reference(record, tmp_path, "tests/fixtures/first_annotation.md")  # 不靠记录中的指纹伪造文件存在。


def test_annotation_reference_rejects_symlink_outside_fixtures(tmp_path: Path) -> None:  # 引用标注不得通过符号链接跳出样例目录。
  fixtures = tmp_path / "tests" / "fixtures"  # 准备受限读取目录。
  fixtures.mkdir(parents=True)  # 创建目录用于放置测试链接。
  external = tmp_path / "external.md"  # 指向目录外的合成文件。
  external.write_text("# 外部合成内容\n", encoding="utf-8")  # 写入不属于标注目录的内容。
  (fixtures / "first_annotation.md").symlink_to(external)  # 在标注目录内建立指向外部的链接。
  record = {"case_id": "first", "annotation_path": "tests/fixtures/first_annotation.md", "annotation_sha256": sha256(external.read_bytes()).hexdigest()}  # 即使指纹匹配外部内容也不能通过。
  with pytest.raises(ValueError, match="fixtures"):  # 越界读取应在计算内容前被拒绝。
    validate_annotation_reference(record, tmp_path, "tests/fixtures/first_annotation.md")  # 不读取目录外文件冒充标注。


def _local_plan_reference(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:  # 构造不涉及真实样例的完整本地引用。
  annotation_path = "tests/fixtures/first_annotation.md"  # 固定一条测试标注路径。
  plan_path = "tests/fixtures/plans/合成计划.md"  # 固定同仓库格式的测试原计划路径。
  annotation = tmp_path / annotation_path  # 将标注放在临时工程目录内。
  plan = tmp_path / plan_path  # 将原计划放在临时 plans 目录内。
  plan.parent.mkdir(parents=True)  # 同时创建 fixtures 和 plans 目录。
  plan.write_text("先完成任务一。\n", encoding="utf-8")  # 写入仅供离线测试的原计划。
  annotation.write_text(f"# 合成标注\n\n原计划：{plan_path}\n", encoding="utf-8")  # 让标注明确指向这份原计划。
  record = {  # 为同一对文件生成测试记录。
    "case_id": "first",  # 标注身份与固定路径相符。
    "annotation_path": annotation_path,  # 记录使用固定清单的标注路径。
    "annotation_sha256": sha256(annotation.read_bytes()).hexdigest(),  # 绑定标注的当前内容。
    "plan_path": plan_path,  # 记录使用标注声明的原计划路径。
    "plan_sha256": sha256(plan.read_bytes()).hexdigest(),  # 绑定原计划的当前内容。
  }  # 结束测试记录。
  return record, annotation, plan  # 返回可独立修改的临时文件与记录。


def test_plan_reference_matches_inventory_annotation_and_bytes(tmp_path: Path) -> None:  # 三处路径一致且两份文件指纹正确时通过。
  record, _, _ = _local_plan_reference(tmp_path)  # 创建可核对的离线文件和记录。
  validate_plan_reference(record, tmp_path, record["annotation_path"], record["plan_path"])  # 不抛错表示完整引用吻合。


@pytest.mark.parametrize(  # 清单路径和记录字段不能自行更换原计划。
  ("field", "value", "expected_path", "message"),  # 每次只改变一个引用位置。
  [  # 枚举记录错配、内容指纹缺失和清单路径越界。
    ("plan_path", "tests/fixtures/plans/另一计划.md", "tests/fixtures/plans/合成计划.md", "记录的原计划路径"),  # 记录不能与清单相悖。
    ("plan_sha256", "old", "tests/fixtures/plans/合成计划.md", "指纹"),  # 过期的内容指纹不能通过。
    ("plan_sha256", "old", "tests/fixtures/../external.md", "固定清单"),  # 即使记录含指纹也不能读越界路径。
  ],  # 结束参数化的错误引用。
)  # 结束参数化设置。
def test_plan_reference_rejects_bad_record_or_inventory(tmp_path: Path, field: str, value: str, expected_path: str, message: str) -> None:  # 核对错误引用会被准确报告。
  record, _, _ = _local_plan_reference(tmp_path)  # 准备自洽的基准数据。
  record[field] = value  # 只替换本次需要检查的记录字段。
  with pytest.raises(ValueError, match=message):  # 错误应指出对应的问题。
    validate_plan_reference(record, tmp_path, record["annotation_path"], expected_path)  # 不允许引用错位。


@pytest.mark.parametrize(  # 标注里的原计划声明必须恰好一条且与清单吻合。
  "annotation_text",  # 每次替换整份合成标注内容。
  ["# 无原计划声明\n", "原计划：tests/fixtures/plans/另一计划.md\n", "原计划：tests/fixtures/plans/合成计划.md\n原计划：tests/fixtures/plans/合成计划.md\n"],  # 覆盖缺失、错配和重复。
)  # 结束参数化设置。
def test_plan_reference_rejects_bad_annotation_declaration(tmp_path: Path, annotation_text: str) -> None:  # 有歧义的标注不能靠记录补齐。
  record, annotation, _ = _local_plan_reference(tmp_path)  # 创建原本自洽的测试文件。
  annotation.write_text(annotation_text, encoding="utf-8")  # 模拟标注中存在错误声明。
  record["annotation_sha256"] = sha256(annotation.read_bytes()).hexdigest()  # 确保失败确实来自原计划声明而非旧指纹。
  with pytest.raises(ValueError, match="标注中的原计划引用"):  # 错误应定位到标注声明。
    validate_plan_reference(record, tmp_path, record["annotation_path"], record["plan_path"])  # 拒绝不确定的引用。


def test_plan_reference_rejects_modified_or_missing_plan(tmp_path: Path) -> None:  # 不以旧记录代替本地原计划。
  record, _, plan = _local_plan_reference(tmp_path)  # 准备可修改的临时计划。
  plan.write_text("改动后的计划。\n", encoding="utf-8")  # 模拟记录产生后原计划改动。
  with pytest.raises(ValueError, match="指纹"):  # 指纹不再匹配时拒绝旧记录。
    validate_plan_reference(record, tmp_path, record["annotation_path"], record["plan_path"])  # 核对原计划文件当下内容。
  plan.unlink()  # 模拟原计划副本随后遗失。
  with pytest.raises(ValueError, match="缺失或不可读"):  # 缺失不能视作已核对。
    validate_plan_reference(record, tmp_path, record["annotation_path"], record["plan_path"])  # 核对原计划是否仍在。


def test_plan_reference_rejects_symlink_outside_plans(tmp_path: Path) -> None:  # 不能利用文件链接越过计划目录。
  record, _, plan = _local_plan_reference(tmp_path)  # 准备正确的标注和原计划记录。
  external = tmp_path / "external.md"  # 另建 plans 目录之外的文件。
  external.write_bytes(plan.read_bytes())  # 保持内容和指纹相同以检验路径限制。
  plan.unlink()  # 移除原计划并准备以链接代替。
  plan.symlink_to(external)  # 链接指向目录外的同内容文件。
  with pytest.raises(ValueError, match="plans"):  # 即使字节吻合也不能越界读取。
    validate_plan_reference(record, tmp_path, record["annotation_path"], record["plan_path"])  # 拒绝目录外的文件。


def _single_case_inventory(tmp_path: Path) -> Path:  # 为合成记录准备相同身份的固定清单。
  row = "| `first` | `tests/fixtures/first_annotation.md` | `tests/fixtures/plans/合成计划.md` | 链式依赖 | 合成 |"  # 声明测试样例的路径和文档来源。
  return _local_inventory_document(tmp_path, (row,))  # 写入只含这一条样例的临时表格。


def test_batch_references_accepts_single_use_records(tmp_path: Path) -> None:  # 一次性生成器不能在集合核对后丢失记录。
  record, _, _ = _local_plan_reference(tmp_path)  # 准备同一份临时标注和原计划。
  document = _single_case_inventory(tmp_path)  # 准备指向这对文件的固定清单。
  records = (item for item in (record,))  # 模拟只能遍历一次的离线记录输入。
  validate_batch_references(document, tmp_path, records)  # 集合完整且文件内容一致时通过。


@pytest.mark.parametrize(  # 批量入口必须在读取文件前核对记录集合。
  ("case_ids", "message"),  # 每次改动记录身份集合。
  [  # 枚举漏项、重复项和清单外项。
    ((), "缺少"),  # 固定清单中的样例不能因未运行而省略。
    (("first", "first"), "重复"),  # 同一编号不能出现两条记录。
    (("first", "outside"), "清单外"),  # 文档外的样例不能混入当前批次。
  ],  # 结束无效集合列表。
)  # 结束参数化设置。
def test_batch_references_rejects_incomplete_inventory(tmp_path: Path, case_ids: tuple[str, ...], message: str) -> None:  # 不接受按已提交子集冒充完整批次。
  record, _, _ = _local_plan_reference(tmp_path)  # 准备文件指纹正确的基准记录。
  document = _single_case_inventory(tmp_path)  # 固定唯一应出现的样例。
  records = tuple({**record, "case_id": case_id} for case_id in case_ids)  # 仅修改批次中每条记录的编号。
  with pytest.raises(ValueError, match=message):  # 错误应指出集合不完整或混入项。
    validate_batch_references(document, tmp_path, records)  # 不静默忽略任何记录。


def test_batch_references_rejects_changed_plan_or_record_path(tmp_path: Path) -> None:  # 批量入口须实际调用逐条引用检查。
  record, _, plan = _local_plan_reference(tmp_path)  # 准备可改动的测试原计划。
  document = _single_case_inventory(tmp_path)  # 固定该记录原本使用的两条路径。
  with pytest.raises(ValueError, match="记录的原计划路径"):  # 记录路径不能取代清单路径。
    validate_batch_references(document, tmp_path, ({**record, "plan_path": "tests/fixtures/plans/其他.md"},))  # 核对清单与记录的一致性。
  plan.write_text("原计划后续被修改。\n", encoding="utf-8")  # 模拟内容在记录生成后发生漂移。
  with pytest.raises(ValueError, match="指纹"):  # 旧记录不能继续用于新文件。
    validate_batch_references(document, tmp_path, (record,))  # 核对计划当前字节。


def test_batch_references_checks_current_twenty_local_files_without_model_call() -> None:  # 用真实文档和本地文件只验证路径及指纹串联。
  server_root = Path(__file__).resolve().parents[1]  # 找到测试工程根目录。
  document = server_root / "doc" / "阶段5.2评估指标口径.md"  # 定位目前的二十项固定清单。
  inventory = load_fixed_case_inventory(document)  # 只读提取清单身份和路径。
  records = tuple(  # 临时构造文件引用记录，不写盘也不冒充模型输出。
    {  # 每条记录只保留本步骤要检查的字段。
      "case_id": entry["case_id"],  # 使用文档固定的样例身份。
      "annotation_path": entry["annotation_path"],  # 使用文档固定的标注路径。
      "annotation_sha256": sha256((server_root / entry["annotation_path"]).read_bytes()).hexdigest(),  # 计算当前本地标注的指纹。
      "plan_path": entry["plan_path"],  # 使用文档固定的原计划路径。
      "plan_sha256": sha256((server_root / entry["plan_path"]).read_bytes()).hexdigest(),  # 计算当前本地原计划的指纹。
    }  # 结束一条仅供离线验证的测试记录。
    for entry in inventory  # 为清单中每个样例准备一条对应记录。
  )  # 结束纯内存的测试记录集合。
  validate_batch_references(document, server_root, records)  # 确认当前二十条路径和标注引用均可本地核对。


def test_record_file_loads_and_checks_synthetic_references(tmp_path: Path) -> None:  # 本地 JSON 可接入现有清单与文件引用检查。
  record, _, plan = _local_plan_reference(tmp_path)  # 准备不涉及真实模型输出的临时计划与记录。
  document = _single_case_inventory(tmp_path)  # 固定本次测试唯一的样例身份。
  record_file = tmp_path / "records.json"  # 在临时目录存放合成 JSON 文件。
  record_file.write_text(json.dumps({"records": [record]}, ensure_ascii=False), encoding="utf-8")  # 用标准序列化器保存一份合成记录。
  loaded = load_and_validate_record_references(document, tmp_path, record_file)  # 读取后必须通过固定清单与文件指纹校验。
  assert loaded == (record,)  # 数据保持原样，不凭路径补造运行结果。
  plan.write_text("修改后的合成计划。\n", encoding="utf-8")  # 模拟保存记录后原计划发生变化。
  with pytest.raises(ValueError, match="指纹"):  # 旧 JSON 不应继续通过本地引用核对。
    load_and_validate_record_references(document, tmp_path, record_file)  # 再次读取文件并检查当前计划。


@pytest.mark.parametrize(  # 损坏 JSON、字段覆盖和错误批次结构都必须被拒绝。
  ("content", "message"),  # 每次检查一种无效内容和预期提示。
  [  # 枚举常见的文件格式错误。
    ("{", "格式"),  # 未闭合的对象无法作为 JSON 解析。
    ('{"records":[{"case_id":"first","case_id":"second"}]}', "重复字段"),  # 不允许后一个编号覆盖前一个编号。
    ('{"records":[{"count":NaN}]}', "非标准数值"),  # 不接受标准 JSON 之外的非有限数值。
    ('{"records":[]}', "非空对象列表"),  # 空数组不能充作完整批次。
    ('{"records":[42]}', "非空对象列表"),  # 记录必须是 JSON 对象。
    ('{"records":[{}],"source":"本轮真实调用"}', "顶层"),  # 顶层其他声明不能冒充逐项来源证据。
  ],  # 结束无效 JSON 列表。
)  # 结束参数化设置。
def test_record_file_rejects_invalid_json_or_shape(tmp_path: Path, content: str, message: str) -> None:  # 格式检查在引用校验前完成。
  record_file = tmp_path / "records.json"  # 准备每次测试独立的临时路径。
  record_file.write_text(content, encoding="utf-8")  # 写入本次需要拒绝的合成 JSON。
  with pytest.raises(ValueError, match=message):  # 不能静默丢弃损坏的记录。
    load_record_batch(record_file)  # 只测试本地文件读取与结构边界。


def test_record_file_rejects_missing_file(tmp_path: Path) -> None:  # 缺失的 JSON 文件不能当作空批次。
  with pytest.raises(ValueError, match="缺失或不可读"):  # 提示必须指向输入文件缺失。
    load_record_batch(tmp_path / "missing.json")  # 不生成任何占位样例。


def test_task_coverage_counts_only_manually_matched_ids() -> None:  # 核对覆盖率的分子与分母原始计数。
  assert count_task_coverage(3, [1, 3]) == (2, 3)  # 三个金标准任务中只覆盖两个。
  assert count_task_coverage(3, []) == (0, 3)  # 没有成功匹配时仍保留全部金标准任务作为分母。


@pytest.mark.parametrize(  # 检查金标准总数不能由空值或错误类型构成。
  "gold_task_count",  # 本组只改变金标准任务总数。
  [0, -1, True, "3"],  # 零、负数、布尔值及字符串均无效。
)  # 结束参数化设置。
def test_task_coverage_rejects_invalid_gold_count(gold_task_count: object) -> None:  # 防止无效分母进入指标。
  with pytest.raises(ValueError, match="金标准任务数"):  # 应明确报告分母问题。
    count_task_coverage(gold_task_count, [])  # 无效金标准总数不能计数。


@pytest.mark.parametrize(  # 检查不允许重复或越界的人工匹配编号。
  "matched_gold_ids",  # 本组只改变人工匹配集合。
  [[1, 1], [0], [4], [True], ["1"]],  # 覆盖重复、越界及错误类型。
)  # 结束参数化设置。
def test_task_coverage_rejects_invalid_matches(matched_gold_ids: list[object]) -> None:  # 防止重复节点虚增覆盖数。
  with pytest.raises(ValueError, match="编号"):  # 错误应指出匹配编号。
    count_task_coverage(3, matched_gold_ids)  # 不接受未经规范化的无效匹配。


def _graph_with_relations(relations: tuple[GraphRelation, ...]) -> PlanGraph:  # 构造纯离线的三任务图供计数测试使用。
  tasks = (  # 准备三个可被关系引用的任务。
    GraphTask("T1", "任务一", ("任务一",), 0),  # 第一个任务。
    GraphTask("T2", "任务二", ("任务二",), 1),  # 第二个任务。
    GraphTask("T3", "任务三", ("任务三",), 2),  # 第三个任务。
  )  # 结束任务列表。
  return PlanGraph(tasks, relations, ())  # 返回没有跳过关系的图。


def test_success_output_pair_matches_generated_source() -> None:  # 成功记录必须对应同一张图生成的源码。
  graph = _graph_with_relations(())  # 准备三任务无连线的合成图。
  record = {"status": "成功出图", "graph": graph, "mermaid_text": render_mermaid(graph)}  # 将图与其源码放入同一条记录。
  assert is_success_output_consistent(record)  # 字段自洽时通过一致性检查。
  record["mermaid_text"] = 'flowchart LR\n  T1["另一任务"]\n'  # 模拟错配到另一张图的源码。
  assert not is_success_output_consistent(record)  # 错配不能冒充同一份输出。


@pytest.mark.parametrize(  # 检查状态错误、缺图和缺源码这三类不完整记录。
  ("field", "value"),  # 每次只替换一个记录字段。
  [  # 枚举不能核对的成功输出记录。
    ("status", "未运行"),  # 未运行样例不能进入成功图校验。
    ("graph", None),  # 成功图缺失时不能从文本逆推出图。
    ("mermaid_text", ""),  # 空 Mermaid 源码不能算已捕获。
  ],  # 结束不完整记录。
)  # 结束参数化设置。
def test_success_output_pair_rejects_missing_fields(field: str, value: object) -> None:  # 缺项不能伪装成一致性检查失败。
  graph = _graph_with_relations(())  # 准备合成的完整图。
  record = {"status": "成功出图", "graph": graph, "mermaid_text": render_mermaid(graph)}  # 准备初始完整记录。
  record[field] = value  # 注入一项不完整字段。
  with pytest.raises(ValueError):  # 不完整记录应明确报错。
    is_success_output_consistent(record)  # 不以布尔值掩盖缺失的成功输出。


def test_success_output_pair_keeps_invalid_graph_for_structure_count() -> None:  # 一致性问题不应抹掉无效成功图。
  valid_graph = _graph_with_relations(())  # 准备一张有效结构图。
  invalid_graph = _graph_with_relations((GraphRelation("T1", "T4", "hard", "不存在的端点", "无效端点"),))  # 准备端点缺失的成功图。
  record = {"status": "成功出图", "graph": invalid_graph, "mermaid_text": render_mermaid(invalid_graph)}  # 记录原样生成的源码。
  assert is_success_output_consistent(record)  # 图与源码对应不等于图的结构有效。
  assert count_structurally_valid_outputs((valid_graph, invalid_graph)) == (1, 2)  # 无效图仍进入结构分母。
  malformed_graph = PlanGraph((GraphTask("X", "坏编号", ("坏编号",), 0),), (), ())  # 编号格式错误使现有生成器无法重建源码。
  malformed_record = {"status": "成功出图", "graph": malformed_graph, "mermaid_text": 'flowchart LR\n  X["坏编号"]\n'}  # 保留已捕获的非空源码。
  assert not is_success_output_consistent(malformed_record)  # 重建失败只标记不一致。
  assert count_structurally_valid_outputs((valid_graph, malformed_graph)) == (1, 2)  # 无法交给现有生成器的 ID 属于结构无效，但仍占成功输出分母。


def test_aligned_task_coverage_requires_one_verdict_per_output_node() -> None:  # 三个输出节点分别匹配、未匹配和匹配。
  graph = _graph_with_relations(())  # 准备一张无关系但有三个输出节点的图。
  assert count_aligned_task_coverage(graph, 4, {0: 1, 1: "未匹配", 2: 3}) == (2, 4)  # 只覆盖两个金标准任务，分母保留全部四个。


@pytest.mark.parametrize(  # 核对漏填、多填、重复匹配及未决裁定。
  "alignment",  # 每次替换一份输出节点裁定。
  [  # 枚举不能发布覆盖计数的裁定。
    {0: 1, 1: "未匹配"},  # 最后一个输出节点没有裁定。
    {0: 1, 1: "未匹配", 2: 3, 3: 4},  # 裁定了不存在的第四个输出节点。
    {0: 1, 1: 1, 2: "未匹配"},  # 两个输出节点不能重复覆盖同一金标准任务。
    {0: 1, 1: "待复核", 2: 3},  # 未决裁定不能冒充已经完成的未匹配。
    {0: 1, 1: None, 2: 3},  # 空值不能冒充明确的未匹配裁定。
    {0: 1, 1: "未匹配", True: 3},  # 布尔值不能充作输出节点位置。
  ],  # 结束无效裁定列表。
)  # 结束参数化设置。
def test_aligned_task_coverage_rejects_incomplete_or_invalid_verdicts(alignment: dict[object, object]) -> None:  # 人工对齐必须完整且一对一。
  with pytest.raises(ValueError):  # 各类未完成裁定应被拒绝。
    count_aligned_task_coverage(_graph_with_relations(()), 4, alignment)  # 不以部分人工匹配冒充完整任务覆盖。


def test_unsupported_hard_edges_count_actual_positions_only() -> None:  # 实线和虚线混排时只计实线。
  relations = (  # 准备两条实线和一条虚线。
    GraphRelation("T1", "T2", "hard", "二依赖一", "确定依赖"),  # 位置零是实线。
    GraphRelation("T1", "T3", "candidate", "三可能等待一", "待确认"),  # 位置一的虚线不计入分母。
    GraphRelation("T2", "T3", "hard", "三依赖二", "确定依赖"),  # 位置二是实线。
  )  # 结束关系。
  graph = _graph_with_relations(relations)  # 将关系列表放入图中。
  assert count_unsupported_hard_edges(graph, {0: "有依据", 2: "无依据"}) == (1, 2)  # 一条无依据实线占两条实际实线。


def test_unsupported_hard_edges_keep_duplicate_edges() -> None:  # 重复输出的实线仍逐条计数。
  hard = GraphRelation("T1", "T2", "hard", "二依赖一", "确定依赖")  # 准备一条可重复的关系。
  graph = _graph_with_relations((hard, hard))  # 两个列表位置实际都输出了实线。
  assert count_unsupported_hard_edges(graph, {0: "无依据", 1: "无依据"}) == (2, 2)  # 相同错边逐条计入分子和分母。


def test_unsupported_hard_edges_zero_denominator_stays_raw() -> None:  # 零实线只返回原始零计数。
  candidate = GraphRelation("T1", "T2", "candidate", "二也许等待一", "待确认")  # 准备一条虚线。
  graph = _graph_with_relations((candidate,))  # 图中没有任何实线。
  assert count_unsupported_hard_edges(graph, {}) == (0, 0)  # 不在此处写成百分比或通过。


@pytest.mark.parametrize(  # 分别核对漏裁定、虚线裁定和待复核。
  "verdicts",  # 本组只改变人工裁定映射。
  [{0: "有依据"}, {0: "有依据", 1: "无依据", 2: "无依据"}, {0: "有依据", 2: "待复核"}],  # 三种尚不能完成计数的情况。
)  # 结束参数化设置。
def test_unsupported_hard_edges_require_complete_verdicts(verdicts: dict[int, str]) -> None:  # 不发布不完整的实线指标。
  relations = (  # 准备实线、虚线、实线的顺序。
    GraphRelation("T1", "T2", "hard", "二依赖一", "确定依赖"),  # 位置零需要裁定。
    GraphRelation("T1", "T3", "candidate", "三可能等待一", "待确认"),  # 位置一不能作为实线裁定。
    GraphRelation("T2", "T3", "hard", "三依赖二", "确定依赖"),  # 位置二需要裁定。
  )  # 结束关系。
  with pytest.raises(ValueError, match="实线裁定"):  # 数据不完整时应明确报错。
    count_unsupported_hard_edges(_graph_with_relations(relations), verdicts)  # 不以已裁定部分冒充全部实线。


def test_graph_structure_accepts_isolated_task_and_mixed_acyclic_edges() -> None:  # 无连线节点和合法虚线都应保留。
  relations = (  # 准备实线与虚线相接但没有环的展示图。
    GraphRelation("T1", "T2", "hard", "二依赖一", "确定依赖"),  # 第一条关系是实线。
    GraphRelation("T2", "T3", "candidate", "三也许等待二", "待确认"),  # 第二条关系是虚线。
  )  # 结束展示关系列表。
  assert is_graph_structurally_valid(_graph_with_relations(relations))  # 三个任务及两条关系均有效。
  assert is_graph_structurally_valid(_graph_with_relations(()))  # 仅有孤立任务的非空图也有效。


def test_graph_structure_rejects_empty_or_duplicate_task_ids() -> None:  # 空图和重复编号均不能通过。
  assert not is_graph_structurally_valid(PlanGraph((), (), ()))  # 空任务图无效。
  duplicate_tasks = (  # 准备两条使用相同编号的任务。
    GraphTask("T1", "任务一", ("任务一",), 0),  # 第一处编号。
    GraphTask("T1", "任务二", ("任务二",), 1),  # 第二处重复编号。
  )  # 结束重复任务列表。
  assert not is_graph_structurally_valid(PlanGraph(duplicate_tasks, (), ()))  # 即使没有边也不能接受重复编号。


@pytest.mark.parametrize(  # 逐一检查端点、自依赖及两类环。
  "relations",  # 每次替换展示关系。
  [  # 枚举无效图中的关系列表。
    (GraphRelation("T1", "T4", "hard", "缺失节点", "无效端点"),),  # 目标端点不存在。
    (GraphRelation("T4", "T1", "candidate", "缺失节点", "无效端点"),),  # 候选关系的起点也必须存在。
    (GraphRelation("T1", "T1", "candidate", "自指", "待确认"),),  # 虚线自依赖仍是无效图。
    (GraphRelation("T1", "T2", "hard", "一到二", "确定依赖"), GraphRelation("T2", "T1", "hard", "二到一", "确定依赖")),  # 全实线环无效。
    (GraphRelation("T1", "T2", "hard", "一到二", "确定依赖"), GraphRelation("T2", "T1", "candidate", "二或许到一", "待确认")),  # 实线与虚线构成的展示环也无效。
  ],  # 结束无效关系列表。
)  # 结束参数化设置。
def test_graph_structure_rejects_invalid_display_relations(relations: tuple[GraphRelation, ...]) -> None:  # 无效边不能被判为结构通过。
  assert not is_graph_structurally_valid(_graph_with_relations(relations))  # 原始图应保留为未通过，而非自动修复。


def test_structure_count_keeps_invalid_success_in_denominator() -> None:  # 无效结构不能被当成坏记录排除。
  valid_graph = _graph_with_relations(())  # 准备一张只有孤立任务的有效成功图。
  invalid_relation = GraphRelation("T1", "T4", "hard", "指向缺失任务", "无效端点")  # 准备一条端点不存在的关系。
  invalid_graph = _graph_with_relations((invalid_relation,))  # 准备一张仍须计入成功输出总数的无效图。
  assert count_structurally_valid_outputs(iter((valid_graph, invalid_graph))) == (1, 2)  # 一张通过，两张都进入分母。
  assert count_structurally_valid_outputs(()) == (0, 0)  # 没有成功输出时只保留原始零计数。


def _synthetic_render_check(mermaid_text: str, status: str) -> dict[str, object]:  # 准备纯合成的渲染记录供一致性测试。
  return {  # 下列值不代表真实调用过渲染器。
    "status": status,  # 人工构造成功或失败结果。
    "renderer": "合成渲染器",  # 仅用于验证非空字段。
    "renderer_version": "test-1",  # 仅用于验证版本字段。
    "source_sha256": sha256(mermaid_text.encode("utf-8")).hexdigest(),  # 指向该测试源码。
    "failure_reason": "合成失败" if status == "失败" else None,  # 合成失败时保存原因。
  }  # 结束合成记录。


def test_recorded_render_count_keeps_failures_in_denominator() -> None:  # 渲染失败仍属于成功图的渲染率分母。
  first = 'flowchart LR\n  T1["接口"]\n'  # 准备第一份合成 Mermaid 源码。
  second = 'flowchart LR\n  T2["测试"]\n'  # 准备第二份合成 Mermaid 源码。
  outputs = ((first, _synthetic_render_check(first, "成功")), (second, _synthetic_render_check(second, "失败")))  # 构造一条成功和一条失败的测试记录。
  assert count_recorded_mermaid_renders(outputs) == (1, 2)  # 仅成功记录进入分子，两条都进入分母。
  assert count_recorded_mermaid_renders(()) == (0, 0)  # 没有成功图时保留零分母原始计数。


@pytest.mark.parametrize(  # 核对未执行、缺失环境和源码不匹配等不完整记录。
  ("field", "value"),  # 每次破坏一项渲染记录字段。
  [  # 枚举不能发布渲染计数的情况。
    ("status", "未执行"),  # 源码存在不等于实际渲染过。
    ("renderer", ""),  # 缺少渲染器名称。
    ("renderer_version", "未确认"),  # 不能用未知版本冒充可复核环境。
    ("source_sha256", "old-source"),  # 旧源码的渲染结果不能套用。
    ("status", "未知"),  # 未知结果不能算成功或失败。
  ],  # 结束错误字段列表。
)  # 结束参数化设置。
def test_recorded_render_count_rejects_incomplete_evidence(field: str, value: str) -> None:  # 离线计数要求记录字段自洽。
  mermaid_text = 'flowchart LR\n  T1["接口"]\n'  # 准备本次实际要核对的测试源码。
  check = _synthetic_render_check(mermaid_text, "成功")  # 先生成完整的合成成功记录。
  check[field] = value  # 将一个字段替换为无效值。
  with pytest.raises(ValueError, match="Mermaid"):  # 不能静默计算部分渲染结果。
    count_recorded_mermaid_renders(((mermaid_text, check),))  # 提交这份不完整记录。


def test_recorded_render_count_requires_failure_reason() -> None:  # 渲染失败必须保留诊断。
  mermaid_text = 'flowchart LR\n  T1["接口"]\n'  # 准备合成源码。
  check = _synthetic_render_check(mermaid_text, "失败")  # 准备失败记录。
  check["failure_reason"] = ""  # 删除可复核的失败原因。
  with pytest.raises(ValueError, match="失败记录缺少原因"):  # 不接受无解释的失败结论。
    count_recorded_mermaid_renders(((mermaid_text, check),))  # 不能将记录当成已完成核验。


def _snapshot(graph: PlanGraph) -> dict[str, object]:  # 用现有图结构构造可序列化的测试快照。
  def relation_data(relation: GraphRelation) -> dict[str, object]:  # 明确一条关系需要的五个字段。
    return {"before": relation.before, "after": relation.after, "kind": relation.kind, "source_quote": relation.source_quote, "reason": relation.reason}  # 保留原有关系顺序。
  return {  # 不根据 Mermaid 源码反推任务证据。
    "tasks": [{"id": task.id, "title": task.title, "source_quotes": list(task.source_quotes), "first_position": task.first_position} for task in graph.tasks],  # 保存任务与引文位置。
    "relations": [relation_data(relation) for relation in graph.relations],  # 保存展示图中的每条边。
    "skipped_relations": [{"relation": relation_data(item.relation), "skip_reason": item.skip_reason} for item in graph.skipped_relations],  # 保存未展示边及原因。
  }  # 结束结构化图快照。


def _complete_case(tmp_path: Path, case_id: str, status: str = "成功出图") -> tuple[str, dict[str, object]]:  # 创建只涉及临时文件的一条完整记录。
  annotation_path = f"tests/fixtures/{case_id}_annotation.md"  # 为本例确定标注路径。
  plan_path = f"tests/fixtures/plans/{case_id}.md"  # 为本例确定原计划路径。
  plan = tmp_path / plan_path  # 定位临时原计划文件。
  plan.parent.mkdir(parents=True, exist_ok=True)  # 准备临时 plans 目录。
  plan.write_text("任务一；任务二；任务三。\n", encoding="utf-8")  # 文件仅包含合成文本。
  annotation = tmp_path / annotation_path  # 定位对应标注。
  annotation.write_text(f"原计划：{plan_path}\n\n## 关键任务\n\n1. 任务一\n2. 任务二\n3. 任务三\n\n## 确定边\n", encoding="utf-8")  # 让金标准来自真实读取的测试标注。
  row = f"| `{case_id}` | `{annotation_path}` | `{plan_path}` | 链式依赖 | 合成 |"  # 生成固定清单行。
  record: dict[str, object] = {  # 每条记录都要绑定临时文件的当前字节。
    "case_id": case_id,  # 身份与清单一致。
    "annotation_path": annotation_path,  # 路径与标注一致。
    "annotation_sha256": sha256(annotation.read_bytes()).hexdigest(),  # 不使用旧标注指纹。
    "plan_path": plan_path,  # 保留金标准所指的原计划。
    "plan_sha256": sha256(plan.read_bytes()).hexdigest(),  # 不使用旧计划指纹。
    "gold_tasks": [{"id": index, "title": f"任务{label}"} for index, label in enumerate("一二三", 1)],  # 完全对应标注中的三项。
    "status": status,  # 指出成功、失败或未运行。
  }  # 结束共同身份字段。
  if status == "未运行":  # 未运行不应有模型或渲染结果。
    record.update({"source": "未运行（无输出来源）", "reason": "未获得传输许可"})  # 只记录原因。
    return row, record  # 未运行不会进入质量分母。
  record.update({  # 已运行的合成记录使用单一测试批次。
    "source": "本地离线构造",  # 不冒充真实模型输出。
    "run_id": "synthetic-1",  # 绑定合成测试批次。
    "execution": {"exit_code": 0 if status == "成功出图" else 6, "error_category": None if status == "成功出图" else "合成错误", "timestamp": "2026-10-20T10:00:00+08:00", "code_version": "test", "prompt_version": "test", "model_alias": "未确认", "server_version": "未确认", "request_parameters": {}},  # 明确全部运行元字段。
    "diagnostics": [] if status == "成功出图" else ["合成失败诊断"],  # 失败至少有一条原因。
  })  # 结束合成运行字段。
  if status != "成功出图":  # 失败不得出现成功图。
    return row, record  # 覆盖分母仍来自三项金标准。
  graph = _graph_with_relations((GraphRelation("T1", "T2", "hard", "任务二", "合成依赖"),))  # 准备一条待人工裁定的实线。
  mermaid_text = render_mermaid(graph)  # 用项目原有生成器产生源码。
  record.update({  # 完整保留图快照、人工裁定及合成渲染记录。
    "graph": _snapshot(graph),  # 成功图不从 Mermaid 文本恢复。
    "mermaid_text": mermaid_text,  # 对应当次合成图。
    "task_alignment": [{"task_index": index, "gold_id": index + 1, "reason": "合成匹配"} for index in range(3)],  # 三个输出节点一对一匹配。
    "hard_edge_verdicts": [{"relation_index": 0, "verdict": "无依据", "reason": "合成错边"}],  # 人工测试裁定一条无依据实线。
    "render_check": _synthetic_render_check(mermaid_text, "失败"),  # 测试记录不能被当成真正渲染。
  })  # 结束成功图字段。
  return row, record  # 返回固定清单行与对应合成记录。


def test_full_batch_sums_success_failure_and_unrun_without_dropping_cases(tmp_path: Path) -> None:  # 一次报告保留成功、失败和未运行三类结果。
  rows, records = zip(*(_complete_case(tmp_path, case_id, status) for case_id, status in (("first", "成功出图"), ("second", "明确冲突停止"), ("third", "未运行"))))  # 构造三条独立的临时文件引用。
  document = _local_inventory_document(tmp_path, rows)  # 固定顺序与记录一致的三条清单。
  report = evaluate_records(document, tmp_path, reversed(records), "synthetic-1")  # 输入倒序也应按清单输出。
  assert [item["case_id"] for item in report["cases"]] == ["first", "second", "third"]  # 结果不受 JSON 排列顺序影响。
  assert report["statuses"] == {"未运行": 1, "成功出图": 1, "明确冲突停止": 1, "其他失败": 0}  # 不隐藏冲突或未运行。
  assert report["metrics"]["coverage"] == {"numerator": 3, "denominator": 6, "rate": 0.5}  # 已运行失败仍贡献三个未覆盖任务。
  assert report["metrics"]["structural"] == {"numerator": 1, "denominator": 1, "rate": 1.0}  # 结构分母只含成功图。
  assert report["metrics"]["unsupported_hard"] == {"numerator": 1, "denominator": 1, "rate": 1.0}  # 记录实际输出的无依据实线。
  assert report["metrics"]["renderable"] == {"numerator": 0, "denominator": 1, "rate": 0.0}  # 渲染失败仍进入分母。
  assert report["provenance_verified"] is False and report["acceptance_ready"] is False  # 合成数据不能证明模型质量。
  assert report["cases"][1]["diagnostics"] == ["合成失败诊断"]  # 原始失败说明仍可复查。


def test_full_batch_zero_success_keeps_nullable_rates(tmp_path: Path) -> None:  # 没有成功图不能把结构或渲染率写成 100%。
  row, record = _complete_case(tmp_path, "first", "其他失败")  # 准备只有失败结果的批次。
  report = evaluate_records(_local_inventory_document(tmp_path, (row,)), tmp_path, (record,), "synthetic-1")  # 独立计算四项。
  assert report["metrics"]["coverage"] == {"numerator": 0, "denominator": 3, "rate": 0.0}  # 失败的任务全未覆盖。
  for name in ("structural", "unsupported_hard", "renderable"):  # 这三项都没有分母。
    assert report["metrics"][name] == {"numerator": 0, "denominator": 0, "rate": None}  # 零分母明确标为不适用。


@pytest.mark.parametrize(  # 分别破坏金标准、裁定、运行身份、渲染和源码。
  ("field", "value", "message"),  # 指定错误字段与提示。
  [  # 以下任何一种缺口都不能发布完整四项报告。
    ("gold_tasks", [{"id": 1, "title": "虚构任务"}], "gold_tasks"),  # JSON 不能改写人工标注的金标准。
    ("task_alignment", [], "任务对齐"),  # 漏填人工节点匹配。
    ("hard_edge_verdicts", [], "实线裁定"),  # 漏填实际输出的实线判定。
    ("render_check", None, "Mermaid"),  # 未渲染不能发布可渲染率。
    ("mermaid_text", "flowchart LR\n", "不一致"),  # 错配源码不能冒充同一次图输出。
    ("source", "本轮真实调用", "来源"),  # 合成报告不能混入自称真实的记录。
    ("run_id", "other", "run_id"),  # 不得跨批次混算。
  ],  # 结束错误字段列表。
)  # 结束参数化设置。
def test_full_batch_rejects_incomplete_or_mixed_record(tmp_path: Path, field: str, value: object, message: str) -> None:  # 对错误输入不产生部分结果。
  row, record = _complete_case(tmp_path, "first")  # 准备一份完整的临时合成记录。
  record[field] = value  # 每次只替换一个字段。
  with pytest.raises(ValueError, match=message):  # 指出不完整的原因。
    evaluate_records(_local_inventory_document(tmp_path, (row,)), tmp_path, (record,), "synthetic-1")  # 不能悄悄降低分母。


def test_graph_snapshot_keeps_invalid_endpoint_and_duplicate_edges() -> None:  # JSON 解码不修复实际成功图的问题。
  graph = _graph_with_relations((GraphRelation("T1", "T4", "hard", "错误端点", "合成"), GraphRelation("T1", "T4", "hard", "错误端点", "合成")))  # 成功输出可能存在结构错误和重复边。
  decoded = decode_graph_snapshot(_snapshot(graph))  # 解码仍保留原始关系。
  assert decoded == graph and not is_graph_structurally_valid(decoded)  # 结构无效必须留给后续分母统计。
  assert count_unsupported_hard_edges(decoded, {0: "无依据", 1: "无依据"}) == (2, 2)  # 两条实线不能因重复而被消掉。


def test_local_renderer_checks_actual_svg_in_temporary_directory(monkeypatch: pytest.MonkeyPatch) -> None:  # 只模拟子进程协议，不声称真的运行了 mmdc。
  def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:  # 模拟本地渲染器的两个命令。
    if "--version" in argv:  # 先返回明确的测试版本。
      return subprocess.CompletedProcess(argv, 0, stdout="test-1\n", stderr="")  # 仅是测试桩。
    output = Path(argv[argv.index("-o") + 1])  # 取得调用者传入的临时 SVG 位置。
    assert Path(argv[argv.index("-i") + 1]).read_text(encoding="utf-8") == 'flowchart LR\n  T1["任务"]\n'  # 确实以当次源码为输入。
    output.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")  # 模拟 CLI 实际产物。
    return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")  # 返回成功状态。
  monkeypatch.setattr("plan2graph.evaluation.subprocess.run", fake_run)  # 不执行真实进程或联网。
  source = 'flowchart LR\n  T1["任务"]\n'  # 准备合成 Mermaid 文本。
  check = render_with_local_mmdc(source, "test-mmdc")  # 通过临时目录检验版本和 SVG。
  assert check == {"status": "成功", "renderer": "test-mmdc", "renderer_version": "test-1", "source_sha256": sha256(source.encode("utf-8")).hexdigest(), "failure_reason": None}  # 成功绑定源码指纹。


def test_local_renderer_rejects_non_svg_or_missing_executable(monkeypatch: pytest.MonkeyPatch) -> None:  # 退出零但未产出 SVG 不得记成功。
  def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:  # 模拟无产物的命令。
    return subprocess.CompletedProcess(argv, 0, stdout="test-1\n" if "--version" in argv else "", stderr="")  # 渲染时故意不写 SVG。
  monkeypatch.setattr("plan2graph.evaluation.subprocess.run", fake_run)  # 避免依赖本机命令。
  assert render_with_local_mmdc("flowchart LR\n", "test-mmdc")["status"] == "失败"  # 无 SVG 不能通过。
  def missing_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:  # 模拟版本进程无法启动。
    raise FileNotFoundError("test-mmdc")  # 表示当前环境没有渲染器。
  monkeypatch.setattr("plan2graph.evaluation.subprocess.run", missing_run)  # 再次替换为缺失可执行文件。
  with pytest.raises(ValueError, match="渲染器不可用"):  # 缺失时不输出伪成功。
    render_with_local_mmdc("flowchart LR\n", "test-mmdc")  # 本地环境须明确可用。


def test_file_entry_replaces_forged_render_record_with_this_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # JSON 自报渲染成功不能直接进入报告。
  row, record = _complete_case(tmp_path, "first")  # 准备完整的测试记录与原文件。
  document = _local_inventory_document(tmp_path, (row,))  # 固定临时清单。
  record["render_check"] = _synthetic_render_check(record["mermaid_text"], "成功")  # 输入文件谎称已渲染成功。
  record_file = tmp_path / "records.json"  # 将记录放到临时 JSON。
  record_file.write_text(json.dumps({"records": [record]}, ensure_ascii=False), encoding="utf-8")  # 实际测试磁盘读取。
  def fake_render(source: str, executable: str) -> dict[str, object]:  # 模拟本次 CLI 渲染失败。
    return _synthetic_render_check(source, "失败")  # 新结果应覆盖输入中原有的伪成功。
  monkeypatch.setattr("plan2graph.evaluation.render_with_local_mmdc", fake_render)  # 不触发任何真实命令。
  report = evaluate_file(document, tmp_path, record_file, "synthetic-1", "test-mmdc")  # 走完整的读取与汇总路径。
  assert report["metrics"]["renderable"] == {"numerator": 0, "denominator": 1, "rate": 0.0}  # 仅本次结果计入。
  assert json.loads(record_file.read_text(encoding="utf-8"))["records"][0]["render_check"]["status"] == "成功"  # 输入文件保持未改动。


def _current_twenty_unrun_records() -> tuple[Path, Path, list[dict[str, object]]]:  # 用当前本地标注构造不接触模型的二十条未运行记录。
  server_root = Path(__file__).resolve().parents[1]  # 使用真实的本地二十份标注。
  document = server_root / "doc" / "阶段5.2评估指标口径.md"  # 读取已固定的评估清单。
  entries = load_fixed_case_inventory(document)  # 不从目录自动扩大样例范围。
  records = []  # 仅在内存中构造未运行记录，不生成评估文件。
  for entry in entries:  # 每份标注与原计划都要通过当前指纹核对。
    annotation = server_root / entry["annotation_path"]  # 找到该样例的标注。
    plan = server_root / entry["plan_path"]  # 找到标注所指的本地计划副本。
    records.append({  # 这些字段都不声称模型运行成功。
      "case_id": entry["case_id"],  # 用文档事先固定的身份。
      "annotation_path": entry["annotation_path"],  # 保留当前标注路径。
      "annotation_sha256": sha256(annotation.read_bytes()).hexdigest(),  # 当前本地标注的字节指纹。
      "plan_path": entry["plan_path"],  # 保留当前原计划路径。
      "plan_sha256": sha256(plan.read_bytes()).hexdigest(),  # 当前计划副本的字节指纹。
      "gold_tasks": [{"id": number, "title": title} for number, title in _annotation_gold_tasks(annotation)],  # 逐项核对现有关键任务格式。
      "status": "未运行",  # 不虚构模型输出。
      "source": "未运行（无输出来源）",  # 未运行没有结果来源。
      "reason": "传输许可未确认",  # 明确当前无法运行模型的原因。
    })  # 结束一条内存记录。
  return server_root, document, records  # 返回可由内存入口或命令入口复用的样例。


def test_full_batch_accepts_current_twenty_as_unrun_without_quality_claim() -> None:  # 当前本地样例可以保留未运行状态，但不能形成质量结论。
  server_root, document, records = _current_twenty_unrun_records()  # 只读准备固定清单与二十份原文件。
  report = evaluate_records(document, server_root, records, "pending-1")  # 全清单只读验证但不计本轮质量。
  assert report["inventory_count"] == 20 and report["statuses"]["未运行"] == 20  # 所有本地标注均保留在结果里。
  assert all(metric["rate"] is None for metric in report["metrics"].values())  # 没有任何成功或已运行样例时全部指标不适用。
  assert report["acceptance_ready"] is False  # 不能将清单核对写成 5.2 质量验收。


def test_cli_twenty_unrun_records_produces_only_null_quality_rates(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:  # 从本地 JSON 文件走完整的命令入口。
  _, _, records = _current_twenty_unrun_records()  # 读取当前已确认本地文件，仍不发送任何内容。
  record_file = tmp_path / "records.json"  # 在 pytest 临时目录准备批次。
  record_file.write_text(json.dumps({"records": records}, ensure_ascii=False), encoding="utf-8")  # 模拟将来由采集端产生的 JSON。
  result = main([str(record_file), "--run-id", "pending-1", "--renderer", "missing-mmdc"])  # 无成功图时不应运行渲染器。
  output = capsys.readouterr()  # 读取本次命令的标准输出与错误。
  report = json.loads(output.out)  # 检查真正写出的 JSON 报告。
  assert result == 0 and not output.err  # 完整未运行记录可以形成状态报告。
  assert report["inventory_count"] == 20 and report["statuses"]["未运行"] == 20  # 固定清单无漏项。
  assert all(metric["rate"] is None for metric in report["metrics"].values())  # 不能发布未执行样例的质量率。


def test_invalid_success_graph_remains_in_structure_and_render_denominators(tmp_path: Path) -> None:  # 无法重建源码的错误 ID 不应被删除。
  row, record = _complete_case(tmp_path, "first")  # 准备一个已有完整裁定的成功记录。
  record["graph"]["tasks"][0]["id"] = "X"  # 令第一个任务 ID 不符合现有 Mermaid 生成器的编号格式。
  record["mermaid_text"] = 'flowchart LR\n  X["任务一"]\n'  # 保留捕获到的非空错误源码。
  record["render_check"] = _synthetic_render_check(record["mermaid_text"], "失败")  # 失败仍占渲染分母。
  report = evaluate_records(_local_inventory_document(tmp_path, (row,)), tmp_path, (record,), "synthetic-1")  # 计算错误成功图。
  assert report["metrics"]["structural"] == {"numerator": 0, "denominator": 1, "rate": 0.0}  # 不把坏图从成功集合剔除。
  assert report["metrics"]["renderable"]["denominator"] == 1  # 有源码但渲染失败同样计入分母。
  assert report["cases"][0]["output_consistent"] is False  # 报告指出快照与源码无法重建吻合。


def test_current_mode_only_checks_source_declaration_not_provenance(tmp_path: Path) -> None:  # 来源字段声明不能自动证明真实模型请求发生过。
  row, record = _complete_case(tmp_path, "first")  # 准备仍为本地合成数据的记录。
  record["source"] = "本轮真实调用"  # 仅更改自报来源，不执行模型调用。
  report = evaluate_records(_local_inventory_document(tmp_path, (row,)), tmp_path, (record,), "synthetic-1", mode="current")  # 身份字段自洽时可做计算。
  assert report["provenance_verified"] is False and report["acceptance_ready"] is False  # 不将自报身份当成模型验收证据。


def test_cli_reports_error_when_record_file_is_missing(capsys: pytest.CaptureFixture[str]) -> None:  # IDE 命令缺输入时返回非零状态。
  result = main(["/this/path/does/not/exist.json", "--run-id", "synthetic-1", "--renderer", "mmdc"])  # 不运行渲染或模型请求。
  captured = capsys.readouterr()  # 检查终端的错误出口。
  assert result == 2 and not captured.out and "记录文件缺失" in captured.err  # 不输出部分报告。
