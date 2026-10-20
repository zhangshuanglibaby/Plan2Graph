"""采集 S01–S05 合成计划的两路模型原始结果；运行才会发送所选原文。"""

import hashlib  # 为实际读取的输入与固定提示词计算指纹。
import json  # 保存请求、响应及运行元数据。
import os  # 安全替换本地结果文件。
import sys  # 从项目的 src 目录导入现有实现。
import tempfile  # 以私有临时文件原子保存采集结果。
from dataclasses import asdict  # 保存已校验的任务图。
from datetime import datetime, timezone  # 记录每次请求的 UTC 时间。
from pathlib import Path  # 固定输入、提示词和结果的位置。
from types import SimpleNamespace  # 为现有抽取函数提供记录请求的客户端代理。
from uuid import uuid4  # 为每次运行生成互不覆盖的结果路径。

from openai import APIConnectionError  # 与现有抽取路径保持相同的连接重试范围。

SERVER = Path(__file__).resolve().parents[1]  # 本脚本只定位所在的 server 工程。
sys.path.insert(0, str(SERVER / "src"))  # 不依赖当前工作目录或可编辑安装状态。

from plan2graph import extract  # 复用现有的模型配置、抽取和校验逻辑。
from plan2graph.cli import get_max_input_chars  # 沿用命令行的输入长度限制。
from plan2graph.mermaid import render_mermaid  # 沿用正式的 Mermaid 生成逻辑。

INPUT = SERVER / "doc/阶段5.3-合成演练输入/01-客户名单导入-合成计划.md"  # 无参数时允许发送的 S01 合成输入。
INPUT_SHA256 = "b486ad3b1a05c490f349ca5cb68f08bd3e3f162fcdf84afb60e2f8c125f9e838"  # 锁定已获授权的 S01 字节。
ADDITIONAL_CASES = {  # 仅增加已核对指纹、由助手编写的四份合成计划。
    "S02": ("02-预约改期-合成计划.md", "1dde77d87f3b2b88b0775f9a1e5f1dc58f987ad688f37f8425145d72ff70083b"),  # 固定 S02 的文件和原始字节。
    "S03": ("03-库存预警-合成计划.md", "f167d70f832f36b811c0c9b9b9a06ac9106c380903b27b20810ee4d75990374e"),  # 固定 S03 的文件和原始字节。
    "S04": ("04-工单附件-合成计划.md", "300ceb9d89a2cf8da62efd4c419266747ecaa15d28a173b628b6ab9fa777a709"),  # 固定 S04 的文件和原始字节。
    "S05": ("05-功能开关发布-合成计划.md", "b6659cd4a97e910d1b9d3fe1c6028aae029f93ec2248bdd5f8db4648a569ea72"),  # 固定 S05 的文件和原始字节。
}  # 未列明的原文不能通过此脚本传输。
PROMPT = SERVER / "doc/阶段5.3-合成演练-直接生成Mermaid提示词.md"  # 读取先前冻结的提示词版本。
RESULTS = SERVER / ".local/phase5_3_s01"  # 本地原始数据不会被 Git 跟踪。


def utc_now() -> str:  # 统一记录带时区的请求时间。
    return datetime.now(timezone.utc).isoformat()  # 使用 UTC ISO 8601 格式。


def sha256(data: bytes) -> str:  # 计算原始字节的内容指纹。
    return hashlib.sha256(data).hexdigest()  # 不对文本做任何规范化。


def load_direct_prompt() -> tuple[str, str]:  # 从固定文档中取出唯一的 system 围栏。
    data = PROMPT.read_bytes()  # 按原始字节记录提示词文件指纹。
    document = data.decode("utf-8")  # 使用文档约定的 UTF-8 编码。
    marker = "```text\n"  # 定位提示词正文的围栏开头。
    if document.count(marker) != 1:  # 拒绝缺失或多份提示词，防止取错版本。
        raise ValueError("直接生成提示词的 text 围栏数量不是 1")  # 不发出任何请求。
    body = document.split(marker, 1)[1]  # 取得唯一围栏后面的内容。
    if "\n```" not in body:  # 围栏没有正常结束时拒绝运行。
        raise ValueError("直接生成提示词围栏未结束")  # 不把后续说明发给模型。
    system_prompt = body.split("\n```", 1)[0]  # 排除围栏结束符及文档其他说明。
    if not system_prompt.strip():  # 空提示词不允许进入对比。
        raise ValueError("直接生成提示词为空")  # 避免失去固定比较条件。
    return system_prompt, sha256(data)  # 返回实际提示词和文档原始指纹。


