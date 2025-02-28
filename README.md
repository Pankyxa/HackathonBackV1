### .env file
```.env
JWT_SECRET=your-secret-key-here
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_HOST=database
POSTGRES_PORT=5432
POSTGRES_DB=your_database
SMTP_HOST=your-smtp-server
SMTP_PORT=25
SMTP_SENDER=your-sender@domain.com
SMTP_RECIPIENT=recipient@domain.com
```

### Запуск приложения
В корне проекта прописать
```sh
docker-compose up --build
```

### После запуска контейнеров
Запустить файл /src/init_database.py (пока так, потом добавлю, чтоб он автоматически прогонялся при запуске)