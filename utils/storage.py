# utils/storage.py
import json
import os
import logging
from datetime import datetime
import time

logger = logging.getLogger("Amaya.Storage")

# 定义记忆库的物理路径
DATA_DIR = "data/memory_bank"
os.makedirs(DATA_DIR, exist_ok=True)

# --- 文件路径注册表 ---
# 集中管理所有数据文件路径
FILES = {
    "meta": os.path.join("data", "meta.json"),
    "pending_reminders": os.path.join("data", "pending_reminders.json"),
    "sys_bus": os.path.join("data", "sys_event_bus.jsonl")
}

# --- 通用文件读写 ---
def load_json(file_key, default=None):
    """读取指定的 JSON 文件"""
    path = FILES.get(file_key)
    if not path or not os.path.exists(path):
        return default if default is not None else []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"JSON 解析失败 {path}: {e}")
        return default if default is not None else []
    except IOError as e:
        logger.warning(f"读取文件失败 {path}: {e}")
        return default if default is not None else []

def save_json(file_key, data):
    """保存数据到指定的 JSON 文件"""
    path = FILES.get(file_key)
    if not path:
        logger.error(f"未知的 file_key: {file_key}")
        return False
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except IOError as e:
        logger.error(f"保存 {path} 失败: {e}")
        return False
    except TypeError as e:
        logger.error(f"JSON 序列化失败 {path}: {e}")
        return False

# --- Amaya 记忆文件系统 API ---
def list_files_in_memory():
    """列出所有记忆文件"""
    return [f for f in os.listdir(DATA_DIR) if not f.startswith('.')]

def read_file_content(filename):
    """读取记忆库中的文件内容"""
    path = os.path.join(DATA_DIR, os.path.basename(filename)) # 安全处理
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {str(e)}"

def write_file_content(filename, content):
    """写入/覆盖记忆库中的文件内容"""
    path = os.path.join(DATA_DIR, os.path.basename(filename))
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        logger.debug(f"已写入文件: {filename}")
        return True
    except IOError as e:
        logger.error(f"写入文件 {filename} 失败: {e}")
        return False
    except Exception as e:
        logger.exception(f"写入文件 {filename} 时发生未知错误: {e}")
        return False

def delete_file(filename):
    """删除记忆库中的文件"""
    path = os.path.join(DATA_DIR, os.path.basename(filename))
    if os.path.exists(path):
        os.remove(path)
        toggle_pin_status(filename, pin=False)
        return True
    return False

# --- 置顶 (Pin) 逻辑 ---
def toggle_pin_status(filename, pin: bool):
    """设置或取消置顶"""
    meta = load_json("meta", default={"pinned_files": []})
    safe_name = os.path.basename(filename)
    if pin:
        if safe_name not in meta["pinned_files"]:
            meta["pinned_files"].append(safe_name)
    else:
        if safe_name in meta["pinned_files"]:
            meta["pinned_files"].remove(safe_name)
    save_json("meta", meta)
    return safe_name in meta["pinned_files"]

def get_pinned_content():
    """获取所有置顶文件的内容"""
    meta = load_json("meta", default={"pinned_files": []})
    context_str = ""
    for fname in meta["pinned_files"]:
        content = read_file_content(fname)
        if content:
            context_str += f"\n--- [Pinned Memory: {fname}] ---\n{content}\n"
    return context_str



# 定义哪些文件是 Amaya "睁眼" 就应该看见的 (即使没有被 Pin)
DEFAULT_VISIBLE_FILES = ["routine.json", "plan.md", "user_profile.md", "current_goals.md"]

def get_pending_reminders_summary():
    """将挂起的闹钟任务转换为较为可读的摘要"""
    reminders = load_json("pending_reminders", default=[])
    if not reminders:
        return "无挂起的提醒任务。"

    summary = ['以下是提醒任务列表']
    now = time.time()
    for reminder in reminders:
        reminder_id = reminder.get('id', '')
        run_at = reminder.get('run_at', 0)
        prompt = reminder.get('prompt', '未知任务')

        # 计算剩余时间
        diff = int(run_at - now)
        if diff > 0:
            time_str = f"{diff}秒后"
            # 如果时间很长，显示具体日期
            if diff > 3600:
                dt = datetime.fromtimestamp(run_at)
                time_str = dt.strftime("%m-%d %H:%M")
            summary.append(f"- (ID: {reminder_id}) {prompt} (执行时间: {time_str})")

    return "\n".join(summary) if summary else "无挂起的提醒任务。"

def get_global_context_string():
    """
    【核心函数】
    聚合所有 Amaya 需要"默认"看见的信息。
    包括：
    1. Pinned Files (用户手动置顶)
    2. Default Files (系统默认可见，如 routine.md)
    3. Pending Reminders (当前的提醒列表)
    4. etc
    """
    context_parts = []

    # 1. 获取 Pinned Files
    meta = load_json("meta", default={"pinned_files": []})
    pinned_set = set(meta.get("pinned_files", []))

    # 2. 合并 Default Files (去重)
    for f in DEFAULT_VISIBLE_FILES:
        if os.path.exists(os.path.join(DATA_DIR, f)):
            pinned_set.add(f)

    # 3. 读取并组装内容
    if pinned_set:
        context_parts.append("=== 📂 MEMORY BANK (ACTIVE FILES) ===")
        for fname in pinned_set:
            content = read_file_content(fname)
            if content:
                # 加上文件名作为标题，方便 AI 区分
                context_parts.append(f"\n--- FILE: {fname} ---\n{content}")

    # 4. 注入 Pending Reminders (这能有效防止重复设置提醒！)
    reminders_summary = get_pending_reminders_summary()
    context_parts.append(f"\n=== ACTIVE TIMERS (PENDING) ===\n{reminders_summary}")

    return "\n".join(context_parts)