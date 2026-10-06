import os, sqlite3, datetime as dt
import numpy as np
import pandas as pd
import yfinance as yf
import requests
DB=os.getenv('LAB_DB','/data/lab.db')
STRATEGIES=['SID','Trend-filtered SID','Trend-Pullback']
DEFAULT='AAPL,MSFT,NVDA,AMZN,GOOGL,META,SPY,QQQ,AZN.L,SHEL.L,HSBA.L,ULVR.L,VWRP.L'
def conn():
    os.makedirs(os.path.dirname(DB) or '.',exist_ok=True)
    c=sqlite3.connect(DB,timeout=30)
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS alerts (symbol TEXT, strategy TEXT, day TEXT, price REAL, stop REAL, target REAL, PRIMARY KEY(symbol,strategy,day))')
    c.execute('CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, strategy TEXT, entry_day TEXT, entry REAL, qty REAL, stop REAL, target REAL, exit_day TEXT, exit REAL, status TEXT)')
    c.commit();return c
def get_setting(k,default=''):
    with conn() as c:
        r=c.execute('SELECT value FROM settings WHERE key=?',(k,)).fetchone()
    return r[0] if r else default
def set_setting(k,v):
    with conn() as c:c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(k,str(v)))
def symbols():return list(dict.fromkeys(s.strip().upper() for s in get_setting('symbols',DEFAULT).split(',') if s.strip()))
def fetch(symbol,period='10y'):
    d=yf.download(symbol,period=period,interval='1d',auto_adjust=True,progress=False,threads=False,multi_level_index=False)
    if d is None or d.empty:raise ValueError(f'No price history for {symbol}')
    if isinstance(d.columns,pd.MultiIndex):d.columns=d.columns.get_level_values(0)
    d=d[['Open','High','Low','Close','Volume']].dropna(subset=['Open','High','Low','Close']).copy()
    d.index=pd.to_datetime(d.index).tz_localize(None) if d.index.tz is not None else pd.to_datetime(d.index)
    return d

