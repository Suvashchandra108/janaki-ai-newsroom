#!/bin/sh
# Runs once when the Postgres volume is first created. Creates the owner and RLS-enforced app roles.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
CREATE ROLE janaki_owner LOGIN PASSWORD '${DB_OWNER_PASSWORD}';
CREATE ROLE janaki_app LOGIN PASSWORD '${DB_APP_PASSWORD}' NOSUPERUSER NOBYPASSRLS;
CREATE DATABASE janaki OWNER janaki_owner;
SQL
