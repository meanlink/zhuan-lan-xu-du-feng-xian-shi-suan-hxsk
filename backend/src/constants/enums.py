from enum import Enum
class Role(str, Enum):
    admin = 'admin'
    analyst = 'analyst'
    viewer = 'viewer'
class JobStatus(str, Enum):
    queued = 'queued'
    running = 'running'
    completed = 'completed'
    failed = 'failed'
    cancelled = 'cancelled'
class AttemptStatus(str, Enum):
    running = 'running'
    completed = 'completed'
    failed = 'failed'
    interrupted = 'interrupted'
    cancelled = 'cancelled'
