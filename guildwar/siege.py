"""帮派战与据点争夺系统"""
import hashlib
import time
from dataclasses import dataclass, field


@dataclass
class Stronghold:
    sid: str
    name: str
    owner: str = ""
    damage_log: dict[str, float] = field(default_factory=dict)  # guild -> damage
    occupy_duration: dict[str, float] = field(default_factory=dict)  # guild -> 战斗内占领时长
    occupy_time: float = 0.0
    buff_active: bool = False
    battle_active: bool = True
    battle_end_time: float = 0.0
    defense_npcs: int = 0
    defense_structures: int = 0
    buff_players: set = field(default_factory=set)


@dataclass(frozen=True)
class OccupationRecord:
    """不可篡改的占领日志条目：冻结 + 哈希链"""
    sid: str
    guild: str
    time: float
    prev_hash: str
    hash: str


class SiegeSystem:
    DAMAGE_WEIGHT = 0.7      # 伤害占比权重
    DURATION_WEIGHT = 0.3    # 占领时长权重
    GOLD_PER_HOUR = 1000     # 满一小时收益
    DEFENSE_NPC_BATCH = 5    # 每批NPC援军
    DEFENSE_STRUCTURE_BATCH = 2  # 每批防御设施
    RESPAWN_WAIT = 30.0      # 死亡后等待时间(秒)
    ENTER_CD = 60.0          # 进场冷却(秒)
    RECENT_MATCH_MEMORY = 3  # 最近对战记录长度

    def __init__(self):
        self.strongholds: dict[str, Stronghold] = {}
        self.occupation_log: list[OccupationRecord] = []
        self.revive_counts: dict[str, int] = {}  # player -> 剩余复活次数
        self.max_revives = 5
        self.last_enter: dict[str, float] = {}   # player -> 上次进场时间
        self.last_death: dict[str, float] = {}   # player -> 上次死亡时间
        self.recent_opponents: dict[str, list] = {}  # guild -> 最近对手
        self.match_round = 0

    # ---- bug1: 占领按伤害占比+持续时间加权，而非最后一击 ----
    def calculate_owner(self, sid: str) -> str:
        if sid not in self.strongholds:
            return ""
        s = self.strongholds[sid]
        if not s.damage_log:
            return s.owner
        total_damage = sum(s.damage_log.values())
        total_duration = sum(s.occupy_duration.values())
        best_guild, best_score = "", -1.0
        for guild, damage in s.damage_log.items():
            damage_share = damage / total_damage if total_damage > 0 else 0.0
            duration_share = (s.occupy_duration.get(guild, 0.0) / total_duration
                              if total_duration > 0 else 0.0)
            score = self.DAMAGE_WEIGHT * damage_share + self.DURATION_WEIGHT * duration_share
            if score > best_score:
                best_guild, best_score = guild, score
        return best_guild

    def deal_damage(self, sid: str, guild: str, amount: float, current_time: float) -> bool:
        """冻结后或超过结束时间的伤害一律无效"""
        s = self.strongholds[sid]
        if not s.battle_active:
            return False
        if s.battle_end_time and current_time >= s.battle_end_time:
            return False
        s.damage_log[guild] = s.damage_log.get(guild, 0.0) + amount
        return True

    # ---- bug2: 结束时间到立即冻结状态并结算 ----
    def end_battle(self, sid: str, current_time: float):
        s = self.strongholds[sid]
        s.battle_end_time = current_time
        s.battle_active = False  # 冻结，之后伤害无效
        new_owner = self.calculate_owner(sid)
        if new_owner and new_owner != s.owner:
            s.owner = new_owner
            s.occupy_time = current_time
            self.record_occupation(sid, new_owner, current_time)

    # ---- bug3: 收益按占领时长比例发放 ----
    def get_rewards(self, sid: str, occupy_duration: float) -> dict:
        gold = int(self.GOLD_PER_HOUR * max(0.0, occupy_duration) / 3600.0)
        return {"gold": gold}

    # ---- bug4: 防守方NPC援军和防御设施 ----
    def spawn_defense_npc(self, sid: str, attacker_count: int = 0):
        s = self.strongholds[sid]
        # 进攻方人越多，援军越多，缓解人数碾压
        batches = 1 + max(0, attacker_count) // 10
        s.defense_npcs += self.DEFENSE_NPC_BATCH * batches
        s.defense_structures += self.DEFENSE_STRUCTURE_BATCH

    # ---- bug5: 不可篡改的占领日志（冻结记录 + 哈希链） ----
    def record_occupation(self, sid: str, guild: str, time: float):
        prev_hash = self.occupation_log[-1].hash if self.occupation_log else "GENESIS"
        digest = hashlib.sha256(f"{sid}|{guild}|{time}|{prev_hash}".encode()).hexdigest()
        self.occupation_log.append(OccupationRecord(sid, guild, time, prev_hash, digest))

    def verify_occupation_log(self) -> bool:
        prev_hash = "GENESIS"
        for rec in self.occupation_log:
            if rec.prev_hash != prev_hash:
                return False
            expect = hashlib.sha256(
                f"{rec.sid}|{rec.guild}|{rec.time}|{rec.prev_hash}".encode()).hexdigest()
            if rec.hash != expect:
                return False
            prev_hash = rec.hash
        return True

    # ---- bug6: buff只对在线且在帮成员生效 ----
    def apply_buff(self, sid: str, player: str, online: bool, in_guild: bool) -> bool:
        if not (online and in_guild):
            return False
        s = self.strongholds[sid]
        s.buff_active = True
        s.buff_players.add(player)
        return True

    def leave_guild(self, player: str):
        """退帮立即移除所有据点buff"""
        for s in self.strongholds.values():
            s.buff_players.discard(player)

    def has_buff(self, sid: str, player: str) -> bool:
        return player in self.strongholds[sid].buff_players

    # ---- bug7: 复活次数限制 + 死亡等待时间 ----
    def can_revive(self, player: str) -> bool:
        return self.revive_counts.get(player, self.max_revives) > 0

    def on_player_death(self, player: str, current_time: float):
        self.revive_counts[player] = self.revive_counts.get(player, self.max_revives) - 1
        self.last_death[player] = current_time

    def can_respawn(self, player: str, current_time: float) -> bool:
        if not self.can_revive(player):
            return False
        died_at = self.last_death.get(player)
        if died_at is None:
            return True
        return current_time - died_at >= self.RESPAWN_WAIT

    # ---- bug8: 进场CD，不能无限进出车轮战 ----
    def enter_battle(self, player: str, current_time: float = None) -> bool:
        if current_time is None:
            current_time = time.time()
        last = self.last_enter.get(player)
        if last is not None and current_time - last < self.ENTER_CD:
            return False
        self.last_enter[player] = current_time
        return True

    # ---- 匹配：战力区间 + 轮换池 + 最近对战记录 ----
    def match_guilds(self, guild_powers: dict[str, int], band: float = 0.2) -> list[tuple]:
        """按战力区间配对，避开最近交手过的对手，并轮换起始点"""
        guilds = sorted(guild_powers, key=guild_powers.get)
        pairs, used = [], set()
        self.match_round += 1
        # 轮换池：每轮从不同起点开始，避免永远是第1打第2
        offset = self.match_round % max(1, len(guilds))
        order = guilds[offset:] + guilds[:offset]
        for g in order:
            if g in used:
                continue
            power = guild_powers[g]
            recent = set(self.recent_opponents.get(g, []))
            best = None
            for other in order:
                if other == g or other in used:
                    continue
                if abs(guild_powers[other] - power) > power * band:
                    continue  # 超出战力区间
                if other in recent:
                    continue  # 最近打过，跳过
                best = other
                break
            if best is None:  # 区间内都被回避则放宽最近对战限制
                for other in order:
                    if other != g and other not in used and \
                            abs(guild_powers[other] - power) <= power * band:
                        best = other
                        break
            if best is not None:
                used.add(g)
                used.add(best)
                pairs.append((g, best))
                for a, b in ((g, best), (best, g)):
                    hist = self.recent_opponents.setdefault(a, [])
                    hist.append(b)
                    del hist[:-self.RECENT_MATCH_MEMORY]
        return pairs
