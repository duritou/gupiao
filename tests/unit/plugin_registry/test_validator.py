"""PluginValidator 单元测试"""

import pytest
from src.infrastructure.plugin_registry.manifest import PluginManifest, PluginType, PluginCapability
from src.infrastructure.plugin_registry.validator import PluginValidator, ValidationResult


def make_manifest(**overrides) -> PluginManifest:
    """快捷创建测试用 Manifest"""
    defaults = {
        "name": "test_plugin",
        "version": "1.0.0",
        "type": PluginType.DATASOURCE,
        "entry_point": "adapter:TestAdapter",
        "api_version": 1,
        "minimum_core": "1.0.0",
    }
    defaults.update(overrides)
    return PluginManifest(**defaults)


class TestValidatorHappyPath:
    """校验通过场景"""

    def test_valid_manifest_passes(self):
        v = PluginValidator(core_version="1.0.0", supported_api_versions=[1])
        m = make_manifest()
        result = v.validate(m)
        assert result.valid is True
        assert len(result.errors) == 0

    def test_valid_with_api_v2(self):
        v = PluginValidator(core_version="1.0.0", supported_api_versions=[1, 2])
        m = make_manifest(api_version=2)
        result = v.validate(m)
        assert result.valid is True

    def test_core_version_exact_match(self):
        v = PluginValidator(core_version="1.0.0", supported_api_versions=[1])
        m = make_manifest(minimum_core="1.0.0")
        result = v.validate(m)
        assert result.valid is True

    def test_core_version_newer_than_required(self):
        v = PluginValidator(core_version="2.0.0", supported_api_versions=[1])
        m = make_manifest(minimum_core="1.0.0")
        result = v.validate(m)
        assert result.valid is True


class TestValidatorErrors:
    """校验失败场景"""

    def test_empty_name(self):
        v = PluginValidator()
        m = make_manifest(name="")
        result = v.validate(m)
        assert result.valid is False
        assert any("name" in e.lower() for e in result.errors)

    def test_invalid_semver(self):
        v = PluginValidator()
        m = make_manifest(version="not-semver")
        result = v.validate(m)
        assert result.valid is False

    def test_unsupported_api_version(self):
        v = PluginValidator(supported_api_versions=[1])
        m = make_manifest(api_version=99)
        result = v.validate(m)
        assert result.valid is False
        assert any("api_version" in e.lower() for e in result.errors)

    def test_core_too_old(self):
        v = PluginValidator(core_version="1.0.0")
        m = make_manifest(minimum_core="2.0.0")
        result = v.validate(m)
        assert result.valid is False

    def test_core_exceeds_maximum(self):
        v = PluginValidator(core_version="2.0.0")
        m = make_manifest(maximum_core="1.x")
        result = v.validate(m)
        assert result.valid is False

    def test_invalid_entry_point_format(self):
        v = PluginValidator()
        m = make_manifest(entry_point="bad_format_no_colon")
        result = v.validate(m)
        assert result.valid is False

    def test_multiple_errors(self):
        v = PluginValidator(core_version="1.0.0")
        m = make_manifest(name="", version="bad", entry_point="bad")
        result = v.validate(m)
        assert result.valid is False
        assert len(result.errors) >= 2

    def test_dependency_warning(self):
        v = PluginValidator()
        m = make_manifest(dependencies=["badformat"])
        result = v.validate(m)
        # 依赖格式警告不应导致校验失败
        assert len(result.warnings) >= 1

    def test_maximum_core_x_format_matches(self):
        """'2.x' 格式匹配 2.0.0"""
        v = PluginValidator(core_version="2.1.0")
        m = make_manifest(maximum_core="2.x")
        result = v.validate(m)
        assert result.valid is True


class TestValidationResult:
    """ValidationResult 测试"""

    def test_default_valid(self):
        r = ValidationResult()
        assert r.valid is True
        assert r.errors == []

    def test_add_error(self):
        r = ValidationResult()
        r.add_error("bad")
        assert r.valid is False
        assert "bad" in r.errors

    def test_add_warning_does_not_invalidate(self):
        r = ValidationResult()
        r.add_warning("warning")
        assert r.valid is True
        assert "warning" in r.warnings
