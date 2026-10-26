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

Quando `DATABASE_URL` estiver configurada, o sistema consulta prioritariamente o PostgreSQL para localizar a placa e preencher os cards de cavalo, carreta ou conjunto. A estrutura esperada possui as tabelas `vehicles` e `vehicle_catalog`, com as mesmas colunas usadas pelo Controle de Pátio.

Sem `DATABASE_URL`, o sistema usa `data/veiculos.xls`. A planilha deve manter as colunas `ID`, `PLACA`, `CHASSI`, `MARCA`, `MODELO`, `TIPO`, `STATUS OPERACIONAL` e `STATUS PRINCIPAL`.

Para configurar o PostgreSQL:

```powershell
$env:DATABASE_URL = 'postgres://usuario:senha@host:porta/banco?sslmode=require'
python server.py
```

No Render, cadastre `DATABASE_URL` em Environment como Secret. Não coloque a senha no código, no README ou no Git.

Para usar outra planilha, configure:

```powershell
$env:PATIO_VEICULOS_PATH = 'C:\caminho\veiculos.xls'
python server.py
```

O banco de ocupações e histórico é salvo em `C:\Users\Pixel Midia 3D\controle-patio-print\database\vagas_patio.db` por padrão, porque a pasta `D:\Print\vagas_patio` pode ser somente leitura em alguns computadores. Para salvar em outro local, use `VAGAS_PATIO_DB_PATH`.
