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
```

### Запуск приложения
В корне проекта прописать
```sh
docker-compose up --build
```

### После запуска контейнеров
На винде потанцевать с бубнами меняв в .env host с database на localhost и обратно.
На линуксе/маке радоваться жизни