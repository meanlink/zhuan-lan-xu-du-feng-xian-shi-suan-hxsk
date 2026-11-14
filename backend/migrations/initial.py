from sqlalchemy import inspect, text
from src.config.database import Base, engine
from src import models

# 增量列：旧库升级时补齐，不重建数据。
JOB_COLUMNS = {
    'claim_token': 'VARCHAR(64) DEFAULT \'\'',
    'claimed_by': 'VARCHAR(120) DEFAULT \'\'',
    'lease_expires_at': 'DOUBLE NULL',
    'attempt_count': 'INTEGER DEFAULT 0',
    'cancelled_at': 'DOUBLE NULL',
    'cancelled_by': 'VARCHAR(150) DEFAULT \'\'',
}


def _columns(table):
    return {c['name'] for c in inspect(engine).get_columns(table)}


def migrate():
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        if 'jobs' in inspect(engine).get_table_names():
            existing = _columns('jobs')
            for name, ddl in JOB_COLUMNS.items():
                if name not in existing:
                    conn.execute(text(f'ALTER TABLE jobs ADD COLUMN {name} {ddl}'))
        if 'job_attempts' in inspect(engine).get_table_names():
            existing = _columns('job_attempts')
            for name, ddl in {
                'dataset_checksum': 'VARCHAR(64) DEFAULT \'\'',
                'effective': 'BOOLEAN DEFAULT FALSE',
                'params': 'JSON NULL',
                'sample': 'JSON NULL',
            }.items():
                if name not in existing:
                    conn.execute(text(f'ALTER TABLE job_attempts ADD COLUMN {name} {ddl}'))


if __name__ == '__main__':
    migrate()
