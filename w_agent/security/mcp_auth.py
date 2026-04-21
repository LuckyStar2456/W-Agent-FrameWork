from typing import Optional, Dict, Any, List
import jwt
from datetime import datetime, timedelta

class JSONRPCRequest:
    """JSON-RPC请求"""
    def __init__(self, params: Dict[str, Any]):
        self.params = params

class McpTransport:
    """MCP传输层"""
    def get_peer_certificate(self) -> Optional[Any]:
        """获取对等证书"""
        return None

class Identity:
    """身份信息"""
    def __init__(self, user_id: str, roles: List[str], permissions: List[str]):
        self.user_id = user_id
        self.roles = roles
        self.permissions = permissions
    
    def has_permission(self, permission: str) -> bool:
        """检查是否有指定权限"""
        return permission in self.permissions

class AuthProvider:
    """认证提供者"""
    async def verify_certificate(self, cert: Any) -> Identity:
        """验证证书"""
        pass
    
    async def verify_token(self, token: str) -> Identity:
        """验证令牌"""
        pass

class JwtAuthProvider(AuthProvider):
    """基于JWT的认证提供者"""
    def __init__(self, secret_key: str, algorithm: str = "HS256", 
                 expiration_seconds: int = 3600, revocation_list: Optional['RevocationList'] = None):
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.expiration_seconds = expiration_seconds
        self.revocation_list = revocation_list
    
    async def verify_certificate(self, cert: Any) -> Identity:
        """验证证书"""
        # 简化实现，实际项目中需要解析和验证证书
        # 这里假设证书中包含用户信息
        user_id = getattr(cert, "subject", {}).get("CN", "unknown")
        return Identity(user_id=user_id, roles=["system"], permissions=["read:all", "write:all"])
    
    async def verify_token(self, token: str) -> Identity:
        """验证令牌"""
        try:
            # 解码JWT
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            
            # 检查令牌是否被吊销
            if self.revocation_list:
                token_id = payload.get("jti")
                if token_id and await self.revocation_list.is_revoked(token_id):
                    raise ValueError("Token has been revoked")
            
            # 检查令牌是否过期
            exp = payload.get("exp")
            if exp and datetime.utcnow().timestamp() > exp:
                raise ValueError("Token has expired")
            
            # 提取用户信息
            user_id = payload.get("sub", "unknown")
            roles = payload.get("roles", [])
            permissions = payload.get("permissions", [])
            
            return Identity(user_id=user_id, roles=roles, permissions=permissions)
        except Exception as e:
            raise ValueError(f"Invalid token: {str(e)}")
    
    def generate_token(self, user_id: str, roles: List[str] = None, permissions: List[str] = None) -> str:
        """生成JWT令牌"""
        roles = roles or []
        permissions = permissions or []
        
        payload = {
            "sub": user_id,
            "roles": roles,
            "permissions": permissions,
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + timedelta(seconds=self.expiration_seconds)
        }
        
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

class McpAuthMiddleware:
    def __init__(self, auth_provider: AuthProvider):
        self.auth_provider = auth_provider
    
    async def authenticate(self, request: JSONRPCRequest, transport: McpTransport) -> Optional[Identity]:
        # 优先使用 mTLS 证书（由传输层提供）
        cert = transport.get_peer_certificate()
        if cert:
            return await self.auth_provider.verify_certificate(cert)
        # 否则使用 Bearer Token
        auth_header = request.params.get("_meta", {}).get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            return await self.auth_provider.verify_token(token)
        return None

class RevocationList:
    def __init__(self, redis=None):
        self.redis = redis
        self._in_memory_revoked = set()  # 内存 fallback
    
    async def is_revoked(self, token_id: str) -> bool:
        """检查令牌是否被吊销"""
        if self.redis:
            try:
                return await self.redis.sismember("revoked_tokens", token_id)
            except Exception:
                # Redis 失败时使用内存 fallback
                pass
        return token_id in self._in_memory_revoked
    
    async def revoke(self, token_id: str):
        """吊销令牌"""
        if self.redis:
            try:
                await self.redis.sadd("revoked_tokens", token_id)
            except Exception:
                # Redis 失败时使用内存 fallback
                pass
        self._in_memory_revoked.add(token_id)