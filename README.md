### .env file
```.env
JWT_SECRET=your-secret-key-here
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_HOST=database
POSTGRES_PORT=5432
POSTGRES_DB=your_database
```

### Запуск приложения
В корне проекта прописать
```sh
docker-compose up --build
```

### После запуска контейнеров
Запустить файл /src/init_database.py (пока так, потом добавлю, чтоб он автоматически прогонялся при запуске)