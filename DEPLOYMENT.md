# 🚀 Развёртывание NadexRes на VPS

Полная инструкция по развёртыванию приложения на собственном сервере (Ubuntu/Debian).

---

## 📋 Требования

### VPS Сервер:
- **ОС:** Ubuntu 20.04+ / Debian 11+
- **RAM:** Минимум 1 GB (рекомендуется 2 GB)
- **CPU:** 1 vCore
- **Диск:** 10 GB
- **Провайдеры:** DigitalOcean, Vultr, Hetzner, Contabo

### Домен:
- Зарегистрированный домен
- DNS A-запись указывает на IP вашего VPS

---

## 🔧 Шаг 1: Подготовка сервера

### Подключитесь к серверу:
```bash
ssh root@your-server-ip
```

### Обновите систему:
```bash
apt update && apt upgrade -y
```

### Установите необходимые пакеты:
```bash
apt install -y python3 python3-pip python3-venv nginx postgresql postgresql-contrib certbot python3-certbot-nginx git
```

---

## 🗄️ Шаг 2: Настройка PostgreSQL

### Создайте базу данных:
```bash
sudo -u postgres psql
```

Выполните в psql:
```sql
CREATE DATABASE nadexres;
CREATE USER nadexres_user WITH PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE nadexres TO nadexres_user;
\q
```

### Проверьте подключение:
```bash
psql -h localhost -U nadexres_user -d nadexres
# Введите пароль
# \q для выхода
```

---

## 📁 Шаг 3: Загрузка приложения

### Создайте директорию:
```bash
mkdir -p /var/www/nadexres
cd /var/www/nadexres
```

### Загрузите файлы приложения:

**Вариант 1: С помощью git (если код в репозитории):**
```bash
git clone https://github.com/yourusername/nadexres.git .
```

**Вариант 2: Загрузка по SCP с локального компьютера:**
```bash
# На вашем компьютере (не на сервере):
scp -r /path/to/nadexres root@your-server-ip:/var/www/nadexres
```

**Вариант 3: Загрузка архива:**
```bash
# На сервере:
cd /var/www/nadexres
wget https://link-to-your-archive/nadexres.tar.gz
tar -xzf nadexres.tar.gz
rm nadexres.tar.gz
```

---

## 🐍 Шаг 4: Установка Python зависимостей

### Создайте виртуальное окружение:
```bash
cd /var/www/nadexres
python3 -m venv venv
source venv/bin/activate
```

### Установите зависимости:
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

## ⚙️ Шаг 5: Конфигурация

### Создайте .env файл:
```bash
cp .env.example .env
nano .env
```

Заполните данными:
```env
BOT_TOKEN=ваш_токен_бота
ADMIN_ID=ваш_telegram_id
CMC_API_KEY=ваш_coinmarketcap_api_key
CRYPTO_PAY_TOKEN=ваш_cryptobot_token
HOST_BASE=https://ваш-домен.com
DATABASE_URL=postgresql+asyncpg://nadexres_user:your_secure_password@localhost:5432/nadexres
MIN_DEPOSIT_USDT=50
MIN_WITHDRAW_RUB=50000
```

Сохраните: `Ctrl+O`, `Enter`, `Ctrl+X`

### Инициализируйте базу данных:
```bash
source venv/bin/activate
python3 -c "from main import engine, Base; import asyncio; asyncio.run(engine.run_sync(Base.metadata.create_all))"
```

---

## 🔄 Шаг 6: Настройка systemd (автозапуск)

### Скопируйте service файл:
```bash
cp nadexres.service /etc/systemd/system/
```

### Отредактируйте пути если нужно:
```bash
nano /etc/systemd/system/nadexres.service
```

### Запустите сервис:
```bash
systemctl daemon-reload
systemctl enable nadexres
systemctl start nadexres
```

### Проверьте статус:
```bash
systemctl status nadexres
```

Вы должны увидеть: `Active: active (running)`

---

## 🌐 Шаг 7: Настройка Nginx

### Скопируйте конфигурацию:
```bash
cp nginx.conf /etc/nginx/sites-available/nadexres
```

### Отредактируйте домен:
```bash
nano /etc/nginx/sites-available/nadexres
# Замените "your-domain.com" на ваш домен
```

