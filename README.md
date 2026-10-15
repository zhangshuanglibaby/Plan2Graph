# Plan2Graph：最小 Python 工程骨架

目前只能运行 `plan2graph --help`，还不能生成任务图，也不会调用 DeepSeek。

## 首次安装

在终端进入 `server` 目录后，依次运行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
```

安装依赖时可能需要网络；运行下面的测试不需要 DeepSeek 或密钥。

## 日常检查

每次打开新终端，先进入 `server` 目录并运行：

```bash
source .venv/bin/activate
plan2graph --help
python -m pytest -q
```

看到 `3 passed` 表示当前三个基础测试通过。用完可输入 `deactivate` 退出虚拟环境。

## 文件用途

- `pyproject.toml`：配置 Python 版本、安装方式和命令入口。
- `src/plan2graph/__init__.py`：标识 Python 包。
- `src/plan2graph/cli.py`：目前只提供帮助信息的命令入口。
- `tests/test_cli.py`：不联网的基础测试。
- `.gitignore`：避免将虚拟环境和缓存纳入 Git 跟踪。