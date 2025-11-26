#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查Redis中的Cognito token缓存
"""

import sys
import os
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from util.cognito.redis_cache import get_token_cache
from dotenv import load_dotenv
import json
import time

def main():
    print("=" * 60)
    print("Redis Token缓存检查")
    print("=" * 60)
    
    # 显示环境变量配置
    import os
    from dotenv import load_dotenv
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        load_dotenv(env_file)
    
    print("\n📋 Redis配置信息:")
    print(f"   REDIS_HOST: {os.getenv('REDIS_HOST', '未设置')}")
    print(f"   REDIS_PORT: {os.getenv('REDIS_PORT', '未设置')}")
    print(f"   REDIS_DB: {os.getenv('REDIS_DB', '未设置')}")
    print(f"   REDIS_URL: {os.getenv('REDIS_URL', '未设置')}")
    print(f"   CELERY_BROKER_URL: {os.getenv('CELERY_BROKER_URL', '未设置')}")
    
    # 获取token缓存实例
    try:
        token_cache = get_token_cache()
        if not token_cache:
            print("\n❌ 无法连接到Redis")
            print("💡 提示: Redis可能未配置或未运行")
            return
        
        print("\n✅ Redis连接成功")
        
        # 显示实际连接信息
        redis_client = token_cache.redis_client
        conn_kwargs = redis_client.connection_pool.connection_kwargs
        print(f"\n🔗 实际连接信息:")
        print(f"   Host: {conn_kwargs.get('host', 'N/A')}")
        print(f"   Port: {conn_kwargs.get('port', 'N/A')}")
        print(f"   DB: {conn_kwargs.get('db', 'N/A')}")
        print(f"   Password: {'已设置' if conn_kwargs.get('password') else '未设置'}")
        
        # 查找所有token缓存
        token_keys = redis_client.keys("cognito:token:*")
        rate_limit_keys = redis_client.keys("rate_limit:*")
        
        print(f"\n📦 当前数据库 (DB {conn_kwargs.get('db', 'N/A')}) 缓存统计:")
        print(f"   Token缓存数量: {len(token_keys)}")
        print(f"   Rate Limit缓存数量: {len(rate_limit_keys)}")
        
        # 检查其他数据库（0-5）
        print(f"\n🔍 检查其他数据库的缓存...")
        import redis
        other_dbs_found = False
        for db_num in range(6):
            if db_num == conn_kwargs.get('db'):
                continue  # 跳过当前数据库
            try:
                test_client = redis.Redis(
                    host=conn_kwargs.get('host'),
                    port=conn_kwargs.get('port'),
                    db=db_num,
                    password=conn_kwargs.get('password'),
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2
                )
                test_client.ping()
                test_token_keys = test_client.keys("cognito:token:*")
                test_rate_keys = test_client.keys("rate_limit:*")
                if test_token_keys or test_rate_keys:
                    if not other_dbs_found:
                        other_dbs_found = True
                    print(f"   ✅ DB {db_num}: Token={len(test_token_keys)}, RateLimit={len(test_rate_keys)}")
            except Exception as e:
                # 连接失败，可能是数据库不存在或权限问题
                pass
        
        if not other_dbs_found:
            print(f"   ℹ️  其他数据库 (0-5, 排除DB {conn_kwargs.get('db')}) 中未找到缓存")
        
        if token_keys:
            print(f"\n--- Token缓存详情（前5个）---")
            for i, key in enumerate(token_keys[:5], 1):
                value = redis_client.get(key)
                ttl = redis_client.ttl(key)
                
                if value:
                    try:
                        data = json.loads(value)
                        client_id = data.get('client_id', 'N/A')
                        exp = data.get('exp', 0)
                        remaining = max(0, int(exp - time.time()))
                        
                        print(f"\n[{i}] Key: {key}")
                        print(f"    Client ID: {client_id}")
                        print(f"    Redis TTL: {ttl}秒 ({ttl//60}分钟)")
                        print(f"    Token剩余有效期: {remaining}秒 ({remaining//60}分钟)")
                        
                        # 显示部分claims
                        if 'scope' in data:
                            print(f"    Scope: {data['scope']}")
                        if 'token_use' in data:
                            print(f"    Token Use: {data['token_use']}")
                    except Exception as e:
                        print(f"\n[{i}] Key: {key}")
                        print(f"    Value: {value[:100]}...")
                        print(f"    TTL: {ttl}秒")
                        print(f"    ⚠️  解析错误: {str(e)}")
            
            if len(token_keys) > 5:
                print(f"\n... 还有 {len(token_keys) - 5} 个token缓存")
        else:
            print("\n⚠️  未找到token缓存")
            print("💡 提示: 需要先调用API才会缓存token")
            print("   运行: python test_cognito_auth.py")
        
        if rate_limit_keys:
            print(f"\n--- Rate Limit缓存（前5个）---")
            for i, key in enumerate(rate_limit_keys[:5], 1):
                count = redis_client.get(key)
                ttl = redis_client.ttl(key)
                print(f"[{i}] Key: {key}")
                print(f"    计数: {count}")
                print(f"    TTL: {ttl}秒")
        
        print("\n" + "=" * 60)
        print("✅ 检查完成")
        
    except Exception as e:
        print(f"\n❌ 错误: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()

