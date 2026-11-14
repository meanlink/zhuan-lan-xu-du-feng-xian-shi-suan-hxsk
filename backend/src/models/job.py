from sqlalchemy import String, JSON, Double, ForeignKey, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class Job(Base):
    __tablename__ = 'jobs'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default='queued')
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String(1000), default='')
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    # 领取协调：只有持有当前 claim_token 且租约未过期的进程可以发布结果。
    claim_token: Mapped[str] = mapped_column(String(64), default='')
    claimed_by: Mapped[str] = mapped_column(String(120), default='')
    lease_expires_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    cancelled_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    cancelled_by: Mapped[str] = mapped_column(String(150), default='')


class JobAttempt(Base):
    """一次领取/执行记录。恢复执行会新建 attempt，并沿用首次领取的样本与参数。"""
    __tablename__ = 'job_attempts'
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer)
    claim_token: Mapped[str] = mapped_column(String(64), unique=True)
    worker: Mapped[str] = mapped_column(String(120), default='')
    status: Mapped[str] = mapped_column(String(20), default='running')
    dataset_id: Mapped[int] = mapped_column(Integer)
    dataset_checksum: Mapped[str] = mapped_column(String(64), default='')
    # 首次领取时的样本快照；重试直接沿用，批次后续变化也不影响复现。
    sample: Mapped[list] = mapped_column(JSON, default=list)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    effective: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str] = mapped_column(String(1000), default='')
    started_at: Mapped[float] = mapped_column(Double)
    heartbeat_at: Mapped[float] = mapped_column(Double)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
