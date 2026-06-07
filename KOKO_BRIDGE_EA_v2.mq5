//+------------------------------------------------------------------+
//| KOKO_BRIDGE_EA v2.0                                              |
//| เชื่อม MT5 → Gemini AI | เพิ่ม LIQ Signal Buffer               |
//| BOS/Score/Direction/VolumeDelta/MajorTrend                       |
//| Version: 2.0 | Date: 2026-06-07                                  |
//+------------------------------------------------------------------+
#property copyright "KOKO Trading System"
#property version   "2.0"
#property strict

input group "=== BRIDGE SETTINGS ==="
input string InpServerURL    = "https://koko-bridge.onrender.com/analyze";
input string InpApiKey       = "KOKO-BRIDGE-KEY-001";
input int    InpSendInterval = 30;
input group "=== LIQ SIGNAL ==="
input string InpLIQName      = "KOKO_LIQ_Signal_v1.6"; // ชื่อ indicator ใน MT5
input group "=== DISPLAY ==="
input bool   InpShowPanel    = true;

datetime g_lastSend   = 0;
string   g_lastSignal = "รอข้อมูล...";
string   g_lastScore  = "---";
string   g_lastDir    = "---";
string   g_lastReason = "---";

int OnInit()
{
   EventSetTimer(InpSendInterval);
   Print("=== KOKO BRIDGE v2.0 === LIQ Signal Ready");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) { EventKillTimer(); Comment(""); }
void OnTimer() { SendToAI(); }
void OnTick()  { if(InpShowPanel) ShowPanel(); }

void SendToAI()
{
   // --- ข้อมูลพื้นฐาน ---
   double bid    = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask    = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double spread = (ask - bid) / _Point / 10;

   int hATR = iATR(_Symbol, PERIOD_M15, 14);
   double atrArr[3]; CopyBuffer(hATR, 0, 0, 3, atrArr);
   double atr = atrArr[1] / _Point / 10;
   IndicatorRelease(hATR);

   int hRSI = iRSI(_Symbol, PERIOD_M15, 14, PRICE_CLOSE);
   double rsiArr[3]; CopyBuffer(hRSI, 0, 0, 3, rsiArr);
   double rsi = rsiArr[1];
   IndicatorRelease(hRSI);

   int hEMAF = iMA(_Symbol, PERIOD_M15, 21, 0, MODE_EMA, PRICE_CLOSE);
   int hEMAS = iMA(_Symbol, PERIOD_M15, 50, 0, MODE_EMA, PRICE_CLOSE);
   double emaFArr[3], emaSArr[3];
   CopyBuffer(hEMAF, 0, 0, 3, emaFArr);
   CopyBuffer(hEMAS, 0, 0, 3, emaSArr);
   double emaF = emaFArr[1], emaS = emaSArr[1];
   IndicatorRelease(hEMAF); IndicatorRelease(hEMAS);

   // --- Volume Delta ---
   long   volArr[5]; double openArr[5], closeArr[5];
   CopyTickVolume(_Symbol, PERIOD_M15, 0, 5, volArr);
   CopyOpen(_Symbol,  PERIOD_M15, 0, 5, openArr);
   CopyClose(_Symbol, PERIOD_M15, 0, 5, closeArr);
   double buyVol = 0, sellVol = 0, totalVol = 0;
   for(int i = 0; i < 5; i++)
   {
      totalVol += volArr[i];
      if(closeArr[i] > openArr[i]) buyVol  += volArr[i];
      else                          sellVol += volArr[i];
   }
   double buyVolPct  = totalVol > 0 ? buyVol  / totalVol * 100 : 50;
   double volDelta   = buyVol - sellVol; // + = Buy pressure, - = Sell pressure

   // --- Major Trend H4/D1 ---
   int hEMA_H4 = iMA(_Symbol, PERIOD_H4, 50, 0, MODE_EMA, PRICE_CLOSE);
   int hEMA_D1 = iMA(_Symbol, PERIOD_D1, 50, 0, MODE_EMA, PRICE_CLOSE);
   double emaH4Arr[2], emaD1Arr[2];
   CopyBuffer(hEMA_H4, 0, 0, 2, emaH4Arr);
   CopyBuffer(hEMA_D1, 0, 0, 2, emaD1Arr);
   string trendH4 = bid > emaH4Arr[1] ? "BULL" : "BEAR";
   string trendD1 = bid > emaD1Arr[1] ? "BULL" : "BEAR";
   IndicatorRelease(hEMA_H4); IndicatorRelease(hEMA_D1);

   // --- LIQ Signal Buffer (Buffer4=Score, Buffer5=Direction) ---
   double liqScore = 0;
   string liqDir   = "NONE";
   string liqGrade = "NONE";
   int hLIQ = iCustom(_Symbol, PERIOD_M15, InpLIQName);
   if(hLIQ != INVALID_HANDLE)
   {
      double scoreArr[3], dirArr[3];
      if(CopyBuffer(hLIQ, 4, 0, 3, scoreArr) > 0) liqScore = scoreArr[1];
      if(CopyBuffer(hLIQ, 5, 0, 3, dirArr)   > 0)
      {
         if(dirArr[1] ==  1.0) liqDir = "BUY";
         if(dirArr[1] == -1.0) liqDir = "SELL";
      }
      if(liqScore >= 100) liqGrade = "SUPER_PREMIUM";
      else if(liqScore >= 70) liqGrade = "PREMIUM";
      else if(liqScore >= 40) liqGrade = "STANDARD";
      IndicatorRelease(hLIQ);
   }

   // --- Account ---
   double equity   = AccountInfoDouble(ACCOUNT_EQUITY);
   double balance  = AccountInfoDouble(ACCOUNT_BALANCE);
   double floatPL  = equity - balance;
   int    positions = PositionsTotal();

   // --- Session ---
   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   int gmtH = dt.hour - 6; if(gmtH < 0) gmtH += 24;
   string session = (gmtH>=0&&gmtH<7)?"Asian":(gmtH>=7&&gmtH<12)?"London":(gmtH>=12&&gmtH<16)?"NY+London":"NewYork";

   // --- Build JSON ---
   string json = "{";
   json += "\"symbol\":\""  + _Symbol + "\",";
   json += "\"price\":"     + DoubleToString(bid, 2) + ",";
   json += "\"spread\":"    + DoubleToString(spread, 1) + ",";
   json += "\"atr\":"       + DoubleToString(atr, 1) + ",";
   json += "\"rsi\":"       + DoubleToString(rsi, 1) + ",";
   json += "\"ema_fast\":"  + DoubleToString(emaF, 2) + ",";
   json += "\"ema_slow\":"  + DoubleToString(emaS, 2) + ",";
   json += "\"buy_vol_pct\":" + DoubleToString(buyVolPct, 1) + ",";
   json += "\"vol_delta\":"   + DoubleToString(volDelta, 0) + ",";
   json += "\"trend_h4\":\"" + trendH4 + "\",";
   json += "\"trend_d1\":\"" + trendD1 + "\",";
   json += "\"liq_score\":"  + DoubleToString(liqScore, 1) + ",";
   json += "\"liq_dir\":\""  + liqDir + "\",";
   json += "\"liq_grade\":\"" + liqGrade + "\",";
   json += "\"session\":\""  + session + "\",";
   json += "\"equity\":"     + DoubleToString(equity, 2) + ",";
   json += "\"float_pl\":"   + DoubleToString(floatPL, 2) + ",";
   json += "\"positions\":"  + IntegerToString(positions);
   json += "}";

   char post[]; StringToCharArray(json, post, 0, StringLen(json));
   char result[]; string headers;
   string reqHeaders = "Content-Type: application/json\r\nX-API-Key: " + InpApiKey + "\r\n";
   int res = WebRequest("POST", InpServerURL, reqHeaders, 5000, post, result, headers);
   if(res == 200)
   {
      ParseAIResponse(CharArrayToString(result));
      g_lastSend = TimeCurrent();
      Print("KOKO BRIDGE v2.0: ", g_lastDir, " | Score:", g_lastScore, " | LIQ:", liqGrade);
   }
   else Print("KOKO BRIDGE v2.0: Error ", res);
}

