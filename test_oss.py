"""
测试 OSS 配置是否正确
"""

import os
from pathlib import Path

# 添加项目路径
import sys
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.billing_agent.integrations import OSSAdapter


def test_oss_configuration():
    """测试 OSS 配置"""
    print("=" * 60)
    print("OSS 配置测试")
    print("=" * 60)

    # 创建 OSS 适配器
    oss = OSSAdapter()

    # 检查配置
    print("\n【配置检查】")
    print(f"  Access Key ID: {oss.access_key_id[:10]}..." if oss.access_key_id else "  Access Key ID: ❌ 未配置")
    print(f"  Access Key Secret: {'*' * 20}" if oss.access_key_secret else "  Access Key Secret: ❌ 未配置")
    print(f"  Endpoint: {oss.endpoint}" if oss.endpoint else "  Endpoint: ❌ 未配置")
    print(f"  Bucket: {oss.bucket_name}" if oss.bucket_name else "  Bucket: ❌ 未配置")

    # 判断是否配置完整
    if oss.is_configured():
        print("\n✅ OSS 配置完整！")
        print("\n【配置详情】")
        print(f"  Bucket 名称: {oss.bucket_name}")
        print(f"  地域节点: {oss.endpoint}")
        print(f"  访问密钥: {oss.access_key_id[:10]}...{oss.access_key_id[-4:]}")

        print("\n【测试建议】")
        print("  1. 重启 Streamlit: streamlit run app.py")
        print("  2. 上传一张图片测试")
        print("  3. 检查是否成功识别")

        return True
    else:
        print("\n❌ OSS 配置不完整")
        print("\n【缺失的配置】")

        missing = []
        if not oss.access_key_id:
            missing.append("OSS_ACCESS_KEY_ID")
        if not oss.access_key_secret:
            missing.append("OSS_ACCESS_KEY_SECRET")
        if not oss.endpoint:
            missing.append("OSS_ENDPOINT")
        if not oss.bucket_name:
            missing.append("OSS_BUCKET")

        for item in missing:
            print(f"  ❌ {item}")

        print("\n【配置方法】")
        print("  1. 复制 .env.example 为 .env")
        print("  2. 编辑 .env 文件，填入以下内容：")
        print()
        print("     OSS_BUCKET=ocr-phy")
        print("     OSS_ENDPOINT=oss-cn-shanghai.aliyuncs.com")
        print("     OSS_ACCESS_KEY_ID=你的AccessKey ID")
        print("     OSS_ACCESS_KEY_SECRET=你的AccessKey Secret")
        print()
        print("  3. 保存文件并重新运行此脚本")

        return False


def test_env_file():
    """检查 .env 文件"""
    print("\n" + "=" * 60)
    print(".env 文件检查")
    print("=" * 60)

    env_file = Path(".env")
    env_example = Path(".env.example")

    if env_file.exists():
        print("\n✅ .env 文件存在")

        # 读取文件内容
        with open(env_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # 检查是否包含 OSS 配置
        if 'OSS_BUCKET' in content:
            print("✅ 包含 OSS_BUCKET 配置")
        else:
            print("❌ 缺少 OSS_BUCKET 配置")

        if 'OSS_ENDPOINT' in content:
            print("✅ 包含 OSS_ENDPOINT 配置")
        else:
            print("❌ 缺少 OSS_ENDPOINT 配置")

        if 'OSS_ACCESS_KEY_ID' in content:
            print("✅ 包含 OSS_ACCESS_KEY_ID 配置")
            # 检查是否已填写
            if 'your_access_key_id_here' in content:
                print("   ⚠️  请替换为实际的 AccessKey ID")
        else:
            print("❌ 缺少 OSS_ACCESS_KEY_ID 配置")

        if 'OSS_ACCESS_KEY_SECRET' in content:
            print("✅ 包含 OSS_ACCESS_KEY_SECRET 配置")
            if 'your_access_key_secret_here' in content:
                print("   ⚠️  请替换为实际的 AccessKey Secret")
        else:
            print("❌ 缺少 OSS_ACCESS_KEY_SECRET 配置")

    else:
        print("\n❌ .env 文件不存在")

        if env_example.exists():
            print("\n💡 发现 .env.example 文件")
            print("   请复制为 .env 并填入实际配置：")
            print()
            print("   copy .env.example .env")
        else:
            print("\n请手动创建 .env 文件")


if __name__ == "__main__":
    print("\n🔧 航运账单智能处理系统 - OSS 配置测试\n")

    # 检查 .env 文件
    test_env_file()

    print()

    # 测试 OSS 配置
    success = test_oss_configuration()

    print("\n" + "=" * 60)

    if success:
        print("✅ 配置测试通过！可以处理图片文件了。")
    else:
        print("❌ 配置测试失败，请按照上述提示完成配置。")

    print("=" * 60)
    print()
