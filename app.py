import copy, json
import pandas as pd
import streamlit as st
import plotly.express as px
from engine import *
st.set_page_config(page_title='Trading Strategy Lab',page_icon='📈',layout='wide'); seed_v5_library(); code,money=currency_info()
st.title('Trading Strategy Lab v5'); st.caption('Choose an idea → understand it → tweak it → test it → paper trade it → enable alerts')
tabs=st.tabs(['Home & Signals','Strategy Library','Test Strategies','Tune a Strategy','Paper Trading','Settings'])
with tabs[0]:
    st.subheader('Today’s scanner'); enabled=list_strategies(True); st.write('Currently watching for: **'+(', '.join(s['name'] for s in enabled) if enabled else 'No strategies enabled')+'**')
    if st.button('Run scan now',type='primary',key='home_run_scan'):
        with st.spinner('Checking your watchlist...'):found,errors=scan_v5()
        st.success(f'Finished — {len(found)} new opportunities found.')
        if errors:st.warning('Some tickers could not be checked: '+'; '.join(errors[:8]))
    with conn() as c:a=pd.read_sql_query('SELECT symbol AS Ticker,strategy AS Strategy,day AS Date,price AS Price,stop AS Stop,target AS Target FROM alerts ORDER BY day DESC LIMIT 200',c)
    st.dataframe(a,use_container_width=True,hide_index=True)
