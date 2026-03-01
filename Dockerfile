# Используем Python 3.12
FROM python:3.12-slim-bookworm

WORKDIR /app

# 1. Сначала копируем ТОЛЬКО requirements.txt
# Это позволяет Docker кэшировать установку библиотек, если файл не менялся
COPY requirements.txt .

# 2. ВАЖНО: Обновляем pip и устанавливаем необходимые пакеты
# Устанавливаем setuptools с опцией --legacy-installation для обеспечения доступа к pkg_resources
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir setuptools==68.2.2 wheel

# 3. Устанавливаем остальные зависимости из файла
RUN pip install --no-cache-dir -r requirements.txt

# 4. Копируем остальной код проекта
COPY . .

EXPOSE 3000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "3000", "--reload"]