# KOKO Bridge Server v2.1
# MT5 → Gemini AI | รองรับ LIQ Signal Buffer
# BOS/Score/Direction/VolumeDelta/MajorTrend

from flask import Flask, request, jsonify
import google.generativeai as genai
import os, json

app = Flask(__name__)
genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))
model = genai.GenerativeModel("gemini-2.0-flash")
API_KEY = os.environ.get("KOKO_API_KEY", "KOKO-BRIDGE-KEY-001")

KOKO_SYSTEM = """คุณคือ KOKO AI ผู้เชี่ยวชาญการเทรด XAU/USD ระดับ Institutional
วิเคราะห์ข้อมูลตลาดและตอบเป็น JSON เท่านั้น รูปแบบ:
{
  "signal": "สรุปสั้นๆ เช่น SELL Premium โอกาสสูง",
  "score": "85/100",
  "direction": "SELL หรือ BUY หรือ WAIT",
  "reason": "เหตุผลสั้นๆ ภาษาไทย ไม่เกิน 60 ตัวอักษร"
}

หลักการวิเคราะห์ KOKO:
1. Volume Delta: + = แรงซื้อจริง | - = แรงขายจริง
2. LIQ Score ≥ 100 = SUPER PREMIUM → เชื่อถือสูงสุด
3. LIQ Score ≥ 70 = PREMIUM → เชื่อถือสูง
4. LIQ Score < 40 = อย่าเชื่อ Signal
5. Trend H4+D1 ต้องตรงกัน = Major Trend ชัดเจน
6. LIQ Dir ต้องตรงกับ Major Trend = ยิ่งแม่น
7. Volume ต่ำ + ราคาวิ่ง = Fake Move อย่าเข้า
8. BOS ด้วย Volume ต่ำ = Fake BOS
9. Trap Zone: Buy Fake/Sell Real = SELL | Sell Fake/Buy Real = BUY
10. ถ้า LIQ Dir ขัดแย้งกับ Trend = WAIT

ตอบเป็น JSON เท่านั้น ไม่มีข้อความอื่น"""

@app.route("/analyze", methods=["POST"])
def analyze():
    if request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400

    liq_score = data.get('liq_score', 0)
    liq_dir   = data.get('liq_dir', 'NONE')
    liq_grade = data.get('liq_grade', 'NONE')
    trend_h4  = data.get('trend_h4', 'UNKNOWN')
    trend_d1  = data.get('trend_d1', 'UNKNOWN')
    vol_delta = data.get('vol_delta', 0)

    trend_align = "✅ ALIGN" if trend_h4 == trend_d1 else "⚠️ CONFLICT"
    liq_trend_match = "✅ CONFIRM" if liq_dir == trend_h4 else "⚠️ COUNTER"

    prompt = f"""{KOKO_SYSTEM}

วิเคราะห์ตลาด XAU/USD ตอนนี้:

=== ราคา & Spread ===
ราคา: {data.get('price')} | Spread: {data.get('spread')} pts | Session: {data.get('session')}

=== Technical ===
ATR: {data.get('atr')} pts | RSI: {data.get('rsi')}
EMA Fast(21): {data.get('ema_fast')} | EMA Slow(50): {data.get('ema_slow')}

=== Volume Analysis ===
Buy Vol%: {data.get('buy_vol_pct')}% | Volume Delta: {vol_delta} ({'+' if float(vol_delta)>0 else ''}{vol_delta})

=== Major Trend ===
H4 Trend: {trend_h4} | D1 Trend: {trend_d1} | {trend_align}

=== KOKO LIQ Signal ===
Score: {liq_score}/100 | Grade: {liq_grade}
Direction: {liq_dir} | vs Trend: {liq_trend_match}

=== Account ===
Equity: ${data.get('equity')} | Float P/L: ${data.get('float_pl')}
Positions: {data.get('positions')} ไม้

วิเคราะห์และตอบเป็น JSON"""

    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"): text = text[4:]
        result = json.loads(text)
    except Exception as e:
        result = {"signal": "วิเคราะห์ไม่สำเร็จ", "score": "0/100",
                  "direction": "WAIT", "reason": str(e)[:60]}
    return jsonify(result), 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "KOKO Bridge v2.1 OK", "ai": "Gemini", "liq": "enabled"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