def save_record(path: Path, record: dict) -> None:  # 每次请求结束就保存现场。
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".s01-", suffix=".tmp", delete=False) as file:  # 临时文件默认仅当前用户可读写。
        temporary = Path(file.name)  # 保留临时文件路径以便原子替换。
        try:  # 确保写入失败时也能移除残留文件。
            json.dump(record, file, ensure_ascii=False, indent=2)  # 保存全部请求、原始响应与失败信息。
            file.write("\n")  # 让结果文件以换行结尾。
        except BaseException:  # 对写入中断也清理不完整的临时文件。
            temporary.unlink(missing_ok=True)  # 不留下残缺结果。
            raise  # 保留原始写入错误。
    os.replace(temporary, path)  # 只有完整写入后才替换结果。


def error_info(error: Exception) -> dict[str, str]:  # 记录失败而不输出密钥。
    secret = os.environ.get("DEEPSEEK_API_KEY", "")  # 读取仅用于脱敏，不写入结果。
    message = str(error)  # 保留错误描述用于区分失败案例。
    if secret:  # 密钥存在时避免意外出现在 SDK 错误消息里。
        message = message.replace(secret, "[REDACTED]")  # 只在本地记录脱敏后的文本。
    return {"type": type(error).__name__, "message": message}  # 返回失败类别和描述。


class RecordingCompletions:  # 代理单次请求并保留所有重试或修复尝试。
    def __init__(self, real_completions, record: dict, arm: str, path: Path) -> None:  # 绑定真实客户端和当前方法。
        self.real_completions = real_completions  # 请求仍走原有 OpenAI SDK 客户端。
        self.record = record  # 两侧共享同一运行记录。
        self.arm = arm  # 区分 Plan2Graph 与直接生成。
        self.path = path  # 逐次将采集结果持久化。

    def create(self, **parameters):  # 匹配现有抽取函数使用的 create 调用。
        attempt = {"started_at_utc": utc_now(), "request": parameters}  # 原样保存模型别名、完整消息及显式参数。
        self.record["arms"][self.arm]["attempts"].append(attempt)  # 先登记当前请求，失败也不遗漏。
        save_record(self.path, self.record)  # 发出请求前保存输入和参数。
        try:  # 单次调用的异常由各自方法决定是否重试。
            response = self.real_completions.create(**parameters)  # 只在运行脚本时请求 DeepSeek。
        except Exception as error:  # 每次失败都独立记下，不只保留最终失败。
            attempt["failure"] = error_info(error)  # 不记录密钥或请求头。
            raise  # 保持正式抽取路径的重试与修复行为。
        else:  # 收到回答时保存 SDK 返回的完整原始响应。
            attempt["response"] = response.model_dump(mode="json")  # 包含响应模型标识和原始正文。
            return response  # 将原对象交给现有抽取逻辑。
        finally:  # 无论成功或失败都立即保存请求现场。
            attempt["finished_at_utc"] = utc_now()  # 标明本次请求结束时间。
            save_record(self.path, self.record)  # 避免下一侧失败时丢失已得到的响应。


def run_plan2graph(text: str, completions: RecordingCompletions, record: dict) -> None:  # 运行正式任务图路径。
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))  # 只代理 create，其他逻辑不改。
    arm = record["arms"]["plan2graph"]  # 取得本侧记录。
    try:  # 单侧失败不阻断另一侧的采集。
        graph = extract.extract_plan_graph(text, client)  # 包含原有的重试、结构修复和图校验。
        arm["graph"] = asdict(graph)  # 保存任务、证据、保留与跳过的关系。
        arm["mermaid"] = render_mermaid(graph)  # 保存未人工修改的 Mermaid。
        arm["status"] = "collected"  # 仅表示采集成功，不表示质量或官方可渲染。
    except Exception as error:  # 包含 SDK、结构校验及渲染阶段的失败。
        arm["failure"] = error_info(error)  # 保留最终失败，不冒充成功图。
        arm["status"] = "failed"  # 明确此侧没有可用的最终输出。


