"""Legal actions available to a combatant each round."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .state import CardType, GameState


@dataclass(frozen=True)
class Action:
    """Play hand[card_idx] at enemies[target_idx] (or self/None), or pass."""
    card_idx: Optional[int]      # None == pass
    target_idx: Optional[int] = None

    def __reduce__(self):
        # frozen dataclasses can't be unpickled via __setattr__ under mypyc,
        # and parallel workers ship Actions back across process boundaries —
        # reconstruct through the constructor instead.
        return (Action, (self.card_idx, self.target_idx))

    @property
    def is_pass(self) -> bool:
        return self.card_idx is None

    def describe(self, state: GameState) -> str:
        if self.card_idx is None:
            return "Pass"
        card = state.hand[self.card_idx]
        if self.target_idx is not None and not card.hits_all:
            return f"{card.name} -> {state.enemies[self.target_idx].name}"
        return card.name


PASS = Action(card_idx=None)

_SELF_TARGETED = {CardType.HEAL, CardType.BLADE, CardType.SHIELD}
_ENEMY_TARGETED = {CardType.DAMAGE, CardType.TRAP}


def legal_actions(state: GameState) -> list[Action]:
    """Enumerate affordable (card, target) pairs plus Pass."""
    actions: list[Action] = [PASS]
    for i, card in enumerate(state.hand):
        if state.player.effective_pips(card.element) < card.pip_cost:
            continue
        if card.card_type in _SELF_TARGETED:
            actions.append(Action(card_idx=i))
        elif card.hits_all:
            actions.append(Action(card_idx=i))
        elif card.card_type in _ENEMY_TARGETED:
            for t, enemy in enumerate(state.enemies):
                if enemy.alive:
                    actions.append(Action(card_idx=i, target_idx=t))
        else:  # UTILITY — castable, no target
            actions.append(Action(card_idx=i))
    return actions
