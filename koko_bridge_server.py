Upgrade from v3.0:
  [MEM-1] agent_memory maxlen: 20 → 100 states (เก็บประวัติยาวขึ้น)
  [MEM-2] action_history maxlen: 10 → 50 actions
  [MEM-3] pattern_memory: NEW — จำ pattern ที่เคย win/lose ไว้เปรียบเทียบ
  [MEM-4] session_stats: NEW — สถิติ per-session (win/loss streak, avg hold time)
  [MEM-5] market_regime: NEW — จดจำ regime (Trending/Ranging/Volatile)

  [PROMPT-1] System prompt ใหม่: LLM-aware context (รู้ว่าตัวเองเป็น LLM)
  [PROMPT-2] Pattern Recognition section: เปรียบ current vs past winning patterns
  [PROMPT-3] Market Regime Analysis: Trending/Ranging/Volatile context
  [PROMPT-4] Multi-timeframe context: M5 + M15 combined signal
  [PROMPT-5] Risk-Adjusted Confidence: คิด confidence จาก win rate + aggression
  [PROMPT-6] Thai language output option
  [PROMPT-7] Sentiment scoring: momentum + structure alignment

  [API-1] /stats endpoint: ดู session stats
  [API-2] /pattern endpoint: ดู pattern memory
  [API-3] /regime endpoint: ดู market regime history
