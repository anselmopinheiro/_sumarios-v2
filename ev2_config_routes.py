from __future__ import annotations

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError

from models import EV2Domain, EV2Rubric, db


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
    descricao = (data.get("descricao") or "").strip() or None
    ativo = _to_bool(data.get("ativo"), default=True)

    if not nome:
        return _error("Campo obrigatório: nome", 400, "ev2_config.ev2_domains_collection")

    entity = EV2Domain(nome=nome, descricao=descricao, ativo=ativo)
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

    clone = EV2Domain(nome=new_designation, descricao=source.descricao, ativo=source.ativo)
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

    db.session.delete(rubrica)
    db.session.commit()
    if _wants_json() or request.method != "POST":
        return jsonify({"status": "ok"})
    flash("Rubrica eliminada com sucesso.", "success")
    return redirect(url_for("ev2_config.ev2_rubricas_collection"))
