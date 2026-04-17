FROM python:3.9-slim

WORKDIR /app

# تثبيت المكتبات
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ الملف الرئيسي
COPY main.py .

# فتح المنفذ
EXPOSE 8080

# تشغيل البوت
CMD ["python", "main.py"]
