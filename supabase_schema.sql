-- Rode este script no Supabase: SQL Editor > New query > cole > Run.
-- O app usa a chave 'service_role' NO SERVIDOR (Render). Com RLS ligado e sem políticas, ninguém mais acessa essas tabelas.

create extension if not exists "pgcrypto";

create table if not exists public.pedidos (
  id      uuid primary key default gen_random_uuid(),
  criado  timestamptz not null default now(),
  nome    text not null,
  itens   jsonb not null,      -- lista de nomes, quantidades, fontes, furos, enfeites
  ajustes jsonb not null       -- tamanho, estilo, furo, qualidade...
);

create table if not exists public.predefinicoes (
  nome    text primary key,
  ajustes jsonb not null
);

alter table public.pedidos       enable row level security;
alter table public.predefinicoes enable row level security;

-- Buckets de Storage (privados)
insert into storage.buckets (id, name, public) values ('ponteiras-assets', 'ponteiras-assets', false) on conflict (id) do nothing;
insert into storage.buckets (id, name, public) values ('ponteiras-arquivos', 'ponteiras-arquivos', false) on conflict (id) do nothing;
