FROM postgis/postgis:16-3.5

RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list \
    && apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update \
    && apt-get install --yes --no-install-recommends postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*
