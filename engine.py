import os, sqlite3, datetime as dt, json, copy, itertools
import numpy as np
import pandas as pd
import yfinance as yf
import requests
DB=os.getenv('LAB_DB','/data/lab.db')
DEFAULT='AAPL,MSFT,NVDA,AMZN,GOOGL,META,SPY,QQQ,AZN.L,SHEL.L,HSBA.L,ULVR.L,VWRP.L'
TEMPLATES={
'SID':{'description':'Classic RSI oversold recovery confirmed by improving MACD histogram.','params':{'rsi_period':14,'rsi_oversold':30,'rsi_recovery_max':35,'arm_days':8,'macd_fast':12,'macd_slow':26,'macd_signal':9,'exit_rsi':50,'atr_period':14,'atr_stop_mult':1.5,'swing_lookback':5,'reward_risk':2.0,'max_hold':20},'rules':{'all':[{'field':'sid_armed','op':'==','value':1},{'field':'rsi','op':'>','compare':'rsi_prev'},{'field':'rsi_prev','op':'<=','param':'rsi_recovery_max'},{'field':'hist','op':'>','compare':'hist_prev'}]}},
'Trend-filtered SID':{'description':'SID plus a positive 50/200-day trend filter.','params':{'rsi_period':14,'rsi_oversold':30,'rsi_recovery_max':35,'arm_days':8,'macd_fast':12,'macd_slow':26,'macd_signal':9,'ma_fast':50,'ma_slow':200,'exit_rsi':50,'atr_period':14,'atr_stop_mult':1.5,'swing_lookback':5,'reward_risk':2.0,'max_hold':20},'rules':{'all':[{'field':'sid_armed','op':'==','value':1},{'field':'rsi','op':'>','compare':'rsi_prev'},{'field':'rsi_prev','op':'<=','param':'rsi_recovery_max'},{'field':'hist','op':'>','compare':'hist_prev'},{'field':'close','op':'>','compare':'ma_fast'},{'field':'ma_fast','op':'>','compare':'ma_slow'}]}},
'Trend-Pullback':{'description':'Uptrend pullback with RSI recovery, previous-high breakout and improving MACD momentum.','params':{'rsi_period':14,'pullback_rsi_min':35,'pullback_rsi_max':45,'macd_fast':12,'macd_slow':26,'macd_signal':9,'ma_fast':50,'ma_slow':200,'atr_period':14,'atr_stop_mult':1.5,'swing_lookback':5,'reward_risk':2.0,'max_hold':20},'rules':{'all':[{'field':'close','op':'>','compare':'ma_fast'},{'field':'ma_fast','op':'>','compare':'ma_slow'},{'field':'rsi_prev','op':'>=','param':'pullback_rsi_min'},{'field':'rsi_prev','op':'<=','param':'pullback_rsi_max'},{'field':'rsi','op':'>','compare':'rsi_prev'},{'field':'close','op':'>','compare':'high_prev'},{'field':'hist','op':'>','compare':'hist_prev'}]}}
}
FIELDS=['close','open','high','low','volume','rsi','rsi_prev','hist','hist_prev','ma_fast','ma_slow','high_prev','volume_ma20','atr','sid_armed']
OPS=['>','>=','<','<=','==']
def conn():
    os.makedirs(os.path.dirname(DB) or '.',exist_ok=True); c=sqlite3.connect(DB,timeout=30); c.execute('PRAGMA journal_mode=WAL')
    c.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS alerts (symbol TEXT, strategy TEXT, day TEXT, price REAL, stop REAL, target REAL, PRIMARY KEY(symbol,strategy,day))')
    c.execute("CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, strategy TEXT, entry_day TEXT, entry REAL, qty REAL, stop REAL, target REAL, exit_day TEXT, exit REAL, status TEXT, direction TEXT DEFAULT 'LONG')")
    try:c.execute("ALTER TABLE trades ADD COLUMN direction TEXT DEFAULT 'LONG'")
    except sqlite3.OperationalError:pass
    c.execute('CREATE TABLE IF NOT EXISTS strategies (name TEXT PRIMARY KEY, description TEXT, config TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0, protected INTEGER NOT NULL DEFAULT 0, created_at TEXT, updated_at TEXT)')
    seeded=c.execute("SELECT value FROM settings WHERE key='templates_seeded'").fetchone()
    if not seeded:
        for name,cfg in TEMPLATES.items():
            c.execute('INSERT OR IGNORE INTO strategies(name,description,config,enabled,protected,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(name,cfg['description'],json.dumps(cfg),1,0,dt.datetime.utcnow().isoformat(),dt.datetime.utcnow().isoformat()))
        c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('templates_seeded','1')")
    c.execute('UPDATE strategies SET protected=0')
    c.commit(); return c
def get_setting(k,default=''):
    with conn() as c:r=c.execute('SELECT value FROM settings WHERE key=?',(k,)).fetchone()
    return r[0] if r else default
def set_setting(k,v):
    with conn() as c:c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(k,str(v)))
def symbols():
    raw=get_setting('symbols',DEFAULT).replace('\n',',').replace(';',',')
    return list(dict.fromkeys(s.strip().upper() for s in raw.split(',') if s.strip()))

def ticker_search(query):
    query=query.strip()
    if not query:return []
    try:
        srch=yf.Search(query,max_results=12,news_count=0)
        rows=[]
        for q in getattr(srch,'quotes',[]) or []:
            sym=q.get('symbol'); name=q.get('shortname') or q.get('longname') or q.get('name') or ''
            exch=q.get('exchange') or q.get('exchDisp') or ''; typ=q.get('quoteType') or q.get('typeDisp') or ''
            if sym: rows.append({'Ticker':sym,'Name':name,'Exchange':exch,'Type':typ})
        return rows
    except Exception:return []
