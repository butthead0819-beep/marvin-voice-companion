/* Marvin Companion — idle mode app
 *
 * WebSocket protocol: {type, payload, ts}
 *   - Bridge → browser events: stt_chunk, intent_routed, tts_started, tts_done,
 *     atmosphere_snapshot, member_joined, member_left, memory_list_response
 *   - Browser → bridge events: atmosphere_feedback, mode_change, memory_list_request,
 *     memory_delete, memory_mark_uncertain, tts_injection
 *
 * Connection state machine: DISCONNECTED → CONNECTING → CONNECTED → FAILED → retry 5s
 */

(() => {
  'use strict';

  const RECONNECT_DELAY_MS = 5000;
  const FEEDBACK_WINDOW_SEC = 5;
  const SPEAKING_FADE_MS = 1500;

  // -------------------------------------------------------------- app state
  const state = {
    ws: null,
    wsState: 'disconnected', // disconnected | connecting | connected | failed
    members: new Map(),       // speaker_id -> {name, stage, activity, marvin}
    selectedSpeaker: null,
    lastAtmosphereSnapshotTs: null,
    lastAtmosphereLabel: null,
    feedbackTimer: null,
    countdownTimer: null,
    bubbleSpeakingTimers: new Map(),
    recorder: null,
    recordChunks: [],
    // Lane E: music mode
    mode: 'idle',             // idle | music | game
    currentSong: null,        // {title, style, target, source, started_ts}
    musicReactions: [],       // [{username, reaction, title, ts}]
    djTarget: 'room',         // 'room' | username
    // Lane F: game mode
    currentGame: null,        // 'detective' | null
    gamePhase: null,          // string from payload.phase
    gameEvents: [],           // [{text, ts}] freshest first
    gameSpectator: false,     // UI-only toggle
  };

  // -------------------------------------------------------------- dom refs
  const els = {
    wsStatus: () => document.getElementById('ws-status'),
    onlineCount: () => document.getElementById('online-count'),
    marvinState: () => document.getElementById('marvin-state'),
    bubbleGrid: () => document.getElementById('bubble-grid'),
    utteranceCard: () => document.getElementById('utterance-card'),
    utteranceText: () => document.getElementById('utterance-text'),
    utteranceMeta: () => document.getElementById('utterance-meta-text'),
    utteranceCountdown: () => document.getElementById('utterance-countdown'),
    feedbackRow: () => document.getElementById('feedback-row'),
    sidePanel: () => document.getElementById('side-panel'),
    panelName: () => document.getElementById('panel-name'),
    panelAvatar: () => document.getElementById('panel-avatar'),
    panelStage: () => document.getElementById('panel-stage'),
    panelBias: () => document.getElementById('panel-bias'),
    panelImpression: () => document.getElementById('panel-impression'),
    panelLikes: () => document.getElementById('panel-likes'),
    panelDislikes: () => document.getElementById('panel-dislikes'),
    panelMemories: () => document.getElementById('panel-memories'),
    voiceButton: () => document.getElementById('voice-button'),
    floatInput: () => document.getElementById('float-input'),
    floatInputField: () => document.getElementById('float-input-field'),
  };

  // -------------------------------------------------------------- helpers
  function now() { return Date.now() / 1000; }

  function send(type, payload) {
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
      console.warn('[Companion] WS not connected, drop:', type, payload);
      return;
    }
    const msg = { type, payload, ts: now() };
    state.ws.send(JSON.stringify(msg));
  }

  function setWsState(s) {
    state.wsState = s;
    const el = els.wsStatus();
    if (!el) return;
    if (s === 'connected') {
      el.classList.remove('disconnected');
    } else {
      el.textContent = s === 'connecting' ? '連線中…'
                     : s === 'failed' ? '連線失敗，5 秒後重試'
                     : '連線中斷';
      el.classList.add('disconnected');
    }
  }

  // -------------------------------------------------------------- WS lifecycle
  function connectWs() {
    setWsState('connecting');
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${proto}://${location.host}/ws`;
    try {
      state.ws = new WebSocket(url);
    } catch (e) {
      console.error('[Companion] WS construct failed', e);
      scheduleReconnect();
      return;
    }
    state.ws.onopen = () => setWsState('connected');
    state.ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      handleIncoming(msg);
    };
    state.ws.onerror = (e) => console.warn('[Companion] WS error', e);
    state.ws.onclose = () => {
      setWsState('failed');
      scheduleReconnect();
    };
  }

  function scheduleReconnect() {
    setTimeout(connectWs, RECONNECT_DELAY_MS);
  }

  // -------------------------------------------------------------- incoming router
  function handleIncoming(msg) {
    if (!msg || typeof msg !== 'object' || !msg.type) return;
    switch (msg.type) {
      case 'stt_chunk': onSttChunk(msg.payload); break;
      case 'intent_routed': console.debug('[intent_routed]', msg.payload); break;
      case 'tts_started': onTtsStarted(msg.payload); break;
      case 'tts_done': onTtsDone(msg.payload); break;
      case 'atmosphere_snapshot': onAtmosphereSnapshot(msg.payload, msg.ts); break;
      case 'member_joined': onMemberJoined(msg.payload); break;
      case 'member_left': onMemberLeft(msg.payload); break;
      case 'voice_channel_snapshot': onVoiceChannelSnapshot(msg.payload); break;
      case 'memory_list_response': onMemoryListResponse(msg.payload); break;
      // Lane E: music
      case 'music_started': onMusicStarted(msg.payload); break;
      case 'music_ended': onMusicEnded(msg.payload); break;
      case 'music_reaction': onMusicReaction(msg.payload); break;
      case 'music_recommendations_response': onMusicRecommendationsResponse(msg.payload); break;
      // Lane F: game mode
      case 'game_phase_changed': onGamePhaseChanged(msg.payload); break;
      default:
        console.debug('[Companion] unknown event', msg.type);
    }
  }

  // -------------------------------------------------------------- mode switch
  function setMode(mode) {
    state.mode = mode;
    const app = document.querySelector('.app');
    if (app) app.dataset.mode = mode;
    const musicPanel = document.getElementById('music-panel');
    const djPanel = document.getElementById('dj-panel');
    const sidePanel = document.getElementById('side-panel');
    const gamePanel = document.getElementById('game-panel');
    const gameSidePanel = document.getElementById('game-side-panel');
    // 一律重設
    if (musicPanel) musicPanel.hidden = true;
    if (djPanel) djPanel.hidden = true;
    if (gamePanel) gamePanel.hidden = true;
    if (gameSidePanel) gameSidePanel.hidden = true;
    if (sidePanel) sidePanel.hidden = true;
    if (mode === 'music') {
      if (musicPanel) musicPanel.hidden = false;
      if (djPanel) djPanel.hidden = false;
    } else if (mode === 'game') {
      if (gamePanel) gamePanel.hidden = false;
      if (gameSidePanel) gameSidePanel.hidden = false;
    } else {
      if (sidePanel) sidePanel.hidden = false;
    }
  }

  // -------------------------------------------------------------- music handlers
  function onMusicStarted(payload) {
    if (!payload) return;
    state.currentSong = payload;
    state.musicReactions = [];
    setMode('music');

    const title = payload.title || '—';
    const style = payload.style || '';
    const target = payload.target || payload.requested_by || '';
    const source = payload.source || '';
    setText('music-title', title);
    setText('music-style', style);
    setText('music-target', target ? `@${target}` : '—');
    setText('music-source', source);
    setProgress(0);
    renderReactions();
    refreshDjTargetTabs();
    // First-fire room-level recommendation request
    requestRecommendations(state.djTarget === 'room' ? null : state.djTarget);
  }

  function onMusicEnded(_payload) {
    state.currentSong = null;
    // 不立刻退出 music mode；保留面板讓使用者繼續挑下一首。
    setProgress(0);
  }

  function onMusicReaction(payload) {
    if (!payload) return;
    state.musicReactions.push({
      username: payload.username || '?',
      reaction: payload.reaction || 'silent',
      title: payload.title || '',
      ts: now(),
    });
    if (state.musicReactions.length > 20) state.musicReactions.shift();
    renderReactions();
  }

  function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  function setProgress(pct) {
    const el = document.getElementById('music-progress-fill');
    if (el) el.style.width = `${Math.max(0, Math.min(100, pct))}%`;
  }

  const REACTION_ICONS = { love: '❤️', skip: '⏭️', hum: '🎵', silent: '💤' };
  function renderReactions() {
    const container = document.getElementById('music-reactions');
    if (!container) return;
    if (!state.musicReactions.length) {
      container.innerHTML = '<div class="empty-hint" style="padding:8px 0">尚無反應</div>';
      return;
    }
    container.innerHTML = '';
    state.musicReactions.slice().reverse().forEach((r) => {
      const row = document.createElement('div');
      row.className = 'reaction-row';
      row.innerHTML = `
        <span class="reaction-icon">${escapeHtml(REACTION_ICONS[r.reaction] || '·')}</span>
        <span class="reaction-user">${escapeHtml(r.username)}</span>
        <span class="reaction-text">${escapeHtml(reactionLabel(r.reaction))}</span>
      `;
      container.appendChild(row);
    });
  }

  function reactionLabel(r) {
    return { love: '對味', skip: '跳過', hum: '跟著哼', silent: '沒有反應' }[r] || r || '—';
  }

  // -------------------------------------------------------------- Lane F: game handlers
  /**
   * GAME_PHASE_CHANGED payload:
   *   {game, phase, round, round_total, scoreboard, current_player, timer_seconds, last_event}
   * phase: 'joining' | 'declaring' | 'voting' | 'revealing' | 'between_rounds' | 'ended'
   */
  const GAME_TITLE = {
    detective: '🕵️ 謊言偵探',
  };
  const PHASE_TEMPLATES = {
    joining: () => '等待玩家加入…',
    declaring: (p) => `${p.current_player || '玩家'} 正在輸入三句話（兩真一假）…`,
    voting: (p) => `${p.current_player || '陳述者'} 完成宣告，請猜哪句是謊言`,
    revealing: () => '揭曉本輪結果…',
    between_rounds: () => '本輪結束，準備下一輪',
    ended: () => '🎉 遊戲結束',
  };
  const PHASE_EMOJI = {
    joining: '👥',
    declaring: '📣',
    voting: '🗳️',
    revealing: '💡',
    between_rounds: '⏱',
    ended: '🏁',
  };

  function onGamePhaseChanged(payload) {
    if (!payload) return;
    const phase = payload.phase || '';
    const game = payload.game || 'detective';
    state.currentGame = game;
    state.gamePhase = phase;

    if (phase === 'ended') {
      // 推一筆事件再退回 idle，讓使用者看到「結束」訊息
      pushGameEvent(payload.last_event || '遊戲結束', PHASE_EMOJI.ended);
      renderGamePanel(payload);
      setTimeout(() => {
        if (state.gamePhase === 'ended') setMode('idle');
      }, 1500);
      return;
    }

    setMode('game');
    if (payload.last_event) {
      pushGameEvent(payload.last_event, PHASE_EMOJI[phase] || '·');
    }
    renderGamePanel(payload);
  }

  function pushGameEvent(text, em) {
    state.gameEvents.unshift({ text, em: em || '·', ts: now() });
    // 只留最新 5 筆
    if (state.gameEvents.length > 5) state.gameEvents.length = 5;
  }

  function renderGamePanel(payload) {
    const game = state.currentGame || 'detective';
    const phase = state.gamePhase || '';
    // 標題 + 輪數
    setText('game-title', `${GAME_TITLE[game] || '遊戲中'}`);
    const round = payload.round || 1;
    const total = payload.round_total || round;
    const roundEl = document.getElementById('game-round');
    if (roundEl) roundEl.textContent = `· 第 ${round} 輪 / 共 ${total}`;

    // Timer
    const timer = payload.timer_seconds;
    setText('game-timer', timer ? `⏱ 0:${String(timer).padStart(2, '0')}` : '⏱ —');

    // Phase 文字
    const tpl = PHASE_TEMPLATES[phase];
    const phaseText = tpl ? tpl(payload) : phase;
    setText('game-phase-text', phaseText);

    renderGameScoreboard(payload.scoreboard || []);
    renderGameEventsLog();
    renderMiniScoreboard(payload.scoreboard || []);
  }

  function renderGameScoreboard(scoreboard) {
    const container = document.getElementById('game-scoreboard');
    if (!container) return;
    if (!scoreboard.length) {
      container.innerHTML = '<div class="empty-hint" style="padding:8px 0">尚無比分</div>';
      return;
    }
    container.innerHTML = '';
    scoreboard.forEach((s, i) => {
      const isLeader = i === 0;
      const isMarvin = (s.user || '').toLowerCase() === 'marvin';
      const medal = isLeader ? '🥇 ' : '';
      const badge = isMarvin ? ' <span class="badge">AI</span>' : '';
      const row = document.createElement('div');
      row.className = 'score-row' + (isLeader ? ' leader' : '');
      row.innerHTML = `
        <div class="player">${escapeHtml(medal)}${escapeHtml(s.user || '?')}${badge}</div>
        <div class="pts">${escapeHtml(String(s.score ?? 0))}</div>
      `;
      container.appendChild(row);
    });
  }

  function renderMiniScoreboard(scoreboard) {
    const container = document.getElementById('game-mini-scoreboard');
    if (!container) return;
    const top = scoreboard.slice(0, 2);
    if (!top.length) {
      container.innerHTML = '<div class="empty-hint" style="padding:8px 0">尚無比分</div>';
      return;
    }
    container.innerHTML = '';
    top.forEach((s, i) => {
      const isMarvin = (s.user || '').toLowerCase() === 'marvin';
      const medal = i === 0 ? '🥇 ' : '';
      const badge = isMarvin ? ' <span class="badge">AI</span>' : '';
      const row = document.createElement('div');
      row.className = 'score-row' + (i === 0 ? ' leader' : '');
      row.innerHTML = `
        <div class="player">${escapeHtml(medal)}${escapeHtml(s.user || '?')}${badge}</div>
        <div class="pts">${escapeHtml(String(s.score ?? 0))}</div>
      `;
      container.appendChild(row);
    });
  }

  function renderGameEventsLog() {
    const container = document.getElementById('game-events-log');
    if (!container) return;
    if (!state.gameEvents.length) {
      container.innerHTML = '<div class="event"><span class="em">·</span>遊戲事件將顯示於此</div>';
      return;
    }
    container.innerHTML = '';
    state.gameEvents.forEach((e, i) => {
      const node = document.createElement('div');
      node.className = 'event' + (i === 0 ? ' fresh' : '');
      node.innerHTML = `
        <span class="em">${escapeHtml(e.em || '·')}</span>${escapeHtml(e.text)}
      `;
      container.appendChild(node);
    });
  }

  /**
   * 將 atmosphere snapshot 映射到 gauge 位置（百分比）。
   *   casual / 放鬆閒聊 → 25%
   *   drinking / energetic → 50%
   *   gaming / focused → 65%
   *   stressed / 嚴肅 → 85%
   * topic 優先；無 topic 才看 room_mood。
   */
  function atmosphereToGaugePercent(payload) {
    const topic = (payload?.dominant_topic || '').toLowerCase();
    const mood = (payload?.room_mood || '');
    if (topic === 'casual') return 25;
    if (topic === 'drinking') return 50;
    if (topic === 'gaming') return 65;
    if (topic === 'work' || topic === 'tech') return 65;
    if (mood.includes('放鬆')) return 25;
    if (mood.includes('專注')) return 65;
    if (mood.includes('緊') || mood.includes('壓')) return 85;
    return 40;
  }

  function atmosphereLabel(payload) {
    const mood = payload?.room_mood;
    if (mood) return mood;
    const topic = (payload?.dominant_topic || '').toLowerCase();
    return {
      casual: '放鬆閒聊',
      drinking: '熱鬧喝酒',
      gaming: '專注遊戲',
      work: '工作話題',
      tech: '技術討論',
    }[topic] || '一般狀態';
  }

  function bindGameControls() {
    const root = document.getElementById('game-controls');
    if (!root) return;
    root.querySelectorAll('.game-ctrl-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const action = btn.dataset.action;
        const game = state.currentGame || 'detective';
        if (action === 'skip') {
          send('game_force_skip_round', { game });
        } else if (action === 'end') {
          if (window.confirm('確定要結束目前的遊戲嗎？')) {
            send('game_end', { game });
          }
        } else if (action === 'restart') {
          // Marvin 尚未提供 restart API；只貼 toast 提示
          console.info('[Companion] restart 尚未支援，請手動 /detective start');
          // 簡易 toast：透過 alert 或事件 log
          pushGameEvent('「重新開始」尚未支援，請手動執行 /detective_start', '⚠️');
          renderGameEventsLog();
        }
      });
    });
  }

  function bindGameModeToggle() {
    const root = document.getElementById('game-mode-toggle');
    if (!root) return;
    root.querySelectorAll('.mode-toggle-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        root.querySelectorAll('.mode-toggle-btn').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        state.gameSpectator = btn.dataset.mode === 'spectator';
      });
    });
  }

  // -------------------------------------------------------------- DJ panel
  function refreshDjTargetTabs() {
    const tabs = document.getElementById('dj-target-tabs');
    if (!tabs) return;
    tabs.innerHTML = '';
    const roomTab = document.createElement('div');
    roomTab.className = 'dj-target' + (state.djTarget === 'room' ? ' active' : '');
    roomTab.dataset.target = 'room';
    roomTab.textContent = '房間全體';
    roomTab.addEventListener('click', () => selectDjTarget('room'));
    tabs.appendChild(roomTab);
    for (const [key, m] of state.members) {
      const tab = document.createElement('div');
      tab.className = 'dj-target' + (state.djTarget === key ? ' active' : '');
      tab.dataset.target = key;
      tab.textContent = m.name || key;
      tab.addEventListener('click', () => selectDjTarget(key));
      tabs.appendChild(tab);
    }
  }

  function selectDjTarget(target) {
    state.djTarget = target;
    refreshDjTargetTabs();
    requestRecommendations(target === 'room' ? null : target);
  }

  function requestRecommendations(targetUsername) {
    send('music_recommendations_request', { target_username: targetUsername });
  }

  function onMusicRecommendationsResponse(payload) {
    if (!payload) return;
    renderDjPicks(payload.recommendations || []);
    renderUserDetail(payload);
  }

  function renderDjPicks(picks) {
    const container = document.getElementById('dj-picks');
    if (!container) return;
    if (!picks.length) {
      container.innerHTML = '<div class="empty-hint" style="padding:12px 0">DJ 還沒挑到合適的歌</div>';
      return;
    }
    container.innerHTML = '';
    picks.forEach((p) => {
      const node = document.createElement('div');
      node.className = 'dj-pick';
      node.innerHTML = `
        <div class="play">▶</div>
        <div class="dj-pick-body">
          <div class="dj-pick-title">${escapeHtml(p.title || '—')}</div>
          <div class="dj-pick-why">${escapeHtml(p.reason || '')}</div>
          <div class="dj-pick-meta">${escapeHtml(p.style || '')} · ${formatDuration(p.duration)}</div>
        </div>
      `;
      node.addEventListener('click', () => {
        send('music_play_request', {
          query: p.title,
          target: state.djTarget === 'room' ? null : state.djTarget,
          style: p.style,
        });
      });
      container.appendChild(node);
    });
  }

  function renderUserDetail(payload) {
    const wrap = document.getElementById('dj-user-detail');
    const label = document.getElementById('dj-user-detail-label');
    const taste = document.getElementById('dj-taste-bars');
    const hist = document.getElementById('dj-history-list');
    if (!wrap || !label || !taste || !hist) return;
    if (payload.target === 'room') {
      wrap.hidden = true;
      return;
    }
    wrap.hidden = false;
    label.textContent = `${payload.target} · 點歌歷史`;

    taste.innerHTML = '';
    const tasteEntries = Object.entries(payload.user_taste || {});
    tasteEntries.forEach(([k, v]) => {
      const row = document.createElement('div');
      row.className = 'taste-row';
      const pct = Math.round((v || 0) * 100);
      row.innerHTML = `
        <span class="taste-label">${escapeHtml(k)}</span>
        <div class="taste-bar"><div class="fill" style="width:${pct}%"></div></div>
        <span class="taste-pct">${pct}%</span>
      `;
      taste.appendChild(row);
    });

    hist.innerHTML = '';
    (payload.history || []).forEach((h) => {
      const row = document.createElement('div');
      row.className = 'history-row';
      const tagClass = h.tag === 'love' ? 'love' : (h.tag === 'skip' ? 'skip' : '');
      row.innerHTML = `
        <span class="h-time">${escapeHtml(h.time || '')}</span>
        <span class="h-title">${escapeHtml(h.title || '')}</span>
        <span class="h-tag ${tagClass}">${escapeHtml(h.tag || '')}</span>
      `;
      hist.appendChild(row);
    });
  }

  function formatDuration(sec) {
    sec = parseInt(sec || 0, 10);
    if (!sec) return '—';
    const m = Math.floor(sec / 60);
    const s = String(sec % 60).padStart(2, '0');
    return `${m}:${s}`;
  }

  // -------------------------------------------------------------- music quick buttons
  function bindMusicQuickButtons() {
    const root = document.getElementById('music-quick');
    if (!root) return;
    root.querySelectorAll('.music-quick-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const action = btn.dataset.action;
        const style = btn.dataset.style;
        if (action === 'stop') {
          send('music_skip', {});
          return;
        }
        if (action === 'generate' || action === 'surprise') {
          send('music_play_request', {
            query: action === 'surprise' ? '__surprise__' : '__generate__',
            target: state.djTarget === 'room' ? null : state.djTarget,
            style: null,
          });
          return;
        }
        if (style) {
          send('music_play_request', {
            query: `${style} 模式`,
            target: state.djTarget === 'room' ? null : state.djTarget,
            style,
          });
        }
      });
    });
  }

  function bindMusicPlayerControls() {
    document.querySelectorAll('#music-panel .player-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const action = btn.dataset.action;
        if (action === 'next') send('music_skip', {});
      });
    });
  }

  // -------------------------------------------------------------- bubble grid
  function memberKey(p) { return p.speaker_id || p.speaker || p.name; }

  function onMemberJoined(payload) {
    const key = memberKey(payload);
    if (!key) return;
    state.members.set(key, {
      name: payload.name || payload.speaker || key,
      stage: payload.stage || 'stranger',
      activity: payload.activity || 'mid',
      marvin: payload.marvin === true || payload.marvin === 'yes',
      avatar: payload.avatar || null,
    });
    renderBubbles();
  }

  function onMemberLeft(payload) {
    const key = memberKey(payload);
    if (!key) return;
    state.members.delete(key);
    if (state.selectedSpeaker === key) state.selectedSpeaker = null;
    renderBubbles();
  }

  // Lane B2：bridge 在新 client 連上時推送的完整成員快照。
  // 清掉本地狀態、用 payload 重建，讓 UI 第一秒就有完整 bubble，
  // 不用等 atmosphere snapshot fallback 慢慢累。
  function onVoiceChannelSnapshot(payload) {
    if (!payload || !Array.isArray(payload.members)) return;
    state.members.clear();
    payload.members.forEach((m) => {
      const key = memberKey(m);
      if (!key) return;
      state.members.set(key, {
        name: m.name || m.speaker || key,
        stage: m.stage || 'stranger',
        activity: m.activity || 'mid',
        marvin: m.marvin === true || m.marvin === 'yes',
        avatar: m.avatar || null,
      });
    });
    renderBubbles();
  }

  function onSttChunk(payload) {
    const key = memberKey(payload);
    if (!key) return;
    if (!state.members.has(key)) {
      // Auto-track speakers we hear but never saw join
      state.members.set(key, {
        name: payload.speaker || key,
        stage: 'stranger',
        activity: 'mid',
        marvin: false,
      });
      renderBubbles();
    }
    pulseBubble(key);
  }

  function pulseBubble(key) {
    const node = document.querySelector(`.bubble[data-key="${cssEscape(key)}"]`);
    if (node) node.classList.add('speaking');
    if (state.bubbleSpeakingTimers.has(key)) {
      clearTimeout(state.bubbleSpeakingTimers.get(key));
    }
    state.bubbleSpeakingTimers.set(key, setTimeout(() => {
      const n2 = document.querySelector(`.bubble[data-key="${cssEscape(key)}"]`);
      if (n2) n2.classList.remove('speaking');
      state.bubbleSpeakingTimers.delete(key);
    }, SPEAKING_FADE_MS));
  }

  function cssEscape(s) {
    return String(s).replace(/["\\]/g, '\\$&');
  }

  function renderBubbles() {
    const grid = els.bubbleGrid();
    if (!grid) return;
    grid.innerHTML = '';
    if (state.members.size === 0) {
      grid.innerHTML = '<div class="empty-hint">尚未有人加入語音頻道</div>';
      els.onlineCount().textContent = '0';
      return;
    }
    els.onlineCount().textContent = String(state.members.size);
    for (const [key, m] of state.members) {
      const node = document.createElement('div');
      node.className = 'bubble';
      node.dataset.key = key;
      node.dataset.stage = m.stage || 'stranger';
      node.dataset.activity = m.activity || 'mid';
      if (m.marvin) node.dataset.marvin = 'yes';
      if (key === state.selectedSpeaker) node.classList.add('selected');
      const initial = (m.name || key || '?').slice(0, 1);
      node.innerHTML = `
        <span class="marvin-mark"></span>
        <div class="avatar">${escapeHtml(initial)}</div>
        <div class="name">${escapeHtml(m.name || key)}</div>
      `;
      node.addEventListener('click', () => onBubbleClick(key));
      grid.appendChild(node);
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  function onBubbleClick(key) {
    state.selectedSpeaker = key;
    renderBubbles();
    send('memory_list_request', { speaker: key, limit: 20 });
    const m = state.members.get(key);
    if (m) {
      els.panelName().textContent = m.name || key;
      els.panelAvatar().textContent = (m.name || key).slice(0, 1);
      els.panelStage().textContent = stageLabel(m.stage);
    }
  }

  function stageLabel(stage) {
    return { inner: '內圈', regular: '常客', stranger: '陌生', blacklist: '黑名單' }[stage] || stage || '—';
  }

  // -------------------------------------------------------------- utterance card
  function onTtsStarted(payload) {
    const card = els.utteranceCard();
    if (!card) return;
    card.classList.remove('idle');
    els.utteranceText().textContent = `「${payload.text || ''}」`;
    const target = payload.target ? `@${payload.target}` : '';
    els.utteranceMeta().innerHTML = target
      ? `對 <span class="target">${escapeHtml(target)}</span> · 剛說`
      : '剛說';
    showFeedback();
  }

  function onTtsDone(_payload) {
    // Keep card showing through feedback window; idle after countdown
  }

  function showFeedback() {
    const row = els.feedbackRow();
    const cd = els.utteranceCountdown();
    if (!row || !cd) return;
    row.classList.remove('hidden');
    cd.classList.remove('hidden');
    document.querySelectorAll('.feedback-btn.active').forEach((b) => b.classList.remove('active'));

    let remaining = FEEDBACK_WINDOW_SEC;
    cd.textContent = String(remaining);
    if (state.countdownTimer) clearInterval(state.countdownTimer);
    state.countdownTimer = setInterval(() => {
      remaining -= 1;
      if (remaining <= 0) {
        clearInterval(state.countdownTimer);
        state.countdownTimer = null;
        hideFeedback();
      } else {
        cd.textContent = String(remaining);
      }
    }, 1000);
  }

  function hideFeedback() {
    const row = els.feedbackRow();
    const cd = els.utteranceCountdown();
    if (row) row.classList.add('hidden');
    if (cd) cd.classList.add('hidden');
    const card = els.utteranceCard();
    if (card) card.classList.add('idle');
  }

  // -------------------------------------------------------------- atmosphere
  function onAtmosphereSnapshot(payload, ts) {
    state.lastAtmosphereSnapshotTs = ts;
    state.lastAtmosphereLabel = payload?.label || payload?.mood || null;
    if (payload?.marvin_state) {
      els.marvinState().textContent = payload.marvin_state;
    }
    // 從 atmosphere snapshot 推導 bubbles
    // （member_joined hook 未串接前的暫用方案；speaker_states 內出現過的人視同在線）
    const speakers = payload?.speaker_states || {};
    let added = false;
    for (const speakerKey of Object.keys(speakers)) {
      if (!state.members.has(speakerKey)) {
        state.members.set(speakerKey, {
          name: speakerKey,
          stage: 'stranger',
          activity: 'mid',
          marvin: false,
        });
        added = true;
      }
    }
    if (added) renderBubbles();
    // Lane F：更新遊戲側面板的氛圍 gauge
    const pointer = document.getElementById('atmos-gauge-pointer');
    if (pointer) {
      const pct = atmosphereToGaugePercent(payload);
      pointer.style.left = `${pct}%`;
    }
    const statusEl = document.getElementById('atmos-status');
    if (statusEl) statusEl.textContent = atmosphereLabel(payload);
  }

  // -------------------------------------------------------------- feedback buttons
  function bindFeedbackButtons() {
    document.querySelectorAll('.feedback-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const label = btn.dataset.label;
        const payload = {
          snapshot_ts: state.lastAtmosphereSnapshotTs || now(),
          label,
        };
        send('atmosphere_feedback', payload);
        btn.classList.add('active');
        setTimeout(hideFeedback, 600);
      });
    });
  }

  // -------------------------------------------------------------- atmos quick
  function bindAtmosButtons() {
    document.querySelectorAll('.atmos-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const mode = btn.dataset.mode;
        send('mode_change', { mode });
        document.querySelectorAll('.atmos-btn').forEach((b) => b.classList.remove('active'));
        if (mode !== 'reset') btn.classList.add('active');
      });
    });
  }

  // -------------------------------------------------------------- voice PTT
  // 動作 → 中文描述（給使用者看的 toast 顯示）
  const ACTION_LABEL = {
    mode_silent: '閉嘴 5 分鐘',
    mode_serious: '嚴肅模式',
    mode_resume: '恢復預設',
    mode_shutup: '完全閉嘴',
    feedback_too_loud: '太吵回饋',
    feedback_too_sharp: '太刺回饋',
    feedback_too_jolly: '太嗨回饋',
    tts_inject: 'TTS 代言',
  };

  // 挑一個瀏覽器支援的 mimeType（iOS Safari 偏好 mp4）
  function pickAudioMime() {
    if (typeof MediaRecorder === 'undefined') return null;
    const candidates = [
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/mp4',
      'audio/mp4;codecs=mp4a.40.2',
      'audio/aac',
    ];
    for (const m of candidates) {
      try {
        if (MediaRecorder.isTypeSupported(m)) return m;
      } catch (_) { /* ignore */ }
    }
    return null;
  }

  function showToast(text, opts = {}) {
    // 簡易 toast：固定底部、自動 3s 淡出。重複呼叫會替換內容並重置計時器。
    let toast = document.getElementById('voice-toast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'voice-toast';
      toast.style.cssText = [
        'position:fixed', 'left:50%', 'bottom:120px',
        'transform:translateX(-50%)',
        'background:rgba(20,20,28,0.92)', 'color:#FFD27A',
        'padding:14px 20px', 'border-radius:16px',
        'font-family:"Instrument Sans",system-ui,sans-serif',
        'font-size:16px', 'line-height:1.4', 'max-width:78vw',
        'box-shadow:0 8px 24px rgba(0,0,0,0.4)',
        'z-index:10000', 'opacity:0',
        'transition:opacity 250ms ease', 'pointer-events:none',
        'text-align:center', 'white-space:pre-wrap',
      ].join(';');
      document.body.appendChild(toast);
    }
    toast.textContent = text;
    toast.style.background = opts.error
      ? 'rgba(140,30,30,0.92)'
      : 'rgba(20,20,28,0.92)';
    toast.style.color = opts.error ? '#FFD7D7' : '#FFD27A';
    // 強制 reflow → transition 才會跑
    void toast.offsetWidth;
    toast.style.opacity = '1';
    clearTimeout(state._voiceToastTimer);
    state._voiceToastTimer = setTimeout(() => {
      toast.style.opacity = '0';
    }, opts.durationMs || 3000);
  }

  async function uploadAudioBlob(blob, btn, labelEl) {
    if (!blob || blob.size === 0) {
      showToast('沒有錄到聲音', { error: true });
      return;
    }
    const form = new FormData();
    const filename = blob.type.includes('mp4') ? 'ptt.mp4' : 'ptt.webm';
    form.append('audio', blob, filename);

    btn.classList.add('uploading');
    btn.disabled = true;
    if (labelEl) labelEl.textContent = '辨識中…';
    try {
      const r = await fetch('/audio', { method: 'POST', body: form });
      if (!r.ok) {
        let detail = '上傳失敗，請重試';
        if (r.status === 503) detail = '伺服器尚未設定 GROQ_API_KEY';
        try {
          const errBody = await r.json();
          if (errBody && errBody.detail) detail = errBody.detail;
        } catch (_) { /* ignore */ }
        showToast(detail, { error: true });
        return;
      }
      const data = await r.json();
      console.log('[Companion] /audio result', data);
      const text = (data.text || '').trim();
      const intent = data.intent;
      let toastLine;
      if (!text) {
        toastLine = '沒有辨識到內容';
        showToast(toastLine, { error: true });
      } else if (intent && intent !== 'unknown') {
        const label = ACTION_LABEL[intent] || intent;
        toastLine = `「${text}」\n→ ${label} 已執行`;
        showToast(toastLine);
      } else {
        toastLine = `「${text}」`;
        showToast(toastLine);
      }
    } catch (err) {
      console.warn('[Companion] /audio upload failed', err);
      showToast('上傳失敗，請重試', { error: true });
    } finally {
      btn.classList.remove('uploading');
      btn.disabled = false;
      if (labelEl) labelEl.textContent = '按住說話';
    }
  }

  function bindVoiceButton() {
    const btn = els.voiceButton();
    if (!btn) return;
    const labelEl = document.getElementById('voice-label');
    let activeStream = null;
    let activeMime = null;

    const start = async (e) => {
      e.preventDefault();
      if (btn.disabled) return; // 上傳中不可重觸發
      if (state.recorder && state.recorder.state === 'recording') return;
      btn.classList.add('recording');
      if (labelEl) labelEl.textContent = '錄音中…';
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        activeStream = stream;
        state.recordChunks = [];
        const mime = pickAudioMime();
        activeMime = mime;
        const recorder = mime
          ? new MediaRecorder(stream, { mimeType: mime })
          : new MediaRecorder(stream);
        state.recorder = recorder;
        recorder.ondataavailable = (ev) => {
          if (ev.data && ev.data.size > 0) state.recordChunks.push(ev.data);
        };
        recorder.onstop = () => {
          if (activeStream) {
            activeStream.getTracks().forEach((t) => t.stop());
            activeStream = null;
          }
          const blobType = activeMime || 'audio/webm';
          const blob = new Blob(state.recordChunks, { type: blobType });
          console.log('[Companion] PTT audio size=', blob.size, 'bytes type=', blobType);
          uploadAudioBlob(blob, btn, labelEl);
        };
        recorder.start();
      } catch (err) {
        console.warn('[Companion] mic access failed', err);
        btn.classList.remove('recording');
        if (labelEl) labelEl.textContent = '按住說話';
        showToast('麥克風存取失敗', { error: true });
      }
    };
    const stop = (e) => {
      if (e && e.preventDefault) e.preventDefault();
      btn.classList.remove('recording');
      // label 在 uploadAudioBlob 內負責切換到「辨識中…」
      if (state.recorder && state.recorder.state === 'recording') {
        state.recorder.stop();
      }
    };
    btn.addEventListener('mousedown', start);
    btn.addEventListener('touchstart', start, { passive: false });
    btn.addEventListener('mouseup', stop);
    btn.addEventListener('mouseleave', stop);
    btn.addEventListener('touchend', stop);
  }

  // -------------------------------------------------------------- float input
  function bindFloatInput() {
    const wrap = els.floatInput();
    const toggle = document.getElementById('float-input-toggle');
    const field = els.floatInputField();
    if (!wrap || !toggle || !field) return;
    toggle.addEventListener('click', () => {
      wrap.classList.toggle('collapsed');
      wrap.classList.toggle('expanded');
      if (wrap.classList.contains('expanded')) field.focus();
    });
    field.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const text = field.value.trim();
        if (!text) return;
        send('tts_injection', {
          text,
          voice: null,
          target: state.selectedSpeaker || null,
        });
        field.value = '';
      } else if (e.key === 'Escape') {
        wrap.classList.add('collapsed');
        wrap.classList.remove('expanded');
        field.blur();
      }
    });
  }

  // -------------------------------------------------------------- memory list
  function onMemoryListResponse(payload) {
    const target = payload?.speaker;
    if (target && state.selectedSpeaker && target !== state.selectedSpeaker) return;

    const profile = payload?.profile || {};
    if (profile.name) els.panelName().textContent = profile.name;
    if (profile.stage) els.panelStage().textContent = stageLabel(profile.stage);
    if (typeof profile.bias === 'number') {
      els.panelBias().textContent = `BIAS ${profile.bias >= 0 ? '+' : ''}${profile.bias}`;
    }
    if (profile.impression) {
      els.panelImpression().textContent = profile.impression;
    } else {
      els.panelImpression().textContent = '尚未有印象記錄。';
    }

    renderTags(els.panelLikes(), profile.likes || [], { draggable: true });
    renderTags(els.panelDislikes(), profile.dislikes || [], { draggable: true });
    renderMemories(els.panelMemories(), payload?.memories || []);
  }

  function renderTags(container, tags, opts) {
    if (!container) return;
    container.innerHTML = '';
    if (!tags.length) {
      container.innerHTML = '<span class="hint" style="margin:0">—</span>';
      return;
    }
    tags.forEach((t) => {
      const node = document.createElement('span');
      node.className = 'tag' + (t.uncertain ? ' uncertain' : '');
      node.dataset.docId = t.doc_id || '';
      if (t.category) {
        node.innerHTML = `<span class="cat">${escapeHtml(t.category)}</span>${escapeHtml(t.text || '')}`;
      } else {
        node.textContent = t.text || String(t);
      }
      if (opts?.draggable) {
        node.draggable = true;
        node.addEventListener('dragend', (e) => {
          // Drag-out delete: any drag end fires memory_delete
          if (!node.dataset.docId) return;
          send('memory_delete', { doc_id: node.dataset.docId });
          node.remove();
        });
        node.addEventListener('dblclick', () => {
          if (!node.dataset.docId) return;
          send('memory_mark_uncertain', { doc_id: node.dataset.docId });
          node.classList.add('uncertain');
        });
      }
      container.appendChild(node);
    });
  }

  function renderMemories(container, memories) {
    if (!container) return;
    container.innerHTML = '';
    if (!memories.length) {
      container.innerHTML = '<span class="hint" style="margin:0">—</span>';
      return;
    }
    memories.forEach((m) => {
      const node = document.createElement('div');
      node.className = 'memory-item' + (m.uncertain ? ' uncertain' : '');
      node.dataset.docId = m.doc_id || '';
      node.innerHTML = `
        <span>「${escapeHtml(m.text || '')}」</span>
        <span class="date">${escapeHtml(m.when || '')}</span>
      `;
      node.addEventListener('dblclick', () => {
        if (!node.dataset.docId) return;
        send('memory_mark_uncertain', { doc_id: node.dataset.docId });
        node.classList.add('uncertain');
      });
      container.appendChild(node);
    });
  }

  // -------------------------------------------------------------- boot
  document.addEventListener('DOMContentLoaded', () => {
    bindFeedbackButtons();
    bindAtmosButtons();
    bindVoiceButton();
    bindFloatInput();
    bindMusicQuickButtons();
    bindMusicPlayerControls();
    bindGameControls();
    bindGameModeToggle();
    renderBubbles();
    connectWs();
  });

  // expose for debug
  window.__marvin = { state, send };
})();
