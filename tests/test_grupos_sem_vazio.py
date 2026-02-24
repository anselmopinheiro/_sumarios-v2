import copy
import os
import sys
import tempfile
import unittest
from contextlib import suppress
from datetime import date


class GruposSemVazioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.sqlite_path = os.path.join(cls.tmpdir.name, "test_grupos.db")
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

    def _seed_trabalho_group(self, member_count):
        AnoLetivo = self.app_module.AnoLetivo
        Turma = self.app_module.Turma
        Aluno = self.app_module.Aluno
        Trabalho = self.app_module.Trabalho
        TrabalhoGrupo = self.app_module.TrabalhoGrupo
        TrabalhoGrupoMembro = self.app_module.TrabalhoGrupoMembro
        db = self.app_module.db

        ano = AnoLetivo(
            nome="2025/2026",
            data_inicio_ano=date(2025, 9, 1),
            data_fim_ano=date(2026, 7, 31),
            data_fim_semestre1=date(2026, 1, 31),
            data_inicio_semestre2=date(2026, 2, 1),
            ativo=True,
        )
        turma = Turma(nome="12A", tipo="regular", periodo_tipo="anual", ano_letivo=ano)
        alunos = [
            Aluno(turma=turma, numero=1, nome="Aluno Um"),
            Aluno(turma=turma, numero=2, nome="Aluno Dois"),
        ]
        trabalho = Trabalho(turma=turma, titulo="Atividade Teste", modo="grupo")
        grupo = TrabalhoGrupo(trabalho=trabalho, nome=f"Grupo-{member_count}")

        db.session.add_all([ano, turma, *alunos, trabalho, grupo])
        db.session.flush()

        for aluno in alunos[:member_count]:
            db.session.add(TrabalhoGrupoMembro(trabalho_grupo_id=grupo.id, aluno_id=aluno.id))

        db.session.commit()
        return {
            "turma_id": turma.id,
            "trabalho_id": trabalho.id,
            "grupo_id": grupo.id,
            "alunos": alunos,
            "grupo_nome": grupo.nome,
        }

    def test_remover_membro_com_grupo_de_dois_mantem_grupo(self):
        data_seed = self._seed_trabalho_group(member_count=2)
        aluno_id = data_seed["alunos"][0].id

        resp = self.client.post(
            f"/turmas/{data_seed['turma_id']}/trabalhos/{data_seed['trabalho_id']}/grupos/{data_seed['grupo_id']}/membros/{aluno_id}/remove",
            headers={"Accept": "application/json"},
        )
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["group_deleted"])
        self.assertFalse(payload["deleted"])
        self.assertEqual(payload["remaining"], 1)

        with self.flask_app.app_context():
            grupo = self.app_module.db.session.get(
                self.app_module.TrabalhoGrupo, data_seed["grupo_id"]
            )
            self.assertIsNotNone(grupo)
            membros = self.app_module.TrabalhoGrupoMembro.query.filter_by(
                trabalho_grupo_id=data_seed["grupo_id"]
            ).all()
            self.assertEqual(len(membros), 1)
            self.assertNotEqual(membros[0].aluno_id, aluno_id)

    def test_remover_ultimo_membro_apaga_grupo(self):
        data_seed = self._seed_trabalho_group(member_count=1)
        aluno_id = data_seed["alunos"][0].id

        resp = self.client.post(
            f"/turmas/{data_seed['turma_id']}/trabalhos/{data_seed['trabalho_id']}/grupos/{data_seed['grupo_id']}/membros/{aluno_id}/remove",
            headers={"Accept": "application/json"},
        )
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["group_deleted"])
        self.assertTrue(payload["deleted"])
        self.assertEqual(payload["remaining"], 0)

        with self.flask_app.app_context():
            grupo = self.app_module.db.session.get(
                self.app_module.TrabalhoGrupo, data_seed["grupo_id"]
            )
            membros_count = self.app_module.TrabalhoGrupoMembro.query.filter_by(
                trabalho_grupo_id=data_seed["grupo_id"]
            ).count()
            self.assertIsNone(grupo)
            self.assertEqual(membros_count, 0)

        refreshed = self.client.get(
            f"/turmas/{data_seed['turma_id']}/trabalhos/{data_seed['trabalho_id']}"
        )
        self.assertEqual(refreshed.status_code, 200)
        self.assertNotIn(data_seed["grupo_nome"], refreshed.get_data(as_text=True))

    def test_criar_grupo_sem_alunos_falha_com_400(self):
        data_seed = self._seed_trabalho_group(member_count=1)
        nome = "Grupo-Vazio"

        resp = self.client.post(
            f"/turmas/{data_seed['turma_id']}/trabalhos/{data_seed['trabalho_id']}/grupos",
            json={"nome": nome, "aluno_ids": []},
            headers={"Accept": "application/json"},
        )
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "Um grupo tem de ter, pelo menos, um aluno.")

        with self.flask_app.app_context():
            exists = self.app_module.TrabalhoGrupo.query.filter_by(
                trabalho_id=data_seed["trabalho_id"], nome=nome
            ).first()
            self.assertIsNone(exists)

    def test_criar_grupo_catalogo_sem_alunos_falha_com_400(self):
        data_seed = self._seed_trabalho_group(member_count=1)
        nome = "Catalogo-Vazio"

        resp = self.client.post(
            f"/turmas/{data_seed['turma_id']}/grupos",
            json={"nome": nome, "aluno_ids": []},
            headers={"Accept": "application/json"},
        )
        payload = resp.get_json()

        self.assertEqual(resp.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "Um grupo tem de ter, pelo menos, um aluno.")

        with self.flask_app.app_context():
            exists = self.app_module.GrupoTurma.query.filter_by(
                turma_id=data_seed["turma_id"], nome=nome
            ).first()
            self.assertIsNone(exists)


if __name__ == "__main__":
    unittest.main()
