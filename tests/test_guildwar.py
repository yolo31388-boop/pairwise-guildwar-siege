"""帮派战与据点争夺系统 - 红态测试"""
import pytest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from guildwar.siege import SiegeSystem, Stronghold

class TestOwnerByDamage:
    def test_owner_by_total_damage_not_last_hit(self):
        ss = SiegeSystem()
        ss.strongholds["s1"] = Stronghold("s1", "fort")
        ss.strongholds["s1"].damage_log = {"A": 900, "B": 100}
        # A打了90%应该归属A
        assert ss.calculate_owner("s1") == "A"  # bug1: 可能看最后一击

class TestBattleFreeze:
    def test_battle_freezes_at_end(self):
        ss = SiegeSystem()
        ss.strongholds["s1"] = Stronghold("s1", "fort")
        ss.end_battle("s1", 100.0)
        # 结束后应该不能再造成伤害
        # 需要实现battle_active状态
        assert hasattr(ss.strongholds["s1"], 'battle_active')
        assert ss.strongholds["s1"].battle_active == False  # bug2: 没冻结

class TestRewardScaling:
    def test_rewards_scale_with_duration(self):
        ss = SiegeSystem()
        r_short = ss.get_rewards("s1", 60)  # 1分钟
        r_long = ss.get_rewards("s1", 3600)  # 1小时
        assert r_long["gold"] > r_short["gold"]  # bug3: 都是1000

class TestDefenseNpc:
    def test_defense_npcs_spawn(self):
        ss = SiegeSystem()
        ss.strongholds["s1"] = Stronghold("s1", "fort", defense_npcs=0)
        ss.spawn_defense_npc("s1")
        assert ss.strongholds["s1"].defense_npcs > 0  # bug4: 还是0

class TestOccupationLog:
    def test_occupation_recorded(self):
        ss = SiegeSystem()
        ss.strongholds["s1"] = Stronghold("s1", "fort")
        ss.record_occupation("s1", "A", 100.0)
        assert len(ss.occupation_log) > 0  # bug5: 空

class TestBuffRequiresOnline:
    def test_buff_only_for_online_members(self):
        ss = SiegeSystem()
        ss.strongholds["s1"] = Stronghold("s1", "fort", owner="A")
        # 离线玩家不应享受buff
        # 需要实现：apply_buff检查online和in_guild
        result = ss.apply_buff("s1", "p1", online=False, in_guild=True)
        assert result == False  # bug6: 离线也给buff

class TestReviveLimit:
    def test_revive_has_limit(self):
        ss = SiegeSystem()
        ss.revive_counts["p1"] = 0
        assert ss.can_revive("p1") == False  # bug7: 返回True
        ss.revive_counts["p1"] = 3
        assert ss.can_revive("p1") == True