with tabs[1]:
    st.subheader('Strategy Library'); st.write('Start with a trading idea rather than building rules from scratch. Every strategy can be copied, changed, tested, enabled for alerts or deleted.')
    strategies=list_strategies(); rows=[]
    for s in strategies:
        cfg=s['config']; rows.append({'Strategy':s['name'],'Style':cfg.get('category','Custom'),'Trades':{'LONG':'🟢 Buy / Long','SHORT':'🔴 Sell / Short','BOTH':'🔵 Both'}.get(cfg.get('direction','LONG'),cfg.get('direction')),'Timeframe':cfg.get('timeframe','Daily'),'Alerts':'On' if s['enabled'] else 'Off','What it does':s['description']})
    st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
    if not strategies:st.stop()
    selected=st.selectbox('Choose a strategy to understand or change',[s['name'] for s in strategies],key='library_strategy'); s=get_strategy(selected); cfg=copy.deepcopy(s['config']); p=cfg['params']
    st.markdown('### In plain English')
    for line in strategy_plain_english(cfg):st.write('✓ '+line)
    a,b,c,d=st.columns(4); direction=a.selectbox('Which trades?', ['LONG','SHORT','BOTH'],key='library_direction',index=['LONG','SHORT','BOTH'].index(cfg.get('direction','LONG')),format_func=lambda x:{'LONG':'🟢 Buy / Long only','SHORT':'🔴 Sell / Short only','BOTH':'🔵 Buy and Short'}[x]); cfg['direction']=direction; cfg['timeframe']=b.selectbox('Chart timeframe',['Daily','Hourly'],index=0 if cfg.get('timeframe','Daily')=='Daily' else 1,key='library_timeframe'); cfg['use_trend']=c.checkbox('Only trade with the wider trend',bool(cfg.get('use_trend',False)),key='library_use_trend'); cfg['use_macd']=d.checkbox('Require MACD confirmation',bool(cfg.get('use_macd',False)),key='library_use_macd')
    st.markdown('### Entry settings')
    recipe=cfg.get('recipe','RSI_REVERSAL')
    c1,c2,c3=st.columns(3)
    if recipe in ('RSI_REVERSAL','TREND_PULLBACK'):
        p['rsi_period']=int(c1.number_input('RSI lookback',2,100,int(p.get('rsi_period',14))))
        if direction in ('LONG','BOTH'):p['rsi_low']=c2.number_input('For BUY trades: RSI is low around',1.,50.,float(p.get('rsi_low',30)),help='Lower values mean the share has fallen harder before the strategy considers buying.')
        if direction in ('SHORT','BOTH'):p['rsi_high']=c3.number_input('For SHORT trades: RSI is high around',50.,99.,float(p.get('rsi_high',70)),help='Higher values mean the share has risen harder before the strategy considers shorting.')
    elif recipe=='BREAKOUT':p['breakout_lookback']=int(c1.number_input('Breakout lookback (bars)',5,250,int(p.get('breakout_lookback',20))))
    elif recipe=='MA_TREND':
        p['ma_fast']=int(c1.number_input('Faster trend average',2,250,int(p.get('ma_fast',50))));p['ma_slow']=int(c2.number_input('Slower trend average',5,500,int(p.get('ma_slow',200))))
    elif recipe=='MACD_MOMENTUM':st.info('This strategy enters when MACD momentum crosses direction. You can change the standard MACD settings below.')
    if cfg.get('use_trend') and recipe!='MA_TREND':
        p['ma_fast']=int(c1.number_input('Trend: shorter average',2,250,int(p.get('ma_fast',50)),key='trendfast'));p['ma_slow']=int(c2.number_input('Trend: longer average',5,500,int(p.get('ma_slow',200)),key='trendslow'))
    st.markdown('### Risk & exit settings'); c1,c2,c3,c4=st.columns(4);p['atr_stop_mult']=c1.number_input('Stop distance (× volatility)',.2,10.,float(p.get('atr_stop_mult',1.5)),.1);p['reward_risk']=c2.number_input('Profit target for every £1 risked',.5,10.,float(p.get('reward_risk',2)),.1);p['max_hold']=int(c3.number_input('Maximum bars to hold',1,500,int(p.get('max_hold',20))));p['swing_lookback']=int(c4.number_input('Recent high/low lookback',2,100,int(p.get('swing_lookback',5))))
    with st.expander('Advanced indicator settings'):
        a,b,c=st.columns(3);p['macd_fast']=int(a.number_input('MACD fast',2,100,int(p.get('macd_fast',12))));p['macd_slow']=int(b.number_input('MACD slow',3,200,int(p.get('macd_slow',26))));p['macd_signal']=int(c.number_input('MACD signal',2,100,int(p.get('macd_signal',9))))
    st.markdown('### Save / manage'); a,b,c=st.columns(3); newname=a.text_input('Save a copy as',value=selected+' - My Version'); enable=b.checkbox('Enable daily alerts for saved copy',False)
    if c.button('Save as a new strategy',type='primary',key='library_save_copy'):
        try:save_strategy(newname,'Custom version of '+selected,cfg,enable,False);st.success(newname+' saved');st.rerun()
        except Exception as e:st.error(str(e))
    a,b,c=st.columns(3)
    if a.button('Update this strategy with the settings above',key='library_update'):
        try:save_strategy(selected,s['description'],cfg,s['enabled'],True);st.success('Updated');st.rerun()
        except Exception as e:st.error(str(e))
    if b.button('Turn alerts '+('OFF' if s['enabled'] else 'ON'),key='library_toggle_alerts'):set_strategy_enabled(selected,not s['enabled']);st.rerun()
    confirm=c.checkbox('Confirm delete',key='deleteconfirm')
    if c.button('Delete strategy',disabled=not confirm,key='library_delete'):delete_strategy(selected);st.rerun()
    st.divider(); st.markdown('### Import / translate a strategy'); st.write('Paste a strategy description or Pine Script snippet. The Lab **does not execute it**; it safely translates recognised RSI, moving-average, MACD, pullback and breakout ideas into a Lab recipe for you to review.')
    pasted=st.text_area('Paste strategy rules or Pine Script',height=160,placeholder='Example: Short when RSI is above 70 and turns down. Use a 200 day trend filter. Target 2x risk.')
    importname=st.text_input('Name for imported strategy','Imported Strategy')
    if st.button('Translate strategy',key='library_translate') and pasted:
        icfg=import_strategy_recipe(pasted,importname);st.session_state['import_cfg']=icfg;st.success('Translated. Review the interpretation below before saving.')
    if 'import_cfg' in st.session_state:
        icfg=st.session_state['import_cfg'];
        for line in strategy_plain_english(icfg):st.write('✓ '+line)
        if st.button('Save translated strategy',key='library_save_translated'):
            try:save_strategy(importname,'Imported and translated strategy',icfg,False,False);del st.session_state['import_cfg'];st.success('Saved');st.rerun()
            except Exception as e:st.error(str(e))
