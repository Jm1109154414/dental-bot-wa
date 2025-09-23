# Imagen ligera de Python
FROM python:3.11-slim
WORKDIR /app

# Copia e instala dependencias
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copia el resto del código
COPY . .

# Exponer puerto que usa Render
EXPOSE 5000
# Comando para arrancar
CMD ["gunicorn", "bot:app", "--bind", "0.0.0.0:5000"]