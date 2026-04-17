def calculate_master_score(sym):
    try:
        # جلب البيانات
        tf15 = pd.DataFrame(exchange.fetch_ohlcv(sym, '15m', limit=100), columns=['t','o','h','l','c','v'])
        tf4h = pd.DataFrame(exchange.fetch_ohlcv(sym, '4h', limit=100), columns=['t','o','h','l','c','v'])

        # تجهيز المؤشرات
        tf15['ma9'] = tf15['c'].rolling(9).mean()
        tf15['ma21'] = tf15['c'].rolling(21).mean()
        tf4h['ma200'] = tf4h['c'].rolling(200).mean()

        l15, l4h = tf15.iloc[-1], tf4h.iloc[-1]
        
        score = 0
        details = []

        # 1. فلتر الترند (أساسي للامان)
        if l4h['c'] > l4h['ma200']: 
            score += 25
            details.append("Trend4H")

        # 2. تقاطع الزخم السريع 15د
        if l15['c'] > l15['ma9'] and l15['ma9'] > l15['ma21']:
            score += 25
            details.append("Momentum")

        # 3. فحص السيولة (تسهيل الشرط لـ 1.5 ضعف)
        avg_vol = tf15['v'].rolling(20).mean().iloc[-1]
        if l15['v'] > avg_vol * 1.5:
            score += 20
            details.append("Volume")

        # 4. قوة الاتجاه (تسهيل الشرط ADX > 20)
        adx_val = calculate_adx(tf15).iloc[-1]
        if adx_val > 20:
            score += 15
            details.append("ADX")

        # 5. ضيق البولنجر (Squeeze)
        sma20 = tf15['c'].rolling(20).mean()
        std20 = tf15['c'].rolling(20).std()
        bbw = ((sma20 + 2*std20) - (sma20 - 2*std20)) / sma20
        if bbw.iloc[-1] < 0.04: # جعل النطاق أوسع قليلاً للاكتشاف
            score += 15
            details.append("Squeeze")

        return score, "|".join(details)
    except:
        return 0, ""
