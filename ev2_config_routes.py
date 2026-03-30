from __future__ import annotations

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError

from models import (
    Disciplina,
    EV2Assessment,
    EV2Domain,
    EV2Rubric,
    EV2SubjectConfig,
    EV2SubjectDomain,
    EV2SubjectRubric,
    Turma,
    db,
)


ev2_config_bp = Blueprint(
    "ev2_config",
    __name__,
    url_prefix="/ev2/config",
    template_folder="app/templates",
    static_folder="app/static",
)


def _wants_json() -> bool:
    if request.args.get("format") == "json":
        return True
    if request.is_json:
        return True
    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return bool(
        best == "application/json"
        and request.accept_mimetypes[best] > request.accept_mimetypes["text/html"]
    )


def _payload() -> dict:
    if request.is_json:
        return request.get_json(silent=True) or {}
    return request.form.to_dict(flat=True)


def _to_bool(value, default=True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "sim"}


def _as_int(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _error(message: str, status: int, redirect_endpoint: str | None = None):
    if _wants_json() or not redirect_endpoint:
        return jsonify({"error": message}), status
    flash(message, "error")
    return redirect(url_for(redirect_endpoint))


def _domain_to_dict(domain: EV2Domain) -> dict:
    return {
        "id": domain.id,
        "nome": domain.nome,
        "letra": getattr(domain, "letra", None),
        "codigo": getattr(domain, "codigo", None),
        "descricao": domain.descricao,
        "ativo": bool(domain.ativo),
        "rubricas_count": len(domain.rubricas),
    }


def _rubric_to_dict(rubric: EV2Rubric) -> dict:
    return {
        "id": rubric.id,
        "domain_id": rubric.domain_id,
        "domain_nome": rubric.dominio.nome if rubric.dominio else None,
        "codigo": rubric.codigo,
        "nome": rubric.nome,
        "descricao": rubric.descricao,
        "ativo": bool(rubric.ativo),
        "in_use_count": EV2Assessment.query.filter_by(rubric_id=rubric.id).count(),
    }


def _subject_profile_to_dict(profile: EV2SubjectConfig) -> dict:
    return {
        "id": profile.id,
        "turma_id": profile.turma_id,
        "turma_nome": profile.turma.nome if profile.turma else None,
        "disciplina_id": profile.disciplina_id,
        "disciplina_nome": profile.disciplina.nome if profile.disciplina else None,
        "nome": profile.nome,
        "ativo": bool(profile.ativo),
        "usar_ev2": bool(profile.usar_ev2),
        "escala_min": int(profile.escala_min or 1),
        "escala_max": int(profile.escala_max or 5),
        "rubricas_count": EV2SubjectRubric.query.filter_by(subject_config_id=profile.id).count(),
    }


def _subject_domain_to_dict(item: EV2SubjectDomain) -> dict:
    return {
        "id": item.id,
        "subject_config_id": item.subject_config_id,
        "domain_id": item.domain_id,
        "domain_nome": item.domain.nome if item.domain else None,
        "ordem": int(item.ordem or 0),
        "weight": float(item.weight or 0),
        "ativo": bool(item.ativo),
    }


def _unique_rubric_code(target_domain_id: int, candidate: str, exclude_id: int | None = None) -> str:
    base = (candidate or "").strip() or "RUB"
    base = base[:80]

    def exists(code: str) -> bool:
        q = EV2Rubric.query.filter(
            EV2Rubric.domain_id == target_domain_id,
            EV2Rubric.codigo == code,
        )
        if exclude_id is not None:
            q = q.filter(EV2Rubric.id != exclude_id)
        return q.first() is not None

    if not exists(base):
        return base

    idx = 2
    while idx < 1000:
        suffix = f"-{idx}"
        clipped = base[: max(1, 80 - len(suffix))]
        code = f"{clipped}{suffix}"
        if not exists(code):
            return code
        idx += 1
    return f"{base[:76]}-dup"


@ev2_config_bp.route("/profiles", methods=["GET", "POST"])
def ev2_profiles_collection():
    if request.method == "GET":
        turma_id = request.args.get("turma_id", type=int)
        prefill_nome = (request.args.get("prefill_nome") or "").strip()

        query = EV2SubjectConfig.query
        if turma_id:
            query = query.filter(EV2SubjectConfig.turma_id == turma_id)

        profiles = (
            query.order_by(
                EV2SubjectConfig.turma_id.asc(),
                EV2SubjectConfig.updated_at.desc(),
                EV2SubjectConfig.id.desc(),
            )
            .all()
        )
        turmas = Turma.query.order_by(Turma.nome.asc()).all()
        if _wants_json():
            return jsonify([_subject_profile_to_dict(item) for item in profiles])
        return render_template(
            "ev2/config/profiles.html",
            profiles=profiles,
            turmas=turmas,
            selected_turma_id=turma_id,
            prefill_nome=prefill_nome,
        )

    data = _payload()
    turma_id = _as_int(data.get("turma_id"))
    disciplina_id = _as_int(data.get("disciplina_id"))
    nome = (data.get("nome") or "").strip()
    ativo = _to_bool(data.get("ativo"), default=True)
    usar_ev2 = _to_bool(data.get("usar_ev2"), default=True)
    escala_min = _as_int(data.get("escala_min")) or 1
    escala_max = _as_int(data.get("escala_max")) or 5
    if escala_min >= escala_max:
        return _error("Escala inválida: o mínimo deve ser inferior ao máximo.", 400, "ev2_config.ev2_profiles_collection")

    if not turma_id or not nome:
        return _error(
            "Campos obrigatórios: turma_id, nome",
            400,
            "ev2_config.ev2_profiles_collection",
        )

    turma = Turma.query.get(turma_id)
    if not turma:
        return _error("Turma não encontrada.", 404, "ev2_config.ev2_profiles_collection")
    if not disciplina_id:
        disciplina_id = (turma.disciplinas[0].id if turma.disciplinas else None)
    disciplina = Disciplina.query.get(disciplina_id) if disciplina_id else None
    if not disciplina:
        return _error(
            "Sem disciplina associada à turma. Associa uma disciplina para criar o perfil EV2.",
            400,
            "ev2_config.ev2_profiles_collection",
        )

    profile = EV2SubjectConfig(
        turma_id=turma_id,
        disciplina_id=disciplina_id,
        nome=nome,
        ativo=ativo,
        usar_ev2=usar_ev2,
        escala_min=escala_min,
        escala_max=escala_max,
    )
    db.session.add(profile)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _error(
            "Já existe perfil com o mesmo nome para esta turma/disciplina.",
            409,
            "ev2_config.ev2_profiles_collection",
        )

    if _wants_json():
        return jsonify(_subject_profile_to_dict(profile)), 201
    flash("Perfil EV2 criado com sucesso.", "success")
    return redirect(url_for("ev2_config.ev2_profiles_collection"))


@ev2_config_bp.post("/profiles/<int:profile_id>/activate")
def ev2_profile_activate(profile_id: int):
    profile = EV2SubjectConfig.query.get(profile_id)
    if not profile:
        return _error("Perfil não encontrado.", 404, "ev2_config.ev2_profiles_collection")

    (
        EV2SubjectConfig.query
        .filter(
            EV2SubjectConfig.turma_id == profile.turma_id,
            EV2SubjectConfig.id != profile.id,
        )
        .update({"ativo": False}, synchronize_session=False)
    )
    profile.ativo = True
    profile.usar_ev2 = True
    db.session.commit()

    if _wants_json():
        return jsonify(_subject_profile_to_dict(profile))
    flash("Perfil ativado para a turma.", "success")
    return redirect(url_for("ev2_config.ev2_profiles_collection"))


@ev2_config_bp.route("/profiles/<int:profile_id>", methods=["GET"])
def ev2_profile_detail(profile_id: int):
    profile = EV2SubjectConfig.query.get(profile_id)
    if not profile:
        return _error("Perfil não encontrado.", 404, "ev2_config.ev2_profiles_collection")

    profile_domains = (
        EV2SubjectDomain.query
        .filter_by(subject_config_id=profile.id)
        .order_by(EV2SubjectDomain.ordem.asc(), EV2SubjectDomain.id.asc())
        .all()
    )
    domain_ids = [d.domain_id for d in profile_domains]
    rubrics_by_domain_id = {}
    if domain_ids:
        linked = (
            EV2SubjectRubric.query
            .join(EV2Rubric, EV2Rubric.id == EV2SubjectRubric.rubric_id)
            .filter(
                EV2SubjectRubric.subject_config_id == profile.id,
                EV2Rubric.domain_id.in_(domain_ids),
            )
            .order_by(EV2Rubric.domain_id.asc(), EV2SubjectRubric.ordem.asc(), EV2SubjectRubric.id.asc())
            .all()
        )
        for sr in linked:
            rubrics_by_domain_id.setdefault(sr.rubrica.domain_id, []).append(sr)

    all_domains = EV2Domain.query.order_by(EV2Domain.nome.asc()).all()
    all_rubrics = EV2Rubric.query.filter_by(ativo=True).order_by(EV2Rubric.codigo.asc()).all()

    if _wants_json():
        return jsonify({
            "profile": _subject_profile_to_dict(profile),
            "domains": [_subject_domain_to_dict(item) for item in profile_domains],
        })
    return render_template(
        "ev2/config/profile_detail.html",
        profile=profile,
        profile_domains=profile_domains,
        rubrics_by_domain_id=rubrics_by_domain_id,
        all_domains=all_domains,
        all_rubrics=all_rubrics,
    )


@ev2_config_bp.post("/profiles/<int:profile_id>/update")
def ev2_profile_update(profile_id: int):
    profile = EV2SubjectConfig.query.get(profile_id)
    if not profile:
        return _error("Perfil não encontrado.", 404, "ev2_config.ev2_profiles_collection")
    data = _payload()
    profile.nome = (data.get("nome") or profile.nome or "").strip() or profile.nome
    profile.escala_min = _as_int(data.get("escala_min")) or profile.escala_min or 1
    profile.escala_max = _as_int(data.get("escala_max")) or profile.escala_max or 5
    if profile.escala_min >= profile.escala_max:
        return _error("Escala inválida: o mínimo deve ser inferior ao máximo.", 400)
    db.session.commit()
    if _wants_json():
        return jsonify(_subject_profile_to_dict(profile))
    flash("Perfil atualizado.", "success")
    return redirect(url_for("ev2_config.ev2_profile_detail", profile_id=profile.id))


@ev2_config_bp.post("/profiles/<int:profile_id>/domains")
def ev2_profile_add_domain(profile_id: int):
    profile = EV2SubjectConfig.query.get(profile_id)
    if not profile:
        return _error("Perfil não encontrado.", 404, "ev2_config.ev2_profiles_collection")
    data = _payload()
    domain_id = _as_int(data.get("domain_id"))
    ordem = _as_int(data.get("ordem")) or 0
    weight = float(data.get("weight") or 0)
    if not domain_id:
        return _error("Campo obrigatório: domain_id", 400)
    if EV2SubjectDomain.query.filter_by(subject_config_id=profile.id, domain_id=domain_id).first():
        return _error("Domínio já associado ao perfil.", 409)
    domain = EV2Domain.query.get(domain_id)
    if not domain:
        return _error("Domínio não encontrado.", 404)
    item = EV2SubjectDomain(
        subject_config_id=profile.id,
        domain_id=domain_id,
        ordem=ordem,
        weight=weight,
        ativo=True,
    )
    db.session.add(item)
    db.session.flush()

    # Automação pedida: ao associar domínio ao perfil, importar rubricas base ativas
    # desse domínio (apenas neste momento, sem reimportações em updates do domínio).
    imported_count = 0
    base_rubrics = (
        EV2Rubric.query
        .filter_by(domain_id=domain_id, ativo=True)
        .order_by(EV2Rubric.codigo.asc(), EV2Rubric.id.asc())
        .all()
    )
    existing_rubric_ids = {
        rid for (rid,) in (
            db.session.query(EV2SubjectRubric.rubric_id)
            .filter(EV2SubjectRubric.subject_config_id == profile.id)
            .all()
        )
    }
    next_ordem = (
        db.session.query(db.func.max(EV2SubjectRubric.ordem))
        .filter(EV2SubjectRubric.subject_config_id == profile.id)
        .scalar()
        or 0
    )
    for idx, rubrica in enumerate(base_rubrics, start=1):
        if rubrica.id in existing_rubric_ids:
            continue
        db.session.add(
            EV2SubjectRubric(
                subject_config_id=profile.id,
                rubric_id=rubrica.id,
                subject_domain_id=item.id,
                ordem=int(next_ordem + idx),
                weight=0,
                scale_min=1,
                scale_max=5,
                ativo=True,
            )
        )
        imported_count += 1

    db.session.commit()
    if _wants_json():
        return jsonify({
            "domain": _subject_domain_to_dict(item),
            "rubrics_imported": imported_count,
        }), 201
    flash(f"Domínio associado ao perfil ({imported_count} rubricas importadas automaticamente).", "success")
    return redirect(url_for("ev2_config.ev2_profile_detail", profile_id=profile.id))


@ev2_config_bp.post("/profiles/<int:profile_id>/domains/<int:subject_domain_id>/update")
def ev2_profile_update_domain(profile_id: int, subject_domain_id: int):
    item = EV2SubjectDomain.query.get(subject_domain_id)
    if not item or item.subject_config_id != profile_id:
        return _error("Associação de domínio não encontrada.", 404, "ev2_config.ev2_profiles_collection")
    data = _payload()
    item.ordem = _as_int(data.get("ordem")) or 0
    item.weight = float(data.get("weight") or 0)
    item.ativo = _to_bool(data.get("ativo"), default=True)
    db.session.commit()
    if _wants_json():
        return jsonify(_subject_domain_to_dict(item))
    flash("Domínio do perfil atualizado.", "success")
    return redirect(url_for("ev2_config.ev2_profile_detail", profile_id=profile_id))


@ev2_config_bp.post("/profiles/<int:profile_id>/domains/<int:subject_domain_id>/delete")
def ev2_profile_remove_domain(profile_id: int, subject_domain_id: int):
    item = EV2SubjectDomain.query.get(subject_domain_id)
    if not item or item.subject_config_id != profile_id:
        return _error("Associação de domínio não encontrada.", 404, "ev2_config.ev2_profiles_collection")
    domain_id = item.domain_id
    EV2SubjectRubric.query.join(EV2Rubric, EV2Rubric.id == EV2SubjectRubric.rubric_id).filter(
        EV2SubjectRubric.subject_config_id == profile_id,
        EV2Rubric.domain_id == domain_id,
    ).delete(synchronize_session=False)
    db.session.delete(item)
    db.session.commit()
    if _wants_json():
        return jsonify({"status": "ok"})
    flash("Domínio removido do perfil.", "success")
    return redirect(url_for("ev2_config.ev2_profile_detail", profile_id=profile_id))


@ev2_config_bp.post("/profiles/<int:profile_id>/rubrics")
def ev2_profile_add_rubric(profile_id: int):
    profile = EV2SubjectConfig.query.get(profile_id)
    if not profile:
        return _error("Perfil não encontrado.", 404, "ev2_config.ev2_profiles_collection")
    data = _payload()
    rubric_id = _as_int(data.get("rubric_id"))
    if not rubric_id:
        return _error("Campo obrigatório: rubric_id", 400)
    rubrica = EV2Rubric.query.get(rubric_id)
    if not rubrica:
        return _error("Rubrica não encontrada.", 404)
    subject_domain = EV2SubjectDomain.query.filter_by(
        subject_config_id=profile.id,
        domain_id=rubrica.domain_id,
    ).first()
    if not subject_domain:
        return _error("Associe primeiro o domínio desta rubrica ao perfil.", 400)
    if EV2SubjectRubric.query.filter_by(subject_config_id=profile.id, rubric_id=rubric_id).first():
        return _error("Rubrica já associada ao perfil.", 409)
    item = EV2SubjectRubric(
        subject_config_id=profile.id,
        rubric_id=rubric_id,
        subject_domain_id=subject_domain.id,
        ordem=_as_int(data.get("ordem")) or 0,
        weight=float(data.get("weight") or 0),
        scale_min=int(profile.escala_min or 1),
        scale_max=int(profile.escala_max or 5),
        ativo=_to_bool(data.get("ativo"), default=True),
    )
    db.session.add(item)
    db.session.commit()
    if _wants_json():
        return jsonify({"id": item.id})
    flash("Rubrica associada ao perfil.", "success")
    return redirect(url_for("ev2_config.ev2_profile_detail", profile_id=profile.id))


@ev2_config_bp.post("/profiles/<int:profile_id>/rubrics/<int:subject_rubric_id>/update")
def ev2_profile_update_rubric(profile_id: int, subject_rubric_id: int):
    item = EV2SubjectRubric.query.get(subject_rubric_id)
    if not item or item.subject_config_id != profile_id:
        return _error("Associação de rubrica não encontrada.", 404, "ev2_config.ev2_profiles_collection")
    data = _payload()
    item.ordem = _as_int(data.get("ordem")) or 0
    item.weight = float(data.get("weight") or 0)
    profile = EV2SubjectConfig.query.get(profile_id)
    item.scale_min = int(profile.escala_min or 1) if profile else 1
    item.scale_max = int(profile.escala_max or 5) if profile else 5
    item.ativo = _to_bool(data.get("ativo"), default=True)
    db.session.commit()
    if _wants_json():
        return jsonify({"status": "ok"})
    flash("Rubrica do perfil atualizada.", "success")
    return redirect(url_for("ev2_config.ev2_profile_detail", profile_id=profile_id))


@ev2_config_bp.post("/profiles/<int:profile_id>/rubrics/<int:subject_rubric_id>/delete")
def ev2_profile_remove_rubric(profile_id: int, subject_rubric_id: int):
    item = EV2SubjectRubric.query.get(subject_rubric_id)
    if not item or item.subject_config_id != profile_id:
        return _error("Associação de rubrica não encontrada.", 404, "ev2_config.ev2_profiles_collection")
    db.session.delete(item)
    db.session.commit()
    if _wants_json():
        return jsonify({"status": "ok"})
    flash("Rubrica removida do perfil.", "success")
    return redirect(url_for("ev2_config.ev2_profile_detail", profile_id=profile_id))


@ev2_config_bp.route("/domains", methods=["GET", "POST"])
def ev2_domains_collection():
    if request.method == "GET":
        domains = EV2Domain.query.order_by(EV2Domain.nome.asc()).all()
        edit_domain = None
        edit_id = request.args.get("edit", type=int)
        if edit_id:
            edit_domain = EV2Domain.query.get(edit_id)
        if _wants_json():
            return jsonify([_domain_to_dict(item) for item in domains])
        return render_template("ev2/config/domains.html", domains=domains, edit_domain=edit_domain)

    data = _payload()
    nome = (data.get("nome") or "").strip()
    letra = (data.get("letra") or "").strip() or None
    codigo = (data.get("codigo") or "").strip() or None
    descricao = (data.get("descricao") or "").strip() or None
    ativo = _to_bool(data.get("ativo"), default=True)

    if not nome:
        return _error("Campo obrigatório: nome", 400, "ev2_config.ev2_domains_collection")

    entity = EV2Domain(nome=nome, letra=letra, codigo=codigo, descricao=descricao, ativo=ativo)
    db.session.add(entity)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _error("Já existe um domínio com esse nome.", 409, "ev2_config.ev2_domains_collection")

    if _wants_json():
        return jsonify(_domain_to_dict(entity)), 201
    flash("Domínio criado com sucesso.", "success")
    return redirect(url_for("ev2_config.ev2_domains_collection"))


@ev2_config_bp.post("/domains/duplicate")
def ev2_domain_duplicate():
    data = _payload()
    domain_id = _as_int(data.get("domain_id"))
    new_designation = (data.get("new_designation") or data.get("new_name") or data.get("nome") or "").strip()

    if not domain_id or not new_designation:
        return _error(
            "Campos obrigatórios: domain_id, new_designation",
            400,
            "ev2_config.ev2_domains_collection",
        )

    source = EV2Domain.query.get(domain_id)
    if not source:
        return _error("Domínio origem não encontrado.", 404, "ev2_config.ev2_domains_collection")

    if EV2Domain.query.filter(EV2Domain.nome == new_designation).first():
        return _error("Já existe domínio com essa designação.", 400, "ev2_config.ev2_domains_collection")

    clone = EV2Domain(
        nome=new_designation,
        letra=source.letra,
        codigo=source.codigo,
        descricao=source.descricao,
        ativo=source.ativo,
    )
    db.session.add(clone)
    db.session.flush()

    created_rubrics = []
    warnings = []
    source_rubrics = EV2Rubric.query.filter_by(domain_id=source.id).order_by(EV2Rubric.codigo.asc()).all()
    for rubrica in source_rubrics:
        final_code = _unique_rubric_code(clone.id, rubrica.codigo)
        if final_code != rubrica.codigo:
            warnings.append(
                f"Código '{rubrica.codigo}' ajustado para '{final_code}' no novo domínio."
            )
        new_rubrica = EV2Rubric(
            domain_id=clone.id,
            codigo=final_code,
            nome=rubrica.nome,
            descricao=rubrica.descricao,
            ativo=rubrica.ativo,
        )
        db.session.add(new_rubrica)
        db.session.flush()
        created_rubrics.append(_rubric_to_dict(new_rubrica))

    db.session.commit()

    payload = {
        "domain_id": clone.id,
        "domain": _domain_to_dict(clone),
        "rubricas": created_rubrics,
        "warnings": warnings,
    }
    if _wants_json():
        return jsonify(payload), 201

    flash(
        f"Domínio duplicado com sucesso ({len(created_rubrics)} rubricas copiadas).",
        "success",
    )
    if warnings:
        flash("; ".join(warnings), "warning")
    return redirect(url_for("ev2_config.ev2_domains_collection"))


@ev2_config_bp.route("/domains/<int:domain_id>", methods=["GET", "PUT", "DELETE", "POST"])
def ev2_domain_item(domain_id: int):
    domain = EV2Domain.query.get(domain_id)
    if not domain:
        return _error("Domínio não encontrado", 404, "ev2_config.ev2_domains_collection")

    method = request.method
    if method == "POST":
        override = (request.form.get("_method") or "").upper()
        if override in {"PUT", "DELETE"}:
            method = override
        else:
            return _error("Método não permitido", 405, "ev2_config.ev2_domains_collection")

    if method == "GET":
        if _wants_json():
            return jsonify(_domain_to_dict(domain))
        return render_template(
            "ev2/config/domains.html",
            domains=EV2Domain.query.order_by(EV2Domain.nome.asc()).all(),
            edit_domain=domain,
        )

    if method == "PUT":
        data = _payload()
        nome = (data.get("nome") or "").strip()
        letra = (data.get("letra") or "").strip() or None
        codigo = (data.get("codigo") or "").strip() or None
        descricao = (data.get("descricao") or "").strip() or None
        ativo = _to_bool(data.get("ativo"), default=True)

        if not nome:
            return _error("Campo obrigatório: nome", 400, "ev2_config.ev2_domains_collection")

        duplicate = EV2Domain.query.filter(
            EV2Domain.nome == nome,
            EV2Domain.id != domain.id,
        ).first()
        if duplicate:
            return _error("Já existe um domínio com esse nome.", 409, "ev2_config.ev2_domains_collection")

        domain.nome = nome
        domain.letra = letra
        domain.codigo = codigo
        domain.descricao = descricao
        domain.ativo = ativo
        db.session.commit()

        if _wants_json() or request.method != "POST":
            return jsonify(_domain_to_dict(domain))
        flash("Domínio atualizado com sucesso.", "success")
        return redirect(url_for("ev2_config.ev2_domains_collection"))

    has_rubrics = EV2Rubric.query.filter_by(domain_id=domain.id).count() > 0
    if has_rubrics:
        return _error(
            "Não é possível eliminar domínio com rubricas associadas.",
            400,
            "ev2_config.ev2_domains_collection",
        )

    db.session.delete(domain)
    db.session.commit()
    if _wants_json() or request.method != "POST":
        return jsonify({"status": "ok"})
    flash("Domínio eliminado com sucesso.", "success")
    return redirect(url_for("ev2_config.ev2_domains_collection"))


@ev2_config_bp.route("/rubricas", methods=["GET", "POST"])
def ev2_rubricas_collection():
    if request.method == "GET":
        rubricas = EV2Rubric.query.order_by(EV2Rubric.domain_id.asc(), EV2Rubric.codigo.asc()).all()
        domains = EV2Domain.query.order_by(EV2Domain.nome.asc()).all()
        edit_rubrica = None
        edit_id = request.args.get("edit", type=int)
        if edit_id:
            edit_rubrica = EV2Rubric.query.get(edit_id)
        selected_domain_id = request.args.get("domain_id", type=int)
        if _wants_json():
            return jsonify([_rubric_to_dict(item) for item in rubricas])
        return render_template(
            "ev2/config/rubricas.html",
            rubricas=rubricas,
            domains=domains,
            edit_rubrica=edit_rubrica,
            selected_domain_id=selected_domain_id,
        )

    data = _payload()
    domain_id = _as_int(data.get("domain_id"))
    codigo = (data.get("codigo") or "").strip()
    nome = (data.get("nome") or "").strip()
    descricao = (data.get("descricao") or "").strip() or None
    ativo = _to_bool(data.get("ativo"), default=True)

    if not domain_id or not codigo or not nome:
        return _error(
            "Campos obrigatórios: domain_id, codigo, nome",
            400,
            "ev2_config.ev2_rubricas_collection",
        )

    domain = EV2Domain.query.get(domain_id)
    if not domain:
        return _error("Domínio não encontrado", 404, "ev2_config.ev2_rubricas_collection")

    duplicate = EV2Rubric.query.filter_by(domain_id=domain_id, codigo=codigo).first()
    if duplicate:
        return _error(
            "Já existe rubrica com esse código neste domínio.",
            409,
            "ev2_config.ev2_rubricas_collection",
        )

    rubrica = EV2Rubric(
        domain_id=domain_id,
        codigo=codigo,
        nome=nome,
        descricao=descricao,
        ativo=ativo,
    )
    db.session.add(rubrica)
    db.session.commit()

    if _wants_json():
        return jsonify(_rubric_to_dict(rubrica)), 201
    flash("Rubrica criada com sucesso.", "success")
    return redirect(url_for("ev2_config.ev2_rubricas_collection"))


@ev2_config_bp.post("/rubricas/import")
def ev2_rubricas_import():
    data = _payload()
    source_domain_id = _as_int(data.get("source_domain_id"))
    target_domain_id = _as_int(data.get("target_domain_id"))

    if not source_domain_id or not target_domain_id:
        return _error(
            "Campos obrigatórios: source_domain_id, target_domain_id",
            400,
            "ev2_config.ev2_rubricas_collection",
        )

    if source_domain_id == target_domain_id:
        return _error(
            "Domínio origem e destino devem ser diferentes.",
            400,
            "ev2_config.ev2_rubricas_collection",
        )

    source = EV2Domain.query.get(source_domain_id)
    target = EV2Domain.query.get(target_domain_id)
    if not source or not target:
        return _error("Domínio origem/destino não encontrado.", 404, "ev2_config.ev2_rubricas_collection")

    warnings = []
    created = []
    source_rubrics = EV2Rubric.query.filter_by(domain_id=source.id).order_by(EV2Rubric.codigo.asc()).all()

    for rubrica in source_rubrics:
        final_code = _unique_rubric_code(target.id, rubrica.codigo)
        if final_code != rubrica.codigo:
            warnings.append(
                f"Código '{rubrica.codigo}' já existia no domínio de destino; usado '{final_code}'."
            )

        new_rubrica = EV2Rubric(
            domain_id=target.id,
            codigo=final_code,
            nome=rubrica.nome,
            descricao=rubrica.descricao,
            ativo=rubrica.ativo,
        )
        db.session.add(new_rubrica)
        db.session.flush()
        created.append(_rubric_to_dict(new_rubrica))

    db.session.commit()

    payload = {
        "source_domain_id": source.id,
        "target_domain_id": target.id,
        "rubricas": created,
        "warnings": warnings,
    }
    if _wants_json():
        return jsonify(payload), 201

    flash(f"Foram importadas {len(created)} rubricas para '{target.nome}'.", "success")
    if warnings:
        flash("; ".join(warnings), "warning")
    return redirect(url_for("ev2_config.ev2_rubricas_collection", domain_id=target.id))


@ev2_config_bp.route("/rubricas/<int:rubrica_id>", methods=["GET", "PUT", "DELETE", "POST"])
def ev2_rubrica_item(rubrica_id: int):
    rubrica = EV2Rubric.query.get(rubrica_id)
    if not rubrica:
        return _error("Rubrica não encontrada", 404, "ev2_config.ev2_rubricas_collection")

    method = request.method
    if method == "POST":
        override = (request.form.get("_method") or "").upper()
        if override in {"PUT", "DELETE"}:
            method = override
        else:
            return _error("Método não permitido", 405, "ev2_config.ev2_rubricas_collection")

    if method == "GET":
        if _wants_json():
            return jsonify(_rubric_to_dict(rubrica))
        return render_template(
            "ev2/config/rubricas.html",
            rubricas=EV2Rubric.query.order_by(EV2Rubric.domain_id.asc(), EV2Rubric.codigo.asc()).all(),
            domains=EV2Domain.query.order_by(EV2Domain.nome.asc()).all(),
            edit_rubrica=rubrica,
            selected_domain_id=rubrica.domain_id,
        )

    if method == "PUT":
        data = _payload()
        domain_id = _as_int(data.get("domain_id"))
        codigo = (data.get("codigo") or "").strip()
        nome = (data.get("nome") or "").strip()
        descricao = (data.get("descricao") or "").strip() or None
        ativo = _to_bool(data.get("ativo"), default=True)

        if not domain_id or not codigo or not nome:
            return _error(
                "Campos obrigatórios: domain_id, codigo, nome",
                400,
                "ev2_config.ev2_rubricas_collection",
            )

        domain = EV2Domain.query.get(domain_id)
        if not domain:
            return _error("Domínio não encontrado", 404, "ev2_config.ev2_rubricas_collection")

        unique_code = _unique_rubric_code(domain_id, codigo, exclude_id=rubrica.id)
        if unique_code != codigo:
            return _error(
                "Já existe rubrica com esse código neste domínio.",
                409,
                "ev2_config.ev2_rubricas_collection",
            )

        rubrica.domain_id = domain_id
        rubrica.codigo = codigo
        rubrica.nome = nome
        rubrica.descricao = descricao
        rubrica.ativo = ativo
        db.session.commit()

        if _wants_json() or request.method != "POST":
            return jsonify(_rubric_to_dict(rubrica))
        flash("Rubrica atualizada com sucesso.", "success")
        return redirect(url_for("ev2_config.ev2_rubricas_collection"))

    in_use = EV2Assessment.query.filter_by(rubric_id=rubrica.id).count()
    if in_use > 0:
        return _error(
            "Não é possível eliminar rubrica em uso em eventos/avaliações.",
            400,
            "ev2_config.ev2_rubricas_collection",
        )

    db.session.delete(rubrica)
    db.session.commit()
    if _wants_json() or request.method != "POST":
        return jsonify({"status": "ok"})
    flash("Rubrica eliminada com sucesso.", "success")
    return redirect(url_for("ev2_config.ev2_rubricas_collection"))
