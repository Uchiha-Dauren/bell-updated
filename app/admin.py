import argparse
from getpass import getpass
from app.database import SessionLocal, init_db
from app.services.auth import create_admin, reset_password


def main() -> None:
    parser = argparse.ArgumentParser(description='Управление администратором школы')
    parser.add_argument('action', choices=['create', 'reset-password'])
    parser.add_argument('--username', default='admin')
    args = parser.parse_args()
    password = getpass('Пароль (минимум 12 символов): ')
    if password != getpass('Повторите пароль: '):
        parser.error('Пароли не совпадают.')
    init_db()
    try:
        with SessionLocal.begin() as session:
            if args.action == 'create':
                create_admin(session, args.username, password)
            else:
                reset_password(session, args.username, password)
    except ValueError as exc:
        parser.error(str(exc))
    print(
        'Администратор создан.'
        if args.action == 'create'
        else 'Пароль обновлён, старые сессии завершены.'
    )

if __name__ == '__main__':
    main()
