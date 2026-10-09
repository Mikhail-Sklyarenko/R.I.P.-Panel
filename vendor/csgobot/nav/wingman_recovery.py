"""Bounded input recovery: never create a player pose from an input command."""

PRIMARY = frozenset('ak47 m4a1 m4a1_silencer awp ssg08 galilar famas aug sg556 '
                    'mp9 mac10 p90 mp7 mp5sd ump45 bizon nova xm1014 mag7 sawedoff '
                    'm249 negev'.split())
PISTOLS = frozenset('glock hkp2000 usp_silencer p250 tec9 fiveseven cz75a deagle '
                   'revolver elite'.split())


class WeaponSelection:
    def __init__(self):self.reset()

    def reset(self):
        self.attempts=0
        self.next_at=0.
        self.wrong_weapon=None

    def choose(self,snapshot,*,now,allowed):
        if not allowed:return None
        active=snapshot.active_weapon.removeprefix('weapon_')
        if active in PRIMARY or active in PISTOLS:
            self.reset()
            return None
        # No input until telemetry identifies the selected item and inventory.
        if not active:return None
        if active!=self.wrong_weapon:
            self.reset();self.wrong_weapon=active
        owned={w.removeprefix('weapon_') for w in snapshot.weapons}
        slot='1' if owned & PRIMARY else '2' if owned & PISTOLS else None
        if slot is None or self.attempts>=3 or now<self.next_at:return None
        self.attempts+=1;self.next_at=now+.65
        return slot
