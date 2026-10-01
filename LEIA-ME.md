# Gerador de Ponteiras de Nomes para topo de lápis (Bambu Lab P1S · PLA · PEI)

Cada nome sai como **uma peça só**: letras 3D arredondadas, **fundidas entre si**, com um **furo para o lápis**
atravessando o nome inteiro (o lápis entra pelo furo). O furo pode ser **circular, hexagonal ou triangular abaloado**. Saída em **3MF para o Bambu Studio** (perfil P1S 0.4 + PLA Basic + Textured PEI, copiado do seu projeto).
É independente do projeto do boneco.

## Usar pela interface
Duplo clique em **`Abrir_Gerador.bat`**.

1. Digite o **nome**, a **quantidade** e, se quiser, uma **fonte só para esse nome** → *Adicionar*.
   (Vários de uma vez: *Adicionar vários...* · lista pronta: *Importar lista...*)
2. Ajuste à direita: fonte padrão, altura da letra, espessura, arredondado, traço, largura das letras, espaçamento,
   **diâmetro do furo** e **largura das pontes**. A **prévia** muda na hora, mostra o tamanho em mm e o furo (linhas azuis).
3. **Qualidade**: Rascunho 0,20 mm · Normal 0,10 mm · Alta 0,06 mm.
4. **GERAR PRATOS 3MF** → a pasta `saida/pedido_AAAA-MM-DD_HHMMSS/` abre sozinha, com `Ponteiras_prato_1.3mf`, `_2`...
   (as peças se distribuem em quantos pratos de 256 × 256 mm forem necessários).

Nomes já gerados com as mesmas configurações ficam em cache (`saida/stl/`): repetir é instantâneo.
Gerar vários nomes novos leva cerca de 1 minuto para 6 nomes (roda em paralelo).

## Linha de comando
```
python gerar_ponteiras.py --nomes "Helena:3, Ana Clara:2:ariblk, Bia"
python gerar_ponteiras.py --arquivo nomes_exemplo.csv --qualidade alta --furo 7.6
python gerar_ponteiras.py --listar-fontes
```
Formato: `Nome:quantidade:fonte:furo` (tudo depois do nome é opcional). Na linha de comando, escreva os símbolos entre chaves: `"{coracao}Ana{coracao}:2"` (no arquivo CSV e na tela vale `:coracao:`). Outras opções: `--estilo vazada|base|fechada`, `--borda`, `--fundo`, `--altura-borda`, `--manter-caixa`.

## Fontes, estilos, símbolos e imagens
- **Fontes**: a lista tem o grupo **★ Especiais** (por tema: *Script estilo Lobster/Disney*, *Infantil/Cartoon*, *Pixel (estilo Minecraft)*, *Pirata/Faroeste (estilo One Piece)*) e o grupo **Padrão (Windows)**. Cada fonte aparece escrita no próprio estilo e há busca. As especiais vêm do Google Fonts (licença livre) e estão na pasta `fontes/` (`bash baixar_fontes.sh` baixa de novo).
  As fontes oficiais do Minecraft e do logo do One Piece não são livres; use as equivalentes acima ou **Importar fonte...** (qualquer .ttf/.otf; aparece em **★ Importadas (suas)**).
- **Sugerir ajustes p/ esta fonte**: aplica engrossar, arredondado, largura e espaço adequados ao tipo (script precisa engrossar; pixel, blocos).
- **Estilo da letra**: *Fechada* (sólida) · *Vazada* (só o contorno; com *fundo* vira bandeja, com fundo 0 é vazada de lado a lado; pontes ligam os anéis) · *Com base / borda em degrau* (borda mais baixa em volta das letras).
- **Símbolos e imagens no nome**: digite `:coracao:`, `:flor:`, `:florzinha:`, `:estrela:`, `:coroa:`, `:borboleta:`... em qualquer ponto (início, meio, fim, nomes compostos): `ANA :coracao: CLARA`, `:coracao:HELENA:coracao:`. Botão **Símbolos e imagens...** insere no ponto do cursor.
  **Trocar letra por símbolo...** troca uma letra (todas, primeira ou última) por um símbolo ou imagem: `LOVE` -> `L:coracao:VE`.
- **Suas imagens (PNG/JPG)**: *Importar imagem* guarda em `imagens/` e cria o atalho `:nome_do_arquivo:`. PNG com transparência usa o contorno; JPG/PNG sem transparência usa o desenho escuro sobre fundo claro (ou claro sobre escuro). A imagem entra na altura das maiúsculas.
  Em **Enfeites** dá para pôr uma imagem/símbolo **antes e depois** de todos os nomes (e trocar por nome nas colunas Antes/Depois).
