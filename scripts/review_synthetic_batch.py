"""核验五份合成双路记录并留存本机 Mermaid 官方渲染证据。"""

import argparse  # 显式传入本轮五份原始记录及渲染器。
import json  # 按结构解析原始请求和回答。
from datetime import datetime, timezone  # 为核验报告记录实际时间。
from pathlib import Path  # 定位原文、提示词和本地私有报告。
from uuid import uuid4  # 避免覆盖先前核验结果。

from compare_synthetic_s01 import INPUT, INPUT_SHA256, PROMPT, SERVER, load_direct_prompt, save_record, sha256, select_case  # 复用采集时锁定的路径与提示词。
from plan2graph.evaluation import decode_graph_snapshot, render_with_local_mmdc  # 复用结构快照和官方渲染核验。
from plan2graph.extract import build_extraction_messages  # 对照正式路径的用户输入包装。
from plan2graph.mermaid import render_mermaid  # 检查采集图与 Mermaid 源码一致。


def inspect_record(path: Path) -> tuple[str, dict]:  # 在启动渲染器之前核对当前合成原文及两路请求。
    record = json.loads(path.read_text(encoding="utf-8"))  # 只读取指定的本地原始记录。
    case = record.get("case")  # 原始记录必须有受限的样例编号。
    if case == "S01":  # 默认入口沿用旧脚本的 S01。
        input_path, expected = INPUT, INPUT_SHA256  # 读取最初锁定的原文字节指纹。
    elif case in ("S02", "S03", "S04", "S05"):  # 其他编号也只能从固定映射选取。
        _, input_path, expected, _ = select_case(["collector", "--case", case])  # 禁止自行声明新原文路径。
    else:  # 未知编号不能被纳入本次五例报告。
        raise ValueError("合成记录编号不属于 S01–S05")  # 在任何渲染进程前终止。
    data = input_path.read_bytes()  # 读取与采集时同一路径的原文字节。
    if sha256(data) != expected or record.get("input_path") != str(input_path) or record.get("input_sha256") != expected:  # 不能串用旧版或其他原文。
        raise ValueError(f"{case} 原文位置或指纹不一致")  # 不让错误来源混进报告。
    if record.get("source") != "assistant_synthetic_not_stage_5_3_acceptance":  # 本脚本只用于合成演练。
        raise ValueError(f"{case} 来源字段无效")  # 不从模型记录推断真实 Agent 来源。
    if record.get("direct_prompt_version") != "direct-mermaid-v1" or record.get("direct_prompt_document_sha256") != sha256(PROMPT.read_bytes()):  # 固定直接侧提示词。
        raise ValueError(f"{case} 直接提示词版本或指纹不一致")  # 避免无意比较不同提示词。
    arms = record.get("arms", {})  # 两路原始请求都必须存在。
    if set(arms) != {"plan2graph", "direct_mermaid"}:  # 不允许缺侧或补造第三侧。
        raise ValueError(f"{case} 双路记录不完整")  # 不能以单侧运行作为比较。
    requests = []  # 收集每侧首次请求供输入和参数核对。
    direct_prompt, _ = load_direct_prompt()  # 恢复采集时冻结的直接侧 system 内容。
    for name, arm in arms.items():  # 同时检查 Plan2Graph 与直接侧。
        attempts = arm.get("attempts", [])  # 失败也须有实际请求记录。
        if not attempts or arm.get("status") not in ("collected", "failed"):  # 未运行不算本轮完成。
            raise ValueError(f"{case} {name} 未完成请求采集")  # 阻断不完整现场。
        first = attempts[0].get("request", {})  # 两侧必须发送同一份 user 原文。
        requests.append(first)  # 保留显式传入的模型和输出上限。
        expected_system = build_extraction_messages(data.decode("utf-8"))[0] if name == "plan2graph" else {"role": "system", "content": direct_prompt}  # 两侧各用预先冻结的规则。
        for attempt in attempts:  # 每次修复或连接重试也须绑定相同原文。
            request = attempt.get("request", {})  # 读取每次真实请求的原样消息。
            if request.get("model") != record.get("model_alias") or request.get("max_tokens") != record.get("max_tokens"):  # 检查运行时参数。
                raise ValueError(f"{case} {name} 请求参数不一致")  # 不通过记录自述代替请求内容。
            messages = request.get("messages", [])  # 用户消息放在索引一。
            if len(messages) < 2 or messages[0] != expected_system or messages[1] != build_extraction_messages(data.decode("utf-8"))[1]:  # 同时比对 system 与 JSON 包装的原文。
                raise ValueError(f"{case} {name} 请求原文不一致")  # 任一侧改写都使比较无效。
    if requests[0]["messages"][1] != requests[1]["messages"][1]:  # 两侧必须逐字共享相同 user 消息。
        raise ValueError(f"{case} 两侧输入不一致")  # 双侧对比不能使用不同原文。
    for name, arm in arms.items():  # 检查采集状态与当次输出之间没有矛盾。
        if arm["status"] == "collected":  # 仅对成功采集的 Mermaid 核对来源。
            last = arm["attempts"][-1].get("response", {})  # 最后一次响应必须正常结束。
            if last.get("choices", [{}])[0].get("finish_reason") != "stop":  # 截断不算成功。
                raise ValueError(f"{case} {name} 成功状态与响应结束原因矛盾")  # 保留失败案例。
            if not isinstance(arm.get("mermaid"), str) or not arm["mermaid"].strip():  # 空文本不是图。
                raise ValueError(f"{case} {name} 缺少原始 Mermaid")  # 不渲染虚构的输出。
            if name == "plan2graph":  # 正式路径应可从保留的图快照重建源码。
                if render_mermaid(decode_graph_snapshot(arm.get("graph"))) != arm["mermaid"]:  # 防止图与文本串样例。
                    raise ValueError(f"{case} 任务图与 Mermaid 不一致")  # 不继续渲染错误配对。
            elif arm["mermaid"] != arm["attempts"][-1].get("response", {}).get("choices", [{}])[0].get("message", {}).get("content"):  # 直接侧须保留原样回答。
                raise ValueError(f"{case} 直接侧 Mermaid 不是原始回答")  # 不隐藏人工修改。
        elif "mermaid" in arm and name == "plan2graph":  # 抽取失败不得保留假成功图。
            raise ValueError(f"{case} 失败抽取含有 Mermaid")  # 失败不参与成功图指标。
    return case, record  # 返回已核对身份的只读记录。


