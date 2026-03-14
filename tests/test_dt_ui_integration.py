import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_python_script(env_overrides, script):
    cmd = [sys.executable, "-c", script]
    env = os.environ.copy()
    env.update(env_overrides)
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, f"process failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    return json.loads(lines[-1])


def _run_flask_upgrade(env_overrides):
    env = os.environ.copy()
    env.update(env_overrides)
    cmd = ["flask", "--app", "app", "db", "upgrade"]
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, f"upgrade failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"


def test_dt_ui_routes_and_forms_are_navigable():
    db_path = ROOT / "instance" / "_test_dt_ui.db"
    if db_path.exists():
        db_path.unlink()

    env = {
        "APP_DB_MODE": "sqlite",
        "DATABASE_URL": "",
        "FLASK_ENV": "development",
        "SQLITE_PATH": str(db_path),
        "SKIP_DB_BOOTSTRAP": "1",
    }
    _run_flask_upgrade(env)

    result = _run_python_script(
        env,
        (
            "import json;"
            "from datetime import date;"
            "from app import create_app;"
            "from models import db, AnoLetivo, Turma, Aluno, DTTurma;"
            "app=create_app();ctx=app.app_context();ctx.push();"
            "ano=AnoLetivo(nome='2026/2027',data_inicio_ano=date(2026,9,1),data_fim_ano=date(2027,7,31),data_fim_semestre1=date(2027,1,31),data_inicio_semestre2=date(2027,2,1));"
            "db.session.add(ano);db.session.flush();"
            "turma=Turma(nome='11A',tipo='regular',periodo_tipo='anual',ano_letivo_id=ano.id,letiva=True);db.session.add(turma);db.session.flush();"
            "a1=Aluno(turma_id=turma.id,nome='Aluno X',numero=1);db.session.add(a1);db.session.flush();"
            "dt=DTTurma(turma_id=turma.id,ano_letivo_id=ano.id);db.session.add(dt);db.session.commit();"
            "c=app.test_client();"
            "c.post(f'/direcao-turma/{dt.id}/alunos/importar');"
            "r_alunos=c.get(f'/direcao-turma/{dt.id}/alunos');"
            "r_ee_list=c.get(f'/direcao-turma/{dt.id}/ee');"
            "r_ee_new=c.post(f'/direcao-turma/{dt.id}/ee/novo',data={'nome':'EE UI','email':'ui@example.com','submit_action':'save'},follow_redirects=False);r_ee_new_save_new=c.post(f'/direcao-turma/{dt.id}/ee/novo',data={'nome':'EE UI 2','email':'ui2@example.com','submit_action':'save_new'},follow_redirects=False);r_ee_new_save_back=c.post(f'/direcao-turma/{dt.id}/ee/novo',data={'nome':'EE UI 3','email':'ui3@example.com','submit_action':'save_back'},follow_redirects=False);"
            "r_ee_assign=c.post(f'/direcao-turma/{dt.id}/alunos/1/ee',data={'ee_id':1,'data_inicio':'2026-09-01','parentesco':'mae'},follow_redirects=False);"
            "r_ctx=c.post(f'/direcao-turma/{dt.id}/alunos/1/contexto',data={'dt_observacoes':'ok'},follow_redirects=False);"
            "r_hist=c.get(f'/direcao-turma/{dt.id}/alunos/1/ee/historico');r_ee_detail=c.get(f'/direcao-turma/{dt.id}/ee/1');"
            "r_contacto_form=c.get(f'/direcao-turma/{dt.id}/contactos/novo-lote');"
            "r_contactos=c.get(f'/direcao-turma/{dt.id}/contactos');"
            "r_cargos_a=c.get(f'/direcao-turma/{dt.id}/cargos/alunos');"
            "r_cargos_ee=c.get(f'/direcao-turma/{dt.id}/cargos/ee');"
            "print(json.dumps({'alunos':r_alunos.status_code,'has_links':('Contexto DT' in r_alunos.get_data(as_text=True) and 'Histórico EE' in r_alunos.get_data(as_text=True)),'ee_list':r_ee_list.status_code,'ee_new':r_ee_new.status_code,'ee_new_save_new':r_ee_new_save_new.status_code,'ee_new_save_back':r_ee_new_save_back.status_code,'ee_assign':r_ee_assign.status_code,'ctx_post':r_ctx.status_code,'hist':r_hist.status_code,'ee_detail':r_ee_detail.status_code,'ee_detail_has_actions':('Editar EE' in r_ee_detail.get_data(as_text=True) and 'Associar aluno' in r_ee_detail.get_data(as_text=True)),'contacto_form':r_contacto_form.status_code,'contactos':r_contactos.status_code,'cargos_a':r_cargos_a.status_code,'cargos_ee':r_cargos_ee.status_code}))"
        ),
    )

    assert result["alunos"] == 200
    assert result["has_links"]
    assert result["ee_list"] == 200
    assert result["ee_new"] in {301, 302, 303}
    assert result["ee_new_save_new"] in {301, 302, 303}
    assert result["ee_new_save_back"] in {301, 302, 303}
    assert result["ee_assign"] in {301, 302, 303}
    assert result["ctx_post"] in {301, 302, 303}
    assert result["hist"] == 200
    assert result["ee_detail"] == 200
    assert result["ee_detail_has_actions"]
    assert result["contacto_form"] == 200
    assert result["contactos"] == 200
    assert result["cargos_a"] == 200
    assert result["cargos_ee"] == 200
