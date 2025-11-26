// -------- Splash Screen ----------
function hideSplashScreen() {
  const splash = document.getElementById('splashScreen');
  if (splash) {
    splash.classList.add('fade-out');
    setTimeout(() => {
      splash.style.display = 'none';
    }, 600);
  }
}

const tg = window.Telegram?.WebApp;
if (tg) {
  tg.expand();
  tg.enableClosingConfirmation();
  tg.setHeaderColor('secondary_bg_color');
  tg.setBackgroundColor('#0c0e12');
}

// -------- i18n ----------
const i18n = { lang:'ru', dict:{} };

// Detect initial language from Telegram → localStorage (only if manually set) → default
function detectInitialLang() {
  const supportedLangs = ['ru', 'en'];
  
  // Check if user manually changed language before
  const manualLangChange = localStorage.getItem('lang_manual');
  
  // Try to get language from Telegram WebApp
  let tgLang = null;
  try {
    const languageCode = tg?.initDataUnsafe?.user?.language_code;
    console.log('[Language Detection] Telegram language_code:', languageCode);
    console.log('[Language Detection] Full Telegram user data:', tg?.initDataUnsafe?.user);
    if (languageCode) {
      // Normalize language code (e.g., 'ru-RU' → 'ru', 'en-US' → 'en')
      tgLang = languageCode.toLowerCase().split('-')[0];
      console.log('[Language Detection] Normalized Telegram lang:', tgLang);
    }
  } catch (e) {
    console.log('[Language Detection] Could not get Telegram language:', e);
  }
  
  const storedLang = localStorage.getItem('lang');
  console.log('[Language Detection] localStorage lang:', storedLang);
  console.log('[Language Detection] Manual language change:', manualLangChange);
  
  // Priority: Manual user choice → Telegram → default 'ru'
  if (manualLangChange === 'true' && storedLang && supportedLangs.includes(storedLang)) {
    console.log('[Language Detection] ✅ Using manually set language:', storedLang);
    return storedLang;
  }
  
  if (tgLang && supportedLangs.includes(tgLang)) {
    console.log('[Language Detection] ✅ Using Telegram language:', tgLang);
    return tgLang;
  }
  
  console.log('[Language Detection] ✅ Using default language: ru');
  return 'ru'; // Default
}

async function loadTranslations(){
  try{
    const r = await fetch('/i18n/translations.json');
    i18n.dict = await r.json();
    console.log('[Translations] Loaded successfully. Keys:', Object.keys(i18n.dict));
    console.log('[Translations] RU keys count:', Object.keys(i18n.dict.ru || {}).length);
    console.log('[Translations] EN keys count:', Object.keys(i18n.dict.en || {}).length);
  }catch(e){ 
    console.error('[Translations] Load failed:', e); 
    i18n.dict={ru:{},en:{}}; 
  }
  
  // Use detected language
  const detectedLang = detectInitialLang();
  console.log('[Translations] Final detected language:', detectedLang);
  console.log('[Translations] Dictionary for', detectedLang, ':', i18n.dict[detectedLang]);
  setLang(detectedLang);
}

function t(k){ return i18n.dict[i18n.lang]?.[k] || k; }

function setLang(lang, isManual = false){
  i18n.lang=(['ru','en'].includes(lang)?lang:'ru');
  localStorage.setItem('lang', i18n.lang);
  if (isManual) {
    localStorage.setItem('lang_manual', 'true');
    console.log('[Language] Manually set language to:', i18n.lang);
  }
  document.querySelectorAll('[data-i18n]').forEach(el=>{
    el.textContent = t(el.getAttribute('data-i18n'));
  });
}
function toast(m){
  const el=document.getElementById('toast'); if(!el) return;
  el.textContent=m; el.classList.add('show'); setTimeout(()=>el.classList.remove('show'),3000);
}

// -------- Auth bootstrap ----------
let TG_USER=null; try{ TG_USER = tg?.initDataUnsafe?.user || null }catch(e){}

// Authenticated fetch wrapper - automatically adds X-Telegram-Id header
const apiFetch = async (url, options = {}) => {
  options.headers = options.headers || {};
  options.headers['X-Telegram-Id'] = TG_USER?.id || '999999';
  return fetch(url, options);
};

async function ensureUser(){
  try{
    await apiFetch('/api/auth/ensure',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        telegram_id: TG_USER?.id||null,
        username: TG_USER?.username||null,
        language: i18n.lang
      })
    });
  }catch(e){ console.error('ensureUser failed', e); }
}
function setActive(tab){
  document.querySelectorAll('.nav-item').forEach(n=>n.classList.remove('active'));
  const el=document.querySelector(`.nav-item[data-tab="${tab}"]`);
  if(el){ el.classList.add('active', tab); }
}
function shortAddr(s){ if(!s) return ''; return s.slice(0,5)+'…'+s.slice(-4); }

// Restore original header
function restoreHeader(){
  const headerBrand = document.querySelector('.header .brand');
  const headerActions = document.querySelector('.header .actions');
  
  if(headerBrand){
    headerBrand.innerHTML = `
      <img src="/static/img/logo.png" onerror="this.style.display='none';document.getElementById('brandTitle').style.display='block'">
      <span id="brandTitle" class="title" style="display:none" data-i18n="app.title">NadexRes</span>
    `;
  }
  
  if(headerActions){
    headerActions.innerHTML = `
      <span class="badge">Mini App</span>
      <button class="icon-btn" id="btnLang" title="Language / Язык">🌐</button>
      <a class="icon-btn" href="#" title="Notifications">🔔</a>
    `;
    // Re-attach language switcher
    const btnLang = document.getElementById('btnLang');
    if(btnLang){ btnLang.onclick = ()=>{ setLang(i18n.lang==='ru'?'en':'ru', true); toast(t('toast.saved')); }; }
  }
}

