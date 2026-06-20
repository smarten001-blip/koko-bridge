Upgrade from v3.0:
  [NEW-G1] Gold Variables Logic: DXY, VIX, Session, Spread impact
  [NEW-G2] Session-based risk adjustment (Asian/London/NY)
  [NEW-G3] Spread danger level assessment
  [NEW-G4] ATR volatility tier (Low/Medium/High)
  [NEW-G5] ADX trend strength gate
  [FIX-1]  Clean code — no escape characters
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

TARGET_PROFIT = 0.70
MAX_DRAWDOWN = -25.0
SNOWBALL_TARGET = 0.70

# === AGENT MEMORY ===
agent_memory = deque(maxlen=20)
action_history = deque(maxlen=10)

# === AGENT PERFORMANCE ===
perf = {
    "cycles_won": 0,
    "cycles_lost": 0,
    "total_decisions": 0,
    "last_action": "WAIT",
    "aggression_factor": 1.0
}

# ============================================================
# GOLD VARIABLES ANALYSIS
# ============================================================

def analyze_gold_variables(data: dict) -> dict:
    """
    Analyze variables that directly impact Gold (XAU/USD)
    Returns risk_adjustment and context for Gemini
    """
    spread = data.get("spread", 0)
    adx = data.get("adx", 0)
    atr = data.get("atr", 0)
    session = data.get("session", "Asian")
    equity = data.get("equity", 0)
    float_pl = data.get("float_pl", 0)

    result = {}

    # --- SPREAD ANALYSIS ---
    if spread <= 30:
        result["spread_level"] = "TIGHT"
        result["spread_ok"] = True
    elif spread <= 58:
        result["spread_level"] = "NORMAL"
        result["spread_ok"] = True
    elif spread <= 80:
        result["spread_level"] = "WIDE"
        result["spread_ok"] = True
    else:
        result["spread_level"] = "DANGER"
        result["spread_ok"] = False

    # --- SESSION ANALYSIS ---
    if session == "Asian":
        result["session_volatility"] = "LOW"
        result["session_bias"] = "RANGE"
        result["session_risk"] = "LOW"
    elif session == "London":
        result["session_volatility"] = "HIGH"
        result["session_bias"] = "TREND"
        result["session_risk"] = "MEDIUM"
    elif session == "NY+London":
        result["session_volatility"] = "VERY_HIGH"
        result["session_bias"] = "BREAKOUT"
        result["session_risk"] = "HIGH"
    else:  # NewYork
        result["session_volatility"] = "HIGH"
        result["session_bias"] = "TREND"
        result["session_risk"] = "MEDIUM"

    # --- ATR VOLATILITY TIER ---
    if atr < 80:
        result["atr_tier"] = "LOW"
        result["volatility_ok"] = False
    elif atr < 150:
        result["atr_tier"] = "MEDIUM"
        result["volatility_ok"] = True
    else:
        result["atr_tier"] = "HIGH"
        result["volatility_ok"] = True

    # --- ADX TREND STRENGTH ---
    if adx < 20:
        result["adx_level"] = "FLAT"
        result["trend_ok"] = False
    elif adx < 25:
        result["adx_level"] = "WEAK"
        result["trend_ok"] = False
    elif adx < 35:
        result["adx_level"] = "MODERATE"
        result["trend_ok"] = True
    else:
        result["adx_level"] = "STRONG"
        result["trend_ok"] = True

    # --- EQUITY HEALTH ---
    if equity > 0:
        float_pct = (float_pl / equity) * 100
        if float_pct < -10:
            result["equity_health"] = "DANGER"
        elif float_pct < -5:
            result["equity_health"] = "WARNING"
        else:
            result["equity_health"] = "OK"
        result["float_pct"] = round(float_pct, 1)
    else:
        result["equity_health"] = "UNKNOWN"
        result["float_pct"] = 0

    # --- OVERALL GOLD CONDITION ---
    green_flags = sum([
        result["spread_ok"],
        result["volatility_ok"],
        result["trend_ok"],
        result["session_risk"] != "HIGH"
    ])

    if green_flags >= 3:
        result["gold_condition"] = "FAVORABLE"
    elif green_flags >= 2:
        result["gold_condition"] = "NEUTRAL"
    else:
        result["gold_condition"] = "UNFAVORABLE"

    return result

# ============================================================
# QUANTUM STATE COMPUTATION
# ============================================================