### Активируйте конфигурацию:
```bash
ln -s /etc/nginx/sites-available/nadexres /etc/nginx/sites-enabled/
nginx -t  # Проверка конфигурации
systemctl restart nginx
```

---

## 🔒 Шаг 8: Установка SSL (HTTPS)

### Получите сертификат Let's Encrypt:
```bash
certbot --nginx -d ваш-домен.com
```

Следуйте инструкциям на экране.

### Автообновление сертификата:
```bash
certbot renew --dry-run  # Тест
```

Certbot автоматически настроит обновление.

---

## 📱 Шаг 9: Настройка Telegram бота

### Установите webhook:
```bash
curl -X POST "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook" \
  -d "url=https://ваш-домен.com/webhook"
```

### Установите команды бота:
```bash
curl -X POST "https://api.telegram.org/bot<BOT_TOKEN>/setMyCommands" \
  -H "Content-Type: application/json" \
  -d '{
    "commands": [
      {"command": "start", "description": "Запустить приложение"},
      {"command": "help", "description": "Помощь"}
    ]
  }'
```

### Настройте Menu Button:
```bash
curl -X POST "https://api.telegram.org/bot<BOT_TOKEN>/setChatMenuButton" \
  -H "Content-Type: application/json" \
  -d '{
    "menu_button": {
      "type": "web_app",
      "text": "🚀 Открыть NadexRes",
      "web_app": {"url": "https://ваш-домен.com"}
    }
  }'
```

---

## ✅ Шаг 10: Проверка

### Проверьте работу приложения:
```bash
curl https://ваш-домен.com/health
# Ответ: {"ok": true}
```

### Проверьте логи:
```bash
# Логи приложения
journalctl -u nadexres -f

# Логи Nginx
tail -f /var/log/nginx/nadexres_access.log
tail -f /var/log/nginx/nadexres_error.log
```

### Откройте бота в Telegram:
1. Напишите `/start` вашему боту
2. Нажмите кнопку "🚀 Открыть NadexRes"
3. Приложение должно открыться

---

## 🛠️ Управление приложением

### Перезапуск:
```bash
systemctl restart nadexres
```

### Остановка:
```bash
systemctl stop nadexres
```

### Просмотр логов:
```bash
journalctl -u nadexres -n 100  # Последние 100 строк
journalctl -u nadexres -f      # В реальном времени
```

### Обновление кода:
```bash
cd /var/www/nadexres
git pull  # Если используете git
systemctl restart nadexres
```

---

## 🔐 Безопасность

### Настройте firewall:
```bash
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw enable
ufw status
```

### Ограничьте SSH доступ:
```bash
nano /etc/ssh/sshd_config
# Измените: PermitRootLogin no
# Добавьте: AllowUsers your_username
systemctl restart sshd
```

### Регулярные обновления:
```bash
apt update && apt upgrade -y
```

---

## 📊 Мониторинг

### Проверка использования ресурсов:
```bash
htop         # CPU, RAM
df -h        # Диск
free -h      # Память
```

### Бэкап базы данных:
```bash
# Создание бэкапа
pg_dump -U nadexres_user nadexres > backup_$(date +%Y%m%d).sql

# Восстановление
psql -U nadexres_user nadexres < backup_20231024.sql
```

---

## ❗ Решение проблем

### Приложение не запускается:
```bash
journalctl -u nadexres -n 50  # Смотрим ошибки
systemctl status nadexres
```

### Nginx показывает 502 Bad Gateway:
```bash
systemctl status nadexres  # Проверяем работает ли приложение
netstat -tlnp | grep 8000  # Проверяем порт
```

### База данных недоступна:
```bash
systemctl status postgresql
psql -h localhost -U nadexres_user -d nadexres
```

---

## 💰 Рекомендуемые VPS провайдеры

1. **Hetzner** - €4.15/мес (лучшее соотношение цена/качество)
2. **DigitalOcean** - $6/мес (простота использования)
3. **Vultr** - $6/мес (глобальные серверы)
4. **Contabo** - €4.99/мес (дешево, много ресурсов)

---

## 📞 Поддержка

Если возникли проблемы:
1. Проверьте логи приложения и nginx
2. Убедитесь что все сервисы запущены
3. Проверьте доступность домена и SSL
4. Проверьте переменные окружения в .env

---

✅ **Приложение готово к использованию 24/7!**
