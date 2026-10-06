import os
import pandas as pd
import streamlit as st
import plotly.express as px
from engine import *
st.set_page_config(page_title='Trading Strategy Lab',page_icon='📈',layout='wide')
st.title('Trading Strategy Lab')
st.caption('US + UK daily swing signals • Research and paper trading only • No live orders')
tabs=st.tabs(['Dashboard & Signals','Backtesting','Paper Trading','Settings'])
with tabs[0]:
    st.subheader('Latest signals')
    if st.button('Scan now',type='primary'):
        with st.spinner('Fetching daily market data...'):
            found,errors=scan()
        st.success(f'{len(found)} new signals recorded')
        if errors:st.warning('Data errors: '+'; '.join(errors[:10]))
    with conn() as c:alerts=pd.read_sql_query('SELECT * FROM alerts ORDER BY day DESC,symbol LIMIT 200',c)
    st.dataframe(alerts,use_container_width=True,hide_index=True)
    st.info('Signals are detected on completed daily candles. Entry and stop levels are indicative; never treat the closing price as a guaranteed next-session fill.')
with tabs[1]:
    st.subheader('Single-symbol historical backtest')
    c1,c2,c3,c4=st.columns(4)
    symbol=c1.text_input('Ticker',value='AAPL').strip().upper()
    strategy=c2.selectbox('Strategy',STRATEGIES)
    period=c3.selectbox('History',['2y','5y','10y','max'],index=2)
    risk=c4.number_input('Risk per trade (%)',min_value=.1,max_value=3.,value=.5,step=.1)
    c5,c6,c7=st.columns(3)
    fee=c5.number_input('Fee (basis points, each side)',0,100,10)
    slip=c6.number_input('Slippage (basis points, each side)',0,100,5)
    hold=c7.number_input('Maximum holding days',1,120,20)
    if st.button('Run backtest',type='primary'):
        try:
            with st.spinner('Loading history and simulating trades...'):
                d=fetch(symbol,period);stats,eq,trades=backtest(d,strategy,risk_pct=risk,fee_bps=fee,slip_bps=slip,max_hold=hold)
            st.session_state['bt']=(stats,eq,trades,symbol,strategy)
        except Exception as e:st.error(str(e))
    if 'bt' in st.session_state:
        stats,eq,trades,bs,bstrat=st.session_state['bt'];st.caption(f'{bs} · {bstrat}')
        cols=st.columns(6)
        for col,(k,v) in zip(cols,stats.items()):col.metric(k,str(v))
        if not eq.empty:st.plotly_chart(px.line(eq,x='day',y='equity',title='Simulated equity curve'),use_container_width=True)
        st.dataframe(trades,use_container_width=True,hide_index=True)
        if not trades.empty:st.download_button('Download trades CSV',trades.to_csv(index=False),'trades.csv','text/csv')
    st.warning('Backtest is single-symbol, long-only, one position at a time. No portfolio-wide cash allocation, dividends, FX conversion, tax, delisting survivorship or market-impact modelling. Results are not predictive. Verify out-of-sample before relying on signals.')
with tabs[2]:
    st.subheader('Paper trading journal')
    with conn() as c:trades=pd.read_sql_query('SELECT * FROM trades ORDER BY id DESC',c)
    st.dataframe(trades,use_container_width=True,hide_index=True)
    if not trades.empty:
        closed=trades[trades.status=='CLOSED'].copy()
        if len(closed):st.metric('Realised paper P/L (instrument currency)',f'{(closed.qty*(closed.exit-closed.entry)).sum():,.2f}')
    with st.form('paper_entry'):
        st.markdown('**Open a simulated trade**')
        a,b,c=st.columns(3)
        sy=a.text_input('Symbol','AAPL').upper();strat=b.selectbox('Signal strategy',STRATEGIES);entry=c.number_input('Entry',min_value=.01,value=100.,step=1.)
        a,b,c=st.columns(3)
        stop=a.number_input('Stop',min_value=.01,value=95.,step=1.);target=b.number_input('Target',min_value=.01,value=110.,step=1.);risk=c.number_input('Risk %',min_value=.1,max_value=3.,value=.5)
        if st.form_submit_button('Open paper position'):
            try:qty=paper_open(sy,strat,entry,stop,target,risk=risk);st.success(f'Opened {qty:.4f} simulated units');st.rerun()
            except Exception as e:st.error(str(e))
    opened=trades[trades.status=='OPEN'] if not trades.empty else pd.DataFrame()
    if not opened.empty:
        with st.form('paper_exit'):
            id=st.selectbox('Close position ID',opened.id.tolist());price=st.number_input('Simulated exit price',min_value=.01,value=100.)
            if st.form_submit_button('Close position'):paper_close(int(id),price);st.rerun()
    st.caption('Manual journal only: stops/targets are not automatically executed. US and UK currency values are not converted; do not aggregate multi-currency P/L as GBP.')
with tabs[3]:
    st.subheader('Watchlist and notifications')
    watch=st.text_area('Comma-separated Yahoo Finance tickers (.L for London)',get_setting('symbols',DEFAULT),height=120)
    if st.button('Save watchlist'):set_setting('symbols',watch);st.success('Saved; scanner will use updated symbols')
    st.write('Telegram credentials are supplied via .env / Portainer environment variables, not stored in the database.')
    if st.button('Send Telegram test'):
        ok,msg=send_telegram('Trading Strategy Lab: Telegram test successful.')
        (st.success if ok else st.error)(msg)
    st.caption('Scheduled scan: Monday–Friday 22:30 UTC, after normal US/UK sessions. See scanner logs for failures. Historical data is sourced from Yahoo Finance through yfinance and may be delayed or incomplete.')
