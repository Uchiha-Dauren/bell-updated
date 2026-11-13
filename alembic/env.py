from sqlalchemy import engine_from_config, pool

from alembic import context
from app.config import DATABASE_URL
from app.models import Base

config = context.config
target_metadata = Base.metadata


def run(connection) -> None:
    if connection.dialect.name != 'sqlite':
        raise RuntimeError('This application currently supports SQLite only.')
    enabled = connection.exec_driver_sql('PRAGMA foreign_keys').scalar()
    connection.commit()
    connection.exec_driver_sql('PRAGMA foreign_keys=OFF')
    connection.commit()
    try:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,

            compare_type=True,
            transactional_ddl=True,
        )
        context.run_migrations()
        if connection.exec_driver_sql('PRAGMA foreign_key_check').first() is not None:
            
            raise ValueError('Database migration rejected: invalid foreign-key references.')
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:

        connection.exec_driver_sql(f'PRAGMA foreign_keys={int(enabled)}')

        connection.commit()


if context.is_offline_mode():


    raise RuntimeError('Legacy schema adoption requires an online database connection.')
elif config.attributes.get('connection') is not None:


    run(config.attributes['connection'])
else:
    config.set_main_option('sqlalchemy.url', DATABASE_URL.replace('%', '%%'))
    engine = engine_from_config(
        
        config.get_section(config.config_ini_section), prefix='sqlalchemy.', poolclass=pool.NullPool
    )
    with engine.connect() as connection:
        run(connection)
