"""
将任务标题转换为可放入 Mermaid 引号中的文字。
输入：
  - text: 任务标题
输出：
  - 转换后的文字
"""
def escape_mermaid_label(text: str) -> str:  # 将任务标题转换为可放入 Mermaid 引号中的文字。
  pieces: list[str] = []  # 逐个保存处理后的字符。
  for character in text:  # 依次检查标题中的每个字符。
    if character.isspace() and character != " ":  # 检查换行、制表符等非普通空格。
      pieces.append(" ")  # 用普通空格代替，避免拆开图语句。
    elif ord(character) < 32 or ord(character) == 127:  # 检查其他不可见控制字符。
      pieces.append(" ")  # 不让控制字符进入图语句。
    elif character in '&"<>[]#`':  # 检查可能影响标签解析的特殊字符。
      pieces.append(f"#{ord(character)};")  # 转成 Mermaid 支持的数字字符编码。
    else:  # 其余字符不需要转换。
      pieces.append(character)  # 保留原字符，包括中文。
  return "".join(pieces)  # 合并处理后的字符。