// -------- Assets (ЛК) ----------
async function renderAssets(){
  try{
    restoreHeader(); // Restore original header
    setActive('assets');
    const cont=document.getElementById('root');
    let user={ balance_usdt:0, wallets:{}, addresses:{}, profile_id:0 };
    try{ user = await (await apiFetch('/api/user')).json(); }catch(e){ console.error('api/user failed',e); }

    cont.innerHTML = `
      <div class="container">
        <div class="balance-card">
          <div class="small">${t('common.balance')}</div>
          <div class="balance-amount">${Number(user.balance_usdt||0).toFixed(2)} <span class="currency">${t('common.usdt')}</span></div>
          <div class="balance-actions">
            <button class="btn btn-primary" id="btnDeposit" data-i18n="btn.deposit">${t('btn.deposit')}</button>
            <button class="btn btn-purple" id="btnWithdraw" data-i18n="btn.withdraw">${t('btn.withdraw')}</button>
            <button class="btn btn-green" id="btnExchange" data-i18n="btn.exchange">${t('btn.exchange')}</button>
          </div>
          <div class="notice small">${t('deposit.min_notice')}</div>
        </div>

        <div class="section" id="walletsSection">
          <div class="section-header" id="walletsToggle">
            <div class="section-title" data-i18n="wallets.title">${t('wallets.title')}</div>
            <div class="badge">10+</div>
          </div>
          <div class="section-content" id="walletsContent">
            <div class="wallet-grid" id="walletGrid"></div>
          </div>
        </div>

        <div class="section">
          <div class="section-header" id="histToggle">
            <div class="section-title" data-i18n="history.title">${t('history.title')}</div>
          </div>
          <div class="section-content hidden" id="historyWrap">
            <div id="historyList"></div>
          </div>
        </div>
      </div>
      <button class="fab" id="fabSupport">Чат</button>`;

    // Свернуть/развернуть
    document.getElementById('walletsToggle').onclick = ()=> document.getElementById('walletsContent').classList.toggle('hidden');
    document.getElementById('histToggle').onclick    = ()=> document.getElementById('historyWrap').classList.toggle('hidden');

    // Кошельки (10+) - загружаем цены для отображения
    const grid = document.getElementById('walletGrid');
    const cryptoList = ['USDT','BTC','ETH','TON','SOL','BNB','XRP','DOGE','LTC','TRX'];
    
    // Получаем цены для всех криптовалют
    let prices = {};
    try {
      const pricesRes = await fetch('/api/prices');
      prices = await pricesRes.json();
    } catch(e) { console.error('Failed to load prices', e); }
    
    cryptoList.forEach(sym=>{
      const bal = sym==='USDT' ? user.balance_usdt : (user.wallets?.[sym] || 0);
      const price = prices[sym] || (sym === 'USDT' ? 1 : 0);
      const valueUSDT = bal * price;
      const hasBalance = bal > 0.0001;
      
      const card = document.createElement('div');
      card.className='wallet-card';
      card.style.cssText = hasBalance ? 'border-color:rgba(139,92,246,0.4);background:linear-gradient(135deg,rgba(139,92,246,0.08),#0b0f15)' : '';
      
      const logo = cryptoLogos[sym] || '';
      const logoHTML = logo ? `<img src="${logo}" style="width:24px;height:24px;border-radius:50%" onerror="this.style.display='none'"/>` : `<span style="font-size:18px">💰</span>`;
      
      card.innerHTML = `
        <div class="wallet-top" style="margin-bottom:8px">
          <div style="display:flex;align-items:center;gap:8px">
            ${logoHTML}
            <span style="font-weight:700;font-size:15px">${sym}</span>
          </div>
          ${sym !== 'USDT' ? `<span style="font-size:11px;color:#9ca3af">$${Number(price).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2})}</span>` : ''}
        </div>
        <div class="wallet-balance" style="font-size:16px;font-weight:700;color:${hasBalance ? '#10b981' : '#6b7280'}">${Number(bal||0).toFixed(sym==='USDT'?2:6)} ${sym}</div>
        ${sym !== 'USDT' && hasBalance ? `<div style="font-size:12px;color:#9ca3af;margin-top:4px">≈ ${valueUSDT.toFixed(2)} USDT</div>` : ''}`;
      card.onclick = ()=>openWallet(sym);
      grid.appendChild(card);
    });

    // История транзакций (только пополнения и выводы)
    try{
      const history = await (await apiFetch('/api/history')).json();
      const historyList = document.getElementById('historyList');
      
      // DEBUG: Check translations availability
      console.log('[History Render] Current language:', i18n.lang);
      console.log('[History Render] Dictionary available:', !!i18n.dict[i18n.lang]);
      console.log('[History Render] Test translation:', t('history.type.deposit'));
      
      // Фильтруем только deposits и withdrawals
      const transactions = (history || []).filter(h => h.type === 'deposit' || h.type === 'withdrawal');
      
      if (transactions.length === 0) {
        historyList.innerHTML = `<div style="text-align:center;color:#888;padding:20px">${t('history.empty')}</div>`;
      } else {
        transactions.forEach((h, idx) => {
          const card = document.createElement('div');
          card.className = 'history-card';
          card.style.cssText = 'background:#1a1a1a;border-radius:8px;padding:12px 15px;margin-bottom:8px;cursor:pointer;transition:all 0.2s';
          
          const date = new Date(h.created_at);
          const localDate = date.toLocaleDateString();
          const localTime = date.toLocaleTimeString();
          
          const typeIcon = h.type === 'deposit' ? '💳' : '💸';
          const typeText = h.type === 'deposit' ? t('history.type.deposit') : t('history.type.withdrawal');
          const amountColor = h.type === 'deposit' ? '#10b981' : '#ef4444';
          
          // Prepare withdrawal details
          let withdrawalDetailsHTML = '';
          if (h.type === 'withdrawal' && h.details) {
            if (h.details.modified_to_crypto) {
              withdrawalDetailsHTML = `
                <div><b>${t('history.destination')}:</b> ${t('history.withdrawal.crypto')}</div>
                <div style="margin-top:4px"><b>${t('history.withdrawal.crypto')}:</b> ${h.details.crypto_currency || 'USDT'}</div>
                <div style="margin-top:4px"><b>${t('history.withdrawal.address')}:</b> <span style="font-family:monospace;font-size:11px">${h.details.crypto_address || 'N/A'}</span></div>
              `;
            } else {
              withdrawalDetailsHTML = `
                <div><b>${t('history.destination')}:</b> ${t('history.bank_card')}</div>
                <div style="margin-top:4px"><b>${t('history.withdrawal.amount_rub')}:</b> ${h.details.modified_amount_rub || h.details.amount_rub || 'N/A'} ₽</div>
                <div style="margin-top:4px"><b>${t('history.withdrawal.card')}:</b> **** ${h.details.card_number || 'N/A'}</div>
                <div style="margin-top:4px"><b>${t('history.withdrawal.recipient')}:</b> ${h.details.full_name || 'N/A'}</div>
              `;
            }
          }
          
          card.innerHTML = `
            <div class="history-main" style="display:flex;justify-content:space-between;align-items:center">
              <div style="display:flex;align-items:center;gap:10px">
                <div style="font-size:24px">${typeIcon}</div>
                <div>
                  <div style="font-weight:600;color:#fff;font-size:14px">${typeText}</div>
                  <div style="color:#888;font-size:12px">${localDate} ${localTime}</div>
                </div>
              </div>
              <div style="text-align:right">
                <div style="font-weight:700;color:${amountColor};font-size:16px">${h.type === 'deposit' ? '+' : '-'}${h.amount} ${h.currency}</div>
                <div style="color:#888;font-size:11px">▼</div>
              </div>
            </div>
            <div class="history-details" style="display:none;margin-top:12px;padding-top:12px;border-top:1px solid #2a2a2a">
              <div style="color:#9ca3af;font-size:13px;line-height:1.6">
                ${h.type === 'deposit' 
                  ? `<div><b>${t('history.source')}:</b> ${h.details?.source || t('history.source.crypto_pay')}</div>` 
                  : withdrawalDetailsHTML}
                ${h.details?.fee ? `<div style="margin-top:4px"><b>${t('history.fee')}:</b> ${h.details.fee} ${h.currency}</div>` : ''}
                <div style="margin-top:4px"><b>${t('history.status')}:</b> ${(() => {
                  const statusKey = 'history.status.' + h.status;
                  const translated = t(statusKey);
                  return translated !== statusKey ? translated : h.status;
                })()}</div>
              </div>
            </div>
          `;
          
          // Toggle details on click
          card.onclick = () => {
            const details = card.querySelector('.history-details');
            const arrow = card.querySelector('.history-main > div:last-child > div:last-child');
            if (details.style.display === 'none') {
              details.style.display = 'block';
              arrow.textContent = '▲';
            } else {
              details.style.display = 'none';
              arrow.textContent = '▼';
            }
          };
          
          historyList.appendChild(card);
        });
      }
    }catch(e){ console.error('history failed',e); }

    document.getElementById('btnDeposit').onclick = openDeposit;
    document.getElementById('btnWithdraw').onclick = openWithdraw;
    document.getElementById('btnExchange').onclick = openExchange;
    document.getElementById('fabSupport').onclick = openSupport;
  }catch(e){
    console.error('renderAssets crash', e);
    toast('Ошибка загрузки Активов');
  }
}

// -------- Deposit ----------
async function openDeposit(){
  setActive('assets');
  const cont=document.getElementById('root');
  const userData = await (await apiFetch('/api/user')).json();
  const isAdmin = userData.is_admin || false;
  const minAmount = isAdmin ? 0 : 50;
  const minAttr = isAdmin ? '' : 'min="50"';
  const noticeText = isAdmin ? 'Админ: нет минимума' : t('deposit.min_notice');
  
  cont.innerHTML = `
  <div class="container">
    <button class="btn" id="backAssets">← Назад</button>
    <div class="section" style="margin-top:10px">
      <div class="section-header"><div class="section-title">${t('btn.deposit')}</div></div>
      <div class="section-content">
        <label class="label">Сумма (USDT)</label>
        <input id="depAmount" type="number" inputmode="numeric" class="input" ${minAttr} placeholder="${isAdmin ? '0.01' : '50'}"/>
        <div class="notice small">${noticeText}</div>
        <div class="small" id="depCalc" style="margin-top:8px;color:#888;"></div>
        <button class="btn btn-primary fullwidth" id="depSubmit" style="margin-top:12px">${t('btn.deposit')}</button>
      </div>
    </div>
  </div>`;
  document.getElementById('backAssets').onclick = renderAssets;
  const depAmountEl = document.getElementById('depAmount');
  const depCalcEl = document.getElementById('depCalc');
  
  // Показываем комиссию при вводе суммы
  depAmountEl.oninput = () => {
    const v = Number(depAmountEl.value || 0);
    if (v > 0) {
      const FEE_PERCENT = 2.5;
      const fee = (v * FEE_PERCENT / 100).toFixed(4);
      const afterFee = (v - fee).toFixed(4);
      depCalcEl.innerHTML = `💳 Комиссия: <b>${fee} USDT (${FEE_PERCENT}%)</b> • ✅ К зачислению: <b>${afterFee} USDT</b>`;
    } else {
      depCalcEl.textContent = '';
    }
  };
  
  document.getElementById('depSubmit').onclick = async ()=>{
    const v=Number(document.getElementById('depAmount').value||0);
    if(!v||v<minAmount){ toast(isAdmin ? 'Введите сумму' : t('deposit.min_notice')); return; }
    try{
      // Показываем процесс создания счета
      toast('Создаем счет...');
      
      const res = await apiFetch('/api/deposit/create_invoice',{
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ amount: v })
      });
      const data = await res.json();
      
      if(data.ok){ 
        // Открываем ссылку на оплату в Crypto Bot
        if(data.pay_url) {
          // Используем Telegram WebApp API для открытия ссылки
          if(tg && tg.openLink) {
            tg.openLink(data.pay_url);
          } else if(tg && tg.openTelegramLink) {
            tg.openTelegramLink(data.pay_url);
          } else {
            // Fallback для браузера
            window.open(data.pay_url, '_blank');
          }
          
          // Показываем уведомление
          toast('Переходим к оплате...');
          
          // Закрываем приложение через небольшую задержку
          setTimeout(() => {
            if(tg) {
              tg.close();
            }
          }, 1000);
        } else {
          // Если нет ссылки, просто закрываем
          toast('Счет создан. Проверьте сообщения от бота.');
          setTimeout(() => {
            if(tg) {
              tg.close();
            }
          }, 1500);
        }
      } else { 
        toast(data.error||t('toast.error')); 
      }
    }catch(e){ 
      console.error('deposit error', e); 
      toast(t('toast.error')); 
    }
  };
}

