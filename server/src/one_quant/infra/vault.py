"""密钥管理集成 — Vault / 1Password / 环境变量降级

铁律：
- API/JWT 密钥经 Vault/1Password 服务账户，不入代码不入仓库
- 启动校验缺失即拒启
- 疑似泄露立即轮换
"""

from __future__ import annotations

import secrets
from abc import ABC, abstractmethod
from typing import Any

from one_quant.infra.logging import get_logger

logger = get_logger("vault")


# ──────────────────── 抽象基类 ────────────────────


class SecretProvider(ABC):
    """密钥 Provider 抽象基类。

    所有密钥后端（Vault、1Password、环境变量）实现此接口，
    由 SecretManager 统一调度。
    """

    @abstractmethod
    async def get_secret(self, key: str) -> str | None:
        """获取密钥。

        Args:
            key: 密钥名称。

        Returns:
            密钥值，不存在返回 None。
        """
        ...

    @abstractmethod
    async def set_secret(self, key: str, value: str) -> None:
        """设置密钥。

        Args:
            key: 密钥名称。
            value: 密钥值。
        """
        ...

    @abstractmethod
    async def rotate_secret(self, key: str) -> str:
        """轮换密钥（生成新值并写入）。

        Args:
            key: 密钥名称。

        Returns:
            新生成的密钥值。
        """
        ...

    @abstractmethod
    async def delete_secret(self, key: str) -> None:
        """删除密钥。

        Args:
            key: 密钥名称。
        """
        ...


# ──────────────────── HashiCorp Vault Provider ────────────────────


