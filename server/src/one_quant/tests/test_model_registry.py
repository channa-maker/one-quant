"""
ONE量化 - 模型注册表测试

覆盖：注册、查询、晋升、回滚、删除、持久化。
"""

import tempfile
from pathlib import Path

import pytest

from one_quant.ml.model_registry import (
    STAGE_ARCHIVED,
    STAGE_PRODUCTION,
    STAGE_SHADOW,
    STAGE_STAGING,
    InvalidStageError,
    ModelNotFoundError,
    ModelRegistry,
    ModelRegistryError,
    VersionNotFoundError,
)


@pytest.fixture
def tmp_registry(tmp_path):
    """提供临时目录的模型注册表"""
    return ModelRegistry(storage_dir=str(tmp_path / "models"))


@pytest.fixture
def dummy_model():
    """简单可 pickle 的模型对象"""
    return {"type": "dummy", "weights": [1.0, 2.0, 3.0]}


class TestModelRegistryInit:
    """注册表初始化"""

    def test_default_storage_dir(self):
        """默认存储目录"""
        ModelRegistry.__new__(ModelRegistry)
        # Just check the class exists and can be instantiated with a path
        with tempfile.TemporaryDirectory() as td:
            r = ModelRegistry(storage_dir=td)
            assert r._storage_dir.exists()

    def test_custom_storage_dir(self, tmp_path):
        custom = tmp_path / "custom" / "models"
        ModelRegistry(storage_dir=str(custom))
        assert custom.exists()


class TestModelRegistration:
    """模型注册"""

    def test_register_and_get(self, tmp_registry, dummy_model):
        tmp_registry.register("test_model", "1", dummy_model, {"accuracy": 0.9})
        loaded = tmp_registry.get_model("test_model", "1")
        assert loaded == dummy_model

    def test_register_default_stage(self, tmp_registry, dummy_model):
        tmp_registry.register("test_model", "1", dummy_model, {"accuracy": 0.9})
        info = tmp_registry.get_model_info("test_model", "1")
        assert info["stage"] == STAGE_SHADOW

    def test_register_metadata(self, tmp_registry, dummy_model):
        tmp_registry.register(
            "test_model",
            "1",
            dummy_model,
            metrics={"accuracy": 0.9, "f1": 0.85},
            description="测试模型",
            tags={"symbol": "BTC/USDT"},
        )
        info = tmp_registry.get_model_info("test_model", "1")
        assert info["description"] == "测试模型"
        assert info["tags"]["symbol"] == "BTC/USDT"
        assert info["metrics"]["accuracy"] == 0.9

    def test_register_multiple_versions(self, tmp_registry, dummy_model):
        tmp_registry.register("test_model", "1", dummy_model, {"accuracy": 0.8})
        tmp_registry.register("test_model", "2", dummy_model, {"accuracy": 0.9})
        versions = tmp_registry.list_versions("test_model")
        assert len(versions) == 2

    def test_get_latest_version(self, tmp_registry, dummy_model):
        tmp_registry.register("test_model", "1", dummy_model, {"accuracy": 0.8})
        tmp_registry.register("test_model", "2", dummy_model, {"accuracy": 0.9})
        loaded = tmp_registry.get_model("test_model", "latest")
        assert loaded == dummy_model


class TestModelRetrieval:
    """模型查询"""

    def test_get_nonexistent_model(self, tmp_registry):
        with pytest.raises(ModelNotFoundError):
            tmp_registry.get_model("nonexistent")

    def test_get_nonexistent_version(self, tmp_registry, dummy_model):
        tmp_registry.register("test_model", "1", dummy_model, {"accuracy": 0.9})
        with pytest.raises(VersionNotFoundError):
            tmp_registry.get_model("test_model", "999")

    def test_get_info_nonexistent_model(self, tmp_registry):
        with pytest.raises(ModelNotFoundError):
            tmp_registry.get_model_info("nonexistent")

    def test_get_info_nonexistent_version(self, tmp_registry, dummy_model):
        tmp_registry.register("test_model", "1", dummy_model, {"accuracy": 0.9})
        with pytest.raises(VersionNotFoundError):
            tmp_registry.get_model_info("test_model", "999")

    def test_list_models(self, tmp_registry, dummy_model):
        tmp_registry.register("model_a", "1", dummy_model, {"accuracy": 0.8})
        tmp_registry.register("model_b", "1", dummy_model, {"accuracy": 0.9})
        models = tmp_registry.list_models()
        assert len(models) == 2
        names = {m["name"] for m in models}
        assert "model_a" in names
        assert "model_b" in names

    def test_list_models_empty(self, tmp_registry):
        assert tmp_registry.list_models() == []

    def test_list_versions_nonexistent(self, tmp_registry):
        with pytest.raises(ModelNotFoundError):
            tmp_registry.list_versions("nonexistent")


