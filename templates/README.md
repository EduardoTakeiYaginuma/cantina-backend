# Templates de Cadastro de Produtos – Cantina

Este diretório contém os arquivos necessários para **cadastrar e importar produtos** no sistema da cantina.

---

## Arquivos

| Arquivo | Descrição |
|---|---|
| `produtos_template.xlsx` | Template Excel para preenchimento de produtos por categoria |
| `consolidado.csv` | Modelo CSV com o cabeçalho esperado pela importação |
| `power_query_consolidado.m` | Script M (Power Query) para gerar a aba Consolidado automaticamente |

---

## Como preencher as tabelas nas abas

1. Abra o arquivo `produtos_template.xlsx` no Excel (versão 2010 ou superior).
2. Navegue pelas abas: **Bebidas**, **Doces** e **Salgados**.
3. Em cada aba, preencha as colunas da tabela:

| Coluna | Descrição | Exemplo |
|---|---|---|
| `Fardos` | Quantidade de fardos/caixas | `2` |
| `ItensPorFardo` | Quantidade de itens por fardo/caixa | `12` |
| `QtdAvulsa` | Quantidade de itens avulsos (fora de fardo) | `5` |
| `Nome` | Nome do produto | `Refrigerante Cola 350ml` |
| `PrecoUnitario` | Preço unitário em reais | `3,50` |

> **Regras:**
> - Não altere os cabeçalhos das colunas.
> - Deixe em branco as linhas não utilizadas (não preencha com zero ou hífen).
> - Não preencha a coluna **categoria** – ela é calculada automaticamente pelo Consolidado.
> - A quantidade final no Consolidado será: `(Fardos × ItensPorFardo) + QtdAvulsa`.

---

## Como configurar o Power Query (Consolidado)

Siga os passos abaixo **uma única vez** para vincular o script ao arquivo.

### Passo a passo

1. Abra `produtos_template.xlsx` no Excel.
2. Vá em **Dados → Obter Dados → De Outras Fontes → Consulta em Branco**.
3. No **Power Query Editor**, clique em **Editor Avançado** (na faixa de opções).
4. Apague todo o conteúdo padrão (`let … in …`).
5. Abra o arquivo `power_query_consolidado.m` com um editor de texto e **copie todo o conteúdo**.
6. Cole o conteúdo no Editor Avançado e clique em **Concluído**.
7. Dê um nome à consulta (ex.: `Consolidado`) na barra lateral esquerda.
8. Clique em **Fechar e Carregar Para…** (não "Fechar e Carregar").
9. Escolha **Tabela Existente** e selecione a célula **A3** da aba **Consolidado**.
10. Clique em **OK** e aguarde o carregamento.
11. Salve o arquivo como `.xlsx` (**Ctrl+S**).

> **Atenção:** Ao salvar, o Excel pode avisar que o formato `.xlsx` não suporta todas as funcionalidades. Escolha **Manter no formato atual** (o Power Query é salvo corretamente em `.xlsx`).

### Script M completo

O script está disponível no arquivo [`power_query_consolidado.m`](./power_query_consolidado.m).

Ele realiza as seguintes operações:
- Importa as tabelas `tbBebidas`, `tbDoces` e `tbSalgados` do próprio arquivo.
- Garante tipos de dados corretos e trata células vazias como `0`.
- Remove linhas com `Nome` vazio.
- Calcula `quantidade = (Fardos × ItensPorFardo) + QtdAvulsa`.
- Adiciona a coluna `categoria` automaticamente (sem intervenção do usuário).
- Renomeia as colunas para o layout de importação: `categoria, nome, quantidade, preco_unitario`.
- Combina as três categorias em uma única tabela.

---

## Como atualizar o Consolidado (Atualizar Tudo)

Após preencher ou alterar dados nas abas de entrada:

1. Vá em **Dados → Atualizar Tudo** (atalho: **Ctrl+Alt+F5**).
2. Aguarde a atualização da consulta Power Query.
3. A aba **Consolidado** será preenchida automaticamente com todos os produtos.

---

## Como exportar a aba Consolidado para CSV

### Opção 1 – Salvar Como (mais simples)

1. Com o arquivo aberto, clique na aba **Consolidado**.
2. Vá em **Arquivo → Salvar Como**.
3. Escolha a pasta de destino.
4. Em **Tipo**, selecione **CSV UTF-8 (Delimitado por vírgula) (*.csv)**.
5. Clique em **Salvar** e confirme os avisos (o Excel avisa que o formato CSV não suporta múltiplas abas – isso é esperado).
6. O arquivo gerado estará pronto para importação no sistema.

### Opção 2 – Copiar apenas os dados

1. Na aba **Consolidado**, selecione todos os dados (**Ctrl+A**).
2. Copie (**Ctrl+C**).
3. Abra um editor de texto (ex.: Notepad++) e cole.
4. Salve com extensão `.csv` e encoding **UTF-8**.

---

## Formato CSV esperado para importação

O arquivo CSV deve ter o seguinte formato (separador: vírgula, sem espaços extras):

```
categoria,nome,quantidade,preco_unitario
bebidas,Refrigerante Cola 350ml,29,3.50
doces,Brigadeiro,50,2.00
salgados,Coxinha,30,4.50
```

> O modelo vazio está disponível em [`consolidado.csv`](./consolidado.csv).

---

## Dúvidas frequentes

**Q: Posso adicionar colunas extras nas tabelas?**
A: Não. Colunas extras serão ignoradas pelo Power Query e podem causar erros.

**Q: O Excel não tem a opção "Obter Dados"?**
A: Certifique-se de usar Excel 2016 ou superior. No Excel 2010/2013, utilize o suplemento **Power Query** (disponível gratuitamente no site da Microsoft).

**Q: O consolidado aparece em branco após atualizar.**
A: Verifique se o script M foi configurado corretamente (Passo a passo acima) e se os nomes das tabelas estão corretos: `tbBebidas`, `tbDoces`, `tbSalgados`.
