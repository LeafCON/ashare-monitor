<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'

const API = ''
const CURRENCY_SYMBOLS = { 'USD': '$', 'CNY': '¥' }
const CURRENCY_NAMES = { 'USD': '美元', 'CNY': '人民币' }
const COLORS = ['#58a6ff', '#3fb950', '#bc8cff', '#d29922', '#f85149', '#79c0ff', '#56d364', '#d2a8ff', '#e3b341', '#ff7b72']

const tab = ref('dashboard')
const loading = ref(false)
const lastUpdate = ref('')
const moreMenuOpen = ref(false)

const themeMode = ref(localStorage.getItem('theme') || 'system')
const themeLabel = computed(() => {
  const m = { system: '跟随系统', dark: '暗色模式', light: '明色模式' }
  return m[themeMode.value] || '切换主题'
})

function applyTheme() {
  const mode = themeMode.value
  let actual = mode
  if (mode === 'system') {
    actual = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }
  document.documentElement.setAttribute('data-theme', actual)
  if (dashPieInstance) { dashPieInstance.dispose(); dashPieInstance = null }
  if (holdingPieInstance) { holdingPieInstance.dispose(); holdingPieInstance = null }
  if (holdingPnlInstance) { holdingPnlInstance.dispose(); holdingPnlInstance = null }
  nextTick(() => {
    if (tab.value === 'dashboard') renderDashPie()
    if (tab.value === 'portfolio') { renderHoldingPie(); renderHoldingPnl() }
  })
}

function cycleTheme() {
  const order = ['system', 'dark', 'light']
  const idx = order.indexOf(themeMode.value)
  themeMode.value = order[(idx + 1) % order.length]
  localStorage.setItem('theme', themeMode.value)
  applyTheme()
}

const mql = window.matchMedia('(prefers-color-scheme: dark)')
function onSystemThemeChange() { if (themeMode.value === 'system') applyTheme() }

const prices = ref([])
const portfolio = ref(null)
const recentAlerts = ref([])
const recentTx = ref([])
const transactions = ref([])
const alertSettings = ref([])
const alertGroupsRaw = ref([])
const alertHistory = ref([])
const cashAccounts = ref([])
const cashLogs = ref([])
const totalAssets = ref(null)
const testingAlert = ref(false)
const stockQuery = ref('')
const searchResults = ref([])
let searchTimer = null
const holdingForm = ref({ symbol: '', name: '', shares: null, cost_price: null, market: 'cn' })
const notifyStatus = ref(null)
const showAddAlert = ref(false)
const showAddTx = ref(false)
const historyFilter = ref('')

const alertViewMode = ref(localStorage.getItem('alertViewMode') || 'card')
function setAlertViewMode(mode) {
  alertViewMode.value = mode
  localStorage.setItem('alertViewMode', mode)
}

const watchlistData = ref([])

// ── New feature data refs ──────────────────────────────────────────────────
const macroIndicators = ref([])
const earningsUpcoming = ref([])
const earningsRecent = ref([])
const earningsAnalysis = ref([])

const earningsRecentGrouped = computed(() => {
  const map = {}
  for (const e of earningsRecent.value) {
    if (!map[e.symbol]) map[e.symbol] = { symbol: e.symbol, name: e.name, records: [] }
    map[e.symbol].records.push(e)
  }
  // 每组内按日期倒序
  for (const g of Object.values(map)) {
    g.records.sort((a, b) => (b.report_date || '').localeCompare(a.report_date || ''))
  }
  return Object.values(map)
})

// 生成 EPS sparkline SVG path
function epsSparkline(records) {
  // 按日期正序取有实际EPS的点
  const pts = records
    .filter(r => r.actual_eps != null)
    .slice()
    .sort((a, b) => (a.report_date || '').localeCompare(b.report_date || ''))
  if (pts.length < 2) return null

  const W = 80, H = 28, PAD = 3
  const vals = pts.map(p => p.actual_eps)
  const minV = Math.min(...vals)
  const maxV = Math.max(...vals)
  const range = maxV - minV || 1

  const coords = pts.map((p, i) => {
    const x = PAD + (i / (pts.length - 1)) * (W - PAD * 2)
    const y = PAD + (1 - (p.actual_eps - minV) / range) * (H - PAD * 2)
    return [x, y]
  })

  const path = coords.map((c, i) => `${i === 0 ? 'M' : 'L'}${c[0].toFixed(1)},${c[1].toFixed(1)}`).join(' ')
  const last = coords[coords.length - 1]
  const trend = vals[vals.length - 1] >= vals[vals.length - 2] ? 'up' : 'down'
  return { path, W, H, last, trend, pts }
}
const earningsLoading = ref(false)
const snapshotHistory = ref([])
const netWorthChartRef = ref(null)
let netWorthChartInstance = null

const alertsByPhase = computed(() => {
  const allGroups = alertGroupsRaw.value
  const holdings = portfolio.value?.holdings || []
  const holdingMap = {}
  for (const h of holdings) holdingMap[h.symbol] = h
  const phases = {
    building: { key: 'building', icon: '📥', label: '建仓中', items: [] },
    holding: { key: 'holding', icon: '📊', label: '持仓中', items: [] },
    exiting: { key: 'exiting', icon: '📤', label: '止盈止损', items: [] },
  }
  for (const group of allGroups) {
    const holding = holdingMap[group.symbol]
    const allLevels = []
    if (group.primary) allLevels.push(group.primary)
    if (group.levels) allLevels.push(...group.levels)
    const hasHolding = !!holding && holding.shares > 0
    const hasExitOnly = allLevels.every(l => !l.target_buy && (l.target_sell || l.stop_loss))
    const enrichedGroup = { ...group, holding: holding || null, allLevels }
    if (!hasHolding) phases.building.items.push(enrichedGroup)
    else if (hasExitOnly) phases.exiting.items.push(enrichedGroup)
    else phases.holding.items.push(enrichedGroup)
  }
  return [phases.building, phases.holding, phases.exiting].filter(p => p.items.length > 0)
})

const cardTimelineData = computed(() => {
  const allGroups = alertGroupsRaw.value
  const holdings = portfolio.value?.holdings || []
  const holdingMap = {}
  for (const h of holdings) holdingMap[h.symbol] = h
  return allGroups.map(group => {
    const holding = holdingMap[group.symbol]
    const currentPrice = group.current_price
    const allLevels = []
    if (group.primary) allLevels.push(group.primary)
    if (group.levels) allLevels.push(...group.levels)
    const pricePoints = []
    for (const level of allLevels) {
      if (level.target_buy) pricePoints.push({ price: level.target_buy, type: 'buy', label: level.label || (level.is_primary ? '建仓' : '加仓'), amount: level.amount || '', enabled: level.enabled })
      if (level.target_sell) pricePoints.push({ price: level.target_sell, type: 'sell', label: level.label || '止盈', amount: level.amount || '', enabled: level.enabled })
      if (level.stop_loss) pricePoints.push({ price: level.stop_loss, type: 'stop', label: '止损', amount: level.amount || '', enabled: level.enabled })
    }
    pricePoints.sort((a, b) => b.price - a.price)
    const timelineRows = []
    let currentInserted = false
    for (let i = 0; i < pricePoints.length; i++) {
      if (currentPrice && !currentInserted && currentPrice >= pricePoints[i].price) {
        timelineRows.push({ isCurrent: true, price: currentPrice })
        currentInserted = true
      }
      timelineRows.push({ isCurrent: false, ...pricePoints[i] })
    }
    if (currentPrice && !currentInserted) timelineRows.push({ isCurrent: true, price: currentPrice })
    let buildProgress = null
    if (holding && holding.shares > 0) {
      const totalBuyAmount = allLevels.reduce((sum, l) => {
        if (l.target_buy && l.amount) { const match = l.amount.match(/[\d,]+/); if (match) return sum + parseFloat(match[0].replace(/,/g, '')) }
        return sum
      }, 0)
      const investedAmount = holding.shares * holding.avg_cost
      const totalPlanned = totalBuyAmount + investedAmount
      if (totalPlanned > 0) buildProgress = Math.min(100, Math.round((investedAmount / totalPlanned) * 100))
    }
    return { symbol: group.symbol, name: group.name, market: group.market, currentPrice, changePct: group.change_pct, holding, marketValue: holding ? holding.market_value : null, pricePoints, timelineRows, buildProgress }
  })
})

const collapsed = ref({})
function isCollapsed(key) { return collapsed.value[key] === true }
function toggleCollapse(key) { collapsed.value = { ...collapsed.value, [key]: !collapsed.value[key] } }

const dashPieChart = ref(null)
const holdingPieChart = ref(null)
const holdingPnlChart = ref(null)
let dashPieInstance = null
let holdingPieInstance = null
let holdingPnlInstance = null

const alertGroupsByMarket = computed(() => {
  const groups = alertGroupsRaw.value
  const markets = [{ key: 'us', label: '美股', stocks: [] }, { key: 'cn', label: 'A股', stocks: [] }]
  const mm = {}
  for (const m of markets) mm[m.key] = m
  for (const g of groups) { const k = g.market || 'us'; (mm[k] || mm['us']).stocks.push(g) }
  for (const m of markets) m.stocks.sort((a, b) => a.symbol.localeCompare(b.symbol))
  return markets
})

const txForm = ref({ symbol: '', name: '', action: 'buy', price: null, shares: null, fee: 0, date: '', notes: '' })
const txFilter = ref({ symbol: '' })
const alertForm = ref({ symbol: '', name: '', market: 'cn', is_primary: true, label: '', target_buy: null, target_sell: null, stop_loss: null, pct_threshold: null, amount: '' })
const cashForm = ref({ currency: 'USD', amount: null, notes: '' })

// 获取 Telegram initData（每次请求时实时读取，避免 SDK 未初始化时取到空值）
function getTgInitData() { return window.Telegram?.WebApp?.initData || '' }

async function api(method, path, body) {
  const headers = { 'Content-Type': 'application/json' }
  const tgInitData = getTgInitData()
  if (tgInitData) headers['X-Telegram-Init-Data'] = tgInitData
  const opts = { method, headers }
  if (body) opts.body = JSON.stringify(body)
  const res = await fetch(API + path, opts)
  if (!res.ok) { const e = await res.json().catch(() => null); throw new Error(e?.detail || 'HTTP ' + res.status) }
  if (res.status === 204) return null
  return res.json()
}

async function loadDashboard() {
  loading.value = true
  try {
    const data = await api('GET', '/api/dashboard')
    prices.value = data.prices; portfolio.value = data.portfolio; recentAlerts.value = data.recent_alerts
    recentTx.value = data.recent_transactions; cashAccounts.value = data.cash_accounts || []; totalAssets.value = data.total_assets
    lastUpdate.value = new Date().toLocaleTimeString('zh-CN')
    nextTick(() => { if (tab.value === 'dashboard') renderDashPie() })
  } catch (e) { console.error('Dashboard error:', e) }
  finally { loading.value = false }
}
async function loadTransactions() { try { transactions.value = await api('GET', '/api/transactions?limit=200') } catch (e) { console.error(e) } }
async function loadAlerts() {
  try {
    alertSettings.value = await api('GET', '/api/alerts')
    alertGroupsRaw.value = await api('GET', '/api/alerts/grouped')
    alertHistory.value = await api('GET', '/api/alerts/history?limit=100')
    watchlistData.value = await api('GET', '/api/watchlist')
    notifyStatus.value = await api('GET', '/api/alerts/notify-status')
  } catch (e) { console.error(e) }
}
async function loadPortfolio() {
  try { portfolio.value = await api('GET', '/api/portfolio'); nextTick(() => { if (tab.value === 'portfolio') { renderHoldingPie(); renderHoldingPnl() } }) } catch (e) { console.error(e) }
}
async function loadCashAccounts() {
  try { cashAccounts.value = await api('GET', '/api/cash') } catch (e) { console.error('cash load error', e) }
  try { cashLogs.value = await api('GET', '/api/cash/logs?limit=30') } catch (e) { console.error('cash logs error', e) }
}