with tabs[2]:
    st.subheader('Test Strategies'); st.write('Compare one or more strategies on the same historical share/ETF data. Both-direction strategies can take BUY and SHORT trades in the same test.')
    names=[s['name'] for s in list_strategies()];a,b,c=st.columns(3);sym=a.text_input('Share / ETF ticker','AAPL',key='backtest_ticker').upper();timeframe=b.selectbox('Chart timeframe',['Daily','Hourly'],key='backtest_timeframe');period=c.selectbox('How far back?',['2y','5y','10y','max'],index=2,disabled=timeframe=='Hourly',key='backtest_period');chosen=st.multiselect('Strategies to compare',names,default=names[:min(3,len(names))],key='backtest_strategies')
    a,b,c,d=st.columns(4);initial=a.number_input(f'Starting account ({code})',1000.,1000000.,10000.,1000.);risk=b.number_input('Account risked per trade (%)',.1,3.,.5,.1);commission=c.number_input(f'Commission per transaction ({money})',0.,100.,1.50,.50);slippage=d.number_input('Estimated price slippage (%)',0.,2.,.05,.01)
    if st.button('Run historical test',type='primary',key='backtest_run') and chosen:
        try:
            dta=fetch(sym,period if timeframe=='Daily' else '2y','1d' if timeframe=='Daily' else '1h');rows=[];curves={};trades={}
            for n in chosen:
                stats,eq,tr=backtest_v5(dta,n,initial,risk,commission,slippage);rows.append({'Strategy':n,**stats});curves[n]=eq;trades[n]=tr
            st.session_state.bt5=(pd.DataFrame(rows),curves,trades)
        except Exception as e:st.error(str(e))
    if 'bt5' in st.session_state:
        res,curves,trades=st.session_state.bt5;st.dataframe(res,use_container_width=True,hide_index=True);parts=[]
        for n,e in curves.items():x=e.copy();x['Strategy']=n;parts.append(x)
        if parts:st.plotly_chart(px.line(pd.concat(parts),x='day',y='equity',color='Strategy',title='Simulated account value'),use_container_width=True)
        n=st.selectbox('Show the individual simulated trades',list(trades),key='backtest_trade_detail');st.dataframe(trades[n],use_container_width=True,hide_index=True)
    st.info('Historical results are experiments, not predictions. Prefer strategies that behave reasonably across several shares, periods and market conditions.')
with tabs[3]:
    st.subheader('Tune a Strategy'); st.write('The Lab can try several versions of the **same idea** for you. Pick settings you are genuinely unsure about; it will test the combinations and rank the balanced results.')
    names=[s['name'] for s in list_strategies()];a,b,c=st.columns(3);osym=a.text_input('Ticker to experiment on','AAPL',key='os');ostrat=b.selectbox('Strategy to tune',names,key='tune_strategy');operiod=c.selectbox('History for experiment',['5y','10y','max'],index=1,key='tune_period');base=get_strategy(ostrat)['config'];numeric=[k for k,v in base['params'].items() if isinstance(v,(int,float))];friendly={'rsi_low':'BUY: low RSI level','rsi_high':'SHORT: high RSI level','reward_risk':'Profit target vs risk','atr_stop_mult':'Stop distance','max_hold':'Maximum holding time','ma_fast':'Shorter trend average','ma_slow':'Longer trend average','breakout_lookback':'Breakout lookback','rsi_period':'RSI lookback'}
    p1=st.selectbox('First setting to experiment with',numeric,key='tune_param1',format_func=lambda x:friendly.get(x,x.replace('_',' ').title()));vals1=st.text_input('Values to try',str(base['params'][p1]),help='Example: 25,30,35');p2=st.selectbox('Optional second setting',['(none)']+numeric,key='tune_param2',format_func=lambda x:x if x=='(none)' else friendly.get(x,x.replace('_',' ').title()));vals2=st.text_input('Second values to try',str(base['params'].get(p2,'')))
    if st.button('Run these experiments',type='primary',key='tune_run'):
        try:
            parse=lambda x:[float(v.strip()) for v in x.split(',') if v.strip()];grid={p1:parse(vals1)}
            if p2!='(none)':grid[p2]=parse(vals2)
            st.session_state.opt5=optimise_v5(fetch(osym,operiod),ostrat,grid)
        except Exception as e:st.error(str(e))
    if 'opt5' in st.session_state:
        st.success('The first rows balance historical return and consistency. Treat them as candidates to test elsewhere, not as automatic winners.');st.dataframe(st.session_state.opt5.head(50),use_container_width=True,hide_index=True)
