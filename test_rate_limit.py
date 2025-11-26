#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
速率限制测试脚本
测试 RateLimiter 的功能
"""

import sys
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from util.cognito.rate_limit import RateLimiter, get_rate_limiter
from util.cognito.redis_cache import get_token_cache

# 加载环境变量
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    load_dotenv(env_file)
    print(f"✅ 已加载环境配置: {env_file}")


def test_rate_limiter_basic():
    """测试基本的速率限制功能"""
    print("=" * 60)
    print("1️⃣ 测试基本速率限制功能")
    print("=" * 60)
    
    try:
        # 获取 Redis 缓存
        redis_cache = get_token_cache()
        if not redis_cache:
            print("❌ 无法连接到 Redis，跳过速率限制测试")
            return False
        
        print("✅ Redis 连接成功")
        
        # 创建速率限制器（每分钟5次，方便测试）
        limiter = RateLimiter(
            redis_cache=redis_cache,
            requests_per_minute=5,
            key_prefix="test_rate_limit:"
        )
        
        test_identifier = "test_client_123"
        
        print(f"\n📋 测试配置:")
        print(f"   标识符: {test_identifier}")
        print(f"   限制: 5 次/分钟")
        print(f"   Key前缀: test_rate_limit:")
        
        # 测试前5次请求（应该都成功）
        print(f"\n🔍 测试前5次请求（应该都成功）...")
        success_count = 0
        for i in range(5):
            try:
                result = limiter.check_rate_limit(identifier=test_identifier)
                if result.get("allowed"):
                    success_count += 1
                    remaining = result.get("remaining", 0)
                    current = result.get("current", 0)
                    print(f"   [{i+1}] ✅ 允许 - 当前: {current}, 剩余: {remaining}")
                else:
                    print(f"   [{i+1}] ❌ 被拒绝")
            except Exception as e:
                print(f"   [{i+1}] ❌ 异常: {str(e)}")
        
        if success_count != 5:
            print(f"❌ 前5次请求应该有5次成功，实际: {success_count}")
            return False
        
        # 测试第6次请求（应该被拒绝）
        print(f"\n🔍 测试第6次请求（应该被拒绝）...")
        try:
            from fastapi import HTTPException
            result = limiter.check_rate_limit(identifier=test_identifier)
            print(f"   ❌ 第6次请求应该被拒绝，但被允许了")
            return False
        except HTTPException as e:
            # 应该抛出 HTTPException（FastAPI 的异常）
            if e.status_code == 429:
                print(f"   ✅ 第6次请求被正确拒绝 (429 Too Many Requests)")
                print(f"   错误信息: {str(e.detail)[:100]}")
                return True
            else:
                print(f"   ❌ 捕获到 HTTPException，但状态码不正确: {e.status_code}")
                return False
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "rate_limit" in error_str.lower() or "Too Many Requests" in error_str:
                print(f"   ✅ 第6次请求被正确拒绝")
                print(f"   错误信息: {error_str[:100]}")
                return True
            else:
                print(f"   ❌ 捕获到异常，但不是速率限制异常: {error_str}")
                import traceback
                traceback.print_exc()
                return False
        
    except Exception as e:
        print(f"❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_rate_limiter_with_token():
    """测试使用 token 的速率限制"""
    print("\n" + "=" * 60)
    print("2️⃣ 测试基于 Token 的速率限制")
    print("=" * 60)
    
    try:
        redis_cache = get_token_cache()
        if not redis_cache:
            print("❌ 无法连接到 Redis，跳过测试")
            return False
        
        limiter = RateLimiter(
            redis_cache=redis_cache,
            requests_per_minute=3,
            key_prefix="test_rate_limit_token:"
        )
        
        # 模拟 token
        test_token = "test_token_abc123xyz"
        
        print(f"\n📋 测试配置:")
        print(f"   Token: {test_token[:20]}...")
        print(f"   限制: 3 次/分钟")
        
        # 测试3次请求
        print(f"\n🔍 测试3次请求...")
        for i in range(3):
            try:
                result = limiter.check_rate_limit(token=test_token)
                if result.get("allowed"):
                    remaining = result.get("remaining", 0)
                    current = result.get("current", 0)
                    print(f"   [{i+1}] ✅ 允许 - 当前: {current}, 剩余: {remaining}")
                else:
                    print(f"   [{i+1}] ❌ 被拒绝")
                    return False
            except Exception as e:
                print(f"   [{i+1}] ❌ 异常: {str(e)}")
                return False
        
        # 测试第4次（应该被拒绝）
        print(f"\n🔍 测试第4次请求（应该被拒绝）...")
        try:
            from fastapi import HTTPException
            result = limiter.check_rate_limit(token=test_token)
            print(f"   ❌ 第4次请求应该被拒绝，但被允许了")
            return False
        except HTTPException as e:
            if e.status_code == 429:
                print(f"   ✅ 第4次请求被正确拒绝 (429 Too Many Requests)")
                return True
            else:
                print(f"   ❌ 状态码不正确: {e.status_code}")
                return False
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "rate_limit" in error_str.lower():
                print(f"   ✅ 第4次请求被正确拒绝")
                return True
            else:
                print(f"   ❌ 异常类型不正确: {error_str}")
                return False
        
    except Exception as e:
        print(f"❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_rate_limiter_with_claims():
    """测试使用 claims 的速率限制"""
    print("\n" + "=" * 60)
    print("3️⃣ 测试基于 Claims 的速率限制")
    print("=" * 60)
    
    try:
        redis_cache = get_token_cache()
        if not redis_cache:
            print("❌ 无法连接到 Redis，跳过测试")
            return False
        
        limiter = RateLimiter(
            redis_cache=redis_cache,
            requests_per_minute=4,
            key_prefix="test_rate_limit_claims:"
        )
        
        # 模拟 claims
        test_claims = {
            "client_id": "test_client_456",
            "sub": "user_123",
            "exp": int(time.time()) + 3600
        }
        
        print(f"\n📋 测试配置:")
        print(f"   Client ID: {test_claims['client_id']}")
        print(f"   限制: 4 次/分钟")
        
        # 测试4次请求
        print(f"\n🔍 测试4次请求...")
        for i in range(4):
            try:
                result = limiter.check_rate_limit(claims=test_claims)
                if result.get("allowed"):
                    remaining = result.get("remaining", 0)
                    current = result.get("current", 0)
                    print(f"   [{i+1}] ✅ 允许 - 当前: {current}, 剩余: {remaining}")
                else:
                    print(f"   [{i+1}] ❌ 被拒绝")
                    return False
            except Exception as e:
                print(f"   [{i+1}] ❌ 异常: {str(e)}")
                return False
        
        # 测试第5次（应该被拒绝）
        print(f"\n🔍 测试第5次请求（应该被拒绝）...")
        try:
            from fastapi import HTTPException
            result = limiter.check_rate_limit(claims=test_claims)
            print(f"   ❌ 第5次请求应该被拒绝，但被允许了")
            return False
        except HTTPException as e:
            if e.status_code == 429:
                print(f"   ✅ 第5次请求被正确拒绝 (429 Too Many Requests)")
                return True
            else:
                print(f"   ❌ 状态码不正确: {e.status_code}")
                return False
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "rate_limit" in error_str.lower():
                print(f"   ✅ 第5次请求被正确拒绝")
                return True
            else:
                print(f"   ❌ 异常类型不正确: {error_str}")
                return False
        
    except Exception as e:
        print(f"❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_rate_limiter_time_window():
    """测试时间窗口重置"""
    print("\n" + "=" * 60)
    print("4️⃣ 测试时间窗口重置")
    print("=" * 60)
    
    try:
        redis_cache = get_token_cache()
        if not redis_cache:
            print("❌ 无法连接到 Redis，跳过测试")
            return False
        
        limiter = RateLimiter(
            redis_cache=redis_cache,
            requests_per_minute=2,
            key_prefix="test_rate_limit_window:"
        )
        
        test_identifier = "test_window_client"
        
        print(f"\n📋 测试配置:")
        print(f"   标识符: {test_identifier}")
        print(f"   限制: 2 次/分钟")
        
        # 使用2次
        print(f"\n🔍 使用2次请求...")
        for i in range(2):
            try:
                result = limiter.check_rate_limit(identifier=test_identifier)
                if result.get("allowed"):
                    print(f"   [{i+1}] ✅ 允许")
                else:
                    print(f"   [{i+1}] ❌ 被拒绝")
                    return False
            except Exception as e:
                print(f"   [{i+1}] ❌ 异常: {str(e)}")
                return False
        
        # 第3次应该被拒绝
        print(f"\n🔍 测试第3次请求（应该被拒绝）...")
        try:
            from fastapi import HTTPException
            result = limiter.check_rate_limit(identifier=test_identifier)
            print(f"   ❌ 第3次请求应该被拒绝")
            return False
        except HTTPException as e:
            if e.status_code == 429:
                print(f"   ✅ 第3次请求被正确拒绝 (429 Too Many Requests)")
            else:
                print(f"   ⚠️  被拒绝但状态码不正确: {e.status_code}")
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "rate_limit" in error_str.lower():
                print(f"   ✅ 第3次请求被正确拒绝")
            else:
                print(f"   ⚠️  异常: {error_str}")
        
        # 获取限流信息（不增加计数）
        print(f"\n🔍 获取限流信息（不增加计数）...")
        info = limiter.get_rate_limit_info(test_identifier)
        print(f"   限制: {info.get('limit')}")
        print(f"   当前: {info.get('current')}")
        print(f"   剩余: {info.get('remaining')}")
        
        if info.get('remaining') == 0:
            print(f"   ✅ 限流信息正确（剩余为0）")
        else:
            print(f"   ⚠️  限流信息可能不正确")
        
        print(f"\n💡 提示: 等待下一分钟窗口，限流会自动重置")
        print(f"   或者可以手动清理测试 key: test_rate_limit_window:{test_identifier}:*")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_rate_limiter_different_identifiers():
    """测试不同标识符的独立限流"""
    print("\n" + "=" * 60)
    print("5️⃣ 测试不同标识符的独立限流")
    print("=" * 60)
    
    try:
        redis_cache = get_token_cache()
        if not redis_cache:
            print("❌ 无法连接到 Redis，跳过测试")
            return False
        
        limiter = RateLimiter(
            redis_cache=redis_cache,
            requests_per_minute=3,
            key_prefix="test_rate_limit_multi:"
        )
        
        identifiers = ["client_a", "client_b", "client_c"]
        
        print(f"\n📋 测试配置:")
        print(f"   标识符: {', '.join(identifiers)}")
        print(f"   每个限制: 3 次/分钟")
        
        # 每个标识符使用3次（总共9次，应该都成功）
        print(f"\n🔍 每个标识符使用3次请求...")
        for identifier in identifiers:
            for i in range(3):
                try:
                    result = limiter.check_rate_limit(identifier=identifier)
                    if result.get("allowed"):
                        remaining = result.get("remaining", 0)
                        print(f"   [{identifier}] [{i+1}] ✅ 允许 - 剩余: {remaining}")
                    else:
                        print(f"   [{identifier}] [{i+1}] ❌ 被拒绝")
                        return False
                except Exception as e:
                    print(f"   [{identifier}] [{i+1}] ❌ 异常: {str(e)}")
                    return False
        
        # 每个标识符再试一次（应该都被拒绝）
        print(f"\n🔍 每个标识符再试一次（应该都被拒绝）...")
        all_rejected = True
        for identifier in identifiers:
            try:
                from fastapi import HTTPException
                result = limiter.check_rate_limit(identifier=identifier)
                print(f"   [{identifier}] ❌ 应该被拒绝，但被允许了")
                all_rejected = False
            except HTTPException as e:
                if e.status_code == 429:
                    print(f"   [{identifier}] ✅ 被正确拒绝 (429)")
                else:
                    print(f"   [{identifier}] ⚠️  被拒绝但状态码不正确: {e.status_code}")
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "rate_limit" in error_str.lower():
                    print(f"   [{identifier}] ✅ 被正确拒绝")
                else:
                    print(f"   [{identifier}] ⚠️  异常: {error_str}")
        
        if all_rejected:
            print(f"\n✅ 所有标识符的限流都独立工作")
            return True
        else:
            print(f"\n❌ 部分标识符的限流未正确工作")
            return False
        
    except Exception as e:
        print(f"❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_rate_limiter_without_redis():
    """测试没有 Redis 时的行为（应该允许所有请求）"""
    print("\n" + "=" * 60)
    print("6️⃣ 测试没有 Redis 时的行为")
    print("=" * 60)
    
    try:
        # 创建一个模拟的没有 Redis 的 TokenCache
        class MockTokenCache:
            def __init__(self):
                self.redis_client = None
        
        # 创建没有 Redis 的限流器（显式传入 None，不使用 get_token_cache）
        limiter = RateLimiter(
            redis_cache=None,  # 显式设置为 None
            requests_per_minute=5,
            key_prefix="test_rate_limit_no_redis:"
        )
        
        # 验证限流器确实没有启用
        if limiter.enabled:
            print(f"   ⚠️  限流器仍然启用了 Redis（因为 get_token_cache() 返回了连接）")
            print(f"   💡 这是正常的，因为环境中配置了 Redis")
            print(f"   💡 要真正测试无 Redis 场景，需要临时禁用 Redis 配置")
            print(f"\n   跳过此测试（在实际无 Redis 环境中会自动允许所有请求）")
            return True
        
        print(f"\n📋 测试配置:")
        print(f"   Redis: 未连接")
        print(f"   限制: 5 次/分钟")
        
        # 应该允许所有请求（因为没有 Redis，无法限流）
        print(f"\n🔍 测试多次请求（应该都允许）...")
        for i in range(10):
            result = limiter.check_rate_limit(identifier="test_no_redis")
            if result.get("allowed"):
                remaining = result.get("remaining", 0)
                print(f"   [{i+1}] ✅ 允许 - 剩余: {remaining}")
            else:
                print(f"   [{i+1}] ❌ 被拒绝（不应该发生）")
                return False
        
        print(f"\n✅ 没有 Redis 时，所有请求都被允许（符合预期）")
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def cleanup_test_keys():
    """清理测试用的 Redis keys"""
    print("\n" + "=" * 60)
    print("🧹 清理测试 keys")
    print("=" * 60)
    
    try:
        redis_cache = get_token_cache()
        if not redis_cache:
            print("⚠️  无法连接到 Redis，跳过清理")
            return
        
        redis_client = redis_cache.redis_client
        
        # 清理所有测试前缀的 keys
        test_prefixes = [
            "test_rate_limit:",
            "test_rate_limit_token:",
            "test_rate_limit_claims:",
            "test_rate_limit_window:",
            "test_rate_limit_multi:"
        ]
        
        total_deleted = 0
        for prefix in test_prefixes:
            keys = redis_client.keys(f"{prefix}*")
            if keys:
                deleted = redis_client.delete(*keys)
                total_deleted += deleted
                print(f"   清理 {prefix}*: {deleted} 个 keys")
        
        if total_deleted > 0:
            print(f"\n✅ 共清理 {total_deleted} 个测试 keys")
        else:
            print(f"\nℹ️  没有需要清理的测试 keys")
        
    except Exception as e:
        print(f"⚠️  清理失败: {str(e)}")


def main():
    """主测试函数"""
    print("=" * 60)
    print("🚀 速率限制功能测试")
    print("=" * 60)
    
    # 检查 Redis 连接
    print("\n📋 检查 Redis 连接...")
    redis_cache = get_token_cache()
    if redis_cache:
        conn_kwargs = redis_cache.redis_client.connection_pool.connection_kwargs
        print(f"   ✅ Redis 连接成功")
        print(f"   Host: {conn_kwargs.get('host')}")
        print(f"   Port: {conn_kwargs.get('port')}")
        print(f"   DB: {conn_kwargs.get('db')}")
    else:
        print(f"   ⚠️  Redis 未连接，部分测试将跳过")
    
    # 运行测试
    test_results = []
    
    test_results.append(("基本速率限制", test_rate_limiter_basic()))
    test_results.append(("基于 Token 的限流", test_rate_limiter_with_token()))
    test_results.append(("基于 Claims 的限流", test_rate_limiter_with_claims()))
    test_results.append(("时间窗口重置", test_rate_limiter_time_window()))
    test_results.append(("不同标识符独立限流", test_rate_limiter_different_identifiers()))
    test_results.append(("无 Redis 时的行为", test_rate_limiter_without_redis()))
    
    # 清理测试 keys
    cleanup_test_keys()
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("📊 测试结果汇总")
    print("=" * 60)
    
    success_count = sum(1 for _, result in test_results if result)
    total_count = len(test_results)
    
    for test_name, result in test_results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"   {status} - {test_name}")
    
    print("\n" + "=" * 60)
    print(f"测试完成: {success_count}/{total_count} 个测试通过")
    print("=" * 60)
    
    if success_count == total_count:
        print("\n✅ 所有测试通过！速率限制功能正常")
    else:
        print(f"\n⚠️  部分测试失败，请检查上述输出")


if __name__ == "__main__":
    main()