def list_strategies(enabled_only=False):
    q='SELECT name,description,config,enabled,protected,created_at,updated_at FROM strategies'+(' WHERE enabled=1' if enabled_only else '')+' ORDER BY protected DESC,name'
    with conn() as c: rows=c.execute(q).fetchall()
    return [{'name':r[0],'description':r[1],'config':json.loads(r[2]),'enabled':bool(r[3]),'protected':bool(r[4]),'created_at':r[5],'updated_at':r[6]} for r in rows]
def get_strategy(name):
    with conn() as c:r=c.execute('SELECT name,description,config,enabled,protected FROM strategies WHERE name=?',(name,)).fetchone()
    if not r: raise KeyError(name)
    return {'name':r[0],'description':r[1],'config':json.loads(r[2]),'enabled':bool(r[3]),'protected':bool(r[4])}
def save_strategy(name,description,config,enabled=False,overwrite=False):
    name=name.strip()
    if not name:raise ValueError('Strategy name is required')
    validate_config(config)
    now=dt.datetime.utcnow().isoformat()
    with conn() as c:
        old=c.execute('SELECT protected FROM strategies WHERE name=?',(name,)).fetchone()
        if old and old[0]:raise ValueError('Built-in templates are protected. Clone them first.')
        if old and not overwrite:raise ValueError('Strategy name already exists')
        c.execute('INSERT OR REPLACE INTO strategies(name,description,config,enabled,protected,created_at,updated_at) VALUES(?,?,?,?,0,COALESCE((SELECT created_at FROM strategies WHERE name=?),?),?)',(name,description,json.dumps(config),int(enabled),name,now,now))
def clone_strategy(source,new_name):
    s=get_strategy(source); save_strategy(new_name,'Clone of '+source,copy.deepcopy(s['config']),False,False)
def delete_strategy(name):
    with conn() as c:
        c.execute('DELETE FROM strategies WHERE name=?',(name,))
def set_strategy_enabled(name,enabled):
    with conn() as c:c.execute('UPDATE strategies SET enabled=?,updated_at=? WHERE name=?',(int(enabled),dt.datetime.utcnow().isoformat(),name))
def validate_config(cfg):
    if not isinstance(cfg,dict) or 'params' not in cfg or 'rules' not in cfg:raise ValueError('Config needs params and rules')
    rules=cfg['rules'].get('all',[])
    if not rules:raise ValueError('At least one entry rule is required')
    for r in rules:
        if r.get('field') not in FIELDS or r.get('op') not in OPS:raise ValueError('Invalid rule field/operator')
        if not any(k in r for k in ('value','param','compare')):raise ValueError('Each rule needs value, param or compare')
def fetch(symbol,period='10y',interval='1d'):
    # Yahoo limits intraday history; use a compatible period automatically.
    if interval=='1h' and period in ('5y','10y','max'): period='2y'
    d=yf.download(symbol,period=period,interval=interval,auto_adjust=True,progress=False,threads=False,multi_level_index=False)
    if d is None or d.empty:raise ValueError(f'No price history for {symbol}')
    if isinstance(d.columns,pd.MultiIndex):d.columns=d.columns.get_level_values(0)
    d=d[['Open','High','Low','Close','Volume']].dropna(subset=['Open','High','Low','Close']).copy(); d.index=pd.to_datetime(d.index).tz_localize(None) if d.index.tz is not None else pd.to_datetime(d.index); return d
def indicators(d,cfg):
    p=cfg['params']; d=d.copy(); c=d.Close; rp=int(p.get('rsi_period',14)); delta=c.diff(); up=delta.clip(lower=0).ewm(alpha=1/rp,adjust=False).mean(); down=(-delta.clip(upper=0)).ewm(alpha=1/rp,adjust=False).mean(); rs=up/down.replace(0,np.nan); d['rsi']=100-100/(1+rs); d.loc[(down==0)&(up>0),'rsi']=100; d.loc[(up==0)&(down==0),'rsi']=50
    ef=c.ewm(span=int(p.get('macd_fast',12)),adjust=False).mean(); es=c.ewm(span=int(p.get('macd_slow',26)),adjust=False).mean(); macd=ef-es; d['hist']=macd-macd.ewm(span=int(p.get('macd_signal',9)),adjust=False).mean()
    d['ma_fast']=c.rolling(int(p.get('ma_fast',50))).mean(); d['ma_slow']=c.rolling(int(p.get('ma_slow',200))).mean(); tr=pd.concat([(d.High-d.Low),(d.High-c.shift()).abs(),(d.Low-c.shift()).abs()],axis=1).max(axis=1); d['atr']=tr.rolling(int(p.get('atr_period',14))).mean(); d['low_swing']=d.Low.shift(1).rolling(int(p.get('swing_lookback',5))).min(); d['rsi_prev']=d.rsi.shift(1); d['hist_prev']=d['hist'].shift(1); d['high_prev']=d.High.shift(1); d['volume_ma20']=d.Volume.rolling(20).mean(); d['close']=d.Close; d['open']=d.Open; d['high']=d.High; d['low']=d.Low; d['volume']=d.Volume
    arm=int(p.get('arm_days',8)); oversold=float(p.get('rsi_oversold',30)); d['sid_armed']=(d.rsi<oversold).rolling(arm,min_periods=1).max().shift(1).fillna(0).astype(int); return d
def evaluate_rules(d,cfg):
    out=pd.Series(True,index=d.index)
    for r in cfg['rules']['all']:
        a=d[r['field']]; b=d[r['compare']] if 'compare' in r else (cfg['params'][r['param']] if 'param' in r else r['value']); op=r['op']
        cond={'>':a>b,'>=':a>=b,'<':a<b,'<=':a<=b,'==':a==b}[op]; out=out & cond.fillna(False)
    return out
