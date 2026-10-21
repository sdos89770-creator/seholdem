const app = document.querySelector('#app');
const params = new URLSearchParams(location.search);
const stored = JSON.parse(sessionStorage.getItem('holdem-session') || 'null');
let roomState = null;
let socket = null;
let playerId = '';
let toastTimer;

function escapeHtml(value = '') {
  return String(value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
}

function cardMarkup(code, hidden = false, small = false) {
  if (hidden || !code) return `<span class="playing-card card-back ${small ? 'card-small' : ''}"><i></i><i></i></span>`;
  const rank = code.slice(0, -1);
  const suitCode = code.slice(-1).toLowerCase();
  const suit = { h: '♥', d: '♦', c: '♣', s: '♠' }[suitCode] || '♠';
  const color = suitCode === 'h' || suitCode === 'd' ? 'red' : 'black';
  return `<span class="playing-card ${color} ${small ? 'card-small' : ''}"><b>${escapeHtml(rank)}</b><i>${suit}</i></span>`;
}

function showToast(message) {
  let node = document.querySelector('.toast');
  if (!node) {
    node = document.createElement('div');
    node.className = 'toast';
    document.body.append(node);
  }
  node.textContent = message;
  node.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove('visible'), 2800);
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || '요청을 처리하지 못했습니다.');
  return data;
}

function renderLobby() {
  const joinCode = params.get('room') || '';
  const invited = Boolean(joinCode);
  app.innerHTML = `
    <main class="lobby-shell">
      <header class="brand-row"><span class="brand-mark">♠</span><span>FRIENDS POKER CLUB</span><span class="brand-status"><i></i> PRIVATE TABLES</span></header>
      <section class="lobby-hero">
        <p class="eyebrow">친구 다섯, 한 테이블</p>
        <h1>색근<br /><em>테이블</em></h1>
        <p class="hero-copy">카드를 나누고, 블라인드가 오르고,<br />마지막 한 명이 남을 때까지.</p>
        <div class="hero-rule"><span></span><b>NO LIMIT · TEXAS HOLD'EM</b><span></span></div>
      </section>
      <section class="entry-panel">
        <label class="field-label" for="nickname">플레이어 이름</label>
        <input id="nickname" maxlength="18" autocomplete="nickname" placeholder="테이블에서 쓸 이름" value="${escapeHtml(stored?.name || '')}" />
        ${invited
          ? `<button class="primary-button" id="join-invite"><span>초대받은 방 입장</span><b>→</b></button><p class="entry-note">ROOM ${escapeHtml(joinCode)}</p>`
          : `<button class="primary-button" id="create-room"><span>새 테이블 열기</span><b>↗</b></button>
        <div class="form-divider"><span></span><i>초대 코드가 있다면</i><span></span></div>
        <div class="join-row"><input id="room-code" maxlength="5" placeholder="ROOM CODE" /><button id="join-room" aria-label="코드로 입장">입장 <b>→</b></button></div>
        <p class="entry-note">최대 5명 · 친구 전용 · 무료 플레이</p>`}
      </section>
      <footer class="lobby-footer"><span>EST. TONIGHT</span><span>ONE TABLE. GOOD COMPANY.</span></footer>
    </main>`;
  document.querySelector('#create-room')?.addEventListener('click', createRoom);
  document.querySelector('#join-invite')?.addEventListener('click', enterRoom);
  document.querySelector('#join-room')?.addEventListener('click', enterRoom);
  document.querySelector('#room-code')?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') enterRoom();
  });
  document.querySelector('#room-code')?.addEventListener('input', (event) => {
    event.target.value = event.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 5);
  });
  document.querySelector('#nickname').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') invited ? enterRoom() : createRoom();
  });
}

function playerName() {
  return document.querySelector('#nickname')?.value.trim() || '';
}

async function createRoom() {
  try {
    const name = playerName();
    const data = await request('/api/rooms', { method: 'POST', body: JSON.stringify({ name }) });
    saveSession(data, name);
    roomState = data.state;
    connectSocket();
    history.replaceState({}, '', `?room=${data.code}`);
  } catch (error) {
    showToast(error.message);
  }
}

