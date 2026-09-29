"""帮派战与据点争夺系统"""
import hashlib
import hmac
import time
from dataclasses import dataclass, field


@dataclass
class Stronghold:
    sid: str
    name: str
    owner: str = ""
    damage_log: dict[str, float] = field(default_factory=dict)  # guild -> damage
    hold_durations: dict[str, float] = field(default_factory=dict)  # guild -> 占领秒数
    occupy_time: float = 0.0
    buff_active: bool = False
    battle_end_time: float = 0.0
    defense_npcs: int = 0
    defense_towers: int = 0
    battle_active: bool = True
    _owner_since: float = 0.0


class SiegeSystem:
    # 归属权重: 伤害占比 + 占领时长占比
    DAMAGE_WEIGHT = 0.7
    DURATION_WEIGHT = 0.3
    # 收益: 每小时基准金币, 按占领时长比例发放
    GOLD_PER_HOUR = 1000.0
    # 复活/进场限制
    max_revives = 5
    revive_wait = 30.0       # 死亡后等待秒数
    enter_cooldown = 10.0    # 进场CD秒数

    def __init__(self):
        self.strongholds: dict[str, Stronghold] = {}
        self.occupation_log: list[dict] = []
        self._log_chain: str = "0" * 64  # 哈希链, 防篡改
        self.revive_counts: dict[str, int] = {}      # player -> 剩余复活次数
        self.death_timestamps: dict[str, float] = {}  # player -> 死亡时间
        self.last_enter: dict[str, float] = {}        # player -> 上次进场时间
        self.buffs: dict[str, set[str]] = {}          # player -> 生效buff据点集合
        self.guilds: dict[str, dict] = {}             # guild -> {"power": float, "members": set}
        self.match_history: dict[str, list[str]] = {}  # guild -> 最近对手
        self._rotation_pool: list[str] = []

    # ---------- bug1: 归属按伤害占比+占领时长加权 ----------
    def calculate_owner(self, sid: str) -> str:
        if sid not in self.strongholds:
            return ""
        s = self.strongholds[sid]
        if not s.damage_log and not s.hold_durations:
            return s.owner
        total_damage = sum(s.damage_log.values())
        total_hold = sum(s.hold_durations.values())
        guilds = set(s.damage_log) | set(s.hold_durations)
        best, best_score = s.owner, -1.0
        for g in guilds:
            dmg_ratio = s.damage_log.get(g, 0.0) / total_damage if total_damage else 0.0
            hold_ratio = s.hold_durations.get(g, 0.0) / total_hold if total_hold else 0.0
            score = self.DAMAGE_WEIGHT * dmg_ratio + self.DURATION_WEIGHT * hold_ratio
            if score > best_score:
                best, best_score = g, score
        return best

    def record_damage(self, sid: str, guild: str, amount: float, now: float = None):
        """造成伤害; 战斗冻结后无效"""
        s = self.strongholds[sid]
        if not s.battle_active:
            return False
        s.damage_log[guild] = s.damage_log.get(guild, 0.0) + amount
        return True

    def tick_occupation(self, sid: str, now: float):
        """累计当前占领者的占领时长"""
        s = self.strongholds[sid]
        if s.owner and s._owner_since:
            s.hold_durations[s.owner] = s.hold_durations.get(s.owner, 0.0) + max(0.0, now - s._owner_since)
            s._owner_since = now

    # ---------- bug2: 结束时间到立即冻结并结算 ----------
    def end_battle(self, sid: str, current_time: float):
        s = self.strongholds[sid]
        s.battle_end_time = current_time
        s.battle_active = False  # 冻结: 之后伤害/进出均无效
        self.tick_occupation(sid, current_time)
        new_owner = self.calculate_owner(sid)
        if new_owner and new_owner != s.owner:
            s.owner = new_owner
            self.record_occupation(sid, new_owner, current_time)

    # ---------- bug3: 收益按占领时长比例 ----------
    def get_rewards(self, sid: str, occupy_duration: float) -> dict:
        hours = max(0.0, occupy_duration) / 3600.0
        return {"gold": int(self.GOLD_PER_HOUR * hours)}

    # ---------- bug4: 防守方NPC援军+防御设施 ----------
    def spawn_defense_npc(self, sid: str, attackers: int = 0, defenders: int = 0):
        s = self.strongholds[sid]
        # 人数差距越大援军越多, 至少1个
        gap = max(0, attackers - defenders)
        reinforcements = max(1, gap // 2 + 1)
        s.defense_npcs += reinforcements
        s.defense_towers += 1
        return reinforcements

    # ---------- bug5: 不可篡改的占领日志(哈希链) ----------
    def record_occupation(self, sid: str, guild: str, time_: float):
        entry = {
            "seq": len(self.occupation_log),
            "sid": sid,
            "guild": guild,
            "time": time_,
            "prev_hash": self._log_chain,
        }
        payload = f"{entry['seq']}|{sid}|{guild}|{time_}|{self._log_chain}"
        entry["hash"] = hashlib.sha256(payload.encode()).hexdigest()
        self._log_chain = entry["hash"]
        self.occupation_log.append(entry)

    def verify_log(self) -> bool:
        """校验日志链完整性, 任何篡改都会被发现"""
        prev = "0" * 64
        for entry in self.occupation_log:
            payload = f"{entry['seq']}|{entry['sid']}|{entry['guild']}|{entry['time']}|{prev}"
            if not hmac.compare_digest(hashlib.sha256(payload.encode()).hexdigest(), entry["hash"]):
                return False
            prev = entry["hash"]
        return True

    # ---------- bug6: buff只对在线且在帮成员生效 ----------
    def apply_buff(self, sid: str, player: str, online: bool, in_guild: bool):
        s = self.strongholds[sid]
        if not (online and in_guild):
            self.buffs.get(player, set()).discard(sid)
            return False
        s.buff_active = True
        self.buffs.setdefault(player, set()).add(sid)
        return True

    def leave_guild(self, player: str):
        """退帮立即移除该玩家所有据点buff"""
        self.buffs.pop(player, None)

    # ---------- bug7: 复活次数限制+死亡等待 ----------
    def can_revive(self, player: str) -> bool:
        return self.revive_counts.get(player, self.max_revives) > 0

    def on_death(self, player: str, now: float = None):
        now = time.time() if now is None else now
        self.death_timestamps[player] = now
        remaining = self.revive_counts.get(player, self.max_revives)
        self.revive_counts[player] = max(0, remaining - 1)

    def revive_wait_remaining(self, player: str, now: float = None) -> float:
        now = time.time() if now is None else now
        died = self.death_timestamps.get(player)
        if died is None:
            return 0.0
        return max(0.0, self.revive_wait - (now - died))

    # ---------- bug8: 进场CD+复活等待 ----------
    def enter_battle(self, player: str, now: float = None):
        now = time.time() if now is None else now
        if not self.can_revive(player):
            return False
        if self.revive_wait_remaining(player, now) > 0:
            return False
        last = self.last_enter.get(player)
        if last is not None and now - last < self.enter_cooldown:
            return False
        self.last_enter[player] = now
        return True

    # ---------- 匹配: 战力区间+轮换池+最近对战记录 ----------
    def register_guild(self, guild: str, power: float, members=()):
        self.guilds[guild] = {"power": power, "members": set(members)}

    def _power_bracket(self, power: float) -> int:
        # 每1000战力一个区间
        return int(power // 1000)

    def matchmake(self, guild: str) -> str:
        if guild not in self.guilds:
            return ""
        me = self.guilds[guild]
        recent = set(self.match_history.get(guild, [])[-3:])
        candidates = [
            g for g in self.guilds
            if g != guild
            and self._power_bracket(self.guilds[g]["power"]) == self._power_bracket(me["power"])
            and g not in recent
        ]
        if not candidates:  # 区间内无可轮换对手则放宽最近对战限制
            candidates = [
                g for g in self.guilds
                if g != guild
                and self._power_bracket(self.guilds[g]["power"]) == self._power_bracket(me["power"])
            ]
        if not candidates:
            return ""
        # 轮换池: 优先选本周期未匹配过的
        pool = [g for g in self._rotation_pool if g in candidates]
        pick = pool[0] if pool else sorted(candidates)[0]
        if pick in self._rotation_pool:
            self._rotation_pool.remove(pick)
        self.match_history.setdefault(guild, []).append(pick)
        self.match_history.setdefault(pick, []).append(guild)
        return pick