def compute_quantum_state(bos: int, liq_score: float, signal: int) -> dict:
    """Compute probability-weighted state vector (Quantum-inspired)"""
    raw = 0.0

    raw += bos * 0.30

    liq_norm = max(-1.0, min(1.0, liq_score / 10.0)) if liq_score else 0
    raw += liq_norm * 0.20

    raw += signal * 0.25

    bull = max(0.0, raw)
    bear = max(0.0, -raw)
    neutral = max(0.0, 1.0 - bull - bear)

    total = bull + bear + neutral
    if total > 0:
        bull /= total
        bear /= total
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
        "bull": round(bull, 3),
        "bear": round(bear, 3),
        "neutral": round(neutral, 3),
        "state": state
    }

# ============================================================
# 3-STEP LOOKAHEAD PLANNING
# ============================================================

def agent_plan(market_data: dict, gold_vars: dict) -> str:
    """3-step lookahead planner with gold variables"""
    net_pl = market_data.get("net_pl", 0)
    positions = market_data.get("positions", 0)
    worst_pl = market_data.get("worst_loss", 0)
    quantum = market_data.get("quantum_state", {})
    spread = market_data.get("spread", 0)

    # Step 1: Emergency checks
    if net_pl >= TARGET_PROFIT and positions > 0:
        return "CLOSE_ALL"
    if net_pl <= MAX_DRAWDOWN * 0.8:
        return "FAILSAFE"

    # Step 2: Recovery checks
    if worst_pl <= -1.50 and positions > 0:
        return "HEDGE"
    if worst_pl <= -0.70 and positions > 0:
        return "AVERAGE_DOWN"

    # Step 3: Opportunity — gate by gold condition
    q_state = quantum.get("state", "NEUTRAL")
    gold_ok = gold_vars.get("gold_condition", "NEUTRAL") == "FAVORABLE"
    spread_ok = gold_vars.get("spread_ok", False)

    if positions == 0 and q_state in ["COLLAPSE_BUY", "COLLAPSE_SELL"]:
        if spread_ok and gold_ok:
            return "NEWPOS"

    return "WAIT"

# ============================================================
# AGENT REFLECTION
# ============================================================

def agent_reflect(action: str, market_data: dict, result_pl: float):
    """After action, reflect and update performance"""
    perf["total_decisions"] += 1
    perf["last_action"] = action

    if action in ["CLOSE_ALL", "TARGET_HIT"] and result_pl >= TARGET_PROFIT:
        perf["cycles_won"] += 1
    elif action in ["FAILSAFE"] and result_pl < 0:
        perf["cycles_lost"] += 1

    total = perf["cycles_won"] + perf["cycles_lost"]
    if total >= 3:
        win_rate = perf["cycles_won"] / total
        if win_rate < 0.40:
            perf["aggression_factor"] = 0.70
        elif win_rate > 0.70:
            perf["aggression_factor"] = 1.20
        else:
            perf["aggression_factor"] = 1.00

# ============================================================
# GEMINI SYSTEM PROMPT
# ============================================================

KOKO_SYSTEM_PROMPT = """You are KOKO, an autonomous AI trading agent for XAU/USD (Gold Spot).

## YOUR ROLE
You are an AGENTIC system — you OBSERVE market state, REASON about the best action,
ACT with a specific decision, and REFLECT on outcomes.

## MARKET CONTEXT
- Symbol: XAU/USD GOLDmicro on MetaTrader 5
- Goal: Achieve Snowball $0.70 per cycle with max -$25 drawdown
- Strategy: Basket management — buy/sell correlated positions, close at net profit

## GOLD VARIABLES (Important factors for XAU/USD)
1. SPREAD: Tight(<30)=Best, Normal(30-58)=OK, Wide(58-80)=Caution, Danger(>80)=No Entry
2. SESSION: Asian=Low volatility/Range, London=High/Trend, NY+London=Very High/Breakout
3. ATR TIER: Low(<80pts)=Quiet, Medium(80-150)=Normal, High(>150)=Big moves
4. ADX: Flat(<20)=No trend, Weak(20-25)=Avoid, Moderate(25-35)=OK, Strong(>35)=Best
5. EQUITY HEALTH: OK=Normal, WARNING=Caution, DANGER=Reduce risk

## QUANTUM STATE VECTOR
- COLLAPSE_BUY: Bull probability > 65% -> strong buy signal
- COLLAPSE_SELL: Bear probability > 65% -> strong sell signal
- NEUTRAL: Indeterminate, no new positions
- INTERFERE: Bull and Bear cancel out, stay flat
- SUPERPOS: Uncertain, wait for clarity

## KEY SIGNALS
- BOS (Break of Structure): 1=Bullish, -1=Bearish, 0=No break
- MA Cross (S3>S2>S1): 1=BUY signal, -1=SELL signal
- Spread: Keep below 80 points max

## DECISION FRAMEWORK
Priority (highest to lowest):
1. CLOSE_ALL if net_pl >= $0.70 (Target Hit)
2. FAILSAFE if net_pl <= -$17.50 (70% of max drawdown)
3. HEDGE if worst single loss <= -$1.50
4. AVERAGE_DOWN if worst loss <= -$0.70
5. NEWPOS if: no positions AND quantum=COLLAPSE AND gold_condition=FAVORABLE
6. WAIT in all other cases

## OUTPUT FORMAT
Respond ONLY with valid JSON (no markdown, no explanation outside JSON):
{
  "action": "BUY|SELL|CLOSE_ALL|HEDGE|AVERAGE_DOWN|WAIT|FAILSAFE",
  "confidence": 0.0-1.0,
  "reason": "brief explanation",
  "risk_level": "LOW|MEDIUM|HIGH",
  "state": "quantum state summary"
}
"""

