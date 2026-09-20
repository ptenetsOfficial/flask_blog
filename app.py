# Импорты
import token
import io

from flask import Flask, render_template, request, redirect, session, jsonify, send_file
import sqlite3
import smtplib
from email.mime.text import MIMEText
import os
from datetime import datetime
from dotenv import load_dotenv
import secrets
import time
import hashlib
app = Flask(__name__)
app.secret_key = secrets.token_hex(16)  # Секретный ключ для сессии

DEFAULT_CATEGORIES = ['Tech', 'Science', 'News', 'Lifestyle', 'Travel']


# Загружаем переменные окружения из .env файла
load_dotenv()

# Подключение к базе данных
conn = sqlite3.connect('users.db', check_same_thread=False)
conn.row_factory = sqlite3.Row
cur = conn.cursor()


def initialize_database():
    # Создание таблицы пользователей
    cur.execute('''CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                email TEXT,
                password TEXT,
                last_login TIMESTAMP,
                avatar BLOB DEFAULT 'default_avatar.png',
                avatar_mimetype TEXT
    )''')
    try:
        cur.execute('ALTER TABLE users ADD COLUMN avatar_mimetype TEXT')
    except sqlite3.OperationalError:
        pass

    cur.execute('''CREATE TABLE IF NOT EXISTS categories(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE
    )''')
    for category_name in DEFAULT_CATEGORIES:
        cur.execute('INSERT OR IGNORE INTO categories(name) VALUES (?)', [category_name])


        






    # Создание таблицы постов
    cur.execute('''CREATE TABLE IF NOT EXISTS posts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                content TEXT,
                user_id INTEGER,
                category_id INTEGER,
                category TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (category_id) REFERENCES categories(id)

    )''')
    try:
        cur.execute('ALTER TABLE posts ADD COLUMN category TEXT DEFAULT ""')
    except sqlite3.OperationalError:
        pass

    # Создание таблицы уведомлений
    cur.execute('''CREATE TABLE IF NOT EXISTS notifications(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    # Таблица подписчиков на события (email подписки)
    cur.execute('''CREATE TABLE IF NOT EXISTS subscribers(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # Локальная таблица входящих уведомлений (локальный inbox)
    cur.execute('''CREATE TABLE IF NOT EXISTS inbox_entries(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient_email TEXT,
                subject TEXT,
                body TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS search_history(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                query_text TEXT,
                category TEXT,
                author TEXT,
                date_from TEXT,
                date_to TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    cur.execute('CREATE INDEX IF NOT EXISTS idx_user_id ON posts(user_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_notif_user_id ON notifications(user_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_subscriber_email ON subscribers(email)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_search_history_user ON search_history(user_id)')

    # Сохранение изменений в базе данных
    conn.commit()


initialize_database()

# Создает токен аутентификации
def create_auth_token(user_id, remember=False):
    token = secrets.token_hex(32)
    if remember:
        expires_at = time.time() + 30 * 24 * 60 * 60 # 30 дней
    else:
        expires_at = time.time() + 60 * 60 # 1 час
    cur.execute('INSERT INTO auth_tokens(user_id, token, expires_at) VALUES (?, ?, ?);',
        [user_id, token, expires_at])
    conn.commit()
    return token




# Проверяет токен аутентификации
def validate_auth_token(token):
    cur.execute('SELECT user_id FROM auth_tokens WHERE token = ? AND expires_at > ?', [token, time.time()])
    result = cur.fetchone()
    if result:
        return result[0]
    return None

# Обновляет время последнего входа
def update_last_login(user_id):
    last_login = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cur.execute('UPDATE users SET last_login = ? WHERE id = ?', [last_login, user_id])
    conn.commit()



# Функция отправки welcome-письма
def send_welcome_email(to_email, username):
    # Получаем данные из переменных окружения
    from_email = os.getenv("EMAIL_USER")
    password = os.getenv("EMAIL_PASSWORD")    
    # Проверяем, что переменные загружены
    if not from_email or not password:
        print("ОШИБКА: EMAIL_USER или EMAIL_PASSWORD не установлены в переменных окружения!")
        return False
    subject = "Добро пожаловать в наш блог!"
    body = f"""
    Привет, {username}!
    Спасибо за регистрацию в нашем блоге.
    С уважением,
    Команда блога
    """
    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = to_email    
    try:
        # Настройки для Gmail
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()  # Включаем шифрование
        server.login(from_email, password)
        server.send_message(msg)
        server.quit()        
        print(f"  Письмо успешно отправлено на {to_email}")
        return True
    except smtplib.SMTPAuthenticationError:
        print(" Ошибка аутентификации. Проверьте email и пароль приложения.")
    except Exception as e:
        print(f" Ошибка отправки письма: {e}")   
    return False


# Универсальная функция отправки уведомлений подписчикам и записи в локальный inbox
def send_notification_email(to_email, subject, body):
    from_email = os.getenv("EMAIL_USER")
    password = os.getenv("EMAIL_PASSWORD")
    if not from_email or not password:
        print("ОШИБКА: EMAIL_USER или EMAIL_PASSWORD не установлены в переменных окружения!")
        return False
    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = to_email
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(from_email, password)
        server.send_message(msg)
        server.quit()
        # Сохраняем в локальный inbox для истории
        try:
            cur.execute('INSERT INTO inbox_entries(recipient_email, subject, body) VALUES (?, ?, ?)',
                        [to_email, subject, body])
            conn.commit()
        except Exception as e:
            print(f"Не удалось записать в inbox_entries: {e}")
        print(f"  Уведомление успешно отправлено на {to_email}")
        return True
    except Exception as e:
        print(f"Ошибка при отправке уведомления на {to_email}: {e}")
        return False


# Создание таблицы токенов аутентификации
cur.execute("""CREATE TABLE IF NOT EXISTS auth_tokens(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    token TEXT UNIQUE,
    expires_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
)""")

cur.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON posts(user_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_notif_user_id ON notifications(user_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_token ON auth_tokens(token)")


def get_posts_paginated(page=1, per_page=5):
    offset = (page - 1) * per_page
    cur.execute('''
        SELECT posts.id, posts.title, posts.content, posts.user_id, posts.category_id, 
               posts.category, posts.created_at, users.name as author_name, categories.name as category_name
        FROM posts
        JOIN users ON posts.user_id = users.id
        LEFT JOIN categories ON posts.category_id = categories.id
        ORDER BY posts.created_at DESC
        LIMIT ? OFFSET ?
    ''', [per_page, offset])
    return cur.fetchall()




# Добавление/удаление/получение подписчиков
def add_subscriber(email):
    try:
        cur.execute('INSERT INTO subscribers(email) VALUES (?)', [email])
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # Уже подписан
        return False
    except Exception as e:
        print(f"Ошибка при добавлении подписчика: {e}")
        return False


def remove_subscriber(email):
    cur.execute('DELETE FROM subscribers WHERE email = ?', [email])
    conn.commit()


def get_subscribers():
    cur.execute('SELECT email FROM subscribers')
    return [r[0] for r in cur.fetchall()]


# Уведомление всех подписчиков о новой регистрации
def notify_subscribers_about_new_user(new_name, new_email):
    subscribers = get_subscribers()
    subject = "Новый пользователь зарегистрировался"
    body = f"Пользователь {new_name} зарегистрировался с почтой: {new_email}"
    for s in subscribers:
        sent = send_notification_email(s, subject, body)
        # Логируем каждое уведомление в таблице notifications (user_id NULL для внешних подписчиков)
        status = 'sent' if sent else 'failed'
        try:
            cur.execute('INSERT INTO notifications(user_id, action, details) VALUES (?, ?, ?)',
                        [None, 'new_user_registered', f'{new_name} <{new_email}> -> {s} : {status}'])
            conn.commit()
        except Exception as e:
            print(f"Не удалось залогировать уведомление: {e}")

# Добавляет нового пользователя и возвращает его ID
def add_user(name, email, password):
    cur.execute('INSERT INTO users(name, email, password) VALUES (?, ?, ?)', [name, email, password])
    conn.commit()
    cur.execute('SELECT id FROM users WHERE email = ?', [email])
    return cur.fetchone()[0]

# Возвращает пользователя по его ID
def get_user_by_id(user_id):
    cur.execute('SELECT * FROM users WHERE id = ?', [user_id])
    return cur.fetchone()

# Возвращает пользователя по его электронной почте
def get_user_by_email(email):
    cur.execute('SELECT * FROM users WHERE email = ?', [email])
    return cur.fetchone()

def normalize_category_name(category):
    if category is None:
        return 'Без категории'
    value = str(category).strip()
    if not value:
        return 'Без категории'

    try:
        category_id = int(value)
    except (TypeError, ValueError):
        return value

    cur.execute('SELECT name FROM categories WHERE id = ?', [category_id])
    row = cur.fetchone()
    return row[0] if row else value


def migrate_post_categories():
    rows = cur.execute('SELECT id, category FROM posts').fetchall()
    for row in rows:
        post_id, raw_category = row
        value = str(raw_category or '').strip()
        if not value:
            new_value = 'Без категории'
        else:
            try:
                category_id = int(value)
            except (TypeError, ValueError):
                new_value = value
            else:
                cat_row = cur.execute('SELECT name FROM categories WHERE id = ?', [category_id]).fetchone()
                new_value = cat_row[0] if cat_row else value

        if new_value and new_value != 'Без категории':
            cur.execute('INSERT OR IGNORE INTO categories(name) VALUES (?)', [new_value])

        if value != new_value:
            cur.execute('UPDATE posts SET category = ? WHERE id = ?', [new_value, post_id])
    conn.commit()


def ensure_category_name(category):
    name = str(category or '').strip()
    if not name:
        return ''
    cur.execute('INSERT OR IGNORE INTO categories(name) VALUES (?)', [name])
    conn.commit()
    return name


migrate_post_categories()


# Добавляет новый пост с привязкой к пользователю
def add_new_post(title, content, user_id, category=''):
    category_name = ensure_category_name(category)
    cur.execute(
        'INSERT INTO posts(title, content, user_id, category) VALUES (?, ?, ?, ?)',
        [title, content, user_id, category_name]
    )
    conn.commit()


# Возвращает посты пользователя
def get_posts_by_user(user_id):
    rows = cur.execute('''
        SELECT posts.*, users.name AS author_name,
               COALESCE(categories.name, posts.category) AS category_name
        FROM posts
        JOIN users ON posts.user_id = users.id
        LEFT JOIN categories ON categories.id = CAST(posts.category AS INTEGER)
        WHERE posts.user_id = ?
        ORDER BY posts.created_at DESC
    ''', [user_id]).fetchall()
    return [dict(row) for row in rows]


def search_posts(query=None, category=None, author=None, date_from=None, date_to=None):
    sql = '''
        SELECT posts.*, users.name AS author_name,
               COALESCE(categories.name, posts.category) AS category_name
        FROM posts
        JOIN users ON posts.user_id = users.id
        LEFT JOIN categories ON categories.id = CAST(posts.category AS INTEGER)
        WHERE 1 = 1
    '''
    params = []

    if query:
        sql += ' AND (posts.title LIKE ? OR posts.content LIKE ?)' 
        like_query = f'%{query}%'
        params.extend([like_query, like_query])

    if category:
        sql += ' AND (LOWER(COALESCE(categories.name, posts.category, "")) = LOWER(?) OR LOWER(COALESCE(posts.category, "")) = LOWER(?))'
        params.extend([category, str(category).strip()])

    if author:
        sql += ' AND LOWER(users.name) LIKE LOWER(?)'
        params.append(f'%{author}%')

    if date_from:
        sql += ' AND date(posts.created_at) >= date(?)'
        params.append(date_from)

    if date_to:
        sql += ' AND date(posts.created_at) <= date(?)'
        params.append(date_to)

    sql += ' ORDER BY posts.created_at DESC'
    rows = cur.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def save_search_history(user_id, query_text='', category='', author='', date_from='', date_to=''):
    if not user_id:
        return
    if not any([query_text, category, author, date_from, date_to]):
        return

    cur.execute(
        'INSERT INTO search_history(user_id, query_text, category, author, date_from, date_to) VALUES (?, ?, ?, ?, ?, ?)',
        [user_id, query_text, category, author, date_from, date_to]
    )
    conn.commit()


def get_search_history(user_id, limit=5):
    cur.execute(
        'SELECT query_text, category, author, date_from, date_to, created_at FROM search_history WHERE user_id = ? ORDER BY created_at DESC LIMIT ?',
        [user_id, limit]
    )
    return cur.fetchall()


def get_post_categories():
    cur.execute('SELECT DISTINCT name FROM categories WHERE name IS NOT NULL AND name != "" ORDER BY name')
    categories = [row[0] for row in cur.fetchall()]
    if categories:
        return categories
    cur.execute('SELECT DISTINCT category FROM posts WHERE category IS NOT NULL AND category != "" ORDER BY category')
    post_categories = [normalize_category_name(row[0]) for row in cur.fetchall()]
    if post_categories:
        return post_categories
    return list(DEFAULT_CATEGORIES)

# Логирует уведомление
def log_notification(user_id, action, details):
    cur.execute('INSERT INTO notifications(user_id, action, details) VALUES (?, ?, ?)',
                [user_id, action, details])
    conn.commit()


def notify_author_about_new_post(user_id, title, category=''):
    user = get_user_by_id(user_id)
    if not user:
        return False

    user_email = user[2] if len(user) > 2 else None
    if not user_email:
        return False

    category_name = str(category or '').strip() or 'Без категории'
    subject = 'Создан пост'
    body = (
        f'Здравствуйте, {user[1]}!\n\n'
        f'Ваш пост "{title}" успешно создан в категории "{category_name}".\n\n'
        'Спасибо, что делитесь своим материалом с нашим блогом.'
    )

    sent = send_notification_email(user_email, subject, body)
    if sent:
        log_notification(user_id, 'post_created_email_sent',
                        f'Письмо о создании поста "{title}" отправлено на {user_email}')
    else:
        log_notification(user_id, 'post_created_email_failed',
                        f'Не удалось отправить письмо о создании поста "{title}" на {user_email}')
    return sent

# Возвращает уведомления пользователя
def get_notifications_by_user(user_id):
    cur.execute('SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC', [user_id])
    return cur.fetchall()

def delete_auth_token(token):
    cur.execute('DELETE FROM auth_tokens WHERE token = ?', [token])
    conn.commit()

# Простой кэш в памяти
cache = {}
def get_cached_posts(page, per_page):
    cache_key = f'posts_{page}_{per_page}'
    # Проверяем, есть ли данные в кэше и не устарели ли они (60 секунд)
    if cache_key in cache:
        cached_data, timestamp = cache[cache_key]
        if time.time() - timestamp < 60:
            return cached_data
    # Если нет в кэше или устарело, получаем из БД
    offset = (page - 1) * per_page
    cur.execute('''
        SELECT posts.*, users.name, categories.name as category_name
        FROM posts
        JOIN users ON posts.user_id = users.id
        LEFT JOIN categories ON posts.category_id = categories.id
        ORDER BY posts.created_at DESC
        LIMIT ? OFFSET ?
    ''', [per_page, offset])
    posts = cur.fetchall()
    # Сохраняем в кэш
    cache[cache_key] = (posts, time.time())
    return posts



# Middleware для проверки аутентификации
@app.before_request
def check_auth():
    if 'user_id' not in session:
        token = request.cookies.get('auth_token')
        if token:
            user_id = validate_auth_token(token)
            if user_id:
                user = get_user_by_id(user_id)
                if user:
                    session['user_id'] = user[0]  # исправлено с user[e] на user[0]
                    session['user_name'] = user[1]

# Удаляет токен аутентификации


# Выход из системы









# Рендерим стартовую страницу
@app.route('/')
def main():
    page = request.args.get('page', 1, type=int)
    per_page = 5  # Количество постов на странице
    # Подсчет общего количества постов
    cur.execute('SELECT COUNT(*) FROM posts')
    total_posts = cur.fetchone()[0]
    q = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()
    author = request.args.get('author', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    posts = search_posts(q, category, author, date_from, date_to)
    users = cur.execute('SELECT * FROM users').fetchall()
    categories = get_post_categories()

    user_name = None
    search_history = []
    if 'user_id' in session:
        user_name = session['user_name']
        if any([q, category, author, date_from, date_to]):
            save_search_history(session['user_id'], q, category, author, date_from, date_to)
        search_history = get_search_history(session['user_id'])
    total_pages = (total_posts + per_page - 1) // per_page
    return render_template(
        'main.html',
        posts=posts,
        users=users,
        user_name=user_name,
        categories=categories,
        search_history=search_history,
        total_pages=total_pages,
        current_page=page,
        per_page=per_page,
        active_filters={
            'q': q,
            'category': category,
            'author': author,
            'date_from': date_from,
            'date_to': date_to,
        }
    )






@app.route('/logout')
def logout():
    token = request.cookies.get('auth_token')
    if token:
        delete_auth_token(token)
    session.clear()
    response = redirect('/')
    response.set_cookie('auth_token', '', expires=0)
    return response

# Подписка на уведомления о новых пользователях
@app.route('/subscribe/', methods=['GET', 'POST'])
def subscribe():
    message = None
    if request.method == 'POST':
        email = request.form.get('email')
        if email:
            added = add_subscriber(email)
            if added:
                send_notification_email(email, 'Подписка оформлена', 'Вы подписаны на уведомления о новых пользователях.')
                message = 'Подписка успешно оформлена.'
            else:
                message = 'Этот email уже подписан.'
    return render_template('subscribe.html', message=message)


# Отписка от уведомлений
@app.route('/unsubscribe/', methods=['GET', 'POST'])
def unsubscribe():
    message = None
    if request.method == 'POST':
        email = request.form.get('email')
        if email:
            remove_subscriber(email)
            message = 'Email удалён из подписчиков (если он там был).'
    return render_template('unsubscribe.html', message=message)


# Просмотр списка подписчиков (простая страница)
@app.route('/subscribers/')
def subscribers_list():
    subs = get_subscribers()
    return render_template('subscribers.html', subscribers=subs)

# Регистрация пользователя
@app.route('/register/', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        avatar = request.files.get('avatar')
        user = get_user_by_email(email)
        if user is None:
            user_id = add_user(name, email, password)
            # Отправляем письмо
            email_sent = send_welcome_email(email, name)            
            # Логируем действие
            if email_sent:
                log_notification(user_id, 'welcome_email_sent', 
                               f'Приветственное письмо отправлено на {email}')
            else:
                log_notification(user_id, 'welcome_email_failed', 
                               f'Не удалось отправить письмо на {email}')           
            # Уведомляем подписчиков о новой регистрации
            try:
                notify_subscribers_about_new_user(name, email)
            except Exception as e:
                print(f"Ошибка при уведомлении подписчиков: {e}")
            return redirect('/login/')
        else:
            print('Такой пользователь уже есть')
    return render_template('register.html')

# Процесс входа
@app.route('/login/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = request.form.get('remember') == 'on'  # Проверяем, установлен ли флажок "Запомнить меня"
        user = get_user_by_email(email)
        if user is None:
            return render_template('login.html', message="Нет такой почты")
        if user[3] == password:
            print('Вход выполнен')
            # Сохраняем ID пользователя в сессии
            session['user_id'] = user[0]
            session['user_name'] = user[1]
            update_last_login(user[0])  # Обновляем время последнего входа
            if remember: 
                token = create_auth_token(user[0], remember=True)
                response = redirect('/profile')
                response.set_cookie('auth_token', token, max_age=30*24*60*60)  # 30 дней
            else:
                response = redirect('/profile')
            log_notification(user[0], 'login', 'Пользователь вошел в систему')
            return response
        else:
            return render_template('login.html', message="Пароль неверный")
    return render_template('login.html')  

# Профиль текущего пользователя
@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect('/login/')
    user_id = session['user_id']
    user = get_user_by_id(user_id)
    posts = get_posts_by_user(user_id)
    notifications = get_notifications_by_user(user_id)
    if user:
        return render_template('profile.html', user=user, posts=posts, notifications=notifications)
    return "Пользователь не найден", 404


@app.route('/api/user/avatar')
def user_avatar():
    if 'user_id' not in session:
        return '', 401

    user = get_user_by_id(session['user_id'])
    if not user or not isinstance(user[5], bytes):
        return '', 404

    return send_file(io.BytesIO(user[5]), mimetype=user[6] or 'application/octet-stream')


@app.route('/api/user/<int:user_id>/avatar')
def public_user_avatar(user_id):
    user = get_user_by_id(user_id)
    if not user or not isinstance(user[5], bytes):
        return '', 404

    return send_file(io.BytesIO(user[5]), mimetype=user[6] or 'application/octet-stream')


@app.route('/profile/upload-avatar', methods=['POST'])
def upload_avatar():
    if 'user_id' not in session:
        return jsonify({'error': 'Требуется авторизация'}), 401

    avatar = request.files.get('avatar')
    if not avatar or not avatar.mimetype.startswith('image/'):
        return jsonify({'error': 'Нужно выбрать изображение'}), 400

    avatar_data = avatar.read()
    if not avatar_data:
        return jsonify({'error': 'Файл пустой'}), 400

    cur.execute(
        'UPDATE users SET avatar = ?, avatar_mimetype = ? WHERE id = ?',
        [avatar_data, avatar.mimetype, session['user_id']]
    )
    conn.commit()
    return jsonify({'message': 'Аватар успешно обновлен'})

# Страница пользователя
@app.route('/user/<int:user_id>')
def user_page(user_id):
    user = get_user_by_id(user_id)
    posts = get_posts_by_user(user_id)
    notifications = get_notifications_by_user(user_id)
    if user:
        return render_template('user_page.html', user=user, posts=posts, notifications=notifications)
    return "Пользователь не найден", 404

# Добавление поста
@app.route('/add_post', methods=['GET', 'POST'])
def add_post():
    if 'user_id' not in session:
        return redirect('/login/')

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        category = request.form.get('category', '').strip()
        user_id = session['user_id']

        if title and content:
            add_new_post(title, content, user_id, category)
            log_notification(user_id, 'new_post', f'Создан пост "{title}" в категории "{category or "Без категории"}"')
            notify_author_about_new_post(user_id, title, category)
        return redirect('/')

    categories = get_post_categories()
    return render_template('new_post.html', categories=categories)

@app.route('/api/posts')
def api_posts():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 5, type=int)
    offset = (page - 1) * per_page
    # Получаем посты
    cur.execute('''
        SELECT posts.id, posts.title, posts.content, posts.user_id, posts.category_id, 
               posts.category, posts.created_at, users.name as author_name, categories.name as category_name
        FROM posts
        JOIN users ON posts.user_id = users.id
        LEFT JOIN categories ON posts.category_id = categories.id
        ORDER BY posts.created_at DESC
        LIMIT ? OFFSET ?
    ''', [per_page, offset])
    # Преобразуем в словарь
    posts_list = []
    for post in cur.fetchall():
        posts_list.append({
            'id': post[0],
            'title': post[1],
            'content': post[2][:200] + '...' if len(post[2]) > 200 else post[2],
            'user_id': post[3],
            'category_id': post[4],
            'created_at': post[6],
            'author': post[7],
            'category': post[8] if post[8] else 'Без категории'
        })
    # Получаем общее количество постов
    cur.execute('SELECT COUNT(*) FROM posts')
    total = cur.fetchone()[0]
    return jsonify({
        'posts': posts_list,
        'page': page,
        'per_page': per_page,
        'total': total,
        'total_pages': (total + per_page - 1) // per_page
    })





if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

    



