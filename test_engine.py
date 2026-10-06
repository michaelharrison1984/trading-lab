import os,tempfile
os.environ['LAB_DB']=tempfile.mktemp(suffix='.db')
import numpy as np,pandas as pd
from engine import *
conn().close()
assert len(list_strategies())>=3
clone_strategy('SID','SID Test')
s=get_strategy('SID Test');assert not s['protected']
set_strategy_enabled('SID Test',True);assert get_strategy('SID Test')['enabled']
n=500;idx=pd.date_range('2024-01-01',periods=n,freq='D');price=100+np.cumsum(np.random.default_rng(1).normal(.05,1,n));d=pd.DataFrame({'Open':price,'High':price+1,'Low':price-1,'Close':price,'Volume':100000},index=idx)
stats,eq,tr=backtest(d,'SID Test');assert 'CAGR %' in stats and not eq.empty
out=optimise(d,'SID Test',{'rsi_oversold':[25,30]});assert len(out)==2
delete_strategy('SID Test')
print('strategy CRUD, backtest and optimiser smoke tests passed')