# ============================================================
# AGENTIC DECISION ENGINE
# ============================================================

def agentic_decide(market_data: dict) -> dict:
    """Main agentic decision loop: OBSERVE -> REASON -> ACT"""

    # OBSERVE: Store in memory
    memory_entry = {
        "time": datetime.now().isoformat(),
        "bos": market_data.get("bos", 0),
        "net_pl": market_data.get("net_pl", 0),
        "positions": market_data.get("positions", 0),
        "spread": market_data.get("spread", 0),
        "session": market_data.get("session", "?"),
        "adx": market_data.get("adx", 0)
    }
    agent_memory.append(memory_entry)

    # Analyze gold variables
    gold_vars = analyze_gold_variables(market_data)

    # Compute Quantum State
    quantum = compute_quantum_state(
        bos=market_data.get("bos", 0),
        liq_score=market_data.get("liq_score", 0),
        signal=market_data.get("signal_direction", 0)
    )
    market_data["quantum_state"] = quantum

    # PLAN: 3-step lookahead
    planned_action = agent_plan(market_data, gold_vars)

    # REASON: Ask Gemini with full context
    recent_memory = list(agent_memory)[-5:]

    win_rate_str = "N/A"
    total_cycles = perf["cycles_won"] + perf["cycles_lost"]
    if total_cycles > 0:
        win_rate_str = f"{perf['cycles_won']/total_cycles*100:.0f}%"

    prompt = f"""
CURRENT MARKET STATE:
- Price: {market_data.get('price', 0):.2f}
- BOS Direction: {market_data.get('bos', 0)}
- MA Cross: {market_data.get('ma_cross', 0)} (S3>S2>S1 logic)
- EMA8: {market_data.get('ema', 0):.2f}
- Spread: {market_data.get('spread', 0)} pts
- ADX: {market_data.get('adx', 0):.1f}
- ATR: {market_data.get('atr', 0):.1f} pts
- Session: {market_data.get('session', '?')}

GOLD VARIABLES ASSESSMENT:
- Spread Level: {gold_vars.get('spread_level', '?')} (OK={gold_vars.get('spread_ok', False)})
- Session: {gold_vars.get('session_volatility', '?')} | Bias: {gold_vars.get('session_bias', '?')} | Risk: {gold_vars.get('session_risk', '?')}
- ATR Tier: {gold_vars.get('atr_tier', '?')} | Volatility OK: {gold_vars.get('volatility_ok', False)}
- ADX Level: {gold_vars.get('adx_level', '?')} | Trend OK: {gold_vars.get('trend_ok', False)}
- Equity Health: {gold_vars.get('equity_health', '?')} ({gold_vars.get('float_pct', 0):.1f}% float)
- GOLD CONDITION: {gold_vars.get('gold_condition', '?')}

BASKET STATUS:
- Open Positions: {market_data.get('positions', 0)}
- Net P&L: ${market_data.get('net_pl', 0):.2f}
- Worst Loss: ${market_data.get('worst_loss', 0):.2f}
- Profit Positions: {market_data.get('prof_count', 0)} (${market_data.get('prof_sum', 0):.2f})
- Loss Positions: {market_data.get('loss_count', 0)} (${market_data.get('loss_sum', 0):.2f})
- Equity: ${market_data.get('equity', 0):.2f}

QUANTUM STATE VECTOR:
- Bull: {quantum['bull']*100:.0f}% Bear: {quantum['bear']*100:.0f}% Neutral: {quantum['neutral']*100:.0f}%
- State: {quantum['state']}

AGENT PLANNER SUGGESTS: {planned_action}

AGENT PERFORMANCE:
- Cycles Won: {perf['cycles_won']} Lost: {perf['cycles_lost']}
- Win Rate: {win_rate_str}
- Aggression Factor: {perf['aggression_factor']:.1f}x

RECENT HISTORY (last 5):
{json.dumps(recent_memory, indent=2)}

Based on ALL above including Gold Variables Assessment, what is your FINAL trading decision?
"""

    try:
        response = model.generate_content(
            KOKO_SYSTEM_PROMPT + "\n\n" + prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.1,
                max_output_tokens=300
            )
        )

        raw_text = response.text.strip()
        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_text:
            raw_text = raw_text.split("```")[1].split("```")[0].strip()

        result = json.loads(raw_text)
        result["quantum_state"] = quantum
        result["planned_action"] = planned_action
        result["gold_condition"] = gold_vars.get("gold_condition", "?")
        result["agent_memory_size"] = len(agent_memory)

        action_history.append({
            "time": datetime.now().isoformat(),
            "action": result.get("action", "WAIT"),
            "confidence": result.get("confidence", 0),
            "net_pl": market_data.get("net_pl", 0)
        })

        return result

    except Exception as e:
        return {
            "action": planned_action,
            "confidence": 0.60,
            "reason": f"Gemini unavailable, using planner: {str(e)[:50]}",
            "risk_level": "MEDIUM",
            "state": quantum.get("state", "NEUTRAL"),
            "quantum_state": quantum,
            "planned_action": planned_action,
            "gold_condition": gold_vars.get("gold_condition", "?"),
            "error": str(e)
        }

