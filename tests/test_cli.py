"""阶段 0.4 的离线测试：只检查命令帮助和功能边界。"""

import pytest  # 导入自动测试工具。

from plan2graph.cli import main  # 导入命令入口函数。


"""
检查 --help 是否正常工作。
输入 --help 后，程序应正常退出，并显示帮助信息。
帮助信息应包含命令用法。
帮助信息不应输出错误。
"""
def test_help_exits_successfully(capsys: pytest.CaptureFixture[str]) -> None:  # 检查 --help 是否正常工作。
  with pytest.raises(SystemExit) as result:  # 捕获显示帮助后的退出状态。
    main(["--help"])  # 模拟用户输入 --help。
  output = capsys.readouterr()  # 读取命令显示的文字。
  assert result.value.code == 0  # 状态 0 表示正常退出。
  assert "usage: plan2graph" in output.out  # 帮助文字应包含命令用法。
  assert output.err == ""  # 正常帮助不应输出错误。
    

"""
检查不传参数的情况。
不传参数时，程序应正常退出，并显示帮助信息。
帮助信息应包含命令用法。
帮助信息不应输出错误。
"""
def test_no_arguments_shows_help(capsys: pytest.CaptureFixture[str]) -> None:  # 检查不传参数的情况。
  assert main([]) == 0  # 不传参数应正常结束。
  assert "usage: plan2graph" in capsys.readouterr().out  # 应显示帮助，而不是生成图。

"""
检查未来功能目前不可用。
输入 generate 命令时，程序应正常退出，并显示错误信息。
错误信息应指出该功能尚未实现。
"""
def test_generate_is_not_available(capsys: pytest.CaptureFixture[str]) -> None:  # 检查未来功能目前不可用。
  with pytest.raises(SystemExit) as result:  # 捕获不支持参数时的退出状态。
      main(["generate", "plan.md"])  # 模拟尝试使用生成命令。
  output = capsys.readouterr()  # 读取错误提示。
  assert result.value.code == 2  # 状态 2 表示参数错误。
  assert "unrecognized arguments: generate plan.md" in output.err  # 错误应明确指出不支持的参数。