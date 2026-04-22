import os
import tempfile
import unittest
from datetime import date

from app import create_app
from models import Aluno, AnoLetivo, AulaAluno, CalendarioAula, Modulo, Periodo, Turma, db


class ApiExportGiaeJsonTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "test_giae_export.db")

        os.environ["APP_DB_MODE"] = "sqlite"
        os.environ["DATABASE_URL"] = ""
        os.environ["SQLITE_PATH"] = self.db_path
        os.environ["SKIP_DB_BOOTSTRAP"] = "1"

        self.app = create_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        self.tmpdir.cleanup()

    def _seed_base(self):
        ano = AnoLetivo(
            nome="2025/2026",
            data_inicio_ano=date(2025, 9, 1),
            data_fim_ano=date(2026, 7, 31),
            data_fim_semestre1=date(2026, 1, 31),
            data_inicio_semestre2=date(2026, 2, 1),
            ativo=True,
        )
        db.session.add(ano)
        db.session.flush()

        turma = Turma(nome="9.ºD", tipo="regular", periodo_tipo="anual", ano_letivo_id=ano.id, letiva=True)
        db.session.add(turma)
        db.session.flush()

        periodo = Periodo(
            nome="Anual",
            tipo="anual",
            data_inicio=date(2025, 9, 1),
            data_fim=date(2026, 7, 31),
            turma_id=turma.id,
        )
        db.session.add(periodo)
        db.session.flush()

        modulo = Modulo(turma_id=turma.id, nome="TIC", total_aulas=100)
        db.session.add(modulo)
        db.session.flush()

        return turma, periodo, modulo

    def test_missing_data_returns_400(self):
        res = self.client.get("/api/export/giae.json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json(), {"error": "Parâmetro 'data' em falta."})

    def test_invalid_data_returns_400(self):
        res = self.client.get("/api/export/giae.json?data=22-04-2026")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json(), {"error": "Data inválida. Use o formato YYYY-MM-DD."})

    def test_valid_date_without_classes_returns_empty_list(self):
        self._seed_base()
        db.session.commit()

        res = self.client.get("/api/export/giae.json?data=2026-04-22")
        self.assertEqual(res.status_code, 200)
        payload = res.get_json()
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["data"], "2026-04-22")
        self.assertEqual(payload["origem"], "sumarios-v1")
        self.assertEqual(payload["aulas"], [])

    def test_valid_date_with_classes_returns_expected_contract(self):
        turma, periodo, modulo = self._seed_base()

        aluno_1 = Aluno(turma_id=turma.id, nome="Aluno Um", numero=10)
        aluno_2 = Aluno(turma_id=turma.id, nome="Aluno Dois", numero=3)
        db.session.add_all([aluno_1, aluno_2])
        db.session.flush()

        aula = CalendarioAula(
            turma_id=turma.id,
            periodo_id=periodo.id,
            data=date(2026, 4, 22),
            weekday=2,
            modulo_id=modulo.id,
            tipo="normal",
            apagado=False,
            sumario="<p>  Texto\n do  <b>sumário</b> </p>",
        )
        db.session.add(aula)
        db.session.flush()

        falta_1 = AulaAluno(aula_id=aula.id, aluno_id=aluno_1.id, faltas=1, atraso=False, observacoes=None)
        falta_2 = AulaAluno(aula_id=aula.id, aluno_id=aluno_2.id, faltas=0, atraso=True, observacoes=None)
        db.session.add_all([falta_1, falta_2])
        db.session.commit()

        res = self.client.get("/api/export/giae.json?data=2026-04-22")
        self.assertEqual(res.status_code, 200)
        self.assertIn("application/json", res.headers.get("Content-Type", ""))
        content_disposition = res.headers.get("Content-Disposition", "")
        self.assertIn("attachment", content_disposition)
        self.assertIn("sumarios_2026-04-22.json", content_disposition)

        payload = res.get_json()
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["data"], "2026-04-22")
        self.assertEqual(payload["origem"], "sumarios-v1")

        self.assertEqual(len(payload["aulas"]), 1)
        aula_payload = payload["aulas"][0]
        self.assertEqual(aula_payload["aula_id"], aula.id)
        self.assertEqual(aula_payload["turma"], "9.ºD")
        self.assertEqual(aula_payload["disciplina"], "TIC")
        self.assertEqual(aula_payload["hora_inicio"], "")
        self.assertEqual(aula_payload["hora_fim"], "")
        self.assertEqual(aula_payload["sumario"], "Texto do sumário")

        faltas = aula_payload["faltas"]
        self.assertEqual([f["numero"] for f in faltas], [3, 10])
        self.assertEqual(faltas[0]["tipo"], "atraso")
        self.assertEqual(faltas[0]["tempos"], 0)
        self.assertEqual(faltas[0]["observacoes"], "")
        self.assertEqual(faltas[1]["tipo"], "falta")
        self.assertEqual(faltas[1]["tempos"], 1)
        self.assertEqual(faltas[1]["observacoes"], "")


if __name__ == "__main__":
    unittest.main()