- Nomes em **MAIÚSCULAS** por padrão (as letras precisam ser mais altas que o furo); desmarque se usar uma fonte/enfeite que peça caixa mista.

## Caixa das letras e nome nos dois lados
- **Letras do nome** (painel da direita na versão desktop; logo abaixo da tabela de nomes no Studio): **MAIÚSCULAS · minúsculas · Primeira Maiúscula · Como digitado**. Os símbolos `:coracao:` não mudam. Minúsculas são mais baixas: confira se o furo cabe.
- **Nome legível nos dois lados (frente e verso)**: a metade de cima da peça traz o nome normal e a metade de baixo traz o mesmo nome de cabeça para baixo; ao girar o lápis 180° o outro lado também lê de pé. As duas metades se encaixam numa peça só. **Precisa de suporte na impressão** (a metade de cima fica em balanço onde a forma das letras difere). Linha de comando: `--caixa capitalizar --dois-lados`.

## Tipo de lápis e gabarito de teste
- **Tipo de lápis**: *Comum* (lápis de 7 a 7,5 mm; furo 8,0 / 7,5 / 7,5 mm; letra 11,5 mm; espessura 10,9 mm) ou *Jumbo* (10 a 10,5 mm; furo 10,8 / 10,4 / 10,6 mm; letra 15,5 mm; espessura 13,5 mm). Na linha de comando: `--lapis jumbo`.
- **Gabarito de teste do furo** (botão na interface, ou `python gerar_ponteiras.py --gabarito "7.0,7.2,7.4,7.6,7.8,8.0" --furo-formato hexagonal`):
  gera uma barrinha de 5 mm com um furo de cada medida, da esquerda (menor, marcada com o canto chanfrado) para a direita. Imprime em poucos minutos:
  o furo onde o **seu lápis** entra com leve atrito é a medida certa. Digite essa medida em *Medida do furo* (com folga 0).
  Faça um gabarito para cada formato de lápis que você usa.
- Como o PLA é rígido e o FDM costuma fechar o furo em 0,1 a 0,2 mm, é normal a medida final ser um pouco maior que a do lápis.

## Furo do lápis: formatos e medidas
| Formato | Medida (padrão) | O que a medida representa |
|---|---|---|
| Circular | 8,0 mm | diâmetro |
| Hexagonal | 7,5 mm | distância entre faces paralelas (o furo fica ~8,7 mm de canto a canto) |
| Triangular abaloado | 7,5 mm | altura (da face ao canto oposto); cantos com raio 1,2 mm (ajustável) |

- Em **"Medida do furo"** você digita a medida do seu lápis; em **"Folga extra"** soma uma folga (se as medidas acima forem do **lápis**, use 0,2 a 0,3 mm de folga; se já forem do **furo**, deixe 0).
- **"Girar furo"** gira o formato (o padrão deixa o hexágono com faces em cima/embaixo e o triângulo com a ponta para cima, que imprimem sem suporte).
- O formato também pode ser escolhido **por nome** (coluna "Furo do lápis"), para misturar lápis diferentes no mesmo pedido.
- A interface mostra o **corte (vista de ponta)** e a largura × altura real do furo, para você comparar com o paquímetro. Se o furo não deixar pelo menos 0,8 mm de parede, avisa.
- Pela linha de comando: `--furo-formato hexagonal --furo 7.5 --furo-folga 0.2 --furo-rot 0`, ou por nome: `"Bia:1::hexagonal"` (nome:qtd:fonte:furo).

## Como a peça é feita (medido no seu projeto original)
- Espessura 10,9 mm, letras de ~12 mm de altura, vistas de cima com os cantos arredondados; base plana (imprime direto na PEI, sem suporte).
- Furo aberto nas duas pontas, com eixo na altura das letras e 1 mm de parede embaixo (no original: circular de 8,0 mm).
- Letras compactas e **se tocando**; se sobrar letra ou acento solto, uma ponte de 2,4 mm liga ao conjunto (todas as peças saem inteiras, sem partes soltas).

## Observações
- O furo precisa caber na altura da letra (mínimo 0,8 mm de parede); a interface avisa.
- Usa o Blender instalado (sem abrir a interface) só para suavizar a malha. Se o caminho mudar, edite `BLENDER` em `ponteiras_core.py`.
- O estilo das letras vem da fonte: troque a fonte na interface até achar o visual. Fontes com traço grosso e arredondado ficam mais parecidas com o original.
