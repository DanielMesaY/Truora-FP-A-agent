-- supabase_schema.sql
-- Esquema mínimo para el agente. Ejecútalo en Supabase (SQL Editor).
-- Dos tablas: cifras mensuales (la "historia" que da el carácter acumulativo)
-- y los reportes generados.

create table if not exists monthly_financials (
    id            bigint generated always as identity primary key,
    compania      text not null,
    anio          int  not null,
    mes_idx       int  not null check (mes_idx between 1 and 12),
    mes           text not null,                 -- "Junio 2025"
    figures       jsonb not null,                -- dict de extract.py (18 líneas)
    created_at    timestamptz default now(),
    unique (compania, anio, mes_idx)             -- idempotencia: 1 fila por mes
);

create table if not exists monthly_reports (
    id            bigint generated always as identity primary key,
    compania      text not null,
    anio          int  not null,
    mes_idx       int  not null check (mes_idx between 1 and 12),
    verdict       text not null,                 -- MEJORA | DETERIORO | LINEA_BASE
    anotaciones   jsonb not null,                -- salida de la IA
    pdf_url       text,                           -- enlace en Drive / Storage
    created_at    timestamptz default now(),
    unique (compania, anio, mes_idx)
);

-- Recuperar la historia acumulada ANTES de analizar el mes N (orden cronológico):
--   select figures from monthly_financials
--   where compania = :compania and anio = :anio and mes_idx < :mes_idx
--   order by mes_idx asc;