"""

from flask import Flask, request, jsonify
import google.generativeai as genai
import os
import json
import time
from datetime import datetime
from collections import deque

app = Flask(__name__)

# === CONFIGURATION ===
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

TARGET_PROFIT   = 0.70
MAX_DRAWDOWN    = -25.0
SNOWBALL_TARGET = 0.70
SPREAD_MAX      = 80

# =================================================================
# MEMORY SYSTEM v4.0 (Extended)
# =================================================================

# [MEM-1] ขยาย Market State Memory: 20 → 100
agent_memory    = deque(maxlen=100)

# [MEM-2] ขยาย Action History: 10 → 50
action_history  = deque(maxlen=50)

# [MEM-3] Pattern Memory: จำ winning/losing patterns
pattern_memory = {
    "winning_patterns": deque(maxlen=20),   # patterns ที่นำไป CLOSE_ALL
    "losing_patterns":  deque(maxlen=20),   # patterns ที่นำไป FAILSAFE/HEDGE
    "neutral_patterns": deque(maxlen=10)    # patterns ที่ WAIT แล้วดีขึ้น
}

# [MEM-4] Session Stats
session_stats = {
    "session_start":    datetime.now().isoformat(),
    "total_bars_seen":  0,
    "win_streak":       0,
    "loss_streak":      0,
    "max_win_streak":   0,
    "max_loss_streak":  0,
    "avg_net_pl":       0.0,
    "pl_history":       deque(maxlen=50),   # ประวัติ net_pl
    "spread_history":   deque(maxlen=30),   # ประวัติ spread
    "bos_history":      deque(maxlen=30),   # ประวัติ BOS direction
}

# [MEM-5] Market Regime Memory
regime_memory = deque(maxlen=30)
current_regime = "UNKNOWN"  # TRENDING_UP / TRENDING_DOWN / RANGING / VOLATILE

# === AGENT PERFORMANCE ===
perf = {
    "cycles_won":        0,
    "cycles_lost":       0,
    "total_decisions":   0,
    "last_action":       "WAIT",
    "aggression_factor": 1.0,
    "consecutive_waits": 0,
    "win_streak":        0,
    "loss_streak":       0,
}

# =================================================================
# MARKET REGIME DETECTION
# =================================================================

def detect_market_regime(adx: float, bos: int, liq_score: float) -> str:
    """Detect current market regime from indicators"""
    global current_regime

    if adx < 15:
        regime = "RANGING"
    elif adx >= 25:
        if bos == 1:
            regime = "TRENDING_UP"
        elif bos == -1:
            regime = "TRENDING_DOWN"
        else:
            regime = "VOLATILE"
    else:
        if abs(liq_score) > 5:
            regime = "VOLATILE"
        else:
            regime = "RANGING"

    current_regime = regime
    regime_memory.append({
        "time":   datetime.now().isoformat(),
        "regime": regime,
        "adx":    adx,
        "bos":    bos
    })
    return regime

# =================================================================
# PATTERN MATCHING
# =================================================================

def extract_pattern(market_data: dict) -> dict:
    """Extract key pattern fingerprint from market data"""
    return {
        "bos":          market_data.get("bos", 0),
        "ma_cross":     market_data.get("ma_cross", 0),
        "liq_dir":      market_data.get("liq_direction", 0),
        "adx_zone":     "HIGH" if market_data.get("adx", 0) >= 25 else "LOW",
        "positions":    market_data.get("positions", 0),
        "net_pl_zone":  "POS" if market_data.get("net_pl", 0) >= 0 else "NEG",
        "regime":       current_regime
    }

def find_similar_patterns(current_pattern: dict) -> dict:
    """Compare current pattern with historical winning/losing patterns"""
    def similarity(p1, p2):
        score = 0
        keys = ["bos", "ma_cross", "liq_dir", "adx_zone", "regime"]
        for k in keys:
            if p1.get(k) == p2.get(k):
                score += 1
        return score / len(keys)

    best_win  = {"similarity": 0, "pattern": None}
    best_lose = {"similarity": 0, "pattern": None}

    for wp in pattern_memory["winning_patterns"]:
        s = similarity(current_pattern, wp)
        if s > best_win["similarity"]:
            best_win = {"similarity": s, "pattern": wp}

    for lp in pattern_memory["losing_patterns"]:
        s = similarity(current_pattern, lp)
        if s > best_lose["similarity"]:
            best_lose = {"similarity": s, "pattern": lp}

    return {
        "win_similarity":  round(best_win["similarity"], 2),
        "lose_similarity": round(best_lose["similarity"], 2),
        "bias": "WIN" if best_win["similarity"] > best_lose["similarity"] else
                "LOSE" if best_lose["similarity"] > best_win["similarity"] else "NEUTRAL"
    }

# =================================================================
# SESSION STATS UPDATE
# =================================================================

def update_session_stats(market_data: dict):
    """Update rolling session statistics"""
    session_stats["total_bars_seen"] += 1
    net_pl  = market_data.get("net_pl", 0)
    spread  = market_data.get("spread", 0)
    bos     = market_data.get("bos", 0)

    session_stats["pl_history"].append(net_pl)
    session_stats["spread_history"].append(spread)
    session_stats["bos_history"].append(bos)

    if session_stats["pl_history"]:
        session_stats["avg_net_pl"] = round(
            sum(session_stats["pl_history"]) / len(session_stats["pl_history"]), 3
        )

# =================================================================
# QUANTUM STATE COMPUTATION v4.0
# =================================================================

def compute_quantum_state(bos: int, liq_score: float, signal: int,
                           adx: float = 0, ma_cross: int = 0) -> dict:
    """
    Compute probability-weighted state vector (Quantum-inspired) v4.0
    เพิ่ม ADX weight + MA Cross weight
    """
    raw = 0.0

    # BOS contribution (25%)
    raw += bos * 0.25

    # LIQ Score (20%)
    liq_norm = max(-1.0, min(1.0, liq_score / 10.0)) if liq_score else 0
    raw += liq_norm * 0.20

    # Signal direction (20%)
    raw += signal * 0.20

    # [NEW v4] MA Cross (20%) — S3>S2>S1 alignment
    raw += ma_cross * 0.20

    # [NEW v4] ADX momentum boost (15%)
    adx_boost = min(1.0, (adx - 25) / 25.0) if adx >= 25 else 0
    raw += adx_boost * 0.15 * (1 if bos >= 0 else -1)

    bull    = max(0.0, raw)
    bear    = max(0.0, -raw)
    neutral = max(0.0, 1.0 - bull - bear)

    total = bull + bear + neutral
    if total > 0:
        bull    /= total
        bear    /= total
        neutral /= total
    else:
        neutral = 1.0

    if bull >= 0.65:
        state = "COLLAPSE_BUY"
    elif bear >= 0.65:
        state = "COLLAPSE_SELL"
    elif neutral >= 0.60:
        state = "NEUTRAL"
    elif 0.45 <= bull <= 0.55:
        state = "INTERFERE"
    else:
        state = "SUPERPOS"

    return {
        "bull":    round(bull, 3),
        "bear":    round(bear, 3),
        "neutral": round(neutral, 3),
        "state":   state
    }

# =================================================================
# 3-STEP LOOKAHEAD PLANNING
# =================================================================

def agent_plan(market_data: dict) -> str:
    """3-step lookahead planner"""
    net_pl    = market_data.get("net_pl", 0)
    positions = market_data.get("positions", 0)
    worst_pl  = market_data.get("worst_loss", 0)
    quantum   = market_data.get("quantum_state", {})
    spread    = market_data.get("spread", 0)

    if net_pl >= TARGET_PROFIT and positions > 0:
        return "CLOSE_ALL"
    if net_pl <= MAX_DRAWDOWN * 0.80:
        return "FAILSAFE"
    if worst_pl <= -1.50 and positions > 0:
        return "HEDGE"
    if worst_pl <= -0.70 and positions > 0:
        return "AVERAGE_DOWN"

    q_state = quantum.get("state", "NEUTRAL")
    if positions == 0 and q_state in ["COLLAPSE_BUY", "COLLAPSE_SELL"]:
        if spread <= SPREAD_MAX:
            return "NEWPOS"

    return "WAIT"

# =================================================================
# AGENT REFLECTION
# =================================================================

def agent_reflect(action: str, market_data: dict, result_pl: float):
    """After action, reflect and update performance + pattern memory"""
    perf["total_decisions"] += 1
    perf["last_action"]      = action

    current_pattern = extract_pattern(market_data)

    if action in ["CLOSE_ALL", "TARGET_HIT"] and result_pl >= TARGET_PROFIT:
        perf["cycles_won"]  += 1
        perf["win_streak"]  += 1
        perf["loss_streak"]  = 0
        if perf["win_streak"] > session_stats["max_win_streak"]:
            session_stats["max_win_streak"] = perf["win_streak"]
        pattern_memory["winning_patterns"].append(current_pattern)

    elif action in ["FAILSAFE"] and result_pl < 0:
        perf["cycles_lost"] += 1
        perf["loss_streak"] += 1
        perf["win_streak"]   = 0
        if perf["loss_streak"] > session_stats["max_loss_streak"]:
            session_stats["max_loss_streak"] = perf["loss_streak"]
        pattern_memory["losing_patterns"].append(current_pattern)

    total = perf["cycles_won"] + perf["cycles_lost"]
    if total >= 3:
        win_rate = perf["cycles_won"] / total
        if win_rate < 0.40:
            perf["aggression_factor"] = 0.70
        elif win_rate > 0.70:
            perf["aggression_factor"] = 1.20
        else:
            perf["aggression_factor"] = 1.00

    if action == "WAIT":
        perf["consecutive_waits"] += 1
    else:
        perf["consecutive_waits"] = 0

# =================================================================
# KOKO SYSTEM PROMPT v4.0 (LLM-Aware + Pattern-Aware)
# =================================================================

KOKO_SYSTEM_PROMPT_V4 = """คุณคือ KOKO — ระบบ AI เทรดทองคำอัตโนมัติ XAU/USD บน MetaTrader 5

