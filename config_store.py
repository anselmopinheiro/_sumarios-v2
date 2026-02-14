import json
import logging
import os
import time
import uuid


class ConfigStore:
    def __init__(self, instance_path, logger=None):
        self.base_dir = os.path.join(instance_path, "config")
        self.logger = logger or logging.getLogger(__name__)

    def _ensure_dir(self):
        os.makedirs(self.base_dir, exist_ok=True)

    def _path(self, filename):
        return os.path.join(self.base_dir, filename)

    def read_json(self, filename, default=None):
        self._ensure_dir()
        path = self._path(filename)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
                if isinstance(payload, dict):
                    return payload
        except FileNotFoundError:
            return default
        except (OSError, json.JSONDecodeError) as exc:
            self.logger.warning("JSON inválido em %s: %s", path, exc)
            return default
        return default

    def write_json(self, filename, payload, tentativas=6, atraso=0.2):
        self._ensure_dir()
        path = self._path(filename)
        tmp_path = f"{path}.{uuid.uuid4().hex}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())

        ultimo_erro = None
        for tentativa in range(tentativas):
            try:
                os.replace(tmp_path, path)
                return True
            except OSError as exc:
                ultimo_erro = exc
                self.logger.warning(
                    "Falha ao gravar %s (tentativa %s): %s",
                    path,
                    tentativa + 1,
                    exc,
                )
                time.sleep(atraso * (2 ** tentativa))
        self.logger.warning("Não foi possível gravar %s: %s", path, ultimo_erro)
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            self.logger.warning("Não foi possível remover tmp %s", tmp_path)
        return False
