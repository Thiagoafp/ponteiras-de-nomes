# Ponteiras de Nomes — versão web (Streamlit)

Mesma ferramenta da versão desktop, no navegador: visual moderno, **prévia 3D interativa** (gira e aproxima), tabela de nomes,
galeria de fontes, símbolos/imagens, gabarito de furo e download dos pratos 3MF (perfil P1S + PLA + Textured PEI).
No servidor não precisa de Blender: a malha é gerada por *marching cubes* (scikit-image).

## 1) Rodar no seu computador
```
cd ponteira_nomes
pip install -r requirements.txt
streamlit run app_web.py
```
Abre em http://localhost:8501. (Testado aqui: abas, prévia 2D e 3D, geração do pedido e vista 3D do prato.)

## 2) Publicar (GitHub + Render) — passo a passo
**GitHub**
1. Crie um repositório (ex.: `ponteiras-de-nomes`) **privado**.
2. Na pasta `ponteira_nomes`: `git init`, `git add .`, `git commit -m "versão web"`, `git remote add origin <URL>`, `git push -u origin main`.
   (O `.gitignore` já exclui `saida/`, `.env`, `secrets.toml` e arquivos temporários. As fontes da pasta `fontes/` têm licença livre OFL/Apache e podem ir junto.)

**Render**
1. Em render.com: *New > Blueprint* e escolha o repositório (usa o `render.yaml`), ou *New > Web Service* com:
   - Build: `pip install -r requirements.txt`
   - Start: `streamlit run app_web.py --server.port $PORT --server.address 0.0.0.0`
2. Em *Environment*, defina (todas opcionais, mas recomendadas):
   - `APP_PASSWORD` = senha de acesso ao app (sem ela, qualquer pessoa com o link usa o app)
   - `SUPABASE_URL` e `SUPABASE_KEY` (veja abaixo)
3. Memória: nomes longos em qualidade *Alta* usam bastante RAM. Se o Render reiniciar o serviço por falta de memória, use o plano com 2 GB
   ou a qualidade *Normal*/*Rascunho*.

## 3) Supabase (opcional): histórico, predefinições e arquivos que não se perdem
1. No Supabase: *SQL Editor > New query*, cole `supabase_schema.sql` e rode (cria as tabelas `pedidos` e `predefinicoes` e os buckets privados).
2. Em *Project Settings > API*, copie a **Project URL** (→ `SUPABASE_URL`) e a chave **service_role** (→ `SUPABASE_KEY`).
3. **Segurança:** a chave `service_role` dá acesso total ao banco. Coloque-a **somente** nas variáveis de ambiente do Render
   (ou em `.streamlit/secrets.toml` local, que o `.gitignore` já ignora). Nunca no GitHub nem no navegador. Mantenha o `APP_PASSWORD` ligado.
4. Com isso ativo, aparecem: aba **Histórico** (salvar/carregar/apagar pedidos), **Predefinições** na barra lateral e a sincronização das
   fontes/imagens que você importa (o disco do Render é temporário; o Storage guarda e o app baixa de novo ao reiniciar).

## Observações
- As fontes do Windows não existem no servidor; o app inclui 14 fontes comuns (`fontes/padrao/`) e 58 especiais (`fontes/`). Importe outras na aba Ferramentas.
- Os arquivos gerados ficam em `saida/web/<sessão>/` no servidor; baixe pelo botão (zip com 3MF + STL).
- Nada aqui foi publicado: GitHub, Render e Supabase são configurados por você com as suas contas.
