import os
import time
import uuid
from fastapi import HTTPException
from redis import Redis
from sqlalchemy import select, update
from src.config.settings import REDIS_URL
from src.models import Dataset, Job, JobAttempt
from src.services.audit import record
from src.services.business import metadata

# 领取租约：持有者需定期续租，过期后其他进程才可恢复该试验。
LEASE_SECONDS = float(os.getenv('JOB_LEASE_SECONDS', '60'))
ACTIVE = ('queued', 'running')


def _check_params(data):
    allowed = {p['key']: p for p in metadata().get('parameters', [])}
    if set(data.params) - set(allowed):
        raise HTTPException(422, '包含未知分析参数')
    params = {k: p['default'] for k, p in allowed.items()}
    params.update(data.params)
    for key, p in allowed.items():
        v = params[key]
        if p['type'] == 'number':
            try:
                v = float(v)
                if not (p.get('min', -1e9) <= v <= p.get('max', 1e9)):
                    raise ValueError()
                params[key] = v
            except (ValueError, TypeError):
                raise HTTPException(422, f'{p["label"]} 超出范围或非数值')
        elif str(v) not in [str(o['value']) for o in p.get('options', [])]:
            raise HTTPException(422, f'{p["label"]} 不是有效选项')
    return params


def create(db, data, user):
    if not db.get(Dataset, data.dataset_id):
        raise HTTPException(404, '数据批次不存在')
    params = _check_params(data)
    j = Job(name=data.name, dataset_id=data.dataset_id, params=params, created_by=user.id,
            created_at=time.time(), status='queued', claim_token='', claimed_by='', attempt_count=0)
    db.add(j)
    db.flush()
    return j


def enqueue(job_id):
    try:
        r = Redis.from_url(REDIS_URL)
        r.rpush('analysis:queue', job_id)
        r.close()
    except Exception:
        pass  # SQL queued status is the durable fallback


def claim(db, job_id, worker_id, lease_seconds=None):
    """原子领取：只有 queued 且仍未被领取的任务会成功，重复领取/已取消均直接放弃。

    返回本次执行记录（JobAttempt），未领取到返回 None。
    """
    lease_seconds = lease_seconds or LEASE_SECONDS
    now = time.time()
    token = uuid.uuid4().hex
    # 条件更新是唯一入口：并发进程在同一行上的更新只有一个能命中 queued。
    result = db.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == 'queued')
        .values(status='running', claim_token=token, claimed_by=worker_id,
                lease_expires_at=now + lease_seconds,
                attempt_count=Job.attempt_count + 1, error='', finished_at=None)
    )
    if result.rowcount != 1:
        db.rollback()
        return None
    job = db.get(Job, job_id)
    # 恢复执行沿用首次领取时的数据样本与参数快照。
    first = db.scalar(select(JobAttempt).where(JobAttempt.job_id == job_id).order_by(JobAttempt.attempt_no))
    if first is not None:
        dataset_id, params = first.dataset_id, first.params
        dataset_checksum, sample = first.dataset_checksum, list(first.sample or [])
    else:
        dataset = db.get(Dataset, job.dataset_id)
        dataset_id, params = job.dataset_id, job.params
        dataset_checksum = dataset.checksum if dataset else ''
        sample = list(dataset.records) if dataset else []
    attempt = JobAttempt(
        job_id=job.id, attempt_no=job.attempt_count, claim_token=token, worker=worker_id,
        status='running', dataset_id=dataset_id, dataset_checksum=dataset_checksum,
        params=dict(params or {}), sample=sample, effective=False, started_at=now, heartbeat_at=now,
    )
    db.add(attempt)
    record(db, worker_id, 'job.claimed', {'id': job.id, 'attempt': attempt.attempt_no})
    db.commit()
    return attempt


def renew(db, job_id, token, lease_seconds=None):
    """续租。只续当前持有者自己的租约，返回是否仍持有。"""
    lease_seconds = lease_seconds or LEASE_SECONDS
    now = time.time()
    result = db.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == 'running', Job.claim_token == token)
        .values(lease_expires_at=now + lease_seconds)
    )
    if result.rowcount != 1:
        db.rollback()
        return False
    db.execute(
        update(JobAttempt)
        .where(JobAttempt.claim_token == token, JobAttempt.status == 'running')
        .values(heartbeat_at=now)
    )
    db.commit()
    return True