with tabs[4]:
    st.subheader('Paper Trading');st.write('Practice with simulated positions. Open trades are repriced from the latest available market data whenever this page refreshes.')
    with conn() as c:tr=pd.read_sql_query('SELECT * FROM trades ORDER BY id DESC',c)
    opened=tr[tr.status=='OPEN'].copy() if not tr.empty else pd.DataFrame();closed=tr[tr.status=='CLOSED'].copy() if not tr.empty else pd.DataFrame()
    if not opened.empty:
        q=live_quotes(opened.symbol.tolist());rows=[]
        for _,r in opened.iterrows():
            qq=q.get(r.symbol,{});current=qq.get('price');direction=(r.direction or 'LONG');pnl=None if current is None else r.qty*((current-r.entry) if direction=='LONG' else (r.entry-current));pct=None if current is None else 100*((current/r.entry-1) if direction=='LONG' else (r.entry/current-1));rows.append({'Status':'🟢 LIVE','Ticker':r.symbol,'Direction':'BUY' if direction=='LONG' else 'SHORT','Strategy':r.strategy,'Entry':r.entry,'Latest':current,f'Unrealised P/L ({code})':pnl,'Return %':pct,'Stop':r.stop,'Target':r.target,'Opened':r.entry_day,'Last market bar':qq.get('asof','Unavailable')})
        st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
    else:st.info('No live paper trades yet.')
    with st.expander('Open a new simulated trade',expanded=opened.empty):
        with st.form('entry'):
            a,b,c=st.columns(3);sy=a.text_input('Ticker','AAPL').upper();strat=b.selectbox('Strategy',[x['name'] for x in list_strategies()],key='paper_strategy');direct=c.radio('Trade',['Buy / Long','Sell / Short']);use_live=st.checkbox('Use latest available market price as my simulated entry',True);a,b,c,d=st.columns(4);manual=a.number_input('Manual entry price',.01,value=100.);stop=b.number_input('Stop loss',.01,value=95. if direct.startswith('Buy') else 105.);target=c.number_input('Profit target',.01,value=110. if direct.startswith('Buy') else 90.);prisk=d.number_input('Account risk (%)',.1,3.,.5)
            if st.form_submit_button('Open paper trade'):
                try:
                    entry=float(live_quotes([sy]).get(sy,{}).get('price')) if use_live else float(manual)
                    qty=paper_open_v3(sy,strat,entry,stop,target,'LONG' if direct.startswith('Buy') else 'SHORT',risk=prisk);st.success(f'Paper trade opened at {money}{entry:.2f}: {qty:.3f} units');st.rerun()
                except Exception as e:st.error(str(e))
    if not opened.empty:
        tid=st.selectbox('Close paper trade',opened.id.tolist(),key='paper_close_trade');price=st.number_input('Exit price',.01,value=float(opened[opened.id==tid].entry.iloc[0]));
        if st.button('Close selected trade',key='paper_close_button'):paper_close(int(tid),price);st.rerun()
    if not closed.empty:st.markdown('#### Completed paper trades');st.dataframe(closed,use_container_width=True,hide_index=True)
with tabs[5]:
    st.subheader('Settings');cur=st.selectbox('Default currency',['GBP','USD','EUR'],key='settings_currency',index=['GBP','USD','EUR'].index(get_setting('currency','GBP')));st.markdown('#### Find a ticker');tq=st.text_input('Search company / ETF name')
    if tq:
        found=ticker_search(tq);st.dataframe(pd.DataFrame(found),use_container_width=True,hide_index=True) if found else st.info('No matches found.')
    st.markdown('#### Daily scan watchlist');st.caption('One ticker per line is easiest to read. Commas also work. London Yahoo tickers usually end in .L.');watch=st.text_area('Tickers to scan','\n'.join(symbols()),height=220);st.caption(f"{len([x for x in watch.replace(chr(10),',').split(',') if x.strip()])} ticker(s) entered")
    if st.button('Save settings',key='settings_save'):set_setting('currency',cur);set_setting('symbols',','.join(x.strip().upper() for x in watch.replace('\n',',').split(',') if x.strip()));st.success('Saved')
    if st.button('Send Telegram test',key='settings_telegram_test'):
        ok,msg=send_telegram('Trading Strategy Lab v5: Telegram test successful.');(st.success if ok else st.error)(msg)
