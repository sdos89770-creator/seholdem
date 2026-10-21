import pytest

from app.game import ROOMS, act, create_room, join_room, public_state, start_hand


@pytest.fixture(autouse=True)
def clear_rooms():
    ROOMS.clear()
    yield
    ROOMS.clear()


def test_room_is_limited_to_five_players():
    room, _ = create_room("Host")
    for index in range(4):
        join_room(room.code, f"Player {index}")
    with pytest.raises(ValueError, match="5명으로 가득"):
        join_room(room.code, "Sixth")


def test_host_can_start_and_private_cards_are_hidden():
    room, host = create_room("Host")
    guest_room, guest = join_room(room.code, "Guest")
    assert guest_room is room
    start_hand(room)
    assert len(room.hand["board"]) == 0
    assert len(room.players[0].hole) == 2
    assert len(room.players[1].hole) == 2
    assert len([card for player in room.players for card in player.hole]) == 4
    state = public_state(room, host.id)
    assert len(state["players"][0]["hole"]) == 2
    assert state["players"][1]["hole"] == []


def test_invalid_player_action_is_rejected():
    room, host = create_room("Host")
    join_room(room.code, "Guest")
    start_hand(room)
    wrong_player = next(player for player in room.players if player.id != room.hand["turn_id"])
    with pytest.raises(ValueError, match="현재 차례가 아닙니다"):
        act(room, wrong_player.id, "fold")


def test_heads_up_dealer_posts_small_blind_and_acts_first():
    room, dealer = create_room("Dealer")
    join_room(room.code, "Big blind")
    start_hand(room)
    assert room.dealer_seat == dealer.seat
    assert dealer.street_bet == room.hand["small_blind"]
    assert room.hand["turn_id"] == dealer.id


def test_hand_reaches_showdown_and_preserves_chips():
    room, dealer = create_room("Dealer")
    join_room(room.code, "Big blind")
    start_hand(room)

    act(room, dealer.id, "call")
    big_blind = next(player for player in room.players if player.id != dealer.id)
    act(room, big_blind.id, "check")
    while not room.hand["complete"]:
        current = next(player for player in room.players if player.id == room.hand["turn_id"])
        act(room, current.id, "check")

    assert room.hand["street"] == "river"
    assert len(room.hand["board"]) == 5
    assert sum(player.chips for player in room.players) == 2_000
    assert room.last_result


def test_fold_awards_the_pot_to_the_remaining_player():
    room, dealer = create_room("Dealer")
    _, other = join_room(room.code, "Big blind")
    start_hand(room)
    act(room, dealer.id, "fold")

    assert room.hand["complete"]
    assert room.last_result[0]["player_id"] == other.id
    assert sum(player.chips for player in room.players) == 2_000
