import os,logging,time
from apscheduler.schedulers.blocking import BlockingScheduler
from engine import scan
logging.basicConfig(level=logging.INFO)
def job():
    try:
        found,errors=scan();logging.info('Scan: %s signals; errors: %s',len(found),errors)
    except Exception:logging.exception('Scan failed')
if __name__=='__main__':
    s=BlockingScheduler(timezone='UTC')
    s.add_job(job,'cron',day_of_week='mon-fri',hour=int(os.getenv('SCAN_HOUR_UTC','22')),minute=int(os.getenv('SCAN_MINUTE_UTC','30')),id='daily',max_instances=1,coalesce=True)
    logging.info('Worker running; daily scans Mon-Fri at %s:%s UTC',os.getenv('SCAN_HOUR_UTC','22'),os.getenv('SCAN_MINUTE_UTC','30'))
    s.start()
