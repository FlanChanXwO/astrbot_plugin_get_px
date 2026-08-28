"""Tests for the /p command coin charging."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot_plugin_get_px.checkin import CheckinStore, CoinSpendResult
from astrbot_plugin_get_px.pixiv.search import SearchMixin


@pytest.mark.asyncio
async def test_spend_coins_deducts_and_returns_new_profile() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = CheckinStore(tmp)
        # 先创建成员并充值到足够余额
        await store.get_profile("10001")
        await store.update_checkin_member(
            user_id="10001", coins=100, affection=0.0, total_days=0, streak_days=0
        )
        result = await store.spend_coins(user_id="10001", cost=30)
        assert isinstance(result, CoinSpendResult)
        assert result.success is True
        assert result.profile.coins == 70
        profile = await store.get_profile("10001")
        assert profile.coins == 70


@pytest.mark.asyncio
async def test_spend_coins_insufficient_leaves_balance_untouched() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = CheckinStore(tmp)
        await store.get_profile("10001")
        await store.update_checkin_member(
            user_id="10001", coins=10, affection=0.0, total_days=0, streak_days=0
        )
        result = await store.spend_coins(user_id="10001", cost=30)
        assert result.success is False
        assert "金币不足，需要 30，当前只有 10。" in result.message
        profile = await store.get_profile("10001")
        assert profile.coins == 10


class _MinSearch(SearchMixin):
    def __init__(self):
        self.config = {}
        self.checkin_store = None
        self._p_charge_user_id = ""

    def _cfg_int(self, key, default, lo, hi):
        val = self.config.get(key, default)
        return int(val) if lo <= int(val) <= hi else default

    def _cfg_bool(self, key, default):
        return bool(self.config.get(key, default))


def test_p_unit_cost_defaults_to_20_and_zero_disables() -> None:
    mixin = _MinSearch()
    assert mixin._p_unit_cost() == 20
    mixin.config["p_coin_cost"] = 0
    assert mixin._p_unit_cost() == 0
    assert mixin._p_charging_active() is False


def test_p_charging_active_requires_checkin_store() -> None:
    mixin = _MinSearch()
    assert mixin._p_charging_active() is False  # checkin_store 为 None


async def test_p_balance_error_reports_shortfall() -> None:
    mixin = _MinSearch()
    mixin.checkin_store = AsyncMock()
    profile = AsyncMock()
    profile.coins = 25
    mixin.checkin_store.get_profile = AsyncMock(return_value=profile)
    error = await mixin._p_balance_error("10001", 3)
    assert "金币不足，需要 60，当前只有 25。" in error
    ok = await mixin._p_balance_error("10001", 1)
    assert ok == ""