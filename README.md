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

O banco de ocupações e histórico é salvo em `C:\Users\Pixel Midia 3D\controle-patio-print\database\vagas_patio.db` por padrão, porque a pasta `D:\Print\vagas_patio` pode ser somente leitura em alguns computadores. Para salvar em outro local, use `VAGAS_PATIO_DB_PATH`.