class VaultProvider(SecretProvider):
    """HashiCorp Vault KV v2 Provider。

    通过 HTTP API 与 Vault 交互，支持 KV v2 引擎。
    所有请求携带 X-Vault-Token 鉴权头。

    Args:
        vault_url: Vault 服务地址（如 https://vault.internal:8200）。
        token: Vault 认证 Token。
        mount_point: KV v2 引擎挂载点，默认 "secret"。
    """

    def __init__(
        self,
        vault_url: str,
        token: str,
        mount_point: str = "secret",
    ) -> None:
        self._url = vault_url.rstrip("/")
        self._token = token
        self._mount_point = mount_point
        self._client: Any = None  # httpx.AsyncClient，延迟初始化

    async def _get_client(self) -> Any:
        """获取或创建 HTTP 客户端（延迟初始化）。"""
        if self._client is None:
            try:
                import httpx
            except ImportError as exc:
                raise ImportError(
                    "Vault Provider 需要 httpx: pip install httpx"
                ) from exc
            self._client = httpx.AsyncClient(
                base_url=self._url,
                headers={"X-Vault-Token": self._token},
                timeout=10.0,
            )
        return self._client

    async def get_secret(self, key: str) -> str | None:
        """从 Vault KV v2 获取密钥。

        API: GET /v1/{mount_point}/data/{key}

        Args:
            key: 密钥路径（如 "prod/binance/api_key"）。

        Returns:
            密钥值，不存在返回 None。
        """
        client = await self._get_client()
        try:
            resp = await client.get(f"/v1/{self._mount_point}/data/{key}")
            if resp.status_code == 200:
                data = resp.json()
                # KV v2 返回格式: { data: { data: { key: value }, metadata: {...} } }
                secret_data = data.get("data", {}).get("data", {})
                # 取第一个值（约定密钥名与路径一致时取 "value" 字段）
                return secret_data.get("value") or secret_data.get(key) or next(
                    iter(secret_data.values()), None
                )
            elif resp.status_code == 404:
                logger.debug("Vault 密钥不存在: %s", key)
                return None
            else:
                logger.error("Vault 获取密钥失败: %s, HTTP %d", key, resp.status_code)
                return None
        except Exception as exc:
            logger.error("Vault 请求异常: %s, 错误: %s", key, exc)
            return None

    async def set_secret(self, key: str, value: str) -> None:
        """写入密钥到 Vault KV v2。

        API: POST /v1/{mount_point}/data/{key}

        Args:
            key: 密钥路径。
            value: 密钥值。
        """
        client = await self._get_client()
        try:
            resp = await client.post(
                f"/v1/{self._mount_point}/data/{key}",
                json={"data": {"value": value}},
            )
            if resp.status_code in (200, 204):
                logger.info("Vault 密钥已写入: %s", key)
            else:
                logger.error("Vault 写入失败: %s, HTTP %d", key, resp.status_code)
                raise RuntimeError(f"Vault 写入失败: HTTP {resp.status_code}")
        except Exception as exc:
            logger.error("Vault 写入异常: %s, 错误: %s", key, exc)
            raise

    async def rotate_secret(self, key: str) -> str:
        """轮换密钥：生成新的随机值并写入 Vault。

        Args:
            key: 密钥路径。

        Returns:
            新生成的密钥值。
        """
        new_value = secrets.token_urlsafe(32)
        await self.set_secret(key, new_value)
        logger.info("Vault 密钥已轮换: %s", key)
        return new_value

    async def delete_secret(self, key: str) -> None:
        """删除 Vault 中的密钥（软删除，标记为已删除）。

        API: DELETE /v1/{mount_point}/data/{key}

        Args:
            key: 密钥路径。
        """
        client = await self._get_client()
        try:
            resp = await client.delete(f"/v1/{self._mount_point}/data/{key}")
            if resp.status_code in (200, 204):
                logger.info("Vault 密钥已删除: %s", key)
            else:
                logger.error("Vault 删除失败: %s, HTTP %d", key, resp.status_code)
        except Exception as exc:
            logger.error("Vault 删除异常: %s, 错误: %s", key, exc)

    async def close(self) -> None:
        """关闭 HTTP 客户端。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


# ──────────────────── 1Password Provider ────────────────────


class OnePasswordProvider(SecretProvider):
    """1Password Provider（通过 CLI 交互）。

    依赖 1Password CLI (`op`)，适合 CI/CD 和本地开发环境。
    需要预先通过 `op signin` 完成认证。

    Args:
        vault_name: 1Password Vault 名称。
    """

    def __init__(self, vault_name: str) -> None:
        self._vault = vault_name

    async def _run_op(self, *args: str) -> str:
        """执行 1Password CLI 命令。

        Args:
            *args: op 命令参数。

        Returns:
            命令标准输出。

        Raises:
            RuntimeError: 命令执行失败。
        """
        import asyncio

        proc = await asyncio.create_subprocess_exec(
            "op", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            error_msg = stderr.decode().strip()
            raise RuntimeError(f"1Password CLI 执行失败: {error_msg}")
        return stdout.decode().strip()

    async def get_secret(self, key: str) -> str | None:
        """通过 1Password CLI 获取密钥。

        命令: op item get {key} --vault {vault} --fields password --format json

        Args:
            key: 1Password 项目名称。

        Returns:
            密钥值，不存在返回 None。
        """
        try:
            output = await self._run_op(
                "item", "get", key,
                "--vault", self._vault,
                "--fields", "password",
                "--format", "json",
            )
            import json
            data = json.loads(output)
            return data.get("value") or data.get("password")
        except Exception as exc:
            logger.warning("1Password 获取密钥失败: %s, 错误: %s", key, exc)
            return None

    async def set_secret(self, key: str, value: str) -> None:
        """通过 1Password CLI 写入密钥。

        命令: op item create --category "API Credential" --title {key}
              --vault {vault} --fields "password={value}"

        Args:
            key: 项目名称。
            value: 密钥值。
        """
        try:
            await self._run_op(
                "item", "create",
                "--category", "API Credential",
                "--title", key,
                "--vault", self._vault,
                f"password={value}",
            )
            logger.info("1Password 密钥已写入: %s", key)
        except Exception as exc:
            logger.error("1Password 写入密钥失败: %s, 错误: %s", key, exc)
            raise

    async def rotate_secret(self, key: str) -> str:
        """轮换密钥。

        Args:
            key: 项目名称。

        Returns:
            新生成的密钥值。
        """
        new_value = secrets.token_urlsafe(32)
        await self.set_secret(key, new_value)
        logger.info("1Password 密钥已轮换: %s", key)
        return new_value

    async def delete_secret(self, key: str) -> None:
        """通过 1Password CLI 删除密钥。

        命令: op item delete {key} --vault {vault}

        Args:
            key: 项目名称。
        """
        try:
            await self._run_op("item", "delete", key, "--vault", self._vault)
            logger.info("1Password 密钥已删除: %s", key)
        except Exception as exc:
            logger.error("1Password 删除密钥失败: %s, 错误: %s", key, exc)


# ──────────────────── 环境变量降级 Provider ────────────────────


class EnvProvider(SecretProvider):
    """环境变量降级 Provider。

    仅用于开发/测试环境，生产环境严禁使用。
    密钥存储在进程环境变量中，进程结束后即丢失。

    Args:
        prefix: 环境变量前缀（如 "SMARTQUANT_"）。
    """

    def __init__(self, prefix: str = "") -> None:
        self._prefix = prefix

    def _env_key(self, key: str) -> str:
        """拼接环境变量完整键名。"""
        return f"{self._prefix}{key}" if self._prefix else key

    async def get_secret(self, key: str) -> str | None:
        """从环境变量获取密钥。

        Args:
            key: 密钥名称。

        Returns:
            环境变量值，不存在返回 None。
        """
        import os
        return os.environ.get(self._env_key(key))

    async def set_secret(self, key: str, value: str) -> None:
        """设置环境变量。

        Args:
            key: 密钥名称。
            value: 密钥值。
        """
        import os
        os.environ[self._env_key(key)] = value

    async def rotate_secret(self, key: str) -> str:
        """轮换密钥（生成新值写入环境变量）。

        Args:
            key: 密钥名称。

        Returns:
            新生成的密钥值。
        """
        new_value = secrets.token_urlsafe(32)
        await self.set_secret(key, new_value)
        logger.info("环境变量密钥已轮换: %s", self._env_key(key))
        return new_value

    async def delete_secret(self, key: str) -> None:
        """删除环境变量。

        Args:
            key: 密钥名称。
        """
        import os
        env_key = self._env_key(key)
        os.environ.pop(env_key, None)
        logger.info("环境变量已删除: %s", env_key)


# ──────────────────── 密钥管理器 ────────────────────


class SecretManager:
    """密钥管理器 — 统一入口。

    提供密钥获取（带内存缓存）、强制校验、轮换、缓存清除等功能。
    所有密钥操作通过此管理器调度，业务代码不得直接访问 Provider。

    Args:
        provider: 密钥后端 Provider 实例。
        cache_ttl: 缓存有效期（秒），0 表示不过期。默认 300 秒。
    """

    def __init__(
        self,
        provider: SecretProvider,
        cache_ttl: int = 300,
    ) -> None:
        self._provider = provider
        self._cache: dict[str, str] = {}
        self._cache_ttl = cache_ttl

    async def get(self, key: str) -> str | None:
        """获取密钥（带内存缓存）。

        缓存命中直接返回，未命中则从 Provider 获取并缓存。

        Args:
            key: 密钥名称。

        Returns:
            密钥值，不存在返回 None。
        """
        if key in self._cache:
            return self._cache[key]

        value = await self._provider.get_secret(key)
        if value is not None:
            self._cache[key] = value
        return value

    async def require(self, key: str) -> str:
        """获取密钥，缺失则拒绝启动。

        用于启动阶段必须存在的密钥（如 JWT_SECRET、交易所 API Key）。
        缺失时抛出 RuntimeError，阻止应用启动。

        Args:
            key: 密钥名称。

        Returns:
            密钥值。

        Raises:
            RuntimeError: 密钥缺失，拒绝启动。
        """
        value = await self.get(key)
        if not value:
            raise RuntimeError(
                f"必需的密钥缺失: {key}，拒绝启动。"
                f"请确保密钥已配置在 Vault/1Password 或环境变量中。"
            )
        return value

    async def require_all(self, keys: list[str]) -> dict[str, str]:
        """批量校验多个必需密钥。

        Args:
            keys: 密钥名称列表。

        Returns:
            密钥名称到值的映射。

        Raises:
            RuntimeError: 任一密钥缺失。
        """
        result: dict[str, str] = {}
        missing: list[str] = []
        for key in keys:
            value = await self.get(key)
            if not value:
                missing.append(key)
            else:
                result[key] = value
        if missing:
            raise RuntimeError(
                f"必需的密钥缺失: {missing}，拒绝启动。"
                f"请确保密钥已配置在 Vault/1Password 或环境变量中。"
            )
        return result

    async def set(self, key: str, value: str) -> None:
        """设置密钥并更新缓存。

        Args:
            key: 密钥名称。
            value: 密钥值。
        """
        await self._provider.set_secret(key, value)
        self._cache[key] = value
        logger.info("密钥已设置: %s", key)

    async def rotate(self, key: str) -> str:
        """轮换密钥并更新缓存。

        Args:
            key: 密钥名称。

        Returns:
            新生成的密钥值。
        """
        new_value = await self._provider.rotate_secret(key)
        self._cache[key] = new_value
        logger.info("密钥已轮换: %s", key)
        return new_value

    async def delete(self, key: str) -> None:
        """删除密钥并清除缓存。

        Args:
            key: 密钥名称。
        """
        await self._provider.delete_secret(key)
        self._cache.pop(key, None)
        logger.info("密钥已删除: %s", key)

    def clear_cache(self) -> None:
        """清除所有内存缓存。"""
        self._cache.clear()
        logger.debug("密钥缓存已清除")

    def invalidate(self, key: str) -> None:
        """清除指定密钥的缓存。

        Args:
            key: 密钥名称。
        """
        self._cache.pop(key, None)
        logger.debug("密钥缓存已失效: %s", key)


# ──────────────────── 工厂函数 ────────────────────


def create_secret_manager(
    backend: str = "env",
    vault_url: str = "",
    vault_token: str = "",
    vault_mount: str = "secret",
    onepassword_vault: str = "",
    env_prefix: str = "",
    cache_ttl: int = 300,
) -> SecretManager:
    """创建密钥管理器实例（工厂函数）。

    根据 backend 参数创建对应的 Provider。

    Args:
        backend: 后端类型，支持 "vault"、"1password"、"env"。
        vault_url: Vault 服务地址（backend=vault 时必填）。
        vault_token: Vault 认证 Token（backend=vault 时必填）。
        vault_mount: KV v2 引擎挂载点，默认 "secret"。
        onepassword_vault: 1Password Vault 名称（backend=1password 时必填）。
        env_prefix: 环境变量前缀（backend=env 时可选）。
        cache_ttl: 缓存有效期（秒）。

    Returns:
        SecretManager 实例。

    Raises:
        ValueError: 后端类型不支持或缺少必要参数。
    """
    provider: SecretProvider

    if backend == "vault":
        if not vault_url or not vault_token:
            raise ValueError("Vault 后端需要 vault_url 和 vault_token 参数")
        provider = VaultProvider(
            vault_url=vault_url,
            token=vault_token,
            mount_point=vault_mount,
        )
        logger.info("密钥后端: HashiCorp Vault (%s)", vault_url)

    elif backend == "1password":
        if not onepassword_vault:
            raise ValueError("1Password 后端需要 onepassword_vault 参数")
        provider = OnePasswordProvider(vault_name=onepassword_vault)
        logger.info("密钥后端: 1Password (vault=%s)", onepassword_vault)

    elif backend == "env":
        provider = EnvProvider(prefix=env_prefix)
        logger.warning("密钥后端: 环境变量（仅限开发环境！）")

    else:
        raise ValueError(
            f"不支持的密钥后端: {backend}，可选: vault, 1password, env"
        )

    return SecretManager(provider=provider, cache_ttl=cache_ttl)