// -------- Withdraw ----------
async function openWithdraw(){
  setActive('assets');
  const cont=document.getElementById('root');
  cont.innerHTML = `
  <div class="container">
    <button class="btn" id="backAssets">← Назад</button>
    <div class="section" style="margin-top:10px">
      <div class="section-header"><div class="section-title">Вывод USDT</div></div>
      <div class="section-content">
        <label class="label">Сумма (USDT)</label>
        <input type="number" inputmode="decimal" id="wAmount" class="input" placeholder="50" min="10" step="0.01"/>
        <div class="notice small">💡 Минимальная сумма: 10 USDT</div>
        
        <div class="notice" style="margin-top:12px;padding:10px;background:rgba(139,92,246,0.1);border-left:3px solid #8b5cf6;border-radius:4px;">
          💸 <b>Важно:</b> Вывод осуществляется в <b>рублях (RUB)</b> на банковскую карту с учётом актуального курса USD/RUB.
        </div>
        
        <div class="inline" style="margin-top:12px">
          <div style="flex:2">
            <label class="label">Номер карты</label>
            <input type="tel" inputmode="numeric" id="wCard" class="input" placeholder="4000000000000000"/>
          </div>
          <div style="flex:3">
            <label class="label">ФИО получателя</label>
            <input type="text" id="wName" class="input" placeholder="Иванов Иван Иванович"/>
          </div>
        </div>
        
        <button class="btn btn-purple fullwidth" id="wSubmit" style="margin-top:12px" disabled>${t('withdraw.submit')}</button>
        <div class="small" id="wCalc"></div>
      </div>
    </div>
  </div>`;
  document.getElementById('backAssets').onclick = renderAssets;
  const amountEl=document.getElementById('wAmount'); const cardEl=document.getElementById('wCard'); const nameEl=document.getElementById('wName'); const btn=document.getElementById('wSubmit'); const calcEl=document.getElementById('wCalc');
  
  async function recalc(){
    const a=Number(amountEl.value||0);
    const card=(cardEl.value||'').replace(/\s+/g,'');
    const name=(nameEl.value||'').trim();
    btn.disabled=!(a>=10 && card.length>=13 && name.length>=3);
    
    if(a>=10){
      try{
        const FEE_PERCENT = 5.7;
        const fee = (a * FEE_PERCENT / 100).toFixed(4);
        const afterFee = (a - fee).toFixed(4);
        calcEl.innerHTML=`<div style="margin-top:8px;">💳 Комиссия: <b>${fee} USDT (${FEE_PERCENT}%)</b></div><div>✅ К выводу: <b>${afterFee} USDT</b></div>`;
      }catch(e){ calcEl.textContent=''; }
    }else{ calcEl.textContent=''; }
  }
  
  amountEl.oninput = recalc;
  cardEl.oninput = recalc;
  nameEl.oninput = recalc;
  recalc();
  
  btn.onclick = async ()=>{
    const payload = {
      amount_usdt: Number(amountEl.value||0),
      card_number: (cardEl.value||'').replace(/\s+/g,''),
      full_name: (nameEl.value||'').trim()
    };
    
    if(!payload.card_number || payload.card_number.length < 13) {
      toast('Введите корректный номер карты');
      return;
    }
    
    if(!payload.full_name || payload.full_name.length < 3) {
      toast('Введите ФИО получателя');
      return;
    }
    
    try{
      const res = await apiFetch('/api/withdraw',{ method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
      const data = await res.json();
      if(data.ok){ toast('Заявка отправлена. Статус: В ожидании'); renderAssets(); } else toast(data.error||t('toast.error'));
    }catch(e){ toast(t('toast.error')); }
  };
}

// -------- Exchange ----------
async function openExchange(){
  setActive('assets');
  const cont=document.getElementById('root');
  
  // Get user data for balance display
  let user = { balance_usdt: 0, wallets: {} };
  try { user = await (await apiFetch('/api/user')).json(); } catch(e) {}
  
  const cryptoOptions = ['USDT','BTC','ETH','TON','SOL','BNB','XRP','DOGE','LTC','TRX'];
  const fromOptions = cryptoOptions.map(c => `<option value="${c}">${c}</option>`).join('');
  const toOptions = cryptoOptions.map(c => `<option value="${c}"${c === 'BTC' ? ' selected' : ''}>${c}</option>`).join('');
  
  cont.innerHTML = `
  <div class="container">
    <button class="btn" id="backAssets">← Назад</button>
    <div class="section" style="margin-top:10px">
      <div class="section-header"><div class="section-title">🔄 Обмен криптовалют</div></div>
      <div class="section-content">
        <div style="background:linear-gradient(135deg,rgba(139,92,246,0.1),rgba(59,130,246,0.05));border:1px solid rgba(139,92,246,0.3);border-radius:12px;padding:14px;margin-bottom:16px">
          <div style="font-size:12px;color:#9ca3af;margin-bottom:4px">Доступный баланс</div>
          <div id="exAvailBalance" style="font-size:20px;font-weight:700;color:#10b981">${Number(user.balance_usdt||0).toFixed(2)} USDT</div>
        </div>
        
        <div class="inline" style="gap:8px;align-items:flex-end">
          <div style="flex:1">
            <label class="label">Отдаю</label>
            <select id="exFrom" style="width:100%;padding:12px;border-radius:10px;border:1px solid var(--border);background:#0c1118;color:#fff;font-size:15px">${fromOptions}</select>
          </div>
          <button id="exSwap" style="padding:12px;background:linear-gradient(135deg,#8b5cf6,#6366f1);border:none;border-radius:10px;color:#fff;font-size:18px;cursor:pointer;margin-bottom:0;min-width:48px" title="Поменять местами">⇄</button>
          <div style="flex:1">
            <label class="label">Получаю</label>
            <select id="exTo" style="width:100%;padding:12px;border-radius:10px;border:1px solid var(--border);background:#0c1118;color:#fff;font-size:15px">${toOptions}</select>
          </div>
        </div>
        
        
        <div style="margin-top:16px">
          <label class="label">Сумма</label>
          <div style="display:flex;gap:8px">
            <input type="number" inputmode="decimal" id="exAmount" class="input" placeholder="0.00" style="flex:1"/>
            <button id="exMax" style="padding:10px 16px;background:rgba(139,92,246,0.2);border:1px solid rgba(139,92,246,0.4);border-radius:10px;color:#c4b5fd;font-weight:600;cursor:pointer">MAX</button>
          </div>
        </div>
        
        <div id="exQuote" style="min-height:24px;margin-top:12px;padding:12px;background:rgba(16,185,129,0.1);border-radius:8px;text-align:center;font-weight:600;color:#10b981;display:none"></div>
        
        <div class="notice small" style="margin-top:12px;color:#888;text-align:center">💳 Комиссия 2% уже включена в курс</div>
        <button class="btn btn-green fullwidth" id="exSubmit" style="margin-top:16px;padding:16px;font-size:16px">🔄 Обменять</button>
      </div>
    </div>
  </div>`;
  
  document.getElementById('backAssets').onclick = renderAssets;
  const fromEl=document.getElementById('exFrom'), toEl=document.getElementById('exTo'), amtEl=document.getElementById('exAmount'), qEl=document.getElementById('exQuote');
  const balEl=document.getElementById('exAvailBalance');
  
  // Update available balance when currency changes
  function updateBalance() {
    const sym = fromEl.value;
    const bal = sym === 'USDT' ? user.balance_usdt : (user.wallets?.[sym] || 0);
    const decimals = sym === 'USDT' ? 2 : 6;
    balEl.textContent = `${Number(bal||0).toFixed(decimals)} ${sym}`;
  }
  
  // Update "to" select based on "from" selection
  function updateToOptions() {
    const fromVal = fromEl.value;
    const currentTo = toEl.value;
    let newToVal = currentTo;
    
    // If same currency selected, auto-switch
    if (fromVal === currentTo) {
      newToVal = fromVal === 'USDT' ? 'BTC' : 'USDT';
    }
    
    // Rebuild options with proper order: if from is crypto, put USDT first
    let orderedOptions = [...cryptoOptions];
    if (fromVal !== 'USDT') {
      // Put USDT first when converting crypto
      orderedOptions = ['USDT', ...cryptoOptions.filter(c => c !== 'USDT')];
    }
    
    toEl.innerHTML = orderedOptions
      .filter(c => c !== fromVal)
      .map(c => `<option value="${c}"${c === newToVal ? ' selected' : ''}>${c}</option>`)
      .join('');
  }
  
  // Swap button
  document.getElementById('exSwap').onclick = () => {
    const fromVal = fromEl.value;
    const toVal = toEl.value;
    fromEl.value = toVal;
    updateToOptions();
    toEl.value = fromVal;
    updateBalance();
    amtEl.value = '';
    qEl.style.display = 'none';
  };
  
  // Max button
  document.getElementById('exMax').onclick = () => {
    const sym = fromEl.value;
    const bal = sym === 'USDT' ? user.balance_usdt : (user.wallets?.[sym] || 0);
    amtEl.value = Number(bal||0).toFixed(sym === 'USDT' ? 2 : 6);
    quote();
  };
  
  // Initialize
  updateToOptions();
  
  function validateSame(){ 
    if(fromEl.value===toEl.value){ 
      qEl.textContent='Нельзя выбрать одинаковую валюту'; 
      qEl.style.display='block';
      qEl.style.background='rgba(239,68,68,0.1)';
      qEl.style.color='#ef4444';
      return false;
    } 
    qEl.style.display='none';
    return true; 
  }
  fromEl.onchange = () => { updateToOptions(); updateBalance(); validateSame(); quote(); };
  toEl.onchange = () => { validateSame(); quote(); };
  let lastQuote = null; // Store last quote for slippage protection
  async function quote(){
    if(!validateSame()) return;
    const a=Number(amtEl.value||0); 
    if(a<=0){ 
      qEl.style.display='none'; 
      lastQuote=null; 
      return; 
    }
    try{
      const r=await (await fetch(`/api/exchange/quote?from=${fromEl.value}&to=${toEl.value}&amount=${a}`)).json();
      lastQuote = r; // Save quote for later
      const toDecimals = toEl.value === 'USDT' ? 2 : 6;
      qEl.innerHTML = `Вы получите: <span style="font-size:18px">${Number(r.amount_to||0).toFixed(toDecimals)} ${toEl.value}</span>`;
      qEl.style.display='block';
      qEl.style.background='rgba(16,185,129,0.1)';
      qEl.style.color='#10b981';
    }catch(e){ 
      qEl.style.display='none'; 
      lastQuote=null; 
    }
  }
  amtEl.oninput=quote;
  document.getElementById('exSubmit').onclick = async ()=>{
    if(!validateSame()) return;
    const amount = Number(amtEl.value||0);
    if(amount <= 0) { toast('Введите сумму'); return; }
    
    try{
      // Send expected_amount_to for slippage protection
      const payload = {
        from: fromEl.value,
        to: toEl.value,
        amount: amount,
        expected_amount_to: lastQuote?.amount_to // Include last quote for slippage check
      };
      
      const res=await apiFetch('/api/exchange',{ method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
      const data=await res.json();
      if(data.ok){ 
        toast('✅ Обмен выполнен'); 
        lastQuote = null; // Clear quote
        renderAssets(); 
      } else {
        toast(data.error||t('toast.error'));
        // If slippage error, auto-refresh quote
        if(data.error && data.error.includes('Курс изменился')){
          setTimeout(() => quote(), 500);
        }
      }
    }catch(e){ 
      console.error('Exchange error:', e);
      toast(t('toast.error')); 
    }
  };
}

// -------- Wallet detail ----------
async function openWallet(sym){
  const cont=document.getElementById('root');
  const user = await (await apiFetch('/api/user')).json();
  const bal = user.wallets?.[sym] ?? (sym==='USDT'? user.balance_usdt: 0);
  cont.innerHTML = `
  <div class="container">
    <button class="btn" id="backAssets">← Назад</button>
    <div class="balance-card" style="margin-top:10px">
      <div class="small">${sym} ${t('common.balance')}</div>
      <div class="balance-amount">${Number(bal||0).toFixed(6)} <span class="currency">${sym}</span></div>
      <div class="balance-actions">
        <button class="btn btn-primary" id="wDep">${t('btn.deposit')}</button>
        <button class="btn btn-green" id="wEx">${t('btn.exchange')}</button>
      </div>
    </div>
    <div class="section">
      <div class="section-header" id="whToggle"><div class="section-title">${t('history.title')} (${sym})</div></div>
      <div class="section-content hidden" id="walletHist"></div>
    </div>
  </div>`;
  document.getElementById('backAssets').onclick = renderAssets;
  document.getElementById('wDep').onclick = openDeposit;
  document.getElementById('wEx').onclick = openExchange;
  document.getElementById('whToggle').onclick = ()=> document.getElementById('walletHist').classList.toggle('hidden');
  
  // Add Create Check button for admin (USDT wallet only)
  const isAdmin = TID && TID === `${ADMIN_ID}`;
  if (isAdmin && sym === 'USDT') {
    const checkBtn = document.createElement('button');
    checkBtn.className = 'btn btn-secondary';
    checkBtn.textContent = '🎁 Создать чек';
    checkBtn.style.marginTop = '10px';
    checkBtn.onclick = createCheck;
    document.querySelector('.balance-card').appendChild(checkBtn);
  }
  const h = await (await apiFetch('/api/history?symbol='+encodeURIComponent(sym))).json();
  const wrap = document.getElementById('walletHist'); const ul=document.createElement('div');
  (h||[]).forEach(x=>{ const row=document.createElement('div'); row.className='small'; row.textContent = `${x.type} • ${x.amount} ${x.currency} • ${new Date(x.created_at).toLocaleString()}`; ul.appendChild(row); });
  wrap.appendChild(ul);
}

// -------- Trade ----------
// Crypto logos mapping (using cryptocurrency-icons CDN)
const cryptoLogos = {
  'BTC': 'https://raw.githubusercontent.com/spothq/cryptocurrency-icons/master/svg/color/btc.svg',
  'ETH': 'https://raw.githubusercontent.com/spothq/cryptocurrency-icons/master/svg/color/eth.svg',
  'SOL': 'https://raw.githubusercontent.com/spothq/cryptocurrency-icons/master/svg/color/sol.svg',
  'ADA': 'https://raw.githubusercontent.com/spothq/cryptocurrency-icons/master/svg/color/ada.svg',
  'DOT': 'https://raw.githubusercontent.com/spothq/cryptocurrency-icons/master/svg/color/dot.svg',
  'LINK': 'https://raw.githubusercontent.com/spothq/cryptocurrency-icons/master/svg/color/link.svg',
  'MATIC': 'https://raw.githubusercontent.com/spothq/cryptocurrency-icons/master/svg/color/matic.svg',
  'AVAX': 'https://raw.githubusercontent.com/spothq/cryptocurrency-icons/master/svg/color/avax.svg',
  'XRP': 'https://raw.githubusercontent.com/spothq/cryptocurrency-icons/master/svg/color/xrp.svg',
  'DOGE': 'https://raw.githubusercontent.com/spothq/cryptocurrency-icons/master/svg/color/doge.svg',
  'SHIB': 'https://raw.githubusercontent.com/spothq/cryptocurrency-icons/master/svg/color/shib.svg',
  'UNI': 'https://raw.githubusercontent.com/spothq/cryptocurrency-icons/master/svg/color/uni.svg',
  'LTC': 'https://raw.githubusercontent.com/spothq/cryptocurrency-icons/master/svg/color/ltc.svg',
  'BCH': 'https://raw.githubusercontent.com/spothq/cryptocurrency-icons/master/svg/color/bch.svg',
  'TRX': 'https://raw.githubusercontent.com/spothq/cryptocurrency-icons/master/svg/color/trx.svg'
};

async function renderTrade(){
  restoreHeader(); // Restore original header
  setActive('trade');
  const cont=document.getElementById('root');
  cont.innerHTML = `
  <div class="container">
    <div class="section">
      <div class="section-header"><div class="section-title">📊 Торговые пары</div></div>
      <div class="section-content" id="pairList" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px"></div>
    </div>
  </div>`;
  const pairs=["BTC/USDT","ETH/USDT","SOL/USDT","ADA/USDT","DOT/USDT","LINK/USDT","MATIC/USDT","AVAX/USDT","XRP/USDT","DOGE/USDT","SHIB/USDT","UNI/USDT","LTC/USDT","BCH/USDT","TRX/USDT"];
  const wrap=document.getElementById('pairList');
  
  pairs.forEach(p => {
    const symbol = p.split('/')[0];
    const logo = cryptoLogos[symbol] || '';
    
    const card = document.createElement('div');
    card.className = 'crypto-pair-card';
    card.innerHTML = `
      <div style="display:flex;align-items:center;gap:12px">
        <img src="${logo}" alt="${symbol}" style="width:40px;height:40px;border-radius:50%;background:#fff;padding:4px" onerror="this.style.display='none'">
        <div>
          <div style="font-weight:600;font-size:15px;color:#fff">${symbol}</div>
          <div style="font-size:12px;color:#9ca3af">USDT</div>
        </div>
      </div>
      <div class="trade-action-btn" data-pair="${p}" data-i18n="btn.trade_action">${t('btn.trade_action')}</div>
    `;
    wrap.appendChild(card);
  });
  
  // Добавляем клик только на кнопки "Торговать"
  document.querySelectorAll('.trade-action-btn').forEach(btn => {
    btn.onclick = (e) => {
      e.stopPropagation();
      const pair = btn.getAttribute('data-pair');
      openPair(pair);
    };
  });
}

async function openPair(pair, displayName = null){
  setActive('trade');
  const cont=document.getElementById('root');
  const title = displayName || pair;
  const symbol = pair.split('/')[0];
  const logo = cryptoLogos[symbol] || '';
  
  // Модифицируем верхний header
  const headerBrand = document.querySelector('.header .brand');
  const headerActions = document.querySelector('.header .actions');
  
  headerBrand.innerHTML = `<button class="btn" id="backTrade" style="background:transparent;border:none;color:#fff;font-size:20px;padding:5px 10px">←</button>`;
  headerActions.innerHTML = `<span style="color:#fff;font-weight:600;font-size:15px;padding:6px 14px;border:1px solid #8b5cf6;border-radius:6px;background:rgba(139,92,246,0.1)">${title}</span>`;
  
  cont.innerHTML = `
  <div class="container" style="padding:0">
    <!-- Кнопки таймфреймов -->
    <div id="timeframeBar" style="display:flex;gap:4px;padding:8px 10px;background:#0e1219;border-bottom:1px solid #1f2937;overflow-x:auto;scrollbar-width:none;-ms-overflow-style:none">
      <button class="tf-btn" data-tf="1" style="padding:6px 12px;background:#1f2937;border:none;border-radius:4px;color:#9ca3af;font-size:12px;font-weight:600;cursor:pointer;white-space:nowrap;transition:all 0.2s">1м</button>
      <button class="tf-btn active" data-tf="5" style="padding:6px 12px;background:#8b5cf6;border:none;border-radius:4px;color:#fff;font-size:12px;font-weight:600;cursor:pointer;white-space:nowrap;transition:all 0.2s">5м</button>
      <button class="tf-btn" data-tf="15" style="padding:6px 12px;background:#1f2937;border:none;border-radius:4px;color:#9ca3af;font-size:12px;font-weight:600;cursor:pointer;white-space:nowrap;transition:all 0.2s">15м</button>
      <button class="tf-btn" data-tf="30" style="padding:6px 12px;background:#1f2937;border:none;border-radius:4px;color:#9ca3af;font-size:12px;font-weight:600;cursor:pointer;white-space:nowrap;transition:all 0.2s">30м</button>
      <button class="tf-btn" data-tf="60" style="padding:6px 12px;background:#1f2937;border:none;border-radius:4px;color:#9ca3af;font-size:12px;font-weight:600;cursor:pointer;white-space:nowrap;transition:all 0.2s">1ч</button>
      <button class="tf-btn" data-tf="240" style="padding:6px 12px;background:#1f2937;border:none;border-radius:4px;color:#9ca3af;font-size:12px;font-weight:600;cursor:pointer;white-space:nowrap;transition:all 0.2s">4ч</button>
      <button class="tf-btn" data-tf="1440" style="padding:6px 12px;background:#1f2937;border:none;border-radius:4px;color:#9ca3af;font-size:12px;font-weight:600;cursor:pointer;white-space:nowrap;transition:all 0.2s">1д</button>
    </div>
    
    <!-- TradingView Lightweight Chart (OKX Data) -->
    <div id="price_chart" style="height:calc(50vh - 45px);width:100%;background:#0e1219;position:relative"></div>
    
    <!-- Кнопки купить/продать -->
    <div style="padding:15px;display:flex;gap:10px">
      <button class="btn btn-green" id="btnBuy" style="flex:1;font-size:16px;font-weight:600;padding:14px;border-radius:8px;transition:all 0.2s;box-shadow:0 2px 8px rgba(16,185,129,0.3)">${t('trade.buy')}</button>
      <button class="btn btn-red" id="btnSell" style="flex:1;font-size:16px;font-weight:600;padding:14px;border-radius:8px;transition:all 0.2s;box-shadow:0 2px 8px rgba(239,68,68,0.3)">${t('trade.sell')}</button>
    </div>
    
    <!-- Список сделок -->
    <div style="padding:0 15px 15px">
      <div style="font-weight:600;font-size:16px;color:#fff;margin-bottom:12px">${t('trade.list.title')}</div>
      <div style="display:flex;gap:15px;margin-bottom:10px;border-bottom:1px solid #1f1f1f">
        <div class="trade-tab active" data-filter="active" style="padding:8px 0;color:#10b981;font-weight:600;border-bottom:2px solid #10b981;cursor:pointer;font-size:14px">${t('trade.list.active')}</div>
        <div class="trade-tab" data-filter="closed" style="padding:8px 0;color:#9ca3af;font-weight:600;cursor:pointer;font-size:14px">${t('trade.list.closed')}</div>
        <div class="trade-tab" data-filter="all" style="padding:8px 0;color:#9ca3af;font-weight:600;cursor:pointer;font-size:14px">${t('trade.list.all')}</div>
      </div>
      <div id="tradesList" style="max-height:calc(100vh - 520px);overflow-y:auto;overflow-x:hidden"></div>
    </div>
  </div>
  
  <!-- Модальное окно для ввода суммы и длительности -->
  <div id="tradeModal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.85);z-index:9999;animation:fadeIn 0.3s">
    <div id="modalContent" style="position:absolute;bottom:0;left:0;right:0;background:#1a1a1a;border-radius:16px 16px 0 0;padding:20px;animation:slideUp 0.3s;max-height:80vh;overflow-y:auto">
      <!-- Заголовок -->
      <div style="text-align:center;margin-bottom:20px">
        <div style="font-size:14px;color:#9ca3af;margin-bottom:5px" id="modalSubtitle">${t('trade.modal.buying')}</div>
        <div style="font-size:32px;font-weight:700;color:#fff" id="modalTitle">BTC</div>
      </div>
      
      <!-- Поле ввода суммы -->
      <div style="margin-bottom:20px">
        <input type="number" id="modalAmount" placeholder="0" min="5" step="1" 
          style="width:100%;padding:0;background:transparent;border:none;color:#8b5cf6;font-size:48px;font-weight:700;text-align:center;outline:none" 
          value="0"/>
        <div style="text-align:center;font-size:18px;color:#fff;margin-top:5px">${t('common.usdt')}</div>
      </div>
      
      <!-- Доступный баланс -->
      <div style="text-align:center;margin-bottom:25px">
        <span style="color:#9ca3af;font-size:14px">${t('trade.modal.available')}: </span>
        <span style="color:#fff;font-weight:600" id="modalBalance">0 ${t('common.usdt')}</span>
      </div>
      
      <!-- Длительность сделки -->
      <div style="margin-bottom:25px">
        <div style="color:#9ca3af;font-size:13px;margin-bottom:10px">${t('trade.modal.duration')}</div>
        <div id="modalDurationChips" style="display:flex;flex-wrap:wrap;gap:8px;justify-content:center">
          <div class="chip" data-dur="30" style="padding:12px 20px;font-size:15px">${t('trade.duration.30s')}</div>
          <div class="chip active" data-dur="60" style="padding:12px 20px;font-size:15px">${t('trade.duration.1m')}</div>
          <div class="chip" data-dur="300" style="padding:12px 20px;font-size:15px">${t('trade.duration.5m')}</div>
          <div class="chip" data-dur="900" style="padding:12px 20px;font-size:15px">${t('trade.duration.15m')}</div>
          <div class="chip" data-dur="1800" style="padding:12px 20px;font-size:15px">${t('trade.duration.30m')}</div>
          <div class="chip" data-dur="3600" style="padding:12px 20px;font-size:15px">${t('trade.duration.1h')}</div>
        </div>
      </div>
      
      <!-- Кнопка назад -->
      <button id="modalBack" style="width:100%;padding:16px;background:#2a2a2a;color:#fff;border:none;border-radius:8px;font-size:16px;font-weight:600;margin-bottom:10px;cursor:pointer">${t('btn.back')}</button>
      
      <!-- Кнопка подтверждения -->
      <button id="modalConfirm" style="width:100%;padding:16px;background:#10b981;color:#fff;border:none;border-radius:8px;font-size:16px;font-weight:600;cursor:pointer">${t('trade.buy')}</button>
    </div>
  </div>
  
  <style>
    @keyframes fadeIn {
      from { opacity: 0; }
      to { opacity: 1; }
    }
    @keyframes slideUp {
      from { transform: translateY(100%); }
      to { transform: translateY(0); }
    }
  </style>
  `;
  
  // Обработчик кнопки назад
  document.getElementById('backTrade').onclick = () => {
    renderTrade(); // Will restore header automatically
  };
  
  const sym=pair.replace('/','');
  
  // Timeframe mapping: minutes → string format
  const tfMap = {
    1: '1m',
    2: '2m',
    5: '5m',
    10: '10m',
    15: '15m',
    30: '30m',
    60: '1h',
    240: '4h',
    1440: '1d'
  };
  
  // Timeframe state (candle interval in minutes)
  let selectedTimeframe = 5; // Default: 5 minutes
  
  // Duration state (trade duration)
  let selectedDuration = 60;
  let selectedSide = 'buy';
  
  // Modal elements
  const tradeModal = document.getElementById('tradeModal');
  const modalTitle = document.getElementById('modalTitle');
  const modalSubtitle = document.getElementById('modalSubtitle');
  const modalAmount = document.getElementById('modalAmount');
  const modalBalance = document.getElementById('modalBalance');
  const modalConfirm = document.getElementById('modalConfirm');
  const modalBack = document.getElementById('modalBack');
  
  // Load user balance
  async function loadUserBalance() {
    try {
      const res = await apiFetch('/api/user');
      const user = await res.json();
      modalBalance.textContent = `${parseFloat(user.balance_usdt || 0).toFixed(2)} ${t('common.usdt')}`;
    } catch (e) {
      console.error('Failed to load balance:', e);
    }
  }
  
  // Open modal
  function openTradeModal(side) {
    selectedSide = side;
    const coinName = pair.split('/')[0];
    
    if (side === 'buy') {
      modalSubtitle.textContent = t('trade.modal.buying');
      modalTitle.textContent = coinName;
      modalConfirm.textContent = t('trade.buy');
      modalConfirm.style.background = '#10b981';
    } else {
      modalSubtitle.textContent = t('trade.modal.selling');
      modalTitle.textContent = coinName;
      modalConfirm.textContent = t('trade.sell');
      modalConfirm.style.background = '#ef4444';
    }
    
    modalAmount.value = '0';
    loadUserBalance();
    tradeModal.style.display = 'block';
    
    // Focus on amount input
    setTimeout(() => modalAmount.focus(), 300);
  }
  
  // Close modal
  function closeTradeModal() {
    tradeModal.style.display = 'none';
  }
  
  // Modal duration chips logic
  document.querySelectorAll('#modalDurationChips .chip').forEach(chip => {
    chip.onclick = () => {
      document.querySelectorAll('#modalDurationChips .chip').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      selectedDuration = parseInt(chip.getAttribute('data-dur'));
    };
  });
  
  // Modal buttons
  modalBack.onclick = closeTradeModal;
  modalConfirm.onclick = () => {
    const amount = parseFloat(modalAmount.value);
    if (!amount || amount < 5) {
      alert(t('trade.modal.min_amount'));
      return;
    }
    closeTradeModal();
    placeOrder(pair, selectedSide, selectedDuration, amount);
  };
  
  // Initialize TradingView Lightweight Charts with OKX data
  const chartContainer = document.getElementById('price_chart');
  
  // Create chart
  const chart = LightweightCharts.createChart(chartContainer, {
    width: chartContainer.clientWidth,
    height: chartContainer.clientHeight,
    layout: {
      background: { color: '#0e1219' },
      textColor: '#9ca3af',
    },
    grid: {
      vertLines: { color: '#1a1a1a' },
      horzLines: { color: '#1a1a1a' },
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
    },
    rightPriceScale: {
      borderColor: '#2a2a2a',
    },
    timeScale: {
      borderColor: '#2a2a2a',
      timeVisible: true,
      secondsVisible: false,
    },
  });

  // Create candlestick series
  const candleSeries = chart.addCandlestickSeries({
    upColor: '#10b981',
    downColor: '#ef4444',
    borderUpColor: '#10b981',
    borderDownColor: '#ef4444',
    wickUpColor: '#10b981',
    wickDownColor: '#ef4444',
  });

  // Store markers for active trades
  let activeTradeMarkers = [];
  let isFirstChartLoad = true;
  let userInteracting = false;

  // Track user interaction with chart
  chart.timeScale().subscribeVisibleLogicalRangeChange(() => {
    userInteracting = true;
    setTimeout(() => { userInteracting = false; }, 5000); // Reset after 5s of no interaction
  });

  // Load and update chart data
  async function loadChartData() {
    try {
      const tf = tfMap[selectedTimeframe];
      const res = await apiFetch(`/api/candles?symbol=${sym}&tf=${tf}&limit=100`);
      const candles = await res.json();
      
      if (!candles || candles.length === 0) {
        chartContainer.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#9ca3af">Нет данных</div>';
        return;
      }

      // Convert OKX candles to TradingView format
      const candleData = candles.map(c => ({
        time: Math.floor(new Date(c.t).getTime() / 1000), // Unix timestamp in seconds
        open: c.o,
        high: c.h,
        low: c.l,
        close: c.c,
      }));

      // Update candlestick series
      candleSeries.setData(candleData);

      // Load active trades for markers
      try {
        const tradesRes = await apiFetch('/api/trade/active');
        if (!tradesRes.ok) throw new Error('API error');
        const tradesData = await tradesRes.json();
        const activeTrades = Array.isArray(tradesData) ? tradesData : (tradesData.trades || []);
        
        // Create markers for active trades
        const markers = activeTrades
          .filter(t => t.pair.replace('-', '').replace('/', '') === pair.replace('-', '').replace('/', ''))
          .map(t => {
            const tradeTime = Math.floor(new Date(t.entry_time).getTime() / 1000);
            const side = t.side === 'buy' ? '⬆️' : '⬇️';
            const color = t.side === 'buy' ? '#10b981' : '#ef4444';
            
            return {
              time: tradeTime,
              position: t.side === 'buy' ? 'belowBar' : 'aboveBar',
              color: color,
              shape: t.side === 'buy' ? 'arrowUp' : 'arrowDown',
              text: `${side} ${t.amount_usdt} USDT`,
            };
          });

        candleSeries.setMarkers(markers);
        activeTradeMarkers = markers;
      } catch (e) {
        console.error('Failed to load active trades:', e);
      }

      // Auto-fit content only on first load or when user is not interacting
      if (isFirstChartLoad) {
        chart.timeScale().fitContent();
        isFirstChartLoad = false;
      }

    } catch (e) {
      console.error('Chart load failed', e);
    }
  }

  // Handle window resize
  window.addEventListener('resize', () => {
    chart.applyOptions({
      width: chartContainer.clientWidth,
      height: chartContainer.clientHeight,
    });
  });

  // Initial load and refresh timer
  loadChartData();
  const chartRefreshTimer = setInterval(loadChartData, 3000);
  
  // Timeframe buttons handler
  document.querySelectorAll('.tf-btn').forEach(btn => {
    btn.onclick = () => {
      // Update selected timeframe
      selectedTimeframe = parseInt(btn.getAttribute('data-tf'));
      
      // Update button styles
      document.querySelectorAll('.tf-btn').forEach(b => {
        b.style.background = '#1f2937';
        b.style.color = '#9ca3af';
        b.classList.remove('active');
      });
      btn.style.background = '#8b5cf6';
      btn.style.color = '#fff';
      btn.classList.add('active');
      
      // Reset chart state and reload with new timeframe
      isFirstChartLoad = true;
      loadChartData();
    };
  });
  
  // Buy/Sell buttons open modal
  const btnBuy = document.getElementById('btnBuy');
  const btnSell = document.getElementById('btnSell');
  
  btnBuy.onclick = () => openTradeModal('buy');
  btnSell.onclick = () => openTradeModal('sell');
  
  // Tabs logic
  let currentFilter = 'active';
  document.querySelectorAll('.trade-tab').forEach(tab => {
    tab.onclick = () => {
      document.querySelectorAll('.trade-tab').forEach(t => {
        t.classList.remove('active');
        t.style.color = '#9ca3af';
        t.style.borderBottom = 'none';
      });
      tab.classList.add('active');
      tab.style.color = '#10b981';
      tab.style.borderBottom = '2px solid #10b981';
      currentFilter = tab.getAttribute('data-filter');
      loadTradesList(currentFilter, pair);
    };
  });
  
  // Store previous trades to prevent flickering
  let previousTradesData = null;
  
  // Load trades list
  async function loadTradesList(filter = 'active', currentPair = null) {
    try {
      let trades = [];
      
      if (filter === 'active') {
        const res = await apiFetch('/api/trade/active');
        if (!res.ok) throw new Error('API error');
        const data = await res.json();
        trades = Array.isArray(data) ? data : (data.trades || []);
      } else {
        // Load all trades from stats
        const res = await apiFetch('/api/stats');
        if (!res.ok) throw new Error('API error');
        const stats = await res.json();
        trades = Array.isArray(stats.trades) ? stats.trades : [];
      }
      
      // Filter by current pair if specified
      const filtered = currentPair 
        ? trades.filter(t => t.pair === currentPair)
        : trades;
      
      const listDiv = document.getElementById('tradesList');
      
      // Check if data changed to prevent flickering
      const currentDataHash = JSON.stringify(filtered.map(t => ({ id: t.id, status: t.status, result: t.result })));
      if (currentDataHash === previousTradesData && listDiv.innerHTML !== '') {
        return; // No changes, skip update
      }
      previousTradesData = currentDataHash;
      
      if (!filtered || filtered.length === 0) {
        listDiv.innerHTML = `<div style="text-align:center;color:#9ca3af;padding:20px;font-size:13px">${t('trade.list.empty')}</div>`;
        return;
      }
      
      listDiv.innerHTML = filtered.map(trade => {
        const isBuy = trade.side === 'buy';
        const sideText = isBuy ? t('trade.side.buy') : t('trade.side.sell');
        const sideColor = isBuy ? '#10b981' : '#ef4444';
        
        // Calculate result
        let resultText = '';
        let resultColor = '#9ca3af';
        if (trade.status === 'active') {
          resultText = 'Активна';
        } else if (trade.result === 'win') {
          resultText = `+${(trade.payout || 0).toFixed(1)} USDT`;
          resultColor = '#10b981';
        } else {
          resultText = `-${(trade.amount_usdt || 0).toFixed(1)} USDT`;
          resultColor = '#ef4444';
        }
        
        const tradeDate = new Date(trade.opened_at);
        const timeStr = tradeDate.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) + 
                       ' ' + tradeDate.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' });
        
        return `
          <div style="display:flex;justify-content:space-between;align-items:center;padding:12px;background:#0e0e0e;border-radius:8px;margin-bottom:8px">
            <div>
              <div style="font-weight:700;font-size:15px;color:#fff">${trade.amount_usdt} USDT</div>
              <div style="font-size:13px;color:${sideColor};margin-top:2px">${sideText}</div>
            </div>
            <div style="text-align:right">
              <div style="font-weight:700;font-size:15px;color:${resultColor}">${resultText}</div>
              <div style="font-size:11px;color:#6b7280;margin-top:2px">${timeStr}</div>
            </div>
          </div>
        `;
      }).join('');
      
    } catch (e) {
      console.error('Failed to load trades:', e);
      document.getElementById('tradesList').innerHTML = '<div style="text-align:center;color:#ef4444;padding:20px">Ошибка загрузки</div>';
    }
  }
  
  // Initial load
  loadTradesList('active', pair);
  
  // Auto-refresh trades list every 5 seconds
  setInterval(() => loadTradesList(currentFilter, pair), 5000);
}
async function placeOrder(pair, side, duration, amount){
  const amt = amount || 0;
  const dur = duration || 60;
  if(amt<5){ toast('Мин. ставка 5 USDT'); return; }
  try{
    const res=await apiFetch('/api/trade/order',{ method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ pair, side, amount_usdt: amt, duration_sec: dur }) });
    const data=await res.json();
    if(!data.ok){ toast(data.error||t('toast.error')); return; }
    const direction = side === 'buy' ? '⬆️ ВВЕРХ' : '⬇️ ВНИЗ';
    toast(`Сделка открыта: ${direction} на ${dur/60} мин. Результат обновится автоматически.`);
    const id=data.order_id;
    const intv=setInterval(async ()=>{
      try{
        const st=await (await apiFetch('/api/trade/order/'+id)).json();
        if(st.status!=='active'){ clearInterval(intv); toast(st.result==='win'?'Профит +'+(st.payout||0)+' USDT':'Убыток -'+(st.amount_usdt||0)+' USDT'); renderAssets(); }
      }catch(e){}
    },5000);
  }catch(e){ toast(t('toast.error')); }
}

// -------- Stats ----------
async function renderStats(){
  restoreHeader(); // Restore original header
  setActive('stats');
  const cont=document.getElementById('root');
  let st = { earned:0,lost:0,balance:0,equity:[{t:0,v:.5}],trades:[] };
  try{ st = await (await apiFetch('/api/stats')).json(); }catch(e){ console.error('stats failed', e); }
  cont.innerHTML = `
  <div class="container">
    <div class="inline">
      <div class="balance-card"><div class="small">${t('stats.earned')}</div><div class="balance-amount">${Number(st.earned||0).toFixed(2)} <span class="currency">USDT</span></div></div>
      <div class="balance-card"><div class="small">${t('stats.lost')}</div><div class="balance-amount">${Number(st.lost||0).toFixed(2)} <span class="currency">USDT</span></div></div>
      <div class="balance-card"><div class="small">${t('stats.balance')}</div><div class="balance-amount">${Number(st.balance||0).toFixed(2)} <span class="currency">USDT</span></div></div>
    </div>
    <div class="section" style="margin-top:12px">
      <div class="section-header"><div class="section-title">График доходности</div></div>
      <div class="section-content"><canvas id="eqChart" height="300"></canvas></div>
    </div>
    <div class="section" style="margin-top:12px">
      <div class="section-header"><div class="section-title">Таблица сделок</div></div>
      <div class="section-content">
        <table class="table"><thead><tr><th>Пара</th><th>Направление</th><th>Сумма</th><th>Результат</th><th>Дата</th></tr></thead><tbody id="tradesBody"></tbody></table>
      </div>
    </div>
  </div>`;
  const canvas=document.getElementById('eqChart');
  const ctx=canvas.getContext('2d'); ctx.clearRect(0,0,canvas.width,canvas.height); ctx.beginPath();
  const data=st.equity||[{t:0,v:.5}];
  data.forEach((p,i)=>{ const x=i*(canvas.width/Math.max(1,(data.length-1)||1)); const y=canvas.height-(p.v*canvas.height); if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y); });
  ctx.lineWidth=2; ctx.strokeStyle='#8b5cf6'; ctx.stroke();
  const tb=document.getElementById('tradesBody');
  (st.trades||[]).forEach(tr=>{ const el=document.createElement('tr'); el.innerHTML=`<td>${tr.pair}</td><td>${tr.side}</td><td>${tr.amount_usdt}</td><td>${tr.result}</td><td>${new Date(tr.opened_at).toLocaleString()}</td>`; tb.appendChild(el); });
}
// -------- Support ----------
async function openSupport(){
  const cont=document.getElementById('root');
  cont.innerHTML = `
  <div class="chat-fullscreen">
    <div class="chat-header">
      <button class="btn-back" id="backAssets">←</button>
      <div class="chat-title">${t('support.title')}</div>
    </div>
    <div class="chat-messages" id="chat"></div>
    <div class="chat-input-container">
      <label for="file" class="btn-attach">+</label>
      <input type="file" id="file" accept="image/*" style="display:none"/>
      <input type="text" id="msg" class="chat-input" placeholder="Введите сообщение..."/>
      <button class="btn-send" id="send">→</button>
    </div>
  </div>`;
  document.getElementById('backAssets').onclick = renderAssets;
  
  async function deleteMessage(messageId) {
    if (!window.confirm('Вы уверены, что хотите удалить это сообщение?')) {
      return;
    }
    try {
      const res = await apiFetch(`/api/support/${messageId}`, { method: 'DELETE' });
      if (res.ok) {
        toast('Сообщение удалено');
        await load();
      } else {
        toast('Ошибка удаления');
      }
    } catch(e) {
      console.error('Delete failed', e);
      toast('Ошибка удаления');
    }
  }
  
  async function load(){ 
    try{ 
      // Load regular support messages
      const data=await (await apiFetch('/api/support')).json(); 
      const isAdmin = data.is_admin || false;
      const msgs = data.messages || [];
      
      // Load admin broadcast and personal messages
      const adminData = await (await apiFetch('/api/admin_messages')).json();
      const adminMsgs = adminData.messages || [];
      
      const chat=document.getElementById('chat'); 
      chat.innerHTML=''; 
      
      // Display admin messages first (if any)
      if (adminMsgs.length > 0) {
        const adminSection = document.createElement('div');
        adminSection.style.marginBottom = '20px';
        adminSection.innerHTML = '<div class="msg-label" style="text-align:center; margin: 10px 0; color: #8b5cf6; font-weight: bold;">📢 Сообщения от администратора</div>';
        chat.appendChild(adminSection);
        
        adminMsgs.forEach(m => {
          const d = document.createElement('div');
          d.className = 'msg admin';
          d.style.position = 'relative';
          const broadcastLabel = m.is_broadcast ? ' (Всем пользователям)' : '';
          d.innerHTML = `<div class="msg-label">Администратор${broadcastLabel}</div><div class="msg-text">${m.message_text}</div><div class="msg-time" style="font-size: 10px; color: #999; margin-top: 4px;">${new Date(m.created_at).toLocaleString()}</div>`;
          chat.appendChild(d);
        });
        
        // Separator
        if (msgs.length > 0) {
          const separator = document.createElement('div');
          separator.style.margin = '20px 0';
          separator.style.borderTop = '1px solid #444';
          separator.innerHTML = '<div class="msg-label" style="text-align:center; margin: 10px 0; color: #8b5cf6; font-weight: bold;">💬 Чат с поддержкой</div>';
          chat.appendChild(separator);
        }
      }
      
      // Display regular support chat messages
      msgs.forEach(m=>{ 
        const d=document.createElement('div'); 
        d.className='msg '+(m.sender==='user'?'user':'admin');
        d.style.position = 'relative';
        const label = m.sender==='user' ? 'Вы' : 'Поддержка';
        const content = m.text || (m.file_path?'[Фото]':'');
        
        const showDeleteBtn = isAdmin || m.sender === 'user';
        const deleteBtn = showDeleteBtn ? `<button class="msg-delete" data-id="${m.id}">×</button>` : '';
        
        d.innerHTML = `<div class="msg-label">${label}</div><div class="msg-text">${content}</div>${deleteBtn}`;
        
        if (showDeleteBtn) {
          d.querySelector('.msg-delete').onclick = () => deleteMessage(m.id);
        }
        
        chat.appendChild(d); 
      }); 
      chat.scrollTop=chat.scrollHeight; 
    }catch(e){ console.error('Load chat failed', e); } 
  }
  await load();
  // Auto-refresh chat every 5 seconds to see admin replies
  const refreshInterval = setInterval(load, 5000);
  
  const sendMsg = async ()=>{
    const fd=new FormData(); fd.append('text', document.getElementById('msg').value);
    const f=document.getElementById('file').files[0]; if(f) fd.append('file', f);
    const r=await apiFetch('/api/support',{method:'POST', body:fd}); const d=await r.json();
    if(d.ok){ document.getElementById('msg').value=''; document.getElementById('file').value=''; await load(); }
  };
  document.getElementById('send').onclick = sendMsg;
  document.getElementById('msg').addEventListener('keypress', (e)=>{ if(e.key==='Enter') sendMsg(); });
  
  // Cleanup on navigation
  document.getElementById('backAssets').addEventListener('click', () => clearInterval(refreshInterval));
} 
// -------- expose & bootstrap ----------
window.renderAssets=renderAssets;
window.renderTrade=renderTrade;
window.renderStats=renderStats;
window.openDeposit=openDeposit;
window.openWithdraw=openWithdraw;
window.openExchange=openExchange;
window.openSupport=openSupport;
window.openWallet=openWallet;

