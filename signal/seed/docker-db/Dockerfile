# Dev/prod Postgres with BOTH PostGIS and pgvector (PRD §14 DB).
FROM postgis/postgis:16-3.4
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*

# Init into a SUBDIRECTORY of the volume mount. Railway (and most managed
# volumes) leave a lost+found at the mount root, which makes initdb refuse a
# "not empty" data dir and crash-loop. Pointing PGDATA one level down sidesteps
# it. Mount the volume at /var/lib/postgresql/data.
ENV PGDATA=/var/lib/postgresql/data/pgdata