def signal_row(d,cfg,i):
    row=d.iloc[i]; p=cfg['params']; stop=min(float(row.low_swing),float(row.Close-float(p.get('atr_stop_mult',1.5))*row.atr))
    if not np.isfinite(stop) or stop>=row.Close:return None
    risk=float(row.Close-stop); rr=float(p.get('reward_risk',2)); return {'day':str(d.index[i].date()),'price':float(row.Close),'stop':stop,'target':float(row.Close+rr*risk),'rsi':float(row.rsi)}
def backtest(d,strategy,initial=10000,risk_pct=.5,fee_bps=10,slip_bps=5,max_hold=None):
    s=get_strategy(strategy) if isinstance(strategy,str) else {'name':'Ad hoc','config':strategy}; cfg=s['config']; d=indicators(d,cfg); signals=evaluate_rules(d,cfg); cash=float(initial); equity=[]; trades=[]; pos=None; cost=(fee_bps+slip_bps)/10000; p=cfg['params']; hold=int(max_hold or p.get('max_hold',20)); warmup=max(210,int(p.get('ma_slow',200))+5)
    for i in range(warmup,len(d)):
        day=str(d.index[i].date()); row=d.iloc[i]
        if pos:
            out=None;reason=''
            if row.Low<=pos['stop']:out=min(float(row.Open),pos['stop'])*(1-cost);reason='stop'
            elif row.High>=pos['target']:out=pos['target']*(1-cost);reason='target'
            elif p.get('exit_rsi') is not None and row.rsi>=float(p['exit_rsi']):out=float(row.Close)*(1-cost);reason='RSI exit'
            elif i-pos['index']>=hold:out=float(row.Close)*(1-cost);reason='time'
            if out is not None:cash+=pos['qty']*out;trades.append({'entry_day':pos['day'],'exit_day':day,'entry':pos['entry'],'exit':out,'qty':pos['qty'],'pnl':pos['qty']*(out-pos['entry']),'reason':reason});pos=None
        if pos is None and bool(signals.iloc[i-1]):
            sig=signal_row(d,cfg,i-1)
            if sig:
                entry=float(row.Open)*(1+cost);stop=sig['stop'];rr=float(p.get('reward_risk',2));target=entry+rr*(entry-stop)
                if entry>stop:
                    qty=min(cash/entry,(cash*risk_pct/100)/(entry-stop))
                    if qty>0:
                        cash-=qty*entry;pos={'index':i,'day':day,'entry':entry,'stop':stop,'target':target,'qty':qty}
                        if row.Low<=stop:out=min(float(row.Open),stop)*(1-cost);cash+=qty*out;trades.append({'entry_day':day,'exit_day':day,'entry':entry,'exit':out,'qty':qty,'pnl':qty*(out-entry),'reason':'entry-day stop'});pos=None
        equity.append({'day':day,'equity':cash+(pos['qty']*float(row.Close) if pos else 0)})
    if pos and equity:
        out=float(d.Close.iloc[-1])*(1-cost);cash+=pos['qty']*out;trades.append({'entry_day':pos['day'],'exit_day':str(d.index[-1].date()),'entry':pos['entry'],'exit':out,'qty':pos['qty'],'pnl':pos['qty']*(out-pos['entry']),'reason':'mark-to-market'});equity[-1]['equity']=cash
    eq=pd.DataFrame(equity);t=pd.DataFrame(trades)
    if eq.empty:return {},eq,t
    peak=eq.equity.cummax();dd=(eq.equity/peak-1).min()*100; years=max((pd.Timestamp(eq.day.iloc[-1])-pd.Timestamp(eq.day.iloc[0])).days/365.25,1/365.25); cagr=((eq.equity.iloc[-1]/initial)**(1/years)-1)*100; gains=t.pnl[t.pnl>0].sum() if not t.empty else 0;losses=-t.pnl[t.pnl<0].sum() if not t.empty else 0
    daily=eq.equity.pct_change().dropna(); sharpe=(np.sqrt(252)*daily.mean()/daily.std()) if len(daily)>2 and daily.std()>0 else 0; avgwin=t.pnl[t.pnl>0].mean() if not t.empty and (t.pnl>0).any() else 0; avgloss=t.pnl[t.pnl<0].mean() if not t.empty and (t.pnl<0).any() else 0
    stats={'Total return %':round((eq.equity.iloc[-1]/initial-1)*100,2),'CAGR %':round(cagr,2),'Max drawdown %':round(dd,2),'Trades':len(t),'Win rate %':round(100*(t.pnl>0).mean(),2) if len(t) else 0,'Profit factor':round(gains/losses,2) if losses else (None if gains==0 else float('inf')),'Sharpe':round(float(sharpe),2),'Avg win':round(float(avgwin),2),'Avg loss':round(float(avgloss),2)}; return stats,eq,t
def optimise(d,strategy,param_grid,risk_pct=.5,fee_bps=10,slip_bps=5,limit=200):
    base=get_strategy(strategy)['config']; keys=list(param_grid); combos=list(itertools.product(*[param_grid[k] for k in keys]))[:limit]; rows=[]
    for vals in combos:
        cfg=copy.deepcopy(base)
        for k,v in zip(keys,vals):cfg['params'][k]=v
        try:
            stats,_,_=backtest(d,cfg,risk_pct=risk_pct,fee_bps=fee_bps,slip_bps=slip_bps); row={k:v for k,v in zip(keys,vals)};row.update(stats);rows.append(row)
        except Exception:pass
    return pd.DataFrame(rows).sort_values(['Sharpe','CAGR %'],ascending=False) if rows else pd.DataFrame()
def send_telegram(message):
    token=os.getenv('TELEGRAM_BOT_TOKEN','');chat=os.getenv('TELEGRAM_CHAT_ID','')
    if not token or not chat:return False,'Telegram credentials missing'
    try:r=requests.post(f'https://api.telegram.org/bot{token}/sendMessage',json={'chat_id':chat,'text':message},timeout=15);r.raise_for_status();return True,'Sent'
    except Exception as e:return False,str(e)
