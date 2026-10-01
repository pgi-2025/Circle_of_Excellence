"""Unit tests for the centralized scoring/tier config — no network needed."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from config import get_scholarship_tier, get_ambassador_level


def test_tier_boundaries():
    assert get_scholarship_tier(49) is None
    assert get_scholarship_tier(50)["discount_percent"] == 50
    assert get_scholarship_tier(79)["discount_percent"] == 50
    assert get_scholarship_tier(80)["discount_percent"] == 80
    assert get_scholarship_tier(99)["discount_percent"] == 80
    assert get_scholarship_tier(100)["discount_percent"] == 100


def test_ambassador_levels_progress():
    assert get_ambassador_level(0)["name"] == "Campus Starter"
    assert get_ambassador_level(299)["name"] == "Campus Starter"
    assert get_ambassador_level(300)["name"] == "Campus Promoter"
    assert get_ambassador_level(750)["name"] == "Campus Leader"
    assert get_ambassador_level(1500)["name"] == "Campus Champion"
    assert get_ambassador_level(5000)["name"] == "Campus Star"
