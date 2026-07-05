"""PluginState 状态机单元测试"""

import pytest
from src.infrastructure.plugin_registry.state import (
    PluginState,
    PluginStateInfo,
    InvalidStateTransitionError,
)


class TestPluginState:
    """PluginState 枚举测试"""

    def test_all_states_defined(self):
        states = list(PluginState)
        assert PluginState.DISCOVERED in states
        assert PluginState.VALIDATED in states
        assert PluginState.ACTIVE in states
        assert PluginState.FAILED in states


class TestPluginStateInfo:
    """PluginStateInfo 状态机测试"""

    def test_initial_state(self):
        info = PluginStateInfo()
        assert info.state == PluginState.DISCOVERED
        assert info.error_message == ""

    def test_valid_transition(self):
        info = PluginStateInfo()
        info.transition(PluginState.VALIDATED)
        assert info.state == PluginState.VALIDATED

    def test_invalid_transition_raises(self):
        info = PluginStateInfo()
        # DISCOVERED → ACTIVE 非法
        with pytest.raises(InvalidStateTransitionError):
            info.transition(PluginState.ACTIVE)

    def test_invalid_transition_message(self):
        info = PluginStateInfo()
        with pytest.raises(InvalidStateTransitionError) as exc:
            info.transition(PluginState.ACTIVE)
        assert "DISCOVERED" in str(exc.value)
        assert "ACTIVE" in str(exc.value)

    def test_full_happy_path(self):
        """DISCOVERED → VALIDATED → LOADED → INITIALIZED → ACTIVE"""
        info = PluginStateInfo()
        info.transition(PluginState.VALIDATED)
        info.transition(PluginState.LOADED)
        info.transition(PluginState.INITIALIZED)
        info.transition(PluginState.ACTIVE)
        assert info.state == PluginState.ACTIVE

    def test_active_to_disabled(self):
        info = PluginStateInfo()
        for s in [PluginState.VALIDATED, PluginState.LOADED, PluginState.INITIALIZED, PluginState.ACTIVE]:
            if info.state != s:
                info.transition(s)
        info.transition(PluginState.DISABLED)
        assert info.state == PluginState.DISABLED

    def test_disabled_to_active(self):
        info = PluginStateInfo()
        for s in [PluginState.VALIDATED, PluginState.LOADED, PluginState.INITIALIZED, PluginState.ACTIVE, PluginState.DISABLED]:
            if info.state != s:
                info.transition(s)
        info.transition(PluginState.ACTIVE)
        assert info.state == PluginState.ACTIVE

    def test_any_to_failed(self):
        """VALIDATED 状态可以转到 FAILED"""
        info = PluginStateInfo()
        info.transition(PluginState.VALIDATED)
        info.transition_to_failed("something went wrong")
        assert info.state == PluginState.FAILED
        assert info.error_message == "something went wrong"

    def test_failed_can_retry(self):
        """FAILED → DISCOVERED (retry)"""
        info = PluginStateInfo()
        info.transition(PluginState.VALIDATED)
        info.transition_to_failed("error")
        info.transition(PluginState.DISCOVERED)
        assert info.state == PluginState.DISCOVERED

    def test_stopped_is_terminal(self):
        info = PluginStateInfo()
        info.transition(PluginState.VALIDATED)
        info.transition(PluginState.LOADED)
        info.transition(PluginState.STOPPED)
        with pytest.raises(InvalidStateTransitionError):
            info.transition(PluginState.ACTIVE)

    def test_state_history_recorded(self):
        info = PluginStateInfo()
        info.transition(PluginState.VALIDATED)
        info.transition_to_failed("test error")
        assert len(info.state_history) >= 2

    def test_failed_from_discovered(self):
        """DISCOVERED → FAILED is valid"""
        info = PluginStateInfo()
        info.transition_to_failed("discovery failed")
        assert info.state == PluginState.FAILED

    def test_disabled_to_stopped(self):
        info = PluginStateInfo()
        for s in [PluginState.VALIDATED, PluginState.LOADED, PluginState.INITIALIZED, PluginState.ACTIVE, PluginState.DISABLED]:
            if info.state != s:
                info.transition(s)
        info.transition(PluginState.STOPPED)
        assert info.state == PluginState.STOPPED