def scan():
    found=[];errors=[]; strategies=list_strategies(True)
    for symbol in symbols():
        try:
            raw=fetch(symbol,'2y')
            for s in strategies:
                d=indicators(raw,s['config']); signals=evaluate_rules(d,s['config']); i=len(d)-1
                if i<1 or not bool(signals.iloc[i]):continue
                sig=signal_row(d,s['config'],i)
                if not sig:continue
                with conn() as c:
                    if c.execute('SELECT 1 FROM alerts WHERE symbol=? AND strategy=? AND day=?',(symbol,s['name'],sig['day'])).fetchone():continue
                    c.execute('INSERT INTO alerts VALUES (?,?,?,?,?,?)',(symbol,s['name'],sig['day'],sig['price'],sig['stop'],sig['target']))
                found.append((symbol,s['name'],sig))
        except Exception as e:errors.append(f'{symbol}: {e}')
    for symbol,strategy,sig in found:send_telegram(f'📈 Trading Lab signal (daily close)\n{symbol} — {strategy}\nDate: {sig["day"]}\nClose: {sig["price"]:.2f}\nIndicative stop: {sig["stop"]:.2f}\nTarget: {sig["target"]:.2f}\nRSI: {sig["rsi"]:.1f}\nReview before trading; not an executed order.')
    return found,errors
def paper_open(symbol,strategy,entry,stop,target,account=10000,risk=.5):
    if not (0<stop<entry<target):raise ValueError('Require 0 < stop < entry < target')
    with conn() as c:
        open_positions=c.execute("SELECT COALESCE(SUM(qty*entry),0) FROM trades WHERE status='OPEN'").fetchone()[0];closed=c.execute("SELECT COALESCE(SUM(qty*(exit-entry)),0) FROM trades WHERE status='CLOSED'").fetchone()[0];equity=account+closed;available=equity-open_positions;qty=min(max(0,available)/entry,max(0,equity)*risk/100/(entry-stop))
        if qty<=0:raise ValueError('Insufficient paper buying power')
        c.execute('INSERT INTO trades(symbol,strategy,entry_day,entry,qty,stop,target,status) VALUES(?,?,?,?,?,?,?,?)',(symbol,strategy,dt.date.today().isoformat(),entry,qty,stop,target,'OPEN'))
    return qty
def paper_close(id,price):
    if price<=0:raise ValueError('Exit price must be positive')
    with conn() as c:c.execute("UPDATE trades SET exit_day=?,exit=?,status='CLOSED' WHERE id=? AND status='OPEN'",(dt.date.today().isoformat(),price,id))


def currency_info():
    code=get_setting('currency','GBP'); symbols={'GBP':'£','USD':'$','EUR':'€'}
    return code,symbols.get(code,code+' ')

def live_quotes(tickers):
    out={}
    for sym in sorted(set(tickers)):
        try:
            d=fetch(sym,'5d','1d'); out[sym]={'price':float(d.Close.iloc[-1]),'asof':str(d.index[-1])}
        except Exception as e:out[sym]={'error':str(e)}
    return out

def paper_open_v3(symbol,strategy,entry,stop,target,direction='LONG',account=10000,risk=.5):
    direction=direction.upper()
    if direction=='LONG' and not (0<stop<entry<target):raise ValueError('For a Buy/Long trade: Stop < Entry < Target')
    if direction=='SHORT' and not (0<target<entry<stop):raise ValueError('For a Sell/Short trade: Target < Entry < Stop')
    risk_per_unit=abs(entry-stop)
    with conn() as c:
        closed=c.execute("SELECT COALESCE(SUM(CASE WHEN direction='SHORT' THEN qty*(entry-exit) ELSE qty*(exit-entry) END),0) FROM trades WHERE status='CLOSED'").fetchone()[0]; equity=account+closed
        qty=max(0,equity)*risk/100/risk_per_unit
        if qty<=0:raise ValueError('Insufficient paper buying power')
        c.execute('INSERT INTO trades(symbol,strategy,entry_day,entry,qty,stop,target,status,direction) VALUES(?,?,?,?,?,?,?,?,?)',(symbol,strategy,dt.date.today().isoformat(),entry,qty,stop,target,'OPEN',direction))
    return qty

