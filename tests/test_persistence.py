import os
import unittest
from unittest.mock import patch


class PersistenceTests(unittest.TestCase):
    def tearDown(self):
        from app.persistence.database import close_database

        close_database()

    def test_database_is_optional_for_legacy_flow(self):
        from app.config import Settings
        from app.persistence.database import DatabaseNotConfigured, get_engine

        with self.assertRaises(DatabaseNotConfigured):
            get_engine(Settings(database_url=None))

    def test_engine_uses_configured_pool_without_logging_url(self):
        from app.config import Settings
        from app.persistence import database

        config = Settings(database_url="sqlite+pysqlite:///:memory:", db_pool_size=2)
        engine = database.get_engine(config)
        self.assertEqual(engine.url.get_backend_name(), "sqlite")
        self.assertNotIn("sqlite+pysqlite", database.logger.name)
        database.close_database()

    def test_first_session_initialization_is_reentrant_and_closes_database(self):
        from app.config import Settings
        from app import persistence as database_api
        from app.persistence import database

        config = Settings(database_url="sqlite+pysqlite:///:memory:")
        database.close_database()
        # Este caminho começa sem engine/factory e exercita a chamada aninhada
        # _get_session_factory -> get_engine sob o mesmo bloqueio.
        with database_api.session_scope(config) as session:
            self.assertIsNotNone(session.bind)
        self.assertIsNotNone(database._engine)
        self.assertIsNotNone(database._session_factory)
        database_api.close_database()
        self.assertIsNone(database._engine)
        self.assertIsNone(database._session_factory)

    def test_session_scope_rolls_back_and_closes_on_failure(self):
        from app.persistence import database

        class FakeSession:
            def __init__(self):
                self.rollback_called = False
                self.close_called = False

            def commit(self):
                raise RuntimeError("synthetic failure")

            def rollback(self):
                self.rollback_called = True

            def close(self):
                self.close_called = True

        fake = FakeSession()
        with patch.object(database, "_get_session_factory", return_value=lambda: fake):
            with self.assertLogs("app.persistence.database", level="ERROR") as captured:
                with self.assertRaises(RuntimeError):
                    with database.session_scope():
                        pass
        self.assertTrue(fake.rollback_called)
        self.assertTrue(fake.close_called)
        self.assertNotIn("synthetic failure", "\n".join(captured.output))

    def test_database_url_is_read_from_environment(self):
        from app.config import Settings

        with patch.dict(os.environ, {"DATABASE_URL": "sqlite+pysqlite:///:memory:"}, clear=False):
            config = Settings()
        self.assertEqual(config.database_url, "sqlite+pysqlite:///:memory:")


if __name__ == "__main__":
    unittest.main()
