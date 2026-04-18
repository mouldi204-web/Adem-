# ============================================
# دوال الأزرار التفاعلية
# ============================================

def show_trading_menu(chat_id, message_id=None):
    """عرض قائمة التداول الرئيسية مع أزرار"""
    keyboard = [
        [{'text': "💥 كشف الانفجارات", 'callback_data': "SCAN_EXPLOSIONS"}],
        [{'text': "🟢 فتح صفقة", 'callback_data': "OPEN_TRADE_MENU"}],
        [{'text': "🔴 إغلاق صفقة", 'callback_data': "CLOSE_TRADE_MENU"}],
        [{'text': "💰 محفظتي", 'callback_data': "SHOW_PORTFOLIO"}],
        [{'text': "📊 حالة البوت", 'callback_data': "BOT_STATUS"}],
        [{'text': "📁 تحميل CSV", 'callback_data': "EXPORT_CSV"}]
    ]
    reply_markup = {'inline_keyboard': keyboard}
    
    status = get_portfolio_status()
    msg = f"""
🤖 <b>قائمة التداول</b>

💰 الرصيد: <code>${status['balance']:.2f}</code>
📈 الربح: <code>${status['total_pnl']:+.2f}</code>
🟢 صفقات مفتوحة: <code>{status['open_trades']}</code>
💥 انفجارات: <code>{len(explosions_found)}</code>

📋 <b>اختر أحد الخيارات:</b>
"""
    if message_id:
        edit_message_text(msg, chat_id, message_id, reply_markup)
    else:
        send_msg(msg, chat_id, reply_markup=reply_markup)

def show_open_trade_menu(chat_id, message_id=None):
    """عرض قائمة العملات لفتح صفقة"""
    if not explosions_found:
        keyboard = [[{'text': "🔍 مسح الانفجارات أولاً", 'callback_data': "SCAN_EXPLOSIONS"}]]
        keyboard.append([{'text': "🔙 رجوع", 'callback_data': "MAIN_MENU"}])
        reply_markup = {'inline_keyboard': keyboard}
        msg = "⚠️ <b>لا توجد انفجارات مكتشفة</b>\n\nقم بمسح السوق أولاً باستخدام زر المسح"
        if message_id:
            edit_message_text(msg, chat_id, message_id, reply_markup)
        else:
            send_msg(msg, chat_id, reply_markup=reply_markup)
        return
    
    keyboard = []
    for exp in explosions_found[:8]:
        explosion = exp['explosion']
        button_text = f"💥 {exp['symbol']} | درجة {explosion['score']} | صعود +{explosion['expected_rise']}%"
        keyboard.append([{'text': button_text, 'callback_data': f"BUY_{exp['symbol']}"}])
    
    keyboard.append([{'text': "🔄 تحديث القائمة", 'callback_data': "REFRESH_OPEN_MENU"}])
    keyboard.append([{'text': "🔙 رجوع للقائمة الرئيسية", 'callback_data': "MAIN_MENU"}])
    reply_markup = {'inline_keyboard': keyboard}
    
    msg = "🟢 <b>اختر العملة لفتح صفقة</b>\n\n"
    for i, exp in enumerate(explosions_found[:8], 1):
        explosion = exp['explosion']
        msg += f"{i}. <b>{exp['symbol']}</b>\n"
        msg += f"   💥 درجة الانفجار: {explosion['score']}/100\n"
        msg += f"   📈 صعود متوقع: +{explosion['expected_rise']}%\n"
        msg += f"   💰 السعر: ${exp['price']:.6f}\n\n"
    
    if message_id:
        edit_message_text(msg, chat_id, message_id, reply_markup)
    else:
        send_msg(msg, chat_id, reply_markup=reply_markup)

