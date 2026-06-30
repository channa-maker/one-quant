"""
ONE量化 - 模型注册表

MLflow 风格的模型版本管理，支持：
  - 模型注册与版本管理
  - 模型晋升（shadow → staging → production）
  - 模型回滚
  - 模型元数据查询

规范：
  - 模型文件存储在 models/ 目录下
  - 元数据持久化为 JSON
  - 线程安全（使用锁）
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 模型阶段常量
STAGE_SHADOW = "shadow"
STAGE_STAGING = "staging"
STAGE_PRODUCTION = "production"
STAGE_ARCHIVED = "archived"
VALID_STAGES = {STAGE_SHADOW, STAGE_STAGING, STAGE_PRODUCTION, STAGE_ARCHIVED}


class ModelRegistryError(Exception):
    """模型注册表错误基类。"""


class ModelNotFoundError(ModelRegistryError):
    """模型未找到。"""


class VersionNotFoundError(ModelRegistryError):
    """版本未找到。"""


class InvalidStageError(ModelRegistryError):
    """无效的模型阶段。"""


class ModelRegistry:
    """模型注册表（MLflow 风格）。

    职责：
      - 管理模型版本
      - 支持 shadow → staging → production 晋升链
      - 支持回滚到上一版本
      - 持久化模型文件和元数据
    """

    def __init__(self, storage_dir: str | Path | None = None) -> None:
        """初始化注册表。

        Args:
            storage_dir: 模型存储目录，None 使用默认路径。
        """
        if storage_dir is None:
            storage_dir = Path(__file__).parent.parent.parent.parent / "models"
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._metadata_file = self._storage_dir / "registry.json"
        self._lock = threading.Lock()
        self._registry: dict[str, dict[str, Any]] = self._load_metadata()

    def _load_metadata(self) -> dict[str, dict[str, Any]]:
        """从磁盘加载元数据。"""
        if self._metadata_file.exists():
            try:
                with open(self._metadata_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("加载模型注册表失败: %s，使用空注册表", e)
        return {}

    def _save_metadata(self) -> None:
        """持久化元数据到磁盘。"""
        try:
            with open(self._metadata_file, "w", encoding="utf-8") as f:
                json.dump(self._registry, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error("保存模型注册表失败: %s", e)
            raise ModelRegistryError(f"保存注册表失败: {e}") from e

    def _model_dir(self, model_name: str) -> Path:
        """获取模型存储目录。"""
        d = self._storage_dir / model_name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def register(
        self,
        model_name: str,
        version: str,
        model: Any,
        metrics: dict[str, float],
        description: str = "",
        tags: dict[str, str] | None = None,
    ) -> None:
        """注册模型版本。

        Args:
            model_name: 模型名称。
            version: 版本号。
            model: 模型对象（需支持 pickle 序列化）。
            metrics: 评估指标。
            description: 模型描述。
            tags: 附加标签。

        Raises:
            ModelRegistryError: 保存失败。
        """
        with self._lock:
            # 保存模型文件
            model_path = self._model_dir(model_name) / f"v{version}.pkl"
            try:
                import pickle

                with open(model_path, "wb") as f:
                    pickle.dump(model, f)
            except Exception as e:
                raise ModelRegistryError(f"保存模型文件失败: {e}") from e

            # 更新元数据
            if model_name not in self._registry:
                self._registry[model_name] = {"versions": {}, "production": None}

            self._registry[model_name]["versions"][version] = {
                "version": version,
                "stage": STAGE_SHADOW,
                "metrics": metrics,
                "description": description,
                "tags": tags or {},
                "path": str(model_path),
                "registered_at": time.time(),
                "registered_at_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
            }

            self._save_metadata()
            logger.info("模型 %s v%s 已注册（stage=%s）", model_name, version, STAGE_SHADOW)

    def get_model(self, model_name: str, version: str = "latest") -> Any:
        """获取模型。

        Args:
            model_name: 模型名称。
            version: 版本号，"latest" 获取最新版本。

        Returns:
            模型对象。

        Raises:
            ModelNotFoundError: 模型不存在。
            VersionNotFoundError: 版本不存在。
        """
        import pickle

        if model_name not in self._registry:
            raise ModelNotFoundError(f"模型 '{model_name}' 不存在")

        versions = self._registry[model_name]["versions"]
        if not versions:
            raise VersionNotFoundError(f"模型 '{model_name}' 无任何版本")

        if version == "latest":
            # 按注册时间排序取最新
            version = max(versions.keys(), key=lambda v: versions[v].get("registered_at", 0))
        elif version not in versions:
            raise VersionNotFoundError(f"模型 '{model_name}' v{version} 不存在")

        meta = versions[version]
        model_path = meta["path"]

        if not os.path.exists(model_path):
            raise ModelNotFoundError(f"模型文件不存在: {model_path}")

        try:
            with open(model_path, "rb") as f:
                return pickle.load(f)
        except Exception as e:
            raise ModelRegistryError(f"加载模型失败: {e}") from e

    def get_model_info(self, model_name: str, version: str = "latest") -> dict[str, Any]:
        """获取模型元数据。

        Args:
            model_name: 模型名称。
            version: 版本号，"latest" 获取最新版本。

        Returns:
            模型元数据字典。

        Raises:
            ModelNotFoundError: 模型不存在。
            VersionNotFoundError: 版本不存在。
        """
        if model_name not in self._registry:
            raise ModelNotFoundError(f"模型 '{model_name}' 不存在")

        versions = self._registry[model_name]["versions"]
        if not versions:
            raise VersionNotFoundError(f"模型 '{model_name}' 无任何版本")

        if version == "latest":
            version = max(versions.keys(), key=lambda v: versions[v].get("registered_at", 0))
        elif version not in versions:
            raise VersionNotFoundError(f"模型 '{model_name}' v{version} 不存在")

        return versions[version]

    def list_models(self) -> list[dict[str, Any]]:
        """列出所有模型。

        Returns:
            模型信息列表，每个包含 name、latest_version、production_version、version_count。
        """
        result: list[dict[str, Any]] = []
        for name, data in self._registry.items():
            versions = data.get("versions", {})
            prod_version = data.get("production")

            latest_version = None
            if versions:
                latest_version = max(
                    versions.keys(), key=lambda v: versions[v].get("registered_at", 0)
                )

            result.append({
                "name": name,
                "latest_version": latest_version,
                "production_version": prod_version,
                "version_count": len(versions),
            })

        return result

    def list_versions(self, model_name: str) -> list[dict[str, Any]]:
        """列出模型的所有版本。

        Args:
            model_name: 模型名称。

        Returns:
            版本信息列表。

        Raises:
            ModelNotFoundError: 模型不存在。
        """
        if model_name not in self._registry:
            raise ModelNotFoundError(f"模型 '{model_name}' 不存在")

        versions = self._registry[model_name].get("versions", {})
        return list(versions.values())

    def promote(self, model_name: str, version: str, stage: str) -> None:
        """模型晋升。

        晋升链：shadow → staging → production
        当一个版本晋升到 production 时，原 production 版本自动降级为 archived。

        Args:
            model_name: 模型名称。
            version: 版本号。
            stage: 目标阶段。

        Raises:
            ModelNotFoundError: 模型不存在。
            VersionNotFoundError: 版本不存在。
            InvalidStageError: 无效的阶段。
        """
        if stage not in VALID_STAGES:
            raise InvalidStageError(
                f"无效的阶段: {stage}，有效值: {', '.join(sorted(VALID_STAGES))}"
            )

        with self._lock:
            if model_name not in self._registry:
                raise ModelNotFoundError(f"模型 '{model_name}' 不存在")

            versions = self._registry[model_name]["versions"]
            if version not in versions:
                raise VersionNotFoundError(f"模型 '{model_name}' v{version} 不存在")

            # 如果晋升到 production，将原 production 版本降级
            if stage == STAGE_PRODUCTION:
                old_prod = self._registry[model_name].get("production")
                if old_prod and old_prod in versions:
                    versions[old_prod]["stage"] = STAGE_ARCHIVED
                    logger.info(
                        "模型 %s v%s 从 production 降级为 archived",
                        model_name,
                        old_prod,
                    )
                self._registry[model_name]["production"] = version

            versions[version]["stage"] = stage
            self._save_metadata()

            logger.info("模型 %s v%s 晋升到 %s", model_name, version, stage)

    def rollback(self, model_name: str) -> str:
        """回滚到上一版本。

        将当前 production 版本降级为 archived，
        将最近的 archived 版本重新晋升为 production。

        Args:
            model_name: 模型名称。

        Returns:
            回滚到的版本号。

        Raises:
            ModelNotFoundError: 模型不存在。
            ModelRegistryError: 无可回滚的版本。
        """
        with self._lock:
            if model_name not in self._registry:
                raise ModelNotFoundError(f"模型 '{model_name}' 不存在")

            versions = self._registry[model_name]["versions"]

            # 找到最近的 archived 版本
            archived = [
                v for v, meta in versions.items() if meta["stage"] == STAGE_ARCHIVED
            ]
            if not archived:
                raise ModelRegistryError(f"模型 '{model_name}' 无可回滚的 archived 版本")

            # 按注册时间排序，取最近的
            archived.sort(key=lambda v: versions[v].get("registered_at", 0), reverse=True)
            rollback_version = archived[0]

            # 降级当前 production
            current_prod = self._registry[model_name].get("production")
            if current_prod and current_prod in versions:
                versions[current_prod]["stage"] = STAGE_ARCHIVED

            # 晋升回滚版本
            versions[rollback_version]["stage"] = STAGE_PRODUCTION
            self._registry[model_name]["production"] = rollback_version

            self._save_metadata()
            logger.info("模型 %s 回滚到 v%s", model_name, rollback_version)

            return rollback_version

    def delete_version(self, model_name: str, version: str) -> None:
        """删除模型版本。

        Args:
            model_name: 模型名称。
            version: 版本号。

        Raises:
            ModelNotFoundError: 模型不存在。
            VersionNotFoundError: 版本不存在。
        """
        with self._lock:
            if model_name not in self._registry:
                raise ModelNotFoundError(f"模型 '{model_name}' 不存在")

            versions = self._registry[model_name]["versions"]
            if version not in versions:
                raise VersionNotFoundError(f"模型 '{model_name}' v{version} 不存在")

            # 删除模型文件
            model_path = Path(versions[version]["path"])
            if model_path.exists():
                model_path.unlink()

            # 如果删除的是 production 版本，清除 production 标记
            if self._registry[model_name].get("production") == version:
                self._registry[model_name]["production"] = None

            del versions[version]
            self._save_metadata()
            logger.info("模型 %s v%s 已删除", model_name, version)
