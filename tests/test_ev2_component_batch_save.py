import copy
import os
import sys
import tempfile
import unittest
from contextlib import suppress
from datetime import date


class EV2ComponentBatchSaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.sqlite_path = os.path.join(cls.tmpdir.name, "test_ev2_component_batch_save.db")
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

    def _seed_event(self, with_group=False):
        AnoLetivo = self.app_module.AnoLetivo
        Turma = self.app_module.Turma
        Disciplina = self.app_module.Disciplina
        Aluno = self.app_module.Aluno
        EV2Domain = self.app_module.EV2Domain
        EV2Rubric = self.app_module.EV2Rubric
        EV2RubricComponent = self.app_module.EV2RubricComponent
        EV2SubjectConfig = self.app_module.EV2SubjectConfig
        EV2Event = self.app_module.EV2Event
        EV2EventStudent = self.app_module.EV2EventStudent
        EV2EvaluationGroup = self.app_module.EV2EvaluationGroup
        EV2EvaluationGroupMember = self.app_module.EV2EvaluationGroupMember
        db = self.app_module.db

        ano = AnoLetivo(
            nome="2025/2026",
            data_inicio_ano=date(2025, 9, 1),
            data_fim_ano=date(2026, 7, 31),
            data_fim_semestre1=date(2026, 1, 31),
            data_inicio_semestre2=date(2026, 2, 1),
            ativo=True,
            fechado=False,
        )
        turma = Turma(nome="9D", tipo="regular", periodo_tipo="anual", ano_letivo=ano)
        disciplina = Disciplina(nome="Portugues", sigla="PT", ano_letivo=ano)
        aluno = Aluno(turma=turma, numero=1, nome="Aluno Teste")

        dominio = EV2Domain(nome="Conhecimento", letra="A", ativo=True)
        rubrica_componentes = EV2Rubric(
            dominio=dominio,
            codigo="R-COMP",
            nome="Rubrica com componentes",
            ordem=1,
            peso=0,
        )
        rubrica_simples = EV2Rubric(
            dominio=dominio,
            codigo="R-SIMP",
            nome="Rubrica simples",
            ordem=2,
            peso=0,
        )

        comp_1 = EV2RubricComponent(rubrica=rubrica_componentes, nome="Componente 1", ordem=1)
        comp_2 = EV2RubricComponent(rubrica=rubrica_componentes, nome="Componente 2", ordem=2)

        subject_config = EV2SubjectConfig(
            nome="Config teste",
            tipo="local_turma",
            disciplina=disciplina,
            usar_ev2=True,
            ativo=True,
        )
        event = EV2Event(
            subject_config=subject_config,
            disciplina=disciplina,
            evaluation_type="observacao_direta",
            titulo="Observacao teste",
            data=date(2025, 10, 20),
            group_mode="grupo" if with_group else "individual",
            peso_evento=100,
            extra_component_weight=0,
            config_snapshot={},
        )
        event_student = EV2EventStudent(
            event=event,
            aluno=aluno,
            tempos_totais=1,
            tempos_presentes=1,
            estado_assiduidade="presente_total",
            pontualidade_manual=True,
            elegivel_avaliacao=True,
        )
        group = None
        group_member = None
        if with_group:
            group = EV2EvaluationGroup(event=event, nome="Grupo A", ordem=1)
            group_member = EV2EvaluationGroupMember(group=group, aluno=aluno)
            event_student.group_key = group.nome

        items_to_add = [
            ano,
            turma,
            disciplina,
            aluno,
            dominio,
            rubrica_componentes,
            rubrica_simples,
            comp_1,
            comp_2,
            subject_config,
            event,
            event_student,
        ]
        if group is not None:
            items_to_add.append(group)
        if group_member is not None:
            items_to_add.append(group_member)

        db.session.add_all(items_to_add)
        db.session.commit()
        return {
            "aluno_id": aluno.id,
            "event_id": event.id,
            "event_student_id": event_student.id,
            "rubrica_componentes_id": rubrica_componentes.id,
            "rubrica_simples_id": rubrica_simples.id,
            "component_ids": [comp_1.id, comp_2.id],
            "group_id": group.id if group else None,
        }

    def _post_save_batch(self, event_id, payload):
        return self.client.post(
            f"/avaliacao/obser/{event_id}",
            json=payload,
            headers={"Accept": "application/json"},
        )

    def _duplicate_group_assignments(self, seed):
        return [
            {
                "aluno_id": seed["aluno_id"],
                "group_id": seed["group_id"],
            },
            {
                "aluno_id": seed["aluno_id"],
                "group_id": seed["group_id"],
            },
        ]

    def test_guarda_apenas_componentes_sem_rubrica_simples(self):
        seed = self._seed_event()

        response = self._post_save_batch(
            seed["event_id"],
            {
                "action": "save_batch",
                "scores": [
                    {
                        "aluno_id": seed["aluno_id"],
                        "rubrica_id": seed["rubrica_componentes_id"],
                        "valor": 0,
                        "component_scores": {
                            str(seed["component_ids"][0]): 4,
                        },
                    }
                ],
            },
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])

        assessment = self.app_module.EV2Assessment.query.filter_by(
            event_student_id=seed["event_student_id"],
            rubric_id=seed["rubrica_componentes_id"],
        ).one()
        component_scores = {
            score.component_id: int(score.score_level) for score in assessment.component_scores
        }

        self.assertEqual(assessment.state, "avaliado")
        self.assertEqual(float(assessment.score_numeric), 4.0)
        self.assertEqual(component_scores, {seed["component_ids"][0]: 4})
        self.assertEqual(payload["medias_por_aluno"][str(seed["aluno_id"])]["A"], 4.0)

    def test_guarda_componentes_e_rubrica_simples_no_mesmo_batch(self):
        seed = self._seed_event()

        response = self._post_save_batch(
            seed["event_id"],
            {
                "action": "save_batch",
                "scores": [
                    {
                        "aluno_id": seed["aluno_id"],
                        "rubrica_id": seed["rubrica_componentes_id"],
                        "valor": 99,
                        "component_scores": {
                            str(seed["component_ids"][0]): 2,
                            str(seed["component_ids"][1]): 4,
                        },
                    },
                    {
                        "aluno_id": seed["aluno_id"],
                        "rubrica_id": seed["rubrica_simples_id"],
                        "valor": 3.5,
                        "component_scores": {},
                    },
                ],
            },
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])

        assessments = self.app_module.EV2Assessment.query.filter_by(
            event_student_id=seed["event_student_id"]
        ).all()
        assessment_by_rubric = {assessment.rubric_id: assessment for assessment in assessments}

        self.assertEqual(len(assessment_by_rubric), 2)
        self.assertEqual(float(assessment_by_rubric[seed["rubrica_componentes_id"]].score_numeric), 3.0)
        self.assertEqual(float(assessment_by_rubric[seed["rubrica_simples_id"]].score_numeric), 3.5)
        self.assertEqual(payload["medias_por_aluno"][str(seed["aluno_id"])]["A"], 3.2)

    def test_regrava_componentes_sem_duplicar_scores_existentes(self):
        seed = self._seed_event()

        first_response = self._post_save_batch(
            seed["event_id"],
            {
                "action": "save_batch",
                "scores": [
                    {
                        "aluno_id": seed["aluno_id"],
                        "rubrica_id": seed["rubrica_componentes_id"],
                        "valor": 1,
                        "component_scores": {
                            str(seed["component_ids"][0]): 1,
                            str(seed["component_ids"][1]): 3,
                        },
                    }
                ],
            },
        )
        self.assertEqual(first_response.status_code, 200)

        second_response = self._post_save_batch(
            seed["event_id"],
            {
                "action": "save_batch",
                "scores": [
                    {
                        "aluno_id": seed["aluno_id"],
                        "rubrica_id": seed["rubrica_componentes_id"],
                        "valor": 1,
                        "component_scores": {
                            str(seed["component_ids"][0]): 5,
                            str(seed["component_ids"][1]): 4,
                        },
                    }
                ],
            },
        )
        payload = second_response.get_json()

        self.assertEqual(second_response.status_code, 200)
        self.assertTrue(payload["ok"])

        assessment = self.app_module.EV2Assessment.query.filter_by(
            event_student_id=seed["event_student_id"],
            rubric_id=seed["rubrica_componentes_id"],
        ).one()
        component_scores = sorted(
            (score.component_id, int(score.score_level)) for score in assessment.component_scores
        )

        self.assertEqual(float(assessment.score_numeric), 4.5)
        self.assertEqual(
            component_scores,
            [
                (seed["component_ids"][0], 5),
                (seed["component_ids"][1], 4),
            ],
        )

    def test_guarda_componente_com_group_assignments_duplicados_sem_duplicar_membership(self):
        seed = self._seed_event(with_group=True)

        response = self._post_save_batch(
            seed["event_id"],
            {
                "action": "save_batch",
                "scores": [
                    {
                        "aluno_id": seed["aluno_id"],
                        "rubrica_id": seed["rubrica_componentes_id"],
                        "valor": 0,
                        "component_scores": {
                            str(seed["component_ids"][0]): 4,
                        },
                    }
                ],
                "group_assignments": self._duplicate_group_assignments(seed),
            },
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        memberships = self.app_module.EV2EvaluationGroupMember.query.filter_by(
            group_id=seed["group_id"],
            aluno_id=seed["aluno_id"],
        ).all()
        self.assertEqual(len(memberships), 1)

    def test_repeated_saves_keep_single_group_membership(self):
        seed = self._seed_event(with_group=True)

        for value in (2, 5, 3):
            response = self._post_save_batch(
                seed["event_id"],
                {
                    "action": "save_batch",
                    "scores": [
                        {
                            "aluno_id": seed["aluno_id"],
                            "rubrica_id": seed["rubrica_componentes_id"],
                            "valor": 0,
                            "component_scores": {
                                str(seed["component_ids"][0]): value,
                            },
                        }
                    ],
                    "group_assignments": self._duplicate_group_assignments(seed),
                },
            )
            self.assertEqual(response.status_code, 200)

        memberships = self.app_module.EV2EvaluationGroupMember.query.filter_by(
            group_id=seed["group_id"],
            aluno_id=seed["aluno_id"],
        ).all()
        assessment = self.app_module.EV2Assessment.query.filter_by(
            event_student_id=seed["event_student_id"],
            rubric_id=seed["rubrica_componentes_id"],
        ).one()

        self.assertEqual(len(memberships), 1)
        self.assertEqual(float(assessment.score_numeric), 3.0)

    def test_rubrica_simples_continua_a_funcionar_com_group_assignments_duplicados(self):
        seed = self._seed_event(with_group=True)

        response = self._post_save_batch(
            seed["event_id"],
            {
                "action": "save_batch",
                "scores": [
                    {
                        "aluno_id": seed["aluno_id"],
                        "rubrica_id": seed["rubrica_simples_id"],
                        "valor": 4.5,
                        "component_scores": {},
                    }
                ],
                "group_assignments": self._duplicate_group_assignments(seed),
            },
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        memberships = self.app_module.EV2EvaluationGroupMember.query.filter_by(
            group_id=seed["group_id"],
            aluno_id=seed["aluno_id"],
        ).all()
        assessment = self.app_module.EV2Assessment.query.filter_by(
            event_student_id=seed["event_student_id"],
            rubric_id=seed["rubrica_simples_id"],
        ).one()

        self.assertEqual(len(memberships), 1)
        self.assertEqual(float(assessment.score_numeric), 4.5)


if __name__ == "__main__":
    unittest.main()
