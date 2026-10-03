FROM python:3.13-slim
WORKDIR /opt/verivision
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY run.py .
COPY data ./data
COPY demo_assets ./demo_assets
EXPOSE 8000
CMD ["python","run.py"]
