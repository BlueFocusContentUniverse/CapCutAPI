#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JWT Token验证器
使用python-jose和requests从Cognito获取JWKS并验证JWT
"""

import time
import json
import requests
from typing import Dict, Any, Optional
from jose import jwt, jwk
from jose.utils import base64url_decode
from jose.exceptions import JWTError, ExpiredSignatureError, JWTClaimsError
from util.cognito.config import CognitoConfig


class CognitoJWTVerifier:
    """Cognito JWT验证器（不使用AWS SDK）"""
    
    def __init__(self, config: Optional[CognitoConfig] = None):
        """
        初始化JWT验证器
        
        Args:
            config: CognitoConfig实例，如果为None则使用默认配置
        """
        self.config = config or CognitoConfig
        
        # 验证配置
        if not self.config.validate():
            raise ValueError("Cognito配置不完整，请检查环境变量")
        
        # 从用户池ID提取区域
        if '_' in self.config.USER_POOL_ID:
            self.region = self.config.USER_POOL_ID.split('_')[0]
        else:
            self.region = self.config.REGION
        
        # JWKS URL（Cognito的JWKS端点）
        self.jwks_url = f"https://cognito-idp.{self.region}.amazonaws.com/{self.config.USER_POOL_ID}/.well-known/jwks.json"
        
        # JWKS缓存
        self._jwks_cache: Optional[Dict[str, Any]] = None
        self._jwks_cache_time: float = 0
        self._jwks_cache_ttl: int = 3600  # 缓存1小时
        
        # 预期的issuer
        self.expected_issuer = f"https://cognito-idp.{self.region}.amazonaws.com/{self.config.USER_POOL_ID}"
        
        # 预期的audience（客户端ID）
        self.expected_audience = self.config.CLIENT_ID
    
    def _get_jwks(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        获取JWKS（JSON Web Key Set）
        
        Args:
            force_refresh: 是否强制刷新缓存（预留功能：调试、缓存可能损坏时，强制刷新）
        
        Returns:
            JWKS字典
        """
        # 检查缓存
        if (
            not force_refresh and
            self._jwks_cache and
            time.time() - self._jwks_cache_time < self._jwks_cache_ttl
        ):
            return self._jwks_cache
        
        try:
            response = requests.get(self.jwks_url, timeout=10)
            response.raise_for_status()
            
            jwks = response.json()
            self._jwks_cache = jwks
            self._jwks_cache_time = time.time()
            
            return jwks
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"获取JWKS失败: {str(e)}")
    
    def _get_signing_key(self, token: str) -> Any:
        """
        从JWKS中获取用于验证token的密钥
        
        Args:
            token: JWT token字符串
        
        Returns:
            签名密钥
        """
        # 解析token header（不验证签名）
        try:
            # 清理token（去除可能的空格和换行符）
            token = token.strip()
            unverified_header = jwt.get_unverified_header(token)
        except Exception as e:
            raise JWTError(f"无法解析token header: {str(e)}")
        
        kid = unverified_header.get('kid')
        if not kid:
            raise JWTError("Token header中缺少kid (Key ID)")
        
        # 获取JWKS
        jwks = self._get_jwks()
        
        # 查找匹配的密钥
        for key in jwks.get('keys', []):
            if key.get('kid') == kid:
                try:
                    # 使用python-jose的jwk.construct构建密钥
                    return jwk.construct(key)
                except Exception as e:
                    raise JWTError(f"无法构建签名密钥: {str(e)}")
        
        raise JWTError(f"未找到匹配的密钥 (kid: {kid})")
    
    def verify_token(
        self,
        token: str,
        verify_exp: bool = True,
        verify_aud: bool = True,
        verify_iss: bool = True
    ) -> Dict[str, Any]:
        """
        验证JWT token
        
        Args:
            token: JWT token字符串
            verify_exp: 是否验证过期时间
            verify_aud: 是否验证audience
            verify_iss: 是否验证issuer
        
        Returns:
            解码后的token claims
        
        Raises:
            JWTError: token验证失败
        """
        try:
            # 获取签名密钥
            signing_key = self._get_signing_key(token)
            
            # 准备验证选项
            options = {
                'verify_signature': True,
                'verify_exp': verify_exp,
                'verify_aud': verify_aud,
                'verify_iss': verify_iss,
            }
            
            # 验证并解码token
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=['RS256'],
                audience=self.expected_audience if verify_aud else None,
                issuer=self.expected_issuer if verify_iss else None,
                options=options
            )
            
            return claims
            
        except ExpiredSignatureError:
            raise JWTError("Token已过期")
        except JWTClaimsError as e:
            raise JWTError(f"Token claims验证失败: {str(e)}")
        except JWTError as e:
            raise JWTError(f"Token验证失败: {str(e)}")
        except Exception as e:
            raise JWTError(f"Token验证时发生错误: {str(e)}")
    
    def get_token_expiry(self, token: str) -> Optional[int]:
        """
        获取token的过期时间（不验证签名）
        
        Args:
            token: JWT token字符串
        
        Returns:
            过期时间戳（Unix时间戳），如果无法获取则返回None
        """
        try:
            claims = jwt.get_unverified_claims(token)
            return claims.get('exp')
        except Exception:
            return None
    
    def is_token_expired(self, token: str) -> bool:
        """
        检查token是否已过期（不验证签名）
        
        Args:
            token: JWT token字符串
        
        Returns:
            如果已过期返回True，否则返回False
        """
        exp = self.get_token_expiry(token)
        if exp is None:
            return True  # 如果无法获取过期时间，认为已过期
        
        return time.time() >= exp