def backtest_v3(d,strategy,initial=10000,risk_pct=.5,commission=1.5,slippage_pct=.05,max_hold=None):
    s=get_strategy(strategy) if isinstance(strategy,str) else {'name':'Ad hoc','config':strategy}; cfg=s['config']; direction=cfg.get('direction','LONG').upper(); d=indicators(d,cfg); d['high_swing']=d.High.shift(1).rolling(int(cfg['params'].get('swing_lookback',5))).max(); signals=evaluate_rules(d,cfg); cash=float(initial); equity=[]; trades=[]; pos=None; p=cfg['params']; hold=int(max_hold or p.get('max_hold',20)); warmup=max(60,int(p.get('ma_slow',50))+5); slip=slippage_pct/100
    for i in range(warmup,len(d)):
        day=str(d.index[i].date()); row=d.iloc[i]
        if pos:
            out=None; reason=''
            if direction=='LONG':
                if row.Low<=pos['stop']:out=min(float(row.Open),pos['stop'])*(1-slip);reason='Stop loss'
                elif row.High>=pos['target']:out=pos['target']*(1-slip);reason='Profit target'
            else:
                if row.High>=pos['stop']:out=max(float(row.Open),pos['stop'])*(1+slip);reason='Stop loss'
                elif row.Low<=pos['target']:out=pos['target']*(1+slip);reason='Profit target'
            if out is None and i-pos['index']>=hold:out=float(row.Close)*(1-slip if direction=='LONG' else 1+slip);reason='Maximum holding time'
            if out is not None:
                pnl=pos['qty']*((out-pos['entry']) if direction=='LONG' else (pos['entry']-out))-commission; cash+=pnl; trades.append({'Direction':direction,'Entry date':pos['day'],'Exit date':day,'Entry':pos['entry'],'Exit':out,'Units':pos['qty'],'Profit/Loss':pnl,'Exit reason':reason});pos=None
        if pos is None and i>0 and bool(signals.iloc[i-1]):
            prev=d.iloc[i-1]; entry=float(row.Open)*(1+slip if direction=='LONG' else 1-slip); atr=float(prev.atr); look=int(p.get('swing_lookback',5)); rr=float(p.get('reward_risk',2)); mult=float(p.get('atr_stop_mult',1.5))
            if direction=='LONG': stop=min(float(prev.low_swing),entry-mult*atr); target=entry+rr*(entry-stop); riskunit=entry-stop
            else: stop=max(float(prev.high_swing),entry+mult*atr); target=entry-rr*(stop-entry); riskunit=stop-entry
            if np.isfinite(riskunit) and riskunit>0:
                qty=max(0,(cash*risk_pct/100-commission)/riskunit); pos={'index':i,'day':day,'entry':entry,'stop':stop,'target':target,'qty':qty}; cash-=commission
        mark=0 if not pos else pos['qty']*((float(row.Close)-pos['entry']) if direction=='LONG' else (pos['entry']-float(row.Close))); equity.append({'day':day,'equity':cash+mark})
    eq=pd.DataFrame(equity); t=pd.DataFrame(trades)
    if eq.empty:return {},eq,t
    peak=eq.equity.cummax(); dd=(eq.equity/peak-1).min()*100; years=max((pd.Timestamp(eq.day.iloc[-1])-pd.Timestamp(eq.day.iloc[0])).days/365.25,1/365.25); cagr=((eq.equity.iloc[-1]/initial)**(1/years)-1)*100; pnl=t['Profit/Loss'] if not t.empty else pd.Series(dtype=float); gains=pnl[pnl>0].sum(); losses=-pnl[pnl<0].sum(); daily=eq.equity.pct_change().dropna(); sharpe=np.sqrt(252)*daily.mean()/daily.std() if len(daily)>2 and daily.std()>0 else 0
    return {'Total return %':round((eq.equity.iloc[-1]/initial-1)*100,2),'Annualised return %':round(cagr,2),'Worst drawdown %':round(dd,2),'Trades':len(t),'Winning trades %':round(100*(pnl>0).mean(),1) if len(pnl) else 0,'Profit factor':round(gains/losses,2) if losses else None,'Risk-adjusted score':round(float(sharpe),2)},eq,t

def optimise_v3(d,strategy,param_grid,risk_pct=.5,commission=1.5,slippage_pct=.05,limit=200):
    base=get_strategy(strategy)['config']; keys=list(param_grid); rows=[]
    for vals in list(itertools.product(*[param_grid[k] for k in keys]))[:limit]:
        cfg=copy.deepcopy(base)
        for k,v in zip(keys,vals):cfg['params'][k]=v
        try:
            stats,_,_=backtest_v3(d,cfg,risk_pct=risk_pct,commission=commission,slippage_pct=slippage_pct); row={k:v for k,v in zip(keys,vals)};row.update(stats);rows.append(row)
        except Exception:pass
    return pd.DataFrame(rows).sort_values(['Risk-adjusted score','Annualised return %'],ascending=False) if rows else pd.DataFrame()

