"""当前阶段只提供命令帮助，不生成任务图。"""

import argparse  # 使用 Python 自带的命令行参数解析工具。

def main(argv: list[str] | None = None) -> int:  # 定义 plan2graph 命令调用的入口。
  parser = argparse.ArgumentParser(prog="plan2graph", description="当前仅提供命令帮助；任务图生成功能尚未实现。")  # 创建帮助信息
  parser.parse_args(argv)  # 识别 --help，并拒绝尚未实现的 generate 等参数。
  parser.print_help()  # 没有传参数时也显示帮助。
  return 0  # 用退出状态 0 表示正常结束。