## IDENTITY
คุณทำงานเป็น LLM (Large Language Model) ที่ถูก embed เข้าไปในระบบเทรด
เหมือนรูปภาพ LLM: เส้น 3 สี (MA Yellow/Green/Red) พุ่งขึ้น ตัดกัน แล้วแผ่ออกเป็น dome
จุดตัดของเส้น = สัญญาณ ความน่าจะเป็น = Quantum State ที่คุณคำนวณ

## MISSION
Snowball $0.70/cycle | Max Drawdown -$25 | ปกป้อง capital เหนือสิ่งอื่นใด

## SIGNAL DICTIONARY
- BOS: +1=Bull Break, -1=Bear Break, 0=No Break
- MA Cross (HackMode S3>S2>S1): +1=Buy alignment, -1=Sell alignment, 0=Mixed
- LIQ Score: -10 to +10 (+ = bullish pressure, - = bearish pressure)
- LIQ Direction: +1=BUY zone, -1=SELL zone, 0=Neutral
- ADX: <15=Flat, 15-25=Transition, >25=Trending
- Spread: ต้องไม่เกิน 80 pts ถึงจะ entry ได้
- Speed: ความเร็วราคา (pts/bar) — High=volatile, Low=calm

## QUANTUM STATE INTERPRETATION
- COLLAPSE_BUY  (Bull>65%): สัญญาณ BUY ชัดเจนมาก — entry ได้ถ้า spread ผ่าน
- COLLAPSE_SELL (Bear>65%): สัญญาณ SELL ชัดเจนมาก — entry ได้ถ้า spread ผ่าน
- NEUTRAL       (Neutral>60%): ตลาดไม่มีทิศ — รอ
- INTERFERE     (Bull≈Bear): สัญญาณขัดกัน — ห้าม entry ใหม่
- SUPERPOS      : ไม่แน่นอน — รอ clarity

