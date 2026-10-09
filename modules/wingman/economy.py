"""Budgeted purchase transactions with explicit observation confirmation."""
from dataclasses import dataclass
from .engine import valid_money


@dataclass(frozen=True)
class Item:
    name: str
    price: int
    slot: str
    teams: tuple[str, ...] = ("T", "CT")


def plan_buy(*, money, team, owned, catalog, priority, reserve=0):
    """Prices/loadout supplied by a separately verified catalog, never guessed."""
    if not valid_money(money) or team not in ("T", "CT"):
        return ()
    if type(reserve) is not int or reserve < 0:
        raise ValueError("Invalid reserve")
    balance = max(0, money - reserve)
    occupied = set(owned)
    result = []
    for name in priority:
        item = catalog.get(name)
        if item is None:
            continue
        if type(item.price) is not int or item.price <= 0:
            raise ValueError("Invalid catalog price")
        if item.slot in occupied or team not in item.teams or item.price > balance:
            continue
        result.append(item)
        occupied.add(item.slot)
        balance -= item.price
    return tuple(result)


class PurchaseTransaction:
    """One command in flight; require both a new inventory and a new balance."""
    def __init__(self, items, *, timeout=2.0):
        self.items = list(items)
        self.timeout = timeout
        self.pending = None
        self.sent_at = None
        self.balance_before = None
        self.failed = False

    def next_item(self, *, now, money, owned, buy_allowed):
        if self.failed:
            return None
        if not buy_allowed or not valid_money(money):
            self.failed = True
            return None
        if self.pending is not None:
            confirmed = (self.pending.name in owned and
                         money == self.balance_before - self.pending.price)
            if confirmed:
                self.pending = None
            else:
                if now - self.sent_at >= self.timeout:
                    self.failed = True
                return None
        while self.items and self.items[0].name in owned:
            self.items.pop(0)
        if not self.items:
            return None
        item = self.items.pop(0)
        if item.price > money:
            self.failed = True
            return None
        self.pending, self.sent_at, self.balance_before = item, now, money
        return item


# One of each type; no automatic throwing. Fire grenades share a carry slot.
GRENADE_NAMES = frozenset(("weapon_smokegrenade", "weapon_hegrenade",
    "weapon_flashbang", "weapon_molotov", "weapon_incgrenade", "weapon_decoy"))
GRENADE_CATALOG = (
    Item("weapon_smokegrenade", 300, "smoke"),
    Item("weapon_hegrenade", 300, "he"),
    Item("weapon_flashbang", 200, "flash"),
    Item("weapon_molotov", 400, "fire", ("T",)),
    Item("weapon_incgrenade", 500, "fire", ("CT",)),
)


def plan_grenades(*, money, team, weapons, grenade_count=0):
    """Spend only the caller's remaining budget, respecting retained grenades."""
    if not valid_money(money) or team not in ("T", "CT"):
        return ()
    owned = tuple(weapons)
    count = max(sum(name in GRENADE_NAMES for name in owned), grenade_count)
    capacity = max(0, 4 - count)
    occupied = {item.slot for item in GRENADE_CATALOG if item.name in owned}
    catalog = {item.name:item for item in GRENADE_CATALOG}
    return plan_buy(money=money, team=team, owned=occupied, catalog=catalog,
                    priority=tuple(catalog))[:capacity]
