# Vagas Pátio Jaraguá

Sistema separado para visualizar as vagas do Pátio Jaraguá, consultar veículos no banco existente e registrar o histórico diário de ocupação.

## Executar

```powershell
python server.py
```

Abra `http://localhost:8787`.

O banco de veículos usado por padrão é o SQLite do Controle de Pátio. Para apontar outro banco:

```powershell
$env:PATIO_DB_PATH = 'C:\caminho\patio.db'
python server.py
```

## Fonte de veículos

O sistema usa prioritariamente `data/veiculos.xls` para localizar a placa e preencher os cards de cavalo, carreta ou conjunto. A planilha fornecida deve manter as colunas `ID`, `PLACA`, `CHASSI`, `MARCA`, `MODELO`, `TIPO`, `STATUS OPERACIONAL` e `STATUS PRINCIPAL`.

Para usar outra planilha, configure:

```powershell
$env:PATIO_VEICULOS_PATH = 'C:\caminho\veiculos.xls'
python server.py
```

O banco de ocupações e histórico é salvo em `C:\Users\Pixel Midia 3D\controle-patio-print\database\vagas_patio.db` por padrão, porque a pasta `D:\Print\vagas_patio` pode ser somente leitura em alguns computadores. Para salvar em outro local, use `VAGAS_PATIO_DB_PATH`.