## MARKET REGIME CONTEXT
- TRENDING_UP:    BOS+1, ADX>25 — ให้น้ำหนัก BUY signals มากขึ้น
- TRENDING_DOWN:  BOS-1, ADX>25 — ให้น้ำหนัก SELL signals มากขึ้น
- RANGING:        ADX<15 — ระวัง false break ลด lot
- VOLATILE:       ADX 15-25 + LIQ ขัดแย้ง — รอ clarity

## PATTERN RECOGNITION
คุณได้รับ Pattern Similarity Score:
- win_similarity: ความคล้ายกับ pattern ที่เคย WIN ก่อนหน้า (0.0–1.0)
- lose_similarity: ความคล้ายกับ pattern ที่เคย LOSE ก่อนหน้า (0.0–1.0)
- bias: WIN/LOSE/NEUTRAL — ใช้เป็น additional filter

ถ้า lose_similarity > 0.8 → เพิ่มความระมัดระวัง แม้ quantum จะบอก COLLAPSE

## DECISION PRIORITY (ห้ามข้าม)
1. CLOSE_ALL    — net_pl >= $0.70 (Target Hit)
2. FAILSAFE     — net_pl <= -$17.50 (70% of max DD)
3. HEDGE        — worst single loss <= -$1.50 + ไม่มี profit pos
4. AVERAGE_DOWN — worst loss <= -$0.70 + เพิ่มไม้ทิศทางเดิม
5. BUY/SELL     — ไม่มี position + COLLAPSE quantum + spread<=80 + regime ok
6. WAIT         — ทุกกรณีที่ไม่ผ่านเงื่อนไขข้างบน

## CONFIDENCE CALIBRATION
- Base confidence จาก quantum collapse %
- ลด confidence 20% ถ้า spread > 60
- ลด confidence 15% ถ้า lose_similarity > 0.6
- เพิ่ม confidence 10% ถ้า regime align กับ quantum
- เพิ่ม confidence 10% ถ้า win_streak >= 3

