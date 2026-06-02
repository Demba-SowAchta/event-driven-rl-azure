const API_URL = '/api/recent?limit=20';
let equityChart = null, actionChart = null;

async function loadData() {
  const btn = document.getElementById('refresh-btn');
  btn.disabled = true; btn.textContent = 'Loading...';
  try {
    const r = await fetch(API_URL);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    render(d.items || []);
    document.getElementById('last-update').textContent =
      'Updated ' + new Date().toLocaleTimeString();
  } catch (e) {
    console.error(e);
    document.getElementById('last-update').textContent = 'Error: ' + e.message;
  } finally {
    btn.disabled = false; btn.textContent = 'Refresh';
  }
}

const PALETTE = ['#065f46','#0891b2','#7c3aed','#db2777','#ea580c'];

function render(items) {
  // ----- KPIs -----
  const n = items.length;
  const avgRet = n ? items.reduce((s,i)=>s+(i.cumulative_return||0),0)/n : 0;
  const avgSharpe = n ? items.reduce((s,i)=>s+(i.sharpe_ratio||0),0)/n : 0;
  const avgLat = n ? items.reduce((s,i)=>s+(i.duration_ms||0),0)/n : 0;
  document.getElementById('kpi-episodes').textContent = n;
  document.getElementById('kpi-return').textContent = (avgRet*100).toFixed(2) + '%';
  document.getElementById('kpi-sharpe').textContent = avgSharpe.toFixed(2);
  document.getElementById('kpi-latency').textContent = avgLat.toFixed(1);

  // ----- Equity curves (5 most recent) -----
  if (equityChart) equityChart.destroy();
  const eqCtx = document.getElementById('equity-chart').getContext('2d');
  const recentEq = items.slice(0, 5).filter(i => i.equity_curve && i.equity_curve.length);
  const maxLen = recentEq.reduce((m,i) => Math.max(m, i.equity_curve.length), 0);
  const labels = Array.from({length: maxLen}, (_,i) => i);
  const datasets = recentEq.map((i, idx) => ({
    label: i.blob_name.slice(0, 20),
    data: i.equity_curve,
    borderColor: PALETTE[idx % PALETTE.length],
    backgroundColor: 'transparent',
    tension: 0.2,
    pointRadius: 0,
  }));
  equityChart = new Chart(eqCtx, {
    type: 'line',
    data: { labels, datasets },
    options: { responsive: true, maintainAspectRatio: false,
               scales: { y: { title: { display: true, text: 'Equity ($)' } } } }
  });

  // ----- Action distribution (aggregated) -----
  if (actionChart) actionChart.destroy();
  const totals = items.reduce((acc,i) => {
    acc.buy  += i.n_buy  || 0;
    acc.hold += i.n_hold || 0;
    acc.sell += i.n_sell || 0;
    return acc;
  }, {buy: 0, hold: 0, sell: 0});
  actionChart = new Chart(document.getElementById('action-chart').getContext('2d'), {
    type: 'doughnut',
    data: {
      labels: ['BUY','HOLD','SELL'],
      datasets: [{
        data: [totals.buy, totals.hold, totals.sell],
        backgroundColor: ['#059669','#6b7280','#dc2626'],
      }]
    },
    options: { responsive: true, maintainAspectRatio: false }
  });

  // ----- Table -----
  const tbody = document.querySelector('#recent-table tbody');
  tbody.innerHTML = '';
  for (const it of items) {
    const ret = (it.cumulative_return || 0) * 100;
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${new Date(it.timestamp).toLocaleString()}</td>
      <td>${it.blob_name}</td>
      <td>${it.algo}</td>
      <td>${it.agent_version}</td>
      <td>${it.n_steps}</td>
      <td class="${ret >= 0 ? 'pos' : 'neg'}">${ret.toFixed(2)}%</td>
      <td>${(it.sharpe_ratio||0).toFixed(2)}</td>
      <td class="neg">${((it.max_drawdown||0)*100).toFixed(2)}%</td>
      <td>${((it.win_rate||0)*100).toFixed(1)}%</td>
      <td>${it.n_buy}/${it.n_hold}/${it.n_sell}</td>
      <td>${(it.duration_ms||0).toFixed(1)}</td>
    `;
    tbody.appendChild(tr);
  }
}

loadData();
setInterval(loadData, 30000);