def review(paths: list[Path], renderer: str) -> dict:  # 对完整五例生成只含证据摘要的本机报告。
    if len(paths) != 5:  # 必须保留全部失败案例和成功样例。
        raise ValueError("必须显式提供 S01–S05 五份原始记录")  # 禁止只挑成功样例。
    checked = [inspect_record(path) for path in paths]  # 先核对所有文件才启动渲染。
    if {case for case, _ in checked} != {"S01", "S02", "S03", "S04", "S05"}:  # 不允许重复编号替代失败案例。
        raise ValueError("五份记录编号不完整或重复")  # 对比必须覆盖固定样例。
    conditions = {(record.get("model_alias"), record.get("max_tokens"), record.get("timeout_seconds"), record.get("direct_prompt_document_sha256")) for _, record in checked}  # 锁定同批次的模型别名、上限、超时和基线提示词。
    if len(conditions) != 1:  # 运行条件不相同就不能汇成固定条件的一组对比。
        raise ValueError("五份记录的模型或请求条件不一致")  # 仍保留原始记录供单独审查。
    paths_by_case = {case: path.resolve() for path, (case, _) in zip(paths, checked)}  # 绑定每例原始文件的准确位置。
    cases = []  # 为每例保存渲染与请求状态。
    for case, record in sorted(checked):  # 以固定样例顺序展示。
        arms = {}  # 保留每个方法的失败状态和渲染结果。
        for name, arm in record["arms"].items():  # 分别核验两侧未经修改的输出。
            item = {"status": arm["status"], "request_count": len(arm["attempts"]), "failure": arm.get("failure"), "attempts": [{"finished_at_utc": attempt.get("finished_at_utc"), "finish_reason": attempt.get("response", {}).get("choices", [{}])[0].get("finish_reason"), "response_model": attempt.get("response", {}).get("model"), "completion_tokens": attempt.get("response", {}).get("usage", {}).get("completion_tokens"), "failure": attempt.get("failure")} for attempt in arm["attempts"]]}  # 汇总每次实际请求而不复制原文。
            item["render_check"] = render_with_local_mmdc(arm["mermaid"], renderer) if arm["status"] == "collected" else None  # 无图只能标为未渲染。
            arms[name] = item  # 留下该侧可复查的状态。
        cases.append({"case": case, "input_sha256": record["input_sha256"], "record_path": str(paths_by_case[case]), "model_alias": record["model_alias"], "max_tokens": record["max_tokens"], "timeout_seconds": record["timeout_seconds"], "direct_prompt_document_sha256": record["direct_prompt_document_sha256"], "arms": arms})  # 绑定原始记录和固定参数。
    return {"scope": "assistant_synthetic_not_stage_5_3_acceptance", "real_agent_plan_count": 0, "renderer": renderer, "checked_at_utc": datetime.now(timezone.utc).isoformat(), "cases": cases}  # 不声明真实质量验收。


def main() -> int:  # 从显式原始文件生成一次不可覆盖的合成演练核验报告。
    parser = argparse.ArgumentParser(description="核验五份合成双路原始记录并实际调用本机 mmdc。")  # 命令不会调用 DeepSeek。
    parser.add_argument("records", type=Path, nargs=5, help="依次指定五份本地 JSON 原始记录")  # 不靠目录最新文件猜批次。
    parser.add_argument("--renderer", required=True, help="官方 mmdc 可执行文件")  # 指向本机安装的程序。
    args = parser.parse_args()  # 获得明确的五份记录及渲染器。
    report = review(args.records, args.renderer)  # 核对请求并实际渲染每张已有图。
    directory = SERVER / ".local/phase5_3_review"  # 原始记录路径和诊断不写入公开仓库。
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)  # 只对本机用户开放目录。
    output = directory / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex}.json"  # 每次核验都保留独立结果。
    save_record(output, report)  # 使用现有原子写入保持证据完整。
    print(f"核验报告：{output}")  # 只输出结果位置和逐例状态。
    for case in report["cases"]:  # 不在终端打印计划原文或密钥。
        print(case["case"], {name: (arm["status"], arm["render_check"]["status"] if arm["render_check"] else "无图") for name, arm in case["arms"].items()})  # 摘要显示渲染与失败差异。
    return 0  # 零退出仅代表五例核验完成，不代表质量验收。


if __name__ == "__main__":  # 显式运行脚本时才启动官方渲染。
    raise SystemExit(main())  # 返回命令的核验状态。