def run_direct(text: str, system_prompt: str, completions: RecordingCompletions, record: dict) -> None:  # 运行直接生成基线。
    arm = record["arms"]["direct_mermaid"]  # 取得本侧记录。
    parameters = {  # 与正式路径使用相同输入包装、别名和输出上限。
        "model": record["model_alias"],  # 两侧记录同一运行时模型别名。
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": json.dumps({"plan_text": text}, ensure_ascii=False)}],  # 两侧 user 内容相同。
        "max_tokens": record["max_tokens"],  # 两侧显式输出上限一致。
    }  # 本侧不传 JSON 输出格式和温度。
    try:  # 基线只对连接错误重试一次，不做内容修复。
        for index in range(2):  # 首次尝试加至多一次连接重试。
            try:  # 尝试本次直接生成请求。
                response = completions.create(**parameters)  # 保存该次完整请求和响应。
                break  # 收到响应后不再重试。
            except APIConnectionError:  # 与正式路径使用相同的连接重试策略。
                if index == 1:  # 第二次连接失败后保留最终失败。
                    raise  # 不吞掉原始 SDK 失败。
        if not response.choices:  # 空选项没有可用于比较的 Mermaid。
            raise RuntimeError("DeepSeek 空响应：没有回答选项")  # 将失败单独记录。
        choice = response.choices[0]  # 使用与正式路径一致的第一个回答。
        if choice.message.content is not None:  # 哪怕结束状态异常也保留原始正文。
            arm["mermaid"] = choice.message.content  # 不去围栏或修改模型输出。
        if choice.finish_reason != "stop":  # 截断或其他异常结束不能当作成功。
            raise RuntimeError(f"DeepSeek 回答结束状态异常：{choice.finish_reason}")  # 保留具体状态。
        if not choice.message.content:  # 空正文无法构成 Mermaid 图。
            raise RuntimeError("DeepSeek 空响应：没有回答正文")  # 不虚报成功。
        arm["status"] = "collected"  # 仅表示原文采集成功，未做官方渲染。
    except Exception as error:  # 单侧请求或结果检查失败时保留失败案例。
        arm["failure"] = error_info(error)  # 保存原因供后续人工核对。
        arm["status"] = "failed"  # 不把失败结果算入成功样例。


def select_case(argv: list[str]) -> tuple[str, Path, str, Path]:  # 明确选取一个受指纹约束的合成样例。
    if len(argv) == 1:  # 保留旧脚本默认运行 S01 的行为。
        return "S01", INPUT, INPUT_SHA256, RESULTS  # 测试与此前采集路径保持有效。
    if len(argv) != 3 or argv[1] != "--case" or argv[2] not in ADDITIONAL_CASES:  # 禁止任意文件路径或未知编号。
        raise ValueError("仅支持 --case S02、S03、S04、S05；无参数时为 S01")  # 在读取原文和创建客户端前拒绝。
    case = argv[2]  # 此时编号属于固定白名单。
    filename, expected_hash = ADDITIONAL_CASES[case]  # 从静态映射取得文件名及指纹。
    return case, INPUT.parent / filename, expected_hash, SERVER / f".local/phase5_3_{case.lower()}"  # 各例独立保存原始现场。


