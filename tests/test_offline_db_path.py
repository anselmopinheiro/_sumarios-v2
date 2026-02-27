import os
import unittest
from pathlib import Path

from app import create_app
from offline_store import get_offline_db_path


class OfflineDbPathTests(unittest.TestCase):
    def test_offline_db_path_is_shared_between_engine_and_store(self):
        custom_offline = Path('custom_offline_for_test.db')
        custom_sqlite = Path('instance') / 'main_for_offline_path_test.db'

        previous_env = dict(os.environ)
        try:
            os.environ['APP_DB_MODE'] = 'sqlite'
            os.environ['SQLITE_PATH'] = str(custom_sqlite)
            os.environ['OFFLINE_DB_PATH'] = str(custom_offline)
            os.environ['BACKUP_ON_STARTUP'] = '0'
            os.environ['BACKUP_ON_COMMIT'] = '0'
            os.environ['DEV_LOCAL_SCHEDULER'] = '0'

            app = create_app()
            with app.app_context():
                resolved = get_offline_db_path(app.instance_path)
                engine_local_path = Path(app.extensions['engine_local'].url.database).resolve()

                self.assertEqual(engine_local_path, Path(resolved).resolve())
                self.assertEqual(Path(app.extensions['offline_db_path']).resolve(), Path(resolved).resolve())
        finally:
            os.environ.clear()
            os.environ.update(previous_env)


if __name__ == '__main__':
    unittest.main()
