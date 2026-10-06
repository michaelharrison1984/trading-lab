import copy
import pandas as pd
import streamlit as st
import plotly.express as px
from engine import *
st.set_page_config(page_title='Trading Strategy Lab',page_icon='📈',layout='wide'); conn(); code,money=currency_info()
st.title('Trading Strategy Lab'); st.caption('Build ideas • test them on history • receive daily alerts • practise with paper money')
tabs=st.tabs(['Home & Signals','Test Strategies','Build a Strategy','Strategy Tuner','Paper Trading','Settings'])
with tabs[0]:
    st.subheader('Today’s scanner'); enabled=list_strategies(True); st.write('Currently watching for: **'+(', '.join(s['name'] for s in enabled) if enabled else 'No strategies enabled')+'**')
    if st.button('Run scan now',type='primary'):
        with st.spinner('Checking your watchlist...'):found,errors=scan()
        st.success(f'Finished — {len(found)} new opportunities found.')
        if errors:st.warning('Some tickers could not be checked: '+'; '.join(errors[:8]))
    with conn() as c:a=pd.read_sql_query('SELECT symbol AS Ticker,strategy AS Strategy,day AS Date,price AS Price,stop AS Stop,target AS Target FROM alerts ORDER BY day DESC LIMIT 200',c)
    st.dataframe(a,use_container_width=True,hide_index=True)
with tabs[1]:
    st.subheader('Test strategies on past market data'); st.write('Choose a share, timeframe and strategies. The Lab then simulates what would have happened if those rules had been followed.')
    names=[s['name'] for s in list_strategies()]; a,b,c=st.columns(3); sym=a.text_input('Share / ETF ticker','AAPL').upper(); timeframe=b.selectbox('Chart timeframe',['Daily','Hourly']); period=c.selectbox('How far back?',['2y','5y','10y','max'],index=2,disabled=timeframe=='Hourly'); chosen=st.multiselect('Strategies to compare',names,default=names[:min(3,len(names))])
    a,b,c,d=st.columns(4); initial=a.number_input(f'Starting account ({code})',1000.,1000000.,10000.,1000.); risk=b.number_input('Account risked per trade (%)',.1,3.,.5,.1); commission=c.number_input(f'Commission per buy/sell ({money})',0.,100.,1.50,.50); slippage=d.number_input('Estimated price slippage (%)',0.,2.,.05,.01,help='Allows for getting a slightly worse price than the chart shows.')
    if st.button('Run historical test',type='primary') and chosen:
        try:
            interval='1d' if timeframe=='Daily' else '1h'; actual_period=period if timeframe=='Daily' else '2y'; dta=fetch(sym,actual_period,interval); rows=[]; curves={}; trades={}
            for n in chosen:
                stats,eq,tr=backtest_v3(dta,n,initial,risk,commission,slippage); rows.append({'Strategy':n,**stats});curves[n]=eq;trades[n]=tr
            st.session_state.bt=(pd.DataFrame(rows),curves,trades,sym)
        except Exception as e:st.error(str(e))
    if 'bt' in st.session_state:
        res,curves,trades,bs=st.session_state.bt; st.dataframe(res,use_container_width=True,hide_index=True)
        parts=[]
        for n,e in curves.items():x=e.copy();x['Strategy']=n;parts.append(x)
        if parts:st.plotly_chart(px.line(pd.concat(parts),x='day',y='equity',color='Strategy',title=f'How the {money}{initial:,.0f} account changed'),use_container_width=True)
        n=st.selectbox('Show individual simulated trades',list(trades));st.dataframe(trades[n],use_container_width=True,hide_index=True)
    st.info('Historical tests are experiments, not predictions. A strategy that looks good here should still be tested on unseen data and paper traded.')