def main() -> int:  # 一次仅执行一份合成计划的双路采集。
    case, input_path, expected_hash, results = select_case(sys.argv)  # 先核对参数对应固定输入。
    data = input_path.read_bytes()  # 只读取当前选择的合成文件。
    actual_hash = sha256(data)  # 对实际读取的字节核对指纹。
    if actual_hash != expected_hash:  # 文本发生变化就必须重新确认传输范围。
        raise ValueError(f"{case} 内容指纹已改变；停止模型调用")  # 不发送变更后的新版本。
    text = data.decode("utf-8")  # 不改写完整计划原文。
    if not text.strip() or len(text) > get_max_input_chars():  # 沿用正式 CLI 的空文本和长度边界。
        raise ValueError(f"{case} 为空或超出当前输入字符数上限")  # 请求前退出。
    system_prompt, prompt_hash = load_direct_prompt()  # 固定直接生成的 system 文本。
    max_tokens = extract.get_deepseek_max_tokens()  # 验证当前配置的输出上限。
    client = extract.create_deepseek_client()  # 读取本地配置但尚未发送请求。
    try:  # 保证模型运行结束后关闭网络客户端。
        model_alias = extract.get_deepseek_model()  # 把别名和已确认服务端版本分开记录。
        timeout_seconds = extract.get_deepseek_timeout_seconds()  # 记录两侧共用的显式客户端超时。
        results.mkdir(mode=0o700, parents=True, exist_ok=True)  # 将原始请求和响应保存在本地私有目录。
        output = results / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex}.json"  # 为每次运行建立独立记录。
        record = {  # 先写运行元信息，后按请求逐次补充。
            "case": case,  # 不把合成计划标为真实 Agent 计划。
            "source": "assistant_synthetic_not_stage_5_3_acceptance",  # 标明仅供流程演练。
            "input_path": str(input_path),  # 保存输入的绝对位置。
            "input_sha256": actual_hash,  # 保存实际读取字节的指纹。
            "direct_prompt_version": "direct-mermaid-v1",  # 保存冻结的提示词版本。
            "direct_prompt_document_sha256": prompt_hash,  # 保存提示词文档的内容指纹。
            "model_alias": model_alias,  # 不是已证实的服务端版本。
            "server_model_version": "unconfirmed",  # 不凭别名猜测服务端实现版本。
            "max_tokens": max_tokens,  # 两侧使用相同显式参数。
            "temperature": "not_supplied",  # 两侧均不显式传温度。
            "timeout_seconds": timeout_seconds,  # 两侧共用一个客户端。
            "sdk_max_retries": 0,  # 内部重试只来自两侧明确的连接重试策略。
            "endpoint": "https://api.deepseek.com",  # 客户端当前固定的服务地址。
            "created_at_utc": utc_now(),  # 记录运行开始时间。
            "arms": {"plan2graph": {"status": "not_started", "attempts": []}, "direct_mermaid": {"status": "not_started", "attempts": []}},  # 失败时仍保留两侧状态。
        }  # 不将密钥或 HTTP 请求头写入结果。
        save_record(output, record)  # 模型请求前先保存配置快照。
        real = client.chat.completions  # 两侧使用同一客户端和服务地址。
        plan_recorder = RecordingCompletions(real, record, "plan2graph", output)  # 记录正式路径的每次请求。
        direct_recorder = RecordingCompletions(real, record, "direct_mermaid", output)  # 记录直接生成的每次请求。
        run_plan2graph(text, plan_recorder, record)  # 首先采集现有实现的未修改输出。
        save_record(output, record)  # 及时保存正式路径的图或最终失败。
        run_direct(text, system_prompt, direct_recorder, record)  # 再用完全相同的 user 输入运行基线。
        save_record(output, record)  # 保存两侧最终状态和全部原始尝试。
        print(f"采集文件：{output}")  # 只打印路径，避免在终端泄漏原文。
        print(f"Plan2Graph：{record['arms']['plan2graph']['status']}；直接生成：{record['arms']['direct_mermaid']['status']}")  # 不宣称质量或渲染结果。
        return 0 if all(arm["status"] == "collected" for arm in record["arms"].values()) else 1  # 两侧都采到结果才返回成功。
    finally:  # 正常结束或失败都释放客户端资源。
        client.close()  # 不在此处发出额外模型请求。


if __name__ == "__main__":  # 只有显式运行脚本才进入模型调用流程。
    raise SystemExit(main())  # 以采集状态作为进程退出码。
