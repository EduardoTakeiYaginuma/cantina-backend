// ============================================================
// Power Query M – Consolidado de Produtos
// Arquivo: power_query_consolidado.m
//
// Como usar:
//   1. Abra o arquivo produtos_template.xlsx no Excel.
//   2. Vá em Dados → Obter Dados → De Outras Fontes → Consulta em Branco.
//   3. Na barra de fórmulas do Power Query Editor, clique em "Editor Avançado".
//   4. Apague o conteúdo padrão e cole TODO o código abaixo.
//   5. Clique em "Concluído" e depois em "Fechar e Carregar Para...".
//   6. Escolha "Tabela Existente" e selecione a célula A3 da aba Consolidado.
//   7. Salve o arquivo como .xlsx.
//   8. Para atualizar: Dados → Atualizar Tudo.
// ============================================================

let

    // ----------------------------------------------------------
    // 1. Importar cada tabela de origem
    // ----------------------------------------------------------
    Bebidas_Raw = Excel.CurrentWorkbook(){[Name="tbBebidas"]}[Content],
    Doces_Raw   = Excel.CurrentWorkbook(){[Name="tbDoces"]}[Content],
    Salgados_Raw= Excel.CurrentWorkbook(){[Name="tbSalgados"]}[Content],

    // ----------------------------------------------------------
    // 2. Função auxiliar: normalizar e enriquecer uma tabela
    //    Parâmetros:
    //      tbl      – tabela bruta
    //      categoria – texto da categoria ("bebidas" | "doces" | "salgados")
    // ----------------------------------------------------------
    ProcessarTabela = (tbl as table, categoria as text) as table =>
        let
            // Garantir tipos corretos (evita erros em células vazias)
            Tipado = Table.TransformColumnTypes(tbl, {
                {"Fardos",        type number},
                {"ItensPorFardo", type number},
                {"QtdAvulsa",     type number},
                {"Nome",          type text},
                {"PrecoUnitario", type number}
            }),

            // Substituir null por 0 nas colunas numéricas
            SemNull = Table.ReplaceValue(
                Table.ReplaceValue(
                    Table.ReplaceValue(Tipado,
                        null, 0, Replacer.ReplaceValue, {"Fardos"}),
                    null, 0, Replacer.ReplaceValue, {"ItensPorFardo"}),
                null, 0, Replacer.ReplaceValue, {"QtdAvulsa"}),

            // Remover linhas onde Nome está vazio
            SemVazios = Table.SelectRows(SemNull,
                each [Nome] <> null and Text.Trim([Nome]) <> ""),

            // Calcular quantidade total
            ComQtd = Table.AddColumn(SemVazios, "quantidade",
                each [Fardos] * [ItensPorFardo] + [QtdAvulsa],
                type number),

            // Adicionar coluna categoria
            ComCategoria = Table.AddColumn(ComQtd, "categoria",
                each categoria, type text),

            // Selecionar e renomear colunas para layout final
            Final = Table.SelectColumns(ComCategoria,
                {"categoria", "Nome", "quantidade", "PrecoUnitario"}),

            Renomeado = Table.RenameColumns(Final, {
                {"Nome",          "nome"},
                {"PrecoUnitario", "preco_unitario"}
            })
        in
            Renomeado,

    // ----------------------------------------------------------
    // 3. Processar cada categoria
    // ----------------------------------------------------------
    Bebidas  = ProcessarTabela(Bebidas_Raw,  "bebidas"),
    Doces    = ProcessarTabela(Doces_Raw,    "doces"),
    Salgados = ProcessarTabela(Salgados_Raw, "salgados"),

    // ----------------------------------------------------------
    // 4. Combinar as três tabelas
    // ----------------------------------------------------------
    Consolidado = Table.Combine({Bebidas, Doces, Salgados}),

    // ----------------------------------------------------------
    // 5. Garantir tipos finais
    // ----------------------------------------------------------
    TipoFinal = Table.TransformColumnTypes(Consolidado, {
        {"categoria",     type text},
        {"nome",          type text},
        {"quantidade",    type number},
        {"preco_unitario",type number}
    })

in
    TipoFinal
