# KOKO Bridge Server v2.2
# Changelog: แก้ 429 Quota Error + retry logic

from flask import Flask, request, jsonify
import google.generativeai as genai
import os, json, time

app = Flask(__name__)
genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))
model = genai.GenerativeModel("gemini-2.0-flash")
API_KEY = os.environ.get("KOKO_API_KEY", "KOKO-BRIDGE-KEY-001")

quota_errors = 0

KOKO_SYSTEM = """คุณคือ KOKO AI ผู้เชี่ยวชาญการเทรด XAU/USD ระดับ Institutional
วิเคราะห์ข้อมูลตลาดและตอบเป็น JSON เท่านั้น รูปแบบ:
{"signal":"...","score":"85/100","direction":"BUY/SELL/WAIT","reason":"...ไม่เกิน60ตัว"}
หลักการ: LIQ Score>=100=SUPER PREMIUM | >=70=PREMIUM | <40=อย่าเชื่อ
VolDelta+>=แรงซื้อ | <=แรงขาย | Trend H4+D1 ต้องตรงกัน
ตอบเป็น JSON เท่านั้น ไม่มีข้อความอื่น"""

def call_gemini(prompt):
    global quota_errors
    for attempt in range(2):
        try:
            response = model.generate_content(prompt)
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"): text = text[4:]
            return json.loads(text), None
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "ResourceExhausted" in err_str or "quota" in err_str.lower():
                quota_errors += 1
                if attempt == 0:
                    time.sleep(5)
                    continue
                else:
                    return None, "429"
            else:
                return None, err_str[:60]
    return None, "Unknown error"

@app.route("/analyze", methods=["POST"])
def analyze():
    if request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400

    vol_delta = data.get('vol_delta', 0)
    trend_h4  = data.get('trend_h4', 'UNKNOWN')
    trend_d1  = data.get('trend_d1', 'UNKNOWN')
    liq_dir   = data.get('liq_dir', 'NONE')
    trend_align     = "ALIGN"   if trend_h4 == trend_d1 else "CONFLICT"
    liq_trend_match = "CONFIRM" if liq_dir  == trend_h4 else "COUNTER"

    prompt = f"""{KOKO_SYSTEM}

ราคา: {data.get('price')} | Spread: {data.get('spread')} | Session: {data.get('session')}
ATR: {data.get('atr')} | RSI: {data.get('rsi')}
EMA21: {data.get('ema_fast')} | EMA50: {data.get('ema_slow')}
BuyVol%: {data.get('buy_vol_pct')}% | VolDelta: {vol_delta}
H4: {trend_h4} | D1: {trend_d1} | Trend: {trend_align}
LIQ Score: {data.get('liq_score')} | Grade: {data.get('liq_grade')}
LIQ Dir: {liq_dir} | vs Trend: {liq_trend_match}
Equity: ${data.get('equity')} | Float: ${data.get('float_pl')} | Pos: {data.get('positions')}
วิเคราะห์และตอบเป็น JSON"""

    result, error = call_gemini(prompt)
    if error == "429":
        return jsonify({"signal":"WAIT","score":"0/100","direction":"WAIT","reason":"Quota หมด รอสักครู่"}), 429
    if result is None:
        result = {"signal":"Error","score":"0/100","direction":"WAIT","reason": error}
    return jsonify(result), 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status":"KOKO Bridge v2.2 OK","quota_errors": quota_errors}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