# ---- v5 Strategy Library / guided strategy engine ----
V5_LIBRARY = {
 'SID': {'description':'Buy after RSI has been oversold and momentum starts recovering.','category':'Mean Reversion','direction':'LONG','timeframe':'Daily','params':{'rsi_period':14,'rsi_low':30,'rsi_high':70,'rsi_exit_long':50,'rsi_exit_short':50,'macd_fast':12,'macd_slow':26,'macd_signal':9,'ma_fast':50,'ma_slow':200,'atr_period':14,'atr_stop_mult':1.5,'swing_lookback':5,'reward_risk':2.0,'max_hold':20},'recipe':'RSI_REVERSAL','use_trend':False,'use_macd':True},
 'Trend SID': {'description':'SID-style RSI recovery, but only in the direction of the wider trend.','category':'Mean Reversion','direction':'BOTH','timeframe':'Daily','params':{'rsi_period':14,'rsi_low':30,'rsi_high':70,'rsi_exit_long':50,'rsi_exit_short':50,'macd_fast':12,'macd_slow':26,'macd_signal':9,'ma_fast':50,'ma_slow':200,'atr_period':14,'atr_stop_mult':1.5,'swing_lookback':5,'reward_risk':2.0,'max_hold':20},'recipe':'RSI_REVERSAL','use_trend':True,'use_macd':True},
 'RSI Reversal': {'description':'Buy oversold recoveries and/or short overbought reversals.','category':'Mean Reversion','direction':'BOTH','timeframe':'Daily','params':{'rsi_period':14,'rsi_low':30,'rsi_high':70,'rsi_exit_long':55,'rsi_exit_short':45,'macd_fast':12,'macd_slow':26,'macd_signal':9,'ma_fast':50,'ma_slow':200,'atr_period':14,'atr_stop_mult':1.5,'swing_lookback':5,'reward_risk':2.0,'max_hold':15},'recipe':'RSI_REVERSAL','use_trend':False,'use_macd':False},
 'Moving Average Trend': {'description':'Follow established trends when the faster moving average is on the correct side of the slower average.','category':'Trend','direction':'BOTH','timeframe':'Daily','params':{'rsi_period':14,'rsi_low':40,'rsi_high':60,'macd_fast':12,'macd_slow':26,'macd_signal':9,'ma_fast':50,'ma_slow':200,'atr_period':14,'atr_stop_mult':2.0,'swing_lookback':10,'reward_risk':2.5,'max_hold':40},'recipe':'MA_TREND','use_trend':True,'use_macd':False},
 'MACD Momentum': {'description':'Enter when MACD momentum crosses in the direction of the trade, optionally with a trend filter.','category':'Momentum','direction':'BOTH','timeframe':'Daily','params':{'rsi_period':14,'rsi_low':35,'rsi_high':65,'macd_fast':12,'macd_slow':26,'macd_signal':9,'ma_fast':50,'ma_slow':200,'atr_period':14,'atr_stop_mult':1.8,'swing_lookback':7,'reward_risk':2.0,'max_hold':25},'recipe':'MACD_MOMENTUM','use_trend':True,'use_macd':True},
 'Trend Pullback': {'description':'Join an existing trend after RSI pulls back and then turns back with the trend.','category':'Trend','direction':'BOTH','timeframe':'Daily','params':{'rsi_period':14,'rsi_low':40,'rsi_high':60,'macd_fast':12,'macd_slow':26,'macd_signal':9,'ma_fast':50,'ma_slow':200,'atr_period':14,'atr_stop_mult':1.5,'swing_lookback':5,'reward_risk':2.0,'max_hold':20},'recipe':'TREND_PULLBACK','use_trend':True,'use_macd':True},
 '20-Day Breakout': {'description':'Buy new 20-bar highs or short new 20-bar lows in the direction of the broader trend.','category':'Breakout','direction':'BOTH','timeframe':'Daily','params':{'rsi_period':14,'rsi_low':40,'rsi_high':60,'macd_fast':12,'macd_slow':26,'macd_signal':9,'ma_fast':50,'ma_slow':200,'breakout_lookback':20,'atr_period':14,'atr_stop_mult':2.0,'swing_lookback':10,'reward_risk':2.5,'max_hold':30},'recipe':'BREAKOUT','use_trend':True,'use_macd':False},
 '50-Day Breakout': {'description':'A slower breakout strategy looking for significant new highs or lows.','category':'Breakout','direction':'BOTH','timeframe':'Daily','params':{'rsi_period':14,'rsi_low':40,'rsi_high':60,'macd_fast':12,'macd_slow':26,'macd_signal':9,'ma_fast':50,'ma_slow':200,'breakout_lookback':50,'atr_period':14,'atr_stop_mult':2.2,'swing_lookback':10,'reward_risk':3.0,'max_hold':50},'recipe':'BREAKOUT','use_trend':True,'use_macd':False},
 'RSI + MACD Confirmation': {'description':'RSI reversal setup confirmed by MACD momentum turning in the same direction.','category':'Momentum','direction':'BOTH','timeframe':'Daily','params':{'rsi_period':14,'rsi_low':35,'rsi_high':65,'rsi_exit_long':55,'rsi_exit_short':45,'macd_fast':12,'macd_slow':26,'macd_signal':9,'ma_fast':50,'ma_slow':200,'atr_period':14,'atr_stop_mult':1.5,'swing_lookback':5,'reward_risk':2.0,'max_hold':20},'recipe':'RSI_REVERSAL','use_trend':False,'use_macd':True},
 'Counter-Trend Extreme': {'description':'Fade unusually stretched RSI readings with tighter holding periods. Higher risk: use cautiously.','category':'Mean Reversion','direction':'BOTH','timeframe':'Daily','params':{'rsi_period':14,'rsi_low':25,'rsi_high':75,'rsi_exit_long':50,'rsi_exit_short':50,'macd_fast':12,'macd_slow':26,'macd_signal':9,'ma_fast':50,'ma_slow':200,'atr_period':14,'atr_stop_mult':1.3,'swing_lookback':5,'reward_risk':1.5,'max_hold':10},'recipe':'RSI_REVERSAL','use_trend':False,'use_macd':False},
}

def seed_v5_library():
    with conn() as c:
        done=c.execute("SELECT value FROM settings WHERE key='v5_library_seeded'").fetchone()
        if done:return
        now=dt.datetime.utcnow().isoformat()
        for name,cfg in V5_LIBRARY.items():
            c.execute('INSERT OR IGNORE INTO strategies(name,description,config,enabled,protected,created_at,updated_at) VALUES(?,?,?,?,0,?,?)',(name,cfg['description'],json.dumps(cfg),0,now,now))
        c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('v5_library_seeded','1')")

def v5_indicators(d,cfg):
    d=indicators(d,{'params':cfg['params'],'rules':{'all':[{'field':'close','op':'>','value':-1}]}})
    p=cfg['params']; look=int(p.get('breakout_lookback',20))
    d['high_swing']=d.High.shift(1).rolling(int(p.get('swing_lookback',5))).max()
    d['breakout_high']=d.High.shift(1).rolling(look).max(); d['breakout_low']=d.Low.shift(1).rolling(look).min()
    d['hist_cross_up']=(d['hist']>0)&(d['hist_prev']<=0); d['hist_cross_down']=(d['hist']<0)&(d['hist_prev']>=0)
    return d

def v5_signal_sides(d,cfg):
    p=cfg['params']; recipe=cfg.get('recipe','RSI_REVERSAL'); trend=bool(cfg.get('use_trend',False)); macd=bool(cfg.get('use_macd',False)); direction=cfg.get('direction','LONG').upper()
    long=pd.Series(False,index=d.index); short=pd.Series(False,index=d.index)
    trend_long=(d.Close>d.ma_fast)&(d.ma_fast>d.ma_slow); trend_short=(d.Close<d.ma_fast)&(d.ma_fast<d.ma_slow)
    if recipe=='RSI_REVERSAL':
        long=(d.rsi_prev<=float(p.get('rsi_low',30)))&(d.rsi>d.rsi_prev)
        short=(d.rsi_prev>=float(p.get('rsi_high',70)))&(d.rsi<d.rsi_prev)
        if macd: long&=d['hist']>d.hist_prev; short&=d['hist']<d.hist_prev
    elif recipe=='TREND_PULLBACK':
        long=(d.rsi_prev<=float(p.get('rsi_low',40)))&(d.rsi>d.rsi_prev)&(d.Close>d.high_prev)
        short=(d.rsi_prev>=float(p.get('rsi_high',60)))&(d.rsi<d.rsi_prev)&(d.Close<d.Low.shift(1))
        if macd: long&=d['hist']>d.hist_prev; short&=d['hist']<d.hist_prev
    elif recipe=='MA_TREND':
        long=trend_long & ~(trend_long.shift(1).fillna(False)); short=trend_short & ~(trend_short.shift(1).fillna(False))
    elif recipe=='MACD_MOMENTUM':
        long=d.hist_cross_up; short=d.hist_cross_down
    elif recipe=='BREAKOUT':
        long=d.Close>d.breakout_high; short=d.Close<d.breakout_low
    if trend: long&=trend_long; short&=trend_short
    if direction=='LONG':short[:]=False
    elif direction=='SHORT':long[:]=False
    return long.fillna(False),short.fillna(False)

