
koko_bridge_agentic_v3.py

หน้า
1
/
1
100%
#!/usr/bin/env python3
"""
KOKO Bridge Agentic Server v3.0
Version: 3.0
Date: 17 Jun 2026
Author: KOKO (AI) x พี่ต่อ (Nont)

Upgrade from v2.x:
  [NEW-A1] Agentic Loop: memory + planning + reflect
  [NEW-A2] Agent Memory Buffer (last 20 states)
  [NEW-A3] 3-Step Lookahead Planning
  [NEW-A4] LIQ Score (Buffer4) + Direction (Buffer5) in payload
  [NEW-A5] Gemini system prompt upgraded with BOS/Score/Direction awareness
  [NEW-Q1] Quantum State Vector in Gemini context
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
MAX_DRAWDOWN  = -25.0
SNOWBALL_TARGET = 0.70

# === AGENT MEMORY ===
agent_memory = deque(maxlen=20)  # Last 20 market states
action_history = deque(maxlen=10) # Last 10 actions taken

# === AGENT PERFORMANCE ===
perf = {
    "cycles_won": 0,
    "cycles_lost": 0,
    "total_decisions": 0,
    "last_action": "WAIT",
    "aggression_factor": 1.0
}

# ============================================================
# QUANTUM STATE COMPUTATION (Python side)
# ============================================================

def compute_quantum_state(bos: int, liq_score: float, signal: int) -> dict:
    """Compute probability-weighted state vector (Quantum-inspired)"""
    raw = 0.0
    
    # BOS contribution (30%)
    raw += bos * 0.30
    
    # LIQ Score contribution (20%) — normalize from -10..10 to -1..1
    liq_norm = max(-1.0, min(1.0, liq_score / 10.0)) if liq_score else 0
    raw += liq_norm * 0.20
    
    # Signal direction contribution (25%)
    raw += signal * 0.25
    
    bull  = max(0.0, raw)
    bear  = max(0.0, -raw)
    neutral = max(0.0, 1.0 - bull - bear)
    
    total = bull + bear + neutral
    if total > 0:
        bull    /= total
        bear    /= total
        neutral /= total
    else:
        neutral = 1.0
    
    # Determine collapsed state
    if bull >= 0.65:
        state = "COLLAPSE_BUY"
    elif bear >= 0.65:
        state = "COLLAPSE_SELL"
    elif neutral >= 0.60:
        state = "NEUTRAL"
    elif 0.45 <= bull <= 0.55:
        state = "INTERFERE"
    else:
        state = f"SUPERPOS"
    
    return {
        "bull":    round(bull, 3),
        "bear":    round(bear, 3),
        "neutral": round(neutral, 3),
        "state":   state
    }

# ============================================================
# 3-STEP LOOKAHEAD PLANNING
# ============================================================

def agent_plan(market_data: dict) -> str:
    """Simple 3-step lookahead planner"""
    net_pl    = market_data.get("net_pl", 0)
    positions = market_data.get("positions", 0)
    worst_pl  = market_data.get("worst_loss", 0)
    quantum   = market_data.get("quantum_state", {})
    spread    = market_data.get("spread", 0)
    
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
    
    # Step 3: Opportunity checks (quantum-gated)
    q_state = quantum.get("state", "NEUTRAL")
    if positions == 0 and q_state in ["COLLAPSE_BUY", "COLLAPSE_SELL"]:
        if spread <= 58:
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
    
    # Adapt aggression
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
# GEMINI AGENTIC SYSTEM PROMPT
# ============================================================

KOKO_SYSTEM_PROMPT = """You are KOKO, an autonomous AI trading agent for XAU/USD (Gold Spot).

## YOUR ROLE
You are an AGENTIC system — you OBSERVE market state, REASON about the best action,
ACT with a specific decision, and REFLECT on outcomes.

## MARKET CONTEXT
- Symbol: XAU/USD GOLDmicro on MetaTrader 5
- Goal: Achieve Snowball $0.70 per cycle with max -$25 drawdown
- Strategy: Basket management — buy/sell correlated positions, close at net profit

