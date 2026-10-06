import unittest
import numpy as np
import pandas as pd
from engine import indicators,backtest,signal_row
class EngineTests(unittest.TestCase):
    def setUp(self):
        idx=pd.bdate_range('2020-01-01',periods=320)
        close=100+np.linspace(0,40,320)+3*np.sin(np.arange(320)/6)
        self.d=pd.DataFrame({'Open':close,'High':close+2,'Low':close-2,'Close':close,'Volume':100000},index=idx)
    def test_indicators(self):
        d=indicators(self.d)
        self.assertTrue(all(s in d for s in ['SID','Trend-filtered SID','Trend-Pullback']))
        self.assertTrue(d['rsi'].dropna().between(0,100).all())
    def test_backtest(self):
        for s in ['SID','Trend-filtered SID','Trend-Pullback']:
            stats,eq,trades=backtest(self.d,s)
            self.assertGreater(len(eq),0)
            self.assertTrue((eq.equity>=0).all())
            self.assertIn('Max drawdown %',stats)
if __name__=='__main__':unittest.main()