// ── Macro Indicators ───────────────────────────────────────────────────────
async function loadMacro() {
  try { macroIndicators.value = await api('GET', '/api/macro') } catch (e) { console.error('Macro load error:', e) }
}
function onStockQuery() {
  clearTimeout(searchTimer)
  const q = stockQuery.value.trim()
  if (!q) { searchResults.value = []; return }
  searchTimer = setTimeout(async () => {
    try { searchResults.value = await api('GET', '/api/search?q=' + encodeURIComponent(q)) }
    catch (e) { console.error(e) }
  }, 300)
}
async function addSearched(item) {
  try {
    await api('POST', '/api/watchlist', { symbol: item.symbol, name: item.name, market: item.market, secid: item.secid, enabled: true })
    stockQuery.value = ''
    searchResults.value = []
    await loadDashboard()
    await loadAlerts()
  } catch (e) { alert('添加失败: ' + e.message) }
}
async function saveHolding() {
  const f = holdingForm.value
  if (!f.symbol || f.shares == null || f.cost_price == null) { alert('请填写代码、股数和成本价'); return }
  try {
    portfolio.value = await api('POST', '/api/portfolio/holdings', { symbol: f.symbol, name: f.name, shares: f.shares, cost_price: f.cost_price, market: f.market })
    holdingForm.value = { symbol: '', name: '', shares: null, cost_price: null, market: 'cn' }
    loadDashboard(); loadAlerts()
    nextTick(() => { renderHoldingPie(); renderHoldingPnl() })
  } catch (e) { alert('保存持仓失败: ' + e.message) }
}
function editHolding(h) {
  const cn = h.symbol.endsWith('.SS') || h.symbol.endsWith('.SZ') || h.symbol.endsWith('.BJ')
  holdingForm.value = { symbol: h.symbol, name: h.name, shares: h.shares, cost_price: Number(h.avg_cost.toFixed(4)), market: cn ? 'cn' : 'us' }
  window.scrollTo({ top: 0, behavior: 'smooth' })
}
async function removeHolding(symbol) {
  if (!confirm('删除 ' + symbol + ' 的持仓记录？')) return
  try {
    portfolio.value = await api('DELETE', '/api/portfolio/holdings/' + encodeURIComponent(symbol))
    loadDashboard()
    nextTick(() => { renderHoldingPie(); renderHoldingPnl() })
  } catch (e) { alert('删除失败: ' + e.message) }
}

// ── Earnings Calendar ──────────────────────────────────────────────────────
async function loadEarnings() {
  earningsLoading.value = true
  try {
    const [up, rec, analysis] = await Promise.all([
      api('GET', '/api/earnings/upcoming'),
      api('GET', '/api/earnings/recent'),
      api('GET', '/api/earnings/analysis'),
    ])
    earningsUpcoming.value = up || []
    earningsRecent.value = rec || []
    earningsAnalysis.value = analysis || []
  } catch (e) { console.error('Earnings load error:', e) }
  finally { earningsLoading.value = false }
}

// ── Snapshot History ───────────────────────────────────────────────────────
async function loadSnapshots() {
  try {
    snapshotHistory.value = await api('GET', '/api/snapshots/history?days=90')
    nextTick(() => { if (tab.value === 'dashboard') renderNetWorthChart() })
  } catch (e) { console.error('Snapshots load error:', e) }
}

function renderNetWorthChart() {
  if (!netWorthChartRef.value || snapshotHistory.value.length < 2) return
  const t = getChartTheme()
  const data = snapshotHistory.value
  const dates = data.map(d => d.date)
  const values = data.map(d => d.total_assets_usd)

  if (netWorthChartInstance) netWorthChartInstance.dispose()
  netWorthChartInstance = echarts.init(netWorthChartRef.value)
  netWorthChartInstance.setOption({
    tooltip: {
      trigger: 'axis',
      backgroundColor: t.tooltipBg,
      borderColor: t.borderColor,
      textStyle: { color: t.textColor },
      formatter: function(params) {
        const idx = params[0].dataIndex
        const d = data[idx]
        const fxRate = totalAssets.value?.usd_to_cny || 7.2
        return `<b>${d.date}</b><br/>总资产: $${d.total_assets_usd.toLocaleString()}<br/>股票: $${d.stock_value_usd.toLocaleString()}<br/>现金: $${(d.cash_usd + d.cash_cny / fxRate).toFixed(0).replace(/\\B(?=(\\d{3})+(?!\\d))/g, ',')}`
      }
    },
    grid: { left: 60, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: dates, axisLabel: { color: t.textColor, fontSize: 10, rotate: 30 }, axisLine: { lineStyle: { color: t.borderColor } } },
    yAxis: { type: 'value', axisLabel: { color: t.textColor, formatter: '${value}' }, splitLine: { lineStyle: { color: t.splitLineColor } } },
    series: [{
      type: 'line', data: values, smooth: true,
      lineStyle: { width: 2, color: '#58a6ff' },
      areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(88,166,255,0.3)' }, { offset: 1, color: 'rgba(88,166,255,0.02)' }] } },
      itemStyle: { color: '#58a6ff' },
    }],
  }, true)
  netWorthChartInstance.resize()
}

// ── Quant Signals ──────────────────────────────────────────────────────────
const quantSignals = ref([])
const quantLoading = ref(false)
const quantRefreshing = ref(false)
const quantExpandedSymbol = ref(null)
const quantHistoryData = ref([])
const quantPeChartRef = ref(null)
let quantPeChartInstance = null

async function loadQuantSignals() {
  quantLoading.value = true
  try { quantSignals.value = await api('GET', '/api/quant/signals') } catch (e) { console.error('Quant load error:', e) }
  finally { quantLoading.value = false }
}

async function refreshQuant() {
  quantRefreshing.value = true
  try {
    // 同步等待接口返回（后端现在是同步执行，约20秒）
    await api('POST', '/api/quant/refresh')
    await loadQuantSignals()
  } catch (e) { alert('刷新失败: ' + e.message) }
  finally { quantRefreshing.value = false }
}

async function toggleQuantDetail(symbol) {
  if (quantExpandedSymbol.value === symbol) { quantExpandedSymbol.value = null; return }
  quantExpandedSymbol.value = symbol
  try {
    quantHistoryData.value = await api('GET', '/api/quant/signals/' + symbol + '?metric=pe_ttm')
    nextTick(() => renderQuantPeChart())
  } catch (e) { console.error(e) }
}

function renderQuantPeChart() {
  if (!quantPeChartRef.value || !quantHistoryData.value.length) return
  const t = getChartTheme()
  const data = quantHistoryData.value.filter(d => d.value != null).map(d => ([d.date.split('T')[0], d.value]))
  const pctData = quantHistoryData.value.filter(d => d.percentile != null).map(d => ([d.date.split('T')[0], d.percentile]))
  if (quantPeChartInstance) quantPeChartInstance.dispose()
  quantPeChartInstance = echarts.init(quantPeChartRef.value)
  quantPeChartInstance.setOption({
    tooltip: { trigger: 'axis', backgroundColor: t.tooltipBg, borderColor: t.borderColor, textStyle: { color: t.textColor } },
    legend: { data: ['PE(TTM)', '分位(%)'], bottom: 0, textStyle: { color: t.textColor } },
    grid: { left: 50, right: 50, top: 20, bottom: 40 },
    xAxis: { type: 'category', data: data.map(d => d[0]), axisLabel: { color: t.textColor, fontSize: 10, rotate: 30 }, axisLine: { lineStyle: { color: t.borderColor } } },
    yAxis: [
      { type: 'value', name: 'PE', axisLabel: { color: t.textColor }, splitLine: { lineStyle: { color: t.splitLineColor } } },
      { type: 'value', name: '分位%', min: 0, max: 100, axisLabel: { color: t.textColor }, splitLine: { show: false } },
    ],
    series: [
      { name: 'PE(TTM)', type: 'line', data: data.map(d => d[1]), smooth: true, lineStyle: { width: 2 }, itemStyle: { color: '#58a6ff' } },
      { name: '分位(%)', type: 'line', yAxisIndex: 1, data: pctData.map(d => d[1]), smooth: true, lineStyle: { width: 2, type: 'dashed' }, itemStyle: { color: '#d29922' },
        markArea: { silent: true, data: [[{ yAxis: 0, itemStyle: { color: 'rgba(63,185,80,0.08)' } }, { yAxis: 20 }], [{ yAxis: 80, itemStyle: { color: 'rgba(248,81,73,0.08)' } }, { yAxis: 100 }]] } },
    ],
  }, true)
  quantPeChartInstance.resize()
}

function pctColor(pct) {
  if (pct == null) return ''
  if (pct < 20) return '#3fb950'
  if (pct < 50) return '#58a6ff'
  if (pct < 80) return '#d29922'
  return '#f85149'
}

function pctLabel(pct) {
  if (pct == null) return '-'
  if (pct < 20) return '低估'
  if (pct < 50) return '偏低'
  if (pct < 80) return '偏高'
  return '高估'
}

function scoreColor(score) {
  if (score == null) return ''
  if (score < 30) return '#3fb950'
  if (score < 50) return '#58a6ff'
  if (score < 70) return '#d29922'
  return '#f85149'
}

function scoreLabel(score) {
  if (score == null) return '-'
  if (score < 30) return '低估值'
  if (score < 50) return '合理偏低'
  if (score < 70) return '合理偏高'
  return '高估值'
}

function metricLabel(m) {
  return { pe_ttm: 'PE(TTM)', pb: 'PB', roe: 'ROE', gross_margin: '毛利率', revenue_growth: '营收增长' }[m] || m
}

function metricUnit(m) {
  return { roe: '%', gross_margin: '%', revenue_growth: '%' }[m] || ''
}

function switchTab(t) {
  tab.value = t
  moreMenuOpen.value = false
  nextTick(() => {
    if (t === 'dashboard') { if (dashPieInstance) { dashPieInstance.dispose(); dashPieInstance = null }; renderDashPie(); renderNetWorthChart() }
    if (t === 'portfolio') { if (holdingPieInstance) { holdingPieInstance.dispose(); holdingPieInstance = null }; if (holdingPnlInstance) { holdingPnlInstance.dispose(); holdingPnlInstance = null }; renderHoldingPie(); renderHoldingPnl() }
    if (t === 'quant') { loadQuantSignals() }
    if (t === 'earnings') { loadEarnings() }
  })
}

function getChartTheme() {
  const actual = document.documentElement.getAttribute('data-theme') || 'dark'
  return actual === 'light'
    ? { bg: 'transparent', textColor: '#1f2328', borderColor: '#d0d7de', splitLineColor: '#e1e4e8', tooltipBg: '#ffffff' }
    : { bg: 'transparent', textColor: '#e6edf3', borderColor: '#21262d', splitLineColor: '#30363d', tooltipBg: '#161b22' }
}

function renderDashPie() {
  if (!dashPieChart.value || !totalAssets.value) return
  const t = getChartTheme(); const ta = totalAssets.value; const rate = ta.usd_to_cny || 7.2
  const data = [{ name: '美股', value: Math.round(ta.stock_value_usd) }, { name: 'A股', value: Math.round((ta.stock_value_cny || 0) / rate) }, { name: '美元现金', value: Math.round(ta.cash_usd) }, { name: '人民币现金', value: Math.round((ta.cash_cny || 0) / rate) }].filter(d => d.value > 0)
  if (!dashPieInstance) dashPieInstance = echarts.init(dashPieChart.value)
  dashPieInstance.setOption({ tooltip: { trigger: 'item', formatter: '{b}: ${c} ({d}%)', backgroundColor: t.tooltipBg, borderColor: t.borderColor, textStyle: { color: t.textColor } }, legend: { bottom: 0, textStyle: { color: t.textColor, fontSize: 12 } }, color: COLORS, series: [{ type: 'pie', radius: ['40%', '70%'], center: ['50%', '45%'], avoidLabelOverlap: true, itemStyle: { borderRadius: 6, borderColor: t.bg === 'transparent' ? undefined : t.bg, borderWidth: 2 }, label: { show: true, color: t.textColor, formatter: '{b}\n${c}', fontSize: 12 }, emphasis: { label: { fontSize: 14, fontWeight: 'bold' } }, data }] }, true)
  dashPieInstance.resize()
}

function renderHoldingPie() {
  if (!holdingPieChart.value || !portfolio.value) return
  const t = getChartTheme(); const holdings = portfolio.value.holdings || []
  const data = holdings.map(h => ({ name: h.symbol + ' ' + h.name, value: Math.round(h.market_value_usd || h.market_value) }))
  if (data.length === 0) return
  if (!holdingPieInstance) holdingPieInstance = echarts.init(holdingPieChart.value)
  holdingPieInstance.setOption({ tooltip: { trigger: 'item', formatter: '{b}: ${c} ({d}%)', backgroundColor: t.tooltipBg, borderColor: t.borderColor, textStyle: { color: t.textColor } }, legend: { type: 'scroll', bottom: 0, textStyle: { color: t.textColor, fontSize: 11 } }, color: COLORS, series: [{ type: 'pie', radius: ['35%', '65%'], center: ['50%', '42%'], itemStyle: { borderRadius: 6 }, label: { show: true, color: t.textColor, formatter: '{b}\n{d}%', fontSize: 11 }, data }] }, true)
  holdingPieInstance.resize()
}

