# KOKO Bridge Server v1.0
# รับข้อมูลจาก MT5 → ส่งให้ Claude วิเคราะห์ → ส่งคำตอบกลับ MT5
# Deploy บน Render.com ฟรี

from flask import Flask, request, jsonify
import anthropic
import os
import json

app = Flask(__name__)
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
API_KEY = os.environ.get("KOKO_API_KEY", "KOKO-BRIDGE-KEY-001")

KOKO_SYSTEM = """คุณคือ KOKO AI ผู้เชี่ยวชาญด้านการเทรด XAU/USD
วิเคราะห์ข้อมูลตลาดที่ได้รับและตอบเป็น JSON เท่านั้น รูปแบบ:
{
  "signal": "สรุปสั้นๆ เช่น SELL โอกาสสูง",
  "score": "85/100",
  "direction": "SELL หรือ BUY หรือ WAIT",
  "reason": "เหตุผลสั้นๆ ภาษาไทย ไม่เกิน 50 ตัวอักษร"
}

หลัก KOKO:
- Volume ต่ำ + ราคาวิ่ง = Fake
- Score < 50 = อย่าเชื่อ Bias
- BOS Volume ต่ำ = Fake Break
- ATR คือความผันผวนจริง
ตอบเป็น JSON เท่านั้น ไม่มีข้อความอื่น"""

@app.route("/analyze", methods=["POST"])
def analyze():
    if request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    prompt = f"""วิเคราะห์ตลาด XAU/USD ตอนนี้:
ราคา: {data.get('price')} | Spread: {data.get('spread')} pts
ATR: {data.get('atr')} pts | RSI: {data.get('rsi')}
EMA Fast: {data.get('ema_fast')} | EMA Slow: {data.get('ema_slow')}
Buy Vol%: {data.get('buy_vol_pct')}% | Session: {data.get('session')}
Equity: ${data.get('equity')} | Float P/L: ${data.get('float_pl')}
Positions: {data.get('positions')} ไม้
วิเคราะห์และตอบเป็น JSON"""
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=200,
        system=KOKO_SYSTEM,
        messages=[{"role": "user", "content": prompt}]
    )
    response_text = message.content[0].text.strip()
    try:
        result = json.loads(response_text)
    except:
        result = {"signal": "วิเคราะห์ไม่สำเร็จ","score": "0/100","direction": "WAIT","reason": "ข้อมูลไม่เพียงพอ"}
    return jsonify(result), 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "KOKO Bridge OK", "version": "1.0"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
