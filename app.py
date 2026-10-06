import copy, json
import pandas as pd
import streamlit as st
import plotly.express as px
from engine import *
st.set_page_config(page_title='Trading Strategy Lab',page_icon='📈',layout='wide'); conn(); st.title('Trading Strategy Lab'); st.caption('Daily US + UK strategy research • configurable scanner • paper trading only')
tabs=st.tabs(['Dashboard & Signals','Backtesting','Strategy Manager','Optimiser','Paper Trading','Settings'])
with tabs[0]:
    enabled=list_strategies(True); st.write('**Scanner strategies:** '+(', '.join(s['name'] for s in enabled) if enabled else 'None enabled'))
    if st.button('Scan now',type='primary'):
        with st.spinner('Scanning watchlist...'):found,errors=scan()
        st.success(f'{len(found)} new signals recorded');
        if errors:st.warning('; '.join(errors[:10]))
    with conn() as c:alerts=pd.read_sql_query('SELECT * FROM alerts ORDER BY day DESC,symbol LIMIT 200',c)
    st.dataframe(alerts,use_container_width=True,hide_index=True); st.info('Signals use completed daily candles. Stops/targets are research levels, not guaranteed fills.')
with tabs[1]:
    strategies=[s['name'] for s in list_strategies()]; st.subheader('Backtest & compare')
    c1,c2,c3=st.columns(3); symbol=c1.text_input('Ticker','AAPL').strip().upper(); period=c2.selectbox('History',['2y','5y','10y','max'],index=2); chosen=c3.multiselect('Strategies',strategies,default=strategies[:min(3,len(strategies))])
    c1,c2,c3=st.columns(3); risk=c1.number_input('Risk/trade %',.1,3.,.5,.1); fee=c2.number_input('Fee bps / side',0,100,10); slip=c3.number_input('Slippage bps / side',0,100,5)
    if st.button('Run comparison',type='primary') and chosen:
        try:
            d=fetch(symbol,period); results=[]; curves={}; tradesets={}
            for name in chosen:
                stats,eq,tr=backtest(d,name,risk_pct=risk,fee_bps=fee,slip_bps=slip); results.append({'Strategy':name,**stats}); curves[name]=eq; tradesets[name]=tr
            st.session_state['compare']=(pd.DataFrame(results),curves,tradesets,symbol)
        except Exception as e:st.error(str(e))
    if 'compare' in st.session_state:
        res,curves,tradesets,bs=st.session_state['compare']; st.dataframe(res,use_container_width=True,hide_index=True)
        long=[]
        for name,eq in curves.items():
            x=eq.copy();x['Strategy']=name;long.append(x)
        if long:st.plotly_chart(px.line(pd.concat(long),x='day',y='equity',color='Strategy',title=f'{bs} simulated equity curves'),use_container_width=True)
        inspect=st.selectbox('Inspect trades',list(tradesets));st.dataframe(tradesets[inspect],use_container_width=True,hide_index=True)
    st.warning('Backtests are hypothetical and single-symbol. Optimisation can overfit. Validate on unseen periods and forward paper trading.')
with tabs[2]:
    st.subheader('Strategy Manager'); all_s=list_strategies(); names=[s['name'] for s in all_s]; selected=st.selectbox('Strategy',names); s=get_strategy(selected); cfg=copy.deepcopy(s['config'])
    c1,c2,c3=st.columns([2,2,1]); c1.write(f"**{selected}** — {s['description']}"); c2.write('Built-in protected template' if s['protected'] else 'Editable custom strategy'); enabled=c3.checkbox('Scanner enabled',value=s['enabled'],key='enable_selected')
    if enabled!=s['enabled']:set_strategy_enabled(selected,enabled);st.success('Scanner setting updated')
    with st.expander('Parameters',expanded=True):
        edited={}; cols=st.columns(3)
        for idx,(k,v) in enumerate(cfg['params'].items()):
            if isinstance(v,(int,float)) and not isinstance(v,bool):edited[k]=cols[idx%3].number_input(k,value=float(v),step=1.0 if isinstance(v,int) else .1,key='p_'+selected+k)
            else:edited[k]=v
        for k,v in edited.items():cfg['params'][k]=int(v) if isinstance(TEMPLATES.get(selected,{}).get('params',{}).get(k),int) or (k.endswith('period') or k.endswith('days') or k.endswith('lookback') or k.startswith('ma_') or k.startswith('macd_') or k=='max_hold') else v
    with st.expander('Entry rules — all conditions must be true',expanded=True):
        newrules=[]
        for i,r in enumerate(cfg['rules']['all']):
            a,b,c,d=st.columns([2,1,2,1]); field=a.selectbox('Field',FIELDS,index=FIELDS.index(r['field']),key=f'f{selected}{i}');op=b.selectbox('Op',OPS,index=OPS.index(r['op']),key=f'o{selected}{i}');
            if 'compare' in r:rhs=c.text_input('Compare field',r['compare'],key=f'c{selected}{i}');nr={'field':field,'op':op,'compare':rhs}
            elif 'param' in r:rhs=c.text_input('Parameter',r['param'],key=f'c{selected}{i}');nr={'field':field,'op':op,'param':rhs}
            else:rhs=c.number_input('Value',value=float(r.get('value',0)),key=f'c{selected}{i}');nr={'field':field,'op':op,'value':rhs}
            keep=d.checkbox('Keep',True,key=f'k{selected}{i}');
            if keep:newrules.append(nr)
        cfg['rules']['all']=newrules
    st.markdown('**Add condition**'); a,b,c,d=st.columns([2,1,2,1]);nf=a.selectbox('New field',FIELDS,key='nf');no=b.selectbox('New operator',OPS,key='no');mode=c.selectbox('Right side',['Fixed value','Parameter','Field'],key='nm');
    if mode=='Fixed value':rhs=d.number_input('Value',value=0.0,key='nv')
    else:rhs=d.text_input('Name',key='nn')
    if st.button('Add rule'):
        nr={'field':nf,'op':no,'value':rhs} if mode=='Fixed value' else {'field':nf,'op':no,'param' if mode=='Parameter' else 'compare':rhs}; cfg['rules']['all'].append(nr); st.session_state['draft_rules']=cfg['rules']['all']; st.info('Rule added to draft. Clone/save below to persist it.')
    if 'draft_rules' in st.session_state:cfg['rules']['all']=st.session_state['draft_rules']
    st.divider(); newname=st.text_input('Clone/save as',value='' if s['protected'] else selected+' v2'); desc=st.text_input('Description',value=s['description'])
    if st.button('Save as new strategy',type='primary'):
        try:save_strategy(newname,desc,cfg,False,False);st.session_state.pop('draft_rules',None);st.success(f'Saved {newname}');st.rerun()
        except Exception as e:st.error(str(e))
    if not s['protected']:
        c1,c2=st.columns(2)
        if c1.button('Overwrite this custom strategy'):
            try:save_strategy(selected,desc,cfg,s['enabled'],True);st.success('Updated')
            except Exception as e:st.error(str(e))
        if c2.button('Delete custom strategy'):
            delete_strategy(selected);st.rerun()
