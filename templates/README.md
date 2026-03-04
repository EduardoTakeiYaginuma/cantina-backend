# Templates de Cadastro de Produtos

Este diretório contém os arquivos necessários para o cadastro em lote de produtos da cantina.

## Arquivos

| Arquivo | Descrição |
|---|---|
| `produtos_template.xlsx` | Template Excel com 4 abas para preenchimento e geração do consolidado |
| `consolidado.csv` | Arquivo CSV com apenas os cabeçalhos usados na importação do sistema |
| `power_query_consolidado.m` | Expressão Power Query (M) para referência ou reimportação manual |
| `generate_template.py` | Script Python que regenera o `produtos_template.xlsx` a partir do zero |

---

## Como preencher o template

1. Abra o arquivo `produtos_template.xlsx` no **Microsoft Excel para Windows 2016+** ou **Excel para Mac 2019+**.
   > ⚠️ O Power Query (necessário para gerar o Consolidado automaticamente) **não está disponível no Excel Online** e tem suporte limitado em versões mais antigas.
2. Navegue até a aba correspondente à categoria do produto:
   - **Bebidas** → tabela `tbBebidas`
   - **Doces** → tabela `tbDoces`
   - **Salgados** → tabela `tbSalgados`
3. Preencha cada linha com um produto, respeitando as colunas:

   | Coluna | Descrição | Tipo |
   |---|---|---|
   | `Fardos` | Quantidade de fardos em estoque | Número inteiro ≥ 0 |
   | `ItensPorFardo` | Itens por fardo | Número inteiro ≥ 0 |
   | `QtdAvulsa` | Unidades avulsas além dos fardos | Número inteiro ≥ 0 |
   | `Nome` | Nome do produto (**obrigatório**) | Texto |
   | `PrecoUnitario` | Preço unitário de venda | Número decimal ≥ 0 (R$) |

   > **Cálculo de quantidade:** `quantidade = (Fardos × ItensPorFardo) + QtdAvulsa`  
   > Células numéricas em branco são tratadas como **0**.

4. As tabelas têm **50 linhas pré-formatadas**. Para adicionar mais linhas, basta digitar na linha imediatamente abaixo da última linha da tabela — o Excel expandirá a tabela automaticamente.

---

## Como atualizar/gerar o Consolidado

A aba **Consolidado** é populada automaticamente pela consulta **Power Query** embutida no arquivo.

### Passos

1. Após preencher as abas de entrada, clique na aba **Consolidado**.
2. No menu **Dados**, clique em **Atualizar Tudo** (ou pressione `Ctrl + Alt + F5`).
3. O Power Query vai:
   - Ler as três tabelas (`tbBebidas`, `tbDoces`, `tbSalgados`).
   - Adicionar a coluna `categoria` automaticamente (`bebida`, `doce` ou `salgado`).
   - Calcular a `quantidade` como `(Fardos × ItensPorFardo) + QtdAvulsa`.
   - Filtrar linhas sem `Nome` (linhas em branco são ignoradas).
   - Exibir as colunas finais: `categoria`, `nome`, `quantidade`, `preco_unitario`.

> **Nota:** O Power Query precisa ser configurado na primeira vez que o arquivo for aberto em uma máquina nova.  
> Veja a seção [Configurar Power Query pela primeira vez](#configurar-power-query-pela-primeira-vez) abaixo.

---

## Como exportar o Consolidado para CSV

1. Na aba **Consolidado**, selecione o intervalo de dados (cabeçalho + linhas geradas).
2. Vá em **Arquivo → Salvar uma Cópia → Navegar**.
3. Em "Tipo", selecione **CSV UTF-8 (delimitado por vírgula) (*.csv)**.
4. Salve o arquivo. Ele estará pronto para importação no sistema da cantina.

> O arquivo `consolidado.csv` neste diretório serve apenas como modelo de cabeçalho.  
> O CSV exportado do Excel substituirá seu conteúdo com os dados reais.

---

## Configurar Power Query pela primeira vez

Se a consulta não estiver presente no arquivo (ex.: arquivo regenerado pelo script Python),
siga os passos abaixo para importar a consulta manualmente:

1. Abra `produtos_template.xlsx` no Excel.
2. Vá em **Dados → Obter Dados → Iniciar Editor do Power Query**.
3. No Editor do Power Query, clique em **Página Inicial → Nova Consulta → Consulta Nula**.
4. No painel de fórmulas (barra `fx`), cole o conteúdo do arquivo `power_query_consolidado.m`.
5. Nomeie a consulta como **Consolidado**.
6. Clique em **Página Inicial → Fechar e Carregar em…** e escolha:
   - *Tabela* → aba **Consolidado** → célula onde a tabela deve começar.
7. Salve o arquivo.

---

## Regenerar o template via script

Caso precise gerar um novo arquivo do zero (por exemplo, após modificar colunas):

```bash
# No diretório raiz do repositório
python3 templates/generate_template.py
```

O script recria `produtos_template.xlsx`, `consolidado.csv` e `power_query_consolidado.m`.