with tabs[2]:
    st.subheader('Build a Strategy'); st.write('Start with an existing idea, change it in plain English, then save your own version. Built-in strategies stay untouched.')
    names=[s['name'] for s in list_strategies()]; selected=st.selectbox('Start from',names); s=get_strategy(selected); cfg=copy.deepcopy(s['config']); p=cfg['params']
    a,b,c=st.columns(3); direction=a.radio('Trade direction',['Buy / Long','Sell / Short'],index=0 if cfg.get('direction','LONG')=='LONG' else 1,help='Buy/Long aims to profit from a rise. Sell/Short aims to profit from a fall.'); cfg['direction']='LONG' if direction.startswith('Buy') else 'SHORT'; cfg['timeframe']=b.selectbox('Timeframe',['Daily','Hourly'],index=0 if cfg.get('timeframe','Daily')=='Daily' else 1); c.write('**Daily scanner:** '+('On' if s['enabled'] else 'Off'))
    st.markdown('#### When should we look for a trade?')
    friendly={'rsi_period':'RSI lookback (bars)','rsi_oversold':'RSI considered oversold below','rsi_recovery_max':'RSI must recover before','arm_days':'How long an oversold signal stays valid','macd_fast':'MACD fast setting','macd_slow':'MACD slow setting','macd_signal':'MACD signal setting','ma_fast':'Short trend average','ma_slow':'Long trend average','pullback_rsi_min':'Pullback RSI minimum','pullback_rsi_max':'Pullback RSI maximum','atr_period':'Volatility lookback','atr_stop_mult':'Stop distance (ATR multiplier)','swing_lookback':'Recent high/low lookback','reward_risk':'Profit target for every 1 risked','max_hold':'Maximum bars to hold','exit_rsi':'Exit when RSI reaches'}
    cols=st.columns(3)
    for i,(k,v) in enumerate(list(p.items())):
        if isinstance(v,(int,float)):p[k]=cols[i%3].number_input(friendly.get(k,k.replace('_',' ').title()),value=float(v),step=1. if isinstance(v,int) else .1,key='v3'+selected+k)
    st.markdown('#### Entry checklist'); st.caption('All of these conditions must be true before the strategy opens a trade. Advanced rule editing is available below if you want it.')
    descriptions={'sid_armed':'RSI has recently been oversold','rsi':'Current RSI','rsi_prev':'Previous RSI','hist':'MACD momentum','hist_prev':'Previous MACD momentum','close':'Closing price','ma_fast':'Short moving average','ma_slow':'Long moving average','high_prev':'Previous high','volume':'Trading volume','volume_ma20':'Average volume'}
    for r in cfg['rules']['all']:
        rhs=descriptions.get(r.get('compare'),friendly.get(r.get('param'),r.get('value'))); st.write('✓',descriptions.get(r['field'],r['field']),r['op'],rhs)
    with st.expander('Advanced: edit the exact entry rules'):
        st.caption('This is for later experimentation. The simpler controls above are enough for most changes.'); st.json(cfg['rules'])
    st.markdown('#### Save your version'); newname=st.text_input('Give it a name',value='' if s['protected'] else selected+' v2'); desc=st.text_input('Short description',value=s['description']); enable=st.checkbox('Include this strategy in automatic scans after saving',False)
    if st.button('Save as my strategy',type='primary'):
        try:save_strategy(newname,desc,cfg,enable,False);st.success(f'{newname} saved.');st.rerun()
        except Exception as e:st.error(str(e))
    if True:
        a,b=st.columns(2)
        if a.button('Update this strategy'):save_strategy(selected,desc,cfg,s['enabled'],True);st.success('Updated')
        confirm=b.checkbox('I understand this permanently removes the strategy from future scans and tests',key='delconfirm')
        if b.button('Delete this strategy',disabled=not confirm):delete_strategy(selected);st.rerun()
with tabs[3]:
    st.subheader('Strategy Tuner'); st.write('**What this does:** you choose one or two settings and a few values to try. The Lab runs the same historical test for every combination and shows which versions performed best.')
    st.example=''; st.caption('Example: try RSI oversold at 25, 30, 35 and 40, combined with profit targets of 1.5×, 2× and 2.5× risk. That is 12 tests automatically.')
    names=[s['name'] for s in list_strategies()]; a,b,c=st.columns(3); osym=a.text_input('Ticker to experiment on','AAPL',key='os'); ostrat=b.selectbox('Strategy to tune',names); operiod=c.selectbox('History for experiment',['5y','10y','max'],index=1); base=get_strategy(ostrat)['config']; numeric=list(base['params']); labels={k:k.replace('_',' ').title() for k in numeric}
    p1=st.selectbox('Setting to try',numeric,format_func=lambda x:labels[x]); vals1=st.text_input('Values to test (comma separated)',str(base['params'][p1])); p2=st.selectbox('Optional second setting',['(none)']+numeric,format_func=lambda x:x if x=='(none)' else labels[x]); vals2=st.text_input('Second set of values',str(base['params'].get(p2,'')))
    if st.button('Try all combinations',type='primary'):
        try:
            parse=lambda x:[float(v.strip()) for v in x.split(',') if v.strip()];grid={p1:parse(vals1)}
            if p2!='(none)':grid[p2]=parse(vals2)
            st.session_state.opt=optimise_v3(fetch(osym,operiod),ostrat,grid)
        except Exception as e:st.error(str(e))
    if 'opt' in st.session_state:
        st.success('Best balanced results are shown first. Do not simply pick the highest return — look for repeatable results with manageable drawdowns.');st.dataframe(st.session_state.opt.head(50),use_container_width=True,hide_index=True)
