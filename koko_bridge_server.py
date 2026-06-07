# KOKO Bridge Server v2.1
from flask import Flask, request, jsonify
import google.generativeai as genai
import os, json

app = Flask(__name__)
genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))
model = genai.GenerativeModel("gemini-2.0-flash")
API_KEY = os.environ.get("KOKO_API_KEY", "KOKO-BRIDGE-KEY-001")

KOKO_SYSTEM = """คุณคือ KOKO AI ผู้เชี่ยวชาญการเทรด XAU/USD ระดับ Institutional
ตอบเป็น JSON เท่านั้น:
{"signal":"...","score":"85/100","direction":"BUY/SELL/WAIT","reason":"...ไม่เกิน60ตัว"}
หลักการ: LIQ Score>=100=SUPER PREMIUM | >=70=PREMIUM | <40=อย่าเชื่อ
VolDelta+>0=แรงซื้อ | <0=แรงขาย | Trend H4+D1 ต้องตรงกัน"""

@app.route("/analyze", methods=["POST"])
def analyze():
    if request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    prompt = f"""{KOKO_SYSTEM}
XAU/USD: ราคา={data.get('price')} Spread={data.get('spread')} ATR={data.get('atr')} RSI={data.get('rsi')}
EMA21={data.get('ema_fast')} EMA50={data.get('ema_slow')} BuyVol={data.get('buy_vol_pct')}%
VolDelta={data.get('vol_delta')} TrendH4={data.get('trend_h4')} TrendD1={data.get('trend_d1')}
LIQ Score={data.get('liq_score')} Dir={data.get('liq_dir')} Grade={data.get('liq_grade')}
Session={data.get('session')} Equity=${data.get('equity')} Pos={data.get('positions')}"""
    try:
        r = model.generate_content(prompt)
        t = r.text.strip()
        if t.startswith("```"): t = t.split("```")[1]; t = t[4:] if t.startswith("json") else t
        result = json.loads(t)
    except Exception as e:
        result = {"signal":"Error","score":"0/100","direction":"WAIT","reason":str(e)[:60]}
    return jsonify(result), 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status":"KOKO Bridge v2.1 OK","ai":"Gemini","liq":"enabled"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)))

