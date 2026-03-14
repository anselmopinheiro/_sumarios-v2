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


def test_dt_ee_contactos_core_flow_and_csv_exports():
    db_path = ROOT / "instance" / "_test_dt_ee_contactos.db"
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
            "from app import create_app;"
            "from models import db, AnoLetivo, Turma, Aluno, DTTurma, TipoContacto, MotivoContacto;"
            "from datetime import date;"
            "app=create_app();"
            "ctx=app.app_context();ctx.push();"
            "ano=AnoLetivo(nome='2025/2026',data_inicio_ano=date(2025,9,1),data_fim_ano=date(2026,7,31),data_fim_semestre1=date(2026,1,31),data_inicio_semestre2=date(2026,2,1));"
            "db.session.add(ano);db.session.flush();"
            "turma=Turma(nome='10A',tipo='regular',periodo_tipo='anual',ano_letivo_id=ano.id,letiva=True);db.session.add(turma);db.session.flush();"
            "a1=Aluno(turma_id=turma.id,nome='Aluno Um',numero=1);a2=Aluno(turma_id=turma.id,nome='Aluno Dois',numero=2);a3=Aluno(turma_id=turma.id,nome='Aluno Tres',numero=3);"
            "db.session.add_all([a1,a2,a3]);db.session.flush();"
            "dt=DTTurma(turma_id=turma.id,ano_letivo_id=ano.id);db.session.add(dt);db.session.commit();"
            "c=app.test_client();"
            "r_ee1=c.post('/direcao-turma/ee',data={'nome':'EE A','email':'eea@example.com'});ee1=r_ee1.get_json()['id'];"
            "r_ee2=c.post('/direcao-turma/ee',data={'nome':'EE B','email':'eeb@example.com'});ee2=r_ee2.get_json()['id'];"
            "r_rel1=c.post('/direcao-turma/ee-alunos',data={'ee_id':ee1,'aluno_id':a1.id,'data_inicio':'2025-09-01','parentesco':'mae'});"
            "r_rel2=c.post('/direcao-turma/ee-alunos',data={'ee_id':ee1,'aluno_id':a2.id,'data_inicio':'2025-09-01','parentesco':'pai'});"
            "r_rel3=c.post('/direcao-turma/ee-alunos',data={'ee_id':ee2,'aluno_id':a3.id,'data_inicio':'2025-09-01','parentesco':'tutor'});"
            "r_rel_conflict=c.post('/direcao-turma/ee-alunos',data={'ee_id':ee2,'aluno_id':a1.id,'data_inicio':'2025-09-02'});"
            "r_cargo_ok=c.post('/direcao-turma/cargos/aluno',data={'dt_turma_id':dt.id,'aluno_id':a1.id,'cargo':'delegado','data_inicio':'2025-09-01'});"
            "r_cargo_dup=c.post('/direcao-turma/cargos/aluno',data={'dt_turma_id':dt.id,'aluno_id':a2.id,'cargo':'delegado','data_inicio':'2025-09-02'});"
            "tipo_id=TipoContacto.query.filter_by(nome='Email').first().id;"
            "motivo_id=MotivoContacto.query.filter_by(nome='Aproveitamento').first().id;"
            "payload={'dt_turma_id':dt.id,'aluno_ids':[a1.id,a2.id,a3.id],'tipo_contacto_ids':[tipo_id],'iniciado_por':'professor','estado_contacto':'realizado','por_aluno':{str(a1.id):{'motivos':[{'motivo_contacto_id':motivo_id,'detalhe':'A melhorar'}]},str(a2.id):{'motivos':[{'motivo_contacto_id':motivo_id,'detalhe':'Bom'}]},str(a3.id):{'motivos':[{'motivo_contacto_id':motivo_id,'detalhe':'Excelente'}]}}};"
            "r_lote=c.post('/direcao-turma/contactos/lote',json=payload);"
            "r_csv_ee=c.get(f'/direcao-turma/export/ee.csv?dt_turma_id={dt.id}&ativos=1');"
            "r_csv_contactos=c.get(f'/direcao-turma/export/contactos.csv?dt_turma_id={dt.id}&periodo=anual');"
            "print(json.dumps({'rel_ok':[r_rel1.status_code,r_rel2.status_code,r_rel3.status_code],'rel_conflict':r_rel_conflict.status_code,'cargo_ok':r_cargo_ok.status_code,'cargo_dup':r_cargo_dup.status_code,'lote_status':r_lote.status_code,'lote_created':len(r_lote.get_json().get('created_contactos',[])),'csv_ee':r_csv_ee.status_code,'csv_ee_has':('EE A' in r_csv_ee.get_data(as_text=True) and 'Aluno Um' in r_csv_ee.get_data(as_text=True)),'csv_contactos':r_csv_contactos.status_code,'csv_contactos_has':'Aproveitamento' in r_csv_contactos.get_data(as_text=True)}));"
        ),
    )

    assert result["rel_ok"] == [200, 200, 200]
    assert result["rel_conflict"] == 409
    assert result["cargo_ok"] == 200
    assert result["cargo_dup"] == 409
    assert result["lote_status"] == 200
    assert result["lote_created"] == 2
    assert result["csv_ee"] == 200
    assert result["csv_ee_has"]
    assert result["csv_contactos"] == 200
    assert result["csv_contactos_has"]