def finish(db, job_id, token, result=None, error=None):
    """发布执行结果。仅当仍是同一领取者且任务仍在运行时生效，否则丢弃迟到结果。"""
    now = time.time()
    completed = error is None
    values = dict(
        status='completed' if completed else 'failed',
        error='' if completed else str(error)[:990],
        result=result if completed else {},
        finished_at=now,
        claim_token='', claimed_by='', lease_expires_at=None,
    )
    updated = db.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == 'running', Job.claim_token == token)
        .values(**values)
    )
    if updated.rowcount != 1:
        db.rollback()
        return False
    db.execute(
        update(JobAttempt)
        .where(JobAttempt.claim_token == token, JobAttempt.status == 'running')
        .values(status='completed' if completed else 'failed',
                effective=completed,
                error='' if completed else str(error)[:990],
                finished_at=now)
    )
    record(db, 'worker', 'job.completed' if completed else 'job.failed',
           {'id': job_id, 'attempt': _attempt_no(db, token)})
    db.commit()
    return True


def _attempt_no(db, token):
    attempt = db.scalar(select(JobAttempt).where(JobAttempt.claim_token == token))
    return attempt.attempt_no if attempt else None


def ignore_stale(db, job_id, token, outcome):
    """记录被拒绝的迟到结果，便于审计；不改变任务状态。"""
    attempt = db.scalar(select(JobAttempt).where(JobAttempt.claim_token == token))
    record(db, 'worker', 'job.stale_result_ignored',
           {'id': job_id, 'attempt': attempt.attempt_no if attempt else None, 'outcome': outcome})
    db.commit()


def requeue(db, job_id, token, actor, reason):
    """把中断的试验放回队列。条件更新保证不会重排已取消/已完成的任务。"""
    now = time.time()
    updated = db.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == 'running', Job.claim_token == token)
        .values(status='queued', claim_token='', claimed_by='', lease_expires_at=None)
    )
    if updated.rowcount != 1:
        db.rollback()
        return False
    db.execute(
        update(JobAttempt)
        .where(JobAttempt.claim_token == token, JobAttempt.status == 'running')
        .values(status='interrupted', finished_at=now)
    )
    attempt = db.scalar(select(JobAttempt).where(JobAttempt.claim_token == token))
    record(db, actor, 'job.recovered',
           {'id': job_id, 'attempt': attempt.attempt_no if attempt else None, 'reason': reason})
    db.commit()
    return True


def recover(db, worker_id, lease_seconds=None):
    """恢复中断任务：只回收租约已过期（原进程失联）的运行中试验。

    绝不按“状态是 running”一刀切重排：加开计算进程或重启不会打断其他进程仍在执行的任务。
    """
    lease_seconds = lease_seconds or LEASE_SECONDS
    now = time.time()
    recovered = 0
    rows = db.execute(
        select(Job.id, Job.claim_token, Job.claimed_by, Job.lease_expires_at).where(Job.status == 'running')
    ).all()
    for job_id, token, claimed_by, lease_expires_at in rows:
        if lease_expires_at is not None and lease_expires_at > now:
            continue  # 持有者仍在续租
        if requeue(db, job_id, token, worker_id, f'lease-expired:{claimed_by}'):
            recovered += 1
    return recovered


def cancel(db, job_id, actor):
    """取消排队中或运行中的试验。与完成并发时，由数据库条件更新裁定谁先落定。"""
    now = time.time()
    updated = db.execute(
        update(Job)
        .where(Job.id == job_id, Job.status.in_(ACTIVE))
        .values(status='cancelled', cancelled_at=now, cancelled_by=actor,
                claim_token='', claimed_by='', lease_expires_at=None,
                finished_at=now, error='')
    )
    if updated.rowcount != 1:
        db.rollback()
        job = db.get(Job, job_id)
        if not job:
            raise HTTPException(404, '分析任务不存在')
        if job.status == 'cancelled':
            raise HTTPException(409, '该试验已取消')
        raise HTTPException(409, f'该试验已{ {"completed": "完成", "failed": "失败"}.get(job.status, job.status) }，以先落定的状态为准')
    db.execute(
        update(JobAttempt)
        .where(JobAttempt.job_id == job_id, JobAttempt.status == 'running')
        .values(status='cancelled', finished_at=now)
    )
    record(db, actor, 'job.cancelled', {'id': job_id})
    db.commit()
    return True
