let
    // ── Bebidas ──────────────────────────────────────────────────────────────
    Bebidas = Excel.CurrentWorkbook(){[Name="tbBebidas"]}[Content],
    BebidasTiped = Table.TransformColumnTypes(Bebidas, {
        {"Fardos",        type number},
        {"ItensPorFardo", type number},
        {"QtdAvulsa",     type number},
        {"Nome",          type text},
        {"PrecoUnitario", type number}
    }),
    BebidasFilled = Table.TransformColumns(BebidasTiped, {
        {"Fardos",        each if _ = null then 0 else _, type number},
        {"ItensPorFardo", each if _ = null then 0 else _, type number},
        {"QtdAvulsa",     each if _ = null then 0 else _, type number}
    }),
    BebidasResult = Table.SelectColumns(
        Table.AddColumn(BebidasFilled, "categoria", each "bebida"),
        {"categoria", "Nome", "Fardos", "ItensPorFardo", "QtdAvulsa", "PrecoUnitario"}
    ),

    // ── Doces ────────────────────────────────────────────────────────────────
    Doces = Excel.CurrentWorkbook(){[Name="tbDoces"]}[Content],
    DocesTiped = Table.TransformColumnTypes(Doces, {
        {"Fardos",        type number},
        {"ItensPorFardo", type number},
        {"QtdAvulsa",     type number},
        {"Nome",          type text},
        {"PrecoUnitario", type number}
    }),
    DocesFilled = Table.TransformColumns(DocesTiped, {
        {"Fardos",        each if _ = null then 0 else _, type number},
        {"ItensPorFardo", each if _ = null then 0 else _, type number},
        {"QtdAvulsa",     each if _ = null then 0 else _, type number}
    }),
    DocesResult = Table.SelectColumns(
        Table.AddColumn(DocesFilled, "categoria", each "doce"),
        {"categoria", "Nome", "Fardos", "ItensPorFardo", "QtdAvulsa", "PrecoUnitario"}
    ),

    // ── Salgados ─────────────────────────────────────────────────────────────
    Salgados = Excel.CurrentWorkbook(){[Name="tbSalgados"]}[Content],
    SalgadosTiped = Table.TransformColumnTypes(Salgados, {
        {"Fardos",        type number},
        {"ItensPorFardo", type number},
        {"QtdAvulsa",     type number},
        {"Nome",          type text},
        {"PrecoUnitario", type number}
    }),
    SalgadosFilled = Table.TransformColumns(SalgadosTiped, {
        {"Fardos",        each if _ = null then 0 else _, type number},
        {"ItensPorFardo", each if _ = null then 0 else _, type number},
        {"QtdAvulsa",     each if _ = null then 0 else _, type number}
    }),
    SalgadosResult = Table.SelectColumns(
        Table.AddColumn(SalgadosFilled, "categoria", each "salgado"),
        {"categoria", "Nome", "Fardos", "ItensPorFardo", "QtdAvulsa", "PrecoUnitario"}
    ),

    // ── União e cálculo de quantidade ────────────────────────────────────────
    All = Table.Combine({BebidasResult, DocesResult, SalgadosResult}),
    WithQty = Table.AddColumn(All, "quantidade",
        each [Fardos] * [ItensPorFardo] + [QtdAvulsa], type number),

    // ── Colunas finais para importação ───────────────────────────────────────
    Final = Table.RenameColumns(
        Table.SelectColumns(WithQty, {"categoria", "Nome", "quantidade", "PrecoUnitario"}),
        {{"Nome", "nome"}, {"PrecoUnitario", "preco_unitario"}}
    ),

    // ── Remove linhas sem nome (linhas vazias da tabela) ─────────────────────
    Filtered = Table.SelectRows(Final, each [nome] <> null and [nome] <> "")
in
    Filtered