void ParseAIResponse(string r)
{
   int p;
   p = StringFind(r, "\"signal\":\"");   if(p>=0){p+=10; int q=StringFind(r,"\"",p); g_lastSignal=StringSubstr(r,p,q-p);}
   p = StringFind(r, "\"score\":\"");    if(p>=0){p+=9;  int q=StringFind(r,"\"",p); g_lastScore =StringSubstr(r,p,q-p);}
   p = StringFind(r, "\"direction\":\"");if(p>=0){p+=13; int q=StringFind(r,"\"",p); g_lastDir   =StringSubstr(r,p,q-p);}
   p = StringFind(r, "\"reason\":\"");   if(p>=0){p+=10; int q=StringFind(r,"\"",p); g_lastReason=StringSubstr(r,p,q-p);}
}

void ShowPanel()
{
   double bid    = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double balance= AccountInfoDouble(ACCOUNT_BALANCE);
   int nextSend  = (int)(InpSendInterval - (TimeCurrent() - g_lastSend));
   if(nextSend < 0) nextSend = 0;
   string sep = "==============================\n";
   string div = "------------------------------\n";
   string d   = sep + "  KOKO BRIDGE v2.0\n" + "  MT5 x Gemini AI | LIQ Signal\n" + sep;
   d += "XAU/USD @ " + DoubleToString(bid, 2) + "\n" + div;
   d += "AI Signal  : " + g_lastSignal + "\n";
   d += "Score      : " + g_lastScore  + "\n";
   d += "Direction  : " + g_lastDir    + "\n";
   d += "เหตุผล     : " + g_lastReason + "\n" + div;
   d += "Equity : $" + DoubleToString(equity, 2)  + "\n";
   d += "Float  : $" + DoubleToString(equity-balance, 2) + "\n";
   d += "Pos    : "  + IntegerToString(PositionsTotal()) + " ไม้\n" + div;
   d += "ส่งใน  : "  + IntegerToString(nextSend) + " วินาที\n";
   d += sep + "KOKO AI v2.0 | Gemini+LIQ\n";
   Comment(d);
}