## OUTPUT FORMAT (JSON เท่านั้น ห้าม markdown)
{
  "action": "BUY|SELL|CLOSE_ALL|HEDGE|AVERAGE_DOWN|WAIT|FAILSAFE",
  "confidence": 0.0-1.0,
  "reason": "อธิบายเหตุผลสั้นๆ ภาษาไทย",
  "risk_level": "LOW|MEDIUM|HIGH",
  "quantum_assessment": "สรุป quantum state",
  "pattern_note": "สังเกตจาก pattern history",
  "regime_note": "market regime ปัจจุบัน"
}
"""

# =================================================================
# AGENTIC DECISION ENGINE v4.0
# =================================================================

def agentic_decide(market_data: dict) -> dict:
    """Main agentic decision loop: OBSERVE → REASON → ACT v4.0"""

    update_session_stats(market_data)

    regime = detect_market_regime(
        adx=market_data.get("adx", 0),
        bos=market_data.get("bos", 0),
        liq_score=market_data.get("liq_score", 0)
    )

    memory_entry = {
        "time":      datetime.now().isoformat(),
        "bos":       market_data.get("bos", 0),
        "net_pl":    market_data.get("net_pl", 0),
        "positions": market_data.get("positions", 0),
        "liq_score": market_data.get("liq_score", 0),
        "spread":    market_data.get("spread", 0),
        "adx":       market_data.get("adx", 0),
        "ma_cross":  market_data.get("ma_cross", 0),
        "regime":    regime,
        "price":     market_data.get("price", 0)
    }
    agent_memory.append(memory_entry)

    quantum = compute_quantum_state(
        bos=market_data.get("bos", 0),
        liq_score=market_data.get("liq_score", 0),
        signal=market_data.get("signal_direction", 0),
        adx=market_data.get("adx", 0),
        ma_cross=market_data.get("ma_cross", 0)
    )
    market_data["quantum_state"] = quantum

    current_pattern = extract_pattern(market_data)
    pattern_match   = find_similar_patterns(current_pattern)

    planned_action = agent_plan(market_data)

    recent_memory = list(agent_memory)[-10:]

    pl_list   = list(session_stats["pl_history"])
    pl_trend  = "IMPROVING" if len(pl_list) >= 3 and pl_list[-1] > pl_list[-3] else \
                "DECLINING" if len(pl_list) >= 3 and pl_list[-1] < pl_list[-3] else "STABLE"

    spread_list = list(session_stats["spread_history"])
    avg_spread  = round(sum(spread_list)/len(spread_list), 1) if spread_list else 0

    total_cycles = perf["cycles_won"] + perf["cycles_lost"]
    win_rate     = round(perf["cycles_won"] / total_cycles * 100, 1) if total_cycles > 0 else 0

    prompt = f"""
CURRENT MARKET STATE [{datetime.now().strftime('%H:%M:%S')}]:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Price:          {market_data.get('price', 0):.2f}
BOS Direction:  {market_data.get('bos', 0)} ({'BULL' if market_data.get('bos',0)==1 else 'BEAR' if market_data.get('bos',0)==-1 else 'NONE'})
MA Cross:       {market_data.get('ma_cross', 0)} ({'S3>S2>S1 BUY' if market_data.get('ma_cross',0)==1 else 'S3>S2>S1 SELL' if market_data.get('ma_cross',0)==-1 else 'Mixed'})
LIQ Score:      {market_data.get('liq_score', 0):.1f}
LIQ Direction:  {market_data.get('liq_direction', 0)}
EMA8:           {market_data.get('ema', 0):.2f}
ADX:            {market_data.get('adx', 0):.1f}
Speed:          {market_data.get('speed', 0):.1f} pts/bar
Spread:         {market_data.get('spread', 0)} pts (avg={avg_spread})

MARKET REGIME: {regime}

BASKET STATUS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Open Positions: {market_data.get('positions', 0)}
Net P&L:       ${market_data.get('net_pl', 0):.2f} (trend={pl_trend})
Worst Loss:    ${market_data.get('worst_loss', 0):.2f}
Profit Pos:     {market_data.get('prof_count', 0)} (${market_data.get('prof_sum', 0):.2f})
Loss Pos:       {market_data.get('loss_count', 0)} (${market_data.get('loss_sum', 0):.2f})

