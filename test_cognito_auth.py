#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试Cognito认证集成
"""

import os
import sys
import requests
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

# 加载环境变量
from dotenv import load_dotenv

# 加载当前项目的.env
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    load_dotenv(env_file)
    print(f"✅ 已加载当前项目配置: {env_file}")
else:
    print(f"⚠️  未找到当前项目的.env文件: {env_file}")


def get_token_from_client():
    """从AWS_Cognito_Client获取token，或直接使用requests获取"""
    # 尝试多个可能的路径
    possible_paths = [
        Path(__file__).parent.parent.parent / "AWS_Cognito_Client",  # workspace/AWS_Cognito_Client
        Path(__file__).parent.parent / "AWS_Cognito_Client",  # jianying_api/AWS_Cognito_Client
        Path.home() / "workspace" / "AWS_Cognito_Client",  # ~/workspace/AWS_Cognito_Client
    ]
    
    client_path = None
    for path in possible_paths:
        if path.exists() and (path / "cognito_client.py").exists():
            client_path = path
            break
    
    # 方法1: 使用AWS_Cognito_Client项目
    if client_path:
        print(f"   📁 找到客户端项目: {client_path}")
        sys.path.insert(0, str(client_path))
        try:
            from cognito_client import CognitoM2MClient
            client = CognitoM2MClient()
            token = client.get_access_token()
            print(f"✅ 成功获取token: {token[:50]}...")
            return token
        except Exception as e:
            print(f"   ⚠️  使用客户端项目失败: {str(e)}")
            print(f"   尝试直接请求token...")
    
    # 方法2: 直接使用requests获取token（备用方案）
    try:
        return get_token_direct()
    except Exception as e:
        print(f"❌ 直接获取token也失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


def get_token_direct():
    """直接使用requests获取token（备用方案）"""
    import base64
    import requests
    
    # 硬编码配置（从AWS_Cognito_Client项目的.env，仅用于测试）
    # 这些配置不会影响生产环境
    region = os.getenv("COGNITO_REGION") or "us-west-2"
    user_pool_id = os.getenv("COGNITO_USER_POOL_ID") or "us-west-2_MHKocs7IE"
    client_id = os.getenv("COGNITO_CLIENT_ID") or "STK0Q1C81OEJLLRJ14DFCNNQ7"
    client_secret = os.getenv("COGNITO_CLIENT_SECRET") or "A1C17kg7sqadkh8gfldsuk2tnegr7AO2UDI7VM2IAJ0U3TKC8C"
    cognito_domain = os.getenv("COGNITO_DOMAIN") or "us-west-2mhkocs7ie.auth.us-west-2.amazoncognito.com"
    scope = os.getenv("COGNITO_SCOPE", "") or "default-m2m-resource-server-yde8kg/read"
    
    # 如果环境变量中没有，尝试从AWS_Cognito_Client项目的.env读取
    client_paths = [
        Path(__file__).parent.parent.parent / "AWS_Cognito_Client",
        Path(__file__).parent.parent / "AWS_Cognito_Client",
        Path.home() / "workspace" / "AWS_Cognito_Client",
    ]
    
    for client_path in client_paths:
        env_file = client_path / ".env"
        if env_file.exists():
            try:
                from dotenv import dotenv_values
                client_env = dotenv_values(env_file)
                region = client_env.get("COGNITO_REGION") or region
                user_pool_id = client_env.get("COGNITO_USER_POOL_ID") or user_pool_id
                client_id = client_env.get("COGNITO_CLIENT_ID") or client_id
                client_secret = client_env.get("COGNITO_CLIENT_SECRET") or client_secret
                cognito_domain = client_env.get("COGNITO_DOMAIN") or cognito_domain
                scope = client_env.get("COGNITO_SCOPE", "") or scope
                print(f"   ✅ 从 {client_path}/.env 读取配置")
                break
            except Exception as e:
                print(f"   ⚠️  读取 {env_file} 失败: {str(e)}")
    
    if not all([region, user_pool_id, client_id, client_secret]):
        missing = []
        if not region:
            missing.append("COGNITO_REGION")
        if not user_pool_id:
            missing.append("COGNITO_USER_POOL_ID")
        if not client_id:
            missing.append("COGNITO_CLIENT_ID")
        if not client_secret:
            missing.append("COGNITO_CLIENT_SECRET")
        raise ValueError(
            f"缺少必需的Cognito配置: {', '.join(missing)}\n"
            f"提示: 服务端项目不需要COGNITO_CLIENT_SECRET，但测试脚本需要它来获取token。\n"
            f"可以在.env中添加COGNITO_CLIENT_SECRET，或确保AWS_Cognito_Client项目的.env文件存在。"
        )
    
    # 优先使用COGNITO_DOMAIN构建token端点
    if cognito_domain:
        if cognito_domain.startswith('http'):
            token_endpoint = f"{cognito_domain.rstrip('/')}/oauth2/token"
        else:
            token_endpoint = f"https://{cognito_domain}/oauth2/token"
        print(f"   📡 使用COGNITO_DOMAIN构建Token端点: {token_endpoint}")
    else:
        # 备用方案：从metadata URL获取token端点
        metadata_url = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}/.well-known/openid-configuration"
        print(f"   📡 获取metadata: {metadata_url}")
        
        response = requests.get(metadata_url, timeout=10)
        response.raise_for_status()
        metadata = response.json()
        token_endpoint = metadata.get('token_endpoint')
        
        if not token_endpoint:
            raise ValueError(f"Metadata响应中缺少token_endpoint")
        
        print(f"   📡 Token端点: {token_endpoint}")
    
    # 准备Basic认证
    auth_string = f"{client_id}:{client_secret}"
    auth_header = base64.b64encode(auth_string.encode('utf-8')).decode('utf-8')
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {auth_header}"
    }
    
    data = {
        "grant_type": "client_credentials"
    }
    
    if scope:
        data["scope"] = scope
    
    response = requests.post(token_endpoint, headers=headers, data=data, timeout=10)
    
    if response.status_code != 200:
        error_detail = response.text
        try:
            error_json = response.json()
            error_msg = error_json.get('error_description', error_json.get('error', error_detail))
        except:
            error_msg = error_detail
        
        error_info = f"获取token失败 (状态码: {response.status_code})\n"
        error_info += f"错误: {error_msg}\n"
        error_info += f"端点: {token_endpoint}\n\n"
        error_info += "这通常是AWS Cognito应用客户端配置问题，请检查：\n"
        error_info += "1. 客户端类型必须是'Confidential client'（有密钥）\n"
        error_info += "2. 必须启用'客户端凭证'流程\n"
        error_info += "3. 客户端ID和密钥是否正确（注意大小写）\n"
        error_info += "4. 如果配置了资源服务器，需要指定COGNITO_SCOPE\n"
        error_info += "\n提示：服务端项目（CapCutAPI）已经正确配置，可以正常运行。\n"
        error_info += "这个错误只影响测试脚本，不影响实际API服务。\n"
        error_info += "详细说明请查看: TEST_SETUP.md"
        
        raise Exception(error_info)
    
    token_data = response.json()
    token = token_data.get('access_token')
    
    if not token:
        raise ValueError("响应中缺少access_token")
    
    print(f"✅ 成功获取token: {token[:50]}...")
    return token


def test_api_endpoint(base_url: str, token: str, endpoint: str, method: str = "GET", payload: dict = None):
    """测试API端点"""
    url = f"{base_url}{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    print(f"\n📡 测试端点: {method} {url}")
    if payload:
        print(f"   请求体: {str(payload)[:200]}")
    
    try:
        if method.upper() == "GET":
            response = requests.get(url, headers=headers, timeout=30)
        elif method.upper() == "POST":
            response = requests.post(url, headers=headers, json=payload, timeout=30)
        elif method.upper() == "PUT":
            response = requests.put(url, headers=headers, json=payload, timeout=30)
        elif method.upper() == "DELETE":
            response = requests.delete(url, headers=headers, timeout=30)
        else:
            print(f"   ❌ 不支持的HTTP方法: {method}")
            return False, None
        
        print(f"   状态码: {response.status_code}")
        
        # 200-299都算成功
        if 200 <= response.status_code < 300:
            print(f"   ✅ 成功")
            try:
                data = response.json()
                # 对于创建草稿等操作，显示关键信息
                if isinstance(data, dict):
                    if "output" in data and isinstance(data["output"], dict):
                        if "draft_id" in data["output"]:
                            print(f"   草稿ID: {data['output']['draft_id']}")
                        if "task_id" in data["output"]:
                            print(f"   任务ID: {data['output']['task_id']}")
                print(f"   响应: {str(data)[:300]}")
            except:
                print(f"   响应: {response.text[:300]}")
            return True, response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text
        elif response.status_code == 401:
            print(f"   ❌ 认证失败 (401 Unauthorized)")
            print(f"   错误: {response.text[:200]}")
            print(f"   提示: token可能无效或已过期")
            return False, None
        elif response.status_code == 404:
            print(f"   ⚠️  端点不存在 (404 Not Found)")
            print(f"   提示: 端点可能不存在或路径不正确")
            return False, None
        else:
            print(f"   ❌ 失败 (状态码: {response.status_code})")
            print(f"   错误: {response.text[:300]}")
            return False, None
        
    except Exception as e:
        print(f"   ❌ 请求异常: {str(e)}")
        import traceback
        traceback.print_exc()
        return False, None


def main():
    """主测试函数"""
    print("=" * 60)
    print("Cognito认证集成测试")
    print("=" * 60)
    
    # 1. 检查配置
    print("\n1️⃣ 检查配置...")
    required_vars = [
        "COGNITO_REGION",
        "COGNITO_USER_POOL_ID",
        "COGNITO_CLIENT_ID"
    ]
    
    missing = []
    for var in required_vars:
        value = os.getenv(var)
        if not value:
            missing.append(var)
        else:
            print(f"   ✅ {var}: {value}")
    
    if missing:
        print(f"   ❌ 缺少配置: {', '.join(missing)}")
        print("   请在.env文件中配置这些变量")
        return
    
    # 2. 获取token
    print("\n2️⃣ 获取Cognito token...")
    token = get_token_from_client()
    if not token:
        print("   ❌ 无法获取token，测试终止")
        return
    
    # 3. 测试API端点
    print("\n3️⃣ 测试API端点...")
    
    # 获取API基础URL（从环境变量或使用默认值）
    # 尝试从环境变量获取，如果没有则尝试检测运行中的服务器
    api_base = os.getenv("API_BASE_URL")
    if not api_base:
        # 尝试从settings.local获取端口配置
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).parent))
            from settings.local import PORT
            default_port = PORT
            print(f"   📍 从配置读取端口: {default_port}")
        except:
            default_port = 8000
            print(f"   ⚠️  无法读取端口配置，使用默认端口: {default_port}")
        
        # 尝试常见的端口
        ports_to_try = [default_port, 8000, 8080, 8981, 3000]
        ports_to_try = list(dict.fromkeys(ports_to_try))  # 去重但保持顺序
        
        print(f"   🔍 检测运行中的API服务器...")
        for port in ports_to_try:
            try:
                response = requests.get(f"http://localhost:{port}/health", timeout=2)
                if response.status_code == 200:
                    api_base = f"http://localhost:{port}"
                    print(f"   ✅ 找到运行中的服务器: {api_base}")
                    break
            except:
                continue
        
        if not api_base:
            api_base = f"http://localhost:{default_port}"
            print(f"   ⚠️  未检测到运行中的服务器")
            print(f"   💡 请先启动API服务器: python main.py")
            print(f"   📍 将使用URL: {api_base}")
    
    print(f"   API基础URL: {api_base}")
    
    # 测试健康检查端点（通常不需要认证）
    print("\n   📍 测试健康检查端点...")
    health_url = f"{api_base}/health"
    try:
        response = requests.get(health_url, timeout=5)
        if response.status_code == 200:
            print(f"   ✅ 健康检查通过 - 服务器正在运行")
        else:
            print(f"   ⚠️  健康检查返回: {response.status_code}")
    except Exception as e:
        print(f"   ❌ 无法连接到API服务器: {str(e)}")
        print(f"\n   💡 请先启动API服务器:")
        print(f"      cd /home/yadihan/workspace/jianying_api/CapCutAPI")
        print(f"      python main.py")
        print(f"\n   或者设置环境变量指定服务器地址:")
        print(f"      export API_BASE_URL=http://localhost:你的端口")
        return
    
    # 测试需要认证的端点
    print("\n   📋 将测试以下需要认证的端点:")
    
    test_results = []
    draft_id = None
    
    # 1. 测试获取视频列表
    print("\n" + "-" * 60)
    print("1️⃣ 测试获取视频列表")
    print("-" * 60)
    success, response = test_api_endpoint(api_base, token, "/api/videos", "GET")
    test_results.append(("GET /api/videos", success))
    
    # 2. 测试创建草稿
    print("\n" + "-" * 60)
    print("2️⃣ 测试创建草稿")
    print("-" * 60)
    create_draft_payload = {
        "width": 1080,
        "height": 1920,
        "framerate": 30,
        "name": "cognito_test_draft",
        "resource": "api"
    }
    success, response = test_api_endpoint(api_base, token, "/create_draft", "POST", create_draft_payload)
    test_results.append(("POST /create_draft", success))
    
    # 提取draft_id
    if success and response and isinstance(response, dict):
        if "output" in response and isinstance(response["output"], dict):
            draft_id = response["output"].get("draft_id")
            if draft_id:
                print(f"\n   💾 保存草稿ID: {draft_id} (用于后续测试)")
    
    # 3. 测试添加视频（如果有draft_id）
    if draft_id:
        print("\n" + "-" * 60)
        print("3️⃣ 测试添加视频到草稿")
        print("-" * 60)
        video_url = "https://objectstorageapi.bja.sealos.run/1wpzyo2e-ai-mcn/watermark_videos/20251103_084202_7f642ed8.MP4"
        add_video_payload = {
            "draft_id": draft_id,
            "video_url": video_url,
            "start": 0,
            "end": 0,  # 0表示到末尾
            "duration": 10.0,  # 假设视频10秒
            "target_start": 0,
            "track_name": "video_main",
            "volume": 1.0,
            "speed": 1.0
        }
        success, response = test_api_endpoint(api_base, token, "/add_video", "POST", add_video_payload)
        test_results.append(("POST /add_video", success))
    else:
        print("\n" + "-" * 60)
        print("3️⃣ 跳过添加视频测试（草稿创建失败）")
        print("-" * 60)
        test_results.append(("POST /add_video", False))
    
    # 4. 测试添加文本（如果有draft_id）
    if draft_id:
        print("\n" + "-" * 60)
        print("4️⃣ 测试添加文本到草稿")
        print("-" * 60)
        add_text_payload = {
            "draft_id": draft_id,
            "text": "Cognito认证测试",
            "start": 1.0,
            "end": 5.0,
            "track_name": "text_main",
            "font": "文轩体",
            "font_size": 48,
            "font_color": "#FFFFFF",
            "transform_y": -0.8,  # 字幕常用位置（底部）
            "shadow_enabled": True,
            "shadow_color": "#000000",
            "background_color": "#000000",
            "background_alpha": 0.5
        }
        success, response = test_api_endpoint(api_base, token, "/add_text", "POST", add_text_payload)
        test_results.append(("POST /add_text", success))
    else:
        print("\n" + "-" * 60)
        print("4️⃣ 跳过添加文本测试（草稿创建失败）")
        print("-" * 60)
        test_results.append(("POST /add_text", False))
    
    # 5. 测试查询草稿（如果有draft_id）
    if draft_id:
        print("\n" + "-" * 60)
        print("5️⃣ 测试查询草稿")
        print("-" * 60)
        query_script_payload = {
            "draft_id": draft_id,
            "force_update": True
        }
        success, response = test_api_endpoint(api_base, token, "/query_script", "POST", query_script_payload)
        test_results.append(("POST /query_script", success))
    else:
        print("\n" + "-" * 60)
        print("5️⃣ 跳过查询草稿测试（草稿创建失败）")
        print("-" * 60)
        test_results.append(("POST /query_script", False))
    
    # 6. 测试获取轨道信息（如果有draft_id）
    if draft_id:
        print("\n" + "-" * 60)
        print("6️⃣ 测试获取轨道信息")
        print("-" * 60)
        success, response = test_api_endpoint(api_base, token, f"/get_tracks?draft_id={draft_id}", "GET")
        test_results.append(("GET /get_tracks", success))
    else:
        print("\n" + "-" * 60)
        print("6️⃣ 跳过获取轨道信息测试（草稿创建失败）")
        print("-" * 60)
        test_results.append(("GET /get_tracks", False))
    
    # 7. 测试保存草稿（如果有draft_id）
    if draft_id:
        print("\n" + "-" * 60)
        print("7️⃣ 测试保存草稿")
        print("-" * 60)
        save_draft_payload = {
            "draft_id": draft_id
        }
        success, response = test_api_endpoint(api_base, token, "/save_draft", "POST", save_draft_payload)
        test_results.append(("POST /save_draft", success))
        if success and response and isinstance(response, dict):
            if "output" in response and isinstance(response["output"], dict):
                draft_url = response["output"].get("draft_url", "")
                if draft_url:
                    print(f"\n   📎 草稿URL: {draft_url}")
    else:
        print("\n" + "-" * 60)
        print("7️⃣ 跳过保存草稿测试（草稿创建失败）")
        print("-" * 60)
        test_results.append(("POST /save_draft", False))
    
    # 8. 测试获取字体类型（不需要draft_id）
    print("\n" + "-" * 60)
    print("8️⃣ 测试获取字体类型")
    print("-" * 60)
    success, response = test_api_endpoint(api_base, token, "/get_font_types", "GET")
    test_results.append(("GET /get_font_types", success))
    
    # 4. 测试结果汇总
    print("\n" + "=" * 60)
    print("📊 测试结果汇总")
    print("=" * 60)
    
    success_count = sum(1 for _, success in test_results if success)
    total_count = len(test_results)
    
    for endpoint_name, success in test_results:
        status = "✅ 通过" if success else "❌ 失败"
        print(f"   {status} - {endpoint_name}")
    
    print("\n" + "=" * 60)
    print(f"测试完成: {success_count}/{total_count} 个端点测试通过")
    print("=" * 60)
    
    if draft_id:
        print(f"\n💾 测试创建的草稿ID: {draft_id}")
        print(f"   可以使用以下命令查询草稿详情:")
        print(f"   python test_query_draft.py {draft_id}")
    
    if success_count == total_count:
        print("\n✅ 所有测试通过！Cognito认证集成成功")
    elif success_count > 0:
        print(f"\n⚠️  部分测试通过 ({success_count}/{total_count})，请检查失败的端点")
    else:
        print("\n❌ 所有测试失败，请检查配置和API服务器状态")


if __name__ == "__main__":
    main()

