#FROM python:3.12-slim
FROM python:3.12-slim-bookworm

# Driver ODBC pra SQL Server (msodbcsql18) — Oracle usa o modo thin
# do python-oracledb, então não precisa de Instant Client aqui.

####
#RUN apt-get update && apt-get install -y --no-install-recommends \
#        curl gnupg2 apt-transport-https ca-certificates \
#    && curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - \
#    && curl https://packages.microsoft.com/config/debian/12/prod.list \
#        > /etc/apt/sources.list.d/mssql-release.list \
#    && apt-get update \
#    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends \
#        msodbcsql18 unixodbc-dev \
#    && apt-get clean && rm -rf /var/lib/apt/lists/*
###

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        gnupg \
        ca-certificates && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | \
        gpg --dearmor -o /etc/apt/keyrings/microsoft.gpg && \
    echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
        > /etc/apt/sources.list.d/mssql-release.list && \
    apt-get update && \
    ACCEPT_EULA=Y apt-get install -y --no-install-recommends \
        msodbcsql18 \
        unixodbc-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic.ini .
COPY alembic ./alembic

EXPOSE 8590

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8590"]