def indicators(d):
    d=d.copy();c=d.Close;delta=c.diff();up=delta.clip(lower=0).ewm(alpha=1/14,adjust=False).mean();down=(-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean()
    rs=up/down.replace(0,np.nan);d['rsi']=100-100/(1+rs);d.loc[(down==0)&(up>0),'rsi']=100;d.loc[(up==0)&(down==0),'rsi']=50
    ema12=c.ewm(span=12,adjust=False).mean();ema26=c.ewm(span=26,adjust=False).mean();macd=ema12-ema26;d['hist']=macd-macd.ewm(span=9,adjust=False).mean()
    d['ma50']=c.rolling(50).mean();d['ma200']=c.rolling(200).mean()
    tr=pd.concat([(d.High-d.Low),(d.High-c.shift()).abs(),(d.Low-c.shift()).abs()],axis=1).max(axis=1)
    d['atr']=tr.rolling(14).mean();d['low5']=d.Low.shift(1).rolling(5).min()
    d['sid_arm']=(d.rsi<30).rolling(8,min_periods=1).max().shift(1).fillna(0).astype(bool)
    d['sid']=(d.sid_arm)&(d.rsi>d.rsi.shift(1))&(d.rsi.shift(1)<=35)&(d['hist']>d['hist'].shift(1))
    d['trend']=(d.Close>d.ma50)&(d.ma50>d.ma200)
    d['Trend-filtered SID']=d.sid&d.trend
    d['Trend-Pullback']=(d.trend)&(d.rsi.shift(1).between(35,45))&(d.rsi>d.rsi.shift(1))&(d.Close>d.High.shift(1))&(d['hist']>d['hist'].shift(1))
    d['SID']=d.sid
    return d

def signal_row(d,strategy,i):
    row=d.iloc[i];stop=min(float(row.low5),float(row.Close-1.5*row.atr))
    if not np.isfinite(stop) or stop>=row.Close:return None
    risk=float(row.Close-stop)
    return {'day':str(d.index[i].date()),'price':float(row.Close),'stop':stop,'target':float(row.Close+2*risk),'rsi':float(row.rsi)}

def backtest(d,strategy,initial=10000,risk_pct=.5,fee_bps=10,slip_bps=5,max_hold=20):
    d=indicators(d);cash=float(initial);equity=[];trades=[];pos=None;cost=(fee_bps+slip_bps)/10000
    # Signals from previous close are entered at next open; stops and targets checked from entry day onward.
    for i in range(201,len(d)):
        day=str(d.index[i].date());row=d.iloc[i]
        if pos:
            out=None;reason=''
            if row.Low<=pos['stop']:
                out=min(float(row.Open),pos['stop'])*(1-cost);reason='stop'
            elif row.High>=pos['target']:
                out=pos['target']*(1-cost);reason='target'
            elif strategy in ('SID','Trend-filtered SID') and row.rsi>=50:
                out=float(row.Close)*(1-cost);reason='RSI 50'
            elif i-pos['index']>=max_hold:
                out=float(row.Close)*(1-cost);reason='time'
            if out is not None:
                cash+=pos['qty']*out
                trades.append({'entry_day':pos['day'],'exit_day':day,'entry':pos['entry'],'exit':out,'qty':pos['qty'],'pnl':pos['qty']*(out-pos['entry']),'reason':reason})
                pos=None
        if pos is None and bool(d[strategy].iloc[i-1]):
            sig=signal_row(d,strategy,i-1)
            if sig:
                entry=float(row.Open)*(1+cost);stop=sig['stop'];target=entry+2*(entry-stop)
                if entry>stop:
                    qty=min(cash/entry,(cash*risk_pct/100)/(entry-stop))
                    if qty>0:
                        cash-=qty*entry;pos={'index':i,'day':day,'entry':entry,'stop':stop,'target':target,'qty':qty}
                        # Conservative same-day stop handling; no target fill on entry bar.
                        if row.Low<=stop:
                            out=min(float(row.Open),stop)*(1-cost);cash+=qty*out
                            trades.append({'entry_day':day,'exit_day':day,'entry':entry,'exit':out,'qty':qty,'pnl':qty*(out-entry),'reason':'entry-day stop'});pos=None
        equity.append({'day':day,'equity':cash+(pos['qty']*float(row.Close) if pos else 0)})
    if pos:
        out=float(d.Close.iloc[-1])*(1-cost);cash+=pos['qty']*out
        trades.append({'entry_day':pos['day'],'exit_day':str(d.index[-1].date()),'entry':pos['entry'],'exit':out,'qty':pos['qty'],'pnl':pos['qty']*(out-pos['entry']),'reason':'mark-to-market'})
        equity[-1]['equity']=cash
    eq=pd.DataFrame(equity);t=pd.DataFrame(trades)
    if eq.empty:return {},eq,t
    peak=eq.equity.cummax();drawdown=(eq.equity/peak-1).min()*100
    years=max((pd.Timestamp(eq.day.iloc[-1])-pd.Timestamp(eq.day.iloc[0])).days/365.25,1/365.25)
    cagr=((eq.equity.iloc[-1]/initial)**(1/years)-1)*100
    gains=t.pnl[t.pnl>0].sum() if not t.empty else 0;losses=-t.pnl[t.pnl<0].sum() if not t.empty else 0
    stats={'Total return %':round((eq.equity.iloc[-1]/initial-1)*100,2),'CAGR %':round(cagr,2),'Max drawdown %':round(drawdown,2),'Trades':len(t),'Win rate %':round(100*(t.pnl>0).mean(),2) if len(t) else 0,'Profit factor':round(gains/losses,2) if losses else (None if gains==0 else float('inf'))}
    return stats,eq,t

def send_telegram(message):
    token=os.getenv('TELEGRAM_BOT_TOKEN','');chat=os.getenv('TELEGRAM_CHAT_ID','')
    if not token or not chat:return False,'Telegram credentials missing'
    try:
        r=requests.post(f'https://api.telegram.org/bot{token}/sendMessage',json={'chat_id':chat,'text':message},timeout=15)
        r.raise_for_status();return True,'Sent'
    except Exception as e:return False,str(e)

def scan():
    found=[];errors=[]
    for symbol in symbols():
        try:
            d=indicators(fetch(symbol,'2y'))
            if len(d)<210:continue
            i=len(d)-1;row=d.iloc[i]
            for strategy in STRATEGIES:
                if not bool(row[strategy]):continue
                sig=signal_row(d,strategy,i)
                if not sig:continue
                with conn() as c:
                    exists=c.execute('SELECT 1 FROM alerts WHERE symbol=? AND strategy=? AND day=?',(symbol,strategy,sig['day'])).fetchone()
                    if exists:continue
                    c.execute('INSERT INTO alerts VALUES (?,?,?,?,?,?)',(symbol,strategy,sig['day'],sig['price'],sig['stop'],sig['target']))
                found.append((symbol,strategy,sig))
        except Exception as e:errors.append(f'{symbol}: {e}')
    for symbol,strategy,sig in found:
        send_telegram(f'📈 Trading Lab signal (daily close)\n{symbol} — {strategy}\nDate: {sig["day"]}\nClose: {sig["price"]:.2f}\nIndicative stop: {sig["stop"]:.2f}\nIndicative 2R target: {sig["target"]:.2f}\nRSI: {sig["rsi"]:.1f}\nReview before trading; not an executed order.')
    return found,errors

def paper_open(symbol,strategy,entry,stop,target,account=10000,risk=.5):
    if not (0<stop<entry<target):raise ValueError('Require 0 < stop < entry < target')
    with conn() as c:
        open_positions=c.execute("SELECT COALESCE(SUM(qty*entry),0) FROM trades WHERE status='OPEN'").fetchone()[0]
        closed=c.execute("SELECT COALESCE(SUM(qty*(exit-entry)),0) FROM trades WHERE status='CLOSED'").fetchone()[0]
        equity=account+closed
        available=equity-open_positions
        qty=min(max(0,available)/entry,max(0,equity)*risk/100/(entry-stop))
        if qty<=0:raise ValueError('Insufficient paper buying power')
        c.execute('INSERT INTO trades(symbol,strategy,entry_day,entry,qty,stop,target,status) VALUES(?,?,?,?,?,?,?,?)',(symbol,strategy,dt.date.today().isoformat(),entry,qty,stop,target,'OPEN'))
    return qty

def paper_close(id,price):
    if price<=0:raise ValueError('Exit price must be positive')
    with conn() as c:c.execute("UPDATE trades SET exit_day=?,exit=?,status='CLOSED' WHERE id=? AND status='OPEN'",(dt.date.today().isoformat(),price,id))
