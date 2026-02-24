import copy
import os
import sys
import tempfile
import unittest
from contextlib import suppress
from datetime import date


class OutrasDatasObservacoesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.sqlite_path = os.path.join(cls.tmpdir.name, "test_outras_datas.db")
        cls.backup_dir = os.path.join(cls.tmpdir.name, "backups")
        cls.exports_dir = os.path.join(cls.tmpdir.name, "exports")
        cls.backup_json_dir = os.path.join(cls.exports_dir, "backups")
        os.makedirs(cls.backup_dir, exist_ok=True)
        os.makedirs(cls.backup_json_dir, exist_ok=True)

        import app as app_module

        cls.app_module = app_module
        cls._config_backup = {
            "SQLALCHEMY_DATABASE_URI": app_module.Config.SQLALCHEMY_DATABASE_URI,
            "SQLALCHEMY_ENGINE_OPTIONS": copy.deepcopy(app_module.Config.SQLALCHEMY_ENGINE_OPTIONS),
            "SQLITE_PATH": app_module.Config.SQLITE_PATH,
            "DB_PATH": app_module.Config.DB_PATH,
            "APP_DB_MODE": app_module.Config.APP_DB_MODE,
            "BACKUP_ON_STARTUP": app_module.Config.BACKUP_ON_STARTUP,
            "BACKUP_ON_COMMIT": app_module.Config.BACKUP_ON_COMMIT,
            "BACKUP_DIR": app_module.Config.BACKUP_DIR,
            "CSV_EXPORT_DIR": app_module.Config.CSV_EXPORT_DIR,
            "BACKUP_JSON_DIR": app_module.Config.BACKUP_JSON_DIR,
        }

        app_module.Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{cls.sqlite_path}"
        app_module.Config.SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_pre_ping": True,
            "pool_recycle": 1800,
        }
        app_module.Config.SQLITE_PATH = cls.sqlite_path
        app_module.Config.DB_PATH = cls.sqlite_path
        app_module.Config.APP_DB_MODE = "sqlite"
        app_module.Config.BACKUP_ON_STARTUP = False
        app_module.Config.BACKUP_ON_COMMIT = False
        app_module.Config.BACKUP_DIR = cls.backup_dir
        app_module.Config.CSV_EXPORT_DIR = cls.exports_dir
        app_module.Config.BACKUP_JSON_DIR = cls.backup_json_dir

        argv_original = list(sys.argv)
        sys.argv = ["flask", "db"]
        try:
            cls.flask_app = app_module.create_app()
        finally:
            sys.argv = argv_original

        cls.flask_app.config.update(TESTING=True)
        cls.client = cls.flask_app.test_client()

    @classmethod
    def tearDownClass(cls):
        with cls.flask_app.app_context():
            cls.app_module.db.session.remove()
            with suppress(Exception):
                cls.app_module.db.engine.dispose()

        for engine_key in ("engine_local", "engine_remote"):
            engine = cls.flask_app.extensions.get(engine_key)
            if engine is not None:
                with suppress(Exception):
                    engine.dispose()

        for key, value in cls._config_backup.items():
            setattr(cls.app_module.Config, key, value)

        cls.tmpdir.cleanup()

    def setUp(self):
        self.app_ctx = self.flask_app.app_context()
        self.app_ctx.push()
        self.app_module.db.drop_all()
        self.app_module.db.create_all()

    def tearDown(self):
        self.app_module.db.session.remove()
        self.app_ctx.pop()

    def _seed_aula(self, fechado=False):
        AnoLetivo = self.app_module.AnoLetivo
        Turma = self.app_module.Turma
        Periodo = self.app_module.Periodo
        CalendarioAula = self.app_module.CalendarioAula
        db = self.app_module.db

        ano = AnoLetivo(
            nome="2025/2026",
            data_inicio_ano=date(2025, 9, 1),
            data_fim_ano=date(2026, 7, 31),
            data_fim_semestre1=date(2026, 1, 31),
            data_inicio_semestre2=date(2026, 2, 1),
            ativo=not fechado,
            fechado=fechado,
        )
        turma = Turma(nome="9.ºD", tipo="regular", periodo_tipo="anual", ano_letivo=ano)
        periodo = Periodo(
            turma=turma,
            nome="Anual",
            tipo="anual",
            data_inicio=date(2025, 9, 1),
            data_fim=date(2026, 7, 31),
        )
        db.session.add_all([ano, turma, periodo])
        db.session.flush()

        aula = CalendarioAula(
            turma=turma,
            periodo_id=periodo.id,
            data=date(2025, 10, 14),
            weekday=1,
            tipo="outros",
            observacoes=None,
            observacoes_html=None,
        )

        db.session.add(aula)
        db.session.commit()
        return aula.id

    def test_guarda_observacoes_sanitizadas(self):
        aula_id = self._seed_aula()
        html_raw = (
            '<p>Texto <strong>importante</strong></p>'
            '<script>alert("x")</script>'
            '<a href="javascript:alert(1)" onclick="x">link inseguro</a>'
            '<a href="https://example.com">link seguro</a>'
        )

        resp = self.client.post(
            f"/outras-datas/{aula_id}/observacoes",
            json={"observacoes_html": html_raw},
            headers={"Accept": "application/json"},
        )
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["saved_at"].endswith("Z"))

        aula = self.app_module.db.session.get(self.app_module.CalendarioAula, aula_id)
        self.assertIsNotNone(aula)
        saved_html = (aula.observacoes_html or "").lower()
        self.assertNotIn("<script", saved_html)
        self.assertNotIn("javascript:", saved_html)
        self.assertNotIn("onclick", saved_html)
        self.assertIn("texto", saved_html)
        self.assertIn("link seguro", saved_html)
        self.assertTrue((aula.observacoes or "").strip())

    def test_rejeita_payload_sem_campo_obrigatorio(self):
        aula_id = self._seed_aula()
        resp = self.client.post(
            f"/outras-datas/{aula_id}/observacoes",
            json={},
            headers={"Accept": "application/json"},
        )
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("observacoes_html", payload["error"])

    def test_rejeita_edicao_em_ano_fechado(self):
        aula_id = self._seed_aula(fechado=True)
        resp = self.client.post(
            f"/outras-datas/{aula_id}/observacoes",
            json={"observacoes_html": "<p>Teste</p>"},
            headers={"Accept": "application/json"},
        )
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("Ano letivo fechado", payload["error"])


if __name__ == "__main__":
    unittest.main()
