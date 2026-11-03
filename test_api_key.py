"""
测试千问 API Key 是否有效
"""

import os
from pathlib import Path

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()

api_key = os.getenv("DASHSCOPE_API_KEY", "")

print("=" * 60)
print("千问 API Key 测试")
print("=" * 60)

if not api_key:
    print("\n❌ 未找到 DASHSCOPE_API_KEY")
    print("请在 .env 文件中配置")
else:
    print(f"\n✅ 找到 API Key")
    print(f"   前缀: {api_key[:10]}...")
    print(f"   长度: {len(api_key)} 字符")

    # 测试 API 调用
    print("\n🔍 测试 API 调用...")

    try:
        import requests

        url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "qwen-max",
            "messages": [
                {"role": "user", "content": "你好"}
            ],
            "max_tokens": 10
        }

        response = requests.post(url, json=data, headers=headers, timeout=10)

        if response.status_code == 200:
            print("✅ API Key 有效！")
            print(f"   响应: {response.json()}")
        elif response.status_code == 401:
            print("❌ API Key 无效（401 Unauthorized）")
            print(f"   错误: {response.text}")
            print("\n可能原因：")
            print("1. API Key 格式不正确")
            print("2. API Key 已过期")
            print("3. API Key 被禁用")
            print("\n请访问阿里云控制台检查：")
            print("https://dashscope.console.aliyun.com/apiKey")
        else:
            print(f"❌ API 调用失败（状态码: {response.status_code}）")
            print(f"   错误: {response.text}")

    except Exception as e:
        print(f"❌ 测试失败: {e}")

print("\n" + "=" * 60)