with tabs[4]:
    st.subheader('Paper Trading'); st.write('Practice the strategy with simulated money. Open positions are repriced from the latest available market data whenever this page refreshes.')
    with conn() as c:tr=pd.read_sql_query("SELECT * FROM trades ORDER BY id DESC",c)
    opened=tr[tr.status=='OPEN'].copy() if not tr.empty else pd.DataFrame(); closed=tr[tr.status=='CLOSED'].copy() if not tr.empty else pd.DataFrame()
    if not opened.empty:
        q=live_quotes(opened.symbol.tolist()); rows=[]
        for _,r in opened.iterrows():
            qq=q.get(r.symbol,{}); current=qq.get('price'); direction=(r.direction or 'LONG'); pnl=None if current is None else r.qty*((current-r.entry) if direction=='LONG' else (r.entry-current)); pct=None if current is None else 100*((current/r.entry-1) if direction=='LONG' else (r.entry/current-1)); rows.append({'Status':'🟢 LIVE','Ticker':r.symbol,'Direction':'BUY' if direction=='LONG' else 'SELL / SHORT','Strategy':r.strategy,'Entry':r.entry,'Latest price':current,f'Unrealised P/L ({code})':pnl,'Return %':pct,'Stop':r.stop,'Target':r.target,'Opened':r.entry_day,'Last market bar':qq.get('asof','Unavailable')})
        st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
    else:st.info('No live paper trades yet. Open one below and it will appear here with a LIVE indicator and changing profit/loss.')
    with st.expander('Open a new simulated trade',expanded=opened.empty):
        with st.form('entry'):
            a,b,c=st.columns(3);sy=a.text_input('Ticker','AAPL').upper();strat=b.selectbox('Strategy',[x['name'] for x in list_strategies()]);direct=c.radio('Trade',['Buy / Long','Sell / Short'])
            use_live=st.checkbox('Use latest available market price as my simulated entry',True,help='Recommended. This prevents a paper trade starting with an artificial profit or loss caused by a made-up entry price.')
            a,b,c,d=st.columns(4);manual=a.number_input('Manual entry price (only used if option above is unticked)',.01,value=100.);stop=b.number_input('Stop loss',.01,value=95. if direct.startswith('Buy') else 105.);target=c.number_input('Profit target',.01,value=110. if direct.startswith('Buy') else 90.);prisk=d.number_input('Account risk (%)',.1,3.,.5)
            if st.form_submit_button('Open paper trade'):
                try:
                    if use_live:
                        qq=live_quotes([sy]).get(sy,{})
                        if 'price' not in qq: raise ValueError('Could not obtain a current market price for '+sy)
                        entry=float(qq['price'])
                    else: entry=float(manual)
                    if direct.startswith('Buy') and not (stop<entry<target): raise ValueError(f'For a Buy trade, set Stop < Entry ({entry:.2f}) < Target.')
                    if direct.startswith('Sell') and not (target<entry<stop): raise ValueError(f'For a Short trade, set Target < Entry ({entry:.2f}) < Stop.')
                    qty=paper_open_v3(sy,strat,entry,stop,target,'LONG' if direct.startswith('Buy') else 'SHORT',risk=prisk);st.success(f'Paper trade opened at {cur_symbol}{entry:.2f}: {qty:.3f} units');st.rerun()
                except Exception as e:st.error(str(e))
    if not opened.empty:
        with st.expander('Close a paper trade'):
            tid=st.selectbox('Trade ID',opened.id.tolist());price=st.number_input('Exit price',.01,value=100.)
            if st.button('Close selected trade'):paper_close(int(tid),price);st.rerun()
    if not closed.empty:st.markdown('#### Completed paper trades');st.dataframe(closed,use_container_width=True,hide_index=True)
with tabs[5]:
    st.subheader('Settings'); cur=st.selectbox('Default currency',['GBP','USD','EUR'],index=['GBP','USD','EUR'].index(get_setting('currency','GBP')))
    st.markdown('#### Find a ticker')
    st.caption('Search by company or fund name, e.g. Apple, Tesco, VWRP or Shell. London-listed Yahoo tickers usually end in .L.')
    tq=st.text_input('Company / ETF search')
    if tq:
        found=ticker_search(tq)
        if found: st.dataframe(pd.DataFrame(found),use_container_width=True,hide_index=True)
        else: st.info('No ticker matches found. Try a shorter company or fund name.')
    st.markdown('#### Daily scan watchlist')
    st.caption('Enter one ticker per line. Commas also work. Examples: AAPL for Apple (US), SHEL.L for Shell (London), VWRP.L for Vanguard FTSE All-World ETF (London).')
    current='\n'.join(symbols())
    watch=st.text_area('Tickers to scan',current,height=220,placeholder='AAPL\nMSFT\nSHEL.L\nVWRP.L')
    st.caption(f'{len([x for x in watch.replace(chr(10), chr(44)).split(chr(44)) if x.strip()])} ticker(s) currently entered.')
    if st.button('Save settings'):set_setting('currency',cur);set_setting('symbols',','.join(x.strip().upper() for x in watch.replace('\n',',').split(',') if x.strip()));st.success('Settings saved.')
    if st.button('Send Telegram test'):
        ok,msg=send_telegram('Trading Strategy Lab: Telegram test successful.');(st.success if ok else st.error)(msg)
    st.caption('Automatic scanning remains Monday–Friday at the configured time. Hourly strategies can be backtested, while scheduled scanning remains daily in this version.')