QUANTUM STATE VECTOR:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Bull:    {quantum['bull']*100:.0f}%
Bear:    {quantum['bear']*100:.0f}%
Neutral: {quantum['neutral']*100:.0f}%
State:   {quantum['state']}

PATTERN RECOGNITION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Win Similarity:  {pattern_match['win_similarity']*100:.0f}%
Lose Similarity: {pattern_match['lose_similarity']*100:.0f}%
Pattern Bias:    {pattern_match['bias']}
Current Pattern: BOS={current_pattern['bos']} MA={current_pattern['ma_cross']} LIQ={current_pattern['liq_dir']} Regime={current_pattern['regime']}

AGENT PERFORMANCE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Cycles Won:    {perf['cycles_won']}  Lost: {perf['cycles_lost']}
Win Rate:      {win_rate}%
Win Streak:    {perf.get('win_streak',0)} (max={session_stats['max_win_streak']})
Loss Streak:   {perf.get('loss_streak',0)} (max={session_stats['max_loss_streak']})
Aggression:    {perf['aggression_factor']:.1f}x
Consec. WAIT:  {perf['consecutive_waits']}
Bars Seen:     {session_stats['total_bars_seen']}

RECENT HISTORY (last 10 bars):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{json.dumps(recent_memory, indent=2)}

PLANNER SUGGESTS: {planned_action}

