from __future__ import annotations
from .game import reset_tournament
import random
import secrets
import string

from dataclasses import dataclass, field
from typing import Any

from treys import Card, Evaluator

MAX_PLAYERS = 5
SHARED_ROOM_CODE = "TABLE"
STARTING_CHIPS = 1_000
BASE_SMALL_BLIND = 10
BASE_BIG_BLIND = 20
EVALUATOR = Evaluator()


@dataclass
class Player:
    id: str
    name: str
    seat: int
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    chips: int = STARTING_CHIPS
    hole: list[int] = field(default_factory=list)
    folded: bool = False
    all_in: bool = False
    committed: int = 0
    street_bet: int = 0
    kicked: bool = False


@dataclass
class Room:
    code: str
    host_id: str
    players: list[Player] = field(default_factory=list)
    started: bool = False
    hand_number: int = 0
    dealer_seat: int = -1
    hand: dict[str, Any] | None = None
    last_result: list[dict[str, Any]] = field(default_factory=list)


ROOMS: dict[str, Room] = {}


def create_room(name: str) -> tuple[Room, Player]:
    code = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(5))
    while code in ROOMS:
        code = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(5))
    player = Player(id=secrets.token_urlsafe(9), name=_clean_name(name), seat=0)
    room = Room(code=code, host_id=player.id, players=[player])
    ROOMS[code] = room
    return room, player


def join_shared_room(name: str) -> tuple[Room, Player]:
    cleaned_name = _clean_name(name)
    room = ROOMS.get(SHARED_ROOM_CODE)
    if room is None:
        player = Player(id=secrets.token_urlsafe(9), name=cleaned_name, seat=0)
        room = Room(code=SHARED_ROOM_CODE, host_id=player.id, players=[player])
        ROOMS[room.code] = room
        return room, player
    return join_room(room.code, cleaned_name)


def join_room(code: str, name: str) -> tuple[Room, Player]:
    room = ROOMS.get(code.upper())
    if room is None:
        raise ValueError("방을 찾을 수 없습니다.")
    if room.started:
        raise ValueError("이미 토너먼트가 시작된 방입니다.")
    if len(room.players) >= MAX_PLAYERS:
        raise ValueError("이 방은 5명으로 가득 찼습니다.")
    
    cleaned_name = _clean_name(name)
    # 중복 닉네임 체크
    if any(p.name == cleaned_name for p in room.players):
        raise ValueError("이미 사용 중인 닉네임입니다. 다른 닉네임을 입력해 주세요.")

    player = Player(id=secrets.token_urlsafe(9), name=cleaned_name, seat=len(room.players))
    room.players.append(player)
    return room, player


def reset_tournament(room: Room, requester_id: str) -> None:
    """토너먼트를 완전히 초기화하여 모든 플레이어의 칩과 상태를 처음으로 되돌립니다."""
    if requester_id != room.host_id:
        raise ValueError("방장만 토너먼트를 초기화할 수 있습니다.")
    
    room.started = False
    room.hand_number = 0
    room.dealer_seat = -1
    room.hand = None
    room.last_result = []
    
    for idx, player in enumerate(room.players):
        player.chips = STARTING_CHIPS
        player.hole = []
        player.folded = False
        player.all_in = False
        player.committed = 0
        player.street_bet = 0
        player.kicked = False
        player.seat = idx


def kick_player(room: Room, requester_id: str, target_id: str) -> None:
    if requester_id != room.host_id:
        raise ValueError("방장만 플레이어를 강퇴할 수 있습니다.")
    if requester_id == target_id:
        raise ValueError("방장은 자기 자신을 강퇴할 수 없습니다.")
    target = _player_by_id(room, target_id)
    if target.kicked:
        raise ValueError("이미 강퇴된 플레이어입니다.")

    hand = room.hand
    if hand and not hand["complete"]:
        target.folded = True
        target.kicked = True
        hand["acted"].add(target.id)
        _refresh_pot(room)
        contenders = [player for player in room.players if not player.folded]
        if len(contenders) == 1:
            _award_uncontested(room, contenders[0])
        elif _round_complete(room):
            _advance_street(room)
        elif hand["turn_id"] == target.id:
            hand["turn_id"] = _next_actor(room, target.seat)
        return

    _remove_player(room, target)


