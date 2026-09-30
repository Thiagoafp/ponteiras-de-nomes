"""Acesso opcional ao Supabase (REST, sem SDK): histórico de pedidos, predefinições e arquivos (fontes/imagens/3MF).

Variáveis de ambiente (no Render ou em .streamlit/secrets.toml / ambiente local):
  SUPABASE_URL   ex.: https://xxxx.supabase.co
  SUPABASE_KEY   chave 'service_role' (fica só no servidor; NUNCA no navegador nem no GitHub)
Se não estiverem definidas, o app funciona normalmente, só sem histórico/predefinições na nuvem.
"""
import json
import os
from urllib.parse import quote

import requests

BUCKET_ASSETS = "ponteiras-assets"
BUCKET_ARQUIVOS = "ponteiras-arquivos"
TIMEOUT = 20


def _cfg():
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY", "")
    return (url, key) if url and key else (None, None)


def configurado():
    return _cfg()[0] is not None


def _h(extra=None):
    _, key = _cfg()
    h = {"apikey": key, "Authorization": f"Bearer {key}"}
    h.update(extra or {})
    return h


def _rest(metodo, tabela, params=None, corpo=None, prefer=None):
    url, _ = _cfg()
    h = _h({"Content-Type": "application/json"})
    if prefer:
        h["Prefer"] = prefer
    r = requests.request(metodo, f"{url}/rest/v1/{tabela}", headers=h, params=params, data=json.dumps(corpo) if corpo is not None else None,
                         timeout=TIMEOUT)
    if r.status_code >= 300:
        raise RuntimeError(f"Supabase {r.status_code}: {r.text[:300]}")
    return r.json() if r.text else None


# ----------------------------------------------------------------------------- pedidos e predefinições
def salvar_pedido(nome, itens, ajustes):
    return _rest("POST", "pedidos", corpo={"nome": nome, "itens": itens, "ajustes": ajustes}, prefer="return=representation")[0]


def listar_pedidos(limite=30):
    return _rest("GET", "pedidos", params={"select": "id,criado,nome,itens,ajustes", "order": "criado.desc", "limit": str(limite)})


def apagar_pedido(pid):
    _rest("DELETE", "pedidos", params={"id": f"eq.{pid}"})


def salvar_predefinicao(nome, ajustes):
    _rest("POST", "predefinicoes", params={"on_conflict": "nome"}, corpo={"nome": nome, "ajustes": ajustes},
          prefer="resolution=merge-duplicates,return=minimal")


def listar_predefinicoes():
    return _rest("GET", "predefinicoes", params={"select": "nome,ajustes", "order": "nome.asc"})


def apagar_predefinicao(nome):
    _rest("DELETE", "predefinicoes", params={"nome": f"eq.{nome}"})


# ----------------------------------------------------------------------------- arquivos (Storage)
def enviar_arquivo(bucket, caminho, dados: bytes, tipo="application/octet-stream"):
    url, _ = _cfg()
    r = requests.post(f"{url}/storage/v1/object/{bucket}/{quote(caminho)}", headers=_h({"Content-Type": tipo, "x-upsert": "true"}),
                      data=dados, timeout=TIMEOUT * 3)
    if r.status_code >= 300:
        raise RuntimeError(f"Storage {r.status_code}: {r.text[:300]}")


def listar_arquivos(bucket, pasta=""):
    url, _ = _cfg()
    r = requests.post(f"{url}/storage/v1/object/list/{bucket}", headers=_h({"Content-Type": "application/json"}),
                      data=json.dumps({"prefix": pasta, "limit": 500}), timeout=TIMEOUT)
    if r.status_code >= 300:
        raise RuntimeError(f"Storage {r.status_code}: {r.text[:300]}")
    return [x["name"] for x in r.json() if x.get("name") and x.get("id")]


def baixar_arquivo(bucket, caminho):
    url, _ = _cfg()
    r = requests.get(f"{url}/storage/v1/object/{bucket}/{quote(caminho)}", headers=_h(), timeout=TIMEOUT * 3)
    if r.status_code >= 300:
        raise RuntimeError(f"Storage {r.status_code}: {r.text[:200]}")
    return r.content


def link_temporario(bucket, caminho, segundos=3600):
    url, _ = _cfg()
    r = requests.post(f"{url}/storage/v1/object/sign/{bucket}/{quote(caminho)}", headers=_h({"Content-Type": "application/json"}),
                      data=json.dumps({"expiresIn": segundos}), timeout=TIMEOUT)
    if r.status_code >= 300:
        raise RuntimeError(f"Storage {r.status_code}: {r.text[:200]}")
    return url + "/storage/v1" + r.json()["signedURL"]


def sincronizar_assets(pasta_fontes, pasta_imagens):
    """Baixa do Storage as fontes e imagens que ainda não estão no disco (o disco do Render é temporário)."""
    if not configurado():
        return 0
    n = 0
    for sub, destino in (("fontes", pasta_fontes), ("imagens", pasta_imagens)):
        try:
            nomes = listar_arquivos(BUCKET_ASSETS, sub)
        except Exception:
            continue
        os.makedirs(destino, exist_ok=True)
        for nome in nomes:
            alvo = os.path.join(destino, nome)
            if not os.path.exists(alvo):
                try:
                    open(alvo, "wb").write(baixar_arquivo(BUCKET_ASSETS, f"{sub}/{nome}"))
                    n += 1
                except Exception:
                    pass
    return n
