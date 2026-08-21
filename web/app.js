/**
 * Clash Mi Gemini Guardian - 前端控制台交互脚本
 */

let allNodes = [];
let activeNode = null;
let currentRegionFilter = 'ALL';
let currentSearchQuery = '';
let isBenchmarking = false;
let guardianRunning = true;

// DOM 元素
const clashStatusBadge = document.getElementById('clashStatusBadge');
const clashStatusText = document.getElementById('clashStatusText');
const activeNodeFlag = document.getElementById('activeNodeFlag');
const activeNodeName = document.getElementById('activeNodeName');
const activeNodeDelay = document.getElementById('activeNodeDelay');
const activeNodeStatus = document.getElementById('activeNodeStatus');
const activeNodeGroup = document.getElementById('activeNodeGroup');
const guardianToggle = document.getElementById('guardianToggle');
const guardianDesc = document.getElementById('guardianDesc');
const benchmarkBtn = document.getElementById('benchmarkBtn');
const refreshBtn = document.getElementById('refreshBtn');
const searchInput = document.getElementById('searchInput');
const clearSearchBtn = document.getElementById('clearSearchBtn');
const nodesGrid = document.getElementById('nodesGrid');
const nodesSummaryText = document.getElementById('nodesSummaryText');
const logConsole = document.getElementById('logConsole');
const clearLogBtn = document.getElementById('clearLogBtn');
const themeToggleBtn = document.getElementById('themeToggleBtn');

// 国家/地区 Flag 提取
function extractFlag(name) {
  const emojiRegex = /(\u00a9|\u00ae|[\u2000-\u3300]|\ud83c[\ud000-\udfff]|\ud83d[\ud000-\udfff]|\ud83e[\ud000-\udfff])/;
  const match = name.match(emojiRegex);
  if (match) return match[0];
  const lower = name.toLowerCase();
  if (lower.includes('taiwan') || lower.includes('tw') || lower.includes('台湾')) return '🇹🇼';
  if (lower.includes('japan') || lower.includes('jp') || lower.includes('日本')) return '🇯🇵';
  if (lower.includes('singapore') || lower.includes('sg') || lower.includes('新加坡')) return '🇸🇬';
  if (lower.includes('malaysia') || lower.includes('my') || lower.includes('马来西亚')) return '🇲🇾';
  if (lower.includes('korea') || lower.includes('kr') || lower.includes('韩国')) return '🇰🇷';
  if (lower.includes('united states') || lower.includes('us') || lower.includes('美国')) return '🇺🇸';
  if (lower.includes('germany') || lower.includes('de') || lower.includes('德国')) return '🇩🇪';
  if (lower.includes('kingdom') || lower.includes('uk') || lower.includes('gb') || lower.includes('英国')) return '🇬🇧';
  if (lower.includes('netherlands') || lower.includes('nl') || lower.includes('荷兰')) return '🇳🇱';
  if (lower.includes('hong') || lower.includes('hk') || lower.includes('香港')) return '🇭🇰';
  return '🌐';
}

function classifyRegion(name) {
  const lower = name.toLowerCase();
  if (name.includes('🇹🇼') || lower.includes('taiwan') || lower.includes('tw') || lower.includes('台湾')) return 'TW';
  if (name.includes('🇯🇵') || lower.includes('japan') || lower.includes('jp') || lower.includes('日本')) return 'JP';
  if (name.includes('🇸🇬') || lower.includes('singapore') || lower.includes('sg') || lower.includes('新加坡')) return 'SG';
  if (name.includes('🇲🇾') || lower.includes('malaysia') || lower.includes('my') || lower.includes('马来西亚')) return 'MY';
  if (name.includes('🇰🇷') || lower.includes('korea') || lower.includes('kr') || lower.includes('韩国')) return 'KR';
  if (name.includes('🇺🇸') || lower.includes('united states') || lower.includes('us') || lower.includes('美国')) return 'US';
  if (name.includes('🇩🇪') || name.includes('🇬🇧') || name.includes('🇳🇱') || lower.includes('germany') || lower.includes('kingdom') || lower.includes('netherlands') || lower.includes('europe')) return 'EU';
  if (name.includes('🇭🇰') || lower.includes('hong kong') || lower.includes('hk') || lower.includes('香港')) return 'RESTRICTED';
  return 'OTHER';
}