function renderHoldingPnl() {
  if (!holdingPnlChart.value || !portfolio.value) return
  const t = getChartTheme(); const holdings = portfolio.value.holdings || []
  if (holdings.length === 0) return
  const sorted = [...holdings].sort((a, b) => (b.unrealized_pnl_usd || b.unrealized_pnl) - (a.unrealized_pnl_usd || a.unrealized_pnl))
  const names = sorted.map(h => h.symbol); const values = sorted.map(h => h.unrealized_pnl_usd || h.unrealized_pnl)
  const colors = values.map(v => v >= 0 ? '#3fb950' : '#f85149')
  if (!holdingPnlInstance) holdingPnlInstance = echarts.init(holdingPnlChart.value)
  holdingPnlInstance.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, backgroundColor: t.tooltipBg, borderColor: t.borderColor, textStyle: { color: t.textColor }, formatter: function(params) { const p = params[0]; const h = sorted[p.dataIndex]; return '<b>' + h.symbol + '</b> ' + h.name + '<br/>盈亏: $' + (h.unrealized_pnl_usd || h.unrealized_pnl).toFixed(2) + '<br/>收益率: ' + h.pnl_pct.toFixed(2) + '%' } },
    grid: { left: 60, right: 20, top: 10, bottom: 30 },
    xAxis: { type: 'category', data: names, axisLabel: { color: t.textColor, fontSize: 11, fontFamily: 'SF Mono, monospace' }, axisLine: { lineStyle: { color: t.borderColor } } },
    yAxis: { type: 'value', axisLabel: { color: t.textColor, formatter: '${value}' }, splitLine: { lineStyle: { color: t.splitLineColor } }, axisLine: { lineStyle: { color: t.borderColor } } },
    series: [{ type: 'bar', data: values.map((v, i) => ({ value: v, itemStyle: { color: colors[i], borderRadius: [4, 4, 0, 0] } })), barMaxWidth: 40 }]
  }, true)
  holdingPnlInstance.resize()
}

async function addTransaction() {
  const f = txForm.value
  const body = { symbol: f.symbol.toUpperCase(), name: f.name, action: f.action, price: f.price, shares: f.shares, fee: f.fee || 0, notes: f.notes || null }
  if (f.date) body.date = new Date(f.date).toISOString()
  try { await api('POST', '/api/transactions', body); txForm.value = { symbol: '', name: '', action: 'buy', price: null, shares: null, fee: 0, date: '', notes: '' }; loadTransactions(); loadPortfolio(); loadDashboard(); loadCashAccounts() } catch (e) { alert('添加失败: ' + e.message) }
}
async function deleteTx(id) { if (!confirm('确认删除？')) return; try { await api('DELETE', '/api/transactions/' + id); loadTransactions(); loadPortfolio(); loadDashboard(); loadCashAccounts() } catch (e) { alert('删除失败: ' + e.message) } }
async function saveAlert() {
  const f = alertForm.value
  const body = { symbol: f.symbol.toUpperCase(), name: f.name, market: f.market, is_primary: f.is_primary, label: f.is_primary ? null : (f.label || null), target_buy: f.target_buy || null, target_sell: f.target_sell || null, stop_loss: f.stop_loss || null, pct_threshold: f.pct_threshold == null || f.pct_threshold === '' ? null : f.pct_threshold, amount: f.amount || null, enabled: true }
  try { await api('POST', '/api/alerts', body); alertForm.value = { symbol: '', name: '', market: 'cn', is_primary: true, label: '', target_buy: null, target_sell: null, stop_loss: null, pct_threshold: null, amount: '' }; loadAlerts() } catch (e) { alert('保存失败: ' + e.message) }
}
async function toggleAlert(a) { try { await api('PUT', '/api/alerts/' + a.id, { enabled: !a.enabled }); loadAlerts() } catch (e) { alert('切换失败') } }
async function deleteAlert(id) { if (!confirm('确认删除？')) return; try { await api('DELETE', '/api/alerts/' + id); loadAlerts() } catch (e) { alert('删除失败') } }
async function testAlert(mode) {
  testingAlert.value = true
  try {
    const r = await api('POST', '/api/alerts/test-send?mode=' + mode)
    if (mode === 'dry') alert('只打印，没有发送 Telegram：\n\n' + r.text)
    else alert(r.sent ? '已发送到 Telegram：\n\n' + r.text : ('没有发送：' + (r.detail || '失败') + '\n\n' + r.text))
  } catch (e) { alert('测试失败: ' + e.message) }
  finally { testingAlert.value = false }
}
async function toggleAutoOrder(ev) {
  const want = ev.target.checked
  if (want && !confirm('打开后仍不会向券商提交委托，也不会保存交易密码。确定只打开这个开关？')) {
    ev.target.checked = false
    return
  }
  try {
    const r = await api('PUT', '/api/alerts/trading', { auto_order: want })
    alert(r.detail)
    notifyStatus.value = await api('GET', '/api/alerts/notify-status')
  } catch (e) {
    alert('切换失败: ' + e.message)
    if (notifyStatus.value) ev.target.checked = !!notifyStatus.value.auto_order
  }
}
async function adjustCash() { const f = cashForm.value; if (!f.amount) { alert('请输入金额'); return }; try { await api('POST', '/api/cash/adjust', { currency: f.currency, amount: parseFloat(f.amount), notes: f.notes || null }); cashForm.value = { currency: 'USD', amount: null, notes: '' }; loadCashAccounts(); loadDashboard() } catch (e) { alert('调整失败: ' + e.message) } }

const filteredTx = computed(() => { const f = txFilter.value.symbol.toUpperCase(); if (!f) return transactions.value; return transactions.value.filter(t => t.symbol.includes(f)) })

const txGroupedByDate = computed(() => {
  const groups = {}
  for (const t of filteredTx.value) {
    const day = (t.date || '').slice(0, 10)
    if (!groups[day]) groups[day] = []
    groups[day].push(t)
  }
  return Object.entries(groups).sort((a, b) => b[0].localeCompare(a[0]))
})

const txStats = computed(() => {
  let totalBuy = 0, totalSell = 0, totalFee = 0
  for (const t of filteredTx.value) {
    if (t.action === 'buy') totalBuy += (t.amount || 0)
    else totalSell += (t.amount || 0)
    totalFee += (t.fee || 0)
  }
  return { totalBuy, totalSell, netIn: totalBuy - totalSell, totalFee, count: filteredTx.value.length }
})
const filteredHistory = computed(() => { const f = historyFilter.value.toUpperCase(); if (!f) return alertHistory.value; return alertHistory.value.filter(a => a.symbol.includes(f)) })
const usStockPrices = computed(() => prices.value.filter(p => p.currency !== 'CNY'))
const cnStockPrices = computed(() => prices.value.filter(p => p.currency === 'CNY'))
const usHoldings = computed(() => { if (!portfolio.value?.holdings) return []; const cn = new Set(cnStockPrices.value.map(p => p.symbol)); return portfolio.value.holdings.filter(h => !cn.has(h.symbol)) })
const cnHoldings = computed(() => { if (!portfolio.value?.holdings) return []; const cn = new Set(cnStockPrices.value.map(p => p.symbol)); return portfolio.value.holdings.filter(h => cn.has(h.symbol)) })
function getHolding(symbol) { if (!portfolio.value?.holdings) return null; return portfolio.value.holdings.find(h => h.symbol === symbol) }

// Build progress map for portfolio holdings (reuses cardTimelineData logic)
const holdingBuildProgress = computed(() => {
  const map = {}
  for (const stock of cardTimelineData.value) {
    if (stock.buildProgress != null && stock.holding) {
      const allLevels = []
      const group = alertGroupsRaw.value.find(g => g.symbol === stock.symbol)
      if (!group) continue
      if (group.primary) allLevels.push(group.primary)
      if (group.levels) allLevels.push(...group.levels)
      const totalBuyAmount = allLevels.reduce((sum, l) => {
        if (l.target_buy && l.amount) { const match = l.amount.match(/[\d,]+/); if (match) return sum + parseFloat(match[0].replace(/,/g, '')) }
        return sum
      }, 0)
      const investedAmount = stock.holding.shares * stock.holding.avg_cost
      const totalPlanned = totalBuyAmount + investedAmount
      map[stock.symbol] = { pct: stock.buildProgress, invested: investedAmount, planned: totalPlanned }
    }
  }
  return map
})

function fmtPrice(v, currency) { if (v == null) return '-'; return (currency === 'CNY' ? '¥' : '$') + v.toFixed(2) }
function fmtChange(v) { if (v == null) return '-'; return (v >= 0 ? '+' : '') + v.toFixed(2) }
function fmtPct(v) { if (v == null) return '-'; return (v >= 0 ? '+' : '') + v.toFixed(2) + '%' }
function fmtNum(v, decimals = 2) { if (v == null) return '0'; return v.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) }

// 资产构成饼图数据 + SVG arc
function cashPieSegments(ta) {
  if (!ta) return []
  const rate = ta.usd_to_cny || 7.2
  const usStock = ta.stock_value_usd || 0
  const cnStock = (ta.stock_value_cny || 0) / rate
  const usdCash = ta.cash_usd || 0
  const cnyCash = (ta.cash_cny || 0) / rate
  const total = ta.total_assets_usd || 1

  const items = [
    { label: '美股', val: '$' + fmtNum(usStock, 0), raw: usStock, color: '#58a6ff' },
    { label: 'A股', val: '¥' + fmtNum(ta.stock_value_cny || 0, 0), raw: cnStock, color: '#3fb950' },
    { label: '美元现金', val: '$' + fmtNum(usdCash, 0), raw: usdCash, color: '#d29922' },
    { label: '人民币现金', val: '¥' + fmtNum(ta.cash_cny || 0, 0), raw: cnyCash, color: '#a371f7' },
  ].filter(i => i.raw > 0)

  // 计算 SVG arc path
  const cx = 60, cy = 60, r = 46
  let startAngle = -Math.PI / 2
  return items.map(item => {
    const pct = Math.round(item.raw / total * 100)
    const angle = (item.raw / total) * Math.PI * 2
    const endAngle = startAngle + angle
    const x1 = cx + r * Math.cos(startAngle), y1 = cy + r * Math.sin(startAngle)
    const x2 = cx + r * Math.cos(endAngle), y2 = cy + r * Math.sin(endAngle)
    const large = angle > Math.PI ? 1 : 0
    const d = `M${cx},${cy} L${x1.toFixed(2)},${y1.toFixed(2)} A${r},${r} 0 ${large},1 ${x2.toFixed(2)},${y2.toFixed(2)} Z`
    startAngle = endAngle
    return { ...item, d, pct }
  })
}
function fmtDate(d) { if (!d) return '-'; return new Date(d).toLocaleDateString('zh-CN') }
function fmtTime(d) { if (!d) return '-'; return new Date(d).toLocaleString('zh-CN') }
function pnlClass(v) { if (v == null || v === 0) return ''; return v > 0 ? 'positive' : 'negative' }
function alertTypeLabel(t) { return { target_buy: '跌破', target_sell: '突破', price_cross_down: '跌破', price_cross_up: '突破', stop_loss: '止损告警', pct_change: '涨跌幅', big_change: '涨跌幅' }[t] || t }
function marketCurrSym(m) { return m === 'cn' ? '¥' : '$' }
function marketAlertCount(market) { let c = 0; for (const g of market.stocks) { if (g.primary) c++; c += (g.levels || []).length }; return c }

function closeMoreMenu() { moreMenuOpen.value = false }

// ── TradingView Chart Modal ────────────────────────────────────────────────
const showChartModal = ref(false)
const chartSymbol = ref('')
const tvContainer = ref(null)
let tvWidget = null

function toTvSymbol(symbol, currency) {
  // A股
  if (currency === 'CNY' || symbol.endsWith('.SS') || symbol.endsWith('.SZ')) {
    const code = symbol.replace(/\.(SS|SZ)$/, '')
    if (code.startsWith('6')) return 'SSE:' + code
    return 'SZSE:' + code
  }
  // 美股常见交易所映射
  const nyse = new Set(['TME','BABA','NIO','JD','PDD','LI','XPEV','BIDU'])
  if (nyse.has(symbol)) return 'NYSE:' + symbol
  return 'NASDAQ:' + symbol
}

function openChartModal(symbol, currency) {
  const tvSym = toTvSymbol(symbol, currency)
  const url = `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(tvSym)}`
  // Telegram Mini App: 用 openLink 在系统浏览器打开
  if (window.Telegram?.WebApp?.openLink) {
    window.Telegram.WebApp.openLink(url)
  } else {
    window.open(url, '_blank')
  }
}

function closeChartModal() {
  showChartModal.value = false
  if (tvContainer.value) tvContainer.value.innerHTML = ''
  tvWidget = null
}

function loadTvScript() {
  // 不再需要加载 tv.js，改为跳转方式
}