// Function to create check (admin only)
async function createCheck() {
  const amount = prompt("Введите сумму USDT для чека:", "100");
  if (!amount) return;
  
  const hours = prompt("Срок действия (часы):", "24");
  if (!hours) return;
  
  const r = await apiFetch(`/api/admin/check/create`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      amount_usdt: parseFloat(amount),
      expires_in_hours: parseInt(hours)
    })
  });
  
  const d = await r.json();
  if (d.ok) {
    const checkLink = d.check_link;
    navigator.clipboard.writeText(checkLink);
    toast(`✅ Чек создан!\n💰 ${d.amount_usdt} USDT\n🔗 Ссылка скопирована`);
    await renderAssets(); // Refresh balance
  } else {
    toast(d.error || 'Ошибка создания чека');
  }
}

// Function to activate check
async function activateCheck(checkCode) {
  const r = await apiFetch(`/api/check/activate`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ check_code: checkCode })
  });
  
  const d = await r.json();
  if (d.ok) {
    toast(`✅ Чек активирован!\n💰 +${d.amount_usdt} USDT\n📊 Баланс: ${d.new_balance} USDT`);
    await renderAssets(); // Refresh balance
  } else {
    toast(d.error || 'Ошибка активации чека');
  }
}

// APP VERSION
const APP_VERSION = 'v2.1.0-lang-fix';
console.log(`%c🚀 NadexRes ${APP_VERSION}`, 'color: #8b5cf6; font-size: 16px; font-weight: bold;');