def strategy_plain_english(cfg):
    p=cfg['params']; direction=cfg.get('direction','LONG'); recipe=cfg.get('recipe','RSI_REVERSAL'); lines=[]
    if direction in ('LONG','BOTH'):
        if recipe=='RSI_REVERSAL': lines.append(f"BUY when RSI({int(p.get('rsi_period',14))}) was at/below {p.get('rsi_low',30)} and turns upward" + (' with improving MACD' if cfg.get('use_macd') else ''))
        elif recipe=='TREND_PULLBACK': lines.append(f"BUY an uptrend after RSI pulls back to about {p.get('rsi_low',40)} and price turns upward")
        elif recipe=='MA_TREND': lines.append(f"BUY when the {int(p.get('ma_fast',50))}-bar average moves into an uptrend above the {int(p.get('ma_slow',200))}-bar average")
        elif recipe=='MACD_MOMENTUM': lines.append('BUY when MACD momentum crosses upward')
        elif recipe=='BREAKOUT': lines.append(f"BUY when price closes above the previous {int(p.get('breakout_lookback',20))}-bar high")
    if direction in ('SHORT','BOTH'):
        if recipe=='RSI_REVERSAL': lines.append(f"SHORT when RSI({int(p.get('rsi_period',14))}) was at/above {p.get('rsi_high',70)} and turns downward" + (' with weakening MACD' if cfg.get('use_macd') else ''))
        elif recipe=='TREND_PULLBACK': lines.append(f"SHORT a downtrend after RSI rallies to about {p.get('rsi_high',60)} and price turns downward")
        elif recipe=='MA_TREND': lines.append(f"SHORT when the {int(p.get('ma_fast',50))}-bar average moves into a downtrend below the {int(p.get('ma_slow',200))}-bar average")
        elif recipe=='MACD_MOMENTUM': lines.append('SHORT when MACD momentum crosses downward')
        elif recipe=='BREAKOUT': lines.append(f"SHORT when price closes below the previous {int(p.get('breakout_lookback',20))}-bar low")
    if cfg.get('use_trend') and recipe!='MA_TREND': lines.append(f"Only trade with the wider {int(p.get('ma_fast',50))}/{int(p.get('ma_slow',200))}-bar trend")
    lines.append(f"Stop about {p.get('atr_stop_mult',1.5)}× recent volatility beyond the setup; target {p.get('reward_risk',2)}× the amount risked")
    lines.append(f"Give up after {int(p.get('max_hold',20))} bars if neither stop nor target is reached")
    return lines

def backtest_v5(d,strategy,initial=10000,risk_pct=.5,commission=1.5,slippage_pct=.05,max_hold=None):
    s=get_strategy(strategy) if isinstance(strategy,str) else {'name':'Ad hoc','config':strategy}; cfg=s['config']; d=v5_indicators(d,cfg); longs,shorts=v5_signal_sides(d,cfg); cash=float(initial); equity=[]; trades=[]; pos=None; p=cfg['params']; hold=int(max_hold or p.get('max_hold',20)); warmup=max(60,int(p.get('ma_slow',50))+5,int(p.get('breakout_lookback',20))+5); slip=slippage_pct/100
    for i in range(warmup,len(d)):
        day=str(d.index[i].date()); row=d.iloc[i]
        if pos:
            side=pos['side']; out=None; reason=''
            if side=='LONG':
                if row.Low<=pos['stop']:out=min(float(row.Open),pos['stop'])*(1-slip);reason='Stop loss'
                elif row.High>=pos['target']:out=pos['target']*(1-slip);reason='Profit target'
                elif p.get('rsi_exit_long') is not None and row.rsi>=float(p['rsi_exit_long']):out=float(row.Close)*(1-slip);reason='RSI recovery exit'
            else:
                if row.High>=pos['stop']:out=max(float(row.Open),pos['stop'])*(1+slip);reason='Stop loss'
                elif row.Low<=pos['target']:out=pos['target']*(1+slip);reason='Profit target'
                elif p.get('rsi_exit_short') is not None and row.rsi<=float(p['rsi_exit_short']):out=float(row.Close)*(1+slip);reason='RSI reversal exit'
            if out is None and i-pos['index']>=hold:out=float(row.Close)*(1-slip if side=='LONG' else 1+slip);reason='Maximum holding time'
            if out is not None:
                pnl=pos['qty']*((out-pos['entry']) if side=='LONG' else (pos['entry']-out))-commission; cash+=pnl; trades.append({'Direction':side,'Entry date':pos['day'],'Exit date':day,'Entry':pos['entry'],'Exit':out,'Units':pos['qty'],'Profit/Loss':pnl,'Exit reason':reason});pos=None
        if pos is None and i>0:
            side='LONG' if bool(longs.iloc[i-1]) else ('SHORT' if bool(shorts.iloc[i-1]) else None)
            if side:
                prev=d.iloc[i-1]; entry=float(row.Open)*(1+slip if side=='LONG' else 1-slip); atr=float(prev.atr); rr=float(p.get('reward_risk',2)); mult=float(p.get('atr_stop_mult',1.5))
                if side=='LONG': stop=min(float(prev.low_swing),entry-mult*atr); riskunit=entry-stop; target=entry+rr*riskunit
                else: stop=max(float(prev.high_swing),entry+mult*atr); riskunit=stop-entry; target=entry-rr*riskunit
                if np.isfinite(riskunit) and riskunit>0:
                    qty=max(0,(cash*risk_pct/100-commission)/riskunit); pos={'index':i,'day':day,'entry':entry,'stop':stop,'target':target,'qty':qty,'side':side}; cash-=commission
        mark=0 if not pos else pos['qty']*((float(row.Close)-pos['entry']) if pos['side']=='LONG' else (pos['entry']-float(row.Close))); equity.append({'day':day,'equity':cash+mark})
    eq=pd.DataFrame(equity); t=pd.DataFrame(trades)
    if eq.empty:return {},eq,t
    peak=eq.equity.cummax(); dd=(eq.equity/peak-1).min()*100; years=max((pd.Timestamp(eq.day.iloc[-1])-pd.Timestamp(eq.day.iloc[0])).days/365.25,1/365.25); cagr=((eq.equity.iloc[-1]/initial)**(1/years)-1)*100; pnl=t['Profit/Loss'] if not t.empty else pd.Series(dtype=float); gains=pnl[pnl>0].sum(); losses=-pnl[pnl<0].sum(); daily=eq.equity.pct_change().dropna(); sharpe=np.sqrt(252)*daily.mean()/daily.std() if len(daily)>2 and daily.std()>0 else 0
    return {'Total return %':round((eq.equity.iloc[-1]/initial-1)*100,2),'Annualised return %':round(cagr,2),'Worst drawdown %':round(dd,2),'Trades':len(t),'Winning trades %':round(100*(pnl>0).mean(),1) if len(pnl) else 0,'Profit factor':round(gains/losses,2) if losses else None,'Risk-adjusted score':round(float(sharpe),2)},eq,t

