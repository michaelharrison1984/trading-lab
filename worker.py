import time, schedule
from engine import scan_v5, get_setting, seed_v5_library
seed_v5_library()
def job():
    print('Starting daily scan...',flush=True)
    found,errors=scan_v5(); print(f'Scan complete: {len(found)} signals, {len(errors)} errors',flush=True)
schedule.every().monday.at('22:30').do(job);schedule.every().tuesday.at('22:30').do(job);schedule.every().wednesday.at('22:30').do(job);schedule.every().thursday.at('22:30').do(job);schedule.every().friday.at('22:30').do(job)
print('Trading Strategy Lab v5 scanner running',flush=True)
while True:schedule.run_pending();time.sleep(30)