window.addEventListener('DOMContentLoaded', async ()=>{
  // FORCE CLEAR old language settings (one-time migration)
  const migrationVersion = localStorage.getItem('lang_migration_v2');
  if (!migrationVersion) {
    console.log('[Migration] Clearing old language settings...');
    localStorage.removeItem('lang');
    localStorage.removeItem('lang_manual');
    localStorage.setItem('lang_migration_v2', 'done');
    console.log('[Migration] Old settings cleared ✅');
  }
  
  await loadTranslations();
  await ensureUser();
  await renderAssets(); // Wait for initial data to load
  
  // Show version in UI
  setTimeout(() => {
    const versionDiv = document.createElement('div');
    versionDiv.style.cssText = 'position:fixed;bottom:60px;right:10px;background:#8b5cf6;color:#fff;padding:4px 8px;border-radius:4px;font-size:10px;z-index:99999;';
    versionDiv.textContent = APP_VERSION;
    document.body.appendChild(versionDiv);
    setTimeout(() => versionDiv.remove(), 5000);
  }, 1000);
  
  // Check if there's a check code in URL
  const urlParams = new URLSearchParams(window.location.search);
  const checkCode = urlParams.get('check');
  if (checkCode) {
    // Show activation dialog
    setTimeout(async () => {
      const confirm = window.confirm(`У вас есть чек!\n\nАктивировать чек?\nКод: ${checkCode}`);
      if (confirm) {
        await activateCheck(checkCode);
        // Remove check from URL
        window.history.replaceState({}, document.title, window.location.pathname);
      }
    }, 1000);
  }
  
  // Hide splash screen after everything is loaded (minimum 1.2s for UX)
  setTimeout(() => {
    hideSplashScreen();
  }, 800); // Shorter delay since we already waited for renderAssets()
  
  const a=document.querySelector('.nav-item[data-tab="assets"]');
  const tradeTab=document.querySelector('.nav-item[data-tab="trade"]');
  const s=document.querySelector('.nav-item[data-tab="stats"]');
  if(a) a.onclick = renderAssets;
  if(tradeTab) tradeTab.onclick = renderTrade;
  if(s) s.onclick = renderStats;
  const btnLang=document.getElementById('btnLang');
  if(btnLang){ btnLang.onclick = ()=>{ setLang(i18n.lang==='ru'?'en':'ru', true); toast(t('toast.saved')); }; }
});

window.createCheck = createCheck;