with tabs[3]:
    st.subheader('Parameter optimiser'); st.caption('Grid-search a few parameters, then validate the best candidates out-of-sample. Maximum 200 combinations per run.')
    strategies=[s['name'] for s in list_strategies()]; c1,c2,c3=st.columns(3); osym=c1.text_input('Ticker','AAPL',key='osym').upper(); ostrat=c2.selectbox('Base strategy',strategies,key='ostrat'); operiod=c3.selectbox('History',['5y','10y','max'],index=1,key='operiod'); base=get_strategy(ostrat)['config']; numeric=list(base['params'])
    p1=st.selectbox('Parameter 1',numeric); vals1=st.text_input('Values 1 (comma separated)',str(base['params'][p1])); p2=st.selectbox('Parameter 2',['(none)']+numeric); vals2=st.text_input('Values 2',str(base['params'].get(p2,'')))
    if st.button('Run optimisation',type='primary'):
        try:
            def parse(x):return [float(v.strip()) for v in x.split(',') if v.strip()]
            grid={p1:parse(vals1)};
            if p2!='(none)':grid[p2]=parse(vals2)
            d=fetch(osym,operiod);out=optimise(d,ostrat,grid);st.session_state['opt']=out
        except Exception as e:st.error(str(e))
    if 'opt' in st.session_state:st.dataframe(st.session_state['opt'].head(50),use_container_width=True,hide_index=True)
with tabs[4]:
    st.subheader('Paper trading journal');
    with conn() as c:trades=pd.read_sql_query('SELECT * FROM trades ORDER BY id DESC',c)
    st.dataframe(trades,use_container_width=True,hide_index=True); strategies=[s['name'] for s in list_strategies()]
    with st.form('paper_entry'):
        a,b,c=st.columns(3);sy=a.text_input('Symbol','AAPL').upper();strat=b.selectbox('Strategy',strategies);entry=c.number_input('Entry',.01,value=100.);a,b,c=st.columns(3);stop=a.number_input('Stop',.01,value=95.);target=b.number_input('Target',.01,value=110.);prisk=c.number_input('Risk %',.1,3.,.5)
        if st.form_submit_button('Open paper position'):
            try:qty=paper_open(sy,strat,entry,stop,target,risk=prisk);st.success(f'Opened {qty:.4f} simulated units');st.rerun()
            except Exception as e:st.error(str(e))
    opened=trades[trades.status=='OPEN'] if not trades.empty else pd.DataFrame()
    if not opened.empty:
        with st.form('paper_exit'):
            tid=st.selectbox('Close ID',opened.id.tolist());price=st.number_input('Exit price',.01,value=100.)
            if st.form_submit_button('Close position'):paper_close(int(tid),price);st.rerun()
with tabs[5]:
    st.subheader('Watchlist & Telegram');watch=st.text_area('Comma-separated Yahoo Finance tickers (.L for London)',get_setting('symbols',DEFAULT),height=120)
    if st.button('Save watchlist'):set_setting('symbols',watch);st.success('Saved')
    if st.button('Send Telegram test'):
        ok,msg=send_telegram('Trading Strategy Lab: Telegram test successful.');(st.success if ok else st.error)(msg)
    st.caption('Scheduled scanner runs Monday–Friday at the configured UTC time. Custom strategies only scan when Scanner enabled is switched on.')