# ============================================================
# FLASK ROUTES
# ============================================================

@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "KOKO Bridge Agentic v3.2",
        "version": "3.2",
        "features": ["gold_variables", "quantum_state", "agentic_loop", "session_filter"],
        "agent_memory": len(agent_memory),
        "cycles_won": perf["cycles_won"],
        "cycles_lost": perf["cycles_lost"],
        "aggression": perf["aggression_factor"],
        "timestamp": datetime.now().isoformat()
    })

@app.route("/decide", methods=["POST"])
def decide():
    """Main agentic decision endpoint"""
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "No data received"}), 400

        required = ["price", "bos", "net_pl", "positions"]
        missing = [f for f in required if f not in data]
        if missing:
            return jsonify({"error": f"Missing fields: {missing}"}), 400

        result = agentic_decide(data)
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e), "action": "WAIT"}), 500

@app.route("/reflect", methods=["POST"])
def reflect():
    """Report trade outcome for agent learning"""
    try:
        data = request.get_json(force=True)
        action = data.get("action", "WAIT")
        result_pl = data.get("result_pl", 0)
        agent_reflect(action, data, result_pl)
        return jsonify({
            "status": "reflected",
            "performance": perf,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/memory", methods=["GET"])
def memory():
    """View agent memory"""
    return jsonify({
        "memory": list(agent_memory),
        "actions": list(action_history),
        "performance": perf
    })

@app.route("/reset", methods=["POST"])
def reset():
    """Reset agent state"""
    agent_memory.clear()
    action_history.clear()
    perf["cycles_won"] = 0
    perf["cycles_lost"] = 0
    perf["total_decisions"] = 0
    perf["aggression_factor"] = 1.0
    return jsonify({"status": "reset complete"})

@app.route("/analyze", methods=["POST"])
def analyze():
    """Legacy endpoint"""
    try:
        data = request.get_json(force=True)
        result = agentic_decide(data)
        return jsonify({
            "action": result.get("action", "WAIT"),
            "confidence": result.get("confidence", 0.5),
            "reason": result.get("reason", ""),
            "quantum": result.get("quantum_state", {}),
            "planned": result.get("planned_action", "WAIT")
        })
    except Exception as e:
        return jsonify({"action": "WAIT", "error": str(e)}), 500

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"KOKO Bridge Agentic v3.2 starting on port {port}")
    print(f"Features: Gold Variables | Quantum State | Session Filter | Agentic Loop")
    app.run(host="0.0.0.0", port=port)