async function enterRoom() {
  try {
    const name = playerName();
    const code = (params.get('room') || document.querySelector('#room-code')?.value || '').trim().toUpperCase();
    const data = await request('/api/rooms/join', { method: 'POST', body: JSON.stringify({ name, code }) });
    saveSession(data, name);
    roomState = data.state;
    connectSocket();
    history.replaceState({}, '', `?room=${data.code}`);
  } catch (error) {
    showToast(error.message);
  }
}

function saveSession(data, name) {
  playerId = data.player_id;
  sessionStorage.setItem('holdem-session', JSON.stringify({ code: data.code, player_id: playerId, name }));
}

async function resumeSession() {
  try {
    playerId = stored.player_id;
    const state = await request(`/api/rooms/${stored.code}?player_id=${encodeURIComponent(playerId)}`);
    roomState = state;
    connectSocket();
    history.replaceState({}, '', `?room=${state.code}`);
  } catch {
    sessionStorage.removeItem('holdem-session');
    renderLobby();
  }
}

function connectSocket() {
  socket?.close();
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const connection = new WebSocket(`${protocol}//${location.host}/ws/${roomState.code}?player_id=${encodeURIComponent(playerId)}`);
  socket = connection;
  connection.addEventListener('message', (event) => {
    const message = JSON.parse(event.data);
    if (message.type === 'state') {
      roomState = message.state;
      renderRoom();
    } else if (message.type === 'error') {
      showToast(message.message);
    }
  });
  connection.addEventListener('close', () => {
    if (socket === connection && roomState) showToast('연결이 끊겼어요. 페이지를 새로고침해 주세요.');
  });
}

function send(message) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    showToast('테이블에 연결 중입니다. 잠시 후 다시 시도해 주세요.');
    return;
  }
  socket.send(JSON.stringify(message));
}