คำถาม: จากข้อมูลทั้งหมดนี้ ตัดสินใจอะไร? ตอบ JSON เท่านั้น
"""

    try:
        response = model.generate_content(
            KOKO_SYSTEM_PROMPT_V4 + "\n\n" + prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.10,
                max_output_tokens=400
            )
        )

        raw_text = response.text.strip()
        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_text:
            raw_text = raw_text.split("```")[1].split("```")[0].strip()

        result = json.loads(raw_text)
        result["quantum_state"]      = quantum
        result["planned_action"]     = planned_action
        result["agent_memory_size"]  = len(agent_memory)
        result["pattern_match"]      = pattern_match
        result["market_regime"]      = regime
        result["session_bars"]       = session_stats["total_bars_seen"]
        result["win_rate"]           = win_rate

        action_history.append({
            "time":       datetime.now().isoformat(),
            "action":     result.get("action", "WAIT"),
            "confidence": result.get("confidence", 0),
            "net_pl":     market_data.get("net_pl", 0),
            "regime":     regime
        })

        return result

    except Exception as e:
        return {
            "action":            planned_action,
            "confidence":        0.55,
            "reason":            f"Gemini unavailable, planner: {str(e)[:50]}",
            "risk_level":        "MEDIUM",
            "quantum_state":     quantum,
            "planned_action":    planned_action,
            "pattern_match":     pattern_match,
            "market_regime":     regime,
            "agent_memory_size": len(agent_memory),
            "error":             str(e)
        }

# =================================================================
# FLASK ROUTES
# =================================================================

@app.route("/", methods=["GET"])
def health():
    total = perf["cycles_won"] + perf["cycles_lost"]
    return jsonify({
        "status":         "KOKO Bridge Agentic v4.0",
        "agent_memory":   len(agent_memory),
        "action_history": len(action_history),
        "cycles_won":     perf["cycles_won"],
        "cycles_lost":    perf["cycles_lost"],
        "win_rate":       round(perf["cycles_won"]/total*100, 1) if total > 0 else 0,
        "aggression":     perf["aggression_factor"],
        "regime":         current_regime,
        "bars_seen":      session_stats["total_bars_seen"],
        "timestamp":      datetime.now().isoformat()
    })

@app.route("/decide", methods=["POST"])
def decide():
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "No data received"}), 400
        required = ["price", "bos", "net_pl", "positions"]
        missing  = [f for f in required if f not in data]
        if missing:
            return jsonify({"error": f"Missing fields: {missing}"}), 400
        result = agentic_decide(data)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "action": "WAIT"}), 500

@app.route("/reflect", methods=["POST"])
def reflect():
    try:
        data      = request.get_json(force=True)
        action    = data.get("action", "WAIT")
        result_pl = data.get("result_pl", 0)
        agent_reflect(action, data, result_pl)
        return jsonify({"status": "reflected", "performance": perf, "timestamp": datetime.now().isoformat()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/memory", methods=["GET"])
def memory():
    return jsonify({"memory": list(agent_memory), "actions": list(action_history), "performance": perf})

@app.route("/stats", methods=["GET"])
def stats():
    total = perf["cycles_won"] + perf["cycles_lost"]
    return jsonify({
        "session_start":      session_stats["session_start"],
        "total_bars_seen":    session_stats["total_bars_seen"],
        "win_streak":         perf.get("win_streak", 0),
        "loss_streak":        perf.get("loss_streak", 0),
        "max_win_streak":     session_stats["max_win_streak"],
        "max_loss_streak":    session_stats["max_loss_streak"],
        "avg_net_pl":         session_stats["avg_net_pl"],
        "win_rate":           round(perf["cycles_won"]/total*100, 1) if total > 0 else 0,
        "aggression_factor":  perf["aggression_factor"],
        "consecutive_waits":  perf["consecutive_waits"],
        "current_regime":     current_regime
    })

@app.route("/pattern", methods=["GET"])
def pattern():
    return jsonify({
        "winning_patterns": list(pattern_memory["winning_patterns"]),
        "losing_patterns":  list(pattern_memory["losing_patterns"]),
        "neutral_patterns": list(pattern_memory["neutral_patterns"]),
        "win_count":        len(pattern_memory["winning_patterns"]),
        "lose_count":       len(pattern_memory["losing_patterns"])
    })

@app.route("/regime", methods=["GET"])
def regime():
    return jsonify({"current_regime": current_regime, "history": list(regime_memory)})

@app.route("/reset", methods=["POST"])
def reset():
    agent_memory.clear()
    action_history.clear()
    pattern_memory["winning_patterns"].clear()
    pattern_memory["losing_patterns"].clear()
    pattern_memory["neutral_patterns"].clear()
    regime_memory.clear()
    session_stats["total_bars_seen"]  = 0
    session_stats["win_streak"]       = 0
    session_stats["loss_streak"]      = 0
    session_stats["max_win_streak"]   = 0
    session_stats["max_loss_streak"]  = 0
    session_stats["avg_net_pl"]       = 0.0
    session_stats["pl_history"].clear()
    session_stats["spread_history"].clear()
    session_stats["bos_history"].clear()
    session_stats["session_start"]    = datetime.now().isoformat()
    perf["cycles_won"]        = 0
    perf["cycles_lost"]       = 0
    perf["total_decisions"]   = 0
    perf["aggression_factor"] = 1.0
    perf["consecutive_waits"] = 0
    perf["win_streak"]        = 0
    perf["loss_streak"]       = 0
    return jsonify({"status": "reset complete", "time": datetime.now().isoformat()})

@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data   = request.get_json(force=True)
        result = agentic_decide(data)
        return jsonify({
            "action":     result.get("action", "WAIT"),
            "confidence": result.get("confidence", 0.5),
            "reason":     result.get("reason", ""),
            "quantum":    result.get("quantum_state", {}),
            "planned":    result.get("planned_action", "WAIT")
        })
    except Exception as e:
        return jsonify({"action": "WAIT", "error": str(e)}), 500

# =================================================================
# MAIN
# =================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"KOKO Bridge Agentic v4.0 starting on port {port}")
    print(f"Memory: 100 states | Actions: 50 | Pattern: 20 win/lose")
    print(f"Endpoints: /decide | /reflect | /memory | /stats | /pattern | /regime | /reset")
    app.run(host="0.0.0.0", port=port)
