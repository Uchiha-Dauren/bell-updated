from pathlib import Path
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from alembic import command


def upgrade_database(engine: Engine) -> bool:

    zhol = Path(__file__).resolve().parent.parent


    babtau = Config(str(zhol / 'alembic.ini'))


    babtau.set_main_option('script_location', str(zhol / 'alembic'))

    with engine.connect() as connection:
        before = None
        if inspect(connection).has_table('alembic_version'):


            before = connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalar()
        connection.commit()
        babtau.attributes['connection'] = connection


        command.upgrade(babtau, 'head')
        after = connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalar()

        
    return before != after