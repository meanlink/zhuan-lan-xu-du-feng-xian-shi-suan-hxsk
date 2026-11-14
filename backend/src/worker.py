import os, json, socket, threading, time, logging
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Report
from src.services.business import analyze
from src.services.reports import deliver
from src.services.audit import record
from src.services import jobs
logging.basicConfig(level=logging.INFO)

# 每个计算进程有独立身份：新增进程不会把其他进程正在执行的试验当作“遗留任务”。
WORKER_ID = os.getenv('WORKER_ID') or f'{socket.gethostname()}:{os.getpid()}'
LEASE_SECONDS = jobs.LEASE_SECONDS
RECOVER_INTERVAL = 5.0
_last_recover = 0.0


class LeaseKeeper:
    """执行期间续租；只续自己的领取令牌。任务被取消或转交后自动停止。"""

    def __init__(self, job_id, token):
        self.job_id, self.token = job_id, token
        self.lost = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        interval = max(1.0, LEASE_SECONDS / 3)
        while not self._stop.wait(interval):
            # 长计算期间也保持进程心跳，避免健康检查把仍在执行的进程判为失联。
            Path('/tmp/heartbeat').touch()
            try:
                with Session() as db:
                    if not jobs.renew(db, self.job_id, self.token):
                        self.lost = True
                        return
            except Exception:
                # 短暂数据库故障不代表失去租约，下个周期继续续租。
                logging.exception('Lease renewal failed for job %s', self.job_id)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=2)


def execute(job_id, worker_id=None):
    worker_id = worker_id or WORKER_ID
    # 领取与执行分开持连接：计算期间不占用数据库连接。
    with Session() as db:
        attempt = jobs.claim(db, job_id, worker_id)
        if attempt is None:
            return False  # 已被其他进程领取、已完成或已取消
        token = attempt.claim_token
        params = dict(attempt.params or {})
        records = list(attempt.sample or [])
    error = None
    result = None
    keeper = LeaseKeeper(job_id, token)
    try:
        if not records:
            raise ValueError('首次领取的数据样本为空，无法恢复该试验')
        with keeper:
            result = analyze(records, params)
            json.dumps(result, allow_nan=False)
    except Exception as e:
        logging.exception('Analysis failed')
        error = e
    with Session() as db:
        if keeper.lost:
            # 任务已被取消或转交，本次结果不再发布。
            jobs.ignore_stale(db, job_id, token, 'failed' if error else 'completed')
            return False
        if error is None and jobs.finish(db, job_id, token, result=result):
            return True
        if error is not None and jobs.finish(db, job_id, token, error=error):
            return False
        jobs.ignore_stale(db, job_id, token, 'failed' if error else 'completed')
        return False


def recover(worker_id=None):
    worker_id = worker_id or WORKER_ID
    with Session() as db:
        n = jobs.recover(db, worker_id)
        if n:
            logging.info('Recovered %s interrupted job(s) for %s', n, worker_id)
        return n


def tick(worker_id=None):
    global _last_recover
    worker_id = worker_id or WORKER_ID
    now = time.time()
    if now - _last_recover >= RECOVER_INTERVAL:
        _last_recover = now
        try:
            recover(worker_id)
        except Exception:
            logging.exception('Recovery sweep failed')
    with Session() as db:
        queued = list(db.scalars(select(Job.id).where(Job.status == 'queued').limit(3)))
    for job_id in queued:
        execute(job_id, worker_id)
    with Session() as db:
        for r in db.scalars(select(Report).where(Report.enabled == True, Report.next_run <= time.time())):
            d = deliver(db, r)
            if d:
                record(db, 'worker', 'report.delivered', {'id': r.id, 'delivery': d.id})
        db.commit()


def main():
    r = Redis.from_url(REDIS_URL, socket_timeout=3)
    # 只回收本进程遗留或租约已过期的任务；绝不重排其他计算进程正在执行的试验。
    while True:
        try:
            recover(WORKER_ID)
            break
        except Exception:
            logging.exception('Startup recovery retry')
            time.sleep(2)
    logging.info('Worker %s ready (lease %.0fs)', WORKER_ID, LEASE_SECONDS)
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item = r.blpop('analysis:queue', timeout=1)
            if item:
                execute(int(item[1]), WORKER_ID)
            tick(WORKER_ID)
        except Exception:
            logging.exception('Worker retry')
            time.sleep(2)


if __name__ == '__main__':
    main()
