# config.py
import os
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OWNER_ID = os.getenv("OWNER_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


if not TOKEN:
    raise ValueError("错误：未找到 TELEGRAM_BOT_TOKEN，请检查 .env 文件！")

if not GEMINI_API_KEY:
    raise ValueError("错误：未找到 GEMINI_API_KEY！")