"""帮派战与据点争夺系统 - 含8个bug"""
from dataclasses import dataclass, field

@dataclass
class Stronghold:
    sid: str
    name: str
    owner: str = ""
    damage_log: dict[str, float] = field(default_factory=dict)  # guild -> damage
    occupy_time: float = 0.0
    buff_active: bool = False
    battle_end_time: float = 0.0
    defense_npcs: int = 0

class SiegeSystem:
    def __init__(self):
        self.strongholds: dict[str, Stronghold] = {}
        self.occupation_log: list = []  # bug: 无日志
        self.revive_counts: dict[str, int] = {}  # player -> 剩余复活次数
        self.max_revives = 5

    def calculate_owner(self, sid: str) -> str:
        # bug1: 只看最后一击
        if sid not in self.strongholds:
            return ""
        s = self.strongholds[sid]
        if not s.damage_log:
            return s.owner
        return max(s.damage_log, key=s.damage_log.get)

    def end_battle(self, sid: str, current_time: float):
        # bug2: 结束不冻结
        s = self.strongholds[sid]
        s.battle_end_time = current_time
        # 还能继续打

    def get_rewards(self, sid: str, occupy_duration: float) -> dict:
        # bug3: 不按时长比例
        return {"gold": 1000}

    def spawn_defense_npc(self, sid: str):
        # bug4: 无援军
        pass

    def record_occupation(self, sid: str, guild: str, time: float):
        # bug5: 无日志
        pass

    def apply_buff(self, sid: str, player: str, online: bool, in_guild: bool):
        # bug6: 离线/退帮也享受buff
        s = self.strongholds[sid]
        s.buff_active = True

    def can_revive(self, player: str) -> bool:
        # bug7: 无复活限制
        return True

    def enter_battle(self, player: str):
        # bug8: 无进场CD
        pass