class TestModelPromotion:
    """模型晋升"""

    def test_promote_to_staging(self, tmp_registry, dummy_model):
        tmp_registry.register("test_model", "1", dummy_model, {"accuracy": 0.9})
        tmp_registry.promote("test_model", "1", STAGE_STAGING)
        info = tmp_registry.get_model_info("test_model", "1")
        assert info["stage"] == STAGE_STAGING

    def test_promote_to_production(self, tmp_registry, dummy_model):
        tmp_registry.register("test_model", "1", dummy_model, {"accuracy": 0.9})
        tmp_registry.promote("test_model", "1", STAGE_PRODUCTION)
        info = tmp_registry.get_model_info("test_model", "1")
        assert info["stage"] == STAGE_PRODUCTION

    def test_promote_replaces_production(self, tmp_registry, dummy_model):
        tmp_registry.register("test_model", "1", dummy_model, {"accuracy": 0.8})
        tmp_registry.register("test_model", "2", dummy_model, {"accuracy": 0.9})
        tmp_registry.promote("test_model", "1", STAGE_PRODUCTION)
        tmp_registry.promote("test_model", "2", STAGE_PRODUCTION)
        # v1 should be archived
        info1 = tmp_registry.get_model_info("test_model", "1")
        assert info1["stage"] == STAGE_ARCHIVED
        info2 = tmp_registry.get_model_info("test_model", "2")
        assert info2["stage"] == STAGE_PRODUCTION

    def test_promote_invalid_stage(self, tmp_registry, dummy_model):
        tmp_registry.register("test_model", "1", dummy_model, {"accuracy": 0.9})
        with pytest.raises(InvalidStageError):
            tmp_registry.promote("test_model", "1", "invalid_stage")

    def test_promote_nonexistent_model(self, tmp_registry):
        with pytest.raises(ModelNotFoundError):
            tmp_registry.promote("nonexistent", "1", STAGE_STAGING)

    def test_promote_nonexistent_version(self, tmp_registry, dummy_model):
        tmp_registry.register("test_model", "1", dummy_model, {"accuracy": 0.9})
        with pytest.raises(VersionNotFoundError):
            tmp_registry.promote("test_model", "999", STAGE_STAGING)


class TestModelRollback:
    """模型回滚"""

    def test_rollback(self, tmp_registry, dummy_model):
        tmp_registry.register("test_model", "1", dummy_model, {"accuracy": 0.8})
        tmp_registry.register("test_model", "2", dummy_model, {"accuracy": 0.9})
        tmp_registry.promote("test_model", "1", STAGE_PRODUCTION)
        tmp_registry.promote("test_model", "2", STAGE_PRODUCTION)
        # v1 is now archived, v2 is production
        rolled = tmp_registry.rollback("test_model")
        assert rolled == "1"
        info1 = tmp_registry.get_model_info("test_model", "1")
        assert info1["stage"] == STAGE_PRODUCTION

    def test_rollback_no_archived(self, tmp_registry, dummy_model):
        tmp_registry.register("test_model", "1", dummy_model, {"accuracy": 0.9})
        tmp_registry.promote("test_model", "1", STAGE_PRODUCTION)
        with pytest.raises(ModelRegistryError, match="无可回滚"):
            tmp_registry.rollback("test_model")

    def test_rollback_nonexistent_model(self, tmp_registry):
        with pytest.raises(ModelNotFoundError):
            tmp_registry.rollback("nonexistent")


class TestModelDeletion:
    """模型删除"""

    def test_delete_version(self, tmp_registry, dummy_model):
        tmp_registry.register("test_model", "1", dummy_model, {"accuracy": 0.9})
        tmp_registry.delete_version("test_model", "1")
        with pytest.raises(VersionNotFoundError):
            tmp_registry.get_model("test_model", "1")

    def test_delete_nonexistent_model(self, tmp_registry):
        with pytest.raises(ModelNotFoundError):
            tmp_registry.delete_version("nonexistent", "1")

    def test_delete_nonexistent_version(self, tmp_registry, dummy_model):
        tmp_registry.register("test_model", "1", dummy_model, {"accuracy": 0.9})
        with pytest.raises(VersionNotFoundError):
            tmp_registry.delete_version("test_model", "999")

    def test_delete_production_version(self, tmp_registry, dummy_model):
        tmp_registry.register("test_model", "1", dummy_model, {"accuracy": 0.9})
        tmp_registry.promote("test_model", "1", STAGE_PRODUCTION)
        tmp_registry.delete_version("test_model", "1")
        models = tmp_registry.list_models()
        assert len(models) == 1
        assert models[0]["production_version"] is None


class TestModelPersistence:
    """持久化"""

    def test_metadata_persisted(self, tmp_path, dummy_model):
        storage = str(tmp_path / "models")
        reg1 = ModelRegistry(storage_dir=storage)
        reg1.register("test_model", "1", dummy_model, {"accuracy": 0.9})
        # Create new registry from same dir
        reg2 = ModelRegistry(storage_dir=storage)
        info = reg2.get_model_info("test_model", "1")
        assert info["metrics"]["accuracy"] == 0.9

    def test_corrupted_metadata_file(self, tmp_path, dummy_model):
        storage = str(tmp_path / "models")
        ModelRegistry(storage_dir=storage)
        # Write corrupted JSON
        meta_file = Path(storage) / "registry.json"
        meta_file.write_text("not valid json{{{")
        # Should not crash, falls back to empty registry
        reg2 = ModelRegistry(storage_dir=storage)
        assert reg2.list_models() == []