// 显示 Toast
function showToast(msg, type = 'info') {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerText = msg;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

// 添加日志
function appendLog(text, level = 'info') {
  const entry = document.createElement('div');
  entry.className = `log-entry log-${level}`;
  const now = new Date().toLocaleTimeString();
  entry.innerText = `[${now}] ${text}`;
  logConsole.appendChild(entry);
  logConsole.scrollTop = logConsole.scrollHeight;
}

// 拉取系统与 Clash 状态
async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    if (data.clash_online) {
      clashStatusBadge.className = 'status-pill online';
      clashStatusText.innerText = `Clash 正常 (${data.clash_version || '9090'})`;
    } else {
      clashStatusBadge.className = 'status-pill offline';
      clashStatusText.innerText = 'Clash 未连接';
    }

    if (data.active_node) {
      activeNode = data.active_node;
      activeNodeName.innerText = activeNode;
      activeNodeFlag.innerText = extractFlag(activeNode);
      activeNodeGroup.innerText = `策略组: ${data.active_group || '节点选择'}`;

      if (data.active_delay !== undefined && data.active_delay < 9999) {
        activeNodeDelay.className = 'badge badge-success';
        activeNodeDelay.innerText = `延迟: ${data.active_delay} ms`;
      } else {
        activeNodeDelay.className = 'badge badge-neutral';
        activeNodeDelay.innerText = '延迟: 检测中';
      }

      if (data.active_status === 'OK') {
        activeNodeStatus.className = 'badge badge-success';
        activeNodeStatus.innerText = '🟢 Gemini 支持正常';
      } else if (data.active_status === 'RESTRICTED') {
        activeNodeStatus.className = 'badge badge-warning';
        activeNodeStatus.innerText = '🟡 地区受限 (HK)';
      } else {
        activeNodeStatus.className = 'badge badge-danger';
        activeNodeStatus.innerText = '🔴 连接异常';
      }
    }

    guardianRunning = !!data.guardian_running;
    guardianToggle.checked = guardianRunning;
    guardianDesc.innerText = guardianRunning ? '监控中：节点恶化或断流时毫秒级自动切换' : '已暂停自动守护，可手动测试切换';

    // 增量日志
    if (data.logs && Array.isArray(data.logs)) {
      data.logs.forEach(l => appendLog(l.msg, l.level));
    }
  } catch (err) {
    clashStatusBadge.className = 'status-pill offline';
    clashStatusText.innerText = '本地后台服务断开';
  }
}

// 拉取节点列表
async function fetchNodes() {
  try {
    const res = await fetch('/api/nodes');
    const data = await res.json();
    if (data.nodes) {
      allNodes = data.nodes;
      updateCounts();
      renderNodes();
    }
  } catch (err) {
    appendLog('获取节点列表失败: ' + err, 'error');
  }
}

// 更新标签栏计数
function updateCounts() {
  let countTW = 0, countJP = 0, countSG = 0, countMY = 0, countKR = 0, countUS = 0, countEU = 0, countRest = 0;
  allNodes.forEach(node => {
    const reg = classifyRegion(node.name);
    if (reg === 'TW') countTW++;
    else if (reg === 'JP') countJP++;
    else if (reg === 'SG') countSG++;
    else if (reg === 'MY') countMY++;
    else if (reg === 'KR') countKR++;
    else if (reg === 'US') countUS++;
    else if (reg === 'EU') countEU++;
    else if (reg === 'RESTRICTED') countRest++;
  });

  document.getElementById('countAll').innerText = allNodes.length;
  document.getElementById('countTW').innerText = countTW;
  document.getElementById('countJP').innerText = countJP;
  document.getElementById('countSG').innerText = countSG;
  document.getElementById('countMY').innerText = countMY;
  document.getElementById('countKR').innerText = countKR;
  document.getElementById('countUS').innerText = countUS;
  document.getElementById('countEU').innerText = countEU;
  document.getElementById('countRestricted').innerText = countRest;
}

// 渲染节点网格卡片
function renderNodes() {
  const filtered = allNodes.filter(node => {
    // 地区筛选
    if (currentRegionFilter !== 'ALL') {
      const reg = classifyRegion(node.name);
      if (reg !== currentRegionFilter) return false;
    }
    // 搜索过滤
    if (currentSearchQuery) {
      if (!node.name.toLowerCase().includes(currentSearchQuery.toLowerCase())) {
        return false;
      }
    }
    return true;
  });

  nodesSummaryText.innerText = `显示 ${filtered.length} / ${allNodes.length} 个节点`;

  if (filtered.length === 0) {
    nodesGrid.innerHTML = `
      <div class="loading-placeholder">
        <div style="font-size: 36px;">🔍</div>
        <div>没有找到匹配的代理节点</div>
      </div>
    `;
    return;
  }

  nodesGrid.innerHTML = filtered.map((node, index) => {
    const isActive = (node.name === activeNode);
    const flag = extractFlag(node.name);
    let statusBadgeHtml = '';
    let delayBadgeHtml = '';

    if (node.status === 'OK') {
      statusBadgeHtml = '<span class="badge badge-success">🟢 完美支持</span>';
      delayBadgeHtml = `<span class="badge badge-info">${node.delay} ms</span>`;
    } else if (node.status === 'RESTRICTED') {
      statusBadgeHtml = '<span class="badge badge-warning">🟡 地区受限</span>';
      delayBadgeHtml = `<span class="badge badge-warning">${node.delay} ms</span>`;
    } else {
      statusBadgeHtml = '<span class="badge badge-danger">🔴 异常/超时</span>';
      delayBadgeHtml = '<span class="badge badge-danger">--</span>';
    }

    return `
      <div class="node-card ${isActive ? 'is-active' : ''}">
        <div class="node-card-top">
          <div class="node-card-flag">${flag}</div>
          <div class="node-card-info">
            <div class="node-card-name" title="${node.name}">${node.name}</div>
            <div class="node-card-tags">
              ${statusBadgeHtml}
              ${delayBadgeHtml}
            </div>
          </div>
        </div>
        <div class="node-card-desc">${node.desc || '实测完成'}</div>
        <div class="node-card-actions">
          ${isActive 
            ? '<span class="active-pill-tag">✓ 当前使用中</span>' 
            : `<button class="switch-node-btn" onclick="switchTargetNode('${encodeURIComponent(node.name)}')">切换至此节点</button>`
          }
        </div>
      </div>
    `;
  }).join('');
}

