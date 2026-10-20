import io
import zipfile

CREDENTIALS = {'db_type': 'oracle', 'host': 'db.invalid', 'port': 1521,
               'service_name': 'synthetic', 'user': 'test_user', 'password': 'SYNTHETIC_SECRET'}
LOG = '''##ID_1##
tempo: 150 (ms)
/* Runtime-info
Application: Teste
ResourceID: sintético
uri: /teste
*/
select * from teste where id = ? and nome = ?
Params:
  1 = 42
  2 = D'Ávila
---
##ID_2##
tempo: 50 (ms)
/* Runtime-info
Application: Teste
ResourceID: sintético
*/
select 1
'''


def archive(entries=None, compression=zipfile.ZIP_DEFLATED):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=compression) as zf:
        for name, content in (entries if entries is not None else [('Monitor_Consulta.log', LOG)]):
            zf.writestr(name, content)
    return output.getvalue()