def show_close_trade_menu(chat_id, message_id=None):
    """عرض قائمة الصفقات المفتوحة لإغلاقها"""
    if not open_trades:
        keyboard = [[{'text': "🔙 رجوع", 'callback_data': "MAIN_MENU"}]]
        reply_markup = {'inline_keyboard': keyboard}
        msg = "⚠️ <b>لا توجد صفقات مفتوحة</b>"
        if message_id:
            edit_message_text(msg, chat_id, message_id, reply_markup)
        else:
            send_msg(msg, chat_id, reply_markup=reply_markup)
        return
    
    keyboard = []
    for symbol, trade in open_trades.items():
        current_price = get_price(symbol)
        if current_price > 0:
            pnl = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
            emoji = "🟢" if pnl >= 0 else "🔴"
            button_text = f"{emoji} {symbol} | {pnl:+.1f}% | دخل ${trade['entry_price']:.4f}"
            keyboard.append([{'text': button_text, 'callback_data': f"CLOSE_{symbol}"}])
    
    keyboard.append([{'text': "🔴 إغلاق جميع الصفقات", 'callback_data': "CLOSE_ALL_TRADES"}])
    keyboard.append([{'text': "🔄 تحديث", 'callback_data': "REFRESH_CLOSE_MENU"}])
    keyboard.append([{'text': "🔙 رجوع", 'callback_data': "MAIN_MENU"}])
    reply_markup = {'inline_keyboard': keyboard}
    
    msg = "🔴 <b>اختر الصفقة لإغلاقها</b>\n\n"
    total_pnl = 0
    for symbol, trade in open_trades.items():
        current_price = get_price(symbol)
        if current_price > 0:
            pnl = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
            pnl_amount = (current_price - trade['entry_price']) * trade['quantity']
            total_pnl += pnl_amount
            emoji = "🟢" if pnl >= 0 else "🔴"
            msg += f"{emoji} <b>{symbol}</b>: {pnl:+.1f}% (${pnl_amount:+.2f})\n"
            msg += f"   دخل: ${trade['entry_price']:.4f} | الحالي: ${current_price:.4f}\n\n"
    
    msg += f"💰 <b>إجمالي PnL المفتوح:</b> ${total_pnl:+.2f}"
    
    if message_id:
        edit_message_text(msg, chat_id, message_id, reply_markup)
    else:
        send_msg(msg, chat_id, reply_markup=reply_markup)

def show_confirmation_menu(chat_id, symbol, action, message_id=None):
    """عرض قائمة تأكيد للصفقة"""
    if action == "BUY":
        # البحث عن العملة
        found = None
        for exp in explosions_found:
            if exp['symbol'] == symbol:
                found = exp
                break
        
        if not found:
            send_msg(f"❌ العملة {symbol} غير موجودة", chat_id)
            return
        
        explosion = found['explosion']
        keyboard = [
            [{'text': "✅ تأكيد الشراء", 'callback_data': f"CONFIRM_BUY_{symbol}"}],
            [{'text': "❌ إلغاء", 'callback_data': "OPEN_TRADE_MENU"}]
        ]
        reply_markup = {'inline_keyboard': keyboard}
        
        msg = f"""
📊 <b>تأكيد فتح صفقة شراء</b>

┌ 📊 <b>{symbol}</b>
├ 💰 السعر: <code>${found['price']:.6f}</code>
├ 💥 درجة الانفجار: <code>{explosion['score']}/100</code>
├ 📈 الصعود المتوقع: <code>+{explosion['expected_rise']}%</code>
├ 💵 المبلغ: <code>${TRADE_AMOUNT}</code>
│
├ 🎯 الهدف: <code>+{PROFIT_TARGET}%</code>
├ 🛑 وقف الخسارة: <code>{STOP_LOSS}%</code>
│
└ ⏰ الوقت: {datetime.now().strftime('%H:%M:%S')}

✅ <b>هل تريد تأكيد الصفقة؟</b>
"""
        if message_id:
            edit_message_text(msg, chat_id, message_id, reply_markup)
        else:
            send_msg(msg, chat_id, reply_markup=reply_markup)
    
    elif action == "CLOSE":
        trade = open_trades.get(symbol)
        if not trade:
            send_msg(f"❌ الصفقة {symbol} غير موجودة", chat_id)
            return
        
        current_price = get_price(symbol)
        if current_price > 0:
            pnl = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
            pnl_amount = (current_price - trade['entry_price']) * trade['quantity']
            
            keyboard = [
                [{'text': "✅ تأكيد الإغلاق", 'callback_data': f"CONFIRM_CLOSE_{symbol}"}],
                [{'text': "❌ إلغاء", 'callback_data': "CLOSE_TRADE_MENU"}]
            ]
            reply_markup = {'inline_keyboard': keyboard}
            
            msg = f"""
📊 <b>تأكيد إغلاق صفقة {symbol}</b>

┌ 📊 <b>{symbol}</b>
├ 💰 سعر الدخول: <code>${trade['entry_price']:.6f}</code>
├ 💰 السعر الحالي: <code>${current_price:.6f}</code>
├ 📈 العائد الحالي: <code>{pnl:+.1f}%</code>
├ 💵 الربح/الخسارة: <code>${pnl_amount:+.2f}</code>
│
└ ⏰ الوقت: {datetime.now().strftime('%H:%M:%S')}

✅ <b>هل تريد تأكيد إغلاق الصفقة؟</b>
"""
            if message_id:
                edit_message_text(msg, chat_id, message_id, reply_markup)
            else:
                send_msg(msg, chat_id, reply_markup=reply_markup)

def edit_message_text(text, chat_id, message_id, reply_markup=None):
    """تعديل رسالة موجودة"""
    try:
        url = f'https://api.telegram.org/bot{TOKEN}/editMessageText'
        data = {'chat_id': chat_id, 'message_id': message_id, 'text': text, 'parse_mode': 'HTML'}
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        post_data = json.dumps(data).encode()
        req = urllib.request.Request(url, data=post_data, headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f"Edit error: {e}")
        return False
