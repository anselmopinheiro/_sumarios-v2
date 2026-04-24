## Exportação GIAE JSON

- O endpoint de exportação GIAE deve manter um contrato JSON estável.
- O nome do ficheiro descarregado deve ser `sumarios_YYYY-MM-DD.json`, usando a data do sumário pedida no parâmetro `data`, não a data de geração.
- O campo `gerado_em` deve continuar a indicar o timestamp real de geração.
- O campo `turma` pode conter a designação composta usada no GIAE, por exemplo `8.ºC PM`, `DIC`, `LD`, `reun DAC`, `reun DIC` ou `co PADDE`; não separar automaticamente turma e disciplina.
- O campo `disciplina` pode ficar vazio.
- Cada aula deve incluir `modulo`, sempre como string; se não existir módulo, usar string vazia.
- Cada aula deve incluir, quando disponível, `tempo_inicio` e `blocos_previstos`, usados pela automação Playwright para localizar o bloco inicial no GIAE.
- A estrutura de `faltas` não deve ser alterada: `tempos: 2` significa falta aos dois tempos; `tempos: 1` significa falta apenas a um tempo.
- Não introduzir dependências EV2 neste endpoint.
