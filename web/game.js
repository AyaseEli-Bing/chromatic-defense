/* game.js — 塔防 Canvas 渲染 + 用户交互
 * 与 Swift 双向通信：
 *   JS→Swift: window.webkit.messageHandlers.cmd.postMessage(JSON.stringify({...}))
 *   Swift→JS: window.handleState(stateObj) / window.handleResp(respObj)
 */
(function () {
  const canvas = document.getElementById('game');
  const ctx = canvas.getContext('2d');
  const CELL = 32; // 每格 32px

  let state = null;
  let selectedTowerType = null;
  let selectedTowerCell = null; // {x, y} 选中的已建塔
  let mouseCell = null;
  let lastSelKey = ''; // 节流 selected-tower-info 的 DOM 重设

  // ===== Swift 桥接 =====
  function sendCommand(cmd) {
    try {
      window.webkit.messageHandlers.cmd.postMessage(JSON.stringify(cmd));
    } catch (e) {
      // 非 WebView 环境（浏览器调试），降级到 console
      console.log('[cmd]', cmd);
    }
  }

  // Swift 调用：传入 Python 推送的状态
  // 用 rAF 合并多次 state 更新：30fps 推送 vs 60fps 渲染节拍，
  // 避免 evaluateJavaScript completion 在主线程堆积导致 HUD 不更新
  let renderScheduled = false;
  window.handleState = function (s) {
    state = s;
    if (!renderScheduled) {
      renderScheduled = true;
      requestAnimationFrame(() => {
        renderScheduled = false;
        render();
        updateHUD();
      });
    }
  };

  // Swift 调用：传入命令响应
  window.handleResp = function (r) {
    if (r && r.msg) {
      // 命中音效（用 Web Audio 合成短促 beep）
      if (r.ok && r.msg.includes('建造')) playBeep(660, 0.08);
      if (r.ok && r.msg.includes('升级')) playBeep(880, 0.08);
      if (r.ok && r.msg.includes('波次')) playBeep(440, 0.15);
      flash(r.msg, 1500);
    }
  };

  // ===== Web Audio 音效（JS 侧即时反馈，不等 Python） =====
  let audioCtx = null;
  function playBeep(freq, dur) {
    try {
      if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const o = audioCtx.createOscillator();
      const g = audioCtx.createGain();
      o.type = 'square';
      o.frequency.value = freq;
      g.gain.value = 0.1;
      g.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + dur);
      o.connect(g); g.connect(audioCtx.destination);
      o.start(); o.stop(audioCtx.currentTime + dur);
    } catch (e) {}
  }

  // ===== 渲染 =====
  function render() {
    if (!state) return;
    const W = state.W, H = state.H;
    canvas.width = W * CELL;
    canvas.height = H * CELL;

    // 背景
    ctx.fillStyle = '#0d1117';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // 地图网格
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const cell = state.map[y][x];
        if (cell === 1) {
          // 路径
          ctx.fillStyle = '#1a3a1a';
          ctx.fillRect(x * CELL, y * CELL, CELL, CELL);
        } else {
          // 空地
          ctx.fillStyle = (x + y) % 2 === 0 ? '#111821' : '#0f1520';
          ctx.fillRect(x * CELL, y * CELL, CELL, CELL);
        }
        // 网格线
        ctx.strokeStyle = '#1a2330';
        ctx.lineWidth = 1;
        ctx.strokeRect(x * CELL, y * CELL, CELL, CELL);
      }
    }

    // 起点终点标记
    if (state.start) {
      ctx.fillStyle = '#4ecca3';
      ctx.font = '12px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('入', state.start[0] * CELL + CELL/2, state.start[1] * CELL + CELL/2 + 4);
    }
    if (state.goal) {
      ctx.fillStyle = '#e74c3c';
      ctx.fillText('出', state.goal[0] * CELL + CELL/2, state.goal[1] * CELL + CELL/2 + 4);
    }

    // 鼠标悬停高亮
    if (mouseCell && state.map[mouseCell.y] && state.map[mouseCell.y][mouseCell.x] === 0) {
      let occupied = state.towers.some(t => t.x === mouseCell.x && t.y === mouseCell.y);
      if (!occupied && selectedTowerType) {
        ctx.fillStyle = 'rgba(78,204,163,0.2)';
        ctx.fillRect(mouseCell.x * CELL, mouseCell.y * CELL, CELL, CELL);
      }
    }

    // 塔
    for (const t of state.towers) {
      const cx = t.x * CELL + CELL / 2;
      const cy = t.y * CELL + CELL / 2;
      // 选中塔显示射程
      if (selectedTowerCell && selectedTowerCell.x === t.x && selectedTowerCell.y === t.y) {
        ctx.strokeStyle = 'rgba(78,204,163,0.4)';
        ctx.beginPath();
        ctx.arc(cx, cy, t.range * CELL, 0, Math.PI * 2);
        ctx.stroke();
      }
      // 塔体
      ctx.fillStyle = t.color;
      ctx.fillRect(cx - 10, cy - 10, 20, 20);
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 2;
      ctx.strokeRect(cx - 10, cy - 10, 20, 20);
      // 炮管指向
      ctx.strokeStyle = t.color;
      ctx.lineWidth = 4;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(cx + Math.cos(t.angle) * 14, cy + Math.sin(t.angle) * 14);
      ctx.stroke();
      // 等级
      ctx.fillStyle = '#ffd700';
      ctx.font = '10px sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText('★'.repeat(t.level), t.x * CELL + 2, t.y * CELL + 10);
    }

    // 敌人
    for (const e of state.enemies) {
      const cx = e.x * CELL + CELL / 2;
      const cy = e.y * CELL + CELL / 2;
      const r = 8 * e.size;
      ctx.fillStyle = e.color;
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 1;
      ctx.stroke();
      // 血条
      const bw = 24, bh = 4;
      ctx.fillStyle = '#333';
      ctx.fillRect(cx - bw/2, cy - r - 8, bw, bh);
      ctx.fillStyle = e.hp / e.max_hp > 0.5 ? '#4ecca3' : (e.hp / e.max_hp > 0.25 ? '#ffd700' : '#e74c3c');
      ctx.fillRect(cx - bw/2, cy - r - 8, bw * (e.hp / e.max_hp), bh);
    }

    // 子弹
    for (const p of state.projectiles) {
      ctx.fillStyle = p.color;
      ctx.beginPath();
      ctx.arc(p.x * CELL, p.y * CELL, 3, 0, Math.PI * 2);
      ctx.fill();
    }

    // 游戏结束/胜利遮罩
    if (state.phase === 'game_over' || state.phase === 'victory') {
      ctx.fillStyle = 'rgba(0,0,0,0.7)';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = state.phase === 'victory' ? '#4ecca3' : '#e74c3c';
      ctx.font = 'bold 36px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(state.phase === 'victory' ? '胜 利' : '游戏结束', canvas.width/2, canvas.height/2 - 20);
      ctx.fillStyle = '#e0e0e0';
      ctx.font = '18px sans-serif';
      ctx.fillText('分数: ' + state.score, canvas.width/2, canvas.height/2 + 20);
      ctx.fillText('波次: ' + state.wave + '/' + state.total_waves, canvas.width/2, canvas.height/2 + 50);
      ctx.fillText('输入名字后回车提交分数，或点击排行榜', canvas.width/2, canvas.height/2 + 80);
    }
  }

  // ===== HUD 更新 =====
  function updateHUD() {
    if (!state) return;
    document.getElementById('gold').textContent = state.gold;
    document.getElementById('lives').textContent = state.lives;
    document.getElementById('wave').textContent = state.wave + '/' + state.total_waves;
    document.getElementById('score').textContent = state.score;

    // 塔按钮可用性
    document.querySelectorAll('.tower-btn').forEach(btn => {
      const spec = state.tower_specs.find(s => s.id === btn.dataset.tower);
      if (spec) {
        btn.classList.toggle('disabled', state.gold < spec.cost);
        btn.querySelector('.cost').textContent = spec.cost + 'G';
      }
    });

    // 波次按钮
    const btnWave = document.getElementById('btn-wave');
    if (state.phase === 'waiting') {
      btnWave.textContent = '开始第' + (state.wave + 1) + '波';
      btnWave.disabled = false;
    } else if (state.phase === 'playing') {
      btnWave.textContent = '进行中...';
      btnWave.disabled = true;
    } else {
      btnWave.textContent = state.phase === 'victory' ? '已胜利' : '已结束';
      btnWave.disabled = true;
    }

    // 选中塔信息（只在 selectedTowerCell 真正改变时重设 innerHTML，避免 30Hz DOM reflow）
    const info = document.getElementById('selected-tower-info');
    const selKey = selectedTowerCell ? selectedTowerCell.x + ',' + selectedTowerCell.y : '';
    if (selKey !== lastSelKey) {
      lastSelKey = selKey;
      if (selectedTowerCell) {
        const t = state.towers.find(t => t.x === selectedTowerCell.x && t.y === selectedTowerCell.y);
        if (t) {
          info.style.display = 'block';
          info.innerHTML = '<div>' + t.name + ' Lv' + t.level + '</div>' +
            '<div>伤害:' + Math.round(t.spec_dmg || t.damage || 0) + '</div>' +
            '<div class="btn-row">' +
            '<button onclick="window._upgrade()">升级</button>' +
            '<button onclick="window._sell()">卖出</button>' +
            '</div>';
        } else {
          info.style.display = 'none';
          selectedTowerCell = null;
        }
      } else {
        info.style.display = 'none';
      }
    }

    // 排行榜
    if (state.leaderboard) {
      const lb = document.getElementById('leaderboard');
      lb.innerHTML = state.leaderboard.map((s, i) =>
        '<div class="entry"><span class="rank">' + (i+1) + '</span>' +
        '<span class="nm">' + esc(s.name) + '</span>' +
        '<span class="sc">' + s.score + '</span></div>'
      ).join('');
    }

    // flash
    if (state.flash_msg) {
      flash(state.flash_msg, 2000);
    }
  }

  function esc(s) { return String(s).replace(/[<>&]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;'}[c])); }

  function flash(msg, dur) {
    const el = document.getElementById('flash');
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.remove('show'), dur || 1500);
  }

  // ===== 鼠标交互 =====
  canvas.addEventListener('mousemove', e => {
    const rect = canvas.getBoundingClientRect();
    const x = Math.floor((e.clientX - rect.left) / CELL);
    const y = Math.floor((e.clientY - rect.top) / CELL);
    if (state && x >= 0 && x < state.W && y >= 0 && y < state.H) {
      mouseCell = { x, y };
    }
  });

  canvas.addEventListener('mouseleave', () => { mouseCell = null; });

  canvas.addEventListener('click', e => {
    const rect = canvas.getBoundingClientRect();
    const x = Math.floor((e.clientX - rect.left) / CELL);
    const y = Math.floor((e.clientY - rect.top) / CELL);
    if (!state || x < 0 || x >= state.W || y < 0 || y >= state.H) return;

    // 点击已有塔 → 选中
    const tower = state.towers.find(t => t.x === x && t.y === y);
    if (tower) {
      selectedTowerCell = { x, y };
      selectedTowerType = null;
      updateTowerButtons();
      return;
    }
    // 点击空地 + 已选塔类型 → 建塔
    if (state.map[y][x] === 0 && selectedTowerType) {
      sendCommand({ type: 'build_tower', x: x, y: y, tower: selectedTowerType });
      playBeep(660, 0.06);
      return;
    }
    // 其他 → 取消选中
    selectedTowerCell = null;
    selectedTowerType = null;
    updateTowerButtons();
  });

  function updateTowerButtons() {
    document.querySelectorAll('.tower-btn').forEach(btn => {
      btn.classList.toggle('selected', btn.dataset.tower === selectedTowerType);
    });
  }

  // ===== 全局函数（供 inline onclick 调用） =====
  window._upgrade = function () {
    if (selectedTowerCell) {
      sendCommand({ type: 'upgrade_tower', x: selectedTowerCell.x, y: selectedTowerCell.y });
      playBeep(880, 0.08);
    }
  };
  window._sell = function () {
    if (selectedTowerCell) {
      sendCommand({ type: 'sell_tower', x: selectedTowerCell.x, y: selectedTowerCell.y });
      selectedTowerCell = null;
    }
  };

  // ===== 初始化塔按钮 =====
  function initTowerButtons() {
    const container = document.getElementById('tower-buttons');
    container.innerHTML = '';
    // 用占位，等第一次 state 到达后填充真实数据
    const types = ['arrow', 'cannon', 'magic'];
    types.forEach(id => {
      const btn = document.createElement('div');
      btn.className = 'tower-btn';
      btn.dataset.tower = id;
      btn.innerHTML = '<span class="nm">加载中...</span><span class="cost">-</span>';
      btn.onclick = function () {
        if (btn.classList.contains('disabled')) return;
        selectedTowerType = id;
        selectedTowerCell = null;
        updateTowerButtons();
      };
      container.appendChild(btn);
    });
  }

  // 当第一次收到 state 后，用真实 spec 更新按钮文字
  const origUpdate = updateHUD;
  updateHUD = function () {
    origUpdate();
    if (state && state.tower_specs && !document.querySelector('.tower-btn .nm[data-ok]')) {
      state.tower_specs.forEach(spec => {
        const btn = document.querySelector('.tower-btn[data-tower="' + spec.id + '"]');
        if (btn) {
          btn.innerHTML = '<span class="nm" data-ok="1">' + spec.name + '</span><span class="cost">' + spec.cost + 'G</span>';
        }
      });
    }
  };

  document.getElementById('btn-wave').onclick = function () {
    sendCommand({ type: 'start_wave' });
  };
  document.getElementById('btn-lb').onclick = function () {
    sendCommand({ type: 'get_leaderboard' });
  };

  // 游戏结束时输入名字提交
  let nameInput = null;
  const origRender = render;
  // 在 game_over/victory 时弹出输入框
  setInterval(() => {
    if (state && (state.phase === 'game_over' || state.phase === 'victory') && !nameInput) {
      nameInput = prompt('输入名字提交分数:', 'Player');
      if (nameInput) {
        sendCommand({ type: 'submit_score', name: nameInput });
        sendCommand({ type: 'get_leaderboard' });
      }
      nameInput = 'done';
    }
    if (state && state.phase === 'waiting') nameInput = null;
  }, 500);

  initTowerButtons();
  flash('点击塔类型，再点击空地建塔。准备好后点"开始波次"', 3000);
})();