// 切换到目标节点
window.switchTargetNode = async function(encodedNodeName) {
  const nodeName = decodeURIComponent(encodedNodeName);
  try {
    appendLog(`正在切换至节点: ${nodeName}...`, 'info');
    const res = await fetch('/api/switch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: nodeName })
    });
    const data = await res.json();
    if (data.ok) {
      showToast(`已成功切换到: ${nodeName}`, 'success');
      appendLog(`已成功切换至节点: ${nodeName}`, 'success');
      activeNode = nodeName;
      await fetchStatus();
      renderNodes();
    } else {
      showToast(`切换失败: ${data.msg}`, 'error');
      appendLog(`切换失败: ${data.msg}`, 'error');
    }
  } catch (err) {
    showToast(`请求失败: ${err}`, 'error');
  }
};

// 一键体检与最优切换
async function runBenchmark() {
  if (isBenchmarking) return;
  isBenchmarking = true;
  benchmarkBtn.disabled = true;
  benchmarkBtn.querySelector('.btn-icon').innerText = '⏳';
  benchmarkBtn.querySelector('.btn-text').innerText = '全量体检中...';
  appendLog('开始并发深度体检所有节点对 Google Gemini 的真实连通性...', 'info');

  try {
    const res = await fetch('/api/benchmark', { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      allNodes = data.nodes || [];
      if (data.best_node) {
        showToast(`体检完成！最优节点: ${data.best_node.name} (${data.best_node.delay}ms)`, 'success');
        appendLog(`体检完成，已自动切换至最优节点: ${data.best_node.name} (${data.best_node.delay}ms)`, 'success');
      } else {
        showToast('体检完成，但未发现完全正常的 Gemini 节点', 'warn');
      }
      updateCounts();
      await fetchStatus();
      renderNodes();
    } else {
      showToast(`体检失败: ${data.msg}`, 'error');
    }
  } catch (err) {
    showToast(`体检请求异常: ${err}`, 'error');
  } finally {
    isBenchmarking = false;
    benchmarkBtn.disabled = false;
    benchmarkBtn.querySelector('.btn-icon').innerText = '🚀';
    benchmarkBtn.querySelector('.btn-text').innerText = '一键体检与最优切换';
  }
}

// 自动守护切换
guardianToggle.addEventListener('change', async (e) => {
  const enabled = e.target.checked;
  try {
    const res = await fetch('/api/guardian/toggle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled })
    });
    const data = await res.json();
    showToast(enabled ? '后台自动守护已开启' : '后台自动守护已暂停', 'info');
    appendLog(enabled ? '后台自动守护已开启' : '后台自动守护已暂停', 'info');
    await fetchStatus();
  } catch (err) {
    showToast('设置自动守护失败', 'error');
  }
});

// 地区标签点击
document.getElementById('regionTabs').addEventListener('click', (e) => {
  const btn = e.target.closest('.tab-btn');
  if (!btn) return;
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  currentRegionFilter = btn.dataset.region;
  renderNodes();
});

// 搜索框事件
searchInput.addEventListener('input', (e) => {
  currentSearchQuery = e.target.value.trim();
  clearSearchBtn.style.display = currentSearchQuery ? 'block' : 'none';
  renderNodes();
});

clearSearchBtn.addEventListener('click', () => {
  searchInput.value = '';
  currentSearchQuery = '';
  clearSearchBtn.style.display = 'none';
  renderNodes();
});

// 主题切换
themeToggleBtn.addEventListener('click', () => {
  const root = document.documentElement;
  if (root.classList.contains('theme-light')) {
    root.classList.remove('theme-light');
    root.classList.add('theme-dark');
  } else {
    root.classList.remove('theme-dark');
    root.classList.add('theme-light');
  }
});

benchmarkBtn.addEventListener('click', runBenchmark);
refreshBtn.addEventListener('click', async () => {
  appendLog('正在刷新节点与 Clash 状态...', 'info');
  await fetchStatus();
  await fetchNodes();
  showToast('状态已刷新', 'info');
});

clearLogBtn.addEventListener('click', () => {
  logConsole.innerHTML = '<div class="log-entry log-info">[日志已清空]</div>';
});

// 初始化启动
(async function init() {
  await fetchStatus();
  await fetchNodes();
  // 首次进入如果尚未测速，自动触发一次体检
  if (allNodes.length > 0 && allNodes.every(n => n.delay === 99999 || n.delay === undefined)) {
    runBenchmark();
  }
  // 每 3 秒拉取一次状态与日志
  setInterval(fetchStatus, 3000);
})();