def optimise_v5(d,strategy,param_grid,risk_pct=.5,commission=1.5,slippage_pct=.05,limit=300):
    base=get_strategy(strategy)['config']; keys=list(param_grid); rows=[]
    for vals in list(itertools.product(*[param_grid[k] for k in keys]))[:limit]:
        cfg=copy.deepcopy(base)
        for k,v in zip(keys,vals):cfg['params'][k]=v
        try:
            stats,_,_=backtest_v5(d,cfg,risk_pct=risk_pct,commission=commission,slippage_pct=slippage_pct); row={k:v for k,v in zip(keys,vals)}; row.update(stats); rows.append(row)
        except Exception:pass
    return pd.DataFrame(rows).sort_values(['Risk-adjusted score','Annualised return %'],ascending=False) if rows else pd.DataFrame()

def scan_v5():
    seed_v5_library(); found=[]; errors=[]
    for symbol in symbols():
        try:
            raw=fetch(symbol,'2y')
            for s in list_strategies(True):
                cfg=s['config']; d=v5_indicators(raw,cfg); longs,shorts=v5_signal_sides(d,cfg); i=len(d)-1; side='LONG' if bool(longs.iloc[i]) else ('SHORT' if bool(shorts.iloc[i]) else None)
                if not side:continue
                row=d.iloc[i]; p=cfg['params']; atr=float(row.atr); mult=float(p.get('atr_stop_mult',1.5)); rr=float(p.get('reward_risk',2)); price=float(row.Close)
                if side=='LONG':stop=min(float(row.low_swing),price-mult*atr);target=price+rr*(price-stop)
                else:stop=max(float(row.high_swing),price+mult*atr);target=price-rr*(stop-price)
                day=str(d.index[i].date())
                with conn() as c:
                    if c.execute('SELECT 1 FROM alerts WHERE symbol=? AND strategy=? AND day=?',(symbol,s['name'],day)).fetchone():continue
                    c.execute('INSERT INTO alerts VALUES (?,?,?,?,?,?)',(symbol,s['name'],day,price,stop,target))
                found.append((symbol,s['name'],side,day,price,stop,target,float(row.rsi)))
        except Exception as e:errors.append(f'{symbol}: {e}')
    for symbol,strategy,side,day,price,stop,target,rsi in found:send_telegram(f"{'📈 BUY' if side=='LONG' else '📉 SHORT'} Trading Lab signal\n{symbol} — {strategy}\nDate: {day}\nClose: {price:.2f}\nIndicative stop: {stop:.2f}\nTarget: {target:.2f}\nRSI: {rsi:.1f}\nReview before trading; not an executed order.")
    return found,errors

def import_strategy_recipe(text,name='Imported Strategy'):
    """Safe best-effort importer: recognises common strategy descriptions/Pine snippets; never executes supplied code."""
    low=text.lower(); base=copy.deepcopy(V5_LIBRARY['RSI Reversal'])
    if 'breakout' in low or 'highest(' in low or 'lowest(' in low: base=copy.deepcopy(V5_LIBRARY['20-Day Breakout'])
    elif 'macd' in low and 'rsi' not in low: base=copy.deepcopy(V5_LIBRARY['MACD Momentum'])
    elif 'crossover' in low and ('sma' in low or 'ema' in low): base=copy.deepcopy(V5_LIBRARY['Moving Average Trend'])
    elif 'pullback' in low: base=copy.deepcopy(V5_LIBRARY['Trend Pullback'])
    import re
    nums=[int(x) for x in re.findall(r'\brsi[^\n]{0,30}?([0-9]{2})\b',low)]
    if nums:
        for n in nums:
            if n<=45:base['params']['rsi_low']=n
            if n>=55:base['params']['rsi_high']=n
    if 'short' in low and not any(x in low for x in ['long and short','long/short','both']):base['direction']='SHORT'
    elif 'long' in low and 'short' not in low:base['direction']='LONG'
    base['description']='Imported/translated strategy recipe. Review the interpretation before saving.'
    return base
