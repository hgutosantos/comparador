# Comparador de produtos digitais

Indexa produtos de várias lojas, mostra com banner, categoria e preço, compara o mesmo
produto entre sites e exporta a tabela (CSV ou Excel) com data e hora. O link é sempre
o original da loja.

```
config/sites.yaml   quais sites indexar e como
config/rules.yaml   categorias unificadas, grupos de comparação e itens excluídos
scraper/            coletor (Python + Playwright)
docs/               site estático (GitHub Pages) + docs/data/products.json
.github/workflows/  atualização automática de hora em hora
rodar_local.py      modo local: atualiza ao abrir e serve em http://localhost:8765
```

## Opção A: online e grátis (GitHub Pages + Actions)

1. Crie um repositório **público** no GitHub (ex.: `hgutosantos/comparador`) e suba esta pasta.
   Repositório público = Actions ilimitado e Pages grátis.
2. Settings → Pages → Source: *Deploy from a branch*, branch `main`, pasta `/docs`.
3. Actions → "Atualizar produtos" → **Run workflow** para a primeira coleta.
4. Pronto: `https://hgutosantos.github.io/comparador/`. O workflow roda todo hora
   (o GitHub pode atrasar alguns minutos em horários de pico).

Produtos que saem de uma loja somem na coleta seguinte, então os links não ficam quebrados.
Se um site falhar, os dados anteriores dele ficam por até 6 h marcados como "dados antigos".

## Opção B: no seu computador

```
pip install -r requirements.txt
python -m playwright install chromium
python rodar_local.py
```
No Windows, basta dar dois cliques em `rodar_local.bat`. Ele atualiza se os dados tiverem
mais de 1 h, abre o navegador e continua atualizando de hora em hora enquanto a janela
estiver aberta. No celular (mesma rede Wi-Fi): `http://IP-DO-PC:8765`.

## Primeira execução: confira os padrões de link

Lupax e Pluffy usam a plataforma CentralCart (links `/package/...`) e já estão prontos.
Basefy, GGMAX, GMD Marketing e Geniuz Hints estão com `verify: true`: rode

```
python -m scraper.discover https://basefy.io/
```

e copie para o `product_link_regex` o padrão que leva à página de um produto.
Depois teste só esse site: `python -m scraper.main --only Basefy`.

## Adicionar um site

Copie um bloco em `config/sites.yaml`, rode o `discover` no site novo e ajuste.

## Comparação entre sites

O modo **Comparar** junta ofertas pelo grupo definido em `config/rules.yaml`
(ex.: tudo que tem "netflix" no nome vira o grupo Netflix). Adicione um grupo por produto
que você quer comparar.
