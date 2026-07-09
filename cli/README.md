# aegis — CLI для ByteBurners Hosting

Утилита командной строки для управления хостингом из консоли. Без зависимостей
(только Python 3.8+ и стандартная библиотека).

## Установка
```bash
# из корня репозитория
sudo cp cli/aegis /usr/local/bin/aegis
sudo chmod +x /usr/local/bin/aegis
```

## Авторизация
```bash
# по логину/паролю (получит и сохранит сессионный токен):
aegis login --url http://SERVER:8000 --user admin --password '<пароль>'

# или сразу по админ-токену из .env:
aegis configure --url http://SERVER:8000 --token '<ADMIN_TOKEN>'
```
Настройки сохраняются в `~/.aegis/config.json` (права 600).

## Примеры
```bash
aegis vm list
aegis vm create my-vm --os ubuntu --cpu 2 --ram 4 --disk 40
aegis vm stop my-vm
aegis vm start my-vm
aegis vm delete my-vm

aegis clusters
aegis db
aegis deploy
aegis audit --failed          # последние отказы в журнале аудита
aegis audit --limit 50
```

Все команды ходят в тот же REST API, что и веб-панель, поэтому действия из CLI
так же попадают в «Логи аудита».
