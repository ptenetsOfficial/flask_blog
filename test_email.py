import os
import smtplib
from dotenv import load_dotenv


def main():
    load_dotenv()
    from_email = os.getenv("EMAIL_USER")
    password = os.getenv("EMAIL_PASSWORD")

    if not from_email or not password:
        print("ОШИБКА: Не найдены EMAIL_USER или EMAIL_PASSWORD в .env файле!")
        return 1

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(from_email, password)
        print("Успешный вход в SMTP сервер Gmail!")
        return 0
    except smtplib.SMTPAuthenticationError:
        print("Ошибка аутентификации - неверный логин или пароль")
    except Exception as error:
        print(f"Ошибка подключения: {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())