## QUANTUM STATE VECTOR
The market exists in a probabilistic state:
- COLLAPSE_BUY: Bull probability > 65% → strong buy signal
- COLLAPSE_SELL: Bear probability > 65% → strong sell signal  
- NEUTRAL: Indeterminate, no new positions
- INTERFERE: Bull and Bear cancel out, stay flat
- SUPERPOS: Uncertain, wait for clarity

## KEY SIGNALS
- BOS (Break of Structure): 1=Bullish, -1=Bearish, 0=No break
- LIQ Score: -10 to +10 (negative=bearish, positive=bullish)
- LIQ Direction: 1.0=BUY signal, -1.0=SELL signal, 0=neutral
- MA Cross (HackMode): 1=Yellow/Green cross above Red, -1=below Red
- Spread: Keep below 58 points for entries

## AGENT MEMORY
You receive the last 5 market states to understand context and trends.
Use this to avoid repetitive actions and detect momentum shifts.

## DECISION FRAMEWORK
Priority (highest to lowest):
1. CLOSE_ALL if net_pl >= $0.70 (Target Hit)
2. FAILSAFE if net_pl <= -$17.50 (70% of max)
3. HEDGE if worst single loss <= -$1.50 and no profitable positions
4. AVERAGE_DOWN if worst loss <= -$0.70 (add same direction, small lot)
5. NEWPOS if no positions AND quantum state is COLLAPSE (strong signal)
6. WAIT in all other cases

## OUTPUT FORMAT
Respond ONLY with valid JSON (no markdown, no explanation):
{
  "action": "BUY|SELL|CLOSE_ALL|HEDGE|AVERAGE_DOWN|WAIT|FAILSAFE",
  "confidence": 0.0-1.0,
  "reason": "brief explanation in Thai or English",
  "risk_level": "LOW|MEDIUM|HIGH",
  "quantum_assessment": "brief quantum state interpretation"
}
"""

# ============================================================
# AGENTIC DECISION ENGINE
# ============================================================

def agentic_decide(market_data: dict) -> dict:
    """Main agentic decision loop: OBSERVE → REASON → ACT"""
    
    # OBSERVE: Store in memory
    memory_entry = {
        "time": datetime.now().isoformat(),
        "bos":  market_data.get("bos", 0),
        "net_pl": market_data.get("net_pl", 0),
        "positions": market_data.get("positions", 0),
        "liq_score": market_data.get("liq_score", 0),
        "spread": market_data.get("spread", 0)
    }
    agent_memory.append(memory_entry)
    
    # Compute Quantum State
    quantum = compute_quantum_state(
        bos=market_data.get("bos", 0),
        liq_score=market_data.get("liq_score", 0),
        signal=market_data.get("signal_direction", 0)
    )
    market_data["quantum_state"] = quantum
    
    # PLAN: 3-step lookahead
    planned_action = agent_plan(market_data)
    
    # REASON: Ask Gemini with full context
    recent_memory = list(agent_memory)[-5:]  # Last 5 states
    
    prompt = f"""
CURRENT MARKET STATE:
- Price: {market_data.get('price', 0):.2f}
- BOS Direction: {market_data.get('bos', 0)} ({'+1=BUY' if market_data.get('bos',0)==1 else '-1=SELL' if market_data.get('bos',0)==-1 else 'NONE'})
- LIQ Score: {market_data.get('liq_score', 0):.1f}
- LIQ Direction: {market_data.get('liq_direction', 0)} (1.0=BUY, -1.0=SELL)
- MA Cross Signal: {market_data.get('ma_cross', 0)}
- EMA8: {market_data.get('ema', 0):.2f}
- Spread: {market_data.get('spread', 0)} pts
- ADX: {market_data.get('adx', 0):.1f}