def start_hand(room: Room) -> None:
    if room.started and room.hand and not room.hand["complete"]:
        raise ValueError("현재 핸드가 진행 중입니다.")
    active = [player for player in room.players if player.chips > 0]
    if len(active) < 2:
        raise ValueError("다음 핸드를 시작하려면 칩을 가진 플레이어가 2명 이상이어야 합니다.")
    room.started = True
    room.hand_number += 1
    room.dealer_seat = _next_seat(room, room.dealer_seat, {player.id for player in active})
    small_blind = BASE_SMALL_BLIND * (2 ** ((room.hand_number - 1) // 5))
    big_blind = small_blind * 2
    for player in room.players:
        player.hole = []
        player.folded = player.chips <= 0
        player.all_in = False
        player.committed = 0
        player.street_bet = 0

    deck = [Card.new(rank + suit) for rank in "23456789TJQKA" for suit in "shdc"]
    random.shuffle(deck)
    for _ in range(2):
        for player in active:
            player.hole.append(deck.pop())

    if len(active) == 2:
        sb_player = next(player for player in active if player.seat == room.dealer_seat)
        bb_player = _player_after(room, sb_player.seat, active)
    else:
        sb_player = _player_after(room, room.dealer_seat, active)
        bb_player = _player_after(room, sb_player.seat, active)
    _post_blind(sb_player, small_blind)
    _post_blind(bb_player, big_blind)
    room.last_result = []
    room.hand = {
        "deck": deck,
        "board": [],
        "street": "preflop",
        "current_bet": max(player.street_bet for player in active),
        "min_raise": big_blind,
        "turn_id": None,
        "acted": set(),
        "small_blind": small_blind,
        "big_blind": big_blind,
        "complete": False,
        "pot": 0,
    }
    first_actor_after = bb_player.seat if len(active) > 2 else room.dealer_seat - 1
    room.hand["turn_id"] = _next_actor(room, first_actor_after)
    _refresh_pot(room)
    if room.hand["turn_id"] is None:
        _advance_street(room)


def act(room: Room, player_id: str, action: str, amount: int = 0) -> None:
    hand = room.hand
    if not hand or hand["complete"]:
        raise ValueError("진행 중인 핸드가 없습니다.")
    player = _player_by_id(room, player_id)
    if player.kicked:
        raise ValueError("강퇴된 플레이어는 행동할 수 없습니다.")
    if hand["turn_id"] != player_id:
        raise ValueError("현재 차례가 아닙니다.")
    if player.folded or player.all_in:
        raise ValueError("행동할 수 없는 플레이어입니다.")

    to_call = max(0, hand["current_bet"] - player.street_bet)
    if action == "fold":
        player.folded = True
    elif action in {"check", "call"}:
        if action == "check" and to_call:
            raise ValueError("콜할 금액이 있습니다.")
        paid = min(to_call, player.chips)
        _put_chips(player, paid)
        if paid < to_call:
            player.all_in = True
    elif action in {"bet", "raise", "all_in"}:
        target = player.street_bet + player.chips if action == "all_in" else amount
        maximum = player.street_bet + player.chips
        if target <= hand["current_bet"]:
            raise ValueError("베팅 금액은 현재 베팅보다 커야 합니다.")
        if target > maximum:
            raise ValueError("보유 칩보다 큰 금액은 베팅할 수 없습니다.")
        raise_size = target - hand["current_bet"]
        if raise_size < hand["min_raise"] and target < maximum:
            raise ValueError(f"최소 레이즈 금액은 {hand['current_bet'] + hand['min_raise']:,}입니다.")
        _put_chips(player, target - player.street_bet)
        if player.chips == 0:
            player.all_in = True
        if raise_size >= hand["min_raise"]:
            hand["min_raise"] = raise_size
        hand["current_bet"] = target
        hand["acted"] = set()
    else:
        raise ValueError("알 수 없는 액션입니다.")

    hand["acted"].add(player.id)
    _refresh_pot(room)
    contenders = [candidate for candidate in room.players if not candidate.folded]
    if len(contenders) == 1:
        _award_uncontested(room, contenders[0])
        return
    if _round_complete(room):
        _advance_street(room)
    else:
        hand["turn_id"] = _next_actor(room, player.seat)


def public_state(room: Room, viewer_id: str | None = None) -> dict[str, Any]:
    hand = room.hand
    players = []
    for player in room.players:
        if player.kicked:
            continue
        show_hole = bool(hand and hand["complete"] and not player.folded) or player.id == viewer_id
        players.append({
            "id": player.id,
            "name": player.name,
            "seat": player.seat,
            "chips": player.chips,
            "hole": [Card.int_to_str(card) for card in player.hole] if show_hole else [],
            "card_count": len(player.hole),
            "folded": player.folded,
            "all_in": player.all_in,
            "kicked": player.kicked,
            "street_bet": player.street_bet,
            "is_host": player.id == room.host_id,
        })
    return {
        "code": room.code,
        "host_id": room.host_id,
        "viewer_id": viewer_id,
        "players": players,
        "started": room.started,
        "hand_number": room.hand_number,
        "dealer_seat": room.dealer_seat,
        "hand": None if hand is None else {
            "board": [Card.int_to_str(card) for card in hand["board"]],
            "street": hand["street"],
            "current_bet": hand["current_bet"],
            "min_raise": hand["min_raise"],
            "pot": hand["pot"],
            "turn_id": hand["turn_id"],
            "complete": hand["complete"],
            "small_blind": hand["small_blind"],
            "big_blind": hand["big_blind"],
        },
        "last_result": room.last_result,
        "max_players": MAX_PLAYERS,
    }


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.strip().split())[:18]
    if not cleaned:
        raise ValueError("닉네임을 입력해 주세요.")
    return cleaned


def _player_by_id(room: Room, player_id: str) -> Player:
    for player in room.players:
        if player.id == player_id:
            return player
    raise ValueError("플레이어를 찾을 수 없습니다.")


def _remove_player(room: Room, player: Player) -> None:
    room.players.remove(player)
    if not room.started:
        for seat, remaining in enumerate(room.players):
            remaining.seat = seat
    if room.host_id == player.id and room.players:
        room.host_id = room.players[0].id
    if not room.players:
        ROOMS.pop(room.code, None)


def _player_after(room: Room, seat: int, players: list[Player]) -> Player:
    ordered = sorted(players, key=lambda player: player.seat)
    return next(player for player in ordered if player.seat > seat) if any(player.seat > seat for player in ordered) else ordered[0]


def _next_seat(room: Room, seat: int, player_ids: set[str]) -> int:
    eligible = sorted(player.seat for player in room.players if player.id in player_ids)
    return next((candidate for candidate in eligible if candidate > seat), eligible[0])


def _post_blind(player: Player, amount: int) -> None:
    _put_chips(player, min(amount, player.chips))
    if player.chips == 0:
        player.all_in = True


def _put_chips(player: Player, amount: int) -> None:
    player.chips -= amount
    player.street_bet += amount
    player.committed += amount


def _next_actor(room: Room, after_seat: int) -> str | None:
    hand = room.hand
    eligible = [player for player in room.players if not player.folded and not player.all_in]
    pending = [player for player in eligible if player.id not in hand["acted"] or player.street_bet < hand["current_bet"]]
    if not pending:
        return None
    ordered = sorted(pending, key=lambda player: (player.seat - after_seat - 1) % MAX_PLAYERS)
    return ordered[0].id


def _round_complete(room: Room) -> bool:
    hand = room.hand
    eligible = [player for player in room.players if not player.folded and not player.all_in]
    return all(player.id in hand["acted"] and player.street_bet == hand["current_bet"] for player in eligible)


def _refresh_pot(room: Room) -> None:
    room.hand["pot"] = sum(player.committed for player in room.players)


def _advance_street(room: Room) -> None:
    hand = room.hand
    if len([player for player in room.players if not player.folded]) < 2:
        winner = next(player for player in room.players if not player.folded)
        _award_uncontested(room, winner)
        return
    if hand["street"] == "river":
        _showdown(room)
        return

    deck = hand["deck"]
    if hand["street"] == "preflop":
        deck.pop()
        hand["board"].extend(deck.pop() for _ in range(3))
        hand["street"] = "flop"
    else:
        deck.pop()
        hand["board"].append(deck.pop())
        hand["street"] = "turn" if hand["street"] == "flop" else "river"
    for player in room.players:
        player.street_bet = 0
    hand["current_bet"] = 0
    hand["min_raise"] = hand["big_blind"]
    hand["acted"] = set()
    hand["turn_id"] = _next_actor(room, room.dealer_seat)
    if hand["turn_id"] is None:
        _advance_street(room)


def _award_uncontested(room: Room, winner: Player) -> None:
    hand = room.hand
    pot = sum(player.committed for player in room.players)
    winner.chips += pot
    room.last_result = [{"player_id": winner.id, "name": winner.name, "chips": pot, "label": "승리"}]
    _complete_hand(room)


def _showdown(room: Room) -> None:
    contributors = [player for player in room.players if player.committed > 0]
    levels = sorted({player.committed for player in contributors})
    previous = 0
    awards: dict[str, int] = {}
    for level in levels:
        layer_players = [player for player in contributors if player.committed >= level]
        pot = (level - previous) * len(layer_players)
        eligible = [player for player in layer_players if not player.folded]
        if eligible:
            scores = {player.id: EVALUATOR.evaluate(room.hand["board"], player.hole) for player in eligible}
            best = min(scores.values())
            winners = sorted((player for player in eligible if scores[player.id] == best), key=lambda player: player.seat)
            share, remainder = divmod(pot, len(winners))
            for index, player in enumerate(winners):
                awards[player.id] = awards.get(player.id, 0) + share + (1 if index < remainder else 0)
        previous = level
    for player in room.players:
        player.chips += awards.get(player.id, 0)
    room.last_result = []
    for player in room.players:
        amount = awards.get(player.id, 0)
        if amount:
            rank = EVALUATOR.evaluate(room.hand["board"], player.hole)
            label = EVALUATOR.class_to_string(EVALUATOR.get_rank_class(rank))
            room.last_result.append({"player_id": player.id, "name": player.name, "chips": amount, "label": label})
    _complete_hand(room)


def _complete_hand(room: Room) -> None:
    hand = room.hand
    hand["complete"] = True
    hand["turn_id"] = None
    _refresh_pot(room)
    for player in list(room.players):
        if player.kicked:
            _remove_player(room, player)