function renderRoom() {
  if (!roomState) return;
  const hand = roomState.hand;
  const me = roomState.players.find((player) => player.id === playerId);
  if (!me) return renderLobby();
  const myTurn = Boolean(hand && hand.turn_id === playerId && !hand.complete);
  const callAmount = hand ? Math.max(0, hand.current_bet - me.street_bet) : 0;
  const minTarget = hand ? Math.min(me.street_bet + me.chips, hand.current_bet + hand.min_raise) : 0;
  const maxTarget = hand ? me.street_bet + me.chips : 0;
  const defaultTarget = Math.min(maxTarget, Math.max(minTarget, hand?.current_bet || 0));
  const seats = [...roomState.players].sort((a, b) => a.seat - b.seat);
  const board = hand?.board || [];
  const shareUrl = `${location.origin}/?room=${roomState.code}`;

  app.innerHTML = `
    <main class="game-shell">
      <header class="game-header">
        <a class="table-brand" href="/" aria-label="처음으로"><span>♠</span> 색근테이블</a>
        <div class="table-meta"><span class="live-dot"></span><span>PRIVATE GAME</span><b>#${roomState.code}</b></div>
        <div class="header-actions"><button class="icon-button" id="copy-invite" title="초대 링크 복사" aria-label="초대 링크 복사">↗</button><button class="leave-button" id="leave">나가기</button></div>
      </header>
      <div class="game-layout">
        <section class="table-column">
          <div class="round-bar"><span>${roomState.started ? `HAND ${String(roomState.hand_number).padStart(2, '0')}` : 'TABLE OPEN'}</span><span>${hand ? `${hand.small_blind.toLocaleString()} / ${hand.big_blind.toLocaleString()} BLINDS` : '1,000 STARTING STACK'}</span></div>
          <div class="poker-table">
            <div class="table-stitch"></div>
            <div class="table-center">
              <div class="board-cards">${Array.from({ length: 5 }, (_, index) => cardMarkup(board[index], !board[index], true)).join('')}</div>
              <div class="pot-line"><span class="pot-icon">◆</span><span>POT</span><b>${(hand?.pot || 0).toLocaleString()}</b></div>
              ${roomState.started ? `<div class="street-label">${hand?.complete ? 'HAND COMPLETE' : (hand?.street || '').toUpperCase()}</div>` : `<div class="table-invite">WAITING FOR PLAYERS</div>`}
            </div>
            ${seats.map((player) => `
              <div class="seat seat-${player.seat} ${player.id === playerId ? 'is-you' : ''} ${hand?.turn_id === player.id ? 'is-active' : ''} ${player.folded ? 'is-folded' : ''}">
                <div class="seat-head"><span class="seat-number">${String(player.seat + 1).padStart(2, '0')}</span>${player.id === roomState.host_id ? '<span class="host-crown">✦</span>' : ''}</div>
                <div class="seat-name">${escapeHtml(player.name)}${player.id === playerId ? '<i>YOU</i>' : ''}</div>
                <div class="seat-stack">${player.chips.toLocaleString()} <span>CHIPS</span></div>
                <div class="seat-cards">${player.hole.length ? player.hole.map((card) => cardMarkup(card, false, true)).join('') : (player.card_count ? cardMarkup('', true, true) + cardMarkup('', true, true) : '<span class="seat-empty">SEAT OPEN</span>')}</div>
                ${player.street_bet ? `<div class="bet-chip">${player.street_bet.toLocaleString()}</div>` : ''}
                ${player.all_in ? '<div class="player-badge">ALL IN</div>' : player.folded ? '<div class="player-badge">FOLDED</div>' : ''}
              </div>`).join('')}
          </div>
          <div class="action-area">
            ${!roomState.started ? `
              <div class="waiting-message"><span class="waiting-symbol">${seats.length}/5</span><span><b>${seats.length < 2 ? '친구를 기다리는 중' : '테이블 준비 완료'}</b><small>${seats.length}명이 자리에 앉았습니다.</small></span></div>
              ${me.id === roomState.host_id ? `<button class="primary-button start-button" id="start-game" ${seats.length < 2 ? 'disabled' : ''}>${seats.length < 2 ? '플레이어 2명부터 시작할 수 있어요' : '토너먼트 시작'} <b>→</b></button>` : '<div class="host-note">방장이 게임을 시작하면 카드가 배분됩니다.</div>'}` : hand?.complete ? `
              <div class="result-strip"><span class="result-mark">✦</span><span><b>${roomState.last_result.map((result) => escapeHtml(result.name)).join(', ') || '핸드 종료'}</b><small>${roomState.last_result.map((result) => `${escapeHtml(result.label)} +${result.chips.toLocaleString()}`).join(' · ')}</small></span></div>
              ${me.id === roomState.host_id ? `<button class="primary-button next-hand" id="next-hand">다음 핸드 <b>→</b></button>` : '<div class="host-note">방장이 다음 핸드를 시작할 때까지 기다려 주세요.</div>'}` : `
              <div class="turn-status ${myTurn ? 'your-turn' : ''}"><i></i><span>${myTurn ? '당신의 차례입니다' : `${escapeHtml(roomState.players.find((player) => player.id === hand.turn_id)?.name || '플레이어')} 차례`}</span><b>${callAmount ? `콜 ${callAmount.toLocaleString()}` : '체크 가능'}</b></div>
              <div class="controls-row">
                <button class="action-button fold-button" data-move="fold" ${!myTurn ? 'disabled' : ''}>폴드</button>
                <button class="action-button call-button" data-move="${callAmount ? 'call' : 'check'}" ${!myTurn ? 'disabled' : ''}>${callAmount ? `콜 ${callAmount.toLocaleString()}` : '체크'}</button>
                <div class="raise-control"><label for="raise-amount">${hand.current_bet ? '레이즈 금액' : '베팅 금액'}</label><div><input id="raise-amount" type="number" min="${minTarget}" max="${maxTarget}" step="${hand.big_blind}" value="${defaultTarget}" /><button class="action-button raise-button" data-move="${hand.current_bet ? 'raise' : 'bet'}" ${!myTurn || maxTarget <= hand.current_bet ? 'disabled' : ''}>${hand.current_bet ? '레이즈' : '베팅'}</button></div></div>
                <button class="action-button allin-button" data-move="all_in" ${!myTurn || me.chips <= 0 ? 'disabled' : ''}>올인</button>
              </div>`}
          </div>
        </section>
        <aside class="sidebar">
          <section class="side-section invite-section"><div class="section-label"><span>INVITE FRIENDS</span><b>01 / 05</b></div><p>좋은 게임은<br /><em>좋은 사람들과.</em></p><button class="invite-button" id="copy-invite-large"><span>초대 링크 복사</span><b>↗</b></button><div class="room-code-line"><span>ROOM CODE</span><strong>${roomState.code}</strong><button id="copy-code" title="방 코드 복사" aria-label="방 코드 복사">⧉</button></div><small class="invite-hint">링크를 카카오톡에 붙여 보내세요.</small></section>
          <section class="side-section player-section"><div class="section-label"><span>PLAYERS</span><b>${seats.length} / 5</b></div><div class="player-list">${Array.from({ length: 5 }, (_, index) => {
            const player = seats.find((item) => item.seat === index);
            return player ? `<div class="player-row ${player.id === playerId ? 'player-me' : ''}"><span class="player-seat">${String(index + 1).padStart(2, '0')}</span><span class="player-avatar">${escapeHtml(player.name.slice(0, 1))}</span><span class="player-info"><b>${escapeHtml(player.name)} ${player.id === playerId ? '<i>YOU</i>' : ''}</b><small>${player.id === roomState.host_id ? 'HOST' : player.folded ? 'FOLDED' : player.all_in ? 'ALL IN' : 'IN THE GAME'}</small></span><strong>${player.chips.toLocaleString()}</strong></div>` : `<div class="player-row vacant"><span class="player-seat">${String(index + 1).padStart(2, '0')}</span><span class="vacant-mark">+</span><span class="player-info"><b>자리 비어 있음</b><small>초대를 기다리는 중</small></span></div>`;
          }).join('')}</div></section>
          <section class="side-section blinds-section"><div class="section-label"><span>BLINDS</span><b>EVERY 5 HANDS</b></div><div class="blind-values"><div><small>SMALL</small><b>${(hand?.small_blind || 10).toLocaleString()}</b></div><span>/</span><div><small>BIG</small><b>${(hand?.big_blind || 20).toLocaleString()}</b></div></div><div class="blind-progress"><span style="width:${roomState.hand_number % 5 * 20 || (roomState.hand_number ? 100 : 0)}%"></span></div><p>다음 블라인드 상승까지 ${5 - (roomState.hand_number % 5 || 0)} 핸드</p></section>
          <footer class="sidebar-footer"><span>NO MONEY. JUST GLORY.</span><span>색근테이블 · FRIENDS ONLY</span></footer>
        </aside>
      </div>
    </main>`;

  document.querySelector('#copy-invite').addEventListener('click', () => copyText(shareUrl, '초대 링크를 복사했어요.'));
  document.querySelector('#copy-invite-large').addEventListener('click', () => copyText(shareUrl, '초대 링크를 복사했어요.'));
  document.querySelector('#copy-code').addEventListener('click', () => copyText(roomState.code, '방 코드를 복사했어요.'));
  document.querySelector('#leave').addEventListener('click', leaveRoom);
  document.querySelector('#start-game')?.addEventListener('click', () => send({ action: 'start' }));
  document.querySelector('#next-hand')?.addEventListener('click', () => send({ action: 'start' }));
  document.querySelectorAll('[data-move]').forEach((button) => button.addEventListener('click', () => {
    const move = button.dataset.move;
    const amount = ['bet', 'raise'].includes(move) ? Number(document.querySelector('#raise-amount').value) : 0;
    send({ action: 'play', move, amount });
  }));
}

async function copyText(text, message) {
  try {
    await navigator.clipboard.writeText(text);
    showToast(message);
  } catch {
    const input = document.createElement('textarea');
    input.value = text;
    input.setAttribute('readonly', '');
    input.style.position = 'fixed';
    input.style.opacity = '0';
    document.body.append(input);
    input.select();
    const copied = document.execCommand('copy');
    input.remove();
    showToast(copied ? message : '주소를 선택해 카카오톡에 붙여넣어 주세요.');
  }
}

async function leaveRoom() {
  try {
    await request(`/api/rooms/${roomState.code}/players/${playerId}`, { method: 'DELETE' });
    socket?.close();
    roomState = null;
    playerId = '';
    sessionStorage.removeItem('holdem-session');
    history.replaceState({}, '', '/');
    renderLobby();
  } catch (error) {
    showToast(error.message);
  }
}

if (params.get('room') && params.get('room') !== stored?.code) renderLobby();
else if (stored?.code && stored?.player_id) resumeSession();
else renderLobby();