let refreshInterval
onMounted(() => {
  applyTheme(); mql.addEventListener('change', onSystemThemeChange)
  loadTvScript()
  loadDashboard(); loadTransactions(); loadAlerts(); loadCashAccounts(); loadMacro(); loadSnapshots()
  refreshInterval = setInterval(() => { loadDashboard(); loadMacro() }, 60000)
  window.addEventListener('resize', () => { dashPieInstance?.resize(); holdingPieInstance?.resize(); holdingPnlInstance?.resize(); quantPeChartInstance?.resize(); netWorthChartInstance?.resize() })
  document.addEventListener('click', closeMoreMenu)
})
onUnmounted(() => { clearInterval(refreshInterval); mql.removeEventListener('change', onSystemThemeChange); dashPieInstance?.dispose(); holdingPieInstance?.dispose(); holdingPnlInstance?.dispose(); quantPeChartInstance?.dispose(); netWorthChartInstance?.dispose(); document.removeEventListener('click', closeMoreMenu) })
</script>

<template>
  <nav class="nav">
    <div class="nav-brand">📊 Portfolio Monitor</div>
    <div class="nav-links">
      <a :class="{active: tab==='dashboard'}" @click="switchTab('dashboard')"><span class="nav-icon">📈</span><span class="nav-text">看板</span></a>
      <a :class="{active: tab==='portfolio'}" @click="switchTab('portfolio')"><span class="nav-icon">💰</span><span class="nav-text">持仓</span></a>
      <a :class="{active: tab==='alerts'}" @click="switchTab('alerts')"><span class="nav-icon">🔔</span><span class="nav-text">监控预警</span></a>
      <a :class="{active: tab==='history'}" @click="switchTab('history')"><span class="nav-icon">📜</span><span class="nav-text">告警历史</span></a>
      <a :class="{active: tab==='transactions'}" @click="switchTab('transactions')"><span class="nav-icon">📝</span><span class="nav-text">交易记录</span></a>
      <a :class="{active: tab==='cash'}" @click="switchTab('cash')"><span class="nav-icon">💵</span><span class="nav-text">现金</span></a>
      <a :class="{active: tab==='earnings'}" @click="switchTab('earnings')"><span class="nav-icon">📅</span><span class="nav-text">财报</span></a>
      <a :class="{active: tab==='quant'}" @click="switchTab('quant')"><span class="nav-icon">📊</span><span class="nav-text">量化</span></a>
    </div>
    <div class="nav-right">
      <div class="nav-status"><span v-if="loading" class="loading-dot">●</span><span v-else class="status-ok">●</span><small>{{ lastUpdate }}</small></div>
      <button class="theme-toggle" @click="cycleTheme" :title="themeLabel"><span v-if="themeMode==='system'">🖥️</span><span v-else-if="themeMode==='dark'">🌙</span><span v-else>☀️</span></button>
    </div>
  </nav>

  <!-- Dashboard -->
  <div v-if="tab==='dashboard'" class="container">
    <div class="page-header"><h2>📈 实时监控看板</h2><button class="btn-outline btn-sm" @click="loadDashboard();loadMacro()">🔄 刷新</button></div>
    <div class="card" style="margin-bottom:16px">
      <div class="form-group"><label>搜索股票并加入自选</label><input v-model="stockQuery" @input="onStockQuery" placeholder="代码或名称，如 600519、茅台、AAPL"></div>
      <div v-for="item in searchResults" :key="item.symbol" style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-top:1px solid var(--border)">
        <span><b class="mono">{{ item.symbol }}</b> {{ item.name }} <small>{{ item.market === 'cn' ? 'A股' : '美股' }}</small></span>
        <button type="button" class="btn-primary btn-sm" @click="addSearched(item)">添加</button>
      </div>
    </div>

    <!-- Macro Indicators Bar -->
    <div class="macro-bar" v-if="macroIndicators.length > 0">
      <div v-for="m in macroIndicators" :key="m.symbol" class="macro-card" :class="{ 'macro-error': m.error }">
        <div class="macro-name">{{ m.short_name }}</div>
        <div class="macro-price" v-if="m.price != null">{{ m.price.toLocaleString() }}</div>
        <div class="macro-price" v-else>--</div>
        <div class="macro-change" :class="pnlClass(m.change_pct)" v-if="m.change_pct != null">{{ fmtPct(m.change_pct) }}</div>
      </div>
    </div>

    <div class="summary-cards" v-if="totalAssets">
      <div class="summary-card highlight"><div class="summary-icon">💎</div><div class="summary-content"><div class="summary-label">总资产</div><div class="summary-value">${{ fmtNum(totalAssets.total_assets_usd) }}</div><div class="summary-sub" v-if="totalAssets.usd_to_cny">≈ ¥{{ fmtNum(totalAssets.total_assets_usd * totalAssets.usd_to_cny) }}<span class="fx-rate">汇率 {{ totalAssets.usd_to_cny }}</span></div></div></div>
      <div class="summary-card"><div class="summary-icon">💵</div><div class="summary-content"><div class="summary-label">美元现金</div><div class="summary-value">${{ fmtNum(totalAssets.cash_usd) }}</div></div></div>
      <div class="summary-card"><div class="summary-icon">💴</div><div class="summary-content"><div class="summary-label">人民币现金</div><div class="summary-value">¥{{ fmtNum(totalAssets.cash_cny) }}</div></div></div>
      <div class="summary-card"><div class="summary-icon">📊</div><div class="summary-content"><div class="summary-label">股票市值</div><div class="summary-value">${{ fmtNum(totalAssets.stock_value_usd) }}</div></div></div>
    </div>
    <div class="grid-2">
      <div class="card">
        <div class="card-header"><h3>🇺🇸 美股实时价格</h3><span class="badge">{{ usStockPrices.length }}</span></div>
        <!-- Desktop table -->
        <table class="table"><thead><tr><th>代码</th><th>名称</th><th>价格</th><th>涨跌</th><th>涨跌幅</th><th></th></tr></thead><tbody><tr v-for="p in usStockPrices" :key="p.symbol"><td class="mono stock-code">{{ p.symbol }}</td><td>{{ p.name }}</td><td class="mono">{{ fmtPrice(p.price, p.currency) }}</td><td :class="pnlClass(p.change)">{{ fmtChange(p.change) }}</td><td><span class="pct-badge" :class="pnlClass(p.change_pct)">{{ fmtPct(p.change_pct) }}</span></td><td><button class="btn-chart" @click="openChartModal(p.symbol, p.currency)" title="查看K线">📈</button></td></tr></tbody></table>
        <!-- Mobile card list -->
        <div class="mobile-card-list">
          <div v-for="p in usStockPrices" :key="'m-us-'+p.symbol" class="mobile-stock-card">
            <div class="mobile-stock-card-header">
              <div><span class="stock-symbol-lg">{{ p.symbol }}</span><span class="stock-name-sm">{{ p.name }}</span></div>
              <div style="display:flex;align-items:center;gap:8px">
                <span class="pct-badge" :class="pnlClass(p.change_pct)">{{ fmtPct(p.change_pct) }}</span>
                <button class="btn-chart-mobile" @click="openChartModal(p.symbol, p.currency)">📈 图表</button>
              </div>
            </div>
            <div class="mobile-stock-card-row">
              <span class="label">价格</span>
              <span class="mobile-stock-card-price" :class="pnlClass(p.change)">{{ fmtPrice(p.price, p.currency) }}</span>
            </div>
            <div class="mobile-stock-card-row">
              <span class="label">涨跌</span>
              <span class="value" :class="pnlClass(p.change)">{{ fmtChange(p.change) }}</span>
            </div>
          </div>
        </div>
        <div v-if="usStockPrices.length===0" class="empty">暂无美股数据</div>
        <div class="card-divider"></div>
        <div class="card-header" style="margin-top:8px"><h3>🇨🇳 A股实时价格</h3><span class="badge">{{ cnStockPrices.length }}</span></div>
        <!-- Desktop table -->
        <table class="table"><thead><tr><th>代码</th><th>名称</th><th>价格</th><th>涨跌</th><th>涨跌幅</th><th></th></tr></thead><tbody><tr v-for="p in cnStockPrices" :key="p.symbol"><td class="mono stock-code">{{ p.symbol }}</td><td>{{ p.name }}</td><td class="mono">{{ fmtPrice(p.price, p.currency) }}</td><td :class="pnlClass(p.change)">{{ fmtChange(p.change) }}</td><td><span class="pct-badge" :class="pnlClass(p.change_pct)">{{ fmtPct(p.change_pct) }}</span></td><td><button class="btn-chart" @click="openChartModal(p.symbol, p.currency)" title="查看K线">📈</button></td></tr></tbody></table>
        <!-- Mobile card list -->
        <div class="mobile-card-list">
          <div v-for="p in cnStockPrices" :key="'m-cn-'+p.symbol" class="mobile-stock-card">
            <div class="mobile-stock-card-header">
              <div><span class="stock-symbol-lg">{{ p.symbol }}</span><span class="stock-name-sm">{{ p.name }}</span></div>
              <div style="display:flex;align-items:center;gap:8px">
                <span class="pct-badge" :class="pnlClass(p.change_pct)">{{ fmtPct(p.change_pct) }}</span>
                <button class="btn-chart-mobile" @click="openChartModal(p.symbol, p.currency)">📈 图表</button>
              </div>
            </div>
            <div class="mobile-stock-card-row">
              <span class="label">价格</span>
              <span class="mobile-stock-card-price" :class="pnlClass(p.change)">{{ fmtPrice(p.price, p.currency) }}</span>
            </div>
            <div class="mobile-stock-card-row">
              <span class="label">涨跌</span>
              <span class="value" :class="pnlClass(p.change)">{{ fmtChange(p.change) }}</span>
            </div>
          </div>
        </div>
        <div v-if="cnStockPrices.length===0" class="empty">暂无A股数据</div>
      </div>
      <div>
        <div class="card"><h3>💰 资产配置</h3><div ref="dashPieChart" class="chart-box" style="height:280px"></div></div>
        <div class="card mt" v-if="snapshotHistory.length >= 2"><h3>📈 总资产趋势</h3><div ref="netWorthChartRef" class="chart-box" style="height:250px"></div></div>
        <div class="card mt"><h3>💵 现金账户</h3><div v-for="acc in cashAccounts" :key="acc.currency" class="cash-item"><div class="cash-currency">{{ CURRENCY_NAMES[acc.currency] || acc.currency }}</div><div class="cash-balance">{{ CURRENCY_SYMBOLS[acc.currency] || '$' }}{{ fmtNum(acc.balance) }}</div></div><div v-if="cashAccounts.length===0" class="empty">暂无</div></div>
        <div class="card mt"><h3>🔔 最近告警</h3><div v-for="a in recentAlerts" :key="a.id" class="alert-item"><div class="alert-meta"><span class="mono alert-symbol">{{ a.symbol }}</span> <span class="alert-type-badge" :class="'alert-type-'+a.alert_type">{{ alertTypeLabel(a.alert_type) }}</span> <span class="alert-time">{{ fmtTime(a.triggered_at) }}</span></div><div class="alert-msg">{{ a.message }}</div></div><div v-if="recentAlerts.length===0" class="empty">暂无</div></div>
        <div class="card mt"><h3>📝 最近交易</h3>
          <table class="table" v-if="recentTx.length>0"><thead><tr><th>日期</th><th>代码</th><th>操作</th><th>价格</th><th>股数</th></tr></thead><tbody><tr v-for="t in recentTx" :key="t.id"><td>{{ fmtDate(t.date) }}</td><td class="mono stock-code">{{ t.symbol }}</td><td><span :class="t.action==='buy'?'tag-buy':'tag-sell'">{{ t.action==='buy'?'买入':'卖出' }}</span></td><td class="mono">{{ fmtPrice(t.price) }}</td><td>{{ t.shares }}</td></tr></tbody></table>
          <div class="mobile-card-list" v-if="recentTx.length>0">
            <div v-for="t in recentTx" :key="'m-rtx-'+t.id" class="mobile-stock-card">
              <div class="mobile-stock-card-header">
                <div><span class="stock-symbol-lg">{{ t.symbol }}</span><span :class="t.action==='buy'?'tag-buy':'tag-sell'" style="margin-left:8px">{{ t.action==='buy'?'买入':'卖出' }}</span></div>
                <span class="value" style="color:var(--text-dim);font-size:12px">{{ fmtDate(t.date) }}</span>
              </div>
              <div class="mobile-stock-card-row"><span class="label">价格</span><span class="value mono">{{ fmtPrice(t.price) }}</span></div>
              <div class="mobile-stock-card-row"><span class="label">股数</span><span class="value">{{ t.shares }}</span></div>
            </div>
          </div>
          <div v-if="recentTx.length===0" class="empty">暂无</div></div>
      </div>
    </div>
  </div>

  <!-- Portfolio -->
  <div v-if="tab==='portfolio'" class="container">
    <div class="page-header"><h2>💰 持仓管理</h2><button class="btn-outline btn-sm" @click="loadPortfolio();loadDashboard()">🔄 刷新</button></div>
    <div class="card form-card" style="margin-bottom:16px">
      <form @submit.prevent="saveHolding" class="form-grid">
        <div class="form-group"><label>代码</label><input v-model="holdingForm.symbol" placeholder="600519 或 AAPL" required></div>
        <div class="form-group"><label>名称</label><input v-model="holdingForm.name" placeholder="贵州茅台"></div>
        <div class="form-group"><label>市场</label><select v-model="holdingForm.market"><option value="cn">A股</option><option value="us">美股</option></select></div>
        <div class="form-group"><label>股数</label><input v-model.number="holdingForm.shares" type="number" min="0" step="1" required></div>
        <div class="form-group"><label>成本价</label><input v-model.number="holdingForm.cost_price" type="number" min="0" step="0.01" required></div>
        <div class="form-group form-actions"><button type="submit" class="btn-primary">保存持仓</button></div>
      </form>
      <p class="hint">直接记录持仓，不扣现金。同一代码再次保存会按新的股数和成本价覆盖。</p>
    </div>
    <div class="summary-cards" v-if="portfolio">
      <div class="summary-card"><div class="summary-icon">💰</div><div class="summary-content"><div class="summary-label">总成本</div><div class="summary-value">${{ fmtNum(portfolio.total_cost) }}</div></div></div>
      <div class="summary-card"><div class="summary-icon">📊</div><div class="summary-content"><div class="summary-label">总市值</div><div class="summary-value">${{ fmtNum(portfolio.total_value) }}</div></div></div>
      <div class="summary-card" :class="portfolio.total_pnl>=0?'card-positive':'card-negative'"><div class="summary-icon">{{ portfolio.total_pnl>=0?'📈':'📉' }}</div><div class="summary-content"><div class="summary-label">总盈亏</div><div class="summary-value" :class="pnlClass(portfolio.total_pnl)">${{ fmtNum(portfolio.total_pnl) }} ({{ fmtPct(portfolio.total_pnl_pct) }})</div></div></div>
    </div>
    <div class="grid-2">
      <div>
        <div class="card"><div class="card-header"><h3>🇺🇸 美股持仓</h3><span class="badge">{{ usHoldings.length }}</span></div>
          <table class="table" v-if="usHoldings.length>0"><thead><tr><th>代码</th><th>名称</th><th>股数</th><th>成本</th><th>现价</th><th>市值</th><th>盈亏</th><th>收益率</th></tr></thead><tbody><tr v-for="h in usHoldings" :key="h.symbol"><td class="mono stock-code">{{ h.symbol }}</td><td>{{ h.name }}</td><td>{{ h.shares }}</td><td class="mono">${{ h.avg_cost.toFixed(2) }}</td><td class="mono">${{ h.current_price.toFixed(2) }}</td><td class="mono">${{ fmtNum(h.market_value) }}</td><td :class="pnlClass(h.unrealized_pnl)" class="mono">${{ fmtNum(h.unrealized_pnl) }}</td><td><span class="pct-badge" :class="pnlClass(h.pnl_pct)">{{ fmtPct(h.pnl_pct) }}</span> <button class="btn-outline btn-sm" @click="editHolding(h)">修改</button> <button class="btn-danger-sm" @click="removeHolding(h.symbol)">删除</button></td></tr></tbody></table>
          <div class="mobile-card-list" v-if="usHoldings.length>0">
            <div v-for="h in usHoldings" :key="'m-ush-'+h.symbol" class="mobile-stock-card">
              <div class="mobile-stock-card-header">
                <div><span class="stock-symbol-lg">{{ h.symbol }}</span><span class="stock-name-sm">{{ h.name }}</span></div>
                <span class="pct-badge" :class="pnlClass(h.pnl_pct)">{{ fmtPct(h.pnl_pct) }}</span>
              </div>
              <div class="mobile-stock-card-row"><span class="label">现价</span><span class="mobile-stock-card-price">${{ h.current_price.toFixed(2) }}</span></div>
              <div class="mobile-stock-card-divider"></div>
              <div class="mobile-stock-card-row"><span class="label">持仓</span><span class="value">{{ h.shares }} 股 @ ${{ h.avg_cost.toFixed(2) }}</span></div>
              <div class="mobile-stock-card-row"><span class="label">市值</span><span class="value mono">${{ fmtNum(h.market_value) }}</span></div>
              <div class="mobile-stock-card-row"><span class="label">盈亏</span><span class="value mono" :class="pnlClass(h.unrealized_pnl)">${{ fmtNum(h.unrealized_pnl) }}</span></div>
              <div class="holding-build-progress" v-if="holdingBuildProgress[h.symbol]">
                <span class="build-progress-label">建仓进度 {{ holdingBuildProgress[h.symbol].pct }}%</span>
                <div class="build-progress-bar"><div class="build-progress-fill" :style="{width: holdingBuildProgress[h.symbol].pct + '%'}"></div></div>
                <span class="build-progress-detail">${{ fmtNum(holdingBuildProgress[h.symbol].invested) }} / ${{ fmtNum(holdingBuildProgress[h.symbol].planned) }}</span>
              </div>
            </div>
          </div>
          <div v-if="usHoldings.length===0" class="empty">暂无美股持仓</div></div>
        <div class="card mt"><div class="card-header"><h3>🇨🇳 A股持仓</h3><span class="badge">{{ cnHoldings.length }}</span></div>
          <table class="table" v-if="cnHoldings.length>0"><thead><tr><th>代码</th><th>名称</th><th>股数</th><th>成本</th><th>现价</th><th>市值</th><th>盈亏</th><th>收益率</th></tr></thead><tbody><tr v-for="h in cnHoldings" :key="h.symbol"><td class="mono stock-code">{{ h.symbol }}</td><td>{{ h.name }}</td><td>{{ h.shares }}</td><td class="mono">¥{{ h.avg_cost.toFixed(2) }}</td><td class="mono">¥{{ h.current_price.toFixed(2) }}</td><td class="mono">¥{{ fmtNum(h.market_value) }}</td><td :class="pnlClass(h.unrealized_pnl)" class="mono">¥{{ fmtNum(h.unrealized_pnl) }}</td><td><span class="pct-badge" :class="pnlClass(h.pnl_pct)">{{ fmtPct(h.pnl_pct) }}</span> <button class="btn-outline btn-sm" @click="editHolding(h)">修改</button> <button class="btn-danger-sm" @click="removeHolding(h.symbol)">删除</button></td></tr></tbody></table>
          <div class="mobile-card-list" v-if="cnHoldings.length>0">
            <div v-for="h in cnHoldings" :key="'m-cnh-'+h.symbol" class="mobile-stock-card">
              <div class="mobile-stock-card-header">
                <div><span class="stock-symbol-lg">{{ h.symbol }}</span><span class="stock-name-sm">{{ h.name }}</span></div>
                <span class="pct-badge" :class="pnlClass(h.pnl_pct)">{{ fmtPct(h.pnl_pct) }}</span>
              </div>
              <div class="mobile-stock-card-row"><span class="label">现价</span><span class="mobile-stock-card-price">¥{{ h.current_price.toFixed(2) }}</span></div>
              <div class="mobile-stock-card-divider"></div>
              <div class="mobile-stock-card-row"><span class="label">持仓</span><span class="value">{{ h.shares }} 股 @ ¥{{ h.avg_cost.toFixed(2) }}</span></div>
              <div class="mobile-stock-card-row"><span class="label">市值</span><span class="value mono">¥{{ fmtNum(h.market_value) }}</span></div>
              <div class="mobile-stock-card-row"><span class="label">盈亏</span><span class="value mono" :class="pnlClass(h.unrealized_pnl)">¥{{ fmtNum(h.unrealized_pnl) }}</span></div>
              <div class="holding-build-progress" v-if="holdingBuildProgress[h.symbol]">
                <span class="build-progress-label">建仓进度 {{ holdingBuildProgress[h.symbol].pct }}%</span>
                <div class="build-progress-bar"><div class="build-progress-fill" :style="{width: holdingBuildProgress[h.symbol].pct + '%'}"></div></div>
                <span class="build-progress-detail">¥{{ fmtNum(holdingBuildProgress[h.symbol].invested) }} / ¥{{ fmtNum(holdingBuildProgress[h.symbol].planned) }}</span>
              </div>
            </div>
          </div>
          <div v-if="cnHoldings.length===0" class="empty">暂无A股持仓</div></div>
      </div>
      <div>
        <div class="card"><h3>📊 持仓占比</h3><div ref="holdingPieChart" class="chart-box" style="height:300px"></div></div>
        <div class="card mt"><h3>📈 持仓盈亏</h3><div ref="holdingPnlChart" class="chart-box" style="height:300px"></div></div>
      </div>
    </div>
  </div>

  <!-- Monitoring & Alerts -->
  <div v-if="tab==='alerts'" class="container">
    <div class="page-header">
      <h2>🔔 监控预警</h2>
      <div class="page-actions">
        <div class="view-toggle">
          <button :class="['view-toggle-btn', alertViewMode==='zone' ? 'active' : '']" @click="setAlertViewMode('zone')">📋 分区视图</button>
          <button :class="['view-toggle-btn', alertViewMode==='card' ? 'active' : '']" @click="setAlertViewMode('card')">🃏 卡片视图</button>
        </div>
        <button class="btn-outline btn-sm" @click="testAlert('dry')" :disabled="testingAlert">只打印</button>
        <button class="btn-outline btn-sm" @click="testAlert('live')" :disabled="testingAlert">真发 Telegram</button>
        <button class="btn-primary btn-sm" @click="showAddAlert=!showAddAlert">{{ showAddAlert ? '收起' : '➕ 添加' }}</button>
      </div>
    </div>
    <div class="card" style="margin-bottom:16px" v-if="notifyStatus">
      <div>策略命中后会发送 Telegram，和「真发 Telegram」是同一个接口。没填写跌破价、突破价、止损价或涨跌幅阈值的股票只显示行情，不会告警。Token {{ notifyStatus.telegram_configured ? '已配置' : '未配置' }} · 冷却 {{ notifyStatus.cooldown_minutes }} 分钟 · 每日上限 {{ notifyStatus.max_per_day }}</div>
      <label style="display:inline-flex;align-items:center;gap:8px;margin-top:8px">
        <input type="checkbox" :checked="notifyStatus.auto_order" @change="toggleAutoOrder">
        自动下单（默认关）
      </label>
      <div style="opacity:.8;margin-top:6px">关闭时只提醒，文案带「请手动确认」，需要你自己下单。打开开关也不会点击交易软件，不会保存交易密码；当前没有券商接口，所以不会提交委托。</div>
    </div>
    <div class="card form-card" v-show="showAddAlert" style="margin-bottom:16px">
      <form @submit.prevent="saveAlert" class="form-grid">
        <div class="form-group"><label>代码</label><input v-model="alertForm.symbol" placeholder="600519" required></div>
        <div class="form-group"><label>名称</label><input v-model="alertForm.name" placeholder="贵州茅台"></div>
        <div class="form-group"><label>市场</label><select v-model="alertForm.market"><option value="us">美股</option><option value="cn">A股</option></select></div>
        <div class="form-group"><label>档位</label><select v-model="alertForm.is_primary"><option :value="true">主档</option><option :value="false">子档</option></select></div>
        <div class="form-group" v-show="!alertForm.is_primary"><label>标签</label><input v-model="alertForm.label" placeholder="子档标签"></div>
        <div class="form-group"><label>跌破价</label><input v-model.number="alertForm.target_buy" type="number" step="0.01"></div>
        <div class="form-group"><label>突破价</label><input v-model.number="alertForm.target_sell" type="number" step="0.01"></div>
        <div class="form-group"><label>止损价</label><input v-model.number="alertForm.stop_loss" type="number" step="0.01"></div>
        <div class="form-group"><label>涨跌幅阈值(%)</label><input v-model.number="alertForm.pct_threshold" type="number" step="0.1" placeholder="留空用全局 3"></div>
        <div class="form-group"><label>金额</label><input v-model="alertForm.amount" placeholder="$15,000"></div>
        <div class="form-group form-actions"><button type="submit" class="btn-primary">保存</button></div>
      </form>
    </div>

    <!-- A方案: Zone View -->
    <div v-if="alertViewMode==='zone'">
      <div v-for="phase in alertsByPhase" :key="phase.key" class="zone-section">
        <div class="zone-header" @click="toggleCollapse('zone:'+phase.key)">
          <span class="collapse-icon">{{ isCollapsed('zone:'+phase.key) ? '▶' : '▼' }}</span>
          <span class="zone-icon">{{ phase.icon }}</span>
          <span class="zone-label">{{ phase.label }}</span>
          <span class="badge">{{ phase.items.length }} 只</span>
        </div>
        <div v-show="!isCollapsed('zone:'+phase.key)" class="zone-items">
          <div v-for="group in phase.items" :key="group.symbol" class="zone-stock-item">
            <div class="zone-stock-header">
              <div class="zone-stock-left">
                <span class="stock-symbol">{{ group.symbol }}</span>
                <span class="stock-name">{{ group.name }}</span>
              </div>
              <div class="zone-stock-right">
                <span class="stock-price mono" v-if="group.current_price">{{ marketCurrSym(group.market) }}{{ group.current_price.toFixed(2) }}</span>
                <span class="pct-badge" :class="pnlClass(group.change_pct)" v-if="group.change_pct!=null">{{ fmtPct(group.change_pct) }}</span>
              </div>
            </div>
            <div class="zone-holding-info" v-if="group.holding && group.holding.shares > 0">
              <span>持仓 {{ group.holding.shares }} 股 @ {{ marketCurrSym(group.market) }}{{ group.holding.avg_cost.toFixed(2) }}</span>
              <span class="mono" :class="pnlClass(group.holding.unrealized_pnl)">盈亏 {{ fmtPct(group.holding.pnl_pct) }}</span>
            </div>
            <div class="zone-levels">
              <div v-for="level in group.allLevels" :key="level.id" class="zone-level-row">
                <div class="zone-level-targets">
                  <span v-if="level.target_buy" class="target-tag target-buy">{{ marketCurrSym(group.market) }}{{ level.target_buy.toFixed(0) }} {{ level.is_primary ? '建仓' : (level.label || '加仓') }}</span>
                  <span v-if="level.target_sell" class="target-tag target-sell">{{ marketCurrSym(group.market) }}{{ level.target_sell.toFixed(0) }} {{ level.label || '止盈' }}</span>
                  <span v-if="level.stop_loss" class="target-tag target-stop">{{ marketCurrSym(group.market) }}{{ level.stop_loss.toFixed(0) }} 止损</span>
                  <span v-if="level.amount" class="target-tag target-amount">{{ level.amount }}</span>
                </div>
                <div class="zone-level-status">
                  <span :class="level.enabled ? 'status-pending' : 'status-paused'">{{ level.enabled ? '待触发' : '已暂停' }}</span>
                  <button :class="level.enabled?'tag-buy':'tag-sell'" @click.stop="toggleAlert(level)" style="font-size:11px;padding:1px 6px;">{{ level.enabled?'✓':'✗' }}</button>
                  <button class="btn-danger-sm" @click.stop="deleteAlert(level.id)" style="font-size:11px;padding:1px 6px;">×</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <!-- Fallback -->
      <div v-if="alertsByPhase.length===0">
        <div v-for="market in alertGroupsByMarket" :key="market.key" v-show="market.stocks.length>0" class="market-block">
          <div class="market-section-header" @click="toggleCollapse('market:'+market.key)"><span class="collapse-icon">{{ isCollapsed('market:'+market.key) ? '▶' : '▼' }}</span><span class="market-flag">{{ market.key==='us'?'🇺🇸':'🇨🇳' }}</span><span class="market-label">{{ market.key==='us'?'美股':'A股' }}</span><span class="badge">{{ market.stocks.length }} 只 · {{ marketAlertCount(market) }} 档</span></div>
          <div v-show="!isCollapsed('market:'+market.key)" class="stock-cards-grid">
            <div v-for="group in market.stocks" :key="group.symbol" class="stock-card">
              <div class="stock-card-header"><div class="stock-card-left"><span class="stock-symbol">{{ group.symbol }}</span><span class="stock-name">{{ group.name }}</span></div><div class="stock-card-right"><span class="stock-price mono" v-if="group.current_price">{{ marketCurrSym(market.key) }}{{ group.current_price.toFixed(2) }}</span><span class="pct-badge" :class="pnlClass(group.change_pct)" v-if="group.change_pct!=null">{{ fmtPct(group.change_pct) }}</span></div></div>
              <div class="stock-card-holding" v-if="getHolding(group.symbol)"><div class="holding-info"><span>持仓 {{ getHolding(group.symbol).shares }} 股</span><span class="mono" :class="pnlClass(getHolding(group.symbol).unrealized_pnl)">盈亏 {{ marketCurrSym(market.key) }}{{ fmtNum(getHolding(group.symbol).unrealized_pnl) }} ({{ fmtPct(getHolding(group.symbol).pnl_pct) }})</span></div></div>
              <div class="stock-card-levels">
                <div v-if="!group.primary && (!group.levels||group.levels.length===0)" class="no-levels">暂无告警档位</div>
                <div v-if="group.primary" class="level-row level-primary"><div class="level-badge primary">主档</div><div class="level-targets"><span v-if="group.primary.target_buy" class="target-tag target-buy">📉买{{ marketCurrSym(market.key) }}{{ group.primary.target_buy.toFixed(0) }}</span><span v-if="group.primary.target_sell" class="target-tag target-sell">📈卖{{ marketCurrSym(market.key) }}{{ group.primary.target_sell.toFixed(0) }}</span><span v-if="group.primary.stop_loss" class="target-tag target-stop">🚨止损{{ marketCurrSym(market.key) }}{{ group.primary.stop_loss.toFixed(0) }}</span><span v-if="group.primary.pct_threshold" class="target-tag">涨跌≥{{ group.primary.pct_threshold }}%</span><span v-if="group.primary.amount" class="target-tag target-amount">💰{{ group.primary.amount }}</span></div><div class="level-actions"><button :class="group.primary.enabled?'tag-buy':'tag-sell'" @click.stop="toggleAlert(group.primary)">{{ group.primary.enabled?'✓':'✗' }}</button><button class="btn-danger-sm" @click.stop="deleteAlert(group.primary.id)">×</button></div></div>
                <div v-for="level in (group.levels||[])" :key="level.id" class="level-row level-sub"><div class="level-badge sub">{{ level.label||'子档' }}</div><div class="level-targets"><span v-if="level.target_buy" class="target-tag target-buy">📉买{{ marketCurrSym(market.key) }}{{ level.target_buy.toFixed(0) }}</span><span v-if="level.target_sell" class="target-tag target-sell">📈卖{{ marketCurrSym(market.key) }}{{ level.target_sell.toFixed(0) }}</span><span v-if="level.stop_loss" class="target-tag target-stop">🚨止损{{ marketCurrSym(market.key) }}{{ level.stop_loss.toFixed(0) }}</span><span v-if="level.amount" class="target-tag target-amount">💰{{ level.amount }}</span></div><div class="level-actions"><button :class="level.enabled?'tag-buy':'tag-sell'" @click.stop="toggleAlert(level)">{{ level.enabled?'✓':'✗' }}</button><button class="btn-danger-sm" @click.stop="deleteAlert(level.id)">×</button></div></div>
              </div>
            </div>
          </div>
        </div>
        <div v-if="alertGroupsByMarket.every(m=>m.stocks.length===0)" class="card mt"><div class="empty">暂无告警设置</div></div>
      </div>
    </div>

    <!-- B方案: Card Timeline View -->
    <div v-if="alertViewMode==='card'">
      <div v-if="cardTimelineData.length > 0" class="timeline-cards-grid">
        <div v-for="stock in cardTimelineData" :key="stock.symbol" class="timeline-card">
          <div class="timeline-card-header">
            <div class="timeline-card-title">
              <span class="stock-symbol">{{ stock.symbol }}</span>
              <span class="stock-name">{{ stock.name }}</span>
            </div>
            <div class="timeline-card-meta">
              <span class="stock-price mono" v-if="stock.currentPrice">{{ marketCurrSym(stock.market) }}{{ stock.currentPrice.toFixed(2) }}</span>
              <span class="pct-badge" :class="pnlClass(stock.changePct)" v-if="stock.changePct!=null">{{ fmtPct(stock.changePct) }}</span>
              <span class="timeline-market-value mono" v-if="stock.marketValue">市值{{ marketCurrSym(stock.market) }}{{ fmtNum(stock.marketValue) }}</span>
            </div>
          </div>
          <div class="timeline-body">
            <div class="timeline-axis">
              <div v-for="(row, idx) in stock.timelineRows" :key="idx"
                   :class="row.isCurrent ? 'timeline-row timeline-row-current' : 'timeline-row'"
                   :style="!row.isCurrent && !row.enabled ? 'opacity:0.45' : ''">
                <span class="timeline-price mono">{{ marketCurrSym(stock.market) }}{{ row.price.toFixed(0) }}</span>
                <template v-if="row.isCurrent">
                  <span class="timeline-connector current">┼</span>
                  <span class="timeline-label-current">现价 ►</span>
                </template>
                <template v-else>
                  <span class="timeline-connector" :class="'connector-'+row.type">●</span>
                  <span class="timeline-label" :class="'label-'+row.type">{{ row.label }} <span v-if="row.amount" class="timeline-amount">{{ row.amount }}</span></span>
                </template>
              </div>
              <div v-if="stock.timelineRows.length === 0" class="timeline-empty">暂无价格档位</div>
            </div>
          </div>
          <div class="timeline-card-footer" v-if="stock.buildProgress != null">
            <div class="build-progress">
              <span class="build-progress-label">进度: 已建仓{{ stock.buildProgress }}%</span>
              <div class="build-progress-bar"><div class="build-progress-fill" :style="{width: stock.buildProgress + '%'}"></div></div>
            </div>
          </div>
          <div class="timeline-card-footer" v-else-if="stock.holding">
            <div class="build-progress">
              <span class="build-progress-label">持仓 {{ stock.holding.shares }} 股 @ {{ marketCurrSym(stock.market) }}{{ stock.holding.avg_cost.toFixed(2) }}</span>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="card mt"><div class="empty">暂无告警设置</div></div>
    </div>
  </div>

  <!-- Alert History -->
  <div v-if="tab==='history'" class="container">
    <div class="page-header"><h2>📜 告警历史</h2><div class="page-actions"><input v-model="historyFilter" placeholder="筛选代码..." class="filter-input"></div></div>
    <div class="card" v-if="filteredHistory.length>0">
      <div class="history-timeline">
        <div v-for="a in filteredHistory" :key="a.id" class="history-item"><div class="history-dot" :class="a.sent?'dot-sent':'dot-failed'"></div><div class="history-content"><div class="history-header"><span class="mono stock-code">{{ a.symbol }}</span> <span class="alert-type-badge" :class="'alert-type-'+a.alert_type">{{ alertTypeLabel(a.alert_type) }}</span> <span class="history-price mono">${{ a.price.toFixed(2) }}</span> <span :class="a.sent?'tag-buy':'tag-sell'" class="history-status">{{ a.sent?'已推送':'失败' }}</span></div><div class="history-msg">{{ a.message }}</div><div class="history-time">{{ fmtTime(a.triggered_at) }}</div></div></div>
      </div>
    </div>
    <div v-else class="card"><div class="empty">暂无告警历史</div></div>
  </div>

  <!-- Transactions -->
  <div v-if="tab==='transactions'" class="container">
    <div class="page-header"><h2>📝 交易记录</h2><div class="page-actions"><a href="/api/transactions/export/csv" class="btn-outline btn-sm" target="_blank">📥 CSV</a><button class="btn-primary btn-sm" @click="showAddTx=!showAddTx">{{ showAddTx?'收起':'➕ 添加' }}</button></div></div>

    <!-- 添加表单 -->
    <div class="card form-card" v-show="showAddTx" style="margin-bottom:16px">
      <form @submit.prevent="addTransaction" class="form-grid">
        <div class="form-group"><label>代码</label><input v-model="txForm.symbol" placeholder="GOOGL" required></div>
        <div class="form-group"><label>名称</label><input v-model="txForm.name" placeholder="谷歌"></div>
        <div class="form-group"><label>操作</label><select v-model="txForm.action"><option value="buy">买入</option><option value="sell">卖出</option></select></div>
        <div class="form-group"><label>价格</label><input v-model.number="txForm.price" type="number" step="0.0001" required></div>
        <div class="form-group"><label>股数</label><input v-model.number="txForm.shares" type="number" step="0.0001" required></div>
        <div class="form-group"><label>手续费</label><input v-model.number="txForm.fee" type="number" step="0.01"></div>
        <div class="form-group"><label>日期</label><input v-model="txForm.date" type="datetime-local"></div>
        <div class="form-group"><label>备注</label><input v-model="txForm.notes" placeholder="可选"></div>
        <div class="form-group form-actions"><button type="submit" class="btn-primary">添加</button></div>
      </form>
      <p class="hint">💡 买入自动扣减现金，卖出自动增加</p>
    </div>

    <!-- 统计卡片 -->
    <div class="tx-stats" v-if="txStats.count > 0">
      <div class="tx-stat-card"><div class="tx-stat-label">共 {{ txStats.count }} 笔</div><div class="tx-stat-value">全部交易</div></div>
      <div class="tx-stat-card buy"><div class="tx-stat-label">总买入</div><div class="tx-stat-value">${{ fmtNum(txStats.totalBuy) }}</div></div>
      <div class="tx-stat-card sell"><div class="tx-stat-label">总卖出</div><div class="tx-stat-value">${{ fmtNum(txStats.totalSell) }}</div></div>
      <div class="tx-stat-card" :class="txStats.netIn >= 0 ? 'buy' : 'sell'"><div class="tx-stat-label">净投入</div><div class="tx-stat-value">${{ fmtNum(txStats.netIn) }}</div></div>
    </div>

    <!-- 筛选 + 时间轴 -->
    <div class="card">
      <div class="card-header"><h3>交易历史</h3><input v-model="txFilter.symbol" placeholder="筛选代码..." class="filter-input"></div>

      <!-- 时间轴（桌面端） -->
      <div class="tx-timeline" v-if="txGroupedByDate.length > 0">
        <div class="tx-day-group" v-for="[day, txs] in txGroupedByDate" :key="day">
          <div class="tx-day-header">
            <span class="tx-day-dot"></span>
            <span class="tx-day-label">{{ day }}</span>
            <span class="tx-day-count">{{ txs.length }} 笔</span>
          </div>
          <div class="tx-day-items">
            <div class="tx-item" v-for="t in txs" :key="t.id">
              <div class="tx-item-dot" :class="t.action === 'buy' ? 'dot-buy' : 'dot-sell'"></div>
              <div class="tx-item-body">
                <div class="tx-item-main">
                  <span :class="t.action==='buy'?'tag-buy':'tag-sell'" class="tx-action-tag">{{ t.action==='buy'?'买入':'卖出' }}</span>
                  <span class="tx-symbol mono">{{ t.symbol }}</span>
                  <span class="tx-name">{{ t.name }}</span>
                  <span class="tx-shares">{{ t.shares }} 股</span>
                  <span class="tx-at">@</span>
                  <span class="tx-price mono">{{ fmtPrice(t.price) }}</span>
                </div>
                <div class="tx-item-meta">
                  <span class="tx-amount mono">${{ fmtNum(t.amount) }}</span>
                  <span class="tx-fee" v-if="t.fee > 0">手续费 ${{ t.fee.toFixed(2) }}</span>
                  <span class="tx-notes" v-if="t.notes">{{ t.notes }}</span>
                </div>
              </div>
              <button class="btn-danger-sm tx-del" @click="deleteTx(t.id)" title="删除">×</button>
            </div>
          </div>
        </div>
      </div>

      <!-- 移动端卡片 -->
      <div class="mobile-card-list">
        <div v-for="t in filteredTx" :key="'m-tx-'+t.id" class="mobile-stock-card">
          <div class="mobile-stock-card-header">
            <div><span class="stock-symbol-lg">{{ t.symbol }}</span><span class="stock-name-sm">{{ t.name }}</span><span :class="t.action==='buy'?'tag-buy':'tag-sell'" style="margin-left:8px">{{ t.action==='buy'?'买入':'卖出' }}</span></div>
            <button class="btn-danger-sm" @click="deleteTx(t.id)">×</button>
          </div>
          <div class="mobile-stock-card-row"><span class="label">日期</span><span class="value">{{ fmtDate(t.date) }}</span></div>
          <div class="mobile-stock-card-row"><span class="label">价格</span><span class="value mono">{{ fmtPrice(t.price) }}</span></div>
          <div class="mobile-stock-card-row"><span class="label">股数</span><span class="value">{{ t.shares }}</span></div>
          <div class="mobile-stock-card-row"><span class="label">金额</span><span class="value mono">${{ fmtNum(t.amount) }}</span></div>
          <div v-if="t.fee > 0" class="mobile-stock-card-row"><span class="label">手续费</span><span class="value mono">${{ t.fee.toFixed(2) }}</span></div>
          <div v-if="t.notes" class="mobile-stock-card-row"><span class="label">备注</span><span class="value">{{ t.notes }}</span></div>
        </div>
      </div>

      <div v-if="filteredTx.length===0" class="empty">暂无交易记录</div>
    </div>
  </div>

  <!-- Cash -->
  <div v-if="tab==='cash'" class="container">
    <div class="page-header"><h2>💵 现金账户管理</h2></div>

    <!-- 顶部：饼图 + 仓位进度条 -->
    <div class="cash-overview" v-if="totalAssets">
      <!-- 资产构成饼图 -->
      <div class="card cash-pie-card">
        <div class="card-header"><h3>资产构成</h3></div>
        <div class="cash-pie-wrap">
          <svg viewBox="0 0 120 120" width="120" height="120" class="cash-pie-svg">
            <template v-if="totalAssets">
              <template v-for="(seg, i) in cashPieSegments(totalAssets)" :key="i">
                <path :d="seg.d" :fill="seg.color" opacity="0.9"/>
              </template>
              <!-- 中心圆 -->
              <circle cx="60" cy="60" r="32" :fill="'var(--bg-card)'"/>
              <text x="60" y="56" text-anchor="middle" font-size="9" fill="var(--text-dim)">总资产</text>
              <text x="60" y="68" text-anchor="middle" font-size="10" font-weight="600" fill="var(--text)">${{ fmtNum(totalAssets.total_assets_usd,0) }}</text>
            </template>
          </svg>
          <div class="cash-pie-legend">
            <div class="pie-legend-item" v-for="seg in cashPieSegments(totalAssets)" :key="seg.label">
              <span class="pie-dot" :style="{background: seg.color}"></span>
              <span class="pie-label">{{ seg.label }}</span>
              <span class="pie-pct">{{ seg.pct }}%</span>
              <span class="pie-val mono">{{ seg.val }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 仓位进度条 -->
      <div class="card cash-position-card">
        <div class="card-header"><h3>仓位分布</h3></div>
        <div class="position-bars">
          <div class="position-bar-item" v-for="seg in cashPieSegments(totalAssets)" :key="'bar-'+seg.label">
            <div class="position-bar-header">
              <span class="position-bar-label">{{ seg.label }}</span>
              <span class="position-bar-pct">{{ seg.pct }}%</span>
              <span class="position-bar-val mono">{{ seg.val }}</span>
            </div>
            <div class="position-bar-track">
              <div class="position-bar-fill" :style="{width: seg.pct + '%', background: seg.color}"></div>
            </div>
          </div>
          <div class="position-hint" v-if="totalAssets">
            <span>💡 现金仓位 {{ Math.round((totalAssets.cash_usd + totalAssets.cash_cny / totalAssets.usd_to_cny) / totalAssets.total_assets_usd * 100) }}%</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 现金账户余额 -->
    <div class="summary-cards" v-if="cashAccounts.length>0" style="margin-bottom:16px">
      <div class="summary-card highlight" v-for="acc in cashAccounts" :key="acc.currency">
        <div class="summary-icon">{{ acc.currency==='USD'?'💵':'💴' }}</div>
        <div class="summary-content">
          <div class="summary-label">{{ CURRENCY_NAMES[acc.currency]||acc.currency }}现金</div>
          <div class="summary-value">{{ CURRENCY_SYMBOLS[acc.currency]||'$' }}{{ fmtNum(acc.balance) }}</div>
          <div class="summary-sub">更新 {{ fmtDate(acc.updated_at) }}</div>
        </div>
      </div>
    </div>

    <!-- 调整表单 -->
    <div class="card form-card" style="margin-bottom:16px">
      <h3>调整现金余额</h3>
      <form @submit.prevent="adjustCash" class="form-grid">
        <div class="form-group"><label>币种</label><select v-model="cashForm.currency"><option value="USD">美元</option><option value="CNY">人民币</option></select></div>
        <div class="form-group" style="grid-column:span 2"><label>金额</label><input v-model.number="cashForm.amount" type="number" step="0.01" placeholder="正数存入，负数取出" required></div>
        <div class="form-group"><label>备注</label><input v-model="cashForm.notes" placeholder="可选"></div>
        <div class="form-group form-actions"><button type="submit" class="btn-primary">确认</button></div>
      </form>
      <p class="hint">💡 正数存入，负数取出。买卖股票自动联动。</p>
    </div>

    <!-- 操作日志 -->
    <div class="card">
      <div class="card-header"><h3>操作记录</h3></div>
      <div v-if="cashLogs.length > 0" class="cash-log-list">
        <div v-for="log in cashLogs" :key="log.id" class="cash-log-row">
          <span class="cash-log-icon">{{ log.amount > 0 ? '⬆️' : '⬇️' }}</span>
          <span class="cash-log-currency">{{ log.currency }}</span>
          <span class="cash-log-amount mono" :class="log.amount > 0 ? 'text-green' : 'text-red'">
            {{ log.amount > 0 ? '+' : '' }}{{ log.currency === 'CNY' ? '¥' : '$' }}{{ fmtNum(Math.abs(log.amount)) }}
          </span>
          <span class="cash-log-after mono">余额 {{ log.currency === 'CNY' ? '¥' : '$' }}{{ fmtNum(log.balance_after) }}</span>
          <span class="cash-log-note" v-if="log.reason">{{ log.reason }}</span>
          <span class="cash-log-date">{{ fmtDate(log.created_at) }}</span>
        </div>
      </div>
      <div v-else class="empty">暂无操作记录</div>
    </div>
  </div>

  <!-- ═══════ Earnings Calendar ═══════ -->
  <div v-if="tab==='earnings'" class="container">
    <div class="page-header"><h2>📅 财报日历</h2><button class="btn-outline btn-sm" @click="loadEarnings" :disabled="earningsLoading">{{ earningsLoading ? '加载中...' : '🔄 刷新' }}</button></div>

    <!-- 未来财报：倒计时卡片 -->
    <div class="section-title">📆 即将发布</div>
    <div v-if="earningsUpcoming.length > 0" class="earnings-upcoming-grid">
      <div v-for="e in earningsUpcoming" :key="e.symbol + '-' + e.report_date"
        class="earnings-upcoming-card"
        :class="{
          'urgent': e.days_until != null && e.days_until <= 1,
          'soon': e.days_until != null && e.days_until <= 7 && e.days_until > 1
        }">
        <div class="earnings-card-top">
          <div class="earnings-card-stock">
            <span class="earnings-card-symbol mono">{{ e.symbol }}</span>
            <span class="earnings-card-name">{{ e.name }}</span>
          </div>
          <div class="earnings-card-countdown" v-if="e.days_until != null">
            <span class="countdown-num">{{ e.days_until === 0 ? '今天' : e.days_until === 1 ? '明天' : e.days_until }}</span>
            <span class="countdown-unit" v-if="e.days_until > 1">天后</span>
          </div>
        </div>
        <div class="earnings-card-date">{{ e.report_date }}</div>
        <div class="earnings-card-estimates" v-if="e.estimate_eps != null || e.estimate_revenue">
          <div class="earnings-estimate-row" v-if="e.estimate_eps != null">
            <span class="estimate-label">预期 EPS</span>
            <span class="estimate-value mono">${{ e.estimate_eps.toFixed(2) }}</span>
          </div>
          <div class="earnings-estimate-row" v-if="e.estimate_revenue">
            <span class="estimate-label">预期营收</span>
            <span class="estimate-value mono">${{ (e.estimate_revenue / 1e9).toFixed(2) }}B</span>
          </div>
        </div>
      </div>
    </div>
    <div class="card" v-else><div class="empty">{{ earningsLoading ? '加载中...' : '未来30天暂无财报日期' }}</div></div>

    <!-- 最近财报：按股票分组 -->
    <div class="section-title" style="margin-top:24px">📊 最近财报</div>
    <div v-if="earningsRecentGrouped.length > 0" class="earnings-by-stock">
      <div v-for="group in earningsRecentGrouped" :key="group.symbol" class="earnings-stock-group">
        <!-- 股票标题行 -->
        <div class="earnings-stock-group-header">
          <span class="earnings-card-symbol mono">{{ group.symbol }}</span>
          <span class="earnings-card-name">{{ group.name }}</span>
          <div class="eps-sparkline-wrap" v-if="epsSparkline(group.records)" :title="'EPS趋势：' + epsSparkline(group.records).pts.map(p=>p.actual_eps.toFixed(2)).join(' → ')">
            <span class="eps-sparkline-label">EPS趋势</span>
            <svg :width="epsSparkline(group.records).W" :height="epsSparkline(group.records).H" class="eps-sparkline-svg">
              <!-- 渐变填充 -->
              <defs>
                <linearGradient :id="'sg-'+group.symbol" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" :stop-color="epsSparkline(group.records).trend==='up' ? '#3fb950' : '#f85149'" stop-opacity="0.3"/>
                  <stop offset="100%" :stop-color="epsSparkline(group.records).trend==='up' ? '#3fb950' : '#f85149'" stop-opacity="0"/>
                </linearGradient>
              </defs>
              <!-- 填充区域 -->
              <path
                :d="epsSparkline(group.records).path + ` L${epsSparkline(group.records).last[0].toFixed(1)},${epsSparkline(group.records).H} L3,${epsSparkline(group.records).H} Z`"
                :fill="'url(#sg-'+group.symbol+')'"
              />
              <!-- 折线 -->
              <path
                :d="epsSparkline(group.records).path"
                fill="none"
                :stroke="epsSparkline(group.records).trend==='up' ? '#3fb950' : '#f85149'"
                stroke-width="1.5"
                stroke-linejoin="round"
                stroke-linecap="round"
              />
              <!-- 末点圆点 -->
              <circle
                :cx="epsSparkline(group.records).last[0]"
                :cy="epsSparkline(group.records).last[1]"
                r="2.5"
                :fill="epsSparkline(group.records).trend==='up' ? '#3fb950' : '#f85149'"
              />
            </svg>
          </div>
        </div>
        <!-- 该股票的财报记录列表 -->
        <div class="earnings-record-list">
          <div v-for="e in group.records" :key="e.report_date"
            class="earnings-record-row"
            :class="e.beat_miss === 'beat' ? 'record-beat' : e.beat_miss === 'miss' ? 'record-miss' : e.beat_miss === 'met' ? 'record-met' : ''">
            <span class="record-date mono">{{ e.report_date || '-' }}</span>
            <div class="record-eps" v-if="e.estimate_eps != null || e.actual_eps != null">
              <span class="record-eps-item">
                <span class="eps-label">预期</span>
                <span class="mono">{{ e.estimate_eps != null ? '$' + e.estimate_eps.toFixed(2) : '-' }}</span>
              </span>
              <span class="record-eps-arrow">→</span>
              <span class="record-eps-item">
                <span class="eps-label">实际</span>
                <span class="mono" :class="e.beat_miss === 'beat' ? 'text-green' : e.beat_miss === 'miss' ? 'text-red' : ''">
                  {{ e.actual_eps != null ? '$' + e.actual_eps.toFixed(2) : '—' }}
                </span>
              </span>
              <span class="record-diff" v-if="e.estimate_eps != null && e.actual_eps != null"
                :class="e.actual_eps >= e.estimate_eps ? 'text-green' : 'text-red'">
                {{ e.actual_eps >= e.estimate_eps ? '+' : '' }}{{ (((e.actual_eps - e.estimate_eps) / Math.abs(e.estimate_eps)) * 100).toFixed(1) }}%
              </span>
            </div>
            <span v-if="e.beat_miss === 'beat'" class="earnings-badge beat">✅ 超预期</span>
            <span v-else-if="e.beat_miss === 'miss'" class="earnings-badge miss">❌ 未达预期</span>
            <span v-else-if="e.beat_miss === 'met'" class="earnings-badge met">🟰 符合预期</span>
            <span v-else class="earnings-badge muted">— 待定</span>
          </div>
        </div>
      </div>
    </div>
    <div class="card" v-else><div class="empty">{{ earningsLoading ? '加载中...' : '暂无最近财报数据' }}</div></div>

    <!-- 老李财报判断区块 -->
    <div class="section-title" style="margin-top:24px">💰 老李判断</div>
    <div v-if="earningsAnalysis.length > 0" class="earnings-analysis-list">
      <div v-for="a in earningsAnalysis" :key="a.id" class="earnings-analysis-card-full">
        <!-- 头部 -->
        <div class="eaf-header">
          <div class="eaf-title">
            <span class="eaf-symbol mono">{{ a.symbol }}</span>
            <span class="eaf-quarter">{{ a.fiscal_quarter }}</span>
            <span class="eaf-date">{{ a.report_date }}</span>
          </div>
          <div class="eaf-badges">
            <span v-if="a.verdict === 'beat'" class="earnings-badge beat">✅ 超预期</span>
            <span v-else-if="a.verdict === 'miss'" class="earnings-badge miss">❌ 未达预期</span>
            <span v-else-if="a.verdict === 'met'" class="earnings-badge met">🟰 符合预期</span>
            <span v-if="a.short_term === 'bullish'" class="earnings-badge beat">📈 短期利好</span>
            <span v-else-if="a.short_term === 'bearish'" class="earnings-badge miss">📉 短期利空</span>
            <span v-else-if="a.short_term === 'neutral'" class="earnings-badge met">➡️ 短期中性</span>
            <span v-if="a.price_reaction_pct != null" class="earnings-badge" :class="a.price_reaction_pct >= 0 ? 'beat' : 'miss'">
              股价反应 {{ a.price_reaction_pct >= 0 ? '+' : '' }}{{ a.price_reaction_pct.toFixed(1) }}%
            </span>
          </div>
        </div>
        <!-- 核心数据 -->
        <div class="eaf-metrics">
          <div class="eaf-metric" v-if="a.eps_actual != null">
            <span class="eaf-metric-label">EPS</span>
            <span class="eaf-metric-val mono" :class="a.eps_surprise_pct >= 0 ? 'text-green' : 'text-red'">
              ${{ a.eps_actual?.toFixed(2) }}
            </span>
            <span class="eaf-metric-sub" v-if="a.eps_estimate != null">预期 ${{ a.eps_estimate?.toFixed(2) }}</span>
            <span class="eaf-metric-diff" v-if="a.eps_surprise_pct != null" :class="a.eps_surprise_pct >= 0 ? 'text-green' : 'text-red'">
              {{ a.eps_surprise_pct >= 0 ? '+' : '' }}{{ a.eps_surprise_pct.toFixed(1) }}%
            </span>
          </div>
          <div class="eaf-metric" v-if="a.revenue_actual != null">
            <span class="eaf-metric-label">营收</span>
            <span class="eaf-metric-val mono" :class="a.revenue_surprise_pct >= 0 ? 'text-green' : 'text-red'">
              ${{ a.revenue_actual?.toFixed(2) }}B
            </span>
            <span class="eaf-metric-sub" v-if="a.revenue_estimate != null">预期 ${{ a.revenue_estimate?.toFixed(2) }}B</span>
            <span class="eaf-metric-diff" v-if="a.revenue_surprise_pct != null" :class="a.revenue_surprise_pct >= 0 ? 'text-green' : 'text-red'">
              {{ a.revenue_surprise_pct >= 0 ? '+' : '' }}{{ a.revenue_surprise_pct.toFixed(1) }}%
            </span>
          </div>
        </div>
        <!-- 指引 -->
        <div class="eaf-guidance" v-if="a.guidance">
          <span class="eaf-section-label">📋 指引</span>
          <span class="eaf-guidance-text">{{ a.guidance }}</span>
        </div>
        <!-- 分析正文 -->
        <div class="eaf-analysis" v-if="a.analysis">
          <span class="eaf-section-label">🔍 分析</span>
          <div class="eaf-analysis-text">{{ a.analysis }}</div>
        </div>
        <!-- 持仓建议 -->
        <div class="eaf-advice" v-if="a.holding_advice">
          <span class="eaf-section-label">💡 持仓建议</span>
          <div class="eaf-advice-text">{{ a.holding_advice }}</div>
        </div>
      </div>
    </div>
    <div class="card" v-else><div class="empty">暂无财报分析，财报发布后老李会自动写入</div></div>
  </div>

  <!-- ═══════ Quant Signals ═══════ -->
  <div v-if="tab==='quant'" class="container">
    <div class="page-header">
      <h2>📊 量化信号</h2>
      <div class="page-actions">
        <button class="btn-outline btn-sm" @click="loadQuantSignals" :disabled="quantLoading">🔄 刷新</button>
        <button class="btn-primary btn-sm" @click="refreshQuant" :disabled="quantRefreshing">{{ quantRefreshing ? '更新中...' : '📡 拉取最新数据' }}</button>
      </div>
    </div>

    <div v-if="quantLoading && quantSignals.length===0" class="card"><div class="empty">加载中...</div></div>

    <div v-if="quantSignals.length > 0" class="quant-grid">
      <div v-for="sig in quantSignals" :key="sig.symbol" class="quant-card" @click="toggleQuantDetail(sig.symbol)">
        <div class="quant-card-header">
          <div class="quant-card-title">
            <span class="stock-symbol">{{ sig.symbol }}</span>
            <span class="stock-name">{{ sig.name }}</span>
            <span class="quant-market-badge" :class="'market-' + sig.market">{{ sig.market === 'cn' ? 'A股' : '美股' }}</span>
          </div>
          <div class="quant-score" v-if="sig.score != null" :style="{ color: scoreColor(sig.score) }">
            <span class="quant-score-value">{{ sig.score.toFixed(0) }}</span>
            <span class="quant-score-label">{{ scoreLabel(sig.score) }}</span>
          </div>
        </div>

        <div class="quant-metrics">
          <div v-for="(mdata, mkey) in sig.metrics" :key="mkey" class="quant-metric-item">
            <div class="quant-metric-label">{{ metricLabel(mkey) }}</div>
            <div class="quant-metric-value">{{ mdata.value != null ? mdata.value.toFixed(2) : '-' }}{{ metricUnit(mkey) }}</div>
            <div class="quant-metric-pct" v-if="mdata.percentile != null">
              <div class="pct-bar-bg">
                <div class="pct-bar-fill" :style="{ width: mdata.percentile + '%', background: pctColor(mdata.percentile) }"></div>
                <div class="pct-bar-marker" :style="{ left: mdata.percentile + '%' }"></div>
              </div>
              <span class="pct-text" :style="{ color: pctColor(mdata.percentile) }">{{ mdata.percentile.toFixed(0) }}% {{ pctLabel(mdata.percentile) }}</span>
            </div>
          </div>
        </div>

        <!-- Expanded: PE history chart -->
        <div v-if="quantExpandedSymbol === sig.symbol" class="quant-detail" @click.stop>
          <div class="quant-detail-header">📈 PE(TTM) 历史分位走势</div>
          <div ref="quantPeChartRef" class="chart-box" style="height:250px"></div>
        </div>
      </div>
    </div>

    <div v-if="!quantLoading && quantSignals.length===0" class="card">
      <div class="empty">暂无量化信号数据，点击「📡 拉取最新数据」开始</div>
    </div>
  </div>

  <!-- ═══════ TradingView Chart Modal ═══════ -->
  <div v-show="showChartModal" class="tv-modal-overlay" @click.self="closeChartModal" @keydown.esc="closeChartModal">
    <div class="tv-modal">
      <div class="tv-modal-header">
        <span class="tv-modal-title">📈 {{ chartSymbol }}</span>
        <button class="tv-modal-close" @click="closeChartModal">✕</button>
      </div>
      <div ref="tvContainer" class="tv-modal-body"></div>
    </div>
  </div>

  <!-- ═══════ Mobile Bottom Navigation Bar ═══════ -->
  <nav class="mobile-bottom-nav">
    <a :class="{active: tab==='dashboard'}" @click="switchTab('dashboard')"><span class="tab-icon">📈</span>看板</a>
    <a :class="{active: tab==='portfolio'}" @click="switchTab('portfolio')"><span class="tab-icon">💰</span>持仓</a>
    <a :class="{active: tab==='alerts'}" @click="switchTab('alerts')"><span class="tab-icon">🔔</span>预警</a>
    <a :class="{active: moreMenuOpen || ['quant','earnings','history','transactions','cash'].includes(tab)}" @click.stop="moreMenuOpen=!moreMenuOpen"><span class="tab-icon">⋯</span>更多</a>
    <div class="mobile-more-menu" v-show="moreMenuOpen" @click.stop>
      <a @click="switchTab('earnings');moreMenuOpen=false"><span class="more-icon">📅</span>财报</a>
      <a @click="switchTab('quant');moreMenuOpen=false"><span class="more-icon">📊</span>量化</a>
      <a @click="switchTab('history');moreMenuOpen=false"><span class="more-icon">📜</span>告警历史</a>
      <a @click="switchTab('transactions');moreMenuOpen=false"><span class="more-icon">📝</span>交易记录</a>
      <a @click="switchTab('cash');moreMenuOpen=false"><span class="more-icon">💵</span>现金</a>
    </div>
  </nav>
</template>