BASKET STATUS:
- Open Positions: {market_data.get('positions', 0)}
- Net P&L: ${market_data.get('net_pl', 0):.2f}
- Worst Loss: ${market_data.get('worst_loss', 0):.2f}
- Profit Positions: {market_data.get('prof_count', 0)} (${market_data.get('prof_sum', 0):.2f})
- Loss Positions: {market_data.get('loss_count', 0)} (${market_data.get('loss_sum', 0):.2f})

QUANTUM STATE VECTOR:
- Bull: {quantum['bull']*100:.0f}%  Bear: {quantum['bear']*100:.0f}%  Neutral: {quantum['neutral']*100:.0f}%
- State: {quantum['state']}

AGENT PLANNER SUGGESTS: {planned_action}

AGENT PERFORMANCE:
- Cycles Won: {perf['cycles_won']}  Lost: {perf['cycles_lost']}
- Win Rate: {perf['cycles_won']/(perf['cycles_won']+perf['cycles_lost'])*100:.0f}% (if available)
- Aggression Factor: {perf['aggression_factor']:.1f}x

RECENT HISTORY (last 5 bars):
{json.dumps(recent_memory, indent=2)}

Based on all above context, what is your FINAL trading decision?
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
        # Clean JSON
        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_text:
            raw_text = raw_text.split("```")[1].split("```")[0].strip()
        
        result = json.loads(raw_text)
        result["quantum_state"]   = quantum
        result["planned_action"]  = planned_action
        result["agent_memory_size"] = len(agent_memory)
        
        # Store action
        action_history.append({
            "time": datetime.now().isoformat(),
            "action": result.get("action", "WAIT"),
            "confidence": result.get("confidence", 0),
            "net_pl": market_data.get("net_pl", 0)
        })
        
        return result
        
    except Exception as e:
        # Fallback to planner
        return {
            "action": planned_action,
            "confidence": 0.60,
            "reason": f"Gemini unavailable, using planner: {str(e)[:50]}",
            "risk_level": "MEDIUM",
            "quantum_state": quantum,
            "planned_action": planned_action,
            "error": str(e)
        }

# ============================================================
# FLASK ROUTES
# ============================================================

@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "KOKO Bridge Agentic v3.0",
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
        
        # [NEW] Validate required fields
        required = ["price", "bos", "net_pl", "positions"]
        missing = [f for f in required if f not in data]
        if missing:
            return jsonify({"error": f"Missing fields: {missing}"}), 400
        
        # Run agentic decision
        result = agentic_decide(data)
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({"error": str(e), "action": "WAIT"}), 500

@app.route("/reflect", methods=["POST"])
def reflect():
    """Report trade outcome for agent learning"""
    try:
        data = request.get_json(force=True)
        action    = data.get("action", "WAIT")
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
    """Reset agent state (new session)"""
    agent_memory.clear()
    action_history.clear()
    perf["cycles_won"] = 0
    perf["cycles_lost"] = 0
    perf["total_decisions"] = 0
    perf["aggression_factor"] = 1.0
    return jsonify({"status": "reset complete"})

# ============================================================
# LEGACY ENDPOINT (backward compatible with v2.x)
# ============================================================

@app.route("/analyze", methods=["POST"])
def analyze():
    """Legacy endpoint — maps to new agentic decide"""
    try:
        data = request.get_json(force=True)
        result = agentic_decide(data)
        # Return in legacy format
        return jsonify({
            "action":     result.get("action", "WAIT"),
            "confidence": result.get("confidence", 0.5),
            "reason":     result.get("reason", ""),
            "quantum":    result.get("quantum_state", {}),
            "planned":    result.get("planned_action", "WAIT")
        })
    except Exception as e:
        return jsonify({"action": "WAIT", "error": str(e)}), 500

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"KOKO Bridge Agentic v3.0 starting on port {port}")
    print(f"Endpoints: /decide (new) | /analyze (legacy) | /reflect | /memory | /reset")
    app.run(host="0.0.0.0", port=port)
กำลังแสดง koko_bridge_agentic_v3.py
