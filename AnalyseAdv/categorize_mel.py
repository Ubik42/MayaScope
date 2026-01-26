import re
import os

# ================= 配置区域 =================
MEL_FILE = "ADV原始代码.mel"
LIST_FILE = "对ADV原始方法进行分类排序.txt"
OUTPUT_FILE = "ADV重排序后.mel"
# ===========================================


def read_file_lines(file_path):
    """尝试用不同编码读取文件"""
    if not os.path.exists(file_path):
        print(f"❌ 错误: 找不到文件 {file_path}")
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.readlines()
    except UnicodeDecodeError:
        pass

    try:
        with open(file_path, "r", encoding="gbk") as f:
            print(f"⚠️ 注意: {file_path} 似乎是 GBK 编码，已自动切换读取模式。")
            return f.readlines()
    except UnicodeDecodeError:
        print(f"❌ 错误: 无法识别 {file_path} 的编码，请将其另存为 UTF-8。")
        return None


def parse_category_file(file_path):
    """解析分类列表文件"""
    categories = []
    current_category = None

    print(f"📄 正在读取列表文件: {file_path} ...")
    lines = read_file_lines(file_path)
    if lines is None:
        return []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 宽松匹配：只要包含“类型”或“Type”且有数字
        is_header = False
        if ("类型" in line or "Type" in line) and any(char.isdigit() for char in line):
            is_header = True

        if is_header:
            current_category = {"name": line, "funcs": []}
            categories.append(current_category)
        elif current_category is not None:
            func_name = line.split()[0]
            if func_name.startswith("//") or func_name.startswith("=="):
                continue
            current_category["funcs"].append(func_name)

    return categories


def parse_mel_file(file_path):
    """
    解析 MEL 文件 (核心修复：支持忽略 /* ... */ 注释块)
    """
    print(f"🔍 正在解析 MEL 文件: {file_path} ...")
    lines = read_file_lines(file_path)
    if lines is None:
        return None, None

    header_lines = []
    func_map = {}

    # 正则：匹配 global proc 定义
    proc_pattern = re.compile(r"^\s*global\s+proc\s+(?:.+?\s+)?(\w+)\s*\(")

    current_func_name = None
    current_func_lines = []
    in_header = True

    # === 状态标记：是否处于块注释中 ===
    in_comment_block = False

    for line in lines:
        # 1. 检查是否正在注释块中
        if in_comment_block:
            # 如果处于注释块中，我们要寻找结束符 */
            if "*/" in line:
                in_comment_block = False
                # 注意：一行里可能出现 `*/ global proc...` 这种极端情况
                # 但通常 */ 是单独结束的。为了稳妥，我们这行依然视为"上一段内容"，不进行正则匹配
                if in_header:
                    header_lines.append(line)
                else:
                    current_func_lines.append(line)
                continue
            else:
                # 依然在注释块深处，直接归档，【跳过正则匹配】
                if in_header:
                    header_lines.append(line)
                else:
                    current_func_lines.append(line)
                continue

        # 2. 如果不在注释块中，检查本行是否开启了新的注释块
        # 必须先处理正则，再处理开启注释。因为 global proc 可能在 /* 之前 (极少见)
        # 但通常是 /* 在行首。
        # 逻辑：如果本行有 /* 且没有配对的 */，或者 */ 在 /* 之前，则开启注释模式

        start_comment_idx = line.find("/*")
        end_comment_idx = line.find("*/")

        # 暂存一个标记，决定下一行是否进入注释模式
        will_be_in_comment = False
        if start_comment_idx != -1:
            # 如果没有结束符，或者结束符在开始符之前 (如 */ ... /* )
            if end_comment_idx == -1 or end_comment_idx < start_comment_idx:
                will_be_in_comment = True

        # 3. 正则匹配 (仅当本行不是以注释开头时才算有效)
        # 如果 regex 匹配成功，我们还要确保它不在行内的注释里
        # 简单判断：如果正则匹配了，且匹配位置在 /* 之前 (如果存在 /*)，则有效
        match = proc_pattern.match(line)

        is_valid_func = False
        if match:
            # 再次确认：匹配到的 proc 不是被 /* 包裹的
            # 比如: /* global proc MyFunc() */ -> 虽然 regex 锚定行首 ^，但为了严谨
            # 实际上 ^\s*global 已经排除了行首有 /* 的情况
            is_valid_func = True

        if is_valid_func:
            new_func_name = match.group(1)

            if in_header:
                in_header = False
            else:
                if current_func_name:
                    func_map[current_func_name] = "".join(current_func_lines)

            current_func_name = new_func_name
            current_func_lines = [line]
        else:
            # 普通代码行
            if in_header:
                header_lines.append(line)
            else:
                current_func_lines.append(line)

        # 4. 更新下一行的状态
        if will_be_in_comment:
            in_comment_block = True

    # 循环结束，保存最后一个函数
    if current_func_name:
        func_map[current_func_name] = "".join(current_func_lines)

    return "".join(header_lines), func_map


def main():
    # 1. 解析分类
    categories = parse_category_file(LIST_FILE)
    if not categories:
        return

    # 2. 解析 MEL
    header, func_map = parse_mel_file(MEL_FILE)
    if func_map is None:
        return

    print(
        f"📊 统计: 列表包含 {len(categories)} 个分类，MEL 文件提取到 {len(func_map)} 个 global proc。"
    )

    # 3. 重组
    output_content = []
    output_content.append(header)

    processed_funcs = set()

    for cat in categories:
        cat_name = cat["name"]
        funcs = cat["funcs"]

        output_content.append(f"\n// #region {cat_name}\n")

        count = 0
        for func_name in funcs:
            if func_name in func_map:
                output_content.append(func_map[func_name])
                processed_funcs.add(func_name)
                count += 1

        output_content.append(f"\n// #endregion {cat_name}\n")
        print(f"  -> 分类 '{cat_name}' 完成: 包含 {count} 个函数")

    # 4. 未分类处理
    all_funcs = set(func_map.keys())
    remaining_funcs = list(all_funcs - processed_funcs)

    if remaining_funcs:
        print(f"📦 发现 {len(remaining_funcs)} 个未分类函数，正在移至末尾...")
        remaining_funcs.sort()

        output_content.append(f"\n// #region 待分类 (Uncategorized)\n")
        for func_name in remaining_funcs:
            output_content.append(func_map[func_name])
        output_content.append(f"\n// #endregion 待分类\n")

    # 5. 写入
    print(f"💾 正在写入: {OUTPUT_FILE} ...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("".join(output_content))

    print("✅ 全部完成！")


if __name__ == "__main__":
    main()
